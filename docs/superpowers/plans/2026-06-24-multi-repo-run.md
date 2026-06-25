# Multi-Repo Run (checkboxes / Run-all, one job at a time) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the cockpit drain **multiple repos in one run** — still exactly one job at a time, globally, sharing one budget — and show it (the active-repo tab marker hops repo→repo). Repo checkboxes choose which repos are in the run; all-checked = "Run all."

**Architecture:** The engine's budget accounting goes from **per-repo trackers** to **one global `EnvelopeTracker`** (budget is one weekly pool, so a single tracker is both simpler and the only honest model — per-repo trackers each re-derive the full budget and over-spend). `run(repos)` sets an **active repo set**; the `advance` chain picks the next eligible affordable job **across the active set in order**, one at a time. Per-repo `RunResult`s are kept (each repo still gets its own AAR). The server's `/run` accepts a `repos` list; the cockpit adds a checkbox per repo (default checked) and Run posts the checked set.

**Tech Stack:** Python 3.8+ stdlib. Touches `coa_serve.py` (Engine + server), `cockpit_template.html`, tests.

## Global Constraints

- **Stdlib only.** Python 3.8 floor; no `match`; no runtime `X | Y` unions.
- **Never touch core.py, calibrate.py, statusline.py.**
- **One job at a time, globally** — the single `_busy` flag and global tracker are unchanged in spirit. Multi-repo means the chain sweeps repos sequentially, never concurrently.
- **One global budget tracker.** Replace `self._trackers` (repo→tracker) with a single `self._tracker` (an `EnvelopeTracker(DEFAULT_ROE)` — the global weekly budget is the cap; **per-repo total `max_windows` caps no longer apply in a multi-repo run** — noted gap; the per-job `unattended_types`/`per_job_max_windows` leash still applies via `pick_next` with each repo's own ROE).
- **Per-repo RunResult kept.** `self._results` stays repo→RunResult; each repo's `rr.spent_estimated` accumulates **that repo's** job windows locally (for its AAR), while `self._tracker` governs the shared budget gate.
- **Threading unchanged:** single lock guards shared state; `run_one` runs OUTSIDE the lock; the kill thread-local + four runaway guards are preserved.
- **Backward-compat:** `run(repos)` accepts a single repo string (normalizes to `[repo]`); `/run` accepts `{repo}` (single) or `{repos: [...]}` (list). Existing single-repo engine tests must stay green.
- **Security unchanged:** `/run` token-guarded, every repo validated against `engine.repos`, job-ids only.
- **Tests** extend `tests/test_cockpit.py`. Keep all four suites green.

---

### Task 1: Engine — global tracker + active-repo set + cross-repo advance

**Files:**
- Modify: `src/scorched_earth/coa_serve.py` (Engine: `__init__`, `run`, `queue`, `advance`)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- `Engine.run(repos)` accepts a list (or single string); sets `self._active` (realpath'd) and clears stop, then advances.
- `advance(self)` (no repo arg) drains across `self._active` using the one global `self._tracker`.
- `self._tracker` (single `EnvelopeTracker(DEFAULT_ROE)`, lazy); `self._active` (list).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py` (before the final `print`):

```python
# --- multi-repo run: one job at a time across repos, shared budget --------------
from scorched_earth.roe import DEFAULT_ROE as _DR  # noqa: E402
_mr_ran = []
def _mr_exec(repo, job, roe):
    _mr_ran.append((os.path.basename(repo), job.id))
    return ("pass", None, "ok")
_mrA = _mk_repo([Job(id="a1", repo=".", title="A1", type="test", est_windows=0.5, value=5),
                 Job(id="a2", repo=".", title="A2", type="test", est_windows=0.5, value=4)])
_mrB = _mk_repo([Job(id="b1", repo=".", title="B1", type="test", est_windows=0.5, value=5)])
_mrC = _mk_repo([Job(id="c1", repo=".", title="C1", type="test", est_windows=0.5, value=5)])
_mr_eng = Engine([_mrA, _mrB, _mrC], execute=_mr_exec, load_state=lambda: _STATE, now=lambda: 1)
_mr_eng.run([_mrA, _mrB, _mrC])
check("multi-repo run drains all checked repos (sweeps A then B then C)",
      [r for r, _ in _mr_ran] == ["A", "A", "B", "C"][:len(_mr_ran)] and
      sorted(j for _, j in _mr_ran) == ["a1", "a2", "b1", "c1"])
check("multi-repo run leaves every queue empty",
      _io.read_queue(_mrA) == [] and _io.read_queue(_mrB) == [] and _io.read_queue(_mrC) == [])
check("multi-repo run ends idle", _mr_eng.state_json()["busy"] is False)

# shared global budget: 2.5 windows, 6 jobs @1.0 across two repos -> only ~2 run, rest wait
_mr_ran2 = []
def _mr_exec2(repo, job, roe):
    _mr_ran2.append(job.id); return ("pass", None, "ok")
_bgA = _mk_repo([Job(id="A"+str(i), repo=".", title="x", type="test", est_windows=1.0, value=5) for i in range(3)])
_bgB = _mk_repo([Job(id="B"+str(i), repo=".", title="x", type="test", est_windows=1.0, value=5) for i in range(3)])
_bg_eng = Engine([_bgA, _bgB], execute=_mr_exec2, load_state=lambda: _STATE, now=lambda: 1)  # windows_left 2.5
_bg_eng.run([_bgA, _bgB])
check("shared budget caps the whole run (2 jobs of 6 fit 2.5 windows, not 2-per-repo)",
      len(_mr_ran2) == 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `run([...])` with a list / cross-repo sweep not supported; the shared-budget check fails (per-repo trackers would run 2 per repo = 4).

- [ ] **Step 3: Implement the Engine changes**

Add near the top imports of `coa_serve.py`: `from .roe import DEFAULT_ROE`.

In `__init__`, replace `self._trackers = {}` with:

```python
        self._tracker = None                       # one global EnvelopeTracker (budget is one pool)
        self._active = []                          # repos armed for the current run
```

Replace `run`:

```python
    def run(self, repos):
        if isinstance(repos, str):
            repos = [repos]
        active = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        with self._lock:
            self._active = active
            self._stop = False                     # Run = go/resume
        self.advance()
```

In `queue`, after the enqueue + before `self.advance(...)`, make the dragged repo join the active set and call the no-arg advance:

```python
    def queue(self, repo, job_id):
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            with self._lock:
                coa_io.enqueue(repo, [jobs[job_id]])
        rp = os.path.realpath(os.path.expanduser(repo))
        with self._lock:
            if rp not in self._active:
                self._active = self._active + [rp]   # a dragged-in card joins the active run
        self._broadcast()
        self.advance()
```

Replace `advance` with the cross-repo version (no `repo` arg):

```python
    def advance(self):
        while True:
            with self._lock:
                if self._busy or self._stop:
                    return
                if self._tracker is None:
                    self._tracker = runner.EnvelopeTracker(DEFAULT_ROE)  # global budget, no per-repo cap
                avail = self._tracker.available(self._load_state(), self._now())
                if avail is None:
                    return                          # stale/absent snapshot -> refuse the run
                picked = None
                for rp in self._active:             # first active repo (in order) with eligible work
                    roe = coa_io.load_roe(rp)
                    job = runner.pick_next(coa_io.read_queue(rp), avail, roe)
                    if job is not None:
                        picked = (rp, roe, job)
                        break
                if picked is None:
                    return                          # idle: nothing eligible/affordable anywhere
                rp, roe, job = picked
                self._busy = True
                self._running = {"repo": rp, "id": job.id}
                self._kill_event = threading.Event()
                kill_event = self._kill_event
                coa_io.unqueue(rp, job.id)          # remove-on-pick
                rr = self._results.get(rp)
                if rr is None:
                    rr = runner.RunResult(
                        generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                        state="running", repo=rp, verdict="unknown", note="",
                        available_windows=avail, spent_estimated=0.0)
                    self._results[rp] = rr
                seq = len(rr.jobs) + 1
            self._broadcast()

            runner._kill_ctx.event = kill_event
            try:
                oc = runner.run_one(rp, job, roe, rp, seq, execute=self._execute)
            finally:
                runner._kill_ctx.event = None

            with self._lock:
                if oc.outcome in ("pass", "fail"):
                    self._tracker.charge(job.est_windows)           # global budget
                    rr.jobs.append(oc)
                    rr.spent_estimated = rr.spent_estimated + job.est_windows   # this repo's own spend
                    self._persist(rp, rr)
                self._kill_event = None
                self._busy = False
                self._running = None
                stopped = self._stop
            self._broadcast()

            if stopped:
                return
```

(Note: `kill(repo, job_id)` and `stop()` and `state_json()` are unchanged. The single-repo `run("path")` still works — it normalizes to a one-element active set, and with one repo the global tracker behaves exactly as the old per-repo tracker did.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py && python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: all green. The EXISTING engine tests (single-repo `run(_r)`, busy-guard, stop, kill) must stay green — `run` normalizes a string and the global tracker matches the old single-repo behavior. Report the actual cockpit count.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(multi-repo): global budget tracker + cross-repo advance (one job at a time)"
```

---

### Task 2: Server — `/run` accepts a repos list

**Files:**
- Modify: `src/scorched_earth/coa_serve.py` (`make_server` `do_POST`)
- Test: `tests/test_cockpit.py`

**Interfaces:** `POST /run` body may be `{repo: "..."}` (single) or `{repos: [...]}` (list). Every repo validated against `engine.repos`; calls `engine.run(<list>)` on a worker thread.

- [ ] **Step 1: Write the failing test**

Append a server test to `tests/test_cockpit.py` (a self-contained block with its own server, mirroring the existing `/kill` server test):

```python
# /run accepts a repos list; every repo validated
_rrA = _mk_repo([Job(id="z", repo=".", title="Z", type="test", est_windows=0.5, value=5)])
_rrB = _mk_repo([Job(id="y", repo=".", title="Y", type="test", est_windows=0.5, value=5)])
_run_eng = Engine([_rrA, _rrB], execute=lambda *a: ("pass", None, "ok"),
                  load_state=lambda: _STATE, now=lambda: 1)
_run_eng.stop()                                   # paused so the POST just validates/dispatches
_hr, _pr = make_server(_run_eng, "r-tok")
import threading as _rth
_rth.Thread(target=_hr.serve_forever, daemon=True).start()
def _rpost(body):
    c = http.client.HTTPConnection("127.0.0.1", _pr, timeout=3)
    c.request("POST", "/run", json.dumps(body), {"Content-Type": "application/json", "X-Scorch-Token": "r-tok"})
    r = c.getresponse(); r.read(); c.close(); return r.status
check("POST /run with a repos list is accepted (200)", _rpost({"repos": [_rrA, _rrB]}) == 200)
check("POST /run with an unknown repo in the list is 400",
      _rpost({"repos": [_rrA, tempfile.mkdtemp()]}) == 400)
check("POST /run with single {repo} still works (back-compat)", _rpost({"repo": _rrA}) == 200)
_hr.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `/run` doesn't validate/forward a `repos` list yet.

- [ ] **Step 3: Implement in `do_POST`**

The existing repo-validation block validates a single `repo` for `/run`. Generalize so `/run` validates each repo in the list (and still single `repo`). In `do_POST`, before the dispatch, compute the run repos and validate:

```python
            run_repos = None
            if path == "/run":
                run_repos = list(body.get("repos") or ([] if body.get("repo") is None else [body.get("repo")]))
                for _rp in run_repos:
                    if os.path.realpath(os.path.expanduser(_rp or "")) not in engine.repos:
                        self._send(400, b'{"error":"unknown repo"}'); return
```

Keep the existing `if path in ("/queue", "/unqueue", "/reorder"):` single-repo validation for those (drop `/run` from that set since it's handled above). Then dispatch `/run` with the list:

```python
                elif path == "/run":
                    threading.Thread(target=engine.run, args=(run_repos,), daemon=True).start()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py`
Expected: all green (the existing single-`{repo}` `/run` test still passes via the back-compat normalization).

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(multi-repo): /run accepts a repos list (token+repo guarded)"
```

---

### Task 3: Cockpit — repo checkboxes + Run-all

**Files:**
- Modify: `src/scorched_earth/cockpit_template.html`
- Test: `tests/test_cockpit.py`

**Interfaces:** each repo tab gets a checkbox (default checked = armed); the Run button posts `{repos: [...armed]}`.

- [ ] **Step 1: Write the failing test**

Append a render-check to `tests/test_cockpit.py`:

```python
# cockpit wires a repos-list run (Run-all over the armed checkboxes)
_hr3 = render_cockpit("tk", {"repos": [], "running": None, "busy": False}).decode("utf-8")
check("cockpit Run posts a repos list (armed checkboxes)", "repos" in _hr3 and "armed" in _hr3.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — the template has no armed-checkbox / repos-list wiring yet.

- [ ] **Step 3: Edit the cockpit template**

Add an `armed` Set in the cockpit JS (module scope near the other state): `let armed = null;` and, in `render()` / on first state, default it to all repo keys. In `renderTabs`, prepend a checkbox to each tab reflecting `armed.has(r.repo)`, toggling on change (and `stopPropagation` so it doesn't switch the active view). Change the Run button handler to post the armed set:

```javascript
  // armed repos (which repos a Run drains). Default: all.
  if(armed === null) armed = new Set(state.repos.map(r=>r.repo));
```
In `renderTabs`, inside the `forEach`, before the name span, add:
```javascript
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.className = "tab__arm"; cb.checked = armed.has(r.repo);
      cb.title = "include this repo in Run";
      cb.onclick = (ev)=>{ ev.stopPropagation(); if(cb.checked) armed.add(r.repo); else armed.delete(r.repo); };
      b.appendChild(cb);
```
(append `cb` first, then the existing name + count/running spans — adjust so the checkbox sits at the left of the tab.)

Change the Run click handler:
```javascript
  document.getElementById("btnRun").addEventListener("click", ()=>{
    if(armed === null) armed = new Set(state.repos.map(r=>r.repo));
    const repos = state.repos.map(r=>r.repo).filter(x=>armed.has(x));
    if(!repos.length) return;
    state.busy = true; renderHeader();
    post("/run", { repos: repos });
  });
```
Add a small CSS rule for `.tab__arm` (e.g. `accent-color:#ff6a1f;margin-right:4px;cursor:pointer`).
Keep the injection tokens (`__COCKPIT_TOKEN__`/`__COCKPIT_JSON__`) appearing once each; no token string in any new comment. Self-contained.

(When `state.repos.length <= 1` the tab strip is hidden, so a single-repo install just Runs that one repo — `armed` defaults to it.)

- [ ] **Step 4: Run tests + render check**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py && python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: all green. Render check:
`python3 -c "import sys;sys.path.insert(0,'src');from scorched_earth.coa_serve import render_cockpit;h=render_cockpit('t',{'repos':[],'running':None,'busy':False}).decode();assert '__COCKPIT_' not in h and 'tab__arm' in h"`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/cockpit_template.html tests/test_cockpit.py
git commit -m "feat(multi-repo): repo checkboxes + Run-all over the armed set"
```

---

## Self-Review

**1. Coverage:** global tracker + active set + cross-repo sweep (Task 1); /run repos list (Task 2); checkboxes + Run-all (Task 3); one-at-a-time preserved (single `_busy`); shared budget honest (single tracker, tested); single-repo back-compat (run normalizes string; /run accepts {repo}). ✓
**2. Placeholders:** none. Engine code complete; template edits described with anchors + JS.
**3. Consistency:** `self._tracker`/`self._active`, `run(repos)`, no-arg `advance()`, `/run {repos}`, `armed` Set — consistent across tasks. Per-repo RunResult retained; `rr.spent_estimated` is per-repo local while the global tracker gates budget.
**Known gap (intentional):** per-repo total `max_windows` ROE cap no longer applies in a multi-repo run (global budget is the cap); per-job leash still applies.
