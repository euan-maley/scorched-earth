"""The unified War Room shell: one big-tab frame (SITREP / COURSE OF ACTION / WAR ROOM) served
by a single 127.0.0.1 token-guarded server. Each tab is an iframe backed by an existing renderer,
unchanged: the served sitrep (report.render_html), the read-only COA (coa_view), and the live
cockpit (coa_serve). The server itself is coa_serve.make_server run in shell mode; this module only
fills the frame template and renders the served sitrep tab. I/O tier; never on the statusline hot
path."""

from __future__ import annotations

import json
import os
import time

_SHELL_TEMPLATE = os.path.join(os.path.dirname(__file__), "shell_template.html")


def render_shell(token: str) -> bytes:
    """The shell frame HTML, with the token injected for the iframe srcs."""
    with open(_SHELL_TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    return html.replace("__SHELL_TOKEN__", json.dumps(token)).encode("utf-8")


def render_sitrep() -> bytes:
    """The SITREP tab body: the same HUD `scorch --sitrep` writes, rendered live off the latest
    snapshot. Refreshes R from the calibration samples (mirrors the CLI) so the field is current.
    Falls back to a small placeholder before any real budget reading exists, never a HUD full of
    fabricated 0%s."""
    from . import calibrate, report
    from . import state as st
    state = st.load_state()
    snap = (state or {}).get("snapshot") or {}
    if snap.get("seven_day_pct") is None:
        return _placeholder("No live budget reading yet. Open a Claude Code session to capture "
                            "a snapshot, then refresh.")
    r_fresh, prov_fresh = calibrate.estimate_r(st.load_calibration().get("samples", []))
    if isinstance(state.get("recommendation"), dict):
        state["recommendation"]["r"] = r_fresh
        state["recommendation"]["r_provisional"] = prov_fresh
    return report.render_html(state, st.load_history(), int(time.time())).encode("utf-8")


def _placeholder(msg: str) -> bytes:
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='margin:0;background:#0b0705;color:#86abab;"
        "font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:1px;"
        "display:flex;align-items:center;justify-content:center;height:100vh;"
        "text-align:center;padding:24px'>"
        f"<div>{msg}</div></body>"
    ).encode("utf-8")
