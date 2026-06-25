"""Render a RunResult to Markdown (the record) and HTML (the live monitor + final debrief),
both from one structured source so they never disagree. The HTML fills the bundled
review_template.html by injecting one JSON blob (same pattern as coa_report.py / report.py).
While the run is in progress the page auto-refreshes; when done it settles, no refresh."""

from __future__ import annotations

import json
import os
import re

from .runner import RunResult

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "review_template.html")


_OUTCOME_LABELS = {
    "blocked-roe": "BLOCKED (ROE)",
    "blocked-approval": "NEEDS APPROVAL",
}


def _job_obj(j) -> dict:
    return {
        "seq": j.seq, "id": j.id, "title": j.title, "type": (j.type or "").upper(),
        "defcon": j.defcon, "outcome": j.outcome,
        "outcomeLabel": _OUTCOME_LABELS.get(j.outcome, (j.outcome or "").upper()),
        "branch": j.branch, "diff": j.diff,
        "note": j.note, "mergeCmd": j.merge_cmd, "discardCmd": j.discard_cmd,
    }


def aar_dict(rr: RunResult) -> dict:
    return {
        "generatedAt": rr.generated_at,
        "state": rr.state,
        "refreshSeconds": rr.refresh_seconds,
        "sector": rr.sector,
        "repo": rr.repo,
        "verdict": (rr.verdict or "unknown").upper(),
        "note": rr.note,
        "jobs": [_job_obj(j) for j in rr.jobs],
    }


def render_review_md(rr: RunResult) -> str:
    lines = [f"# After-Action Report — {rr.generated_at}", "",
             f"{rr.repo} · {rr.note}", "",
             "| # | job | type | DEFCON | outcome | branch | diff |",
             "|---|-----|------|--------|---------|--------|------|"]
    for j in rr.jobs:
        d = (f"+{j.diff['insertions']}/-{j.diff['deletions']} ({j.diff['files']}f)"
             if j.diff else "—")
        lines.append(f"| {j.seq} | {j.title} | {j.type} | {j.defcon} | {j.outcome} "
                     f"| {j.branch or '—'} | {d} |")
    return "\n".join(lines) + "\n"


def render_review_html(rr: RunResult) -> str:
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    html = template.replace("__REVIEW_JSON__", json.dumps(aar_dict(rr)))
    if rr.state == "running":
        meta = f'<meta http-equiv="refresh" content="{rr.refresh_seconds}">'
        # Inject after the <head> open tag, tolerating attributes (design template may use
        # <head ...>); a lambda replacement avoids re backref-escaping in `meta`.
        html = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + "\n" + meta, html, count=1)
    return html
