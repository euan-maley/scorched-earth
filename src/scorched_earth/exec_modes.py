"""Execution modes for COA jobs (Phase 3). The headless mode stays in runner.py; this module
owns the two ATTENDED modes and the shared machinery:

  - resolve_mode: the pure mode cascade (per-task override -> ROE run_mode -> headless).
  - operating_orders / compose_attended_prompt: the ROE leash + goal + task, injected into the
    opening prompt an attended session starts from (the "session context" clause).
  - build_takeover_cmd / build_session_cmd: pure command builders (unit-tested).
  - run_takeover / run_session: thin launchers (execvp this window / spawn a new one). These
    replace or spawn a process and are verified by hand, not unit-tested.

takeover keeps the OS sandbox (delivered via a CLI --settings file so the real repo's own
.claude/settings.json is never touched); session is fully free. Neither uses
--dangerously-skip-permissions: the present operator approves actions (for takeover the sandbox
locks network + credentials on top). Only headless (disposable worktree) skips permissions."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import List, Optional

from .jobs import Job
from .roe import ROE
from .runner import branch_name, model_arg, sandbox_settings_dict

VALID_MODES = ("headless", "takeover", "session")


def resolve_mode(roe: ROE, override: Optional[str] = None) -> str:
    """The effective run mode: a valid per-task override wins, else the (already global+per-repo
    merged) ROE run_mode, else headless. Pure."""
    if override in VALID_MODES:
        return override
    m = getattr(roe, "run_mode", "headless") or "headless"
    return m if m in VALID_MODES else "headless"


# ---------------------------------------------------------------------------
# Opening prompt: operating orders (ROE leash + goal) + the task
# ---------------------------------------------------------------------------

_ATTENDED_HEADER = (
    "You are running an approved Course-of-Action job in this repository, with the operator "
    "present and watching. Operating orders:"
)


def operating_orders(roe: ROE) -> str:
    """The ROE leash + goal as binding operating orders, injected into every attended job. This
    is the attended modes' equivalent of the headless OS sandbox: it keeps the agent on-mission
    and inside the confines the human set. Pure."""
    lines = []
    if roe.goals:
        lines.append("- Goal(s): " + "; ".join(roe.goals))
    if roe.exclude_paths:
        lines.append("- Do NOT touch these paths: " + ", ".join(roe.exclude_paths))
    if roe.allowed_types:
        lines.append("- Stay within these work types: " + ", ".join(roe.allowed_types))
    lines.append("- Make additive, focused changes; do not touch other repositories or files "
                 "outside this repo.")
    lines.append("- When done, commit with a clear message. Do NOT push.")
    return "\n".join(lines)


def compose_attended_prompt(job: Job, roe: ROE) -> str:
    """The single opening message an attended session starts from: an optional context-gathering
    command, the operating orders, an optional model hint, then the task. We hand the session this
    one prompt and let the agent itself run the context command and the task. Pure."""
    parts = []
    if roe.context_cmd:
        parts.append("First, run `{}` to gather context before starting.".format(roe.context_cmd))
    parts.append(_ATTENDED_HEADER + "\n" + operating_orders(roe))
    if getattr(job, "model", ""):
        parts.append("(Recommended model for this task: {}.)".format(job.model))
    parts.append("Task:\n" + (job.launch or job.title))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Command builders (pure)
# ---------------------------------------------------------------------------

def build_takeover_cmd(job: Job, roe: ROE, settings_path: str) -> List[str]:
    """Interactive claude that seizes the current window. The composed opening prompt is the
    positional argument; the OS sandbox rides --settings (a temp file outside the repo). No
    --dangerously-skip-permissions: the present operator approves, the sandbox locks network."""
    return ["claude", compose_attended_prompt(job, roe),
            "--settings", settings_path] + model_arg(job)


# ---------------------------------------------------------------------------
# Launchers (thin I/O; verified by hand, not unit-tested)
# ---------------------------------------------------------------------------

def write_temp_sandbox_settings() -> str:
    """Write the OS-sandbox settings to a temp file OUTSIDE any repo; return its path. Used to
    deliver the sandbox to an attended takeover without writing the repo's own .claude/."""
    fd, path = tempfile.mkstemp(prefix="scorch-sandbox-", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(sandbox_settings_dict(), fh)
    return path


def _maybe_branch(root: str, job: Job, roe: ROE) -> None:
    """Attended jobs run on the current branch by default; opt into a fresh scorched/<id> branch
    with ROE attended_branch."""
    if roe.attended_branch:
        subprocess.run(["git", "-C", root, "checkout", "-b", branch_name(job.id)],
                       capture_output=True, text=True)


def run_takeover(repo: str, job: Job, roe: ROE) -> None:
    """Seize THIS terminal window: exec an interactive claude in the real repo. Replaces the
    current process, so it never returns on success. Verified by hand (execvp)."""
    root = os.path.realpath(os.path.expanduser(repo))
    _maybe_branch(root, job, roe)
    os.chdir(root)
    cmd = build_takeover_cmd(job, roe, write_temp_sandbox_settings())
    os.execvp(cmd[0], cmd)
