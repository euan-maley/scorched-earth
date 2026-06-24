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


print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
