"""Served, read-only COA report: a tiny 127.0.0.1 HTTP server that hosts the tabbed DEFCON battle
plan and a /coa.json refresh endpoint. The page's Refresh button re-fetches /coa.json, which
RE-READS each repo's jobs.json + ROE and re-runs the pure matcher — it never re-scans the repos.
Token-guarded on every request (the token lives in the URL, like the War Room cockpit). I/O tier;
never on the statusline hot path."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

from . import advisor, coa_io, coa_report
from . import state as st


def _fmt_dur(secs: int) -> str:
    secs = int(secs)
    if secs <= 0:
        return "now"
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"


def _live(repos):
    """(repo_coas, global_kwargs) by re-reading jobs.json + ROE per repo and the latest snapshot.
    Pure read — no repo scan, no writes."""
    state = st.load_state() or {}
    snap = state.get("snapshot") or {}
    rec = state.get("recommendation") or {}
    wr = snap.get("seven_day_reset")
    reset_in = _fmt_dur(wr - snap.get("now", int(time.time()))) if wr else ""
    repo_coas = [(r, advisor.match(coa_io.load_jobs(r), coa_io.load_roe(r))) for r in repos]
    kw = {
        "verdict": rec.get("level", "unknown"),
        "weekly_reserve_pct": advisor.weekly_reserve_pct(snap) or 0.0,
        "reset_in": reset_in,
    }
    return repo_coas, kw


def coa_state(repos) -> dict:
    """Fresh COA data blob (what /coa.json returns)."""
    repo_coas, kw = _live(repos)
    return coa_report.build_data(repo_coas, time.strftime("%Y-%m-%d", time.localtime()),
                                 verdict=kw["verdict"], reset_in=kw["reset_in"],
                                 weekly_reserve_pct=kw["weekly_reserve_pct"])


def render_page(token: str, repos) -> bytes:
    """The served HTML, with the Refresh button armed (token embedded)."""
    repo_coas, kw = _live(repos)
    html = coa_report.render_html(None, time.strftime("%Y-%m-%d", time.localtime()),
                                  repos=repo_coas, token=token, **kw)
    return html.encode("utf-8")


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(repos, token, *, host="127.0.0.1", port=0):
    """A token-guarded, read-only COA server. Routes (token required on every request as ?t=):
        GET /            -> the tabbed COA page
        GET /coa.json    -> fresh coa_state() as JSON (the Refresh fetch)
    Returns (httpd, port). Bind to 127.0.0.1 only."""
    if not token:
        raise ValueError("token required")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _tok(self):
            return (parse_qs(urlparse(self.path).query).get("t") or [""])[0]

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if self._tok() != token:
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            if path == "/":
                self._send(200, render_page(token, repos))
            elif path == "/coa.json":
                self._send(200, json.dumps(coa_state(repos)).encode("utf-8"),
                           "application/json; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

    httpd = _ThreadingHTTPServer((host, port), Handler)
    return httpd, httpd.server_address[1]
