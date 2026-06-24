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

from . import coa_io
from . import runner
from . import state as st


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
        self._trackers = {}                        # repo -> EnvelopeTracker
        self._results = {}                         # repo -> RunResult (accumulating)

    # ---- public mutations (called by HTTP handlers) ----
    def queue(self, repo, job_id):
        # promote a proposed job into the queue by id
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            coa_io.enqueue(repo, [jobs[job_id]])
        self._broadcast()
        self.advance(repo)

    def unqueue(self, repo, job_id):
        coa_io.unqueue(repo, job_id)
        self._broadcast()

    def reorder(self, repo, ids):
        coa_io.reorder(repo, ids)
        self._broadcast()

    def run(self, repo):
        self.advance(repo)

    def stop(self):
        with self._lock:
            self._stop = True

    # ---- state ----
    def state_json(self):
        with self._lock:
            running = dict(self._running) if self._running else None
            busy = self._busy
        return {"repos": [coa_io.board_state(r) for r in self.repos],
                "running": running, "busy": busy}

    # ---- the event-driven step ----
    def advance(self, repo):
        repo = os.path.realpath(os.path.expanduser(repo))
        while True:
            # one-at-a-time guard + stop check, atomically
            with self._lock:
                if self._busy or self._stop:
                    return
                roe = coa_io.load_roe(repo)
                tracker = self._trackers.get(repo)
                if tracker is None:
                    tracker = runner.EnvelopeTracker(roe)
                    self._trackers[repo] = tracker
                avail = tracker.available(self._load_state(), self._now())
                if avail is None:
                    return                              # stale/absent snapshot -> refuse
                job = runner.pick_next(coa_io.read_queue(repo), avail, roe)
                if job is None:
                    return                              # idle: nothing eligible/affordable
                self._busy = True
                self._running = {"repo": repo, "id": job.id}
                coa_io.unqueue(repo, job.id)            # remove-on-pick: can never run twice
                rr = self._results.get(repo)
                if rr is None:
                    rr = runner.RunResult(
                        generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                        state="running", repo=repo, verdict="unknown", note="",
                        available_windows=avail, spent_estimated=0.0)
                    self._results[repo] = rr
                seq = len(rr.jobs) + 1
            self._broadcast()

            # execute OUTSIDE the lock (long-running, sandboxed)
            oc = runner.run_one(repo, job, roe, repo, seq, execute=self._execute)

            with self._lock:
                tracker.charge(job.est_windows)
                rr.jobs.append(oc)
                rr.spent_estimated = tracker.spent
                self._persist(repo, rr)
                self._busy = False
                self._running = None
                stopped = self._stop
            self._broadcast()

            if stopped:
                return
            # loop to the next card (chain) — O(1) stack

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


def _default_render(token, state):
    # Minimal page; Task 7 replaces this with the cockpit template renderer.
    return ("<!doctype html><meta charset=utf-8><title>COA Cockpit</title>"
            "<body>cockpit (token ok)</body>").encode("utf-8")


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
    render = render or _default_render
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
            from urllib.parse import urlparse, parse_qs
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
