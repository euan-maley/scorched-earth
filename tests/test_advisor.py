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

# --- coa_report.py ---------------------------------------------------------------
from scorched_earth.coa_report import render_md, render_html  # noqa: E402

_md = render_md(_coa, "2026-06-24")
check("render_md lists queued jobs and the date",
      "cheap" in _md and "2026-06-24" in _md and _md.lstrip().startswith("#"))
_html = render_html(_coa, "2026-06-24")
check("render_html is a self-contained doc with the title",
      _html.lstrip().lower().startswith("<!doctype html") and "COURSE OF ACTION" in _html.upper())

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

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
