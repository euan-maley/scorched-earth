# COA Advisor (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase-1 advisor: link repos, scan them for expensive work, budget-match it to available burn, and present a ranked Course of Action you run yourself.

**Architecture:** New modules isolated from the pure statusline hot path. Deterministic parts (job schema, ROE merge, the tier-and-fill matcher, rendering) are pure Python; the adversarial scan is orchestrated by the `/coa` slash command (a Claude agent), which writes a JSON job list the matcher consumes. Config is JSON throughout, mirroring the existing `state.py` I/O patterns.

**Tech Stack:** Python ≥ 3.8, stdlib only. Markdown slash commands. The project's custom `check()` test harness (no pytest).

## Global Constraints

- Python ≥ 3.8, **stdlib only**, no pip dependencies. (`pyproject.toml` floor.)
- **JSON config throughout** (`repos.json`, `roe.default.json`, `<repo>/.scorched/roe.json`, `<repo>/.scorched/jobs.json`). No TOML.
- `core.py` and the statusline hot path stay **untouched**. The advisor is a separate module that only *reads* `state.json`; it is never in the statusline path.
- **Honesty rule:** the COA refuses to fabricate a plan when there is no budget data, exactly as `--report` refuses a zeros dashboard.
- Central state lives under `~/.claude/scorched-earth/`; per-repo files live under `<repo>/.scorched/`.
- Tests use the project's `check(name, cond)` harness in `tests/test_advisor.py`, run with `python3 tests/test_advisor.py` (NOT pytest). State files written under a temp `HOME` in tests.
- Surfaces: standalone `/coa` and `/roe` commands; `scorch link|advise|roe` CLI verbs underneath.

---

## File Structure

- `src/scorched_earth/jobs.py` — `Job` dataclass, `parse_jobs()`, `tier_for()`. Pure.
- `src/scorched_earth/roe.py` — `ROE` dataclass, `DEFAULT_ROE`, `roe_from_dict()`, `merge_roe()`. Pure.
- `src/scorched_earth/advisor.py` — `COA` dataclass, `match()` (envelope + tier-and-fill). Pure.
- `src/scorched_earth/coa_report.py` — `render_md(coa)`, `render_html(coa)`. Pure.
- `src/scorched_earth/coa_io.py` — repos registry, ROE/job loaders, COA output paths/writers. I/O, reuses `state._read_json`/`_write_json`.
- `bin/scorch` — add `link` / `advise` / `roe` verb dispatch (existing flag parser untouched).
- `commands/coa.md`, `commands/roe.md` — slash commands (scan orchestration + `scorch` calls).
- `tests/test_advisor.py` — new test harness file.
- `.github/workflows/*.yml`, `CLAUDE.md`, `docs/playbook.md` — wire CI + docs.

---

### Task 1: Job schema (`jobs.py`)

**Files:**
- Create: `src/scorched_earth/jobs.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Produces: `tier_for(est_windows: float) -> str` (returns "S"|"M"|"L"|"XL"); `Job` dataclass with fields `id, repo, title, type, est_windows, value, rationale, launch, status` and a `.tier` property; `parse_jobs(data, repo="") -> list[Job]` (skips malformed entries missing `id`/`est_windows`/`value`).

- [ ] **Step 1: Create the test file with the harness header and a first failing test**

```python
"""Advisor tests. Run: python3 tests/test_advisor.py"""

import json
import os
import subprocess
import sys
import tempfile

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

passed = 0
failures = []


def check(name, cond):
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}")


# --- jobs.py ---------------------------------------------------------------------
from scorched_earth.jobs import Job, parse_jobs, tier_for  # noqa: E402

check("tier_for buckets by est_windows",
      (tier_for(0.4), tier_for(1.0), tier_for(2.5), tier_for(6)) == ("S", "M", "L", "XL"))

_parsed = parse_jobs([
    {"id": "a", "title": "x", "type": "test", "est_windows": 2.0, "value": 8},
    {"id": "b", "est_windows": 0.3, "value": 1},        # minimal valid
    {"title": "no id"},                                  # dropped: no id
], repo="/tmp/r")
check("parse_jobs keeps valid, drops malformed", len(_parsed) == 2)
check("parse_jobs fills repo + tier", _parsed[0].repo == "/tmp/r" and _parsed[0].tier == "L")


print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scorched_earth.jobs'`

- [ ] **Step 3: Create `src/scorched_earth/jobs.py`**

```python
"""Job schema for the COA advisor: the expensive-work items a repo scan produces and the
budget matcher consumes. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

# Upper bounds (in 5h-window-units) for the human-readable tier label. Above L -> XL.
_TIER_BOUNDS = (("S", 0.5), ("M", 1.5), ("L", 3.0))


def tier_for(est_windows: float) -> str:
    for name, upper in _TIER_BOUNDS:
        if est_windows <= upper:
            return name
    return "XL"


@dataclass
class Job:
    id: str
    repo: str
    title: str
    type: str
    est_windows: float            # rough cost in window-units, emitted by the scan agent
    value: float                  # the scan agent's worth ranking, drives priority
    rationale: str = ""
    launch: str = ""              # prompt/command to run it (Phase 1 hands this to the user)
    status: str = "proposed"      # proposed | queued | done (Phase 2+ uses this)

    @property
    def tier(self) -> str:
        return tier_for(self.est_windows)


def parse_jobs(data, repo: str = "") -> List[Job]:
    """Build Jobs from a list of dicts (e.g. parsed .scorched/jobs.json). Entries missing the
    matcher inputs (id, est_windows, value) are skipped rather than crashing."""
    out: List[Job] = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        if d.get("id") is None or d.get("est_windows") is None or d.get("value") is None:
            continue
        out.append(Job(
            id=str(d["id"]),
            repo=d.get("repo") or repo,
            title=d.get("title", ""),
            type=d.get("type", "other"),
            est_windows=float(d["est_windows"]),
            value=float(d["value"]),
            rationale=d.get("rationale", ""),
            launch=d.get("launch", ""),
            status=d.get("status", "proposed"),
        ))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`3 checks passed.`)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/jobs.py tests/test_advisor.py
git commit -m "feat(advisor): job schema (parse_jobs, tier_for)"
```

---

### Task 2: Rules of Engagement (`roe.py`)

**Files:**
- Create: `src/scorched_earth/roe.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Produces: `ROE` dataclass with fields `max_windows: Optional[float]`, `per_job_max_windows: Optional[float]`, `min_weekly_left: float`, `allowed_types: Optional[List[str]]`, `exclude_paths: List[str]`, `goals: List[str]`; `DEFAULT_ROE` (permissive); `roe_from_dict(d, base=DEFAULT_ROE) -> ROE` (base overlaid by keys present in `d`); `merge_roe(base: ROE, override: ROE) -> ROE`.

- [ ] **Step 1: Add the failing test (insert above the final `print` footer in `tests/test_advisor.py`)**

```python
# --- roe.py ----------------------------------------------------------------------
from scorched_earth.roe import ROE, DEFAULT_ROE, roe_from_dict, merge_roe  # noqa: E402

check("DEFAULT_ROE is permissive",
      DEFAULT_ROE.max_windows is None and DEFAULT_ROE.allowed_types is None)

_roe = roe_from_dict({"max_windows": 2, "allowed_types": ["test"]})
check("roe_from_dict overlays only given keys",
      _roe.max_windows == 2 and _roe.allowed_types == ["test"] and _roe.min_weekly_left == 0.0)

_merged = merge_roe(roe_from_dict({"max_windows": 9, "goals": ["a"]}),
                    roe_from_dict({"max_windows": 2}))
check("merge_roe: override wins where set, base kept otherwise",
      _merged.max_windows == 2 and _merged.goals == ["a"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scorched_earth.roe'`

- [ ] **Step 3: Create `src/scorched_earth/roe.py`**

```python
"""Rules of Engagement: the confines that bound the advisor (and, later, the executor).
Three families: cost, task, goal. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import List, Optional


@dataclass
class ROE:
    # cost rules
    max_windows: Optional[float] = None             # cap total burn per COA (window-units)
    per_job_max_windows: Optional[float] = None     # reject any single job bigger than this
    min_weekly_left: float = 0.0                    # don't propose unless weekly-left above this
    # task rules
    allowed_types: Optional[List[str]] = None       # None = all types allowed
    # goal rules
    exclude_paths: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)


DEFAULT_ROE = ROE()


def roe_from_dict(d, base: ROE = DEFAULT_ROE) -> ROE:
    """Overlay the keys present in `d` onto `base`. Unknown keys are ignored."""
    d = d or {}
    names = {f.name for f in fields(ROE)}
    kwargs = {f.name: getattr(base, f.name) for f in fields(ROE)}
    for k, v in d.items():
        if k in names and v is not None:
            kwargs[k] = v
    return ROE(**kwargs)


def merge_roe(base: ROE, override: ROE) -> ROE:
    """Per-repo ROE over global default. A field on `override` wins only if it differs from
    the dataclass default (i.e. it was actually set)."""
    blank = ROE()
    kwargs = {}
    for f in fields(ROE):
        ov = getattr(override, f.name)
        kwargs[f.name] = ov if ov != getattr(blank, f.name) else getattr(base, f.name)
    return ROE(**kwargs)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`6 checks passed.`)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/roe.py tests/test_advisor.py
git commit -m "feat(advisor): ROE schema + merge"
```

---

### Task 3: The matcher (`advisor.py`)

**Files:**
- Create: `src/scorched_earth/advisor.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Consumes: `Job` (Task 1), `ROE` (Task 2).
- Produces: `COA` dataclass with fields `queue: List[Job]`, `skipped: List[Job]`, `envelope_windows: float`, `spent_windows: float`, `note: str`; `match(available_windows: float, jobs: List[Job], roe: ROE) -> COA`. `available_windows` is the already-sleep-discounted figure from `recommendation.windows_left`.

- [ ] **Step 1: Add the failing test (insert above the footer)**

```python
# --- advisor.py (matcher) --------------------------------------------------------
from scorched_earth.advisor import COA, match  # noqa: E402

_jobs = [
    Job(id="big", repo="r", title="big", type="audit", est_windows=3.0, value=6),
    Job(id="cheap", repo="r", title="cheap", type="test", est_windows=1.0, value=5),  # best density
    Job(id="docs", repo="r", title="docs", type="docs", est_windows=1.0, value=2),
]
_coa = match(2.5, _jobs, DEFAULT_ROE)
check("match fills by value-per-window within envelope",
      [j.id for j in _coa.queue] == ["cheap", "docs"] and _coa.spent_windows == 2.0)
check("match records what spilled over", [j.id for j in _coa.skipped] == ["big"])

_coa_cap = match(10, _jobs, roe_from_dict({"max_windows": 1.0}))
check("match honors ROE max_windows", [j.id for j in _coa_cap.queue] == ["cheap"])

_coa_type = match(10, _jobs, roe_from_dict({"allowed_types": ["docs"]}))
check("match drops disallowed types", [j.id for j in _coa_type.queue] == ["docs"])

_coa_empty = match(0.0, _jobs, DEFAULT_ROE)
check("zero capacity yields empty queue with a note",
      _coa_empty.queue == [] and "nothing to burn" in _coa_empty.note.lower())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scorched_earth.advisor'`

- [ ] **Step 3: Create `src/scorched_earth/advisor.py`**

```python
"""Budget-to-job matcher: the tier-and-fill core. Given the available burn (window-units) and
a list of Jobs, greedily select the highest value-per-window jobs that fit, honoring the ROE
cost and task rules. Pure, stdlib only. Reads no files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .jobs import Job
from .roe import ROE

_EPS = 1e-9


@dataclass
class COA:
    queue: List[Job] = field(default_factory=list)      # selected, in run order
    skipped: List[Job] = field(default_factory=list)    # didn't fit or disallowed
    envelope_windows: float = 0.0                       # capacity used for matching
    spent_windows: float = 0.0                          # sum of selected est_windows
    note: str = ""


def match(available_windows: float, jobs: List[Job], roe: ROE) -> COA:
    envelope = max(0.0, available_windows)
    if roe.max_windows is not None:
        envelope = min(envelope, roe.max_windows)

    eligible: List[Job] = []
    skipped: List[Job] = []
    for j in jobs:
        if roe.allowed_types is not None and j.type not in roe.allowed_types:
            skipped.append(j)
            continue
        if roe.per_job_max_windows is not None and j.est_windows > roe.per_job_max_windows:
            skipped.append(j)
            continue
        eligible.append(j)

    # Highest value-per-window first; ties by raw value.
    eligible.sort(key=lambda j: (j.value / j.est_windows if j.est_windows > 0 else 0.0, j.value),
                  reverse=True)

    queue: List[Job] = []
    spent = 0.0
    for j in eligible:
        if spent + j.est_windows <= envelope + _EPS:
            queue.append(j)
            spent += j.est_windows
        else:
            skipped.append(j)

    if envelope <= _EPS:
        note = "Nothing to burn right now: no available capacity."
    elif not queue:
        note = "Budget available but no eligible jobs fit the rules of engagement."
    else:
        note = f"Queued {len(queue)} job(s), ~{spent:.1f} of {envelope:.1f} windows."
    return COA(queue=queue, skipped=skipped, envelope_windows=envelope,
               spent_windows=spent, note=note)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`11 checks passed.`)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/advisor.py tests/test_advisor.py
git commit -m "feat(advisor): tier-and-fill matcher"
```

---

### Task 4: Renderers (`coa_report.py`)

**Files:**
- Create: `src/scorched_earth/coa_report.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Consumes: `COA` (Task 3).
- Produces: `render_md(coa: COA, generated_at: str) -> str`; `render_html(coa: COA, generated_at: str) -> str`. Both pure (take a pre-formatted date string so they stay deterministic / clock-free).

- [ ] **Step 1: Add the failing test (insert above the footer)**

```python
# --- coa_report.py ---------------------------------------------------------------
from scorched_earth.coa_report import render_md, render_html  # noqa: E402

_md = render_md(_coa, "2026-06-24")
check("render_md lists queued jobs and the date",
      "cheap" in _md and "2026-06-24" in _md and _md.lstrip().startswith("#"))
_html = render_html(_coa, "2026-06-24")
check("render_html is a self-contained doc with the title",
      _html.lstrip().lower().startswith("<!doctype html") and "COURSE OF ACTION" in _html.upper())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scorched_earth.coa_report'`

- [ ] **Step 3: Create `src/scorched_earth/coa_report.py`**

```python
"""Render a COA result to Markdown (the record) and HTML (the presentation). Both render from
the same COA object so they never disagree. Pure; the caller passes a formatted date string."""

from __future__ import annotations

import html as _html

from .advisor import COA


def _row(j):
    return (j.id, j.tier, f"{j.est_windows:.1f}", f"{j.value:g}", j.type, j.title)


def render_md(coa: COA, generated_at: str) -> str:
    lines = [f"# Course of Action — {generated_at}", "", coa.note, "",
             "## Queue", "", "| id | tier | windows | value | type | title |",
             "|----|------|---------|-------|------|-------|"]
    for j in coa.queue:
        lines.append("| " + " | ".join(_row(j)) + " |")
    if not coa.queue:
        lines.append("| _(none)_ | | | | | |")
    lines += ["", "## Launch", ""]
    for j in coa.queue:
        lines += [f"### {j.id} — {j.title}", "", f"> {j.rationale}", "", "```", j.launch, "```", ""]
    if coa.skipped:
        lines += ["## Left on the table", ""]
        for j in coa.skipped:
            lines.append(f"- {j.id} ({j.tier}, {j.est_windows:.1f}w): {j.title}")
    return "\n".join(lines) + "\n"


def render_html(coa: COA, generated_at: str) -> str:
    e = _html.escape
    rows = ""
    for j in coa.queue:
        rows += ("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"
                 .format(*[e(str(c)) for c in _row(j)]))
    if not rows:
        rows = '<tr><td colspan="6">(none)</td></tr>'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Scorched Earth · Course of Action</title>
<style>
  body{{background:#0b0705;color:#f4e4c8;font-family:ui-monospace,Menlo,monospace;padding:28px}}
  h1{{color:#ff8a1f;letter-spacing:2px}}
  table{{border-collapse:collapse;width:100%;margin-top:12px}}
  td,th{{border:1px solid #6b4a2b;padding:6px 10px;text-align:left}}
  th{{color:#e2a04d}} .note{{color:#e9c08a}}
</style></head><body>
<h1>COURSE OF ACTION <span style="color:#86abab;font-size:14px">// {e(generated_at)}</span></h1>
<div class="note">{e(coa.note)}</div>
<table><tr><th>id</th><th>tier</th><th>windows</th><th>value</th><th>type</th><th>title</th></tr>
{rows}</table>
</body></html>"""
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`13 checks passed.`)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_report.py tests/test_advisor.py
git commit -m "feat(advisor): MD + HTML renderers from one COA result"
```

---

### Task 5: Config & file I/O (`coa_io.py`)

**Files:**
- Create: `src/scorched_earth/coa_io.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Consumes: `state._read_json`, `state._write_json`, `state.STATE_DIR`; `roe.roe_from_dict`, `roe.merge_roe`, `roe.DEFAULT_ROE`; `jobs.parse_jobs`.
- Produces: `link_repo(path) -> str` (abspath, adds to registry); `unlink_repo(path) -> bool`; `list_repos() -> list[str]`; `load_roe(repo_path) -> ROE` (global default merged with `<repo>/.scorched/roe.json`); `load_jobs(repo_path) -> list[Job]`; `write_coa(repo_path, md, html, date) -> tuple[str, str]` (returns the md and html paths under `<repo>/.scorched/coa/`).

- [ ] **Step 1: Add the failing test (insert above the footer)**

```python
# --- coa_io.py (round-trips under a temp HOME) -----------------------------------
_home = tempfile.mkdtemp()
_repo = tempfile.mkdtemp()
_env_keys = dict(os.environ)
os.environ["HOME"] = _home
import importlib  # noqa: E402
import scorched_earth.state as _st  # noqa: E402
importlib.reload(_st)
import scorched_earth.coa_io as _io  # noqa: E402
importlib.reload(_io)

_io.link_repo(_repo)
check("link_repo registers an abspath", os.path.realpath(_repo) in _io.list_repos())
check("unlink_repo removes it", _io.unlink_repo(_repo) and _io.list_repos() == [])

os.makedirs(os.path.join(_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_repo, ".scorched", "roe.json"), "w") as f:
    json.dump({"max_windows": 4}, f)
check("load_roe merges per-repo over default", _io.load_roe(_repo).max_windows == 4)

with open(os.path.join(_repo, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "j1", "est_windows": 1, "value": 3}], f)
check("load_jobs reads the repo job list", [j.id for j in _io.load_jobs(_repo)] == ["j1"])

_mdp, _htmlp = _io.write_coa(_repo, "# md", "<html></html>", "2026-06-24")
check("write_coa writes md + html under .scorched/coa",
      os.path.exists(_mdp) and os.path.exists(_htmlp) and "2026-06-24" in _mdp)
os.environ.clear(); os.environ.update(_env_keys)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scorched_earth.coa_io'`

- [ ] **Step 3: Create `src/scorched_earth/coa_io.py`**

```python
"""Filesystem I/O for the COA advisor: the linked-repos registry and the global default ROE
(central, under ~/.claude/scorched-earth/), plus per-repo ROE, jobs, and COA outputs (under
<repo>/.scorched/). Reuses state.py's JSON helpers (atomic write, 0600)."""

from __future__ import annotations

import os
from typing import List, Tuple

from . import state as st
from .jobs import Job, parse_jobs
from .roe import ROE, DEFAULT_ROE, roe_from_dict, merge_roe

REPOS_PATH = os.path.join(st.STATE_DIR, "repos.json")
ROE_DEFAULT_PATH = os.path.join(st.STATE_DIR, "roe.default.json")


def _repo_dir(repo_path: str) -> str:
    return os.path.join(os.path.realpath(os.path.expanduser(repo_path)), ".scorched")


def list_repos() -> List[str]:
    return list(st._read_json(REPOS_PATH, {"repos": []}).get("repos", []))


def link_repo(repo_path: str) -> str:
    ap = os.path.realpath(os.path.expanduser(repo_path))
    repos = list_repos()
    if ap not in repos:
        repos.append(ap)
        st._write_json(REPOS_PATH, {"repos": repos})
    return ap


def unlink_repo(repo_path: str) -> bool:
    ap = os.path.realpath(os.path.expanduser(repo_path))
    repos = list_repos()
    if ap in repos:
        repos.remove(ap)
        st._write_json(REPOS_PATH, {"repos": repos})
        return True
    return False


def load_roe(repo_path: str) -> ROE:
    base = roe_from_dict(st._read_json(ROE_DEFAULT_PATH, {}), DEFAULT_ROE)
    override = roe_from_dict(st._read_json(os.path.join(_repo_dir(repo_path), "roe.json"), {}))
    return merge_roe(base, override)


def load_jobs(repo_path: str) -> List[Job]:
    data = st._read_json(os.path.join(_repo_dir(repo_path), "jobs.json"), [])
    return parse_jobs(data, repo=os.path.realpath(os.path.expanduser(repo_path)))


def write_coa(repo_path: str, md: str, html: str, date: str) -> Tuple[str, str]:
    out = os.path.join(_repo_dir(repo_path), "coa")
    os.makedirs(out, exist_ok=True)
    md_path = os.path.join(out, f"{date}.md")
    html_path = os.path.join(out, f"{date}.html")
    with open(md_path, "w") as f:
        f.write(md)
    with open(html_path, "w") as f:
        f.write(html)
    return md_path, html_path
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`18 checks passed.`)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_io.py tests/test_advisor.py
git commit -m "feat(advisor): registry + ROE/jobs/COA file I/O"
```

---

### Task 6: CLI verbs (`bin/scorch`)

**Files:**
- Modify: `bin/scorch` (add verb dispatch at the top of `main`, plus a `_coa_cli` handler)
- Test: `tests/test_advisor.py`

**Interfaces:**
- Consumes: `coa_io` (Task 5), `advisor.match` (Task 3), `coa_report` (Task 4), `state.load_state`.
- Produces: `scorch link <path>` (register repo), `scorch advise [<repo>]` (print the matched COA from existing job lists; refuse with a clear message if there's no usable snapshot), `scorch roe [<repo>]` (print effective ROE as JSON).
- `advise` reads available windows from `state.load_state()["recommendation"]["windows_left"]`.

- [ ] **Step 1: Add the failing test (insert above the footer)**

```python
# --- bin/scorch verbs (subprocess, temp HOME) ------------------------------------
_env = dict(os.environ)
_env["HOME"] = tempfile.mkdtemp()
_scorch = os.path.join(os.path.dirname(__file__), "..", "bin", "scorch")
_r = tempfile.mkdtemp()
_p = subprocess.run([sys.executable, _scorch, "link", _r], capture_output=True, text=True, env=_env)
check("scorch link exits 0", _p.returncode == 0)
_p2 = subprocess.run([sys.executable, _scorch, "advise"], capture_output=True, text=True, env=_env)
check("scorch advise refuses cleanly with no snapshot",
      _p2.returncode == 0 and "no" in _p2.stdout.lower())
_p3 = subprocess.run([sys.executable, _scorch, "roe", _r], capture_output=True, text=True, env=_env)
check("scorch roe prints JSON", _p3.returncode == 0 and "max_windows" in _p3.stdout)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL on the three new checks (`scorch link` errors: unrecognized arguments).

- [ ] **Step 3: Add verb dispatch to `bin/scorch`. Near the top of `main(argv=None)`, before building the ArgumentParser, insert:**

```python
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] in ("link", "unlink", "advise", "roe"):
        return _coa_cli(raw)
```

- [ ] **Step 4: Add the `_coa_cli` handler to `bin/scorch` (above `main`)**

```python
def _coa_cli(raw):
    import json as _json
    from scorched_earth import coa_io, advisor, coa_report
    verb, rest = raw[0], raw[1:]

    if verb in ("link", "unlink"):
        if not rest:
            print(f"usage: scorch {verb} <repo-path>")
            return 2
        if verb == "link":
            print(f"Linked {coa_io.link_repo(rest[0])}")
        else:
            print("Unlinked." if coa_io.unlink_repo(rest[0]) else "Not linked.")
        return 0

    if verb == "roe":
        repo = rest[0] if rest else "."
        roe = coa_io.load_roe(repo)
        print(_json.dumps(roe.__dict__, indent=2))
        return 0

    # advise
    state = st.load_state()
    rec = (state or {}).get("recommendation") or {}
    wl = rec.get("windows_left")
    if not _has_usable_snapshot(state) or wl is None:
        print("No live budget reading yet, so there's nothing to plan against. "
              "Open a Claude Code session to capture a snapshot, then try again.")
        return 0
    repos = [rest[0]] if rest else coa_io.list_repos()
    if not repos:
        print("No repos linked. Use: scorch link <path>")
        return 0
    date = time.strftime("%Y-%m-%d", time.localtime())
    for repo in repos:
        roe = coa_io.load_roe(repo)
        coa = advisor.match(wl, coa_io.load_jobs(repo), roe)
        print(f"\n=== {repo} ===")
        print(coa_report.render_md(coa, date))
    return 0
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`21 checks passed.`)

- [ ] **Step 6: Sanity-check the existing suite still passes**

Run: `python3 tests/test_scorched.py`
Expected: PASS (`57 checks passed.`) — confirms the verb dispatch didn't break the flag parser.

- [ ] **Step 7: Commit**

```bash
git add bin/scorch tests/test_advisor.py
git commit -m "feat(advisor): scorch link/advise/roe CLI verbs"
```

---

### Task 7: Slash commands (`/coa`, `/roe`)

**Files:**
- Create: `commands/coa.md`
- Create: `commands/roe.md`
- Test: `tests/test_advisor.py` (presence + frontmatter check)

**Interfaces:**
- Consumes: the `scorch` verbs (Task 6). `/coa` additionally orchestrates the adversarial+constructive scan agent when a repo has no `.scorched/jobs.json` (or on `--refresh`), writing the job list before calling `scorch advise`.

- [ ] **Step 1: Add the failing test (insert above the footer)**

```python
# --- slash commands exist with frontmatter ---------------------------------------
_cmds = os.path.join(os.path.dirname(__file__), "..", "commands")
for _c in ("coa", "roe"):
    _path = os.path.join(_cmds, f"{_c}.md")
    _txt = open(_path).read() if os.path.exists(_path) else ""
    check(f"/{_c} command exists with description frontmatter",
          _txt.startswith("---") and "description:" in _txt)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_advisor.py`
Expected: FAIL (files don't exist yet).

- [ ] **Step 3: Create `commands/coa.md`**

```markdown
---
description: Generate a Course of Action — scan linked repos for expensive work and budget-match it to the available burn
argument-hint: "[repo path] [--refresh]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Read, Grep, Glob, Agent
---

Generate a **Course of Action (COA)**: the budget-matched, ranked list of expensive jobs worth
running right now, given how much weekly budget is left and how close the reset is.

Steps:

1. Resolve the target repo(s): the `$ARGUMENTS` path if given, else `scorch advise` uses all
   linked repos (`scorch link <path>` adds one).
2. For each target repo, ensure a job list exists at `<repo>/.scorched/jobs.json`:
   - If it exists and `--refresh` was NOT passed, use it.
   - If it's missing, or `--refresh` was passed, run the scan. Load the repo's effective rules
     with `scorch roe <repo>` first, then dispatch an adversarial + constructive scan agent
     bounded by those rules (respect `exclude_paths`, `allowed_types`, `goals`). The agent
     returns a JSON array of jobs matching the schema (`id, repo, title, type, est_windows,
     value, rationale, launch`); write it to `<repo>/.scorched/jobs.json`. The adversarial lens
     finds gaps (thin tests, stale deps, weak error handling); the constructive lens finds big
     exhaustive jobs worth the compute.
3. Run `scorch advise <repo>` (fallback `~/scorched-earth/bin/scorch advise`) to budget-match and
   print the ranked queue. It refuses if there's no live snapshot yet; relay that as-is.
4. Summarize the top of the queue and point the user at the written COA. Don't invent numbers;
   relay what `scorch` prints.
```

- [ ] **Step 4: Create `commands/roe.md`**

```markdown
---
description: View or edit the Rules of Engagement (cost / task / goal confines) for a linked repo
argument-hint: "[repo path]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Read, Edit, Write
---

View or edit the **Rules of Engagement (ROE)**: the confines that bound what the advisor and
(later) the executor may do.

- To **view** the effective rules: run `scorch roe <repo>` (it prints the merged JSON of the
  global default plus `<repo>/.scorched/roe.json`).
- To **edit**: the rules are three families, written to `<repo>/.scorched/roe.json`:
  - **cost** — `max_windows`, `per_job_max_windows`, `min_weekly_left`
  - **task** — `allowed_types` (e.g. `["test","docs","refactor","perf","audit"]`)
  - **goal** — `goals` (objectives to weight), `exclude_paths` (globs to ignore)
  Apply the user's request (e.g. "cap overnight jobs at 2 windows", "never touch migrations")
  by editing that JSON file, then show the result with `scorch roe <repo>`.

Confirm the change in one line. Only the keys the user asked about should change.
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 tests/test_advisor.py`
Expected: PASS (`23 checks passed.`)

- [ ] **Step 6: Commit**

```bash
git add commands/coa.md commands/roe.md tests/test_advisor.py
git commit -m "feat(advisor): /coa and /roe slash commands"
```

---

### Task 8: Wire CI and docs

**Files:**
- Modify: `.github/workflows/<the CI workflow>.yml` (run `tests/test_advisor.py` too)
- Modify: `CLAUDE.md` (architecture list)
- Modify: `docs/playbook.md` (test count / new surfaces)

**Interfaces:** none (integration + docs).

- [ ] **Step 1: Find the CI test step**

Run: `grep -rn "test_scorched" .github/`
Expected: a line running `python3 tests/test_scorched.py`.

- [ ] **Step 2: Add the advisor suite to CI**

In the workflow, immediately after the `python3 tests/test_scorched.py` step, add:

```yaml
      - name: Advisor tests
        run: python3 tests/test_advisor.py
```

- [ ] **Step 3: Add the new modules to `CLAUDE.md`'s architecture list**

Under the one-line-each module list, add:

```markdown
- `src/scorched_earth/jobs.py` / `roe.py` / `advisor.py` — COA advisor: job schema, rules of engagement, and the pure tier-and-fill budget matcher. No I/O.
- `src/scorched_earth/coa_report.py` — renders a COA result to Markdown (the record) and HTML (the presentation), from one structured source.
- `src/scorched_earth/coa_io.py` — advisor I/O: the linked-repos registry, ROE/jobs loaders, COA output writers (central config + per-repo `.scorched/`).
- `commands/coa.md` / `commands/roe.md` — `/coa` (generate a Course of Action) and `/roe` (edit the Rules of Engagement).
```

- [ ] **Step 4: Update the test-count line in `docs/playbook.md`**

Run: `grep -n "checks" docs/playbook.md`
Replace the stated count to reflect both suites (e.g. "57 + 23 advisor checks").

- [ ] **Step 5: Run both suites to confirm green**

Run: `python3 tests/test_scorched.py && python3 tests/test_advisor.py`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add .github CLAUDE.md docs/playbook.md
git commit -m "ci+docs: wire advisor test suite and document COA modules"
```

---

## Self-Review

**Spec coverage:**
- Naming `/coa` + `/roe` → Tasks 6, 7. ✓
- ROE cost/task/goal + per-repo over global default → Tasks 2, 5. ✓
- COA flow (read budget, load ROE, ensure list w/ 3 modes, match, render) → Tasks 5, 6, 7 (scan-on-demand + `--refresh` in `/coa`). ✓
- Job schema (agent-emitted est_windows/value, derived tier) → Task 1. ✓
- Tier-and-fill matcher → Task 3. ✓
- One-source MD + HTML output → Task 4 (render from one COA); written to `.scorched/coa/` in Task 5. ✓
- JSON throughout → all I/O in Task 5 uses JSON. ✓
- Error handling (no snapshot refuse, missing repo skip, empty result, zero capacity note) → Task 3 (note), Task 6 (snapshot refuse). Missing-repo skip: `load_jobs` returns `[]` for an absent `.scorched/jobs.json`, so `advise` simply yields an empty COA for that repo (acceptable Phase-1 behavior). ✓
- Invariants (core.py untouched, advisor reads state.json only, honesty) → no task modifies `core.py`/`statusline.py`; Task 6 enforces the refuse. ✓
- Out of scope (queue-runner, scheduling, execution paths B/A) → not planned; `status`/`launch` fields reserved in Task 1. ✓

**Placeholder scan:** every code step contains complete code; no TBD/TODO. The `/coa` scan step delegates the *agent prompt* to runtime (it's an agent dispatch, not code), which is correct, the command file specifies the schema it must return.

**Type consistency:** `Job` fields (Task 1) are consumed unchanged by `parse_jobs` (1), `match` (3), `render_*` (4), `load_jobs` (5). `COA` fields (Task 3) consumed by renderers (4) and `advise` (6). `match(available_windows, jobs, roe)` signature is identical in Task 3 definition and Task 6 call. `ROE.__dict__` printed in Task 6 matches the dataclass in Task 2. No drift found.

---

## Notes for the implementer

- The test file grows by appending checks **above the final `print(f"\n{passed} checks passed.")` footer**. Keep that footer last.
- Run `python3 tests/test_advisor.py` after each task; run `python3 tests/test_scorched.py` after Task 6 (the only task touching shared code, `bin/scorch`).
- This is on branch `feat/burn-advisor`, do not push until the advisor works end-to-end or you need a second machine to test.
