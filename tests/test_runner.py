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

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
