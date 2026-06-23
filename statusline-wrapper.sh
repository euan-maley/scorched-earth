#!/bin/bash
# Scorched Earth statusline WRAPPER (used by the plugin install path).
#
# When installed as a plugin, the SessionStart hook points Claude Code's statusLine at
# this wrapper. It runs the user's *previous* statusline (captured at install, so we never
# clobber it) and appends the Scorched Earth light. If there was no prior statusline, it
# just shows the light.
#
# The statusline JSON arrives once on stdin; we fan it out to both the inner command and
# our segment.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$HOME/.claude/scorched-earth"
INNER_FILE="$STATE_DIR/inner-statusline.txt"

DATA=$(cat)

INNER_OUT=""
if [ -s "$INNER_FILE" ]; then
    INNER_CMD=$(cat "$INNER_FILE")
    # The captured command is the user's own prior statusLine.command — run it with the
    # same stdin Claude Code would have given it.
    INNER_OUT=$(printf '%s' "$DATA" | eval "$INNER_CMD" 2>/dev/null || true)
fi

SCORCH=$(printf '%s' "$DATA" | "$DIR/statusline-segment.sh" 2>/dev/null || true)

if [ -n "$INNER_OUT" ] && [ -n "$SCORCH" ]; then
    printf '%s  │  %s\n' "$INNER_OUT" "$SCORCH"
elif [ -n "$INNER_OUT" ]; then
    printf '%s\n' "$INNER_OUT"
elif [ -n "$SCORCH" ]; then
    printf '%s\n' "$SCORCH"
fi
