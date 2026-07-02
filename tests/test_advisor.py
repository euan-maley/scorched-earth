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

check("DEFAULT_ROE is permissive with defcon gate at 3",
      DEFAULT_ROE.allowed_types is None and DEFAULT_ROE.auto_run_min_defcon == 3
      and not hasattr(DEFAULT_ROE, "max_windows"))

_roe = roe_from_dict({"auto_run_min_defcon": 2, "allowed_types": ["test"]})
check("roe_from_dict overlays only given keys",
      _roe.auto_run_min_defcon == 2 and _roe.allowed_types == ["test"] and _roe.min_weekly_left == 0.0)

_merged = merge_roe(roe_from_dict({"max_jobs": 9, "goals": ["a"]}),
                    roe_from_dict({"max_jobs": 2}))
check("merge_roe: override wins where set, base kept otherwise",
      _merged.max_jobs == 2 and _merged.goals == ["a"])

# --- advisor.py (matcher) --------------------------------------------------------
from scorched_earth.advisor import COA, match, approval_required, weekly_reserve_pct  # noqa: E402
from scorched_earth.roe import ROE as _ROE  # noqa: E402

_jobs = [
    Job(id="minor", repo="r", title="minor", type="docs", defcon=4, value=5),
    Job(id="campaign", repo="r", title="campaign", type="audit", defcon=1, value=2),
    Job(id="feature", repo="r", title="feature", type="test", defcon=3, value=9),
]
_coa = match(_jobs, DEFAULT_ROE)
check("match sorts by DEFCON then value",
      [j.id for j in _coa.queue] == ["campaign", "feature", "minor"])
check("match leaves over_budget/headroom behind", not hasattr(_coa, "over_budget"))

_coa_type = match(_jobs, roe_from_dict({"allowed_types": ["docs"]}))
check("match routes disallowed types to blocked",
      [j.id for j in _coa_type.blocked] == ["campaign", "feature"]
      and [j.id for j in _coa_type.queue] == ["minor"])

check("approval_required: defcon below gate needs approval",
      approval_required(Job(id="x", repo="r", title="", type="test", defcon=2), DEFAULT_ROE)
      and not approval_required(Job(id="y", repo="r", title="", type="test", defcon=3), DEFAULT_ROE))

check("weekly_reserve_pct = 100 - seven_day_pct", weekly_reserve_pct({"seven_day_pct": 81}) == 19)

_coa_empty = match([], DEFAULT_ROE)
check("empty job list yields empty queue with a note",
      _coa_empty.queue == [] and "no jobs" in _coa_empty.note.lower())

# --- coa_report.py ---------------------------------------------------------------
from scorched_earth.coa_report import render_md, render_html, _job_obj as _coa_job_obj  # noqa: E402

_md = render_md(_coa, "2026-06-25")
check("render_md lists queued jobs, date, DEFCON", "campaign" in _md and "2026-06-25" in _md
      and "DEFCON" in _md.upper() and _md.lstrip().startswith("#"))
check("render_md has no budget framing",
      "windows" not in _md.lower() and "over budget" not in _md.lower())

_html = render_html(_coa, "2026-06-25", verdict="green")
check("render_html fills the template, token substituted",
      _html.lstrip().lower().startswith("<!doctype html") and "__COA_JSON__" not in _html
      and "campaign" in _html)
check("render_html carries defcon, not headroom",
      '"defcon"' in _html and '"headroom"' not in _html)
check("_job_obj carries defcon + approval_required",
      _coa_job_obj(Job(id="z", repo="r", title="Z", type="test", defcon=1, value=7))["defcon"] == 1)

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
    json.dump({"auto_run_min_defcon": 2}, f)
check("load_roe merges per-repo over default", _io.load_roe(_repo).auto_run_min_defcon == 2)

with open(os.path.join(_repo, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "j1", "defcon": 2, "value": 3}], f)
check("load_jobs reads the repo job list", [j.id for j in _io.load_jobs(_repo)] == ["j1"])
check("load_jobs reads defcon", _io.load_jobs(_repo)[0].defcon == 2)

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
check("scorch roe prints JSON", _p3.returncode == 0 and "auto_run_min_defcon" in _p3.stdout)

# --- slash commands exist with frontmatter ---------------------------------------
_cmds = os.path.join(os.path.dirname(__file__), "..", "commands")
for _c in ("coa", "roe"):
    _path = os.path.join(_cmds, f"{_c}.md")
    _txt = open(_path).read() if os.path.exists(_path) else ""
    check(f"/{_c} command exists with description frontmatter",
          _txt.startswith("---") and "description:" in _txt)


# --- AAR _job_obj carries defcon (Task 8) ----------------------------------------
from scorched_earth.runner import JobOutcome  # noqa: E402
from scorched_earth.review_report import _job_obj as _aar_job_obj  # noqa: E402
check("aar _job_obj carries defcon",
      _aar_job_obj(JobOutcome(seq=1, id="x", title="x", type="test",
                              defcon=8, outcome="pass"))["defcon"] == 8)

# advise writes BOTH md + html (no-budget API)
import tempfile as _tf2, os as _os2  # noqa: E402
from scorched_earth import coa_io as _cio2  # noqa: E402
_arepo = _tf2.mkdtemp(); _os2.makedirs(_os2.path.join(_arepo, ".scorched"), exist_ok=True)
with open(_os2.path.join(_arepo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "a1", "repo": _arepo, "title": "A", "type": "docs", "defcon": 1, "value": 7}], _f)
_coaA = match(_cio2.load_jobs(_arepo), _ROE())
_mdp, _htmlp = _cio2.write_coa(_arepo, render_md(_coaA, "2026-06-25"),
                               render_html(_coaA, "2026-06-25", verdict="green"), "2026-06-25")
check("advise path writes md + html records", _os2.path.exists(_mdp) and _os2.path.exists(_htmlp))

# --- multi-repo tabbed render ----------------------------------------------------
from scorched_earth.jobs import parse_jobs as _pj  # noqa: E402
_coaB = match(_pj([{"id": "b1", "repo": "/x/beta", "title": "Beta audit", "type": "audit",
                    "defcon": 2, "value": 8}]), _ROE())
_multi = render_html(None, "2026-06-25", repos=[("/x/alpha", _coaA), ("/x/beta", _coaB)],
                     verdict="green", token="TK9")
check("render_html multi-repo carries every repo by name",
      '"name": "alpha"' in _multi and '"name": "beta"' in _multi)
check("render_html multi-repo arms the refresh token",
      '"TK9"' in _multi and "__COA_TOKEN__" not in _multi)
check("render_html single-repo still works (backward compat)", '"repos"' in render_html(_coaA, "2026-06-25"))

# --- Phase 2: freshness UI + honest Refresh (#5/#6) --------------------------------
# The COA template paints the scanned-ago label client-side from each repo's scannedAt; these
# confirm the template ships the freshness readout and an honest (does-not-re-scan) Refresh.
_fresh_html = render_html(None, "2026-06-25", repos=[("/x/alpha", _coaA)], verdict="green", token="TK9")
check("COA template wires a scanned-ago freshness label off scannedAt",
      "scannedAgo" in _fresh_html and "SCANNED" in _fresh_html)
check("COA Refresh is honest that it does not re-scan the repo",
      "Does NOT re-scan" in _fresh_html and "run /coa to re-scan" in _fresh_html)

# --- coa_view.py (served, read-only) ---------------------------------------------
from scorched_earth import coa_view as _cv  # noqa: E402
import threading as _thr, urllib.request as _url, urllib.error as _uerr  # noqa: E402
_vrepo = _tf2.mkdtemp(); _os2.makedirs(_os2.path.join(_vrepo, ".scorched"), exist_ok=True)
def _wj(jobs):
    with open(_os2.path.join(_vrepo, ".scorched", "jobs.json"), "w") as _f:
        json.dump(jobs, _f)
_wj([{"id": "v1", "repo": _vrepo, "title": "first", "type": "audit", "defcon": 1, "value": 9}])
check("coa_state re-reads jobs.json into a repos list",
      _cv.coa_state([_vrepo])["repos"][0]["queue"][0]["title"] == "first")
_expected_mtime = _os2.path.getmtime(_os2.path.join(_vrepo, ".scorched", "jobs.json"))
check("coa_state stamps each repo with jobs.json scannedAt (mtime, for staleness)",
      abs(_cv.coa_state([_vrepo])["repos"][0]["scannedAt"] - _expected_mtime) < 2)
_norepo = _tf2.mkdtemp()  # never scanned: no .scorched/jobs.json
check("coa_state scannedAt is None when a repo was never scanned",
      _cv.coa_state([_norepo])["repos"][0]["scannedAt"] is None)
_tok = "TESTTOK"
_httpd, _port = _cv.make_server([_vrepo], _tok)
_thr.Thread(target=_httpd.serve_forever, daemon=True).start()
def _req(p):
    try:
        _r = _url.urlopen(f"http://127.0.0.1:{_port}{p}", timeout=5); return _r.status, _r.read()
    except _uerr.HTTPError as _e:
        return _e.code, _e.read()
check("served / returns the page (token ok)", _req(f"/?t={_tok}")[0] == 200)
check("served /coa.json without token is 403", _req("/coa.json")[0] == 403)
check("served /coa.json with bad token is 403", _req("/coa.json?t=nope")[0] == 403)
check("served /coa.json returns the jobs",
      json.loads(_req(f"/coa.json?t={_tok}")[1])["repos"][0]["queue"][0]["title"] == "first")
_wj([{"id": "v1", "repo": _vrepo, "title": "first", "type": "audit", "defcon": 1, "value": 9},
     {"id": "v2", "repo": _vrepo, "title": "second-new", "type": "test", "defcon": 2, "value": 8}])
check("Refresh picks up new jobs from jobs.json (no repo re-scan)",
      any(j["title"] == "second-new"
          for j in json.loads(_req(f"/coa.json?t={_tok}")[1])["repos"][0]["queue"]))
_httpd.shutdown()

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
