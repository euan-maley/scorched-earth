# DEFCON COA Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the COA advisor's per-job budget/effort estimation with a DEFCON (1–5) criticality index measuring project impact, and expand the scan agent to hunt extreme overnight campaigns alongside the existing small knockouts.

**Architecture:** The COA layer stops estimating per-job cost entirely. Jobs carry a `defcon` (1 = most critical). The matcher becomes a priority sort (DEFCON, then value); the runner/cockpit drain in DEFCON order and stop only on the *real* rate limit. ROE's window-based cost caps are deleted; a new task rule `auto_run_min_defcon` gates high-impact jobs behind explicit approval. The statusline weekly-burn engine is untouched.

**Tech Stack:** Python 3.8+ stdlib only (no deps — COA modules are I/O tier except `jobs`/`roe`/`advisor` which are pure). Tests are plain `assert`-style harnesses run with `python3 tests/<file>.py`.

## Global Constraints

- **Stdlib only**, Python ≥ 3.8. No new dependencies.
- `core.py`, `calibrate.py`, `habits.py`, `report.py`, `statusline.py`, `gradient.py`, and `tests/test_scorched.py` (the 57 core checks) are **out of scope and must not change**.
- DEFCON scale: **1 = most critical** (overnight campaigns), **5 = trivial**. Lower number = higher impact. Clamp all DEFCON values to `[1, 5]`.
- DEFCON measures **impact only** — never effort, length, or duration.
- `auto_run_min_defcon` default = **3**: jobs with `defcon < 3` (i.e. 1 and 2) are `approval_required`.
- Clean break: no depth/windows → DEFCON mapping. Legacy job dicts lacking `defcon` default to **3**.
- Run each task's tests with the exact command shown; a task is done only when its suite is green.

---

### Task 1: `jobs.py` — DEFCON job model

**Files:**
- Modify: `src/scorched_earth/jobs.py` (full rewrite of the module body)
- Test: `tests/test_advisor.py` (jobs + depth sections)

**Interfaces:**
- Produces: `Job` dataclass with fields `id: str, repo: str, title: str, type: str, defcon: int = 3, value: float = 0.0, rationale: str = "", launch: str = "", verify: str = "", status: str = "proposed"`. Property `Job.approval_required(roe)` — see note. `parse_jobs(data, repo="") -> List[Job]`. `clamp_defcon(n) -> int`.
- Consumes: nothing.

Note: keep `approval_required` as a free function in `roe`/`advisor` consumers rather than on `Job` to avoid a `Job→ROE` import. Expose `clamp_defcon` from `jobs`.

- [ ] **Step 1: Replace the jobs tests** — in `tests/test_advisor.py`, delete the `tier_for` import and the two old `parse_jobs` checks (lines ~27–38) and the entire `--- depth rating ---` section (lines ~170–188). Add at the jobs section:

```python
from scorched_earth.jobs import Job, parse_jobs, clamp_defcon  # noqa: E402

check("clamp_defcon bounds to 1..5",
      (clamp_defcon(0), clamp_defcon(3), clamp_defcon(9)) == (1, 3, 5))

_parsed = parse_jobs([
    {"id": "a", "title": "x", "type": "test", "defcon": 1, "value": 8},
    {"id": "b", "defcon": 4},                 # minimal valid (value defaults 0)
    {"id": "c"},                              # no defcon -> default 3
    {"title": "no id"},                       # dropped: no id
], repo="/tmp/r")
check("parse_jobs keeps valid (incl. defcon-defaulted), drops id-less", len(_parsed) == 3)
check("parse_jobs fills repo + defcon", _parsed[0].repo == "/tmp/r" and _parsed[0].defcon == 1)
check("parse_jobs defaults missing defcon to 3", _parsed[2].defcon == 3)
check("parse_jobs clamps out-of-range defcon",
      parse_jobs([{"id": "z", "defcon": 99}])[0].defcon == 5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL — `ImportError` on `clamp_defcon` / `tier_for`.

- [ ] **Step 3: Rewrite `jobs.py`**

```python
"""Job schema for the COA advisor: the expensive-work items a repo scan produces and the
priority matcher consumes. Pure, stdlib only. Jobs are rated by DEFCON criticality
(1 = most critical / project-defining, 5 = trivial) — impact on the project, never effort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


def clamp_defcon(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, n))


@dataclass
class Job:
    id: str
    repo: str
    title: str
    type: str
    defcon: int = 3               # 1..5 criticality, 1 = most critical (project impact)
    value: float = 0.0            # within-DEFCON tie-breaker (agent's worth ranking)
    rationale: str = ""
    launch: str = ""              # prompt/command to run it
    verify: str = ""              # per-job test-gate override; falls back to ROE test_cmd
    status: str = "proposed"      # proposed | queued | done


def parse_jobs(data, repo: str = "") -> List[Job]:
    """Build Jobs from a list of dicts. Each needs an `id`. `defcon` defaults to 3 when absent
    (clean-break: legacy depth/est_windows fields are ignored). `value` defaults to 0."""
    out: List[Job] = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        if d.get("id") is None:
            continue
        out.append(Job(
            id=str(d["id"]),
            repo=d.get("repo") or repo,
            title=d.get("title", ""),
            type=d.get("type", "other"),
            defcon=clamp_defcon(d.get("defcon", 3)),
            value=float(d.get("value", 0) or 0),
            rationale=d.get("rationale", ""),
            launch=d.get("launch", ""),
            verify=d.get("verify", ""),
            status=d.get("status", "proposed"),
        ))
    return out
```

- [ ] **Step 4: Run to verify the jobs section passes** (other sections will still fail — that's expected until later tasks)

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'defcon|clamp|parse_jobs'`
Expected: those lines all `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/jobs.py tests/test_advisor.py
git commit -m "feat(coa): DEFCON job model replaces depth/est_windows"
```

---

### Task 2: `roe.py` — drop cost caps, add `auto_run_min_defcon`

**Files:**
- Modify: `src/scorched_earth/roe.py`
- Test: `tests/test_advisor.py` (roe section, lines ~40–53)

**Interfaces:**
- Produces: `ROE` dataclass minus `max_windows`, `per_job_max_windows`, `max_est_windows`; plus `auto_run_min_defcon: int = 3`. Unchanged: `max_jobs`, `min_weekly_left`, `allowed_types`, `unattended_types`, `test_cmd`, `setup_cmd`, `exclude_paths`, `goals`. `roe_from_dict`, `merge_roe`, `DEFAULT_ROE` keep their signatures.
- Consumes: nothing.

- [ ] **Step 1: Update the roe tests** — replace the roe section checks with:

```python
from scorched_earth.roe import ROE, DEFAULT_ROE, roe_from_dict, merge_roe  # noqa: E402

check("DEFAULT_ROE is permissive with defcon gate at 3",
      DEFAULT_ROE.allowed_types is None and DEFAULT_ROE.auto_run_min_defcon == 3
      and not hasattr(DEFAULT_ROE, "max_windows"))

_roe = roe_from_dict({"auto_run_min_defcon": 2, "allowed_types": ["test"]})
check("roe_from_dict overlays only given keys",
      _roe.auto_run_min_defcon == 2 and _roe.allowed_types == ["test"] and _roe.min_weekly_left == 0.0)

_merged = merge_roe(roe_from_dict({"max_jobs": 9, "goals": ["a"]}),
                    roe_from_dict({"max_jobs": 2}))
check("merge_roe: override wins where set, base kept otherwise",
      _merged.max_jobs == 2 and _merged.goals == ["a"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'defcon gate|overlays|merge_roe'`
Expected: FAIL (`max_windows` still present / `auto_run_min_defcon` missing).

- [ ] **Step 3: Edit `roe.py`** — remove the three window fields, add the gate. The dataclass becomes:

```python
@dataclass
class ROE:
    # cost / run-length rules
    min_weekly_left: float = 0.0                    # don't propose unless weekly-left above this (real signal)
    max_jobs: Optional[int] = None                  # optional run cap: stop after N jobs (off by default)
    # task rules
    allowed_types: Optional[List[str]] = None       # None = all types allowed
    auto_run_min_defcon: int = 3                     # jobs with defcon < this need explicit approval to run
    # runner rules (bound the autonomous executor)
    unattended_types: Optional[List[str]] = None    # types allowed to run unattended; None = SAFE default
    test_cmd: Optional[str] = None                  # post-job verification gate command
    setup_cmd: Optional[str] = None                 # dependency pre-warm command (runner-run, with network)
    # goal rules
    exclude_paths: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
```

`roe_from_dict` and `merge_roe` use `fields(ROE)` reflectively, so they need no change.

- [ ] **Step 4: Run to verify those checks pass**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'defcon gate|overlays|merge_roe'`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/roe.py tests/test_advisor.py
git commit -m "feat(coa): ROE drops window cost caps, adds auto_run_min_defcon gate"
```

---

### Task 3: `advisor.py` — priority-sort matcher

**Files:**
- Modify: `src/scorched_earth/advisor.py` (rewrite)
- Test: `tests/test_advisor.py` (matcher + headroom sections)

**Interfaces:**
- Consumes: `Job` (Task 1), `ROE` (Task 2).
- Produces:
  - `approval_required(job, roe) -> bool` — `job.defcon < roe.auto_run_min_defcon`.
  - `weekly_reserve_pct(snapshot) -> Optional[float]` — kept (real-signal context).
  - `match(jobs, roe) -> COA` — **no headroom param**.
  - `COA` dataclass: `queue: List[Job]`, `blocked: List[Job]`, `note: str`. (Drop `over_budget`, `headroom_windows`, `weekly_reserve_pct`, `fits_windows`.)

- [ ] **Step 1: Replace the matcher tests** — delete the old matcher section (lines ~55–77) and the entire `--- headroom model ---` section (lines ~201–242, but **keep** the `advise writes BOTH md + html` block, rewriting it in Task 7). Add:

```python
from scorched_earth.advisor import COA, match, approval_required, weekly_reserve_pct  # noqa: E402
from scorched_earth.roe import ROE as _ROE  # noqa: E402

_jobs = [
    Job(id="minor", repo="r", title="minor", type="docs", defcon=4, value=5),
    Job(id="campaign", repo="r", title="campaign", type="audit", defcon=1, value=2),
    Job(id="feature", repo="r", title="feature", type="test", defcon=3, value=9),
]
_coa = match(_jobs, DEFAULT_ROE)
check("match sorts by DEFCON then value",
      [j.id for j in _coa.queue] == ["campaign", "feature", "minor"])
check("match leaves over_budget/headroom behind", not hasattr(_coa, "over_budget"))

_coa_type = match(_jobs, roe_from_dict({"allowed_types": ["docs"]}))
check("match routes disallowed types to blocked",
      [j.id for j in _coa_type.blocked] == ["campaign", "feature"]
      and [j.id for j in _coa_type.queue] == ["minor"])

check("approval_required: defcon below gate needs approval",
      approval_required(Job(id="x", repo="r", title="", type="test", defcon=2), DEFAULT_ROE)
      and not approval_required(Job(id="y", repo="r", title="", type="test", defcon=3), DEFAULT_ROE))

check("weekly_reserve_pct = 100 - seven_day_pct", weekly_reserve_pct({"seven_day_pct": 81}) == 19)

_coa_empty = match([], DEFAULT_ROE)
check("empty job list yields empty queue with a note",
      _coa_empty.queue == [] and "no jobs" in _coa_empty.note.lower())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'DEFCON then value|approval_required|over_budget'`
Expected: FAIL.

- [ ] **Step 3: Rewrite `advisor.py`**

```python
"""Priority matcher for the COA advisor. Given a list of Jobs and the ROE, splits them into a
DEFCON-ordered battle plan (`queue`) and ROE-disallowed jobs (`blocked`). No budget: nothing is
sized or forfeited — the runner stops on the real rate limit. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .jobs import Job
from .roe import ROE


@dataclass
class COA:
    queue: List[Job] = field(default_factory=list)        # DEFCON-ordered run plan
    blocked: List[Job] = field(default_factory=list)      # ROE-disallowed (type)
    note: str = ""


def approval_required(job: Job, roe: ROE) -> bool:
    """High-impact jobs (defcon below the ROE gate) need explicit approval to run unattended."""
    return job.defcon < roe.auto_run_min_defcon


def weekly_reserve_pct(snapshot) -> Optional[float]:
    """Weekly budget still unspent, as a percent — shown as display CONTEXT, never a gate."""
    seven = (snapshot or {}).get("seven_day_pct")
    if seven is None:
        return None
    return max(0.0, 100.0 - float(seven))


def match(jobs: List[Job], roe: ROE) -> COA:
    """Sort eligible jobs by (defcon asc, value desc); route ROE-disallowed types to `blocked`."""
    eligible: List[Job] = []
    blocked: List[Job] = []
    for j in jobs:
        if roe.allowed_types is not None and j.type not in roe.allowed_types:
            blocked.append(j)
        else:
            eligible.append(j)
    eligible.sort(key=lambda j: (j.defcon, -j.value))

    if not eligible:
        note = "No eligible jobs (all blocked by the rules of engagement)." if blocked \
            else "No jobs proposed."
    else:
        n_appr = sum(1 for j in eligible if approval_required(j, roe))
        note = f"{len(eligible)} job(s) queued, most critical first"
        note += f" — {n_appr} need approval (DEFCON < {roe.auto_run_min_defcon})." if n_appr else "."
    return COA(queue=eligible, blocked=blocked, note=note)
```

- [ ] **Step 4: Run to verify those checks pass**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'DEFCON then value|approval_required|disallowed|weekly_reserve|empty job'`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/advisor.py tests/test_advisor.py
git commit -m "feat(coa): advisor becomes a DEFCON priority matcher (no budget)"
```

---

### Task 4: `coa_io.py` — serialize DEFCON, drop cost fields

**Files:**
- Modify: `src/scorched_earth/coa_io.py` (`_job_to_dict`, `_job_brief`, `board_state`)
- Test: `tests/test_advisor.py` (coa_io round-trip section, lines ~108–146)

**Interfaces:**
- Consumes: `Job` (Task 1), `advisor.approval_required` (Task 3).
- Produces: `_job_to_dict(j)` and `_job_brief(j)` emit `defcon` + `value` (no `est_windows`/`depth`/`tier`). `board_state(repo_path, running_ids=())` unchanged signature; each brief gains `"approval_required"` via the repo's ROE.

- [ ] **Step 1: Update the coa_io tests** — change the `load_jobs` fixture and check:

```python
with open(os.path.join(_repo, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "j1", "defcon": 2, "value": 3}], f)
check("load_jobs reads the repo job list", [j.id for j in _io.load_jobs(_repo)] == ["j1"])
check("load_jobs reads defcon", _io.load_jobs(_repo)[0].defcon == 2)
```

And change the `load_roe` fixture to a non-window key:

```python
with open(os.path.join(_repo, ".scorched", "roe.json"), "w") as f:
    json.dump({"auto_run_min_defcon": 2}, f)
check("load_roe merges per-repo over default", _io.load_roe(_repo).auto_run_min_defcon == 2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'load_jobs reads defcon|load_roe merges'`
Expected: FAIL.

- [ ] **Step 3: Edit `coa_io.py`** — replace `_job_to_dict` and `_job_brief`:

```python
def _job_to_dict(j: Job) -> dict:
    return {
        "id": j.id, "repo": j.repo, "title": j.title, "type": j.type,
        "defcon": j.defcon, "value": j.value,
        "rationale": j.rationale, "launch": j.launch, "verify": j.verify,
        "status": j.status,
    }


def _job_brief(j: Job, roe=None) -> dict:
    from . import advisor
    appr = advisor.approval_required(j, roe) if roe is not None else (j.defcon < 3)
    return {"id": j.id, "title": j.title, "type": j.type,
            "defcon": j.defcon, "value": j.value, "approval_required": appr}
```

In `board_state`, load the repo ROE once and pass it to every `_job_brief`:

```python
def board_state(repo_path: str, running_ids=()) -> dict:
    from . import advisor  # noqa: F401  (kept local to avoid import cycle)
    ap = os.path.realpath(os.path.expanduser(repo_path))
    roe = load_roe(repo_path)
    queued = read_queue(repo_path)
    rec = read_run_record(repo_path) or {}
    finished = [j for j in (rec.get("jobs") or []) if j.get("outcome") in ("pass", "fail")]
    spoken = {j.id for j in queued} | {j.get("id") for j in finished} | set(running_ids)
    proposed = [_job_brief(j, roe) for j in load_jobs(repo_path) if j.id not in spoken]
    return {"repo": ap, "name": os.path.basename(ap),
            "proposed": proposed, "queued": [_job_brief(j, roe) for j in queued],
            "finished": finished}
```

- [ ] **Step 4: Run to verify those checks pass**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'load_jobs|load_roe merges|write_coa'`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_io.py tests/test_advisor.py
git commit -m "feat(coa): persist DEFCON in queue + board state, drop cost fields"
```

---

### Task 5: `runner.py` — delete budget layer, DEFCON drain, approval gate

**Files:**
- Modify: `src/scorched_earth/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Job`, `ROE`, `advisor.approval_required`, `coa_io`.
- Produces:
  - `plan_run(jobs, roe, *, approved=False) -> List[Tuple[Job, str]]` — dispositions `"run"` / `"blocked-roe"` / `"blocked-approval"`. (Drop `envelope` param and the spent return.)
  - `pick_next(queue, roe, *, approved=False) -> Optional[Job]` — first job ROE-allowed unattended AND (approved or not `approval_required`).
  - `JobOutcome` — replace `tier`/`est_windows`/`depth` with `defcon: int`. New outcome value `"blocked-approval"`.
  - `RunResult` — drop `available_windows`, `spent_estimated`. Keep the rest.
  - `run_queue(repo, state, *, now, date, execute=None, on_step=None, approved=False)`.
  - **Delete:** `EnvelopeTracker`, `read_envelope`, `read_headroom`, the `est_windows` accumulation. Keep `is_stale`, `detect_rate_limit`, all worktree/sandbox/git helpers, `_run_killable`, `execute_job`.

- [ ] **Step 1: Read `tests/test_runner.py` fully**, then update every `Job(...)`/`JobOutcome(...)` construction to use `defcon=` instead of `est_windows=`/`depth=`/`tier=`, delete assertions about `available_windows`/`spent_estimated`/`EnvelopeTracker`/`read_envelope`/`read_headroom`, and add:

```python
from scorched_earth.runner import plan_run, pick_next
from scorched_earth.roe import ROE
from scorched_earth.jobs import Job

_q = [Job(id="a", repo="r", title="A", type="test", defcon=4),
      Job(id="b", repo="r", title="B", type="audit", defcon=1)]  # approval-required by default

_disp = plan_run(_q, ROE())                       # unattended: not approved
check("plan_run blocks approval-required jobs unattended",
      dict((j.id, d) for j, d in _disp) == {"a": "run", "b": "blocked-approval"})
_disp2 = plan_run(_q, ROE(), approved=True)
check("plan_run runs everything once approved",
      all(d == "run" for _, d in _disp2))
check("pick_next skips approval-required unless approved",
      pick_next(_q, ROE()).id == "a" and pick_next(_q, ROE(), approved=True).id == "b")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL (import/attribute errors).

- [ ] **Step 3: Edit `runner.py`.** Replace `plan_run`:

```python
def plan_run(jobs, roe, *, approved=False):
    """Pure pre-run disposition: 'blocked-roe' (type not unattended), 'blocked-approval'
    (defcon below the gate and not approved), else 'run'. No budget — execution stops on a
    real usage-limit, not a predicted envelope."""
    from .advisor import approval_required
    out = []
    for j in jobs:
        if not _allowed_unattended(roe, j.type):
            out.append((j, "blocked-roe"))
        elif approval_required(j, roe) and not approved:
            out.append((j, "blocked-approval"))
        else:
            out.append((j, "run"))
    return out
```

Replace `pick_next`:

```python
def pick_next(queue, roe, *, approved=False):
    """First queued job ROE-allowed to run unattended and not gated behind approval (unless
    approved). Drains in given order; the queue is already DEFCON-sorted by the matcher."""
    from .advisor import approval_required
    for j in queue:
        if _allowed_unattended(roe, j.type) and (approved or not approval_required(j, roe)):
            return j
    return None
```

Update `JobOutcome`: drop `tier`, `est_windows`, `depth`; add `defcon: int = 3`. Update `RunResult`: drop `available_windows`, `spent_estimated`. Update `_outcome_for` to add a `blocked-approval` note (`f"DEFCON {job.defcon} needs approval — not run unattended."`) and build the outcome with `defcon=job.defcon` (no tier/est_windows). Update `run_one` to build `JobOutcome(..., defcon=job.defcon)`. Delete `read_envelope`, `read_headroom`, `EnvelopeTracker`.

Rewrite `run_queue` to drop the envelope and pass `approved`:

```python
def run_queue(repo, state, *, now, date, execute=None, on_step=None, approved=False):
    from . import review_report as _rev
    execute = execute or execute_job
    if is_stale(state, now):
        return None
    roe = coa_io.load_roe(repo)
    queue = coa_io.read_queue(repo)
    dispositions = plan_run(queue, roe, approved=approved)
    verdict = ((state or {}).get("recommendation") or {}).get("level", "unknown")
    repo_disp = os.path.realpath(os.path.expanduser(repo))
    rr = RunResult(generated_at=date, state="running", repo=repo_disp, verdict=verdict, note="")

    def _persist():
        rr.note = _summary(rr)
        coa_io.write_run_record(repo, _dataclass_dict(rr), date)
        html = _rev.render_review_html(rr)
        with open(os.path.join(coa_io.runs_dir(repo), f"{date}.html"), "w") as f:
            f.write(html)
        if on_step:
            on_step(rr)

    for i, (job, disp) in enumerate(dispositions, start=1):
        if disp != "run":
            rr.jobs.append(_outcome_for(job, i, disp))
            _persist()
            continue
        oc = run_one(repo, job, roe, repo_disp, i, execute=execute,
                     on_running=lambda r: (rr.jobs.append(r), _persist()))
        rr.jobs[-1] = oc
        if oc.outcome == "limit":
            rr.state = "halted"
            _persist()
            return rr
        _persist()
    rr.state = "done"
    _persist()
    return rr
```

Update `_summary` to drop the windows line:

```python
def _summary(rr):
    n = {}
    for j in rr.jobs:
        n[j.outcome] = n.get(j.outcome, 0) + 1
    parts = []
    if n.get("pass"):              parts.append(f"{n['pass']} secured")
    if n.get("fail"):              parts.append(f"{n['fail']} cratered")
    if n.get("blocked-roe"):       parts.append(f"{n['blocked-roe']} blocked (ROE)")
    if n.get("blocked-approval"):  parts.append(f"{n['blocked-approval']} need approval")
    if n.get("killed"):            parts.append(f"{n['killed']} killed")
    if n.get("running"):           parts.append(f"{n['running']} working")
    return (", ".join(parts) if parts else "no jobs") + "."
```

- [ ] **Step 4: Run the runner suite**

Run: `python3 tests/test_runner.py`
Expected: PASS (all checks).

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_runner.py
git commit -m "feat(coa): runner drains by DEFCON + approval gate, budget layer deleted"
```

---

### Task 6: `coa_serve.py` — cockpit engine without budget

**Files:**
- Modify: `src/scorched_earth/coa_serve.py` (`state_json`, `_drain_repo`)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Consumes: `advisor.match(jobs, roe)` (Task 3), `runner.pick_next(queue, roe, approved=True)` (Task 5), `coa_io.board_state` (Task 4).
- Produces: `state_json()` returns `{"repos": [...], "running": [...], "busy": bool, "weekly_reserve_pct": float|None}` — **no `headroom`, no per-job `fit`**. The cockpit is operator-driven, so its workers pick with `approved=True`.

- [ ] **Step 1: Read `tests/test_cockpit.py` fully.** Update Job/JobOutcome constructions to `defcon=`; delete assertions on `headroom`, `fit`, `max_est_windows`, `EnvelopeTracker`. Add:

```python
_sj = engine.state_json()
check("state_json drops headroom/fit", "headroom" not in _sj)
check("board briefs carry defcon + approval_required",
      all("defcon" in jb and "approval_required" in jb
          for r in _sj["repos"] for jb in r["proposed"] + r["queued"]))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL.

- [ ] **Step 3: Edit `state_json`** — remove the `headroom`/`window_headroom` computation, the `advisor.match(headroom, ...)` call, and the `fit` annotation loop. New body:

```python
    def state_json(self):
        from . import advisor
        state = self._load_state()
        snap = (state or {}).get("snapshot") or {}
        wrp = advisor.weekly_reserve_pct(snap)
        with self._lock:
            running = [dict(v) for v in self._running.values()]
            busy = bool(running) or bool(self._workers)
            running_by_repo = {}
            for v in self._running.values():
                running_by_repo.setdefault(v["repo"], []).append(v["id"])
        repos = [coa_io.board_state(r, running_by_repo.get(r, ())) for r in self.repos]
        return {"repos": repos, "running": running, "busy": busy,
                "weekly_reserve_pct": round(wrp, 0) if wrp is not None else None}
```

Edit `_drain_repo`: in the capped check drop `max_est_windows`/`spent_w` (keep only `max_jobs`); call `runner.pick_next(coa_io.read_queue(repo), roe, approved=True)`. Replace:

```python
                    rr = self._results.get(repo)
                    done_n = len(rr.jobs) if rr else 0
                    capped = roe.max_jobs is not None and done_n >= roe.max_jobs
                    job = None if capped else runner.pick_next(
                        coa_io.read_queue(repo), roe, approved=True)
```

And in the `RunResult(...)` construction inside `_drain_repo`, drop `available_windows=0.0, spent_estimated=0.0` (those fields no longer exist).

- [ ] **Step 4: Run the cockpit suite**

Run: `python3 tests/test_cockpit.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(coa): cockpit engine drops budget, surfaces DEFCON + approval"
```

---

### Task 7: `coa_report.py` + `coa_template.html` — DEFCON cards

**Files:**
- Modify: `src/scorched_earth/coa_report.py`
- Modify: `src/scorched_earth/coa_template.html`
- Test: `tests/test_advisor.py` (coa_report section + the retained advise-writes block)

**Interfaces:**
- Consumes: `COA` (Task 3, now `queue`/`blocked`/`note` only).
- Produces: `render_md(coa, generated_at)`, `render_html(coa, generated_at, *, verdict="unknown", roe_lines=None, reset_in="")`. Data blob carries per-job `defcon` + `approval_required`; aggregate carries `weeklyReservePct` (context) but **no `headroom`/`overBudget`**.

- [ ] **Step 1: Update the coa_report tests** — replace the section (~79–106) and rewrite the retained `advise writes BOTH md + html` block to the no-budget API:

```python
from scorched_earth.coa_report import render_md, render_html, _job_obj as _coa_job_obj  # noqa: E402

_md = render_md(_coa, "2026-06-25")
check("render_md lists queued jobs, date, DEFCON", "campaign" in _md and "2026-06-25" in _md
      and "DEFCON" in _md.upper() and _md.lstrip().startswith("#"))
check("render_md has no budget framing",
      "windows" not in _md.lower() and "over budget" not in _md.lower())

_html = render_html(_coa, "2026-06-25", verdict="green")
check("render_html fills the template, token substituted",
      _html.lstrip().lower().startswith("<!doctype html") and "__COA_JSON__" not in _html
      and "campaign" in _html)
check("render_html carries defcon, not headroom",
      '"defcon"' in _html and '"headroom"' not in _html)
check("_job_obj carries defcon + approval_required",
      _coa_job_obj(Job(id="z", repo="r", title="Z", type="test", defcon=1, value=7))["defcon"] == 1)

# advise path writes md + html (no headroom math)
import tempfile as _tf2, os as _os2
from scorched_earth import coa_io as _cio2
_arepo = _tf2.mkdtemp(); _os2.makedirs(_os2.path.join(_arepo, ".scorched"), exist_ok=True)
with open(_os2.path.join(_arepo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "a1", "repo": _arepo, "title": "A", "type": "docs", "defcon": 1, "value": 7}], _f)
_coaA = match(_cio2.load_jobs(_arepo), _ROE())
_mdp, _htmlp = _cio2.write_coa(_arepo, render_md(_coaA, "2026-06-25"),
                               render_html(_coaA, "2026-06-25", verdict="green"), "2026-06-25")
check("advise path writes md + html records", _os2.path.exists(_mdp) and _os2.path.exists(_htmlp))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'DEFCON|defcon, not headroom|approval_required'`
Expected: FAIL.

- [ ] **Step 3: Rewrite `coa_report.py`.** Replace `_value_label`/`_VALUE_LABELS` usage as needed and the body:

```python
_DEFCON_LABELS = {1: "DEFCON 1", 2: "DEFCON 2", 3: "DEFCON 3", 4: "DEFCON 4", 5: "DEFCON 5"}


def _row(j):
    return (j.id, _DEFCON_LABELS[j.defcon], f"{j.value:g}", j.type, j.title)


def render_md(coa, generated_at):
    lines = [f"# Course of Action — {generated_at}", "", coa.note, "",
             "## Battle plan (most critical first)", "",
             "| id | defcon | value | type | title |",
             "|----|--------|-------|------|-------|"]
    for j in coa.queue:
        lines.append("| " + " | ".join(_row(j)) + " |")
    if not coa.queue:
        lines.append("| _(none)_ | | | | |")
    lines += ["", "## Launch", ""]
    for j in coa.queue:
        appr = "  **(approval required)**" if j.defcon < 3 else ""
        lines += [f"### {j.id} — {j.title} [{_DEFCON_LABELS[j.defcon]}]{appr}", "",
                  f"> {j.rationale}", "", "```", j.launch, "```", ""]
    if coa.blocked:
        lines += ["## Blocked by ROE", ""]
        for j in coa.blocked:
            lines.append(f"- {j.id} ({j.type}): {j.title}")
    return "\n".join(lines) + "\n"


def _job_obj(j):
    return {
        "title": j.title,
        "defcon": j.defcon,
        "type": (j.type or "").upper(),
        "value": f"{j.value:g}",
        "approval_required": j.defcon < 3,
        "rationale": j.rationale,
        "command": j.launch,
    }


def render_html(coa, generated_at, *, verdict="unknown", roe_lines=None, reset_in="",
                weekly_reserve_pct=0.0):
    data = {
        "sector": "SECTOR 07",
        "date": generated_at,
        "verdict": (verdict or "unknown").lower(),
        "note": coa.note,
        "weeklyReservePct": round(weekly_reserve_pct or 0.0, 0),
        "resetIn": reset_in,
        "roe": list(roe_lines or []),
        "queue": [_job_obj(j) for j in coa.queue],
        "blocked": [_job_obj(j) for j in coa.blocked],
    }
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    return template.replace("__COA_JSON__", json.dumps(data))
```

(Delete `_value_label`/`_VALUE_LABELS`, `tier`, `est_windows`, `overBudget`, `headroom`, the `fit` arg.)

- [ ] **Step 4: Update `coa_template.html`.** Read it first. The JS reads `DATA.queue`/`DATA.overBudget`/`DATA.blocked`, and per-job `tier`/`cost`/`value`/`depth`/`fit`. Change it to: drop the `overBudget` column/section; render each job with a **DEFCON badge** from `job.defcon` (1 = red-alert, 5 = quiet — reuse existing accent classes or add `.defcon-1 … .defcon-5`); show an "APPROVAL REQUIRED" marker when `job.approval_required`; remove the headroom gauge / `DATA.headroom` reference and the dead `TIER` const; keep the `weeklyReservePct` context readout. Verify no `__COA_JSON__` literal survives in a comment.

- [ ] **Step 5: Run the suite + eyeball the HTML**

Run: `python3 tests/test_advisor.py`
Expected: PASS (whole file).
Run: `python3 -c "import sys; sys.path.insert(0,'src'); from scorched_earth.advisor import match; from scorched_earth.roe import ROE; from scorched_earth.jobs import Job; from scorched_earth.coa_report import render_html; open('/tmp/coa.html','w').write(render_html(match([Job(id='c',repo='r',title='Build backend',type='audit',defcon=1,value=9)], ROE()),'2026-06-25',verdict='green'))" && echo wrote /tmp/coa.html`
Then open `/tmp/coa.html` and confirm the DEFCON badge + approval marker render.

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/coa_report.py src/scorched_earth/coa_template.html tests/test_advisor.py
git commit -m "feat(coa): COA report + template render DEFCON badges, drop budget UI"
```

---

### Task 8: `review_report.py` + `review_template.html` — AAR DEFCON

**Files:**
- Modify: `src/scorched_earth/review_report.py`
- Modify: `src/scorched_earth/review_template.html`
- Test: `tests/test_runner.py` (review_report section)

**Interfaces:**
- Consumes: `RunResult`/`JobOutcome` (Task 5, now `defcon`, no `tier`/`est_windows`/`depth`; `RunResult` has no `available_windows`/`spent_estimated`).
- Produces: `render_review_html(rr)`, `_job_obj(jobOutcome)` carrying `defcon` (not `depth`/`tier`/`cost`).

- [ ] **Step 1: Read `review_report.py` and its tests.** Update `_job_obj` to emit `defcon` from the outcome (drop `tier`/`cost`/`depth`); remove any `available_windows`/`spent_estimated` references in the data blob. Update the test's `JobOutcome(...)` constructions to `defcon=` and assert `_job_obj(...)["defcon"]`.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL.

- [ ] **Step 3: Edit `review_report.py`** per Step 1 (mirror the `coa_report._job_obj` shape; the AAR shows outcome too). Add a `"blocked-approval"` styling/label alongside `"blocked-roe"`.

- [ ] **Step 4: Update `review_template.html`** — swap the per-job DEPTH/tier/cost readout for the DEFCON badge; remove the `available_windows`/`spent_estimated` gauge; add a label for `blocked-approval`. Read the file first; confirm no leftover token in a comment.

- [ ] **Step 5: Run the suite**

Run: `python3 tests/test_runner.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/review_report.py src/scorched_earth/review_template.html tests/test_runner.py
git commit -m "feat(coa): After-Action Report renders DEFCON, drops budget gauge"
```

---

### Task 9: `cockpit_template.html` — DEFCON board

**Files:**
- Modify: `src/scorched_earth/cockpit_template.html`
- Test: `tests/test_cockpit.py` (render check)

**Interfaces:**
- Consumes: `state_json()` (Task 6): per-job `defcon` + `approval_required`; no `headroom`/`fit`; `weekly_reserve_pct` context.

- [ ] **Step 1: Add/adjust the cockpit render test** in `tests/test_cockpit.py`:

```python
from scorched_earth.coa_serve import render_cockpit
_html = render_cockpit("tok", engine.state_json()).decode()
check("cockpit renders, token + json substituted",
      "__COCKPIT_TOKEN__" not in _html and "__COCKPIT_JSON__" not in _html)
check("cockpit template references defcon, not headroom/fit",
      "defcon" in _html.lower() and "headroom" not in _html.lower())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL.

- [ ] **Step 3: Edit `cockpit_template.html`** — read it first. Replace per-card DEPTH/cost/`fit` styling with a DEFCON badge from `job.defcon`; add an approval marker when `job.approval_required`; remove the global headroom readout and any `state.headroom`/`fit` references; keep `weekly_reserve_pct` as context. Remove the dead `TIER` const if present.

- [ ] **Step 4: Run the suite**

Run: `python3 tests/test_cockpit.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/cockpit_template.html tests/test_cockpit.py
git commit -m "feat(coa): cockpit board shows DEFCON + approval, drops headroom"
```

---

### Task 10: `bin/scorch` + `commands/coa.md` + `commands/roe.md` — CLI + expanded scan role

**Files:**
- Modify: `bin/scorch` (the `advise`/`coa`/`run`/`roe` verbs)
- Modify: `commands/coa.md`
- Modify: `commands/roe.md`
- Test: `tests/test_advisor.py` (bin/scorch verbs section)

**Interfaces:**
- Consumes: everything above. CLI `scorch advise` renders via the new `match(jobs, roe)`; `scorch coa run [--approve]` threads `approved` into `run_queue`; `scorch roe` prints the new ROE shape.

- [ ] **Step 1: Read `bin/scorch`** end-to-end. Find every use of `match(headroom, ...)`, `window_headroom`, `read_envelope`, `est_windows`, `depth`, `tier`, `max_windows`. Update the bin verb tests in `tests/test_advisor.py` to the new ROE (the existing `"max_windows" in _p3.stdout` assertion must change):

```python
_p3 = subprocess.run([sys.executable, _scorch, "roe", _r], capture_output=True, text=True, env=_env)
check("scorch roe prints JSON", _p3.returncode == 0 and "auto_run_min_defcon" in _p3.stdout)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py 2>&1 | grep -iE 'scorch roe prints'`
Expected: FAIL.

- [ ] **Step 3: Edit `bin/scorch`:**
  - `advise`: call `match(jobs, roe)` (no headroom); pass `weekly_reserve_pct=advisor.weekly_reserve_pct(snap)` and `verdict`/`reset_in` into `render_html`. Drop any headroom/over-budget readout in the text output; print the DEFCON-ordered plan with an approval marker for DEFCON < gate.
  - `coa run`: add an `--approve` flag; pass `approved=<flag>` into `run_queue`.
  - `roe`: ensure it dumps the new ROE dataclass (reflective dump already works if it serializes `dataclasses.asdict(load_roe(repo))`).

- [ ] **Step 4: Expand the scan prompt — `commands/coa.md`.** This is the role addition. Rewrite the scan instructions so the agent emits jobs with `defcon` (1–5) + `value` + `rationale` + `launch` and **explicitly hunts the full spectrum**. Include this directive block verbatim in the command body:

```
Rate every job by DEFCON — its IMPACT on the project, never its effort or length:
  - DEFCON 1: project-defining overnight campaigns. Actively look for these. Examples:
    build an entire roadmap phase (e.g. a whole backend) in one pass; generate a complete
    regression + UI-capability test harness; an exhaustive line-by-line security audit of
    every file; a deep research/analysis spike. Framed as "approve, walk away, wake up to
    it done — pending approve/rollback."
  - DEFCON 2: a whole feature/subsystem or a significant refactor.
  - DEFCON 3: a normal feature or meaningful fix.
  - DEFCON 4: small TODO knockouts, cleanups.
  - DEFCON 5: cosmetic/trivial (typos, comments, formatting).
Do NOT estimate effort, duration, or window cost. Surface BOTH extreme DEFCON-1 campaigns
AND ordinary knockouts in the same scan. Emit each job as:
  {"id","repo","title","type","defcon",1-5,"value",0-10 tie-break,"rationale","launch"}
```

  - Remove any old depth/window/tier instructions from `coa.md`.

- [ ] **Step 5: Update `commands/roe.md`** — drop `max_windows`/`per_job_max_windows`/`max_est_windows` from the documented rules; document `auto_run_min_defcon` (default 3, gates DEFCON 1–2 behind approval) and that `max_jobs` is the run-length leash.

- [ ] **Step 6: Run the full advisor suite**

Run: `python3 tests/test_advisor.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bin/scorch commands/coa.md commands/roe.md tests/test_advisor.py
git commit -m "feat(coa): CLI + scan prompt hunt DEFCON-1 overnight campaigns, --approve gate"
```

---

### Task 11: Full sweep + docs

**Files:**
- Modify: `CLAUDE.md` (architecture lines for `jobs.py`/`advisor.py`/`roe.py`/`runner.py` if their one-liners mention budget/depth), `docs/playbook.md` (Current Status), `TODO.md`.
- Test: all four suites.

- [ ] **Step 1: Grep for stragglers**

Run: `grep -rniE 'est_windows|headroom|windows_for_depth|EnvelopeTracker|max_windows|window_headroom|\\btier\\b|over_budget|\\bdepth\\b' src/ bin/ commands/ skills/ docs/the-math.md`
Expected: no functional references remain (design-spec/plan docs may still mention them historically — that's fine).

- [ ] **Step 2: Run every suite**

Run: `python3 tests/test_scorched.py && python3 tests/test_advisor.py && python3 tests/test_runner.py && python3 tests/test_cockpit.py`
Expected: all green; `test_scorched.py` still reports **57 checks passed**.

- [ ] **Step 3: Update docs.** In `CLAUDE.md`, adjust the one-line descriptions of `jobs.py`/`advisor.py`/`roe.py`/`runner.py` to the DEFCON model. In `docs/playbook.md`, update Current Status. In `TODO.md`, check off the DEFCON work and note the budget-estimation removal. Leave `docs/the-math.md` alone (it's the weekly-burn model, unchanged).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/playbook.md TODO.md
git commit -m "docs: DEFCON COA model — architecture lines, playbook, TODO"
```

---

## Self-Review

**Spec coverage:** §1 jobs → Task 1; §2 matcher → Task 3; §3 ROE → Task 2; §4 runner+cockpit → Tasks 5, 6; §5 scan role → Task 10; §6 reports/templates → Tasks 7, 8, 9; §7 tests → woven into each task + Task 11 sweep. coa_io serialization (implied by §1/§4) → Task 4. All covered.

**Placeholder scan:** No TBDs. Template tasks (4/8/9) are directive-style by necessity (design-handoff HTML must be read and adapted), but each names the exact data-contract change, the exact removals, and a concrete render test — not "handle the rest."

**Type consistency:** `match(jobs, roe)` (no headroom) is consistent across advisor, coa_serve, coa_report, bin. `Job.defcon`/`value` only (no est_windows/depth/tier) across jobs, coa_io, runner, reports. `approval_required(job, roe)` defined in advisor (Task 3), consumed in coa_io (4), runner (5). `pick_next(queue, roe, approved=)` / `plan_run(jobs, roe, approved=)` consistent between runner (5) and coa_serve (6). `JobOutcome.defcon` consistent between runner (5), review_report (8), test (8/9).
