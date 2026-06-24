"""Runner tests. Run: python3 tests/test_runner.py"""

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


# --- Task 1: schema fields --------------------------------------------------------
from scorched_earth.roe import ROE, roe_from_dict  # noqa: E402
from scorched_earth.jobs import parse_jobs  # noqa: E402

_r = roe_from_dict({"test_cmd": "pytest -q", "setup_cmd": "pip install -e .",
                    "unattended_types": ["test", "docs"]})
check("ROE carries runner fields",
      _r.test_cmd == "pytest -q" and _r.setup_cmd == "pip install -e ."
      and _r.unattended_types == ["test", "docs"])
check("ROE runner fields default to None",
      ROE().test_cmd is None and ROE().setup_cmd is None and ROE().unattended_types is None)

_j = parse_jobs([{"id": "a", "est_windows": 1, "value": 5, "verify": "make test"}])[0]
check("Job carries per-job verify override", _j.verify == "make test")
check("Job verify defaults empty", parse_jobs([{"id": "b", "est_windows": 1, "value": 5}])[0].verify == "")

# --- Task 2: queue I/O ------------------------------------------------------------
import importlib  # noqa: E402
_home = tempfile.mkdtemp()
_repo = tempfile.mkdtemp()
_saved_env = dict(os.environ)
os.environ["HOME"] = _home
import scorched_earth.state as _st  # noqa: E402
importlib.reload(_st)
import scorched_earth.coa_io as _io  # noqa: E402
importlib.reload(_io)
from scorched_earth.jobs import Job  # noqa: E402

_q = [Job(id="j1", repo=_repo, title="One", type="test", est_windows=1.0, value=5),
      Job(id="j2", repo=_repo, title="Two", type="docs", est_windows=0.5, value=3)]
_io.write_queue(_repo, _q)
check("read_queue round-trips written jobs",
      [j.id for j in _io.read_queue(_repo)] == ["j1", "j2"])
check("write_queue marks jobs queued",
      all(j.status == "queued" for j in _io.read_queue(_repo)))

_io.enqueue(_repo, [Job(id="j2", repo=_repo, title="dup", type="docs", est_windows=0.5, value=3),
                    Job(id="j3", repo=_repo, title="Three", type="audit", est_windows=2.0, value=7)])
check("enqueue appends new and dedups by id, preserving order",
      [j.id for j in _io.read_queue(_repo)] == ["j1", "j2", "j3"])

# --- Task 3: predictive planner ---------------------------------------------------
from scorched_earth.runner import plan_run, SAFE_UNATTENDED  # noqa: E402
from scorched_earth.roe import roe_from_dict as _rfd  # noqa: E402

_pjobs = [
    Job(id="t", repo="r", title="t", type="test", est_windows=1.0, value=5),
    Job(id="ref", repo="r", title="ref", type="refactor", est_windows=0.5, value=9),  # not in SAFE
    Job(id="d", repo="r", title="d", type="docs", est_windows=1.0, value=4),
    Job(id="a", repo="r", title="a", type="audit", est_windows=2.0, value=8),
]
_disp, _spent = plan_run(_pjobs, envelope=2.5, roe=ROE())
_by_id = {j.id: d for j, d in _disp}
check("plan_run runs additive jobs that fit, in order",
      _by_id["t"] == "run" and _by_id["d"] == "run")
check("plan_run blocks non-SAFE types regardless of budget", _by_id["ref"] == "blocked-roe")
check("plan_run marks the overflow job skipped-budget", _by_id["a"] == "skipped-budget")
check("plan_run predicted spend counts only run jobs", _spent == 2.0)
check("SAFE_UNATTENDED is additive-only",
      set(SAFE_UNATTENDED) == {"test", "docs", "perf", "audit"})
check("explicit unattended_types widens the leash",
      {j.id: d for j, d in plan_run([_pjobs[1]], 5.0, _rfd({"unattended_types": ["refactor"]}))[0]}["ref"] == "run")

# --- Task 4: RunResult + envelope/staleness + run-record I/O ----------------------
from scorched_earth.runner import JobOutcome, RunResult, read_envelope, is_stale  # noqa: E402
from dataclasses import asdict as _asdict  # noqa: E402

_now = 1_000_000
_fresh = {"snapshot": {"five_hour_reset": _now + 3600, "seven_day_pct": 40},
          "recommendation": {"windows_left": 3.0, "level": "green"}}
_stale = {"snapshot": {"five_hour_reset": _now - 10, "seven_day_pct": 40},
          "recommendation": {"windows_left": 3.0, "level": "green"}}
check("is_stale: fresh snapshot is usable", not is_stale(_fresh, _now))
check("is_stale: elapsed-window snapshot is stale", is_stale(_stale, _now))
check("is_stale: missing snapshot is stale", is_stale(None, _now))
check("read_envelope returns windows_left when fresh", read_envelope(_fresh, ROE(), _now) == 3.0)
check("read_envelope caps at ROE max_windows",
      read_envelope(_fresh, _rfd({"max_windows": 2.0}), _now) == 2.0)
check("read_envelope refuses (None) on stale snapshot", read_envelope(_stale, ROE(), _now) is None)
_noreset = {"snapshot": {"seven_day_pct": 40},  # has weekly but no five_hour_reset
            "recommendation": {"windows_left": 3.0, "level": "green"}}
check("is_stale: snapshot missing five_hour_reset is stale", is_stale(_noreset, _now))
check("read_envelope refuses (None) when reset is missing", read_envelope(_noreset, ROE(), _now) is None)

_rr = RunResult(generated_at="2026-06-24", state="done", repo=_repo, verdict="green",
                note="1 secured.", available_windows=3.0, spent_estimated=1.0,
                jobs=[JobOutcome(seq=1, id="j1", title="One", type="test", tier="M",
                                 outcome="pass", est_windows=1.0, branch="scorched/j1")])
_path = _io.write_run_record(_repo, _asdict(_rr), "2026-06-24")
check("write_run_record persists under .scorched/runs",
      os.path.exists(_path) and "runs" in _path and "2026-06-24" in _path)
check("read_run_record reads the latest record",
      _io.read_run_record(_repo)["jobs"][0]["id"] == "j1")

# --- Task 5: review render --------------------------------------------------------
from scorched_earth.review_report import aar_dict, render_review_md, render_review_html  # noqa: E402

_running = RunResult(generated_at="2026-06-24 03:14", state="running", repo=_repo,
                     verdict="green", note="1 working.", available_windows=2.5,
                     spent_estimated=1.0,
                     jobs=[JobOutcome(seq=1, id="t", title="Tests", type="test", tier="M",
                                      outcome="running", est_windows=1.0, branch="scorched/t")])
_d = aar_dict(_running)
check("aar_dict camelCases the template contract",
      _d["state"] == "running" and _d["envelope"]["spentEstimated"] == 1.0
      and _d["jobs"][0]["estWindows"] == 1.0)
_md = render_review_md(_running)
check("render_review_md lists job + outcome + estimated label",
      "Tests" in _md and "running" in _md.lower() and "estimated" in _md.lower())
_html_run = render_review_html(_running)
check("render_review_html substitutes the data token",
      "__REVIEW_JSON__" not in _html_run and _html_run.lstrip().lower().startswith("<!doctype html"))
check("render_review_html auto-refreshes while running",
      "http-equiv" in _html_run.lower() and "refresh" in _html_run.lower())
_done = RunResult(generated_at="2026-06-24 03:20", state="done", repo=_repo, verdict="green",
                  note="done.", available_windows=2.5, spent_estimated=1.0, jobs=_running.jobs)
check("render_review_html omits refresh when done",
      "http-equiv" not in render_review_html(_done).lower())

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
