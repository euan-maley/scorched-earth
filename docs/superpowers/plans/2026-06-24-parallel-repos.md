# Parallel Per-Repo Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run each armed repo's queue **concurrently** — one job per repo at a time, different repos at the same time — sharing one weekly budget honestly (no collective overspend).

**Architecture:** Replace the single-job engine (one `_busy` flag, one worker chain, charge-after) with **one drain worker per armed repo**. State goes per-repo: `_running` (dict), `_kill_events` (dict), `_workers` (set). A single global `EnvelopeTracker` plus **charge-at-pick reservation under the lock** lets concurrent workers share the budget without overspending — a worker reserves its job's cost atomically before running, so a second worker sees the reduced budget. `_running`/`state_json.running` becomes a **list** (multiple jobs in flight); the cockpit shows multiple RUNNING. `/run`, `/kill`, `/stop` are unchanged (already accept the right shapes).

**Tech Stack:** Python 3.8+ stdlib (`threading`). Touches `coa_serve.py` (Engine) and `cockpit_template.html`; tests.

## Global Constraints

- **Stdlib only.** Python 3.8 floor; no `match`; no runtime `X | Y` unions.
- **Never touch core.py, calibrate.py, statusline.py.**
- **One job per repo at a time; different repos concurrent.** Concurrency = number of armed repos with eligible affordable work. No global one-at-a-time cap.
- **Shared budget via charge-at-pick reservation.** ONE global `EnvelopeTracker`. A worker, **under the lock**, computes `available`, picks its repo's next eligible job, and **charges (reserves) `est_windows` before releasing the lock** — so concurrent workers can't collectively overspend. No refund on any outcome (the tokens were spent). **This changes accounting: killed/failed jobs are now charged** (they consumed real tokens) — more honest than the old charge-only-pass/fail. `rr.spent_estimated` per repo accumulates that repo's reserved windows.
- **Per-repo state:** `_running` (dict repo→{"repo","id"}), `_kill_events` (dict repo→Event), `_workers` (set of repos with a live worker). `_busy`(flag), `_active`(list), `_kill_event`(single), `_tracker`(global, kept) — remove the single-job ones. `_results` (dict repo→RunResult) kept.
- **`state_json` `running` is a LIST** `[{"repo","id"}, ...]`; `busy` = `bool(running)`.
- **Threading:** single `self._lock` guards all shared state; `run_one` runs OUTSIDE the lock (so workers run concurrently); the kill thread-local `runner._kill_ctx.event` is set/cleared per worker thread (thread-local → each worker's execute_job sees its own kill event); lock never held across `run_one` or nested → no deadlock.
- **`run(repos)` / `queue(repo,id)`** each spawn (or reuse) a daemon worker per repo via `_ensure_worker` (don't double-spawn a repo; don't spawn while stopped). `stop()` halts ALL workers. `kill(repo,id)` targets that repo's in-flight job.
- **Security/server unchanged:** `/run` (repos list, validated), `/kill {repo,id}`, `/stop` already exist and work with the new engine.
- **Tests** in `tests/test_cockpit.py` — the existing single-job engine tests are rewritten for the parallel model (concurrency proof, shared-budget reservation cap, per-repo kill, stop-all). Keep all four suites green.

---

### Task 1: Parallel engine (per-repo workers + shared-budget reservation)

**Files:**
- Modify: `src/scorched_earth/coa_serve.py` (Engine: `__init__`, `run`, `queue`, `unqueue`, `reorder`, `stop`, `kill`, `state_json`; replace `advance` with `_ensure_worker` + `_drain_repo`)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- `run(repos)` (list or string) → ensure+spawn a worker per repo; `queue(repo,id)` enqueues + ensures a worker; `kill(repo,id)`; `stop()`; `state_json()` with `running` as a list.
- Internal: `_ensure_worker(repo) -> bool`; `_drain_repo(repo)` (the per-repo loop).

- [ ] **Step 1: Write the failing tests**

The existing cockpit engine-test block (Task 5 area + the multi-repo block) asserts single-job/sequential behavior that no longer holds. **Replace the multi-repo block** (the `_mr_*` / `_bg_*` sweep tests added by the previous feature) and the busy-guard concurrency test with the parallel tests below; keep the single-repo drain/stop/over-budget/kill tests (they still hold — one worker for one repo). Append to `tests/test_cockpit.py`:

```python
# --- parallel per-repo execution -------------------------------------------------
import threading as _pth, time as _ptime  # noqa: E402
# two repos run CONCURRENTLY (both jobs in flight at once)
_pgate = _pth.Event()
def _par_exec(repo, job, roe):
    _pgate.wait(3)                                   # hold each job until the test releases
    return ("pass", None, "ok")
_pA = _mk_repo([Job(id="pa", repo=".", title="PA", type="test", est_windows=0.5, value=5, depth=3)])
_pB = _mk_repo([Job(id="pb", repo=".", title="PB", type="test", est_windows=0.5, value=5, depth=3)])
_par = Engine([_pA, _pB], execute=_par_exec, load_state=lambda: _STATE, now=lambda: 1)  # 2.5 windows
_par.run([_pA, _pB])
_end = _ptime.time() + 3
while _ptime.time() < _end and len(_par.state_json()["running"]) < 2:
    _ptime.sleep(0.02)
check("two armed repos run CONCURRENTLY (2 jobs in flight at once)",
      len(_par.state_json()["running"]) == 2)
_pgate.set()
_end = _ptime.time() + 3
while _ptime.time() < _end and _par.state_json()["busy"]:
    _ptime.sleep(0.02)
check("both repos drain after release (queues empty, idle)",
      _par.state_json()["busy"] is False and _io.read_queue(_pA) == [] and _io.read_queue(_pB) == [])

# shared budget via reservation: 2 repos x 3 jobs @1.0, 2.5 windows -> only 2 run total
_sb_ran = []
def _sb_exec(repo, job, roe):
    _sb_ran.append(job.id); return ("pass", None, "ok")
_sbA = _mk_repo([Job(id="A"+str(i), repo=".", title="x", type="test", est_windows=1.0, value=5, depth=5) for i in range(3)])
_sbB = _mk_repo([Job(id="B"+str(i), repo=".", title="x", type="test", est_windows=1.0, value=5, depth=5) for i in range(3)])
_sb = Engine([_sbA, _sbB], execute=_sb_exec, load_state=lambda: _STATE, now=lambda: 1)
_sb.run([_sbA, _sbB])
_end = _ptime.time() + 3
while _ptime.time() < _end and _sb.state_json()["busy"]:
    _ptime.sleep(0.02)
check("shared budget caps the WHOLE parallel run (2 of 6 jobs, not 3-per-repo)", len(_sb_ran) == 2)

# per-repo kill targets one repo's in-flight job; the other keeps running
_kgate = _pth.Event(); _kstarted = _pth.Event()
def _k_exec(repo, job, roe):
    ev = getattr(_k2runner._kill_ctx, "event", None) if False else getattr(__import__("scorched_earth.runner", fromlist=["x"])._kill_ctx, "event", None)
    _kstarted.set()
    if ev is not None and ev.wait(3):
        return ("killed", None, "killed")
    _kgate.wait(3)
    return ("pass", None, "ok")
_kA = _mk_repo([Job(id="ka", repo=".", title="x", type="test", est_windows=0.5, value=5, depth=3)])
_kB = _mk_repo([Job(id="kb", repo=".", title="x", type="test", est_windows=0.5, value=5, depth=3)])
_keng = Engine([_kA, _kB], execute=_k_exec, load_state=lambda: _STATE, now=lambda: 1)
_keng.run([_kA, _kB])
_end = _ptime.time() + 3
while _ptime.time() < _end and len(_keng.state_json()["running"]) < 2:
    _ptime.sleep(0.02)
_keng.kill(_kA, "ka")                                # kill only repo A's job
_kgate.set()                                         # let B finish
_end = _ptime.time() + 3
while _ptime.time() < _end and _keng.state_json()["busy"]:
    _ptime.sleep(0.02)
check("per-repo kill: killed repo's job returns to proposed, the other repo completes",
      "ka" in [j["id"] for j in _io.board_state(_kA)["proposed"]]
      and "kb" in [j["id"] for j in _io.board_state(_kB)["finished"]])
```

(Use the simpler kill-event lookup — replace the `_k_exec` first line with: `import scorched_earth.runner as _krun` at the top of the block and `ev = getattr(_krun._kill_ctx, "event", None)`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `state_json()["running"]` is not a list / no concurrency (the single-job engine never has 2 running).

- [ ] **Step 3: Implement the parallel Engine**

Ensure `from .roe import DEFAULT_ROE` is imported. Rewrite the Engine's state + methods:

In `__init__`, replace the per-job fields with per-repo:

```python
        self._lock = threading.Lock()
        self._stop = False
        self._tracker = None                       # one global shared-budget EnvelopeTracker
        self._running = {}                         # repo -> {"repo","id"} (one in-flight job per repo)
        self._kill_events = {}                     # repo -> threading.Event
        self._workers = set()                      # repos with a live drain worker
        self._results = {}                         # repo -> RunResult
```

Replace `run`, `queue`, `unqueue`, `reorder`, `stop`, `kill`, `state_json`, and the whole `advance` with:

```python
    def _ensure_worker(self, repo):
        """Register a worker for repo if none is live and we're not stopped. Returns True if the
        CALLER should spawn the thread (registration happened here)."""
        with self._lock:
            if self._stop or repo in self._workers:
                return False
            self._workers.add(repo)
            return True

    def run(self, repos):
        if isinstance(repos, str):
            repos = [repos]
        repos = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        with self._lock:
            self._stop = False
        for rp in repos:
            if self._ensure_worker(rp):
                threading.Thread(target=self._drain_repo, args=(rp,), daemon=True).start()

    def queue(self, repo, job_id):
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            with self._lock:
                coa_io.enqueue(repo, [jobs[job_id]])
        rp = os.path.realpath(os.path.expanduser(repo))
        self._broadcast()
        if self._ensure_worker(rp):                # a dragged-in card starts/continues this repo's worker
            threading.Thread(target=self._drain_repo, args=(rp,), daemon=True).start()

    def unqueue(self, repo, job_id):
        with self._lock:
            coa_io.unqueue(repo, job_id)
        self._broadcast()

    def reorder(self, repo, ids):
        with self._lock:
            coa_io.reorder(repo, ids)
        self._broadcast()

    def stop(self):
        with self._lock:
            self._stop = True                      # halts every worker after its current job

    def kill(self, repo, job_id):
        target = os.path.realpath(os.path.expanduser(repo))
        with self._lock:
            r = self._running.get(target)
            ke = self._kill_events.get(target)
            if r and r.get("id") == job_id and ke is not None:
                ke.set()

    def state_json(self):
        with self._lock:
            running = [dict(v) for v in self._running.values()]
        return {"repos": [coa_io.board_state(r) for r in self.repos],
                "running": running, "busy": bool(running)}

    def _drain_repo(self, repo):
        while True:
            with self._lock:
                if self._stop:
                    self._workers.discard(repo)
                    done = True
                else:
                    if self._tracker is None:
                        self._tracker = runner.EnvelopeTracker(DEFAULT_ROE)   # global shared budget
                    avail = self._tracker.available(self._load_state(), self._now())
                    roe = coa_io.load_roe(repo)
                    job = None if avail is None else runner.pick_next(coa_io.read_queue(repo), avail, roe)
                    if job is None:
                        self._workers.discard(repo)                            # this repo: nothing to do
                        done = True
                    else:
                        done = False
                        self._tracker.charge(job.est_windows)                  # RESERVE under the lock
                        self._running[repo] = {"repo": repo, "id": job.id}
                        ke = threading.Event()
                        self._kill_events[repo] = ke
                        coa_io.unqueue(repo, job.id)
                        rr = self._results.get(repo)
                        if rr is None:
                            rr = runner.RunResult(
                                generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                                state="running", repo=repo, verdict="unknown", note="",
                                available_windows=avail, spent_estimated=0.0)
                            self._results[repo] = rr
                        rr.spent_estimated = rr.spent_estimated + job.est_windows
                        seq = len(rr.jobs) + 1
            self._broadcast()
            if done:
                return

            runner._kill_ctx.event = ke              # per-worker-thread kill handle (thread-local)
            try:
                oc = runner.run_one(repo, job, roe, repo, seq, execute=self._execute)
            finally:
                runner._kill_ctx.event = None

            with self._lock:
                if oc.outcome in ("pass", "fail"):
                    rr.jobs.append(oc)
                    self._persist(repo, rr)          # killed: not appended (board -> proposed); budget already reserved
                self._running.pop(repo, None)
                self._kill_events.pop(repo, None)
                if self._stop:
                    self._workers.discard(repo)
                    done = True
            self._broadcast()
            if done:
                return
            # loop: drain the next job in THIS repo
```

(`_persist` is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py && python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: all green. Single-repo tests (drain order, stop, kill, over-budget) still pass — one worker for one repo behaves as before, plus charge-at-pick (which only changes killed/failed accounting; the single-repo drain tests use passing jobs, so spend is identical). Report the actual cockpit count.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(parallel): per-repo concurrent workers + shared-budget reservation (one job per repo)"
```

---

### Task 2: Cockpit — show multiple RUNNING (running is now a list)

**Files:**
- Modify: `src/scorched_earth/cockpit_template.html`
- Test: `tests/test_cockpit.py`

**Interfaces:** `state.running` is now an array `[{repo,id}, ...]`. Update every reader: per-repo RUNNING column finds its own entry; the active-repo tab marker uses `.some()`; the header "NOW RUNNING" shows the count / parallel state; `busy` is unchanged (bool).

- [ ] **Step 1: Write the failing test**

Append a render-check to `tests/test_cockpit.py`:

```python
# cockpit renders running as a list (multiple in-flight)
_hp = render_cockpit("tk", {"repos": [{"repo": "/r/a", "name": "a", "proposed": [], "queued": [], "finished": []},
                                      {"repo": "/r/b", "name": "b", "proposed": [], "queued": [], "finished": []}],
                            "running": [{"repo": "/r/a", "id": "j1"}, {"repo": "/r/b", "id": "j2"}],
                            "busy": True}).decode("utf-8")
check("cockpit handles a running LIST (renders without error, references running as array)",
      "__COCKPIT_" not in _hp and "running" in _hp.lower())
```

- [ ] **Step 2: Run test to verify it fails (or the template mishandles a list)**

Run: `python3 tests/test_cockpit.py`
Expected: the render-check passes only after the template treats `state.running` as a list everywhere (some current reads assume `{repo,id}|null`). If it already renders without throwing, tighten by also asserting the parallel header wording you add (Step 3) is present.

- [ ] **Step 3: Update the template's running readers**

In `cockpit_template.html`, change every `state.running` usage to treat it as an array:
- **`renderRunning(repo)`** (and wherever the RUNNING column is built): replace `state.running && state.running.repo === repo.repo` with finding this repo's entry: `const here = (state.running||[]).find(x=>x.repo===repo.repo);` and use `here` (its `id`) for the running card; show empty if none.
- **`renderTabs`** active-repo marker: `const isRunning = (state.running||[]).some(x=>x.repo===r.repo);` (multiple tabs can show RUNNING at once).
- **`renderHeader`** NOW RUNNING readout: use the list — e.g. `const R = state.running||[];` then if `R.length===1` show `NOW RUNNING ▶ <repo>/<id>`, if `R.length>1` show `<N> RUNNING IN PARALLEL · <repo>, <repo>…`, else the idle subtitle. `busy` stays `state.busy`.
- **`renderStatus`** / budget readout: if it reads `state.running.repo`, switch to the list (sum/iterate as needed; a per-repo status can use the active repo's entry via `find`).
- Keep the injection tokens (`__COCKPIT_TOKEN__`/`__COCKPIT_JSON__`) appearing once each; no token string in any new comment. Self-contained.

- [ ] **Step 4: Run tests + render check**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py && python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: all green. Render check:
`python3 -c "import sys;sys.path.insert(0,'src');from scorched_earth.coa_serve import render_cockpit;h=render_cockpit('t',{'repos':[],'running':[],'busy':False}).decode();assert '__COCKPIT_' not in h"`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/cockpit_template.html tests/test_cockpit.py
git commit -m "feat(parallel): cockpit shows multiple RUNNING (running is a list)"
```

---

## Self-Review

**1. Coverage:** per-repo concurrent workers (Task 1 `_drain_repo` + `run`/`queue` spawn); shared budget reservation (charge-at-pick under lock, tested 2-of-6); per-repo running/kill/stop (Task 1); running-as-list state (Task 1) + multi-RUNNING display (Task 2); `/run`/`/kill`/`/stop` unchanged (already correct shapes). ✓
**2. Placeholders:** none. Engine code complete; template edits described with exact reader sites.
**3. Consistency:** `_running`/`_kill_events`/`_workers` dicts/set, `_tracker` global, `_drain_repo`/`_ensure_worker`, `state_json.running` list — consistent across tasks. Charge-at-pick reservation is the one budget-semantics change (killed/failed now charged) — flagged in Global Constraints.
**Concurrency note for the reviewer:** the single `_lock` guards every shared-state read/write; `run_one` runs outside it (so workers truly overlap); reservation (`_tracker.charge`) happens under the lock at pick time so two workers can't overspend; the kill thread-local is per worker thread. No lock is ever held across `run_one` or nested — no deadlock.
