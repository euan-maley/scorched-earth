"""Cockpit (Phase 2b) tests. Run: python3 tests/test_cockpit.py"""

import json
import os
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


# --- Task 2: pick_next + EnvelopeTracker ------------------------------------------
from scorched_earth.jobs import Job  # noqa: E402
from scorched_earth.roe import ROE, roe_from_dict  # noqa: E402
from scorched_earth.runner import pick_next, EnvelopeTracker  # noqa: E402

_q = [Job(id="big", repo="r", title="big", type="test", est_windows=3.0, value=5),
      Job(id="ref", repo="r", title="ref", type="refactor", est_windows=0.2, value=9),  # ROE-blocked
      Job(id="ok",  repo="r", title="ok",  type="docs", est_windows=1.0, value=4)]
check("pick_next skips too-big top and ROE-blocked, returns first that fits",
      pick_next(_q, 1.5, ROE()).id == "ok")
check("pick_next returns None when nothing fits", pick_next(_q, 0.1, ROE()) is None)

_fresh = {"snapshot": {"now": 1000, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
          "recommendation": {"windows_left": 2.0, "level": "green"}}
_tr = EnvelopeTracker(ROE())
check("EnvelopeTracker available = windows_left initially", _tr.available(_fresh, 1) == 2.0)
_tr.charge(0.5)
check("EnvelopeTracker subtracts predictive spend", _tr.available(_fresh, 1) == 1.5)
_adv = {"snapshot": {"now": 2000, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
        "recommendation": {"windows_left": 1.8, "level": "green"}}
check("EnvelopeTracker re-syncs (spent->0) when snapshot timestamp advances",
      _tr.available(_adv, 1) == 1.8)
_stale = {"snapshot": {"now": 3000, "seven_day_pct": 50},
          "recommendation": {"windows_left": 1.0}}
check("EnvelopeTracker returns None on stale snapshot", _tr.available(_stale, 1) is None)


# --- Task 3: queue ops ------------------------------------------------------------
import importlib  # noqa: E402
_home = tempfile.mkdtemp(); _repo = tempfile.mkdtemp()
os.environ["HOME"] = _home
import scorched_earth.state as _st  # noqa: E402
importlib.reload(_st)
import scorched_earth.coa_io as _io  # noqa: E402
importlib.reload(_io)

_io.write_queue(_repo, [Job(id="a", repo=_repo, title="A", type="test", est_windows=1, value=5),
                        Job(id="b", repo=_repo, title="B", type="docs", est_windows=1, value=4),
                        Job(id="c", repo=_repo, title="C", type="perf", est_windows=1, value=3)])
check("unqueue removes by id", [j.id for j in _io.unqueue(_repo, "b")] == ["a", "c"])
check("unqueue persisted", [j.id for j in _io.read_queue(_repo)] == ["a", "c"])
_io.write_queue(_repo, [Job(id="a", repo=_repo, title="A", type="test", est_windows=1, value=5),
                        Job(id="b", repo=_repo, title="B", type="docs", est_windows=1, value=4),
                        Job(id="c", repo=_repo, title="C", type="perf", est_windows=1, value=3)])
check("reorder applies the given order", [j.id for j in _io.reorder(_repo, ["c", "a", "b"])] == ["c", "a", "b"])
check("reorder appends un-named queued jobs after",
      [j.id for j in _io.reorder(_repo, ["b"])] == ["b", "c", "a"])


# --- Task 4: board_state assembler ------------------------------------------------
os.makedirs(os.path.join(_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_repo, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "p1", "title": "Prop1", "type": "test", "est_windows": 1, "value": 5},
               {"id": "q1", "title": "Queued1", "type": "docs", "est_windows": 1, "value": 4},
               {"id": "d1", "title": "Done1", "type": "perf", "est_windows": 1, "value": 3}], f)
_io.write_queue(_repo, [Job(id="q1", repo=_repo, title="Queued1", type="docs", est_windows=1, value=4)])
_io.write_run_record(_repo, {"generated_at": "2026-06-24", "state": "done", "repo": _repo,
                             "jobs": [{"id": "d1", "title": "Done1", "type": "perf", "tier": "M",
                                       "outcome": "pass", "est_windows": 1.0, "branch": "scorched/d1"},
                                      {"id": "d2", "title": "Done2", "type": "test", "tier": "S",
                                       "outcome": "fail", "est_windows": 0.5, "branch": "scorched/d2"},
                                      {"id": "d3", "title": "Skip3", "type": "docs", "tier": "S",
                                       "outcome": "skipped-budget", "est_windows": 0.5, "branch": None}]},
                     "2026-06-24")
_bs = _io.board_state(_repo)
check("board_state proposes only un-queued/un-finished jobs", [j["id"] for j in _bs["proposed"]] == ["p1"])
check("board_state queued reflects the queue", [j["id"] for j in _bs["queued"]] == ["q1"])
check("board_state finished keeps only pass/fail, drops non-terminal (skipped)",
      [j["id"] for j in _bs["finished"]] == ["d1", "d2"])
check("board_state carries repo name", _bs["name"] == os.path.basename(_repo))

_repo_norec = tempfile.mkdtemp()
os.makedirs(os.path.join(_repo_norec, ".scorched"), exist_ok=True)
with open(os.path.join(_repo_norec, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "n1", "title": "N1", "type": "test", "est_windows": 1, "value": 5}], f)
_bsn = _io.board_state(_repo_norec)
check("board_state with no run record yields empty finished + the job proposed",
      _bsn["finished"] == [] and [j["id"] for j in _bsn["proposed"]] == ["n1"])

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
