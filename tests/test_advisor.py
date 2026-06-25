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
check("match fills by value-per-window within headroom",
      [j.id for j in _coa.queue] == ["cheap", "docs"] and _coa.fits_windows == 2.0)
check("match records what spilled over budget", [j.id for j in _coa.over_budget] == ["big"])

_coa_cap = match(10, _jobs, roe_from_dict({"max_windows": 1.0}))
check("match honors ROE max_windows", [j.id for j in _coa_cap.queue] == ["cheap"])

_coa_type = match(10, _jobs, roe_from_dict({"allowed_types": ["docs"]}))
check("match routes disallowed types to blocked", [j.id for j in _coa_type.blocked] == ["big", "cheap"]
      and [j.id for j in _coa_type.queue] == ["docs"])

_coa_empty = match(0.0, _jobs, DEFAULT_ROE)
check("zero capacity yields empty queue with a note",
      _coa_empty.queue == [] and "window free now" in _coa_empty.note.lower())

# --- coa_report.py ---------------------------------------------------------------
from scorched_earth.coa_report import render_md, render_html  # noqa: E402

_md = render_md(_coa, "2026-06-24")
check("render_md lists queued jobs and the date",
      "cheap" in _md and "2026-06-24" in _md and _md.lstrip().startswith("#"))
_html = render_html(_coa, "2026-06-24")
check("render_html fills the war-HUD template with the COA data",
      _html.lstrip().lower().startswith("<!doctype html")
      and "COURSE OF ACTION" in _html.upper()
      and "__COA_JSON__" not in _html          # the data token was substituted
      and "cheap" in _html)                    # a queued job title made it into the blob

from scorched_earth import coa_report as _rep  # noqa: E402
_md = _rep.render_md(_coa, "2026-06-25")
check("render_md uses the 'Over budget' framing, not 'Left on the table'",
      "Over budget" in _md and "Left on the table" not in _md)
check("render_md lists the over-budget jobs under the Over budget section",
      "## Over budget (queue anyway)" in _md and "- big (" in _md)
_html = _rep.render_html(_coa, "2026-06-25", verdict="green")
check("render_html substitutes the token (no leftover __COA_JSON__)",
      "__COA_JSON__" not in _html)
import json as _json  # noqa: E402
_blob = _json.loads(_html.split("var DATA = ", 1)[1].split(";\n", 1)[0]) if "var DATA = " in _html else None
check("render_html carries headroom + weeklyReservePct in the data blob",
      ('"headroom"' in _html) and ('"weeklyReservePct"' in _html))
check("render_html marks each job's fit (fits vs over)",
      ('"fit": "fits"' in _html or '"fit":"fits"' in _html))

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

# link_repo ignores .scorched/ in the target repo, preserving existing content, idempotently
_repo2 = tempfile.mkdtemp()
with open(os.path.join(_repo2, ".gitignore"), "w") as f:
    f.write("node_modules/\n")
_io.link_repo(_repo2)
_gi = open(os.path.join(_repo2, ".gitignore")).read()
check("link_repo gitignores .scorched/ without clobbering existing entries",
      ".scorched/" in _gi and "node_modules/" in _gi)
_io.link_repo(_repo2)  # re-link must not duplicate
check("gitignore .scorched/ entry is idempotent",
      open(os.path.join(_repo2, ".gitignore")).read().count(".scorched") == 1)
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

# --- slash commands exist with frontmatter ---------------------------------------
_cmds = os.path.join(os.path.dirname(__file__), "..", "commands")
for _c in ("coa", "roe"):
    _path = os.path.join(_cmds, f"{_c}.md")
    _txt = open(_path).read() if os.path.exists(_path) else ""
    check(f"/{_c} command exists with description frontmatter",
          _txt.startswith("---") and "description:" in _txt)


# --- depth flows into the rendered job dicts -------------------------------------
from scorched_earth.coa_report import _job_obj as _coa_job_obj  # noqa: E402
from scorched_earth.review_report import _job_obj as _aar_job_obj  # noqa: E402
_dj2 = parse_jobs([{"id": "z", "title": "Z", "type": "test", "depth": 8, "value": 7}])[0]
check("coa_report _job_obj carries depth", _coa_job_obj(_dj2)["depth"] == 8)

from scorched_earth.runner import JobOutcome  # noqa: E402
check("aar _job_obj carries depth",
      _aar_job_obj(JobOutcome(seq=1, id="x", title="x", type="test", tier="M",
                              outcome="pass", est_windows=1.0, depth=8))["depth"] == 8)

# --- headroom model (replaces the windows-until-reset envelope) ------------------
from scorched_earth import advisor as _adv  # noqa: E402
from scorched_earth.advisor import COA as _COA, match as _match  # noqa: E402
from scorched_earth.jobs import Job as _J  # noqa: E402

check("window_headroom = unused fraction of the current 5h window",
      abs(_adv.window_headroom({"five_hour_pct": 5}) - 0.95) < 1e-9)
check("window_headroom None when five_hour_pct missing",
      _adv.window_headroom({}) is None)
check("weekly_reserve_pct = 100 - seven_day_pct",
      _adv.weekly_reserve_pct({"seven_day_pct": 81}) == 19)

# annotate, never forfeit: 3 jobs @0.5w, headroom 0.6 -> 1 fits, 2 over, 0 dropped
_mj = [_J(id="a", repo=".", title="A", type="docs", est_windows=0.5, value=9, depth=3),
       _J(id="b", repo=".", title="B", type="docs", est_windows=0.5, value=8, depth=3),
       _J(id="c", repo=".", title="C", type="docs", est_windows=0.5, value=7, depth=3)]
from scorched_earth.roe import ROE as _ROE  # noqa: E402
_coa = _match(0.6, _mj, _ROE())
check("match keeps every eligible job (nothing forfeited)",
      len(_coa.queue) + len(_coa.over_budget) == 3)
check("match: only the highest-value job fits 0.6 windows",
      [j.id for j in _coa.queue] == ["a"] and [j.id for j in _coa.over_budget] == ["b", "c"])
check("match exposes headroom on the COA", _coa.headroom_windows == 0.6)

# ROE-disallowed types go to `blocked`, not `over_budget`
_coa2 = _match(5.0, _mj, _ROE(allowed_types=["test"]))
check("match routes ROE-disallowed jobs to blocked (distinct from over_budget)",
      len(_coa2.blocked) == 3 and _coa2.queue == [] and _coa2.over_budget == [])

# advise writes BOTH md + html (html is the artifact to open, md is the record)
import tempfile as _tf2, os as _os2
from scorched_earth import coa_io as _cio2
_arepo = _tf2.mkdtemp(); _os2.makedirs(_os2.path.join(_arepo, ".scorched"), exist_ok=True)
with open(_os2.path.join(_arepo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id":"a1","repo":_arepo,"title":"A","type":"docs","depth":3,"value":7}], _f)
# drive the same render+write the CLI uses
_snap = {"five_hour_pct": 5, "seven_day_pct": 81}
_hr = _adv.window_headroom(_snap); _wr = _adv.weekly_reserve_pct(_snap)
_coaA = _match(_hr, _cio2.load_jobs(_arepo), _ROE(), weekly_reserve_pct=_wr)
_mdp, _htmlp = _cio2.write_coa(_arepo, _rep.render_md(_coaA, "2026-06-25"),
                               _rep.render_html(_coaA, "2026-06-25", verdict="green"), "2026-06-25")
check("advise path writes md + html records", _os2.path.exists(_mdp) and _os2.path.exists(_htmlp))

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
