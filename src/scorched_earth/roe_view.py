"""The served ROE editor (the Phase 2 #10 follow-up): the same pure `roe_edit` model the
terminal editor drives, rendered as a war-HUD shell tab and edited over a token-guarded
POST /roe. Read side: `roe_state` re-reads each repo's merged ROE per request. Write side: one
(repo, index, direction) editor step, applied via `roe_edit.apply` and saved instantly with
`roe_edit.save` (managed fields only; freeform keys are shown read-only and are never writable
from the browser). I/O tier; never on the statusline hot path."""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from . import coa_io, roe_edit

_TEMPLATE = os.path.join(os.path.dirname(__file__), "roe_template.html")

# Merged-ROE fields the editor does NOT manage, surfaced read-only for legibility (hand-edit
# them in .scorched/roe.json). Kept in sync with roe_edit.MANAGED_FIELDS by exclusion.
FREEFORM_FIELDS = ("test_cmd", "setup_cmd", "context_cmd", "min_weekly_left",
                   "goals", "exclude_paths")


def repo_state(repo: str) -> dict:
    """One repo's editor state: the control rows (current merged values) + the read-only
    freeform fields."""
    ap = os.path.realpath(os.path.expanduser(repo))
    roe = coa_io.load_roe(repo)
    return {"repo": ap, "name": os.path.basename(ap),
            "controls": [asdict(c) for c in roe_edit.controls(roe)],
            "freeform": {f: getattr(roe, f) for f in FREEFORM_FIELDS}}


def roe_state(repos) -> dict:
    return {"repos": [repo_state(r) for r in repos]}


def apply_step(repo: str, index: int, direction: int) -> dict:
    """Apply ONE editor step (the same reducer the curses editor uses) to the repo's ROE and
    persist it immediately. An out-of-range index is a no-op (the pure model guarantees it).
    Returns the repo's fresh state so the page can repaint from truth, not optimism."""
    roe = coa_io.load_roe(repo)
    new = roe_edit.apply(roe, index, direction)
    if new != roe:
        roe_edit.save(repo, new)
    return repo_state(repo)


def render_page(token: str, repos) -> bytes:
    """The ROE tab HTML: the template with the state + token baked in."""
    with open(_TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__ROE_TOKEN__", json.dumps(token))
    html = html.replace("__ROE_JSON__", json.dumps(roe_state(repos)))
    return html.encode("utf-8")
