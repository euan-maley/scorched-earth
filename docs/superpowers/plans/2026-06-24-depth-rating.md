# Per-Task DEPTH Rating (replace shown window-cost) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop showing a fake-precise per-task window cost. Each task is rated **DEPTH 1–10** (the scan agent's honest relative magnitude); the window cost the matcher/runner need is *derived* from depth and kept internal — never displayed per-card.

**Architecture:** The agent emits `depth` (1–10). `jobs.py` derives `est_windows = windows_for_depth(depth)` (coarse band) for the unchanged budget math; legacy jobs that carry only `est_windows` derive a display `depth` (inverse band). Python renderers add `depth` to their per-job dicts; the three card templates show DEPTH and drop the per-card window cost + S/M/L/XL tier badge. The **aggregate** budget gauges (COA envelope, AAR/cockpit spend) are unchanged — they're about the real budget, not a per-task estimate.

**Tech Stack:** Python 3.8+ stdlib. Touches `jobs.py`, `coa_report.py`, `review_report.py`, `coa_io.py`, the three `*_template.html`, `commands/coa.md`, tests.

## Global Constraints (the locked decisions)

- **Stdlib only.** Python 3.8 floor: `from __future__ import annotations`; no `match`; no runtime `X | Y` unions.
- **Never touch core.py, calibrate.py, statusline.py.**
- **Depth is the agent's primary signal.** The scan agent emits `depth` (int 1–10). `est_windows` is **derived** from it and is internal-only (never shown per-card).
- **Coarse depth→windows map (one function, `jobs.windows_for_depth`):** `1–2 → 0.25 · 3–4 → 0.5 · 5–6 → 1.0 · 7–8 → 2.0 · 9–10 → 3.5`.
- **Inverse for legacy (`jobs.depth_for_windows`):** representative depth per band — `≤0.375 → 2 · ≤0.75 → 4 · ≤1.5 → 6 · ≤2.75 → 8 · else → 10`.
- **Backward-compatible both ways:** a job dict with `depth` → derive windows; a legacy dict with only `est_windows` (no depth) → derive a display depth. A dict needs `id` + `value` + **at least one of** `depth`/`est_windows`, else it's skipped.
- **Per-card display = DEPTH N/10** (a compact label, optionally a small 10-segment bar styled to each template). The per-card window cost (`EST ~Xw` / `job.cost` / `estWindows`) and the **tier badge (S/M/L/XL)** are removed from the cards.
- **Aggregate gauges unchanged.** The COA envelope and the AAR/cockpit "budget spent" gauges keep using `est_windows` (they're aggregate budget, in scope-out of this change). `est_windows`, `value`, and `j.tier` stay in the data dicts (additive `depth`) so the gauges and any math keep working — only the per-card *rendering* changes.
- **The matcher (`advisor.match`) and runner accounting are untouched** — they read `est_windows`, which is now derived but still present.
- **Tests** extend `tests/test_advisor.py` (jobs/renderers) and `tests/test_cockpit.py` (board_state depth). Keep all suites green.

---

### Task 1: `jobs.py` depth field + mappings + parse_jobs (both-ways); agent instruction

**Files:**
- Modify: `src/scorched_earth/jobs.py`
- Modify: `commands/coa.md` (scan-agent emits depth)
- Test: `tests/test_advisor.py`

**Interfaces:**
- Produces: `Job.depth: int` (default 5); `windows_for_depth(depth: int) -> float`; `depth_for_windows(w: float) -> int`. `parse_jobs` accepts a dict with `depth` and/or `est_windows` (id+value required; at least one cost field) and fills both `depth` and `est_windows` (deriving the missing one).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_advisor.py` (before the final summary `print`):

```python
# --- depth rating ----------------------------------------------------------------
from scorched_earth.jobs import windows_for_depth, depth_for_windows  # noqa: E402

check("windows_for_depth coarse bands",
      (windows_for_depth(1), windows_for_depth(4), windows_for_depth(6),
       windows_for_depth(8), windows_for_depth(10)) == (0.25, 0.5, 1.0, 2.0, 3.5))
check("windows_for_depth clamps out-of-range", windows_for_depth(0) == 0.25 and windows_for_depth(99) == 3.5)
check("depth_for_windows inverse bands",
      (depth_for_windows(0.25), depth_for_windows(0.5), depth_for_windows(1.0),
       depth_for_windows(2.0), depth_for_windows(3.5)) == (2, 4, 6, 8, 10))

_dj = parse_jobs([{"id": "a", "title": "A", "type": "test", "depth": 7, "value": 8}])[0]
check("parse_jobs: depth job derives est_windows", _dj.depth == 7 and _dj.est_windows == 2.0)
_lj = parse_jobs([{"id": "b", "title": "B", "type": "test", "est_windows": 1.0, "value": 5}])[0]
check("parse_jobs: legacy est_windows job derives a display depth", _lj.est_windows == 1.0 and _lj.depth == 6)
check("parse_jobs: a dict with neither depth nor est_windows is skipped",
      parse_jobs([{"id": "c", "value": 3}]) == [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL — `ImportError: cannot import name 'windows_for_depth'`.

- [ ] **Step 3: Implement in `jobs.py`**

Add the mapping functions (near `tier_for`):

```python
# Coarse depth(1-10) -> internal window-cost band. The agent rates depth (it's good at
# relative magnitude); est_windows is derived for the budget matcher/runner only — never shown.
_DEPTH_WINDOWS = {1: 0.25, 2: 0.25, 3: 0.5, 4: 0.5, 5: 1.0, 6: 1.0, 7: 2.0, 8: 2.0, 9: 3.5, 10: 3.5}


def windows_for_depth(depth: int) -> float:
    return _DEPTH_WINDOWS[max(1, min(10, int(depth)))]


def depth_for_windows(w: float) -> int:
    """Representative display depth for a legacy job that carries only est_windows."""
    if w <= 0.375:
        return 2
    if w <= 0.75:
        return 4
    if w <= 1.5:
        return 6
    if w <= 2.75:
        return 8
    return 10
```

Add `depth` to the `Job` dataclass (after `value`):

```python
    est_windows: float            # INTERNAL cost (window-units), derived from depth; not shown
    value: float                  # the scan agent's worth ranking, drives priority
    depth: int = 5                # 1-10 agent-rated cost/depth — the DISPLAYED magnitude
```

Rewrite `parse_jobs` to accept depth and/or est_windows:

```python
def parse_jobs(data, repo: str = "") -> List[Job]:
    """Build Jobs from a list of dicts. Each needs id + value + at least one cost field
    (depth, 1-10, or legacy est_windows). Fills both: depth-> est_windows (windows_for_depth),
    or legacy est_windows -> a display depth (depth_for_windows)."""
    out: List[Job] = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        if d.get("id") is None or d.get("value") is None:
            continue
        has_depth = d.get("depth") is not None
        has_win = d.get("est_windows") is not None
        if not (has_depth or has_win):
            continue
        if has_depth:
            depth = max(1, min(10, int(d["depth"])))
            est = windows_for_depth(depth)
        else:
            est = float(d["est_windows"])
            depth = depth_for_windows(est)
        out.append(Job(
            id=str(d["id"]),
            repo=d.get("repo") or repo,
            title=d.get("title", ""),
            type=d.get("type", "other"),
            est_windows=est,
            value=float(d["value"]),
            depth=depth,
            rationale=d.get("rationale", ""),
            launch=d.get("launch", ""),
            verify=d.get("verify", ""),
            status=d.get("status", "proposed"),
        ))
    return out
```

(Keep the `tier` property as-is — still derived from `est_windows`, used by aggregate/legacy; just not shown per-card.)

- [ ] **Step 4: Update the scan-agent instruction in `commands/coa.md`**

In `commands/coa.md`, find where the scan agent is told to emit job fields (the est_windows / sizing instruction). Update it so the agent emits a **`depth` integer 1–10** (its honest relative cost/depth rating) instead of guessing `est_windows`. Add one line: depth 1–2 = a quick strike, 9–10 = a major multi-window operation; the tool derives the budget cost from depth, so the agent never estimates windows. (Read the surrounding instruction first and match its voice.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_advisor.py && python3 tests/test_scorched.py && python3 tests/test_runner.py && python3 tests/test_cockpit.py`
Expected: all green (advisor +6). The matcher tests still pass (they pass `est_windows` directly via `Job(...)`, which still works).

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/jobs.py commands/coa.md tests/test_advisor.py
git commit -m "feat(depth): Job.depth 1-10 + windows<->depth maps; agent emits depth"
```

---

### Task 2: renderers emit `depth`

**Files:**
- Modify: `src/scorched_earth/coa_report.py` (`_job_obj`)
- Modify: `src/scorched_earth/review_report.py` (`_job_obj`)
- Modify: `src/scorched_earth/coa_io.py` (`_job_brief`)
- Test: `tests/test_advisor.py`, `tests/test_cockpit.py`

**Interfaces:** each per-job dict gains `"depth": j.depth` (additive — existing keys kept).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_advisor.py` (renderers) :

```python
# depth flows into the rendered job dicts
from scorched_earth.coa_report import _job_obj as _coa_job_obj  # noqa: E402
from scorched_earth.review_report import _job_obj as _aar_job_obj  # noqa: E402
_dj2 = parse_jobs([{"id": "z", "title": "Z", "type": "test", "depth": 8, "value": 7}])[0]
check("coa_report _job_obj carries depth", _coa_job_obj(_dj2)["depth"] == 8)
```

And append to `tests/test_cockpit.py` (board_state brief) before its final print:

```python
# board_state job briefs carry depth
_rb2 = tempfile.mkdtemp(); os.makedirs(os.path.join(_rb2, ".scorched"), exist_ok=True)
with open(os.path.join(_rb2, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "g", "title": "G", "type": "test", "depth": 9, "value": 6}], _f)
check("board_state brief carries depth", _io.board_state(_rb2)["proposed"][0]["depth"] == 9)
```

(For the AAR `_job_obj`, it takes a `JobOutcome`, not a `Job`. `JobOutcome` has no `depth` field. Add `depth` to `JobOutcome` in runner.py with default 5, populate it where outcomes are built from jobs, and emit it. See Step 3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_advisor.py`
Expected: FAIL — `KeyError: 'depth'`.

- [ ] **Step 3: Implement**

In `coa_report._job_obj`, add `"depth": j.depth,` to the returned dict (keep the existing keys including `cost`/`tier` for now — the template stops reading them in Task 3).

In `coa_io._job_brief`, add `"depth": j.depth`:

```python
def _job_brief(j: Job) -> dict:
    return {"id": j.id, "title": j.title, "type": j.type, "tier": j.tier,
            "depth": j.depth, "est_windows": j.est_windows, "value": j.value}
```

For the AAR: add a `depth: int = 5` field to `JobOutcome` (in `runner.py`), populate it in `run_one` (`depth=job.depth`) and in `_outcome_for` (`depth=job.depth`), and add `"depth": j.depth` to `review_report._job_obj`. The AAR test:

```python
check("aar _job_obj carries depth",
      _aar_job_obj(JobOutcome(seq=1, id="x", title="x", type="test", tier="M",
                              outcome="pass", est_windows=1.0, depth=8))["depth"] == 8)
```
(add `from scorched_earth.runner import JobOutcome` if not already imported in test_advisor — or place this AAR check in test_cockpit where JobOutcome is in scope. Put it wherever JobOutcome is already imported.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_advisor.py && python3 tests/test_cockpit.py && python3 tests/test_runner.py && python3 tests/test_scorched.py`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_report.py src/scorched_earth/review_report.py src/scorched_earth/coa_io.py src/scorched_earth/runner.py tests/
git commit -m "feat(depth): renderers + JobOutcome carry depth"
```

---

### Task 3: templates show DEPTH, drop per-card cost + tier

**Files:**
- Modify: `src/scorched_earth/coa_template.html`
- Modify: `src/scorched_earth/review_template.html`
- Modify: `src/scorched_earth/cockpit_template.html`
- Test: `tests/test_cockpit.py`

**Interfaces:** none (display only). Each per-job CARD shows a `DEPTH N/10` indicator (a compact label, optionally a small 10-segment bar matching the template's palette) and NO per-card window cost or S/M/L/XL tier badge. Aggregate gauges (envelope / "budget spent") are untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py` (render-check — cockpit card now references depth):

```python
# cockpit cards render depth (and no per-card window-cost label "EST ~")
_hk2 = render_cockpit("tk", {"repos": [], "running": None, "busy": False}).decode("utf-8")
check("cockpit template renders job depth", "depth" in _hk2.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — the cockpit template doesn't reference `depth` yet.

- [ ] **Step 3: Edit the three templates**

For each template, in the per-JOB card render, REMOVE the window-cost element and the tier badge, and ADD a DEPTH indicator reading `DEPTH N/10` (style a small bar if it fits the aesthetic). Keep the literal injection tokens (`__COA_JSON__` / `__REVIEW_JSON__` / `__COCKPIT_TOKEN__` / `__COCKPIT_JSON__`) appearing exactly once at their existing sites — do NOT introduce a token string in any new comment.

- **cockpit_template.html:** replace the three `EST ~'+fmt(job.est_windows)+'w` spans (proposed/queued/running card branches, ~lines 298/305/308) with a `DEPTH '+ (job.depth||'?') +'/10` span; remove the tier `cval` span (~line 317). Leave the status-bar budget computation (`est_windows` sum, ~lines 420/422) UNCHANGED — that's the aggregate gauge.
- **review_template.html (AAR):** replace `EST <b>~${fmt(j.estWindows)} win</b>` (~line 285) with `DEPTH <b>${j.depth}/10</b>`; remove the `tier` badge span (~line 300). Leave the ammo/budget gauge (envelope) UNCHANGED.
- **coa_template.html:** replace the `job__cost` element (`${esc(job.cost)}`, ~lines 258/281) with a `DEPTH ${job.depth}/10` element; remove the tier badge (~lines 243/273). Leave the envelope/ammo gauge UNCHANGED. (Optionally update the `cost:` line in the header data-shape comment to `depth:` — but ensure `__COA_JSON__` does not appear in that comment.)

After editing, the per-card display shows DEPTH; the aggregate gauges still show their window/% figures.

- [ ] **Step 4: Update `commands/coa.md` / docs note (optional) + run tests**

Run: `python3 tests/test_cockpit.py && python3 tests/test_advisor.py && python3 tests/test_runner.py && python3 tests/test_scorched.py`
Expected: all green. Also confirm each template still renders without a token leak:
`python3 -c "import sys;sys.path.insert(0,'src');from scorched_earth.coa_serve import render_cockpit;h=render_cockpit('t',{'repos':[],'running':None,'busy':False}).decode();assert '__COCKPIT_' not in h"`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_template.html src/scorched_earth/review_template.html src/scorched_earth/cockpit_template.html tests/test_cockpit.py
git commit -m "feat(depth): cards show DEPTH 1-10, drop per-card window-cost + tier badge"
```

---

## Self-Review

**1. Coverage:** depth field + maps + parse both-ways (Task 1); agent emits depth (Task 1, coa.md); renderers carry depth (Task 2); cards display depth, drop cost+tier, aggregate gauges untouched (Task 3); matcher/runner read derived est_windows unchanged (Global Constraints). ✓
**2. Placeholders:** none. Template edits are described per-file with exact anchor lines; the implementer styles the DEPTH indicator to each template.
**3. Consistency:** `windows_for_depth`/`depth_for_windows`, `Job.depth`, `JobOutcome.depth`, `"depth"` dict key — consistent across Tasks 1–3. Aggregate gauges (`est_windows`) deliberately retained.
