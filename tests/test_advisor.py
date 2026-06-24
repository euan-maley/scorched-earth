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

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
