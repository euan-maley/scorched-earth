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


print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
