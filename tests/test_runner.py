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

_j = parse_jobs([{"id": "a", "defcon": 2, "value": 5, "verify": "make test"}])[0]
check("Job carries per-job verify override", _j.verify == "make test")
check("Job verify defaults empty", parse_jobs([{"id": "b", "defcon": 2, "value": 5}])[0].verify == "")

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

_q = [Job(id="j1", repo=_repo, title="One", type="test", defcon=3, value=5),
      Job(id="j2", repo=_repo, title="Two", type="docs", defcon=4, value=3)]
_io.write_queue(_repo, _q)
check("read_queue round-trips written jobs",
      [j.id for j in _io.read_queue(_repo)] == ["j1", "j2"])
check("write_queue marks jobs queued",
      all(j.status == "queued" for j in _io.read_queue(_repo)))

_io.enqueue(_repo, [Job(id="j2", repo=_repo, title="dup", type="docs", defcon=4, value=3),
                    Job(id="j3", repo=_repo, title="Three", type="audit", defcon=3, value=7)])
check("enqueue appends new and dedups by id, preserving order",
      [j.id for j in _io.read_queue(_repo)] == ["j1", "j2", "j3"])

# --- Task 3: DEFCON planner (no budget) -------------------------------------------
from scorched_earth.runner import plan_run, pick_next, SAFE_UNATTENDED  # noqa: E402
from scorched_earth.roe import roe_from_dict as _rfd  # noqa: E402

_pjobs = [
    Job(id="t", repo="r", title="t", type="test", defcon=3, value=5),
    Job(id="ref", repo="r", title="ref", type="refactor", defcon=3, value=9),  # not in SAFE
    Job(id="d", repo="r", title="d", type="docs", defcon=3, value=4),
    Job(id="a", repo="r", title="a", type="audit", defcon=3, value=8),
]
_disp = plan_run(_pjobs, ROE())
_by_id = {j.id: d for j, d in _disp}
check("plan_run runs ROE-allowed additive jobs, in order",
      _by_id["t"] == "run" and _by_id["d"] == "run")
check("plan_run blocks non-SAFE types via the ROE leash", _by_id["ref"] == "blocked-roe")
check("plan_run runs all ROE-allowed jobs (no budget gate)", _by_id["a"] == "run")
check("SAFE_UNATTENDED is additive-only",
      set(SAFE_UNATTENDED) == {"test", "docs", "perf", "audit"})
check("explicit unattended_types widens the leash",
      {j.id: d for j, d in plan_run([_pjobs[1]], _rfd({"unattended_types": ["refactor"]}))}["ref"] == "run")

# approval gate: defcon below auto_run_min_defcon needs explicit approval to run unattended
_aq = [Job(id="a", repo="r", title="A", type="test", defcon=4),
       Job(id="b", repo="r", title="B", type="audit", defcon=1)]  # approval-required by default
_adisp = plan_run(_aq, ROE())                       # unattended: not approved
check("plan_run blocks approval-required jobs unattended",
      dict((j.id, d) for j, d in _adisp) == {"a": "run", "b": "blocked-approval"})
_adisp2 = plan_run(_aq, ROE(), approved=True)
check("plan_run runs everything once approved",
      all(d == "run" for _, d in _adisp2))
check("pick_next picks the ungated job first, regardless of approval",
      pick_next(_aq, ROE()).id == "a" and pick_next(_aq, ROE(), approved=True).id == "a")
# an approval-required job alone is skipped unless approved
_bq = [Job(id="b", repo="r", title="B", type="audit", defcon=1)]
check("pick_next skips an approval-required job unless approved",
      pick_next(_bq, ROE()) is None and pick_next(_bq, ROE(), approved=True).id == "b")

# --- Task 4: RunResult + staleness + run-record I/O -------------------------------
from scorched_earth.runner import JobOutcome, RunResult, is_stale  # noqa: E402
from dataclasses import asdict as _asdict  # noqa: E402

_now = 1_000_000
_fresh = {"snapshot": {"five_hour_reset": _now + 3600, "seven_day_pct": 40},
          "recommendation": {"windows_left": 3.0, "level": "green"}}
_stale = {"snapshot": {"five_hour_reset": _now - 10, "seven_day_pct": 40},
          "recommendation": {"windows_left": 3.0, "level": "green"}}
check("is_stale: fresh snapshot is usable", not is_stale(_fresh, _now))
check("is_stale: elapsed-window snapshot is stale", is_stale(_stale, _now))
check("is_stale: missing snapshot is stale", is_stale(None, _now))
_noreset = {"snapshot": {"seven_day_pct": 40},  # has weekly but no five_hour_reset
            "recommendation": {"windows_left": 3.0, "level": "green"}}
check("is_stale: snapshot missing five_hour_reset is stale", is_stale(_noreset, _now))

_rr = RunResult(generated_at="2026-06-24", state="done", repo=_repo, verdict="green",
                note="1 secured.",
                jobs=[JobOutcome(seq=1, id="j1", title="One", type="test", defcon=3,
                                 outcome="pass", branch="scorched/j1")])
_path = _io.write_run_record(_repo, _asdict(_rr), "2026-06-24")
check("write_run_record persists under .scorched/runs",
      os.path.exists(_path) and "runs" in _path and "2026-06-24" in _path)
check("read_run_record reads the latest record",
      _io.read_run_record(_repo)["jobs"][0]["id"] == "j1")

# --- Task 5: review render (DEFCON, no budget gauge) -------------------------------
from scorched_earth.review_report import aar_dict, render_review_md, render_review_html  # noqa: E402

_running = RunResult(generated_at="2026-06-24 03:14", state="running", repo=_repo,
                     verdict="green", note="1 working.",
                     jobs=[JobOutcome(seq=1, id="t", title="Tests", type="test", defcon=2,
                                      outcome="running", branch="scorched/t")])
_d = aar_dict(_running)
check("aar_dict camelCases the template contract + carries DEFCON",
      _d["state"] == "running" and _d["jobs"][0]["defcon"] == 2
      and "envelope" not in _d)
_md = render_review_md(_running)
check("render_review_md lists job + outcome",
      "Tests" in _md and "running" in _md.lower())
_html_run = render_review_html(_running)
check("render_review_html substitutes the data token",
      "__REVIEW_JSON__" not in _html_run and _html_run.lstrip().lower().startswith("<!doctype html"))
check("render_review_html auto-refreshes while running",
      "http-equiv" in _html_run.lower() and "refresh" in _html_run.lower())
_done = RunResult(generated_at="2026-06-24 03:20", state="done", repo=_repo, verdict="green",
                  note="done.", jobs=_running.jobs)
check("render_review_html omits refresh when done",
      "http-equiv" not in render_review_html(_done).lower())
check("render_review_html refresh injection survives running state",
      render_review_html(_running).lower().count("http-equiv") == 1)
check("render_review_html contains a DEFCON badge (defcon-2 CSS present for defcon=2 job)",
      "defcon-2" in render_review_html(_running))
# Phase 2 (#9): the CRATERED (fail) state is legible - the field legend explains what it means.
check("AAR legend explains CRATERED = the fail state (work discarded)",
      "CRATERED" in _html_run and "work was discarded" in _html_run)

# --- Task 6: command builders + sandbox settings ----------------------------------
from scorched_earth.runner import (worktree_path, branch_name, build_claude_cmd,  # noqa: E402
                                    build_gate_cmd, merge_cmd, discard_cmd,
                                    write_sandbox_settings, model_arg)

_jb = Job(id="cov", repo=_repo, title="Coverage", type="test", defcon=3, value=5,
          launch="Raise coverage to 90%, TDD.")
check("branch_name namespaces under scorched/", branch_name("cov") == "scorched/cov")
check("worktree_path lives under .scorched/wt", worktree_path(_repo, "cov").endswith("/.scorched/wt/cov"))
_cmd = build_claude_cmd(_jb, worktree_path(_repo, "cov"))
check("build_claude_cmd is a headless claude invocation carrying the launch",
      _cmd[0] == "claude" and "-p" in _cmd and any("Raise coverage" in a for a in _cmd))
check("build_claude_cmd prelude forbids push", any("do not push" in a.lower() for a in _cmd))
check("build_claude_cmd includes --dangerously-skip-permissions",
      "--dangerously-skip-permissions" in _cmd)
check("build_claude_cmd omits --model when the job names none", "--model" not in _cmd)
_cmd_m = build_claude_cmd(Job(id="m", repo=_repo, title="M", type="test", defcon=1,
                              value=9, launch="deep audit", model="opus"),
                          worktree_path(_repo, "m"))
check("build_claude_cmd passes --model opus for a modelled job",
      _cmd_m[_cmd_m.index("--model") + 1] == "opus")
check("model_arg accepts aliases and claude-* ids",
      model_arg(Job(id="a", repo="r", title="", type="test", model="haiku")) == ["--model", "haiku"]
      and model_arg(Job(id="b", repo="r", title="", type="test", model="claude-opus-4-8"))
      == ["--model", "claude-opus-4-8"])
check("model_arg ignores an unknown/empty model (inherit default)",
      model_arg(Job(id="c", repo="r", title="", type="test", model="gpt-9")) == []
      and model_arg(Job(id="d", repo="r", title="", type="test")) == [])
check("build_gate_cmd prefers per-job verify",
      build_gate_cmd(Job(id="x", repo="r", title="x", type="test", defcon=3, value=1,
                         verify="make test"), _rfd({"test_cmd": "pytest"})) == "make test")
check("build_gate_cmd falls back to ROE test_cmd",
      build_gate_cmd(_jb, _rfd({"test_cmd": "pytest -q"})) == "pytest -q")
check("build_gate_cmd is None when neither set", build_gate_cmd(_jb, ROE()) is None)

# --- Stage 3: run-mode cascade + attended prompt/command builders -----------------
from scorched_earth import exec_modes as _em  # noqa: E402

check("resolve_mode: a valid per-task override wins",
      _em.resolve_mode(ROE(run_mode="headless"), "session") == "session")
check("resolve_mode: falls back to ROE run_mode when no override",
      _em.resolve_mode(ROE(run_mode="takeover")) == "takeover")
check("resolve_mode: an invalid override is ignored, ROE used",
      _em.resolve_mode(ROE(run_mode="session"), "bogus") == "session")
check("resolve_mode: an unknown run_mode falls back to headless",
      _em.resolve_mode(ROE(run_mode="weird")) == "headless")

_roe_att = ROE(goals=["ship v2"], exclude_paths=["infra/"], allowed_types=["test"],
               context_cmd="/kerd:switch in")
_orders = _em.operating_orders(_roe_att)
check("operating_orders carries goal, exclusions, allowed types, and no-push",
      "ship v2" in _orders and "infra/" in _orders and "test" in _orders
      and "do not push" in _orders.lower())

_jb3 = Job(id="j3", repo=_repo, title="T", type="test", defcon=1, value=9,
           launch="Do the audit", model="opus")
_prompt = _em.compose_attended_prompt(_jb3, _roe_att)
check("compose_attended_prompt runs the context_cmd before the task",
      "/kerd:switch in" in _prompt and _prompt.index("switch in") < _prompt.index("Do the audit"))
check("compose_attended_prompt injects orders, model hint, and the task",
      "ship v2" in _prompt and "opus" in _prompt and "Do the audit" in _prompt)
check("compose_attended_prompt omits the context line when context_cmd unset",
      "gather context" not in _em.compose_attended_prompt(_jb3, ROE(goals=["g"])))

_tk = _em.build_takeover_cmd(_jb3, _roe_att, "/tmp/s.json")
check("build_takeover_cmd is interactive claude with the prompt, --settings, and --model",
      _tk[0] == "claude" and "-p" not in _tk and _tk[_tk.index("--settings") + 1] == "/tmp/s.json"
      and _tk[_tk.index("--model") + 1] == "opus")
check("build_takeover_cmd does not skip permissions (operator present)",
      "--dangerously-skip-permissions" not in _tk)

# --- Stage 4: session mode (new-window spawn) -------------------------------------
_ss = _em.build_session_cmd(_jb3, _roe_att)
check("build_session_cmd is interactive claude, no --settings (session is fully free), with model",
      _ss[0] == "claude" and "-p" not in _ss and "--settings" not in _ss
      and "--dangerously-skip-permissions" not in _ss and _ss[_ss.index("--model") + 1] == "opus")
check("build_session_cmd still carries the composed prompt (context_cmd + task)",
      any("/kerd:switch in" in a for a in _ss) and any("Do the audit" in a for a in _ss))
_scr = _em._session_script("/tmp/myrepo", _ss)
_body = open(_scr).read()
check("_session_script cd's to the repo and execs the session command",
      _body.startswith("#!/bin/bash") and "cd /tmp/myrepo" in _body and "exec claude" in _body)
os.remove(_scr)

# --- Stage 5: deliverables --------------------------------------------------------
from scorched_earth.runner import render_deliverable_md, write_job_deliverable  # noqa: E402
_oc_pass = JobOutcome(seq=1, id="dlv", title="Cover", type="test", defcon=3, outcome="pass",
                      branch="scorched/dlv", diff={"files": 2, "insertions": 10, "deletions": 1},
                      note="gate passed.", merge_cmd="git merge scorched/dlv",
                      discard_cmd="git branch -D scorched/dlv")
_dmd = render_deliverable_md(_oc_pass, "/tmp/r")
check("render_deliverable_md carries title, diff, outcome, and take/drop cmds",
      "Cover (dlv)" in _dmd and "2 files, +10/-1" in _dmd and "outcome: pass" in _dmd
      and "git merge scorched/dlv" in _dmd)
_drepo = tempfile.mkdtemp()
write_job_deliverable(_drepo, _oc_pass)
check("write_job_deliverable writes the file and stamps a repo-relative path",
      _oc_pass.deliverable == ".scorched/deliverables/dlv.md"
      and os.path.exists(_io.deliverable_path(_drepo, "dlv")))
_oc_block = JobOutcome(seq=2, id="bk", title="B", type="refactor", defcon=2, outcome="blocked-roe")
write_job_deliverable(_drepo, _oc_block)
check("write_job_deliverable skips non-run outcomes (no deliverable for blocked)",
      _oc_block.deliverable is None and not os.path.exists(_io.deliverable_path(_drepo, "bk")))
check("compose_attended_prompt instructs writing the deliverable file",
      ".scorched/deliverables/j3.md" in _em.compose_attended_prompt(_jb3, _roe_att))
check("merge_cmd / discard_cmd reference the branch",
      "scorched/cov" in merge_cmd(_repo, "cov") and "scorched/cov" in discard_cmd(_repo, "cov"))

# write_sandbox_settings: API-only network, sandbox enabled
_wt = tempfile.mkdtemp()
write_sandbox_settings(_wt)
_settings_path = os.path.join(_wt, ".claude", "settings.json")
with open(_settings_path) as _f:
    _settings = json.load(_f)
check("write_sandbox_settings: sandbox.enabled is true",
      _settings.get("sandbox", {}).get("enabled") is True)
check("write_sandbox_settings: network allowedDomains is API-only (no npm/pypi)",
      set(_settings.get("sandbox", {}).get("network", {}).get("allowedDomains", [])) ==
      {"api.anthropic.com", "*.anthropic.com"})
check("sandbox settings: failIfUnavailable is True",
      _settings["sandbox"]["failIfUnavailable"] is True)
check("sandbox settings: allowUnsandboxedCommands is False",
      _settings["sandbox"]["allowUnsandboxedCommands"] is False)

# --- Task 7: run_queue orchestration (hermetic, stub executor) --------------------
from scorched_earth.runner import run_queue  # noqa: E402

# queue: a runnable test job, a refactor (ROE-blocked), an audit (runs — no budget gate)
_io.write_queue(_repo, [
    Job(id="t1", repo=_repo, title="Tests", type="test", defcon=3, value=5,
        launch="add tests"),
    Job(id="r1", repo=_repo, title="Refactor", type="refactor", defcon=3, value=9),
    Job(id="a1", repo=_repo, title="Audit", type="audit", defcon=3, value=8),
])
_steps = []
def _stub_exec(repo, job, roe):
    return ("pass", {"files": 2, "insertions": 30, "deletions": 4}, "gate passed.")
_state_ok = {"snapshot": {"five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
             "recommendation": {"windows_left": 1.5, "level": "green"}}
_rr = run_queue(_repo, _state_ok, now=1, date="2026-06-24",
                execute=_stub_exec, on_step=lambda rr: _steps.append(rr.state))
_out = {j.id: j.outcome for j in _rr.jobs}
check("run_queue executes the runnable additive job", _out["t1"] == "pass")
check("run_queue blocks the refactor via ROE leash", _out["r1"] == "blocked-roe")
check("run_queue runs all ROE-allowed jobs (audit runs, no budget gate)", _out["a1"] == "pass")
check("run_queue final state is done", _rr.state == "done")
check("run_queue re-renders live (on_step fired every persist)", len(_steps) == 6)
check("run_queue attaches merge/discard to executed job",
      _rr.jobs[0].branch == "scorched/t1" and "scorched/t1" in (_rr.jobs[0].merge_cmd or ""))
check("run_queue persisted a run record + html",
      os.path.exists(os.path.join(_io.runs_dir(_repo), "2026-06-24.json"))
      and os.path.exists(os.path.join(_io.runs_dir(_repo), "2026-06-24.html")))

_refused = run_queue(_repo, _stale, now=_now, date="2026-06-24", execute=_stub_exec)
check("run_queue refuses on a stale snapshot", _refused is None)

def _boom_exec(repo, job, roe):
    raise RuntimeError("claude died")
_io.write_queue(_repo, [Job(id="t2", repo=_repo, title="T2", type="test", defcon=3, value=5)])
_rr2 = run_queue(_repo, _state_ok, now=1, date="2026-06-25", execute=_boom_exec)
check("run_queue turns an executor crash into a failed job, not an abort",
      _rr2 is not None and _rr2.jobs[0].outcome == "fail")

# --- Task 8: CLI verbs (subprocess, temp HOME) ------------------------------------
os.environ.clear(); os.environ.update(_saved_env)
_cli_env = dict(os.environ)
_cli_env["HOME"] = tempfile.mkdtemp()
_scorch = os.path.join(os.path.dirname(__file__), "..", "bin", "scorch")
_cli_repo = tempfile.mkdtemp()
subprocess.run([sys.executable, _scorch, "link", _cli_repo], capture_output=True, text=True, env=_cli_env)

_run = subprocess.run([sys.executable, _scorch, "coa", "run"], capture_output=True, text=True, env=_cli_env)
check("scorch coa run refuses cleanly with no snapshot",
      _run.returncode == 0 and ("no" in _run.stdout.lower() or "snapshot" in _run.stdout.lower()))
_rev = subprocess.run([sys.executable, _scorch, "coa", "review"], capture_output=True, text=True, env=_cli_env)
check("scorch coa review reports cleanly when there's no run yet",
      _rev.returncode == 0 and ("no" in _rev.stdout.lower()))
_que = subprocess.run([sys.executable, _scorch, "coa", "queue", "--all", _cli_repo],
                      capture_output=True, text=True, env=_cli_env)
check("scorch coa queue runs without error (empty COA -> nothing queued)",
      _que.returncode == 0)

_merge_noid = subprocess.run([sys.executable, _scorch, "coa", "review", "--merge"],
                             capture_output=True, text=True, env=_cli_env)
check("scorch coa review --merge with no id refuses cleanly (no traceback)",
      _merge_noid.returncode == 0 and "Traceback" not in _merge_noid.stderr
      and "usage" in _merge_noid.stdout.lower())

_bare_queue = subprocess.run([sys.executable, _scorch, "coa", "queue"],
                             capture_output=True, text=True, env=_cli_env)
# With no snapshot the budget guard fires first; with a snapshot the id/--all guard fires.
# Either way: exit 0, no traceback, and the output contains a useful hint.
check("scorch coa queue with no --all/ids refuses cleanly",
      _bare_queue.returncode == 0 and "Traceback" not in _bare_queue.stderr
      and ("nothing specified" in _bare_queue.stdout.lower()
           or "no live budget" in _bare_queue.stdout.lower()))

# --- Task 1 (2b): run_one extraction ----------------------------------------------
from scorched_earth.runner import run_one  # noqa: E402

_phase = []
def _ex_ok(repo, job, roe):
    return ("pass", {"files": 1, "insertions": 5, "deletions": 0}, "gate passed.")
_oc = run_one(_repo, Job(id="z1", repo=_repo, title="Z", type="test", defcon=3, value=5),
              ROE(), _repo, 3, execute=_ex_ok, on_running=lambda oc: _phase.append(oc.outcome))
check("run_one fires on_running with a 'running' outcome first", _phase == ["running"])
check("run_one returns the finished outcome with branch + merge/discard",
      _oc.outcome == "pass" and _oc.branch == "scorched/z1"
      and "scorched/z1" in (_oc.merge_cmd or "") and _oc.diff["files"] == 1)

def _ex_boom(repo, job, roe):
    raise RuntimeError("died")
_ocb = run_one(_repo, Job(id="z2", repo=_repo, title="Z2", type="test", defcon=3, value=5),
               ROE(), _repo, 4, execute=_ex_boom)
check("run_one turns an executor raise into a fail outcome", _ocb.outcome == "fail")

# --- Phase 2c: killable executor primitive ----------------------------------------
import threading as _kt, time as _ktime  # noqa: E402
from scorched_earth.runner import _run_killable  # noqa: E402

# a long child gets killed promptly when the event is set
_ev = _kt.Event()
_sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
_res = {}
def _go():
    _res["r"] = _run_killable(_sleeper, None, _ev, grace=2.0, poll=0.05)
_th = _kt.Thread(target=_go); _th.start()
_ktime.sleep(0.3)              # let it spawn
_ev.set()                      # request kill
_th.join(5)
# _run_killable now returns (status, output); status is index 0
check("_run_killable returns 'killed' when the event is set", _res.get("r", (None,))[0] == "killed")
check("_run_killable actually terminated the child (thread finished)", not _th.is_alive())

# a fast child runs to completion -> 'done' (kill_event present but never set)
check("_run_killable returns 'done' when the process exits on its own",
      _run_killable([sys.executable, "-c", "pass"], None, _kt.Event(), poll=0.02)[0] == "done")
# no kill_event -> waits to completion
check("_run_killable with no kill_event waits to completion",
      _run_killable([sys.executable, "-c", "pass"], None, None)[0] == "done")

# operator intent wins even if the child finishes coincidentally
_pre = _kt.Event(); _pre.set()
check("_run_killable: a kill requested before the child exits still returns 'killed'",
      _run_killable([sys.executable, "-c", "pass"], None, _pre)[0] == "killed")

# _run_killable captures stdout so the runner can scan it for the rate-limit signal
_capout = _run_killable([sys.executable, "-c", "print('hello-from-child')"], None, None)
check("_run_killable captures child stdout", "hello-from-child" in (_capout[1] or ""))

# REGRESSION (final review): a child that writes MORE than one OS pipe buffer (~64KB) must NOT
# deadlock. Pre-fix the main loop never drained p.stdout, so once the ~64KB pipe filled the child
# blocked on write(), poll() stayed None forever, and the worker hung. With a concurrent reader
# thread it drains to EOF and returns 'done' promptly. kill_event is present but NEVER set.
_flood = [sys.executable, "-c",
          "import sys\n[sys.stdout.write('x'*1024+chr(10)) for _ in range(200)]"]  # ~200KB
_flood_res = {}
def _flood_go():
    _flood_res["r"] = _run_killable(_flood, None, _kt.Event(), grace=2.0, poll=0.05)
_flood_th = _kt.Thread(target=_flood_go); _flood_th.start()
_flood_th.join(8)               # generous ceiling; un-drained version never returns at all
check("_run_killable does not deadlock on >pipe-buffer output (drains concurrently)",
      not _flood_th.is_alive() and _flood_res.get("r", (None,))[0] == "done")
check("_run_killable returns the FULL flooded output (nothing lost to the buffer)",
      len(_flood_res.get("r", (None, ""))[1]) >= 200 * 1025)

# _run_killable now also surfaces the child returncode (Fix 3: execute_job needs it to catch a
# nonzero claude exit with no changes — a phantom 'pass' otherwise).
_rc_ok = _run_killable([sys.executable, "-c", "pass"], None, None)
check("_run_killable returns returncode 0 on a clean exit (no kill_event)", _rc_ok[2] == 0)
_rc_bad = _run_killable([sys.executable, "-c", "import sys; sys.exit(7)"], None, _kt.Event())
check("_run_killable surfaces a nonzero child returncode", _rc_bad[2] == 7)

# --- pick_next no-budget-gate, detect_rate_limit, ROE caps ------------------------
from scorched_earth import runner as _rn  # noqa: E402
from scorched_earth.jobs import Job as _RJ  # noqa: E402
from scorched_earth.roe import ROE as _RROE  # noqa: E402

# pick_next no longer gates on budget — returns the next ROE-allowed job regardless of size
_q = [_RJ(id="big", repo=".", title="B", type="docs", defcon=3, value=9)]
check("pick_next returns the next ROE-allowed job (no budget gate)",
      _rn.pick_next(_q, _RROE()) is not None and _rn.pick_next(_q, _RROE()).id == "big")
check("pick_next still skips ROE-disallowed types",
      _rn.pick_next([_RJ(id="x", repo=".", title="X", type="refactor", defcon=3, value=5)],
                    _RROE()) is None)

# detect_rate_limit keys on the stream-json rate_limit signal, not normal failures
check("detect_rate_limit true on the stream-json rate_limit event",
      _rn.detect_rate_limit('{"type":"system","subtype":"api_retry","error":"rate_limit"}') is True)
check("detect_rate_limit false on a normal job failure",
      _rn.detect_rate_limit('{"type":"result","is_error":true,"error":"server_error"}') is False)
check("detect_rate_limit false on empty output", _rn.detect_rate_limit("") is False)

# ROE gains an optional run cap, default off (window cost caps are gone)
check("ROE max_jobs defaults to None (off)", _RROE().max_jobs is None)

# plan_run no longer forfeits for budget
_disp = _rn.plan_run([_RJ(id="d", repo=".", title="D", type="docs", defcon=3, value=9)], _RROE())
check("plan_run never emits skipped-budget",
      all(d != "skipped-budget" for _, d in _disp))

# --- Task 4: run_queue halts on a usage-limit outcome (resumable) -----------------
# a job that returns outcome 'limit' halts the queue; the rest stay un-run (resumable)
import tempfile as _tf, os as _os, json as _json2  # noqa: E402
def _mk_runner_repo(jobs):
    r = _tf.mkdtemp(); _os.makedirs(_os.path.join(r, ".scorched"), exist_ok=True)
    from scorched_earth import coa_io as _cio
    _cio.write_queue(r, jobs); return r
_lim_repo = _mk_runner_repo([_RJ(id="j1", repo=".", title="1", type="docs", defcon=3, value=9),
                             _RJ(id="j2", repo=".", title="2", type="docs", defcon=3, value=8)])
_calls = []
def _lim_exec(repo, job, roe):
    _calls.append(job.id)
    return ("limit", None, "usage limit") if job.id == "j1" else ("pass", None, "ok")
_state_ok = {"snapshot": {"five_hour_pct": 5, "seven_day_pct": 50, "five_hour_reset": 9_999_999_999},
             "recommendation": {"windows_left": 5, "level": "green"}}
_rr = _rn.run_queue(_lim_repo, _state_ok, now=1, date="2026-06-25", execute=_lim_exec)
check("run_queue halts the queue on a usage-limit outcome (j2 never runs)", _calls == ["j1"])
check("run_queue records the limit job as 'limit', not 'fail'",
      any(j.outcome == "limit" for j in _rr.jobs))

# --- Stage 6: roadblock ladder (watchdog, report, notify, resume) -----------------
from scorched_earth.runner import (_run_killable, render_roadblock_md, handle_roadblock,  # noqa: E402
                                   execute_job as _exec_real)
import scorched_earth.statusline as _sl  # noqa: E402
_sl._notify = lambda *a, **k: True       # silence real desktop notifications during tests

_st_idle, _out_idle, _rc_idle = _run_killable(["sleep", "2"], ".", None, poll=0.05, idle_secs=0.3)
check("_run_killable flags a silent job as idle (the roadblock watchdog)", _st_idle == "idle")

_oc_rb = JobOutcome(seq=1, id="rb", title="Stuck job", type="audit", defcon=1,
                    outcome="roadblocked", branch="scorched/rb", note="roadblock: gate FAILED (pytest).")
_rbmd = render_roadblock_md(_oc_rb, "/tmp/r")
check("render_roadblock_md carries what-happened, the branch, and the resume command",
      "Stuck job (rb)" in _rbmd and "scorched/rb" in _rbmd and "scorch coa resume rb" in _rbmd)

_rbrepo = tempfile.mkdtemp()
handle_roadblock(_rbrepo, _oc_rb)
check("handle_roadblock writes the report and stamps a repo-relative path",
      _oc_rb.roadblock == ".scorched/roadblocks/rb.md" and os.path.exists(_io.roadblock_path(_rbrepo, "rb")))
_oc_ok = JobOutcome(seq=1, id="p", title="P", type="test", defcon=3, outcome="pass")
handle_roadblock(_rbrepo, _oc_ok)
check("handle_roadblock is a no-op for non-roadblocked outcomes", _oc_ok.roadblock is None)

_ghostrepo = tempfile.mkdtemp()
_go, _gd, _gn = _exec_real(_ghostrepo, Job(id="ghost", repo=_ghostrepo, title="G", type="test"),
                           ROE(), resume=True)
check("execute_job resume with no prior worktree returns a clean fail",
      _go == "fail" and "no prior worktree" in _gn)

_rbq_repo = _mk_runner_repo([_RJ(id="k1", repo=".", title="1", type="docs", defcon=3, value=9),
                             _RJ(id="k2", repo=".", title="2", type="docs", defcon=3, value=8)])
def _rb_exec(repo, job, roe):
    return ("roadblocked", None, "roadblock: stuck") if job.id == "k1" else ("pass", None, "ok")
_rrq = _rn.run_queue(_rbq_repo, _state_ok, now=1, date="2026-06-26", execute=_rb_exec)
check("run_queue records a roadblock but does NOT halt (k2 still runs)",
      [j.outcome for j in _rrq.jobs] == ["roadblocked", "pass"] and _rrq.state == "done")
check("run_queue writes the roadblock report + counts it in the summary",
      os.path.exists(_io.roadblock_path(_rbq_repo, "k1")) and "roadblocked" in _rrq.note)
check("board_state files a roadblocked job under finished, not proposed",
      any(j.get("outcome") == "roadblocked" for j in _io.board_state(_rbq_repo)["finished"]))

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
