"""Execution modes for COA jobs (Phase 3). The headless mode stays in runner.py; this module
owns the two ATTENDED modes and the shared machinery:

  - resolve_mode: the pure mode cascade (per-task override -> ROE run_mode -> headless).
  - operating_orders / compose_attended_prompt: the ROE leash + goal + task, injected into the
    opening prompt an attended session starts from (the "session context" clause).
  - build_takeover_cmd / build_session_cmd: pure command builders (unit-tested).
  - run_takeover / run_session: thin launchers (execvp this window / spawn a new one). These
    replace or spawn a process and are verified by hand, not unit-tested.

takeover keeps the OS sandbox (delivered via a CLI --settings file so the real repo's own
.claude/settings.json is never touched); session is fully free. How much an attended claude may
do WITHOUT asking is the ROE `attended_perms` dial (perms_args): default `skip`
(--dangerously-skip-permissions), because the operator hit go precisely so the job runs
without babysitting permission prompts; `edits` auto-approves file edits only; `prompt` asks
for everything. For takeover the OS sandbox still locks network + credentials underneath
`skip`, the same trust model as the headless worktree."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

from . import coa_io
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
    parts.append("When done, write a short deliverable (what changed, files touched, "
                 "follow-ups) to `{}`.".format(coa_io.deliverable_rel(job.id)))
    parts.append("Task:\n" + (job.launch or job.title))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Command builders (pure)
# ---------------------------------------------------------------------------

VALID_PERMS = ("skip", "edits", "prompt")


def perms_args(roe: ROE) -> List[str]:
    """The permission flags an attended claude gets, from the ROE attended_perms dial: `skip`
    runs --dangerously-skip-permissions (the default: the operator hit go so the job should do
    the work, not queue up permission prompts), `edits` auto-approves file edits but still asks
    for commands, `prompt` asks for everything. Unknown values fall back to skip. Pure."""
    p = getattr(roe, "attended_perms", "skip") or "skip"
    if p == "prompt":
        return []
    if p == "edits":
        return ["--permission-mode", "acceptEdits"]
    return ["--dangerously-skip-permissions"]


def build_takeover_cmd(job: Job, roe: ROE, settings_path: str) -> List[str]:
    """Interactive claude that seizes the current window. The composed opening prompt is the
    positional argument; the OS sandbox rides --settings (a temp file outside the repo) and
    still confines the default skip-permissions run (API-only network, no credentials)."""
    return ["claude", compose_attended_prompt(job, roe),
            "--settings", settings_path] + perms_args(roe) + model_arg(job)


def build_session_cmd(job: Job, roe: ROE) -> List[str]:
    """Interactive claude for a fresh session in a new window (no OS sandbox): the composed
    opening prompt as the positional arg, the ROE permission dial, plus the per-task model. The
    'run it in front of me with full context' mode; the operator, the injected orders, and the
    attended_perms dial are the leash."""
    return ["claude", compose_attended_prompt(job, roe)] + perms_args(roe) + model_arg(job)


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
    with ROE attended_branch. If that branch already exists, check it out instead of failing
    silently onto whatever branch happened to be current; if that also fails, raise so the
    caller can report it instead of quietly working on the wrong branch."""
    if not roe.attended_branch:
        return
    name = branch_name(job.id)
    created = subprocess.run(["git", "-C", root, "checkout", "-b", name],
                             capture_output=True, text=True)
    if created.returncode == 0:
        return
    exists = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "--quiet", name],
                            capture_output=True, text=True)
    if exists.returncode == 0:
        switched = subprocess.run(["git", "-C", root, "checkout", name],
                                  capture_output=True, text=True)
        if switched.returncode == 0:
            return
        raise RuntimeError(f"Could not switch to existing branch '{name}' in {root}: "
                           f"{switched.stderr.strip()}")
    raise RuntimeError(f"Could not create branch '{name}' in {root}: {created.stderr.strip()}")


def run_takeover(repo: str, job: Job, roe: ROE) -> None:
    """Seize THIS terminal window: exec an interactive claude in the real repo. Replaces the
    current process, so it never returns on success. Verified by hand (execvp)."""
    root = os.path.realpath(os.path.expanduser(repo))
    try:
        _maybe_branch(root, job, roe)
    except RuntimeError as exc:
        print(str(exc))
        return
    os.chdir(root)
    cmd = build_takeover_cmd(job, roe, write_temp_sandbox_settings())
    os.execvp(cmd[0], cmd)


def _session_script(repo_root: str, cmd: List[str]) -> str:
    """Write a temp shell script that cd's to the repo then execs the session command; return its
    path. Sidesteps nested AppleScript / terminal quoting: the terminal just runs one file path."""
    body = "#!/bin/bash\ncd {}\nexec {}\n".format(
        shlex.quote(repo_root), " ".join(shlex.quote(a) for a in cmd))
    fd, path = tempfile.mkstemp(prefix="scorch-session-", suffix=".sh")
    with os.fdopen(fd, "w") as fh:
        fh.write(body)
    os.chmod(path, 0o755)
    return path


def _osascript(src: str) -> bool:
    try:
        return subprocess.run(["osascript", "-e", src],
                              capture_output=True, text=True).returncode == 0
    except Exception:  # noqa: BLE001 — osascript absent / AppleScript error -> caller falls back
        return False


def _as_quote(s: str) -> str:
    """Escape a string for safe embedding inside a double-quoted AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _spawn_terminal(script_path: str) -> bool:
    """Open a new terminal window/tab running script_path. macOS: iTerm first, then Terminal.app.
    Linux: best-effort common emulators. Returns True if one launched, else False (caller prints
    the manual command)."""
    if sys.platform == "darwin":
        safe_path = _as_quote(script_path)
        iterm = ('tell application "iTerm"\n'
                 '  if (count of windows) = 0 then\n'
                 '    create window with default profile\n'
                 '  else\n'
                 '    tell current window to create tab with default profile\n'
                 '  end if\n'
                 '  tell current session of current window to write text "bash {}"\n'
                 'end tell').format(safe_path)
        if _osascript(iterm):
            return True
        return _osascript('tell application "Terminal" to do script "bash {}"'.format(safe_path))
    for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"],
                 ["konsole", "-e"], ["xterm", "-e"]):
        if shutil.which(term[0]):
            try:
                subprocess.Popen([term[0]] + term[1:] + ["bash", script_path])
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def run_session(repo: str, job: Job, roe: ROE) -> int:
    """Spawn a NEW terminal session in the real repo running the job (fully free). Your current
    window stays put. Falls back to printing the exact command if no terminal can be opened.
    Verified by hand (spawns a window)."""
    root = os.path.realpath(os.path.expanduser(repo))
    try:
        _maybe_branch(root, job, roe)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    cmd = build_session_cmd(job, roe)
    if not _spawn_terminal(_session_script(root, cmd)):
        print("Could not open a new terminal. Run this job yourself:")
        print("  cd {} && {}".format(shlex.quote(root), " ".join(shlex.quote(a) for a in cmd)))
    return 0
