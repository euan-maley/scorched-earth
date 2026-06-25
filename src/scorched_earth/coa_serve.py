"""The COA live cockpit: a localhost server hosting an event-driven engine that drives the
Phase 2a runner. The Engine holds shared board state behind a lock and runs an `advance`
step (no background loop) on a worker thread; HTTP/SSE wiring is added in Task 6. I/O tier;
never imported by the statusline hot path."""

from __future__ import annotations

import json
import os
import queue as _queue
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from . import coa_io
from . import runner
from . import state as st
from .roe import DEFAULT_ROE


class Engine:
    """Event-driven cockpit engine. `advance` runs ONE eligible affordable job and chains on
    completion. Re-entrancy is blocked by a global BUSY flag (one job at a time across all
    repos, since budget is one pool). Terminates by default: empty/over-budget/ROE-blocked
    queue or stop -> idle. A crashing job is recorded fail, dropped, and the chain continues."""

    def __init__(self, repos, *, execute=None, broadcast=None, load_state=None, now=None):
        self.repos = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        self._execute = execute or runner.execute_job
        self._broadcast = broadcast or (lambda: None)
        self._load_state = load_state or st.load_state
        self._now = now or (lambda: int(time.time()))
        self._lock = threading.Lock()
        self._busy = False
        self._stop = False
        self._running = None                       # {"repo","id"} or None
        self._kill_event = None                    # threading.Event or None (when idle)
        self._tracker = None                       # one global EnvelopeTracker (budget is one pool)
        self._active = []                          # repos armed for the current run
        self._results = {}                         # repo -> RunResult (accumulating)

    # ---- public mutations (called by HTTP handlers) ----
    def queue(self, repo, job_id):
        # promote a proposed job into the queue by id. The queue.json read-modify-write
        # runs under the lock so concurrent /queue|/unqueue|/reorder POSTs (and advance's
        # own unqueue) can't race and lose updates. Lock is released before advance (the
        # lock is non-reentrant and advance re-acquires it).
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            with self._lock:
                coa_io.enqueue(repo, [jobs[job_id]])
        rp = os.path.realpath(os.path.expanduser(repo))
        with self._lock:
            if rp not in self._active:
                self._active = self._active + [rp]   # a dragged-in card joins the active run
        self._broadcast()
        self.advance()

    def unqueue(self, repo, job_id):
        with self._lock:
            coa_io.unqueue(repo, job_id)
        self._broadcast()

    def reorder(self, repo, ids):
        with self._lock:
            coa_io.reorder(repo, ids)
        self._broadcast()

    def run(self, repos):
        if isinstance(repos, str):
            repos = [repos]
        active = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        with self._lock:
            self._active = active
            self._stop = False                     # Run = go/resume
        self.advance()

    def stop(self):
        with self._lock:
            self._stop = True

    def kill(self, repo, job_id):
        target = os.path.realpath(os.path.expanduser(repo))
        with self._lock:
            if (self._running and self._running == {"repo": target, "id": job_id}
                    and self._kill_event is not None):
                self._kill_event.set()

    # ---- state ----
    def state_json(self):
        with self._lock:
            running = dict(self._running) if self._running else None
            busy = self._busy
        return {"repos": [coa_io.board_state(r) for r in self.repos],
                "running": running, "busy": busy}

    # ---- the event-driven step ----
    def advance(self):
        while True:
            with self._lock:
                if self._busy or self._stop:
                    return
                if self._tracker is None:
                    self._tracker = runner.EnvelopeTracker(DEFAULT_ROE)  # global budget, no per-repo cap
                avail = self._tracker.available(self._load_state(), self._now())
                if avail is None:
                    return                          # stale/absent snapshot -> refuse the run
                picked = None
                for rp in self._active:             # first active repo (in order) with eligible work
                    roe = coa_io.load_roe(rp)
                    job = runner.pick_next(coa_io.read_queue(rp), avail, roe)
                    if job is not None:
                        picked = (rp, roe, job)
                        break
                if picked is None:
                    return                          # idle: nothing eligible/affordable anywhere
                rp, roe, job = picked
                self._busy = True
                self._running = {"repo": rp, "id": job.id}
                self._kill_event = threading.Event()
                kill_event = self._kill_event
                coa_io.unqueue(rp, job.id)          # remove-on-pick
                rr = self._results.get(rp)
                if rr is None:
                    rr = runner.RunResult(
                        generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                        state="running", repo=rp, verdict="unknown", note="",
                        available_windows=avail, spent_estimated=0.0)
                    self._results[rp] = rr
                seq = len(rr.jobs) + 1
            self._broadcast()

            runner._kill_ctx.event = kill_event
            try:
                oc = runner.run_one(rp, job, roe, rp, seq, execute=self._execute)
            finally:
                runner._kill_ctx.event = None

            with self._lock:
                if oc.outcome in ("pass", "fail"):
                    self._tracker.charge(job.est_windows)           # global budget
                    rr.jobs.append(oc)
                    rr.spent_estimated = rr.spent_estimated + job.est_windows   # this repo's own spend
                    self._persist(rp, rr)
                self._kill_event = None
                self._busy = False
                self._running = None
                stopped = self._stop
            self._broadcast()

            if stopped:
                return

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


def make_server(engine, token, *, render=None):
    """Build a ThreadingHTTPServer bound to 127.0.0.1 on an ephemeral port.

    Enforces *token* on every request (query ``?t=`` for GET,
    ``X-Scorch-Token`` header for POST; wrong/absent → 403).

    Routes:
      GET /          → cockpit HTML
      GET /state     → engine.state_json() as JSON
      GET /events    → SSE stream (event: board)
      POST /queue    → engine.queue(repo, id)   [worker thread]
      POST /unqueue  → engine.unqueue(repo, id)
      POST /reorder  → engine.reorder(repo, ids)
      POST /run      → engine.run(repo)          [worker thread]
      POST /stop     → engine.stop()

    SECURITY: POST handler reads job-ids ONLY from the body.  Any ``cmd`` or
    ``launch`` field in the body is never read or executed.

    Returns ``(httpd, port)``.  Does NOT call ``serve_forever``; the caller
    controls the event loop.
    """
    if not token:
        raise ValueError("token required")
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
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if self._tok_q() != token:
                self._send(403, b'{"error":"forbidden"}')
                return
            if path == "/":
                self._send(200, render(token, engine.state_json()),
                           "text/html; charset=utf-8")
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
            if path in ("/queue", "/unqueue", "/reorder", "/run", "/kill"):
                if os.path.realpath(os.path.expanduser(repo or "")) not in engine.repos:
                    self._send(400, b'{"error":"unknown repo"}'); return
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
                        args=(repo,),
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
