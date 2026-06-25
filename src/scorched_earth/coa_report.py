"""Render a COA result to Markdown (the record) and HTML (the presentation), both from the same
COA object so they never disagree. The Markdown is plain and self-contained. The HTML fills the
bundled war-HUD template (coa_template.html) by injecting one JSON data blob, the same way
report.py drives the sitrep. The caller passes a preformatted date string."""

from __future__ import annotations

import json
import os

from .advisor import COA

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "coa_template.html")

# Bucket the scan agent's numeric `value` into the labels the template colour-codes by.
_VALUE_LABELS = ((9.0, "CRITICAL"), (7.0, "HIGH"), (4.0, "MEDIUM"))


def _value_label(value: float) -> str:
    for threshold, label in _VALUE_LABELS:
        if value >= threshold:
            return label
    return "LOW"


def _row(j):
    return (j.id, j.tier, f"{j.est_windows:.1f}", f"{j.value:g}", j.type, j.title)


def render_md(coa: COA, generated_at: str) -> str:
    lines = [f"# Course of Action — {generated_at}", "", coa.note, "",
             "## Queue", "", "| id | tier | windows | value | type | title |",
             "|----|------|---------|-------|------|-------|"]
    for j in coa.queue:
        lines.append("| " + " | ".join(_row(j)) + " |")
    if not coa.queue:
        lines.append("| _(none)_ | | | | | |")
    lines += ["", "## Launch", ""]
    for j in coa.queue:
        lines += [f"### {j.id} — {j.title}", "", f"> {j.rationale}", "", "```", j.launch, "```", ""]
    if coa.skipped:
        lines += ["## Left on the table", ""]
        for j in coa.skipped:
            lines.append(f"- {j.id} ({j.tier}, {j.est_windows:.1f}w): {j.title}")
    return "\n".join(lines) + "\n"


def _job_obj(j) -> dict:
    """Map our Job onto the template's job shape. Values stay raw strings; the template's own
    `esc()` escapes them at render, so we must not double-escape here."""
    return {
        "title": j.title,
        "tier": j.tier,
        "type": (j.type or "").upper(),
        "cost": f"{j.est_windows:.1f} win",
        "value": _value_label(j.value),
        "depth": j.depth,
        "rationale": j.rationale,
        "command": j.launch,
    }


def render_html(coa: COA, generated_at: str, *, verdict: str = "unknown",
                roe_lines=None, reset_in: str = "") -> str:
    """Fill the war-HUD COA template with this plan. `verdict` (green|amber|off|unknown) drives
    the accent, `roe_lines` is the human-readable rules of engagement, `reset_in` is a display
    string for time-to-reset. All optional so the renderer works standalone (e.g. in tests); the
    CLI passes the live verdict, ROE, and reset from the snapshot."""
    data = {
        "sector": "SECTOR 07",
        "date": generated_at,
        "verdict": (verdict or "unknown").lower(),
        "note": coa.note,
        "envelope": {
            "available": round(coa.envelope_windows, 1),
            "spent": round(coa.spent_windows, 1),
            "unit": "WINDOWS",
            "resetIn": reset_in,
        },
        "roe": list(roe_lines or []),
        "queue": [_job_obj(j) for j in coa.queue],
        "skipped": [dict(_job_obj(j), note="Did not fit the budget or the rules of engagement.")
                    for j in coa.skipped],
    }
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    return template.replace("__COA_JSON__", json.dumps(data))
