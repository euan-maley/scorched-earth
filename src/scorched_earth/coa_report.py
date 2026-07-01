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
        lines += ["", "## Blocked by ROE", ""]
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


def _repo_name(repo_path: str) -> str:
    return os.path.basename((repo_path or "").rstrip("/")) or repo_path or "repo"


def _repo_obj(repo_path: str, coa: COA, roe_lines=None) -> dict:
    from . import coa_io
    return {
        "repo": repo_path or "",
        "name": _repo_name(repo_path),
        "note": coa.note,
        "roe": list(roe_lines or []),
        "scannedAt": coa_io.jobs_scanned_at(repo_path) if repo_path else None,
        "queue": [_job_obj(j) for j in coa.queue],
        "blocked": [_job_obj(j) for j in coa.blocked],
    }


def build_data(repo_coas, generated_at: str, *, verdict: str = "unknown", reset_in: str = "",
               weekly_reserve_pct: float = 0.0, roe_by_repo=None) -> dict:
    """The COA data blob the template renders: global accent/date/reserve + a `repos` list, each
    repo carrying its own DEFCON-ranked queue + blocked + note (so the page can tab between them).
    `repo_coas` is an iterable of (repo_path, COA)."""
    roe_by_repo = roe_by_repo or {}
    return {
        "sector": "SECTOR 07",
        "date": generated_at,
        "verdict": (verdict or "unknown").lower(),
        "weeklyReservePct": round(weekly_reserve_pct or 0.0, 0),
        "resetIn": reset_in,
        "repos": [_repo_obj(rp, c, roe_by_repo.get(rp)) for rp, c in repo_coas],
    }


def render_html(coa, generated_at: str, *, repos=None, verdict: str = "unknown",
                roe_lines=None, reset_in: str = "", weekly_reserve_pct: float = 0.0,
                token: str = "") -> str:
    """Fill the war-HUD COA template. Pass either a single `coa` (one repo, no tabs) or `repos` as
    a list of (repo_path, COA) for the multi-repo tabbed view. `token`, when set, arms the in-page
    Refresh button (served mode); empty for the static record. `verdict` drives the accent."""
    if repos is None:
        repos = [("", coa)]
        roe_by_repo = {"": roe_lines}
    else:
        roe_by_repo = {rp: roe_lines for rp, _ in repos} if roe_lines else None
    data = build_data(repos, generated_at, verdict=verdict, reset_in=reset_in,
                      weekly_reserve_pct=weekly_reserve_pct, roe_by_repo=roe_by_repo)
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    return (template.replace("__COA_JSON__", json.dumps(data))
                    .replace("__COA_TOKEN__", json.dumps(token)))
