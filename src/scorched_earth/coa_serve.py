"""The COA live cockpit: a localhost server hosting an event-driven engine that drives the
Phase 2a runner. The Engine holds shared board state behind a lock and runs an `advance`
step (no background loop) on a worker thread; HTTP/SSE wiring is added in Task 6. I/O tier;
never imported by the statusline hot path."""

from __future__ import annotations

import json
import os
import queue as _queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from . import coa_io
from . import runner
from . import state as st


class Engine:
    """Cockpit engine with parallel per-repo workers. Each armed repo gets its own drain worker
    thread that picks ungated (no budget envelope — the old EnvelopeTracker is retired). The run
    drains whatever is queued and halts ONLY on a real usage-limit (re-queueing the un-run job and
    stopping every worker) or an optional ROE cap. Terminates by default: empty/ROE-blocked queue,
    cap reached, or stop -> idle per repo. A crashing job is recorded fail, dropped, chain continues."""

    def __init__(self, repos, *, execute=None, broadcast=None, load_state=None, now=None):
        self.repos = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        self._execute = execute or runner.execute_job
        self._broadcast = broadcast or (lambda: None)
        self._load_state = load_state or st.load_state
        self._now = now or (lambda: int(time.time()))
        self._lock = threading.Lock()
        self._stop = False
        self._stop_reason = None                   # None | "operator" | "limit": why the drain halted
        self._running = {}                         # repo -> {"repo","id"} (one in-flight job per repo)
        self._kill_events = {}                     # repo -> threading.Event
        self._workers = set()                      # repos with a live drain worker
        self._results = {}                         # repo -> RunResult
        self._progress = {}                        # repo -> {"line","started","ts"} (live per-job)
        self._last_prog_bcast = 0.0                # throttle the progress SSE push

    # ---- public mutations (called by HTTP handlers) ----
    def _ensure_worker(self, repo):
        """Register a worker for repo if none is live and we're not stopped. Returns True if the
        CALLER should spawn the thread (registration happened here)."""
        with self._lock:
            if self._stop or repo in self._workers:
                return False
            self._workers.add(repo)
            return True

    def run(self, repos):
        if isinstance(repos, str):
            repos = [repos]
        repos = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        with self._lock:
            self._stop = False
            self._stop_reason = None                # Run resumes: clear the prior halt reason
        for rp in repos:
            if self._ensure_worker(rp):
                threading.Thread(target=self._drain_repo, args=(rp,), daemon=True).start()

    def queue(self, repo, job_id):
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            with self._lock:
                coa_io.enqueue(repo, [jobs[job_id]])
        rp = os.path.realpath(os.path.expanduser(repo))
        self._broadcast()
        if self._ensure_worker(rp):                # a dragged-in card starts/continues this repo's worker
            threading.Thread(target=self._drain_repo, args=(rp,), daemon=True).start()

    def unqueue(self, repo, job_id):
        with self._lock:
            coa_io.unqueue(repo, job_id)
        self._broadcast()

    def reorder(self, repo, ids):
        with self._lock:
            coa_io.reorder(repo, ids)
        self._broadcast()

    def stop(self):
        with self._lock:
            self._stop = True                      # halts every worker after its current job
            self._stop_reason = "operator"

    def kill(self, repo, job_id):
        target = os.path.realpath(os.path.expanduser(repo))
        with self._lock:
            r = self._running.get(target)
            ke = self._kill_events.get(target)
            if r and r.get("id") == job_id and ke is not None:
                ke.set()

    # ---- state ----
    def state_json(self):
        from . import advisor
        state = self._load_state()
        snap = (state or {}).get("snapshot") or {}
        wrp = advisor.weekly_reserve_pct(snap)
        now = self._now()
        with self._lock:
            running = [dict(v) for v in self._running.values()]
            for r in running:                      # attach the live progress line + elapsed
                p = self._progress.get(r["repo"])
                if p:
                    r["progress"] = {"line": p["line"],
                                     "elapsed": max(0, now - p["started"])}
            busy = bool(running) or bool(self._workers)
            stopped, stop_reason = self._stop, self._stop_reason
            running_by_repo = {}
            for v in self._running.values():
                running_by_repo.setdefault(v["repo"], []).append(v["id"])
        repos = [coa_io.board_state(r, running_by_repo.get(r, ())) for r in self.repos]
        return {"repos": repos, "running": running, "busy": busy,
                "stopped": stopped, "stop_reason": stop_reason,
                "weekly_reserve_pct": round(wrp, 0) if wrp is not None else None}

    # ---- per-repo drain worker ----
    def _drain_repo(self, repo):
        while True:
            with self._lock:
                if self._stop:
                    self._workers.discard(repo)
                    done = True
                else:
                    roe = coa_io.load_roe(repo)
                    rr = self._results.get(repo)
                    done_n = len(rr.jobs) if rr else 0
                    capped = roe.max_jobs is not None and done_n >= roe.max_jobs
                    job = None if capped else runner.pick_next(
                        coa_io.read_queue(repo), roe, approved=True)
                    if job is None:
                        self._workers.discard(repo)                            # this repo: nothing to do
                        done = True
                    else:
                        done = False
                        self._running[repo] = {"repo": repo, "id": job.id}
                        self._progress[repo] = {"line": "starting", "started": self._now(),
                                                "ts": self._now()}
                        ke = threading.Event()
                        self._kill_events[repo] = ke
                        coa_io.unqueue(repo, job.id)
                        if rr is None:
                            rr = runner.RunResult(
                                generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                                state="running", repo=repo, verdict="unknown", note="")
                            self._results[repo] = rr
                        seq = len(rr.jobs) + 1
            self._broadcast()
            if done:
                return

            runner._kill_ctx.event = ke              # per-worker-thread kill handle (thread-local)
            runner._kill_ctx.progress = lambda line, _r=repo: self._on_progress(_r, line)
            try:
                oc = runner.run_one(repo, job, roe, repo, seq, execute=self._execute)
            finally:
                runner._kill_ctx.event = None
                runner._kill_ctx.progress = None

            with self._lock:
                self._progress.pop(repo, None)       # job finished: clear its live progress
                if oc.outcome == "limit":
                    coa_io.enqueue(repo, [job])          # didn't run — put it back, resumable
                    self._stop = True                    # halt every worker
                    self._stop_reason = "limit"          # hit the real weekly ceiling
                elif oc.outcome in ("pass", "fail", "roadblocked"):
                    if oc.outcome == "roadblocked":
                        runner.handle_roadblock(repo, oc)    # report + notify; drain continues
                    else:
                        runner.write_job_deliverable(repo, oc)   # per-job deliverable record
                    rr.jobs.append(oc)
                    self._persist(repo, rr)          # killed: not appended (board -> proposed)
                self._running.pop(repo, None)
                self._kill_events.pop(repo, None)
                if self._stop:
                    self._workers.discard(repo)
                    done = True
            self._broadcast()
            if done:
                return
            # loop: drain the next job in THIS repo

    def _on_progress(self, repo, line):
        """Per-output-line progress sink (called on the worker thread by the runner). Stores the
        latest activity for the live view and pushes it over SSE, throttled to at most ~1/2s so a
        chatty stream never floods the clients."""
        summary = runner.summarize_stream_line(line)
        if not summary:
            return
        now = self._now()
        with self._lock:
            p = self._progress.get(repo)
            if p is None:
                return
            p["line"] = summary
            p["ts"] = now
            if now - self._last_prog_bcast < 2:
                return
            self._last_prog_bcast = now
        self._broadcast()

    def _persist(self, repo, rr):
        from . import review_report
        rr.note = runner._summary(rr)
        coa_io.write_run_record(repo, runner._dataclass_dict(rr), rr.generated_at)
        with open(os.path.join(coa_io.runs_dir(repo), rr.generated_at + ".html"), "w") as f:
            f.write(review_report.render_review_html(rr))


# ---------------------------------------------------------------------------
# HTTP server: token, routing, SSE
# ---------------------------------------------------------------------------

class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


_COCKPIT_TEMPLATE = os.path.join(os.path.dirname(__file__), "cockpit_template.html")


def render_cockpit(token, state):
    with open(_COCKPIT_TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__COCKPIT_TOKEN__", json.dumps(token))
    html = html.replace("__COCKPIT_JSON__", json.dumps(state))
    return html.encode("utf-8")


# ---------------------------------------------------------------------------
# Shell-mode AFTER-ACTION tab: the latest run record, plus its artifact files
# ---------------------------------------------------------------------------

def _placeholder(msg):
    return ("<!doctype html><meta charset='utf-8'><body style='margin:0;background:#0b0705;"
            "color:#86abab;font-family:ui-monospace,Menlo,monospace;letter-spacing:1px;display:flex;"
            "align-items:center;justify-content:center;height:100vh;text-align:center;padding:24px'>"
            "<div>" + msg + "</div></body>").encode("utf-8")


def aar_page(shell_repos, token):
    """The AFTER-ACTION tab body: re-renders the most recent run record across the shell's repos,
    with the token armed so each job's OPEN links reach the artifact route. Placeholder if no run
    has happened yet."""
    from . import review_report
    best = None                                   # (mtime, repo, record)
    for r in shell_repos:
        d = coa_io.runs_dir(r)
        try:
            stamps = [f for f in os.listdir(d) if f.endswith(".json")]
        except OSError:
            continue
        if not stamps:
            continue
        latest = max(stamps)
        mt = os.path.getmtime(os.path.join(d, latest))
        if best is None or mt > best[0]:
            best = (mt, r, coa_io.read_run_record(r, latest[:-5]))
    if not best or not best[2]:
        return _placeholder("No run yet. Queue a job in the War Room, or run `scorch coa run`, "
                            "then the After-Action Report lands here.")
    _, repo, rec = best
    rr = review_report.rr_from_record(rec)
    real = os.path.realpath(os.path.expanduser(repo))
    return review_report.render_review_html(rr, token=token, repo=real).encode("utf-8")


_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def serve_artifact(shell_repos, qs):
    """GET /artifact?repo=&id=&kind=deliverable|roadblock -> the artifact .md, wrapped for reading.
    Repo must be one of the shell's repos and id must be a bare filename (no traversal)."""
    repo = (qs.get("repo") or [""])[0]
    jid = (qs.get("id") or [""])[0]
    kind = (qs.get("kind") or ["deliverable"])[0]
    allowed = {os.path.realpath(os.path.expanduser(r)) for r in shell_repos}
    ap = os.path.realpath(os.path.expanduser(repo))
    if ap not in allowed:
        return 400, b'{"error":"unknown repo"}', "application/json"
    if not _ID_RE.match(jid or ""):
        return 400, b'{"error":"bad id"}', "application/json"
    path = coa_io.roadblock_path(ap, jid) if kind == "roadblock" else coa_io.deliverable_path(ap, jid)
    if not os.path.isfile(path):
        return 404, b'{"error":"not found"}', "application/json"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = ("<!doctype html><meta charset='utf-8'><title>" + jid + "</title>"
            "<body style='margin:0;background:#0b0f12;color:#cfe0e0;"
            "font:13px/1.6 ui-monospace,Menlo,Consolas,monospace'>"
            "<pre style='padding:28px 34px;white-space:pre-wrap;word-break:break-word'>"
            + esc + "</pre></body>").encode("utf-8")
    return 200, body, "text/html; charset=utf-8"


def make_server(engine, token, *, render=None, shell_repos=None):
    """Build a ThreadingHTTPServer bound to 127.0.0.1 on an ephemeral port.

    Enforces *token* on every request (query ``?t=`` for GET,
    ``X-Scorch-Token`` header for POST; wrong/absent → 403).

    Routes (standalone cockpit mode):
      GET /          → cockpit HTML
      GET /state     → engine.state_json() as JSON
      GET /events    → SSE stream (event: board)
      POST /queue    → engine.queue(repo, id)   [worker thread]
      POST /unqueue  → engine.unqueue(repo, id)
      POST /reorder  → engine.reorder(repo, ids)
      POST /run      → engine.run(repo)          [worker thread]
      POST /stop     → engine.stop()

    When *shell_repos* is given, the server runs in SHELL mode: the big-tab frame moves to
    ``/`` and the cockpit to ``/war-room``, and the two read-only surfaces are served from the
    same origin so the shell's iframes work under one token:
      GET /          → the shell frame (SITREP / COURSE OF ACTION / WAR ROOM tabs)
      GET /war-room  → cockpit HTML
      GET /sitrep    → served sitrep (shell.render_sitrep)
      GET /coa       → read-only COA page (coa_view.render_page)
      GET /coa.json  → fresh coa_state (the COA tab's Refresh fetch)
    The engine/SSE/POST routes are unchanged; the read-only tabs never touch the engine.

    SECURITY: POST handler reads job-ids ONLY from the body.  Any ``cmd`` or
    ``launch`` field in the body is never read or executed.

    Returns ``(httpd, port)``.  Does NOT call ``serve_forever``; the caller
    controls the event loop.
    """
    if not token:
        raise ValueError("token required")
    shell_mode = shell_repos is not None
    render = render or render_cockpit
    clients = []                               # list[queue.Queue] for SSE subscribers
    clients_lock = threading.Lock()

    def _broadcast():
        snap = engine.state_json()
        with clients_lock:
            dead = []
            for q in clients:
                try:
                    q.put_nowait(snap)
                except Exception:              # noqa: BLE001
                    dead.append(q)
            for q in dead:
                clients.remove(q)

    engine._broadcast = _broadcast            # wire engine → SSE

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):            # silence default stderr logging
            pass

        def _tok_q(self):
            qs = parse_qs(urlparse(self.path).query)
            return (qs.get("t") or [None])[0]

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # Every response here is dynamic state; a cached copy is a stale tab (a reopened
            # shell iframe was observed painting an old page from the browser cache).
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/favicon.ico":
                # Browsers request this tokenless; answer 204 before the gate so it never
                # shows up as a 403 in the console (the shell's iframes multiply the noise).
                self._send(204, b"", "image/x-icon")
                return
            if self._tok_q() != token:
                self._send(403, b'{"error":"forbidden"}')
                return
            if path == "/":
                if shell_mode:
                    from . import shell
                    self._send(200, shell.render_shell(token), "text/html; charset=utf-8")
                else:
                    self._send(200, render(token, engine.state_json()),
                               "text/html; charset=utf-8")
            elif shell_mode and path == "/war-room":
                self._send(200, render(token, engine.state_json()),
                           "text/html; charset=utf-8")
            elif shell_mode and path == "/sitrep":
                from . import shell
                self._send(200, shell.render_sitrep(), "text/html; charset=utf-8")
            elif shell_mode and path == "/coa":
                from . import coa_view
                self._send(200, coa_view.render_page(token, shell_repos),
                           "text/html; charset=utf-8")
            elif shell_mode and path == "/coa.json":
                from . import coa_view
                self._send(200, json.dumps(coa_view.coa_state(shell_repos)).encode("utf-8"))
            elif shell_mode and path == "/aar":
                self._send(200, aar_page(shell_repos, token), "text/html; charset=utf-8")
            elif shell_mode and path == "/roe":
                from . import roe_view
                self._send(200, roe_view.render_page(token, shell_repos),
                           "text/html; charset=utf-8")
            elif shell_mode and path == "/roe.json":
                from . import roe_view
                self._send(200, json.dumps(roe_view.roe_state(shell_repos)).encode("utf-8"))
            elif shell_mode and path == "/artifact":
                qs = parse_qs(urlparse(self.path).query)
                code, body, ctype = serve_artifact(shell_repos, qs)
                self._send(code, body, ctype)
            elif path == "/state":
                self._send(200,
                           json.dumps(engine.state_json()).encode("utf-8"))
            elif path == "/events":
                self._sse()
            else:
                self._send(404, b'{"error":"not found"}')

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = _queue.Queue()
            with clients_lock:
                clients.append(q)
            try:
                # send current board immediately on connect
                self.wfile.write(
                    b"event: board\ndata: "
                    + json.dumps(engine.state_json()).encode("utf-8")
                    + b"\n\n")
                self.wfile.flush()
                while True:
                    snap = q.get()
                    self.wfile.write(
                        b"event: board\ndata: "
                        + json.dumps(snap).encode("utf-8")
                        + b"\n\n")
                    self.wfile.flush()
            except Exception:                  # noqa: BLE001 — client disconnected
                pass
            finally:
                with clients_lock:
                    if q in clients:
                        clients.remove(q)

        def do_POST(self):
            if self.headers.get("X-Scorch-Token") != token:
                self._send(403, b'{"error":"forbidden"}')
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, b'{"error":"bad json"}')
                return
            path = self.path.split("?", 1)[0]
            repo = body.get("repo")
            run_repos = None
            if path == "/run":
                run_repos = list(body.get("repos") or ([] if body.get("repo") is None else [body.get("repo")]))
                for _rp in run_repos:
                    if os.path.realpath(os.path.expanduser(_rp or "")) not in engine.repos:
                        self._send(400, b'{"error":"unknown repo"}'); return
            is_global_roe = path == "/roe" and body.get("scope") == "global"
            if path in ("/queue", "/unqueue", "/reorder", "/kill", "/roe") and not is_global_roe:
                if os.path.realpath(os.path.expanduser(repo or "")) not in engine.repos:
                    self._send(400, b'{"error":"unknown repo"}'); return
            if path == "/roe":
                # The editor write path: a mode flip ({repo, mode: global|specific}) or one
                # editor step ({index, direction}, repo-scoped or scope:"global"), applied by
                # the pure roe_edit reducer and saved server-side. Only shell mode serves the
                # editor page but the write path validates independently: allowlisted repo (or
                # the explicit global scope), int index, direction in -1/0/1.
                if not shell_mode:
                    self._send(404, b'{"error":"not found"}'); return
                from . import roe_view
                try:
                    mode = body.get("mode")
                    if mode is not None:
                        if is_global_roe or mode not in ("global", "specific"):
                            self._send(400, b'{"error":"bad mode"}'); return
                        fresh = roe_view.set_mode(repo, mode == "specific")
                    else:
                        idx, dirn = body.get("index"), body.get("direction")
                        if not isinstance(idx, int) or isinstance(idx, bool) or dirn not in (-1, 0, 1):
                            self._send(400, b'{"error":"bad step"}'); return
                        if is_global_roe:
                            fresh = roe_view.apply_step_global(idx, dirn)
                        else:
                            fresh = roe_view.apply_step(repo, idx, dirn)
                except Exception as e:             # noqa: BLE001
                    self._send(500, json.dumps({"error": str(e)}).encode("utf-8")); return
                self._send(200, json.dumps(fresh).encode("utf-8"))
                return
            # job-ids ONLY: any cmd/launch field in the body is never read.
            try:
                if path == "/queue":
                    threading.Thread(
                        target=engine.queue,
                        args=(repo, body.get("id")),
                        daemon=True).start()
                elif path == "/unqueue":
                    engine.unqueue(repo, body.get("id"))
                elif path == "/reorder":
                    engine.reorder(repo, list(body.get("ids") or []))
                elif path == "/run":
                    threading.Thread(
                        target=engine.run,
                        args=(run_repos,),
                        daemon=True).start()
                elif path == "/stop":
                    engine.stop()
                elif path == "/kill":
                    threading.Thread(
                        target=engine.kill,
                        args=(repo, body.get("id")),
                        daemon=True).start()
                else:
                    self._send(404, b'{"error":"not found"}')
                    return
            except Exception as e:             # noqa: BLE001
                self._send(500,
                           json.dumps({"error": str(e)}).encode("utf-8"))
                return
            self._send(200, b'{"ok":true}')

    httpd = _ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return httpd, httpd.server_address[1]
