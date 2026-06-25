# COA Kill-a-Running-Job (Phase 2c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a **Kill** button to the cockpit's running card — abort the running `claude -p`, always discard its work, return the card to Proposed, and continue to the next job.

**Architecture:** Make the running job killable: `execute_job` runs the claude step through a new `_run_killable` (Popen + SIGTERM→SIGKILL on a `threading.Event`). The event is handed to `execute_job` via a **thread-local** (`_kill_ctx`) set by the engine on the same worker thread `advance` runs on — so no `execute`/stub signature changes. The Engine tracks the running job's event, `kill(repo, id)` sets it, and a token-guarded `POST /kill` routes to it. Killed jobs are discarded (worktree + branch) and recorded `killed`; the existing `board_state` pass/fail filter returns the card to Proposed. Budget stays charged (no refund). `core.py`/statusline untouched.

**Tech Stack:** Python 3.8+ stdlib (`subprocess.Popen`, `threading`, `time`). Reuses Phase 2a `execute_job`/`run_one`/`_git`/`worktree_path`/`branch_name` and Phase 2b `Engine`/`make_server`.

## Global Constraints

- **Stdlib only.** Python 3.8 floor: `from __future__ import annotations`; no `match`; no runtime `X | Y` unions.
- **Never touch `core.py`, `calibrate.py`, `statusline.py`.**
- **Always discard the work on kill** (`git worktree remove --force` + `branch -D`). No keep option, no confirmation.
- **No budget refund.** The killed job's `est_windows` stays charged; it re-syncs to ground truth on the next snapshot (the existing `EnvelopeTracker` behavior).
- **Killed job → Proposed.** Record outcome `"killed"`; `board_state` already keeps only `pass`/`fail` in `finished`, so a killed job (in `jobs.json`, not queued) reappears in Proposed automatically. Do NOT change the `board_state` filter.
- **Security unchanged.** `POST /kill` is token-guarded (`X-Scorch-Token`), job-ids only (reads `repo`/`id`), repo validated against `engine.repos`. Never executes a body command.
- **Signatures stable.** Do NOT add a `kill_event` parameter to `execute`/`run_one`/the injected stubs — the kill event flows via the `runner._kill_ctx` thread-local. (`_run_killable` itself takes the event as a normal arg — it's the unit-tested primitive.)
- **Tests** extend `tests/test_runner.py` (killable primitive) and `tests/test_cockpit.py` (engine kill + server). The batch `scorch coa run` path has no kill event and must stay green.

---

### Task 1: The killable executor primitive

**Files:**
- Modify: `src/scorched_earth/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces:
  - `_kill_ctx` — a module-level `threading.local()`; `execute_job` reads `getattr(_kill_ctx, "event", None)`.
  - `_run_killable(cmd, cwd, kill_event, grace=3.0, poll=0.1) -> str` — `Popen` the command (stdout/stderr to `DEVNULL`); if `kill_event` is None, wait to completion and return `"done"`; else poll, and when the event is set, `terminate()` (then `kill()` after `grace`) and return `"killed"`; return `"done"` when the process exits on its own.
  - `_discard_worktree(root, job_id)` — `git worktree remove --force <wt>` then `git branch -D <branch>` via `_git`.
  - `execute_job` runs the claude step through `_run_killable`; on `"killed"` it calls `_discard_worktree` and returns `("killed", None, "killed by operator — work discarded.")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py` (before the final `print`):

```python
# --- Phase 2c: killable executor primitive ----------------------------------------
import threading as _kt, time as _ktime  # noqa: E402
from scorched_earth.runner import _run_killable  # noqa: E402

# a long child gets killed promptly when the event is set
_ev = _kt.Event()
_sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
_res = {}
def _go():
    _res["r"] = _run_killable(_sleeper, None, _ev, grace=2.0, poll=0.05)
_th = _kt.Thread(target=_go); _th.start()
_ktime.sleep(0.3)              # let it spawn
_ev.set()                      # request kill
_th.join(5)
check("_run_killable returns 'killed' when the event is set", _res.get("r") == "killed")
check("_run_killable actually terminated the child (thread finished)", not _th.is_alive())

# a fast child runs to completion -> 'done' (kill_event present but never set)
check("_run_killable returns 'done' when the process exits on its own",
      _run_killable([sys.executable, "-c", "pass"], None, _kt.Event(), poll=0.02) == "done")
# no kill_event -> waits to completion
check("_run_killable with no kill_event waits to completion",
      _run_killable([sys.executable, "-c", "pass"], None, None) == "done")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ImportError: cannot import name '_run_killable'`.

- [ ] **Step 3: Implement in `runner.py`**

Add to the imports at the top of `runner.py` (alongside the existing `import os`, `import subprocess`): `import threading` and `import time`.

Add near the other module-level helpers (e.g. just above `execute_job`):

```python
# Ambient handle to the currently-running job's kill Event, set by the cockpit Engine on the
# same worker thread execute_job runs on (so no execute/run_one signature change). None in the
# batch `scorch coa run` path.
_kill_ctx = threading.local()


def _run_killable(cmd, cwd, kill_event, grace=3.0, poll=0.1):
    """Run cmd; if kill_event is set, terminate (SIGTERM, then SIGKILL after `grace`) and return
    'killed'. Returns 'done' when the process exits on its own (or kill_event is None)."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if kill_event is None:
        p.wait()
        return "done"
    while p.poll() is None:
        if kill_event.is_set():
            p.terminate()
            try:
                p.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            return "killed"
        time.sleep(poll)
    return "done"


def _discard_worktree(root, job_id):
    """Always-discard: drop a killed job's worktree + branch (no keep option)."""
    _git(root, "worktree", "remove", "--force", worktree_path(root, job_id))
    _git(root, "branch", "-D", branch_name(job_id))
```

Then in `execute_job`, replace the claude step:

```python
        subprocess.run(build_claude_cmd(job, wt), cwd=wt,
                       capture_output=True, text=True)
```

with:

```python
        # Killable claude step: the cockpit Engine may set _kill_ctx.event for this job.
        if _run_killable(build_claude_cmd(job, wt), wt,
                         getattr(_kill_ctx, "event", None)) == "killed":
            _discard_worktree(root, job.id)        # always discard the partial work
            return "killed", None, "killed by operator — work discarded."
```

(Leave the rest of `execute_job` — `_diffstat`, gate — unchanged for the not-killed path.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — runner count +4. The existing runner suite stays green (the batch path passes `kill_event=None` implicitly via the thread-local default).

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_runner.py
git commit -m "feat(kill): killable executor primitive + discard-on-kill"
```

---

### Task 2: Engine `kill` + `POST /kill`

**Files:**
- Modify: `src/scorched_earth/coa_serve.py`
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Engine gains `self._kill_event` (None when idle). `advance` creates a `threading.Event` before executing, stores it on `self._kill_event` (under the lock) AND sets `runner._kill_ctx.event` on the worker thread before `run_one`, clearing both after (in a `finally`).
- `Engine.kill(self, repo, job_id)` — under the lock, if the running job matches `(realpath(repo), job_id)`, set `self._kill_event`.
- `POST /kill {repo, id}` — token-guarded, repo validated against `engine.repos` (the existing `/run` etc. block), started on a worker thread → `engine.kill(repo, id)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py` (before the final `print`), in/after the engine test block (where `Engine`, `_mk_repo`, `_STATE`, `_io`, `Job` are in scope):

```python
# --- Phase 2c: engine kill -------------------------------------------------------
import threading as _k2th, time as _k2time  # noqa: E402
import scorched_earth.runner as _k2runner  # noqa: E402

_k2_started = _k2th.Event()
def _exec_killable(repo, job, roe):
    # mimic a long job: block on the engine-provided kill event (thread-local), like execute_job
    ev = getattr(_k2runner._kill_ctx, "event", None)
    _k2_started.set()
    if ev is not None and ev.wait(3):
        return ("killed", None, "killed by operator — work discarded.")
    return ("pass", None, "ran to completion")
_rk = _mk_repo([Job(id="kill-me", repo=".", title="Kill me", type="test", est_windows=1.0, value=5),
                Job(id="next-up", repo=".", title="Next", type="test", est_windows=0.5, value=4)])
_engk = Engine([_rk], execute=_exec_killable, load_state=lambda: _STATE, now=lambda: 1)
_tk = _k2th.Thread(target=_engk.run, args=(_rk,), daemon=True); _tk.start()
_k2_started.wait(3)                                  # kill-me is now "running"
_engk.kill(_rk, "kill-me")                           # operator kills it
_tk.join(5)
_fin = [j["id"] for j in _io.board_state(_rk)["finished"]]
_prop = [j["id"] for j in _io.board_state(_rk)["proposed"]]
check("engine.kill ends the running job (not left busy)", _engk.state_json()["busy"] is False)
check("killed job is NOT in finished (pass/fail only)", "kill-me" not in _fin)
check("killed job returns to proposed (re-queueable)", "kill-me" in _prop)
check("after a kill the chain continues to the next job (next-up ran)", "next-up" in _fin)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `AttributeError: 'Engine' object has no attribute 'kill'`.

- [ ] **Step 3: Implement the Engine kill wiring in `coa_serve.py`**

Add `import scorched_earth.runner` is already present as `from . import runner`. In `Engine.__init__`, add alongside the other state:

```python
        self._kill_event = None
```

In `advance`, set up the kill event. In the first locked block, after `self._running = {...}` and creating `rr`, add `self._kill_event = threading.Event()` (under the lock). Capture it in a local `kill_event = self._kill_event`. Then wrap the execute so the thread-local is set and cleared:

```python
            self._running = {"repo": repo, "id": job.id}
            self._kill_event = threading.Event()
            kill_event = self._kill_event
            coa_io.unqueue(repo, job.id)
            # ... (rr create + seq, unchanged) ...
        self._broadcast()

        runner._kill_ctx.event = kill_event          # ambient handle for execute_job (this thread)
        try:
            oc = runner.run_one(repo, job, roe, repo, seq, execute=self._execute)
        finally:
            runner._kill_ctx.event = None

        with self._lock:
            # ... (charge / append / persist, unchanged) ...
            self._kill_event = None
            self._busy = False
            self._running = None
            stopped = self._stop
```

Add the `kill` method (next to `stop`):

```python
    def kill(self, repo, job_id):
        target = os.path.realpath(os.path.expanduser(repo))
        with self._lock:
            if self._running and self._running == {"repo": target, "id": job_id} \
                    and self._kill_event is not None:
                self._kill_event.set()
```

- [ ] **Step 4: Add the `POST /kill` endpoint**

In `make_server`'s `do_POST`, add `/kill` to the repo-validated set and route it like `/run` (worker thread):

```python
            if path in ("/queue", "/unqueue", "/reorder", "/run", "/kill"):
                if os.path.realpath(os.path.expanduser(repo or "")) not in engine.repos:
                    self._send(400, b'{"error":"unknown repo"}'); return
```

and in the dispatch:

```python
                elif path == "/kill":
                    threading.Thread(target=engine.kill,
                                     args=(repo, body.get("id")), daemon=True).start()
```

- [ ] **Step 5: Add the server test**

Append to the Task 6 server-test area of `tests/test_cockpit.py` (where `_eng6`/`make_server`/`_post`/`_TOKEN` exist) — or a small self-contained block:

```python
# /kill: token-guarded, repo-validated, job-ids only
_rkill = _mk_repo([Job(id="z", repo=".", title="Z", type="test", est_windows=1.0, value=5)])
_engkill = Engine([_rkill], execute=lambda *a: ("pass", None, "ok"), load_state=lambda: _STATE, now=lambda: 1)
_hk, _pk = make_server(_engkill, "k-tok")
import threading as _k3
_k3.Thread(target=_hk.serve_forever, daemon=True).start()
def _kpost(body, token):
    c = http.client.HTTPConnection("127.0.0.1", _pk, timeout=3)
    h = {"Content-Type": "application/json"}
    if token: h["X-Scorch-Token"] = token
    c.request("POST", "/kill", json.dumps(body), h); r = c.getresponse(); r.read(); c.close(); return r.status
check("POST /kill without token is 403", _kpost({"repo": _rkill, "id": "z"}, None) == 403)
check("POST /kill with unknown repo is 400", _kpost({"repo": tempfile.mkdtemp(), "id": "z"}, "k-tok") == 400)
check("POST /kill with token + known repo is 200 (no-op when nothing running)",
      _kpost({"repo": _rkill, "id": "z"}, "k-tok") == 200)
_hk.shutdown()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py`
Expected: PASS — cockpit count +7. Engine kill ends the job, chain continues, killed job back in proposed; `/kill` token/repo guards hold.

- [ ] **Step 7: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(kill): Engine.kill + POST /kill (token-guarded, job-ids only)"
```

---

### Task 3: Kill button in the cockpit + docs

**Files:**
- Modify: `src/scorched_earth/cockpit_template.html`
- Modify: `commands/coa.md`
- Test: `tests/test_cockpit.py`

**Interfaces:** the running card renders a **KILL** button → `post("/kill", {repo, id})`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py` (render check — the template must wire a `/kill` POST):

```python
# --- Phase 2c: cockpit Kill button wiring -----------------------------------------
_kh = render_cockpit("tk", {"repos": [], "running": None, "busy": False}).decode("utf-8")
check("cockpit template wires a /kill POST", '"/kill"' in _kh or "/kill" in _kh)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — the template has no `/kill` wiring yet.

- [ ] **Step 3: Add the Kill button to the running card**

In `cockpit_template.html`, in `updateCard` where `kind === "running"` (the branch that appends the `WORKING…` badge), also append a Kill button, and add a click handler that POSTs `/kill`. In the running-card foot:

```javascript
    } else if(kind==="running"){
      foot.appendChild(html('<span class="working"><span class="dot ember" style="background:#ff6a1f"></span>WORKING…</span>'));
      if(job.est_windows!=null) foot.appendChild(html('<span class="cwin" style="margin-left:auto">EST <b>~'+fmt(job.est_windows)+'w</b></span>'));
      const kb = html('<button class="btn btn--stop" data-kill="'+esc(job.id)+'" style="margin-left:auto;padding:4px 11px 3px;font-size:11px">✕ KILL</button>');
      foot.appendChild(kb);
    }
```

And add a delegated click handler near the other engine-control listeners (job-id only, token-headed via the existing `post`):

```javascript
  root.addEventListener("click", e=>{
    const k = e.target.closest("[data-kill]"); if(!k) return;
    const repo = activeRepoObj(); if(!repo) return;
    post("/kill", { repo: repo.repo, id: k.getAttribute("data-kill") });
  });
```

(Keep the literal token strings out of any new comment — render_cockpit does a blind replace of `__COCKPIT_TOKEN__`/`__COCKPIT_JSON__`.)

- [ ] **Step 4: Document in `commands/coa.md`**

In the "Live cockpit (Phase 2b)" section, add one sentence: a running job can be **killed** from its card — this aborts it, **discards its work** (you lose the partial output and the tokens already spent), and returns the card to Proposed; the next queued job takes over.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py`
Expected: PASS — cockpit count +1.

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/cockpit_template.html commands/coa.md tests/test_cockpit.py
git commit -m "feat(kill): KILL button on the running card + docs"
```

---

## Self-Review

**1. Spec coverage:**
- Kill aborts the running `claude -p` → Task 1 (`_run_killable` + execute_job). ✓
- Always discard work → Task 1 (`_discard_worktree`, no keep path). ✓
- No signature churn (thread-local) → Task 1 (`_kill_ctx`), Task 2 (engine sets it). ✓
- Engine tracks event + `kill` + chain continues → Task 2. ✓
- `POST /kill` token-guarded, repo-validated, job-ids only → Task 2 (Step 4). ✓
- Killed job → Proposed (no `board_state` change) → Task 2 test asserts it. ✓
- No budget refund → Task 2 (charge stays; nothing refunds). ✓
- Kill button on running card → Task 3. ✓
- Batch `scorch coa run` unchanged (kill_event None) → Task 1 (default), existing suite stays green. ✓

**2. Placeholder scan:** none. The `_run_killable` no-kill branch and the thread-local default keep the batch path identical.

**3. Type/name consistency:** `_run_killable(cmd, cwd, kill_event, grace, poll) -> str`, `_kill_ctx.event`, `_discard_worktree(root, job_id)`, `Engine.kill(repo, job_id)`, `self._kill_event`, `POST /kill {repo,id}` — consistent across Tasks 1–3. `engine.kill` matches the `do_POST` dispatch and the test calls.
