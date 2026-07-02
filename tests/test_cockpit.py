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


# --- Task 2: pick_next (ungated; budget envelope retired) -------------------------
from scorched_earth.jobs import Job  # noqa: E402
from scorched_earth.roe import ROE, roe_from_dict  # noqa: E402
from scorched_earth.runner import pick_next  # noqa: E402

_q = [Job(id="ref", repo="r", title="ref", type="refactor", value=9),  # ROE-blocked
      Job(id="ok",  repo="r", title="ok",  type="docs", value=4)]
check("pick_next skips ROE-blocked, returns the first ROE-allowed job (no budget gate)",
      pick_next(_q, ROE()).id == "ok")
check("pick_next returns None when nothing is ROE-allowed",
      pick_next([Job(id="ref", repo="r", title="ref", type="refactor", value=9)], ROE()) is None)
check("pick_next returns an over-headroom job (no budget gate)",
      pick_next([Job(id="big", repo="r", title="big", type="docs", value=5)], ROE()).id == "big")


# --- Task 3: queue ops ------------------------------------------------------------
import importlib  # noqa: E402
_home = tempfile.mkdtemp(); _repo = tempfile.mkdtemp()
os.environ["HOME"] = _home
import scorched_earth.state as _st  # noqa: E402
importlib.reload(_st)
import scorched_earth.coa_io as _io  # noqa: E402
importlib.reload(_io)

_io.write_queue(_repo, [Job(id="a", repo=_repo, title="A", type="test", value=5),
                        Job(id="b", repo=_repo, title="B", type="docs", value=4),
                        Job(id="c", repo=_repo, title="C", type="perf", value=3)])
check("unqueue removes by id", [j.id for j in _io.unqueue(_repo, "b")] == ["a", "c"])
check("unqueue persisted", [j.id for j in _io.read_queue(_repo)] == ["a", "c"])
_io.write_queue(_repo, [Job(id="a", repo=_repo, title="A", type="test", value=5),
                        Job(id="b", repo=_repo, title="B", type="docs", value=4),
                        Job(id="c", repo=_repo, title="C", type="perf", value=3)])
check("reorder applies the given order", [j.id for j in _io.reorder(_repo, ["c", "a", "b"])] == ["c", "a", "b"])
check("reorder appends un-named queued jobs after",
      [j.id for j in _io.reorder(_repo, ["b"])] == ["b", "c", "a"])
# depth must survive the queue.json round-trip (was lost: 9 -> re-derived 10)
_io.write_queue(_repo, [Job(id="d9", repo=_repo, title="D9", type="test", value=8)])
check("queue round-trip preserves defcon (no re-derivation)",
      _io.read_queue(_repo)[0].defcon == 3)


# --- Task 4: board_state assembler ------------------------------------------------
os.makedirs(os.path.join(_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_repo, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "p1", "title": "Prop1", "type": "test", "est_windows": 1, "value": 5},
               {"id": "q1", "title": "Queued1", "type": "docs", "est_windows": 1, "value": 4},
               {"id": "d1", "title": "Done1", "type": "perf", "est_windows": 1, "value": 3}], f)
_io.write_queue(_repo, [Job(id="q1", repo=_repo, title="Queued1", type="docs", value=4)])
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

# board_state is running-aware: an in-flight job (unqueued, not yet finished, still in
# jobs.json) is held out of `proposed` only when its id is passed via running_ids.
_io.unqueue(_repo_norec, "n1")          # simulate the pick: gone from the queue, mid-run
check("board_state WITHOUT running_ids leaks the in-flight job into proposed",
      [j["id"] for j in _io.board_state(_repo_norec)["proposed"]] == ["n1"])
check("board_state(running_ids=[id]) hides the in-flight job from proposed",
      _io.board_state(_repo_norec, running_ids=["n1"])["proposed"] == [])

# --- Task 5: Engine (event-driven advance) ----------------------------------------
from scorched_earth.coa_serve import Engine  # noqa: E402
import time as _time5  # noqa: E402

def _wait_idle(eng, timeout=5):
    """Wait up to `timeout` seconds for the engine to go idle (busy=False)."""
    end = _time5.time() + timeout
    while _time5.time() < end and eng.state_json()["busy"]:
        _time5.sleep(0.01)

def _mk_repo(jobs):
    r = tempfile.mkdtemp()
    os.makedirs(os.path.join(r, ".scorched"), exist_ok=True)
    with open(os.path.join(r, ".scorched", "jobs.json"), "w") as f:
        json.dump([{"id": j.id, "title": j.title, "type": j.type,
                    "defcon": j.defcon, "value": j.value} for j in jobs], f)
    _io.write_queue(r, jobs)
    return r

_ran = []
def _exec(repo, job, roe):
    _ran.append(job.id)
    return ("pass", {"files": 1, "insertions": 3, "deletions": 0}, "ok")
_STATE = {"snapshot": {"now": 1, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
          "recommendation": {"windows_left": 2.5, "level": "green"}}
_r = _mk_repo([Job(id="t1", repo=".", title="T1", type="test", value=5),
               Job(id="r1", repo=".", title="R1", type="refactor", value=9),  # ROE block
               Job(id="t2", repo=".", title="T2", type="test", value=4),
               Job(id="t3", repo=".", title="T3", type="test", value=3)])  # runs regardless (no budget gate)
_beats = []
_eng = Engine([_r], execute=_exec, broadcast=lambda: _beats.append(1),
              load_state=lambda: _STATE, now=lambda: 1)
_eng.run(_r); _wait_idle(_eng)
# no budget envelope anymore: every ROE-allowed card drains in order, regardless of headroom
check("engine drains all ROE-allowed additive cards in order (no budget gate)", _ran == ["t1", "t2", "t3"])
check("engine skips the ROE-blocked card (refactor never ran)", "r1" not in _ran)
check("engine leaves only the ROE-blocked card queued (t3 ran)",
      [j.id for j in _io.read_queue(_r)] == ["r1"])
check("engine broadcast fired across the run", len(_beats) >= 4)
check("engine not busy after draining", _eng.state_json()["busy"] is False)

# crash containment + no-retry
_ran2 = []
def _boom(repo, job, roe):
    _ran2.append(job.id)
    if job.id == "x1":
        raise RuntimeError("died")
    return ("pass", None, "ok")
_r2 = _mk_repo([Job(id="x1", repo=".", title="X1", type="test", value=5),
                Job(id="x2", repo=".", title="X2", type="test", value=4)])
_eng2 = Engine([_r2], execute=_boom, load_state=lambda: _STATE, now=lambda: 1)
_eng2.run(_r2); _wait_idle(_eng2)
check("engine: a crashing job is dropped (not retried) and the chain continues",
      _ran2 == ["x1", "x2"] and _io.read_queue(_r2) == [])

# stop halts the chain
_ran3 = []
def _exec_stop(repo, job, roe):
    _ran3.append(job.id)
    _eng3.stop()                     # request stop after the first job
    return ("pass", None, "ok")
_r3 = _mk_repo([Job(id="s1", repo=".", title="S1", type="test", value=5),
                Job(id="s2", repo=".", title="S2", type="test", value=4)])
_eng3 = Engine([_r3], execute=_exec_stop, load_state=lambda: _STATE, now=lambda: 1)
_eng3.run(_r3); _wait_idle(_eng3)
check("engine: stop halts the chain after the current job", _ran3 == ["s1"])
check("engine: operator stop is reflected in state_json (stopped + reason)",
      _eng3.state_json()["stopped"] is True and _eng3.state_json()["stop_reason"] == "operator")

# Run clears a prior Stop (Stop is a pause, not a permanent kill)
_ran_sr = []
def _exec_sr(repo, job, roe):
    _ran_sr.append(job.id); return ("pass", None, "ok")
_rs = _mk_repo([Job(id="p1", repo=".", title="P1", type="test", value=5),
                Job(id="p2", repo=".", title="P2", type="test", value=4)])
_engsr = Engine([_rs], execute=_exec_sr, load_state=lambda: _STATE, now=lambda: 1)
_engsr.stop()                         # pre-stopped
_engsr.run(_rs); _wait_idle(_engsr)   # Run must clear the stop flag and drain
check("engine: Run resumes after a prior Stop (clears the stop flag)",
      sorted(_ran_sr) == ["p1", "p2"] and _io.read_queue(_rs) == []
      and _engsr.state_json()["busy"] is False)
check("engine: Run clears the halt reason (stop is a pause, not a permanent halt)",
      _engsr.state_json()["stopped"] is False and _engsr.state_json()["stop_reason"] is None)

# --- Task 6: HTTP server (token, routing, SSE) ------------------------------------
import http.client  # noqa: E402
import threading as _threading  # noqa: E402
from scorched_earth.coa_serve import make_server  # noqa: E402

_r6 = _mk_repo([Job(id="g1", repo=".", title="G1", type="test", value=5)])
_eng6 = Engine([_r6], execute=_exec, load_state=lambda: _STATE, now=lambda: 1)
_TOKEN = "secret-token-xyz"
_httpd, _port = make_server(_eng6, _TOKEN)
_srv_thread = _threading.Thread(target=_httpd.serve_forever, daemon=True)
_srv_thread.start()

def _get(path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", _port, timeout=3)
    c.request("GET", path, headers=headers or {}); r = c.getresponse(); body = r.read(); c.close()
    return r.status, body

def _post(path, payload, token):
    c = http.client.HTTPConnection("127.0.0.1", _port, timeout=3)
    hdr = {"Content-Type": "application/json"}
    if token: hdr["X-Scorch-Token"] = token
    c.request("POST", path, body=json.dumps(payload), headers=hdr)
    r = c.getresponse(); body = r.read(); c.close()
    return r.status, body

check("server binds loopback only", _httpd.server_address[0] == "127.0.0.1")
check("GET / without token is 403", _get("/")[0] == 403)
check("GET / with token serves html", _get(f"/?t={_TOKEN}")[0] == 200)
check("POST without token is 403", _post("/queue", {"repo": _r6, "id": "g1"}, None)[0] == 403)
import time as _t6
_inj = _post("/run", {"repo": _r6, "cmd": "rm -rf /", "launch": "evil"}, _TOKEN)
_t6.sleep(0.2)   # let the worker thread settle
check("POST with raw command/launch fields executes no command (job-ids only)",
      _inj[0] == 200 and "rm -rf /" not in _ran and "evil" not in _ran)
_st6, _b6 = _get(f"/state?t={_TOKEN}")
check("GET /state returns board json", _st6 == 200 and b"repos" in _b6)
# /queue mutates the queue file
_io.write_queue(_r6, [Job(id="g1", repo=".", title="G1", type="test", value=5)])
_post("/reorder", {"repo": _r6, "ids": ["g1"]}, _TOKEN)
check("POST /reorder returns ok", _post("/reorder", {"repo": _r6, "ids": ["g1"]}, _TOKEN)[0] == 200)

_raised = False
try:
    make_server(_eng6, "")
except ValueError:
    _raised = True
check("make_server refuses an empty token", _raised)

_unknown = tempfile.mkdtemp()
check("POST naming an unregistered repo is rejected (400)",
      _post("/run", {"repo": _unknown}, _TOKEN)[0] == 400)

_httpd.shutdown()

# --- Task 7: cockpit renderer -----------------------------------------------------
from scorched_earth.coa_serve import render_cockpit  # noqa: E402

_html = render_cockpit("tok-123", {"repos": [{"repo": _r6, "name": "g", "proposed": [],
                                              "queued": [{"id": "g1"}], "finished": []}],
                                   "running": None, "busy": False})
_txt = _html.decode("utf-8")
check("render_cockpit substitutes both tokens",
      "__COCKPIT_TOKEN__" not in _txt and "__COCKPIT_JSON__" not in _txt)
check("render_cockpit embeds token + state",
      "tok-123" in _txt and "g1" in _txt and _txt.lstrip().lower().startswith("<!doctype html"))

# --- Task 8: CLI verb (no-repos refusal; never starts the blocking server) ---------
import subprocess  # noqa: E402
_cli_env = dict(os.environ); _cli_env["HOME"] = tempfile.mkdtemp()
_scorch = os.path.join(os.path.dirname(__file__), "..", "bin", "scorch")
_p = subprocess.run([sys.executable, _scorch, "coa", "--serve"],
                    capture_output=True, text=True, env=_cli_env, timeout=10)
check("scorch coa --serve with no linked repos refuses cleanly (exit 0, no traceback)",
      _p.returncode == 0 and "Traceback" not in _p.stderr
      and ("link" in _p.stdout.lower() or "no repos" in _p.stdout.lower()))

# --- concurrency: rapid /queue POSTs must not lose cards (queue mutations under the lock) --
import threading as _ccth, time as _cctime  # noqa: E402
_cc_repo = tempfile.mkdtemp()
os.makedirs(os.path.join(_cc_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_cc_repo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": _c, "title": _c, "type": "test", "est_windows": 0.5, "value": 5}
               for _c in "abcdef"], _f)
_cc_eng = Engine([_cc_repo], execute=lambda *_a: ("pass", None, "ok"),
                 load_state=lambda: _STATE, now=lambda: 1)
_cc_httpd, _cc_port = make_server(_cc_eng, "cc-tok")
_ccth.Thread(target=_cc_httpd.serve_forever, daemon=True).start()
def _cc_req(path, body):
    _c = http.client.HTTPConnection("127.0.0.1", _cc_port, timeout=3)
    _c.request("POST", path, json.dumps(body),
               {"Content-Type": "application/json", "X-Scorch-Token": "cc-tok"})
    _c.getresponse().read(); _c.close()
_cc_req("/stop", {})                                          # stage without auto-running
_cc_threads = [_ccth.Thread(target=_cc_req, args=("/queue", {"repo": _cc_repo, "id": _c}))
               for _c in "abcdef"]                            # 6 concurrent /queue POSTs
[t.start() for t in _cc_threads]; [t.join() for t in _cc_threads]
_cc_end = _cctime.time() + 3
while _cctime.time() < _cc_end and len(_io.read_queue(_cc_repo)) < 6:
    _cctime.sleep(0.02)
check("rapid concurrent /queue loses no cards (mutations serialized under the lock)",
      sorted(j.id for j in _io.read_queue(_cc_repo)) == list("abcdef"))
_cc_httpd.shutdown()

# --- Phase 2c: engine kill -------------------------------------------------------
import threading as _k2th, time as _k2time  # noqa: E402
import scorched_earth.runner as _k2runner  # noqa: E402

_k2_started = _k2th.Event()
def _exec_killable(repo, job, roe):
    # mimic a long job: block on the engine-provided kill event (thread-local), like execute_job
    ev = getattr(_k2runner._kill_ctx, "event", None)
    _k2_started.set()
    if ev is not None and ev.wait(3):
        return ("killed", None, "killed by operator — work discarded.")
    return ("pass", None, "ran to completion")
_rk = _mk_repo([Job(id="kill-me", repo=".", title="Kill me", type="test", value=5),
                Job(id="next-up", repo=".", title="Next", type="test", value=4)])
_engk = Engine([_rk], execute=_exec_killable, load_state=lambda: _STATE, now=lambda: 1)
_tk = _k2th.Thread(target=_engk.run, args=(_rk,), daemon=True); _tk.start()
_k2_started.wait(3)                                  # kill-me is now "running"
_engk.kill(_rk, "kill-me")                           # operator kills it
_tk.join(5); _wait_idle(_engk)       # wait for kill-me to die and next-up to complete
_fin = [j["id"] for j in _io.board_state(_rk)["finished"]]
_prop = [j["id"] for j in _io.board_state(_rk)["proposed"]]
check("engine.kill ends the running job (not left busy)", _engk.state_json()["busy"] is False)
check("killed job is NOT in finished (pass/fail only)", "kill-me" not in _fin)
check("killed job returns to proposed (re-queueable)", "kill-me" in _prop)
check("after a kill the chain continues to the next job (next-up ran)", "next-up" in _fin)

# /kill: token-guarded, repo-validated, job-ids only
_rkill = _mk_repo([Job(id="z", repo=".", title="Z", type="test", value=5)])
_engkill = Engine([_rkill], execute=lambda *a: ("pass", None, "ok"), load_state=lambda: _STATE, now=lambda: 1)
_hk, _pk = make_server(_engkill, "k-tok")
import threading as _k3
_k3.Thread(target=_hk.serve_forever, daemon=True).start()
def _kpost(body, token):
    c = http.client.HTTPConnection("127.0.0.1", _pk, timeout=3)
    h = {"Content-Type": "application/json"}
    if token: h["X-Scorch-Token"] = token
    c.request("POST", "/kill", json.dumps(body), h); r = c.getresponse(); r.read(); c.close(); return r.status
check("POST /kill without token is 403", _kpost({"repo": _rkill, "id": "z"}, None) == 403)
check("POST /kill with unknown repo is 400", _kpost({"repo": tempfile.mkdtemp(), "id": "z"}, "k-tok") == 400)
check("POST /kill with token + known repo is 200 (no-op when nothing running)",
      _kpost({"repo": _rkill, "id": "z"}, "k-tok") == 200)
_hk.shutdown()

# --- Phase 2c: cockpit Kill button wiring -----------------------------------------
_kh = render_cockpit("tk", {"repos": [], "running": None, "busy": False}).decode("utf-8")
check("cockpit template wires a /kill POST", '"/kill"' in _kh or "/kill" in _kh)

# --- paused-by-default: stage the queue first, Run drains it -----------------------
_rp = tempfile.mkdtemp()
os.makedirs(os.path.join(_rp, ".scorched"), exist_ok=True)
with open(os.path.join(_rp, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "s1", "title": "S1", "type": "test", "value": 5},
               {"id": "s2", "title": "S2", "type": "test", "value": 4}], _f)
_ran_p = []
_engp = Engine([_rp], execute=lambda repo, job, roe: (_ran_p.append(job.id), ("pass", None, "ok"))[1],
               load_state=lambda: _STATE, now=lambda: 1)
_engp.stop()                          # cockpit starts paused (as bin/scorch --serve does)
_engp.queue(_rp, "s1"); _engp.queue(_rp, "s2")     # drag cards in while paused
check("paused cockpit: dragging cards in stages them without running",
      _ran_p == [] and [j.id for j in _io.read_queue(_rp)] == ["s1", "s2"])
_engp.run(_rp); _wait_idle(_engp)    # press Run
check("paused cockpit: Run then drains the staged queue in order",
      _ran_p == ["s1", "s2"] and _io.read_queue(_rp) == [])

# --- board_state job briefs carry defcon + approval_required ----------------------
_rb2 = tempfile.mkdtemp(); os.makedirs(os.path.join(_rb2, ".scorched"), exist_ok=True)
with open(os.path.join(_rb2, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "g", "title": "G", "type": "test", "defcon": 2, "value": 6}], _f)
check("board_state brief carries defcon", _io.board_state(_rb2)["proposed"][0]["defcon"] == 2)
check("board_state brief carries approval_required", "approval_required" in _io.board_state(_rb2)["proposed"][0])

# cockpit cards render DEFCON (template updated in Task 9)
_defcon_repo = tempfile.mkdtemp()
os.makedirs(os.path.join(_defcon_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_defcon_repo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "d1", "title": "DefconJob", "type": "test", "defcon": 2, "value": 7}], _f)
_hk2 = render_cockpit("tk", {
    "repos": [{"repo": _defcon_repo, "name": "dr",
               "proposed": [{"id": "d1", "title": "DefconJob", "type": "test",
                              "defcon": 2, "approval_required": True, "value": 7}],
               "queued": [], "finished": []}],
    "running": None, "busy": False, "weekly_reserve_pct": 42
}).decode("utf-8")
check("cockpit renders a DEFCON badge for proposed cards", "defcon-" in _hk2)

# --- parallel per-repo execution -------------------------------------------------
import threading as _pth, time as _ptime  # noqa: E402
# two repos run CONCURRENTLY (both jobs in flight at once)
_pgate = _pth.Event()
def _par_exec(repo, job, roe):
    _pgate.wait(3)                                   # hold each job until the test releases
    return ("pass", None, "ok")
_pA = _mk_repo([Job(id="pa", repo=".", title="PA", type="test", value=5)])
_pB = _mk_repo([Job(id="pb", repo=".", title="PB", type="test", value=5)])
_par = Engine([_pA, _pB], execute=_par_exec, load_state=lambda: _STATE, now=lambda: 1)
_par.run([_pA, _pB])
_end = _ptime.time() + 3
while _ptime.time() < _end and len(_par.state_json()["running"]) < 2:
    _ptime.sleep(0.02)
check("two armed repos run CONCURRENTLY (2 jobs in flight at once)",
      len(_par.state_json()["running"]) == 2)
_pgate.set()
_end = _ptime.time() + 3
while _ptime.time() < _end and _par.state_json()["busy"]:
    _ptime.sleep(0.02)
check("both repos drain after release (queues empty, idle)",
      _par.state_json()["busy"] is False and _io.read_queue(_pA) == [] and _io.read_queue(_pB) == [])

# a usage-limit on one repo's job HALTS all workers (no shared budget envelope anymore)
_hl_gate = _pth.Event()
def _hl_exec(repo, job, roe):
    if job.id.endswith("1"):
        return ("limit", None, "usage limit")     # first job in each repo trips the limit
    _hl_gate.wait(2)
    return ("pass", None, "ok")
_hlA = _mk_repo([Job(id="A1", repo=".", title="x", type="docs", value=9),
                 Job(id="A2", repo=".", title="x", type="docs", value=8)])
_hl = Engine([_hlA], execute=_hl_exec, load_state=lambda: _STATE, now=lambda: 1)
_hl.run([_hlA])
_end = _ptime.time() + 3
while _ptime.time() < _end and _hl.state_json()["busy"]:
    _ptime.sleep(0.02)
check("a usage-limit halts the engine; the limit job is re-queued (resumable)",
      "A1" in [j["id"] for j in _io.board_state(_hlA)["queued"]]
      and "A1" not in [j["id"] for j in _io.board_state(_hlA)["finished"]])

# state_json drops headroom/fit, keeps weekly_reserve_pct; board briefs carry defcon + approval_required
_sj = _hl.state_json()
check("state_json drops headroom/fit", "headroom" not in _sj)
check("state_json exposes weekly reserve context", "weekly_reserve_pct" in _sj)
check("state_json reports the halt reason on a usage-limit (stopped + reason=limit)",
      _sj["stopped"] is True and _sj["stop_reason"] == "limit")
check("board briefs carry defcon + approval_required",
      all("defcon" in jb and "approval_required" in jb
          for r in _sj["repos"] for jb in r["proposed"] + r["queued"]))

# optional ROE max_jobs cap stops the drain after N jobs (off by default)
_capdir = tempfile.mkdtemp(); os.makedirs(os.path.join(_capdir, ".scorched"), exist_ok=True)
with open(os.path.join(_capdir, ".scorched", "roe.json"), "w") as _f:
    json.dump({"max_jobs": 1}, _f)
with open(os.path.join(_capdir, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "c1", "title": "C1", "type": "test", "value": 5},
               {"id": "c2", "title": "C2", "type": "test", "value": 4}], _f)
_io.write_queue(_capdir, [Job(id="c1", repo=".", title="C1", type="test", value=5),
                          Job(id="c2", repo=".", title="C2", type="test", value=4)])
_cap_ran = []
_capeng = Engine([_capdir], execute=lambda repo, job, roe: (_cap_ran.append(job.id), ("pass", None, "ok"))[1],
                 load_state=lambda: _STATE, now=lambda: 1)
_capeng.run([_capdir]); _wait_idle(_capeng)
check("ROE max_jobs cap stops the drain after one job (c2 left queued)",
      _cap_ran == ["c1"] and "c2" in [j["id"] for j in _io.board_state(_capdir)["queued"]])

# per-repo kill targets one repo's in-flight job; the other keeps running
import scorched_earth.runner as _krun  # noqa: E402
_kgate = _pth.Event(); _kstarted = _pth.Event()
def _k_exec(repo, job, roe):
    ev = getattr(_krun._kill_ctx, "event", None)
    _kstarted.set()
    if ev is not None and ev.wait(3):
        return ("killed", None, "killed")
    _kgate.wait(3)
    return ("pass", None, "ok")
_kA = _mk_repo([Job(id="ka", repo=".", title="x", type="test", value=5)])
_kB = _mk_repo([Job(id="kb", repo=".", title="x", type="test", value=5)])
_keng = Engine([_kA, _kB], execute=_k_exec, load_state=lambda: _STATE, now=lambda: 1)
_keng.run([_kA, _kB])
_end = _ptime.time() + 3
while _ptime.time() < _end and len(_keng.state_json()["running"]) < 2:
    _ptime.sleep(0.02)
_keng.kill(_kA, "ka")                                # kill only repo A's job
_kgate.set()                                         # let B finish
_end = _ptime.time() + 6                             # B may still be in ev.wait(3); allow full drain
while _ptime.time() < _end and _keng.state_json()["busy"]:
    _ptime.sleep(0.02)
check("per-repo kill: killed repo's job returns to proposed, the other repo completes",
      "ka" in [j["id"] for j in _io.board_state(_kA)["proposed"]]
      and "kb" in [j["id"] for j in _io.board_state(_kB)["finished"]])

# /run accepts a repos list; every repo validated
_rrA = _mk_repo([Job(id="z", repo=".", title="Z", type="test", value=5)])
_rrB = _mk_repo([Job(id="y", repo=".", title="Y", type="test", value=5)])
_run_eng = Engine([_rrA, _rrB], execute=lambda *a: ("pass", None, "ok"),
                  load_state=lambda: _STATE, now=lambda: 1)
_run_eng.stop()                                   # paused so the POST just validates/dispatches
_hr, _pr = make_server(_run_eng, "r-tok")
import threading as _rth
_rth.Thread(target=_hr.serve_forever, daemon=True).start()
def _rpost(body):
    c = http.client.HTTPConnection("127.0.0.1", _pr, timeout=3)
    c.request("POST", "/run", json.dumps(body), {"Content-Type": "application/json", "X-Scorch-Token": "r-tok"})
    r = c.getresponse(); r.read(); c.close(); return r.status
check("POST /run with a repos list is accepted (200)", _rpost({"repos": [_rrA, _rrB]}) == 200)
check("POST /run with an unknown repo in the list is 400",
      _rpost({"repos": [_rrA, tempfile.mkdtemp()]}) == 400)
check("POST /run with single {repo} still works (back-compat)", _rpost({"repo": _rrA}) == 200)
_hr.shutdown()

# cockpit wires a repos-list run (Run-all over the armed checkboxes)
_hr3 = render_cockpit("tk", {"repos": [], "running": None, "busy": False}).decode("utf-8")
check("cockpit Run posts a repos list (armed checkboxes)", "repos" in _hr3 and "armed" in _hr3.lower())

# cockpit renders running as a list (multiple in-flight)
_hp = render_cockpit("tk", {"repos": [{"repo": "/r/a", "name": "a", "proposed": [], "queued": [], "finished": []},
                                      {"repo": "/r/b", "name": "b", "proposed": [], "queued": [], "finished": []}],
                            "running": [{"repo": "/r/a", "id": "j1"}, {"repo": "/r/b", "id": "j2"}],
                            "busy": True}).decode("utf-8")
check("cockpit handles a running LIST (renders without error, references running as array)",
      "__COCKPIT_" not in _hp and "running" in _hp.lower()
      and "PARALLEL" in _hp)

# --- in-flight job must not flicker back into the proposed column ----------------
# Regression: a worker unqueues a job at pick time but only writes it to the run record
# on completion. In that window board_state saw it in neither queue nor finished and,
# since it's still in jobs.json, leaked it back into `proposed` — so the live cockpit
# showed a RUNNING card simultaneously in the proposed column. state_json must hide
# any in-flight job from its repo's proposed list.
_fgate = _pth.Event()
def _flick_exec(repo, job, roe):
    _fgate.wait(3); return ("pass", None, "ok")
_fr = _mk_repo([Job(id="f1", repo=".", title="F1", type="test", value=5),
                Job(id="f2", repo=".", title="F2", type="test", value=5)])
_feng = Engine([_fr], execute=_flick_exec, load_state=lambda: _STATE, now=lambda: 1)
_feng.run([_fr])
_end = _ptime.time() + 3
while _ptime.time() < _end and not _feng.state_json()["running"]:
    _ptime.sleep(0.02)
_sj = _feng.state_json()
_running_id = _sj["running"][0]["id"] if _sj["running"] else None
_prop_ids = [j["id"] for _rep in _sj["repos"] for j in _rep["proposed"]]
check("state_json hides the in-flight job from proposed (no RUNNING-in-proposed flicker)",
      _running_id is not None and _running_id not in _prop_ids)
_fgate.set()
_end = _ptime.time() + 3
while _ptime.time() < _end and _feng.state_json()["busy"]:
    _ptime.sleep(0.02)

# --- Task 9: cockpit DEFCON board — headroom dropped, DEFCON + approval rendered ----
_hd = render_cockpit("tk", {"repos": [{"repo":"/r/a","name":"a",
        "proposed":[{"id":"p1","title":"P","type":"docs","defcon":2,"approval_required":True,"value":7}],
        "queued":[{"id":"q1","title":"Q","type":"test","defcon":4,"approval_required":False,"value":5}],
        "finished":[]}],
        "running": [], "busy": False, "weekly_reserve_pct": 19}).decode("utf-8")
check("cockpit renders DEFCON badge for proposed card", "defcon-2" in _hd)
check("cockpit renders DEFCON badge for queued card", "defcon-4" in _hd)
check("cockpit renders approval marker for approval_required card", "APPROVAL REQUIRED" in _hd)
check("cockpit weekly_reserve_pct context is present", "weekly_reserve_pct" in _hd)
check("cockpit headroom not in rendered HTML", "headroom" not in _hd.lower())
check("cockpit no longer labels the HUD 'BUDGET SPENT'", "BUDGET SPENT" not in _hd)
# token + JSON substitution
check("__COCKPIT_TOKEN__ and __COCKPIT_JSON__ are fully substituted",
      "__COCKPIT_TOKEN__" not in _hd and "__COCKPIT_JSON__" not in _hd)

# --- Phase 2: HALTED banner keyed on stop_reason == "limit" (#2/#8) ----------------
# The cockpit paints the flag client-side from state_json; these confirm the template wires
# the HALTED branch (distinct from IDLE) off the limit reason and carries the resume hint.
_hh = render_cockpit("tk", {"repos": [], "running": [], "busy": False,
                            "stopped": True, "stop_reason": "limit"}).decode("utf-8")
check("cockpit wires a HALTED flag off stop_reason == 'limit'",
      'stop_reason === "limit"' in _hh and "HALTED" in _hh)
check("cockpit HALTED state carries a resume hint (re-queued; press RUN)",
      "resume" in _hh.lower() and "RUN" in _hh)
check("cockpit HALTED is distinct from an operator pause (operator does not force HALTED)",
      'state.stop_reason === "limit"' in _hh)  # operator/None fall through to IDLE

# --- Phase 2: CRATERED (fail) badge is legible (#9) --------------------------------
check("cockpit CRATERED badge explains the fail state (work discarded)",
      "CRATERED" in _hh and "work was discarded" in _hh)

# --- Phase 2: approval marker explains why + how (#1) ------------------------------
check("cockpit approval marker explains why (auto-run threshold) and how (RUN / --approve)",
      "auto-run threshold" in _hh and "scorch coa run --approve" in _hh and "APPROVAL REQUIRED" in _hh)

# --- Phase 2: manual board REFRESH pulls an external jobs.json change (#6) ----------
# SSE only pushes on engine events, so a fresh /coa scan is invisible until /state is re-read.
check("cockpit wires a manual REFRESH that re-reads /state (no re-scan)",
      "btnRefresh" in _hh and '/state?t="' in _hh and "re-scan" in _hh)

# --- Phase 2: the unified shell (one server, big-tab frame over all three surfaces) ---
from scorched_earth import shell as _shell  # noqa: E402
# In shell mode make_server serves the frame at / and folds in the two read-only tabs
# (/sitrep, /coa, /coa.json) alongside the live /war-room + /state + /events + POSTs, all
# under the one token. The read-only tabs never touch the engine.
_sh_repo = tempfile.mkdtemp(); os.makedirs(os.path.join(_sh_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_sh_repo, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "sh1", "title": "ShellJob", "type": "test", "defcon": 3, "value": 5}], _f)
_sh_eng = Engine([_sh_repo], execute=lambda *a: ("pass", None, "ok"),
                 load_state=lambda: _STATE, now=lambda: 1)
_sh_eng.stop()
_sh_httpd, _sh_port = make_server(_sh_eng, "sh-tok", shell_repos=[_sh_repo])
import threading as _shth  # noqa: E402
_shth.Thread(target=_sh_httpd.serve_forever, daemon=True).start()
def _shget(path, tok="sh-tok"):
    c = http.client.HTTPConnection("127.0.0.1", _sh_port, timeout=3)
    q = (f"?t={tok}" if tok is not None else "")
    c.request("GET", path + q); r = c.getresponse(); b = r.read(); c.close(); return r.status, b

_s, _b = _shget("/")
check("shell mode: GET / serves the big-tab frame with all three tabs",
      _s == 200 and b'data-tab="sitrep"' in _b and b'data-tab="coa"' in _b
      and b'data-tab="war-room"' in _b and b'id="panes"' in _b)
check("shell frame injects the token (no __SHELL_TOKEN__ placeholder leak)",
      b"__SHELL_TOKEN__" not in _b)
check("shell mode: GET /war-room serves the live cockpit", _shget("/war-room")[0] == 200)
_s, _b = _shget("/coa")
check("shell mode: GET /coa serves the read-only COA page", _s == 200 and len(_b) > 200)
_s, _b = _shget("/coa.json")
check("shell mode: GET /coa.json returns fresh COA json (the tab's Refresh fetch)",
      _s == 200 and isinstance(json.loads(_b), dict))
check("shell mode: GET /sitrep serves the sitrep tab", _shget("/sitrep")[0] == 200)
check("shell mode: every route is token-guarded (no token -> 403)", _shget("/", tok=None)[0] == 403)
check("shell mode: the engine routes (/state) are still served alongside the tabs",
      _shget("/state")[0] == 200)
_sh_httpd.shutdown()

# standalone cockpit mode is unchanged: no shell_repos -> GET / is still the cockpit itself
_st_eng = Engine([_sh_repo], execute=lambda *a: ("pass", None, "ok"),
                 load_state=lambda: _STATE, now=lambda: 1)
_st_httpd, _st_port = make_server(_st_eng, "st-tok")   # no shell_repos -> legacy cockpit at /
_shth.Thread(target=_st_httpd.serve_forever, daemon=True).start()
_c = http.client.HTTPConnection("127.0.0.1", _st_port, timeout=3)
_c.request("GET", "/?t=st-tok"); _r = _c.getresponse(); _sb = _r.read(); _c.close()
check("standalone (no shell_repos): GET / is still the cockpit, not the shell frame",
      _r.status == 200 and b'data-tab="war-room"' not in _sb)
_st_httpd.shutdown()

# render_shell fills the frame and never leaks the placeholder
_frame = _shell.render_shell("frame-tok").decode("utf-8")
check("render_shell substitutes the token and embeds it",
      "__SHELL_TOKEN__" not in _frame and "frame-tok" in _frame
      and _frame.lstrip().lower().startswith("<!doctype html"))

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
