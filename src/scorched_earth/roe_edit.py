"""Interactive ROE editor model: pure, stdlib-only. Describes the toggle/cycle-able Rules of
Engagement as a flat list of controls plus a reducer for arrow-key input, so the terminal
(curses) frontend and a later html frontend share one source of truth.

Only WIRED rules are exposed - fields the advisor/runner actually consume:
  run_mode (cycle), auto_run_min_defcon (cycle), max_jobs (cycle), attended_branch (toggle),
  advise_on_roadblock (toggle), roadblock_idle_secs (cycle), allowed_types + unattended_types
  (toggle rows). Freeform fields (test_cmd/setup_cmd/context_cmd/goals/exclude_paths/
  min_weekly_left) are left to hand-editing and preserved untouched on save. No dead toggles."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .roe import ROE
from .runner import SAFE_UNATTENDED

# Canonical job types (freeform in data, but these are the known ones the scan/runner emit).
KNOWN_TYPES = ["test", "docs", "perf", "audit", "refactor", "fix", "infra"]
RUN_MODE_CYCLE = ["headless", "takeover", "session"]   # how a job runs (Phase 3)
DEFCON_CYCLE = [1, 2, 3, 4, 5]              # auto_run_min_defcon: DEFCON >= N auto-runs; below N asks
MAX_JOBS_CYCLE = [None, 1, 2, 3, 5, 10]     # None = off (no run cap)
IDLE_SECS_CYCLE = [300, 600, 900, 1800]     # roadblock idle timeout: 5 / 10 / 15 / 30 min

# The two type-set fields and the set they default to when unset (None).
_TYPESETS = {"allowed_types": KNOWN_TYPES, "unattended_types": SAFE_UNATTENDED}


@dataclass
class Control:
    field: str            # the ROE field this row edits
    member: str | None    # for a type-set toggle: which type; None for cycles
    label: str            # human label
    kind: str             # "cycle" | "toggle"
    value: str            # display value for a cycle ("DEFCON 3", "off", "5"); "" for toggles
    on: bool | None       # toggle state; None for cycles
    help: str = ""        # one-line explanation


def _typeset(roe: ROE, field: str) -> set:
    v = getattr(roe, field)
    return set(v) if v is not None else set(_TYPESETS[field])


def controls(roe: ROE) -> list:
    """The ordered list of editable controls for this ROE, with current values filled in."""
    out = [
        Control("run_mode", None,
                "Run mode", "cycle", roe.run_mode, None,
                "headless = sandboxed worktree; takeover = this window, sandboxed; session = new free session."),
        Control("auto_run_min_defcon", None,
                "Auto-run threshold", "cycle", f"DEFCON {roe.auto_run_min_defcon}", None,
                "Jobs at DEFCON >= N auto-run; below N (more critical) needs approval."),
        Control("max_jobs", None,
                "Run cap", "cycle", "off" if roe.max_jobs is None else str(roe.max_jobs), None,
                "Stop a war-room session after N jobs. off = drain the whole queue."),
        Control("attended_branch", None,
                "Attended branch", "toggle", "", roe.attended_branch,
                "Attended jobs run on a fresh scorched/<id> branch (on) or your current branch (off)."),
        Control("advise_on_roadblock", None,
                "Auto-advise on roadblock", "toggle", "", roe.advise_on_roadblock,
                "On a headless roadblock, try an advising agent to auto-solve before pausing."),
        Control("roadblock_idle_secs", None,
                "Roadblock idle timeout", "cycle", f"{roe.roadblock_idle_secs // 60} min", None,
                "Headless: minutes of no output before a job is flagged stuck."),
    ]
    allowed = _typeset(roe, "allowed_types")
    for t in KNOWN_TYPES:
        out.append(Control("allowed_types", t, f"Allow type: {t}", "toggle", "", t in allowed,
                           "Whether the advisor may propose this job type at all."))
    unatt = _typeset(roe, "unattended_types")
    for t in KNOWN_TYPES:
        out.append(Control("unattended_types", t, f"Unattended: {t}", "toggle", "", t in unatt,
                           "Whether this type may run unattended (else operator-present only)."))
    return out


def _cycle(seq, cur, direction):
    """Step `cur` forward (direction >= 0) or back through `seq`, wrapping around."""
    i = seq.index(cur) if cur in seq else 0
    return seq[(i + (1 if direction >= 0 else -1)) % len(seq)]


def apply(roe: ROE, index: int, direction: int) -> ROE:
    """Return a NEW ROE with the control at `index` changed. direction: +1 right, -1 left,
    0 = toggle/enter (cycles treat 0 as +1). Out-of-range index is a no-op. Pure."""
    ctrls = controls(roe)
    if not (0 <= index < len(ctrls)):
        return roe
    c = ctrls[index]
    if c.field == "run_mode":
        return replace(roe, run_mode=_cycle(RUN_MODE_CYCLE, roe.run_mode, direction or 1))
    if c.field == "auto_run_min_defcon":
        return replace(roe, auto_run_min_defcon=_cycle(DEFCON_CYCLE, roe.auto_run_min_defcon, direction or 1))
    if c.field == "max_jobs":
        return replace(roe, max_jobs=_cycle(MAX_JOBS_CYCLE, roe.max_jobs, direction or 1))
    if c.field == "roadblock_idle_secs":
        return replace(roe, roadblock_idle_secs=_cycle(IDLE_SECS_CYCLE, roe.roadblock_idle_secs, direction or 1))
    if c.field in ("attended_branch", "advise_on_roadblock"):   # plain boolean toggles
        return replace(roe, **{c.field: not getattr(roe, c.field)})
    if c.field in _TYPESETS:                       # toggle: left/right/enter all flip
        cur = _typeset(roe, c.field)
        cur.discard(c.member) if c.member in cur else cur.add(c.member)
        ordered = [t for t in KNOWN_TYPES if t in cur]
        return replace(roe, **{c.field: ordered})
    return roe


# Which ROE fields the editor manages (overwritten on save); everything else in roe.json is kept.
MANAGED_FIELDS = ("run_mode", "auto_run_min_defcon", "max_jobs", "attended_branch",
                  "advise_on_roadblock", "roadblock_idle_secs", "allowed_types", "unattended_types")


def to_raw(roe: ROE, base_raw: dict | None = None) -> dict:
    """The roe.json dict to persist: `base_raw` (the repo's existing file, to preserve freeform
    keys) with the managed fields overwritten from `roe`."""
    d = dict(base_raw or {})
    for f in MANAGED_FIELDS:
        d[f] = getattr(roe, f)
    return d


def save(repo_path: str, roe: ROE) -> str:
    """Persist `roe` to the repo's roe.json, overwriting only the managed fields and preserving
    any freeform keys already there. Returns the file path."""
    from . import coa_io
    return coa_io.write_roe_raw(repo_path, to_raw(roe, coa_io.read_roe_raw(repo_path)))
