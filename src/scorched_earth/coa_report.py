"""Render a COA result to Markdown (the record) and HTML (the presentation), both from the same
COA object so they never disagree. The Markdown is plain and self-contained. The HTML fills the
bundled war-HUD template (coa_template.html) by injecting one JSON data blob, the same way
report.py drives the sitrep. The caller passes a preformatted date string."""

from __future__ import annotations

import json
import os

from .advisor import COA

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "coa_template.html")

_DEFCON_LABELS = {1: "DEFCON 1", 2: "DEFCON 2", 3: "DEFCON 3", 4: "DEFCON 4", 5: "DEFCON 5"}


def _row(j):
    return (j.id, _DEFCON_LABELS[j.defcon], f"{j.value:g}", j.type, j.title)


def render_md(coa: COA, generated_at: str) -> str:
    lines = [f"# Course of Action — {generated_at}", "", coa.note, "",
             "## Battle plan (most critical first)", "",
             "| id | defcon | value | type | title |",
             "|----|--------|-------|------|-------|"]
    for j in coa.queue:
        lines.append("| " + " | ".join(_row(j)) + " |")
    if not coa.queue:
        lines.append("| _(none)_ | | | | |")
    lines += ["", "## Launch", ""]
    for j in coa.queue:
        appr = "  **(approval required)**" if j.defcon < 3 else ""
        lines += [f"### {j.id} — {j.title} [{_DEFCON_LABELS[j.defcon]}]{appr}", "",
                  f"> {j.rationale}", "", "```", j.launch, "```", ""]
    if coa.blocked:
        lines += ["## Blocked by ROE", ""]
        for j in coa.blocked:
            lines.append(f"- {j.id} ({j.type}): {j.title}")
    return "\n".join(lines) + "\n"


def _job_obj(j) -> dict:
    return {
        "title": j.title,
        "defcon": j.defcon,
        "type": (j.type or "").upper(),
        "value": f"{j.value:g}",
        "approval_required": j.defcon < 3,
        "rationale": j.rationale,
        "command": j.launch,
    }


def render_html(coa: COA, generated_at: str, *, verdict: str = "unknown",
                roe_lines=None, reset_in: str = "",
                weekly_reserve_pct: float = 0.0) -> str:
    """Fill the war-HUD COA template with this plan. `verdict` (green|amber|off|unknown) drives
    the accent, `roe_lines` is the human-readable rules of engagement, `reset_in` is a display
    string for time-to-reset. All optional so the renderer works standalone (e.g. in tests); the
    CLI passes the live verdict, ROE, and reset from the snapshot."""
    data = {
        "sector": "SECTOR 07",
        "date": generated_at,
        "verdict": (verdict or "unknown").lower(),
        "note": coa.note,
        "weeklyReservePct": round(weekly_reserve_pct or 0.0, 0),
        "resetIn": reset_in,
        "roe": list(roe_lines or []),
        "queue": [_job_obj(j) for j in coa.queue],
        "blocked": [_job_obj(j) for j in coa.blocked],
    }
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    return template.replace("__COA_JSON__", json.dumps(data))
