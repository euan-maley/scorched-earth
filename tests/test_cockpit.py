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

# --- Task 5: Engine (event-driven advance) ----------------------------------------
from scorched_earth.coa_serve import Engine  # noqa: E402

def _mk_repo(jobs):
    r = tempfile.mkdtemp()
    os.makedirs(os.path.join(r, ".scorched"), exist_ok=True)
    with open(os.path.join(r, ".scorched", "jobs.json"), "w") as f:
        json.dump([{"id": j.id, "title": j.title, "type": j.type,
                    "est_windows": j.est_windows, "value": j.value} for j in jobs], f)
    _io.write_queue(r, jobs)
    return r

_ran = []
def _exec(repo, job, roe):
    _ran.append(job.id)
    return ("pass", {"files": 1, "insertions": 3, "deletions": 0}, "ok")
_STATE = {"snapshot": {"now": 1, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
          "recommendation": {"windows_left": 2.5, "level": "green"}}
_r = _mk_repo([Job(id="t1", repo=".", title="T1", type="test", est_windows=1.0, value=5),
               Job(id="r1", repo=".", title="R1", type="refactor", est_windows=0.2, value=9),  # ROE block
               Job(id="t2", repo=".", title="T2", type="test", est_windows=1.0, value=4),
               Job(id="t3", repo=".", title="T3", type="test", est_windows=1.0, value=3)])  # over budget
_beats = []
_eng = Engine([_r], execute=_exec, broadcast=lambda: _beats.append(1),
              load_state=lambda: _STATE, now=lambda: 1)
_eng.run(_r)
check("engine drains the affordable additive cards in order", _ran == ["t1", "t2"])
check("engine skips the ROE-blocked card (refactor never ran)", "r1" not in _ran)
check("engine stops when the next card is over budget (t3 left queued)",
      [j.id for j in _io.read_queue(_r)] == ["r1", "t3"])
check("engine broadcast fired across the run", len(_beats) >= 4)
check("engine not busy after draining", _eng.state_json()["busy"] is False)

# crash containment + no-retry
_ran2 = []
def _boom(repo, job, roe):
    _ran2.append(job.id)
    if job.id == "x1":
        raise RuntimeError("died")
    return ("pass", None, "ok")
_r2 = _mk_repo([Job(id="x1", repo=".", title="X1", type="test", est_windows=0.5, value=5),
                Job(id="x2", repo=".", title="X2", type="test", est_windows=0.5, value=4)])
_eng2 = Engine([_r2], execute=_boom, load_state=lambda: _STATE, now=lambda: 1)
_eng2.run(_r2)
check("engine: a crashing job is dropped (not retried) and the chain continues",
      _ran2 == ["x1", "x2"] and _io.read_queue(_r2) == [])

# stop halts the chain
_ran3 = []
def _exec_stop(repo, job, roe):
    _ran3.append(job.id)
    _eng3.stop()                     # request stop after the first job
    return ("pass", None, "ok")
_r3 = _mk_repo([Job(id="s1", repo=".", title="S1", type="test", est_windows=0.5, value=5),
                Job(id="s2", repo=".", title="S2", type="test", est_windows=0.5, value=4)])
_eng3 = Engine([_r3], execute=_exec_stop, load_state=lambda: _STATE, now=lambda: 1)
_eng3.run(_r3)
check("engine: stop halts the chain after the current job", _ran3 == ["s1"])

# busy guard under real concurrency: a second run() while a job is in flight must no-op
import threading as _th
_run_evt = _th.Event(); _gate = _th.Event(); _cstarted = []
def _blocking_exec(repo, job, roe):
    _cstarted.append(job.id)
    if job.id == "c1":
        _run_evt.set()
        _gate.wait(2)
    return ("pass", None, "ok")
_rc = _mk_repo([Job(id="c1", repo=".", title="C1", type="test", est_windows=0.5, value=5),
                Job(id="c2", repo=".", title="C2", type="test", est_windows=0.5, value=4)])
_engc = Engine([_rc], execute=_blocking_exec, load_state=lambda: _STATE, now=lambda: 1)
_t1 = _th.Thread(target=_engc.run, args=(_rc,), daemon=True); _t1.start()
_run_evt.wait(2)                          # c1 is now executing (busy=True, lock free)
_engc.run(_rc)                            # concurrent second run() must no-op (busy guard)
check("engine busy guard: a concurrent run() no-ops while a job is in flight",
      _cstarted == ["c1"] and _engc.state_json()["busy"] is True)
_gate.set()                               # release c1; the loop then drains c2
_t1.join(3)
check("engine busy guard: after release the chain drains the rest and goes idle",
      sorted(_cstarted) == ["c1", "c2"] and _engc.state_json()["busy"] is False
      and _io.read_queue(_rc) == [])

# Run clears a prior Stop (Stop is a pause, not a permanent kill)
_ran_sr = []
def _exec_sr(repo, job, roe):
    _ran_sr.append(job.id); return ("pass", None, "ok")
_rs = _mk_repo([Job(id="p1", repo=".", title="P1", type="test", est_windows=0.5, value=5),
                Job(id="p2", repo=".", title="P2", type="test", est_windows=0.5, value=4)])
_engsr = Engine([_rs], execute=_exec_sr, load_state=lambda: _STATE, now=lambda: 1)
_engsr.stop()                         # pre-stopped
_engsr.run(_rs)                        # Run must clear the stop flag and drain
check("engine: Run resumes after a prior Stop (clears the stop flag)",
      sorted(_ran_sr) == ["p1", "p2"] and _io.read_queue(_rs) == []
      and _engsr.state_json()["busy"] is False)

# --- Task 6: HTTP server (token, routing, SSE) ------------------------------------
import http.client  # noqa: E402
import threading as _threading  # noqa: E402
from scorched_earth.coa_serve import make_server  # noqa: E402

_r6 = _mk_repo([Job(id="g1", repo=".", title="G1", type="test", est_windows=1.0, value=5)])
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
_io.write_queue(_r6, [Job(id="g1", repo=".", title="G1", type="test", est_windows=1.0, value=5)])
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
_rk = _mk_repo([Job(id="kill-me", repo=".", title="Kill me", type="test", est_windows=1.0, value=5),
                Job(id="next-up", repo=".", title="Next", type="test", est_windows=0.5, value=4)])
_engk = Engine([_rk], execute=_exec_killable, load_state=lambda: _STATE, now=lambda: 1)
_tk = _k2th.Thread(target=_engk.run, args=(_rk,), daemon=True); _tk.start()
_k2_started.wait(3)                                  # kill-me is now "running"
_engk.kill(_rk, "kill-me")                           # operator kills it
_tk.join(5)
_fin = [j["id"] for j in _io.board_state(_rk)["finished"]]
_prop = [j["id"] for j in _io.board_state(_rk)["proposed"]]
check("engine.kill ends the running job (not left busy)", _engk.state_json()["busy"] is False)
check("killed job is NOT in finished (pass/fail only)", "kill-me" not in _fin)
check("killed job returns to proposed (re-queueable)", "kill-me" in _prop)
check("after a kill the chain continues to the next job (next-up ran)", "next-up" in _fin)

# /kill: token-guarded, repo-validated, job-ids only
_rkill = _mk_repo([Job(id="z", repo=".", title="Z", type="test", est_windows=1.0, value=5)])
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
    json.dump([{"id": "s1", "title": "S1", "type": "test", "est_windows": 0.5, "value": 5},
               {"id": "s2", "title": "S2", "type": "test", "est_windows": 0.5, "value": 4}], _f)
_ran_p = []
_engp = Engine([_rp], execute=lambda repo, job, roe: (_ran_p.append(job.id), ("pass", None, "ok"))[1],
               load_state=lambda: _STATE, now=lambda: 1)
_engp.stop()                          # cockpit starts paused (as bin/scorch --serve does)
_engp.queue(_rp, "s1"); _engp.queue(_rp, "s2")     # drag cards in while paused
check("paused cockpit: dragging cards in stages them without running",
      _ran_p == [] and [j.id for j in _io.read_queue(_rp)] == ["s1", "s2"])
_engp.run(_rp)                        # press Run
check("paused cockpit: Run then drains the staged queue in order",
      _ran_p == ["s1", "s2"] and _io.read_queue(_rp) == [])

# --- board_state job briefs carry depth ------------------------------------------
_rb2 = tempfile.mkdtemp(); os.makedirs(os.path.join(_rb2, ".scorched"), exist_ok=True)
with open(os.path.join(_rb2, ".scorched", "jobs.json"), "w") as _f:
    json.dump([{"id": "g", "title": "G", "type": "test", "depth": 9, "value": 6}], _f)
check("board_state brief carries depth", _io.board_state(_rb2)["proposed"][0]["depth"] == 9)

print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
