#!/bin/bash
# Scorched Earth statusline segment.
# Reads the Claude Code statusline JSON on stdin, emits a compact light token on stdout
# (empty when there's no actionable signal). Never fails into the host statusline.
#
# Host usage (statusline.sh already has the JSON in $DATA):
#   SCORCH=$(printf '%s' "$DATA" | "$HOME/scorched-earth/statusline-segment.sh")
#   [ -n "$SCORCH" ] && printf '  │  %s' "$SCORCH"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || exit 0

PYTHONPATH="$REPO/src" python3 -m scorched_earth.statusline 2>/dev/null || true
