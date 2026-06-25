# COA Budget Model + UX Revision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the COA's windows-until-weekly-reset budget gate with a soft current-window-headroom model: nothing is forfeited, the runner drains whatever you queue and halts only on a real `claude -p` usage-limit (or an optional cap); fold COA HTML generation into `scorch advise`; and wrap the COA pipeline behind one subagent.

**Architecture:** The Phase-1 weekly green-light (`windows_left`, `core.py`) is untouched. A NEW, separate number — `headroom` = unused capacity of the current 5-hour window — drives COA. `advisor.match` annotates every job `fits`/`over`/`blocked` instead of forfeiting. The cockpit shows headroom + an over-budget badge (cosmetic). The runner/cockpit drain ungated and halt on a usage-limit signal parsed from `claude -p --output-format stream-json` (the just-built `EnvelopeTracker`/charge-at-pick reservation retires; per-repo concurrency stays).

**Tech Stack:** Python 3.8+ stdlib only; the existing assert-counter test harness (`check(name, cond)`, no pytest); self-contained HTML templates filled via `__*_JSON__` token substitution.

## Global Constraints

- **Stdlib only.** Python 3.8 floor; no `match` statement; no runtime `X | Y` unions (use `Optional[...]`).
- **Never touch `core.py`, `calibrate.py`, `statusline.py`** — the weekly green-light / `windows_left` / sitrep stay exactly as-is.
- **Nothing is forfeited for budget.** Jobs are annotated `fits` / `over` (cosmetic) / `blocked` (ROE), never dropped for being too big.
- **Headroom = `max(0, (100 - five_hour_pct) / 100)`** (window-units, 0..1.0). `weekly_reserve_pct = max(0, 100 - seven_day_pct)` is shown as context only, never a gate. No `R` dependency.
- **Real-limit halt:** detect `"rate_limit"` in `claude -p --output-format stream-json` output. Exit code alone cannot distinguish a limit from a normal failure.
- **Optional caps default OFF** (`ROE.max_jobs`, `ROE.max_est_windows` both `None`).
- **Test harness:** match the existing style in `tests/test_advisor.py` / `tests/test_cockpit.py` — module-level `check(name, cond)` calls, run via `python3 tests/test_*.py`, no pytest. Keep all four suites green.
- The interpreter is `python3` (there is no `python`).

---

### Task 1: advisor — headroom helpers + annotate-not-forfeit `match`

**Files:**
- Modify: `src/scorched_earth/advisor.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Produces: `window_headroom(snapshot) -> Optional[float]`, `weekly_reserve_pct(snapshot) -> Optional[float]`, reshaped `COA` (fields: `queue`, `over_budget`, `blocked`, `headroom_windows`, `weekly_reserve_pct`, `fits_windows`, `note`), `match(headroom: float, jobs, roe, *, weekly_reserve_pct: float = 0.0) -> COA`.
- Consumed by: Tasks 2 (report), 4 (coa_serve), 6 (advise CLI).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_advisor.py` (after the existing advisor block):

```python
# --- headroom model (replaces the windows-until-reset envelope) ------------------
from scorched_earth import advisor as _adv  # noqa: E402
from scorched_earth.advisor import COA as _COA, match as _match  # noqa: E402
from scorched_earth.jobs import Job as _J  # noqa: E402

check("window_headroom = unused fraction of the current 5h window",
      abs(_adv.window_headroom({"five_hour_pct": 5}) - 0.95) < 1e-9)
check("window_headroom None when five_hour_pct missing",
      _adv.window_headroom({}) is None)
check("weekly_reserve_pct = 100 - seven_day_pct",
      _adv.weekly_reserve_pct({"seven_day_pct": 81}) == 19)

# annotate, never forfeit: 3 jobs @0.5w, headroom 0.6 -> 1 fits, 2 over, 0 dropped
_mj = [_J(id="a", repo=".", title="A", type="docs", est_windows=0.5, value=9, depth=3),
       _J(id="b", repo=".", title="B", type="docs", est_windows=0.5, value=8, depth=3),
       _J(id="c", repo=".", title="C", type="docs", est_windows=0.5, value=7, depth=3)]
from scorched_earth.roe import ROE as _ROE  # noqa: E402
_coa = _match(0.6, _mj, _ROE())
check("match keeps every eligible job (nothing forfeited)",
      len(_coa.queue) + len(_coa.over_budget) == 3)
check("match: only the highest-value job fits 0.6 windows",
      [j.id for j in _coa.queue] == ["a"] and [j.id for j in _coa.over_budget] == ["b", "c"])
check("match exposes headroom on the COA", _coa.headroom_windows == 0.6)

# ROE-disallowed types go to `blocked`, not `over_budget`
_coa2 = _match(5.0, _mj, _ROE(allowed_types=["test"]))
check("match routes ROE-disallowed jobs to blocked (distinct from over_budget)",
      len(_coa2.blocked) == 3 and _coa2.queue == [] and _coa2.over_budget == [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_advisor.py`
Expected: FAIL — `window_headroom`/`weekly_reserve_pct` undefined; `COA` has no `over_budget`/`blocked`/`headroom_windows`.

- [ ] **Step 3: Implement** — replace the `COA` dataclass and `match`, add the two helpers, in `src/scorched_earth/advisor.py`:

```python
from typing import List, Optional


@dataclass
class COA:
    queue: List[Job] = field(default_factory=list)          # fits within headroom, run order
    over_budget: List[Job] = field(default_factory=list)    # eligible but beyond headroom — queue anyway
    blocked: List[Job] = field(default_factory=list)        # ROE-disallowed (type / per-job cap)
    headroom_windows: float = 0.0                           # current-window headroom used for the split
    weekly_reserve_pct: float = 0.0                         # context only
    fits_windows: float = 0.0                               # sum of queue est_windows
    note: str = ""


def window_headroom(snapshot) -> Optional[float]:
    """Unused capacity of the CURRENT 5-hour window, in window-units (0..1.0). This is the COA
    execution headroom — NOT windows-until-weekly-reset. None when five_hour_pct is absent."""
    five = (snapshot or {}).get("five_hour_pct")
    if five is None:
        return None
    return max(0.0, (100.0 - float(five)) / 100.0)


def weekly_reserve_pct(snapshot) -> Optional[float]:
    """Weekly budget still unspent, as a percent — shown as CONTEXT next to headroom, never a gate."""
    seven = (snapshot or {}).get("seven_day_pct")
    if seven is None:
        return None
    return max(0.0, 100.0 - float(seven))


def match(headroom: float, jobs: List[Job], roe: ROE, *, weekly_reserve_pct: float = 0.0) -> COA:
    """Annotate every job against the current-window headroom: fits / over_budget / blocked.
    Nothing is forfeited for budget — `over_budget` jobs are still queueable. ROE-disallowed
    jobs (type / per-job cap) are `blocked` (distinct). roe.max_windows, if set, lowers the
    fit threshold but never drops a job."""
    cap = max(0.0, headroom)
    if roe.max_windows is not None:
        cap = min(cap, roe.max_windows)

    eligible: List[Job] = []
    blocked: List[Job] = []
    for j in jobs:
        if roe.allowed_types is not None and j.type not in roe.allowed_types:
            blocked.append(j)
            continue
        if roe.per_job_max_windows is not None and j.est_windows > roe.per_job_max_windows:
            blocked.append(j)
            continue
        eligible.append(j)

    eligible.sort(key=lambda j: (j.value / j.est_windows if j.est_windows > 0 else 0.0, j.value),
                  reverse=True)

    queue: List[Job] = []
    over: List[Job] = []
    spent = 0.0
    for j in eligible:
        if spent + j.est_windows <= cap + _EPS:
            queue.append(j)
            spent += j.est_windows
        else:
            over.append(j)

    if not eligible:
        note = "No eligible jobs (all blocked by the rules of engagement)." if blocked \
            else "No jobs proposed."
    elif not queue:
        note = (f"~{cap:.2f} window free now — every job is bigger than that. "
                f"Queue what's worth it; it runs until the real limit.")
    else:
        note = (f"{len(queue)} job(s) fit ~{cap:.2f} window free now"
                + (f", {len(over)} over budget (queue anyway)." if over else "."))
    return COA(queue=queue, over_budget=over, blocked=blocked,
               headroom_windows=round(cap, 4), weekly_reserve_pct=weekly_reserve_pct,
               fits_windows=round(spent, 4), note=note)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 tests/test_advisor.py`
Expected: PASS. (Other tests in the file that referenced `COA.skipped`/`envelope_windows`/`spent_windows` or the old `match(windows, ...)` selection semantics must be updated to the new shape in this same step — search the file for `.skipped`, `.envelope_windows`, `.spent_windows`, and `match(` and fix each to `over_budget`/`headroom_windows`/`fits_windows`. Report the count changed.)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/advisor.py tests/test_advisor.py
git commit -m "feat(coa): headroom helpers + annotate-not-forfeit match (fits/over/blocked)"
```

---

### Task 2: coa_report — render the new COA shape (md + html)

**Files:**
- Modify: `src/scorched_earth/coa_report.py`
- Test: `tests/test_advisor.py` (report tests live here today)

**Interfaces:**
- Consumes: reshaped `COA` from Task 1.
- Produces: `render_md(coa, generated_at) -> str`, `render_html(coa, generated_at, *, verdict, roe_lines, reset_in) -> str` — same signatures, new field names; HTML data blob gains `headroom`, `weeklyReservePct`, per-job `fit`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_advisor.py`:

```python
from scorched_earth import coa_report as _rep  # noqa: E402
_md = _rep.render_md(_coa, "2026-06-25")
check("render_md uses the 'Over budget' framing, not 'Left on the table'",
      "Over budget" in _md and "Left on the table" not in _md)
check("render_md lists the over-budget jobs", "b" in _md and "c" in _md)
_html = _rep.render_html(_coa, "2026-06-25", verdict="green")
check("render_html substitutes the token (no leftover __COA_JSON__)",
      "__COA_JSON__" not in _html)
import json as _json  # noqa: E402
_blob = _json.loads(_html.split("var DATA = ", 1)[1].split(";\n", 1)[0]) if "var DATA = " in _html else None
check("render_html carries headroom + weeklyReservePct in the data blob",
      ('"headroom"' in _html) and ('"weeklyReservePct"' in _html))
check("render_html marks each job's fit (fits vs over)",
      ('"fit": "fits"' in _html or '"fit":"fits"' in _html))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_advisor.py`
Expected: FAIL — md still says "Left on the table"; html blob has no `headroom`/`fit`.

- [ ] **Step 3: Implement** — in `src/scorched_earth/coa_report.py`:

Replace the `coa.skipped` block in `render_md` (the "Left on the table" section) with:

```python
    if coa.over_budget:
        lines += ["## Over budget (queue anyway)", ""]
        for j in coa.over_budget:
            lines.append(f"- {j.id} ({j.tier}, {j.est_windows:.1f}w): {j.title}")
    if coa.blocked:
        lines += ["", "## Blocked by ROE", ""]
        for j in coa.blocked:
            lines.append(f"- {j.id} ({j.type}): {j.title}")
```

In `_job_obj`, add a `fit` arg so each rendered job carries its status:

```python
def _job_obj(j, fit="fits") -> dict:
    return {
        "title": j.title, "tier": j.tier, "type": (j.type or "").upper(),
        "cost": f"{j.est_windows:.1f} win", "value": _value_label(j.value),
        "depth": j.depth, "rationale": j.rationale, "command": j.launch, "fit": fit,
    }
```

In `render_html`, rebuild the data blob's job lists + headroom context (replace the `envelope`/`queue`/`skipped` keys):

```python
    data = {
        "sector": "SECTOR 07",
        "date": generated_at,
        "verdict": (verdict or "unknown").lower(),
        "note": coa.note,
        "headroom": round(coa.headroom_windows, 2),
        "weeklyReservePct": round(coa.weekly_reserve_pct, 0),
        "resetIn": reset_in,
        "roe": list(roe_lines or []),
        "queue": [_job_obj(j, "fits") for j in coa.queue],
        "overBudget": [_job_obj(j, "over") for j in coa.over_budget],
        "blocked": [_job_obj(j, "blocked") for j in coa.blocked],
    }
```

- [ ] **Step 4: Verify the template reads the new keys.** Open `src/scorched_earth/coa_template.html` and update its JS that consumed `envelope.available`/`envelope.spent`/`skipped` to read `headroom`/`weeklyReservePct`/`overBudget` and to render the per-job `fit` (a `FITS`/`OVER` badge). Keep the single `__COA_JSON__` token (appearing once, never inside a comment). If a key it referenced no longer exists, default it (`(DATA.overBudget||[])`). This is presentation only.

- [ ] **Step 5: Run to verify they pass**

Run: `python3 tests/test_advisor.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/coa_report.py src/scorched_earth/coa_template.html tests/test_advisor.py
git commit -m "feat(coa): report renders fits/over-budget/blocked + headroom (md+html)"
```

---

### Task 3: runner — ungate pick_next, read_headroom, drop skipped-budget, rate-limit parser, ROE caps

**Files:**
- Modify: `src/scorched_earth/runner.py`, `src/scorched_earth/roe.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces: `pick_next(queue, roe) -> Optional[Job]` (NO budget arg), `read_headroom(state, now) -> Optional[float]`, `detect_rate_limit(output: str) -> bool`, `ROE.max_jobs: Optional[int]`, `ROE.max_est_windows: Optional[float]`. `plan_run` no longer emits `"skipped-budget"`.
- Consumed by: Task 4 (coa_serve drain), Task 4 (run_queue halt).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_runner.py` (match its harness):

```python
from scorched_earth import runner as _rn  # noqa: E402
from scorched_earth.jobs import Job as _RJ  # noqa: E402
from scorched_earth.roe import ROE as _RROE  # noqa: E402

# pick_next no longer gates on budget — returns the next ROE-allowed job regardless of size
_q = [_RJ(id="big", repo=".", title="B", type="docs", est_windows=3.5, value=9, depth=10)]
check("pick_next returns an over-headroom job (no budget gate)",
      _rn.pick_next(_q, _RROE()) is not None and _rn.pick_next(_q, _RROE()).id == "big")
check("pick_next still skips ROE-disallowed types",
      _rn.pick_next([_RJ(id="x", repo=".", title="X", type="refactor", est_windows=0.5, value=5, depth=3)],
                    _RROE()) is None)

# detect_rate_limit keys on the stream-json rate_limit signal, not normal failures
check("detect_rate_limit true on the stream-json rate_limit event",
      _rn.detect_rate_limit('{"type":"system","subtype":"api_retry","error":"rate_limit"}') is True)
check("detect_rate_limit false on a normal job failure",
      _rn.detect_rate_limit('{"type":"result","is_error":true,"error":"server_error"}') is False)
check("detect_rate_limit false on empty output", _rn.detect_rate_limit("") is False)

# read_headroom mirrors the current-window-free model (fresh snapshot)
_fresh = {"snapshot": {"five_hour_pct": 5, "seven_day_pct": 81, "five_hour_reset": 9_999_999_999},
          "recommendation": {"windows_left": 0.2}}
check("read_headroom = current-window free on a fresh snapshot",
      abs(_rn.read_headroom(_fresh, 1) - 0.95) < 1e-9)

# ROE gains optional caps, default off
check("ROE caps default to None (off)", _RROE().max_jobs is None and _RROE().max_est_windows is None)

# plan_run no longer forfeits for budget
_disp, _ = _rn.plan_run([_RJ(id="d", repo=".", title="D", type="docs", est_windows=3.5, value=9, depth=10)],
                        999, _RROE())
check("plan_run never emits skipped-budget",
      all(d != "skipped-budget" for _, d in _disp))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `pick_next` takes an `available` arg; `detect_rate_limit`/`read_headroom` undefined; `ROE` has no `max_jobs`; `plan_run` still emits `skipped-budget`.

- [ ] **Step 3: Implement.**

In `src/scorched_earth/roe.py`, add to the `ROE` dataclass (cost rules block):

```python
    max_jobs: Optional[int] = None                  # optional run cap: stop after N jobs (off by default)
    max_est_windows: Optional[float] = None         # optional run cap: stop after ~this much est spend
```

In `src/scorched_earth/runner.py`:

Replace `pick_next` (drop the budget gate):

```python
def pick_next(queue, roe):
    """First queued job that is ROE-allowed to run unattended. No budget gate — the cockpit/runner
    drain whatever is queued and stop only on a real usage-limit (or an optional ROE cap)."""
    for j in queue:
        if _allowed_unattended(roe, j.type):
            return j
    return None
```

Add (near `read_envelope`):

```python
def read_headroom(state, now):
    """COA execution headroom: unused capacity of the CURRENT 5-hour window, in window-units.
    None when the snapshot is stale/missing (same honesty rule as read_envelope)."""
    if is_stale(state, now):
        return None
    snap = (state or {}).get("snapshot") or {}
    five = snap.get("five_hour_pct")
    if five is None:
        return None
    return max(0.0, (100.0 - float(five)) / 100.0)


def detect_rate_limit(output):
    """True when headless `claude -p --output-format stream-json` output carries the rate-limit
    signal (429 api_retry). Substring match on the stable error value; exit code alone can't tell
    a usage-limit from a normal failure. Conservative: only the rate_limit value, not 'overloaded'."""
    s = output or ""
    return '"error":"rate_limit"' in s or '"error": "rate_limit"' in s or '"rate_limit_error"' in s
```

In `plan_run`, remove the budget forfeiting: delete the `budget_gone` / `skipped-budget` branch so every ROE-allowed job is `"run"` (ROE-blocked stays `"blocked-roe"`):

```python
def plan_run(jobs, envelope, roe):
    """Pure pre-run disposition. ROE-blocked jobs are 'blocked-roe'; everything else is 'run'
    (no budget forfeiting — execution stops on a real usage-limit, not a predicted envelope).
    `envelope` is kept in the signature for back-compat but no longer gates."""
    out = []
    spent = 0.0
    for j in jobs:
        if not _allowed_unattended(roe, j.type):
            out.append((j, "blocked-roe"))
            continue
        out.append((j, "run"))
        spent += j.est_windows
    return out, spent
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS. Existing tests that call `pick_next(queue, available, roe)` or assert `skipped-budget` must be updated in this step (search `pick_next(` and `skipped-budget`). Report the count changed.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py src/scorched_earth/roe.py tests/test_runner.py
git commit -m "feat(coa): ungate pick_next, add read_headroom + rate-limit parser + ROE caps; plan_run stops forfeiting"
```

---

### Task 4: runner execute path + cockpit Engine — halt on usage-limit, drop the EnvelopeTracker

**Files:**
- Modify: `src/scorched_earth/runner.py` (`build_claude_cmd`, `_run_killable`, `execute_job`, `run_queue`), `src/scorched_earth/coa_serve.py` (`Engine`)
- Test: `tests/test_runner.py`, `tests/test_cockpit.py`

**Interfaces:**
- Consumes: `detect_rate_limit`, `pick_next(queue, roe)`, `read_headroom` (Task 3); `advisor.match`/`window_headroom`/`weekly_reserve_pct` (Task 1).
- Produces: new `JobOutcome.outcome` value `"limit"`; `Engine` with no `EnvelopeTracker`/reservation; `Engine.state_json()` carries `headroom`, `weekly_reserve_pct`, and a per-job `fit` flag; drain halts all workers on `"limit"` and re-enqueues the limit job; optional ROE cap halts.

- [ ] **Step 1: Write the failing tests.**

In `tests/test_runner.py` (run_queue halt — uses the injected `execute`):

```python
# a job that returns outcome 'limit' halts the queue; the rest stay un-run (resumable)
import tempfile as _tf, os as _os, json as _json2  # noqa: E402
def _mk_runner_repo(jobs):
    r = _tf.mkdtemp(); _os.makedirs(_os.path.join(r, ".scorched"), exist_ok=True)
    from scorched_earth import coa_io as _cio
    _cio.write_queue(r, jobs); return r
_lim_repo = _mk_runner_repo([_RJ(id="j1", repo=".", title="1", type="docs", est_windows=0.5, value=9, depth=3),
                             _RJ(id="j2", repo=".", title="2", type="docs", est_windows=0.5, value=8, depth=3)])
_calls = []
def _lim_exec(repo, job, roe):
    _calls.append(job.id)
    return ("limit", None, "usage limit") if job.id == "j1" else ("pass", None, "ok")
_state_ok = {"snapshot": {"five_hour_pct": 5, "seven_day_pct": 50, "five_hour_reset": 9_999_999_999},
             "recommendation": {"windows_left": 5, "level": "green"}}
_rr = _rn.run_queue(_lim_repo, _state_ok, now=1, date="2026-06-25", execute=_lim_exec)
check("run_queue halts the queue on a usage-limit outcome (j2 never runs)", _calls == ["j1"])
check("run_queue records the limit job as 'limit', not 'fail'",
      any(j.outcome == "limit" for j in _rr.jobs))
```

In `tests/test_cockpit.py` (replace the shared-budget-reservation test from the parallel feature with a shared-halt test; keep the concurrency-proof test):

```python
# a usage-limit on one repo's job HALTS all workers (no shared budget envelope anymore)
_hl_gate = _pth.Event()
def _hl_exec(repo, job, roe):
    if job.id.endswith("1"):
        return ("limit", None, "usage limit")     # first job in each repo trips the limit
    _hl_gate.wait(2)
    return ("pass", None, "ok")
_hlA = _mk_repo([Job(id="A1", repo=".", title="x", type="docs", est_windows=0.5, value=9, depth=3),
                 Job(id="A2", repo=".", title="x", type="docs", est_windows=0.5, value=8, depth=3)])
_hl = Engine([_hlA], execute=_hl_exec, load_state=lambda: _STATE, now=lambda: 1)
_hl.run([_hlA])
_end = _ptime.time() + 3
while _ptime.time() < _end and _hl.state_json()["busy"]:
    _ptime.sleep(0.02)
check("a usage-limit halts the engine; the limit job is re-queued (resumable)",
      "A1" in [j["id"] for j in _io.board_state(_hlA)["queued"]]
      and "A1" not in [j["id"] for j in _io.board_state(_hlA)["finished"]])

# state_json carries headroom context + per-job fit flags
_sjs = _hl.state_json()
check("state_json exposes headroom + weekly reserve context",
      "headroom" in _sjs and "weekly_reserve_pct" in _sjs)
```

(Also: delete the old `"shared budget caps the WHOLE parallel run (2 of 6 jobs...)"` test — the envelope it asserted no longer exists. Keep the `"two armed repos run CONCURRENTLY"` test.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_runner.py && python3 tests/test_cockpit.py`
Expected: FAIL — `run_queue` treats `"limit"` like any outcome and keeps going; `Engine` still references `EnvelopeTracker`; `state_json` has no `headroom`.

- [ ] **Step 3: Implement the runner execute path.**

`build_claude_cmd` — request stream-json so the rate-limit signal is machine-readable:

```python
def build_claude_cmd(job, worktree):
    return [
        "claude", "-p", _PRELUDE + (job.launch or job.title),
        "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions",
    ]
```

`_run_killable` — capture stdout (so we can scan it) instead of DEVNULL; return `(status, output)`:

```python
def _run_killable(cmd, cwd, kill_event, grace=3.0, poll=0.1):
    """Run cmd capturing stdout (for rate-limit detection). Returns (status, output) where status
    is 'killed' or 'done'. Honors kill_event (SIGTERM then SIGKILL after grace)."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if kill_event is None:
        out, _ = p.communicate()
        return "done", out or ""
    chunks = []
    while p.poll() is None:
        if kill_event.is_set():
            p.terminate()
            try:
                p.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
            try:
                rest = p.stdout.read() if p.stdout else ""
            except Exception:  # noqa: BLE001
                rest = ""
            return "killed", "".join(chunks) + (rest or "")
        time.sleep(poll)
    out = p.stdout.read() if p.stdout else ""
    chunks.append(out or "")
    return ("killed" if kill_event.is_set() else "done"), "".join(chunks)
```

`execute_job` — scan the captured output; return outcome `"limit"` when the rate-limit signal is present:

```python
        status, out = _run_killable(build_claude_cmd(job, wt), wt, getattr(_kill_ctx, "event", None))
        if status == "killed":
            _discard_worktree(root, job.id)
            return "killed", None, "killed by operator — work discarded."
        if detect_rate_limit(out):
            _discard_worktree(root, job.id)             # nothing landed; job returns to the queue
            return "limit", None, "stopped: usage limit reached — re-queued, resume after reset."
```

(Replace the existing single-line `_run_killable(...) == "killed"` block with the above; everything after — diff/gate — is unchanged.)

`run_queue` — halt the loop on `"limit"`; mark the limit job and leave the rest un-run:

```python
        oc = run_one(repo, job, roe, repo_disp, i, execute=execute,
                     on_running=lambda r: (rr.jobs.append(r), _persist()))
        rr.jobs[-1] = oc
        if oc.outcome == "limit":
            rr.state = "halted"
            _persist()
            return rr
        spent += job.est_windows
        rr.spent_estimated = spent
        _persist()
```

- [ ] **Step 4: Implement the cockpit Engine** (`src/scorched_earth/coa_serve.py`). Remove `EnvelopeTracker`/reservation; drain ungated; halt on `"limit"`; add headroom to `state_json`.

In `__init__`, delete `self._tracker = None`. In `_drain_repo`, replace the locked pick block so it no longer reads the tracker or charges — pick ungated and stop on the stop flag:

```python
            with self._lock:
                if self._stop:
                    self._workers.discard(repo); done = True
                else:
                    roe = coa_io.load_roe(repo)
                    job = runner.pick_next(coa_io.read_queue(repo), roe)
                    if job is None:
                        self._workers.discard(repo); done = True
                    else:
                        done = False
                        self._running[repo] = {"repo": repo, "id": job.id}
                        ke = threading.Event(); self._kill_events[repo] = ke
                        coa_io.unqueue(repo, job.id)
                        rr = self._results.get(repo)
                        if rr is None:
                            rr = runner.RunResult(
                                generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                                state="running", repo=repo, verdict="unknown", note="",
                                available_windows=0.0, spent_estimated=0.0)
                            self._results[repo] = rr
                        seq = len(rr.jobs) + 1
```

After `run_one`, handle the `"limit"` outcome (re-enqueue + stop all) alongside pass/fail:

```python
            with self._lock:
                if oc.outcome == "limit":
                    coa_io.enqueue(repo, [job])          # didn't run — put it back, resumable
                    self._stop = True                    # halt every worker
                elif oc.outcome in ("pass", "fail"):
                    rr.jobs.append(oc); self._persist(repo, rr)
                self._running.pop(repo, None); self._kill_events.pop(repo, None)
                if self._stop:
                    self._workers.discard(repo); done = True
```

Add headroom + per-job fit to `state_json` (compute once from the snapshot, annotate each repo's proposed/queued briefs):

```python
    def state_json(self):
        from . import advisor
        state = self._load_state()
        snap = (state or {}).get("snapshot") or {}
        headroom = advisor.window_headroom(snap)
        wrp = advisor.weekly_reserve_pct(snap)
        with self._lock:
            running = [dict(v) for v in self._running.values()]
            busy = bool(running) or bool(self._workers)
            running_by_repo = {}
            for v in self._running.values():
                running_by_repo.setdefault(v["repo"], []).append(v["id"])
        repos = []
        for r in self.repos:
            board = coa_io.board_state(r, running_by_repo.get(r, ()))
            roe = coa_io.load_roe(r)
            coa = advisor.match(headroom or 0.0, coa_io.read_queue(r) + coa_io.load_jobs(r), roe)
            fits = {j.id for j in coa.queue}
            for col in ("proposed", "queued"):
                for jb in board[col]:
                    jb["fit"] = "fits" if jb["id"] in fits else "over"
            repos.append(board)
        return {"repos": repos, "running": running, "busy": busy,
                "headroom": round(headroom, 2) if headroom is not None else None,
                "weekly_reserve_pct": round(wrp, 0) if wrp is not None else None}
```

- [ ] **Step 5: Run to verify they pass**

Run: `python3 tests/test_runner.py && python3 tests/test_cockpit.py && python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: all green. Report the cockpit count. (The optional ROE cap halt — `max_jobs`/`max_est_windows` — is wired in Task 4 Step 6 below before commit.)

- [ ] **Step 6: Wire the optional caps.** In `coa_serve._drain_repo`, before picking, count this run's completed jobs / est spend per repo and stop when a cap is set and reached:

```python
                    roe = coa_io.load_roe(repo)
                    rr = self._results.get(repo)
                    done_n = len(rr.jobs) if rr else 0
                    spent_w = sum(j.est_windows for j in rr.jobs) if rr else 0.0
                    capped = ((roe.max_jobs is not None and done_n >= roe.max_jobs) or
                              (roe.max_est_windows is not None and spent_w >= roe.max_est_windows))
                    job = None if capped else runner.pick_next(coa_io.read_queue(repo), roe)
```

Add a runner test that a `max_jobs=1` ROE stops after one job, and run `python3 tests/test_cockpit.py`.

- [ ] **Step 7: Commit**

```bash
git add src/scorched_earth/runner.py src/scorched_earth/coa_serve.py tests/test_runner.py tests/test_cockpit.py
git commit -m "feat(coa): halt on real usage-limit + optional caps; retire the EnvelopeTracker; headroom+fit in state_json"
```

---

### Task 5: cockpit_template — headroom HUD + fits/over badge

**Files:**
- Modify: `src/scorched_earth/cockpit_template.html`
- Test: `tests/test_cockpit.py`

**Interfaces:** `state.headroom` (number|null), `state.weekly_reserve_pct` (number|null); each proposed/queued job brief now carries `fit: "fits"|"over"`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_cockpit.py`:

```python
_hd = render_cockpit("tk", {"repos": [{"repo":"/r/a","name":"a",
        "proposed":[{"id":"p1","title":"P","type":"docs","tier":"M","depth":6,"est_windows":1.0,"value":7,"fit":"over"}],
        "queued":[],"finished":[]}],
        "running": [], "busy": False, "headroom": 0.95, "weekly_reserve_pct": 19}).decode("utf-8")
check("cockpit renders the headroom readout", "0.95" in _hd and "headroom" in _hd.lower())
check("cockpit renders an OVER-budget badge for over-headroom jobs", "OVER" in _hd)
check("cockpit no longer labels the HUD 'BUDGET SPENT'", "BUDGET SPENT" not in _hd)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — template has no headroom readout / OVER badge; still says "BUDGET SPENT".

- [ ] **Step 3: Implement** in `src/scorched_earth/cockpit_template.html`:
- Replace the `BUDGET SPENT` stat (`#sbBudget`, ~line 223) with a **HEADROOM** readout: `~<headroom> win free now` and a sub-line `weekly <weekly_reserve_pct>% reserve`. Drive it in the render JS from `state.headroom` / `state.weekly_reserve_pct` (show `—` when null). Remove the now-dead `spent` computation (~lines 450-455).
- In the proposed/queued card renderer, add a badge when `job.fit === "over"`: a small `OVER` tag (and optionally a subtle `FITS` styling otherwise). Cosmetic only — the card stays draggable/queueable.
- Keep `__COCKPIT_TOKEN__` / `__COCKPIT_JSON__` appearing exactly once each, none in comments.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_cockpit.py && python3 tests/test_runner.py && python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: all green. Render smoke check:
`python3 -c "import sys;sys.path.insert(0,'src');from scorched_earth.coa_serve import render_cockpit;h=render_cockpit('t',{'repos':[],'running':[],'busy':False,'headroom':None,'weekly_reserve_pct':None}).decode();assert '__COCKPIT_' not in h;print('ok')"`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/cockpit_template.html tests/test_cockpit.py
git commit -m "feat(coa): cockpit headroom readout + over-budget badge (replaces BUDGET SPENT)"
```

---

### Task 6: `scorch advise` writes + opens the HTML (and MD)

**Files:**
- Modify: `bin/scorch` (`_coa_cli` advise branch)
- Test: `tests/test_advisor.py` (CLI smoke via subprocess, matching existing patterns)

**Interfaces:** `scorch advise [repo] [--no-open]` → for each repo: compute headroom from the cached snapshot, `match`, render md+html, `coa_io.write_coa`, open the HTML (single repo) unless `--no-open`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_advisor.py` (use the snapshot fixture + a temp linked repo; assert the files are written). If the existing file already has a CLI-subprocess helper, reuse it; otherwise assert via the function path:

```python
# advise writes BOTH md + html (html is the artifact to open, md is the record)
import tempfile as _tf2, os as _os2
from scorched_earth import coa_io as _cio2
_arepo = _tf2.mkdtemp(); _os2.makedirs(_os2.path.join(_arepo, ".scorched"), exist_ok=True)
with open(_os2.path.join(_arepo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id":"a1","repo":_arepo,"title":"A","type":"docs","depth":3,"value":7}], _f)
# drive the same render+write the CLI uses
_snap = {"five_hour_pct": 5, "seven_day_pct": 81}
_hr = _adv.window_headroom(_snap); _wr = _adv.weekly_reserve_pct(_snap)
_coaA = _match(_hr, _cio2.load_jobs(_arepo), _ROE(), weekly_reserve_pct=_wr)
_mdp, _htmlp = _cio2.write_coa(_arepo, _rep.render_md(_coaA, "2026-06-25"),
                               _rep.render_html(_coaA, "2026-06-25", verdict="green"), "2026-06-25")
check("advise path writes md + html records", _os2.path.exists(_mdp) and _os2.path.exists(_htmlp))
```

- [ ] **Step 2: Run to verify it fails (or guards the contract)**

Run: `python3 tests/test_advisor.py`
Expected: PASS only once `render_html`/`render_md` accept the new COA (Task 2) — if Task 2 is done this guards the write contract. (This task's real change is the CLI wiring in Step 3.)

- [ ] **Step 3: Implement** the advise branch in `bin/scorch` `_coa_cli` — compute headroom, render both, write, open:

```python
    # advise
    state = st.load_state()
    snap = (state or {}).get("snapshot") or {}
    rec = (state or {}).get("recommendation") or {}
    from scorched_earth import advisor as _adv
    headroom = _adv.window_headroom(snap)
    if not _has_usable_snapshot(state) or headroom is None:
        print("No live budget reading yet, so there's nothing to plan against. "
              "Open a Claude Code session to capture a snapshot, then try again.")
        return 0
    no_open = "--no-open" in rest
    rest = [a for a in rest if a != "--no-open"]
    repos = [rest[0]] if rest else coa_io.list_repos()
    if not repos:
        print("No repos linked. Use: scorch link <path>")
        return 0
    date = time.strftime("%Y-%m-%d", time.localtime())
    wrp = _adv.weekly_reserve_pct(snap) or 0.0
    level = rec.get("level", "unknown")
    written = []
    for repo in repos:
        roe = coa_io.load_roe(repo)
        coa = advisor.match(headroom, coa_io.load_jobs(repo), roe, weekly_reserve_pct=wrp)
        md = coa_report.render_md(coa, date)
        html = coa_report.render_html(coa, date, verdict=level)
        md_path, html_path = coa_io.write_coa(repo, md, html, date)
        written.append(html_path)
        print(f"\n=== {repo} ===")
        print(coa.note)
        print(f"COA written: {html_path}")
    if not no_open and len(written) == 1:
        _open_path(written[0])      # reuse the same opener --sitrep uses
    return 0
```

(If a shared opener helper like `_open_path`/`_open` doesn't exist, factor the `open`/`xdg-open` logic from the sitrep path into one and call it here.)

- [ ] **Step 4: Run to verify**

Run: `python3 tests/test_advisor.py` and a manual `./bin/scorch advise <a linked repo> --no-open` (assert it prints `COA written: …html` and writes the file).
Expected: file written; `--no-open` suppresses the browser.

- [ ] **Step 5: Commit**

```bash
git add bin/scorch tests/test_advisor.py
git commit -m "feat(coa): scorch advise writes + opens the HTML report (md kept as the record)"
```

---

### Task 7: `/coa` dispatches one "COA officer" subagent

**Files:**
- Modify: `commands/coa.md`
- (No test — it's a command prompt; verified by reading.)

**Interfaces:** `/coa [repo] [--refresh]` → dispatch ONE subagent that runs scan (if needed) → `scorch advise` (now writes+opens) → returns a tidy briefing.

- [ ] **Step 1: Rewrite `commands/coa.md`** so the body instructs the MAIN agent to dispatch a single subagent for the whole mechanical pipeline, then relay only its briefing. Keep the existing scan-personality guidance, but move it into the subagent's instructions. The command body should:
  1. Resolve target repo(s) (`$ARGUMENTS` path or all linked).
  2. Dispatch ONE subagent told to: ensure `<repo>/.scorched/jobs.json` (run the scan with the existing personality + ROE bounds when missing or `--refresh`); run `scorch advise <repo>` (which now budget-annotates against current-window headroom and writes+opens the HTML, keeping the MD record); and return a ~4-line briefing — top 3 jobs by value, count over budget, the current headroom line, and the report path.
  3. The main agent prints only that briefing (and notes the user can expand the subagent view for detail).
  Keep `allowed-tools` permissive enough for the subagent dispatch + `scorch`.

- [ ] **Step 2: Verify** by reading the rewritten command: the heavy scan/advise detail lives in the subagent instructions; the surface flow is one dispatch + a briefing; the budget language matches the new headroom model (no "windows left until reset" / "forfeit" framing).

- [ ] **Step 3: Commit**

```bash
git add commands/coa.md
git commit -m "feat(coa): /coa dispatches one COA-officer subagent (tidy surface, detail in subagent view)"
```

---

## Self-Review

**Spec coverage:**
- A1 headroom helpers → Task 1. A2 annotate match → Task 1. A3 report → Task 2. A4 cockpit board/Engine (drop tracker, headroom, fit) → Task 4 + 5. A5 runner (pick_next, halt-on-limit, caps, plan_run) → Tasks 3 + 4. A6 green-light untouched → Global Constraints. Part B advise html+md → Task 6. Part C /coa subagent → Task 7. ✓
- ROE caps (A5) → Task 3 (fields) + Task 4 Step 6 (enforcement). ✓
- Usage-limit detection (the flagged risk) → Task 3 `detect_rate_limit` (pure, tested) + Task 4 `build_claude_cmd`/`execute_job` (stream-json + scan). The `--verbose` requirement for `print + stream-json` is version-dependent — verify at Task 4 implement time; if a version rejects it, drop `--verbose` and confirm stream-json still emits the `rate_limit` event.

**Placeholder scan:** the only deferred items are the template JS edit *sites* (Tasks 2 Step 4, 5 Step 3) and the command prose (Task 7) — described by exact location/contract per the repo's established template-edit style; no "TBD"/"handle edge cases" in logic code.

**Type consistency:** `COA` fields (`queue`, `over_budget`, `blocked`, `headroom_windows`, `weekly_reserve_pct`, `fits_windows`, `note`) are used consistently across Tasks 1/2/4/6. `pick_next(queue, roe)` (2-arg) is consistent in Tasks 3/4. `detect_rate_limit`/`read_headroom`/`window_headroom`/`weekly_reserve_pct` names match across tasks. `JobOutcome.outcome == "limit"` is produced in Task 4 (runner) and consumed in Task 4 (run_queue + Engine).

**Risk:** Task 4 unwinds the just-built `EnvelopeTracker`/charge-at-pick reservation (parallel-repos feature). Concurrency (per-repo workers, the "two armed repos run CONCURRENTLY" test) is preserved; the shared-budget-reservation test is replaced by a shared-halt test. This is the deliberate evolution the spec calls out.
