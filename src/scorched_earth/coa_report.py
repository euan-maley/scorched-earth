"""Render a COA result to Markdown (the record) and HTML (the presentation). Both render from
the same COA object so they never disagree. Pure; the caller passes a formatted date string."""

from __future__ import annotations

import html as _html

from .advisor import COA


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


def render_html(coa: COA, generated_at: str) -> str:
    e = _html.escape
    rows = ""
    for j in coa.queue:
        rows += ("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"
                 .format(*[e(str(c)) for c in _row(j)]))
    if not rows:
        rows = '<tr><td colspan="6">(none)</td></tr>'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Scorched Earth · Course of Action</title>
<style>
  body{{background:#0b0705;color:#f4e4c8;font-family:ui-monospace,Menlo,monospace;padding:28px}}
  h1{{color:#ff8a1f;letter-spacing:2px}}
  table{{border-collapse:collapse;width:100%;margin-top:12px}}
  td,th{{border:1px solid #6b4a2b;padding:6px 10px;text-align:left}}
  th{{color:#e2a04d}} .note{{color:#e9c08a}}
</style></head><body>
<h1>COURSE OF ACTION <span style="color:#86abab;font-size:14px">// {e(generated_at)}</span></h1>
<div class="note">{e(coa.note)}</div>
<table><tr><th>id</th><th>tier</th><th>windows</th><th>value</th><th>type</th><th>title</th></tr>
{rows}</table>
</body></html>"""
