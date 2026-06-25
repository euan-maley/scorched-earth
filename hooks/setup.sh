#!/bin/bash
# Scorched Earth SessionStart setup (plugin install path).
# Idempotent and fast: ensures the statusLine points at our wrapper, capturing any prior
# statusline so we wrap rather than clobber it. Runs every session so it self-heals after
# a plugin update (the plugin dir is version-stamped, so the wrapper path changes).
#
# Never fails the session: best-effort, exits 0.
set -uo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$HOME/.claude/scorched-earth"
SETTINGS="$HOME/.claude/settings.json"
WRAPPER="$PLUGIN_ROOT/statusline-wrapper.sh"

command -v python3 >/dev/null 2>&1 || exit 0
mkdir -p "$STATE_DIR" 2>/dev/null || true
[ -f "$STATE_DIR/style" ] || echo "fire" > "$STATE_DIR/style"
chmod +x "$WRAPPER" "$PLUGIN_ROOT/statusline-segment.sh" "$PLUGIN_ROOT/bin/scorch" 2>/dev/null || true

python3 - "$SETTINGS" "$WRAPPER" "$STATE_DIR/inner-statusline.txt" <<'PY' 2>/dev/null || true
import json, os, sys
settings, wrapper, inner_file = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(settings) as f:
        cfg = json.load(f)
except (FileNotFoundError, ValueError):
    cfg = {}

sl = cfg.get("statusLine")
cur = sl.get("command") if isinstance(sl, dict) else None
is_ours = lambda c: bool(c) and "statusline-wrapper.sh" in c

if cur == wrapper:
    sys.exit(0)  # already current — nothing to do

# Preserve a genuinely foreign statusline so the wrapper can run it. Don't capture an
# older-version wrapper as "inner" (that would nest us inside ourselves).
if cur and not is_ours(cur):
    with open(inner_file, "w") as f:
        f.write(cur)

cfg["statusLine"] = {"type": "command", "command": wrapper}
os.makedirs(os.path.dirname(settings), exist_ok=True)
tmp = settings + ".tmp"
with open(tmp, "w") as f:
    json.dump(cfg, f, indent=2)
os.replace(tmp, settings)
PY

# --- bare (unprefixed) command aliases --------------------------------------
# Plugin commands are always namespaced (/scorched-earth:coa). To give users the bare forms
# (/coa, /sitrep, /roe, /war-room, /scorched-earth) we install standalone copies into their
# personal command dir. Collision-safe: only writes files WE manage (tagged with $SENTINEL);
# never clobbers a command the user already has. Re-runs each session so copies track updates.
CMD_DIR="$HOME/.claude/commands"
SENTINEL="managed-by: scorched-earth-plugin"
if mkdir -p "$CMD_DIR" 2>/dev/null; then
  for src in "$PLUGIN_ROOT"/commands/*.md; do
    [ -f "$src" ] || continue
    name="$(basename "$src")"; dest="$CMD_DIR/$name"
    if [ ! -e "$dest" ] || grep -q "$SENTINEL" "$dest" 2>/dev/null; then
      if { cat "$src"; printf '\n<!-- %s: bare alias of /scorched-earth:%s; overwritten on update -->\n' "$SENTINEL" "${name%.md}"; } > "$dest.tmp" 2>/dev/null; then
        mv "$dest.tmp" "$dest" 2>/dev/null || rm -f "$dest.tmp" 2>/dev/null
      fi
    fi
  done
  # bare /scorched-earth -> the in-session readout skill
  dest="$CMD_DIR/scorched-earth.md"
  if [ ! -e "$dest" ] || grep -q "$SENTINEL" "$dest" 2>/dev/null; then
    if cat > "$dest.tmp" <<EOF 2>/dev/null
---
description: Scorched Earth — weekly burn-rate readout + forecast (in-session signal)
---
Use the \`scorched-earth\` skill to give the weekly burn-rate readout (the hard green/amber/off
signal plus the day-of-week forecast). Pass through any argument (e.g. a light style like \`fire\`).

<!-- $SENTINEL: bare alias of the scorched-earth skill; overwritten on update -->
EOF
    then mv "$dest.tmp" "$dest" 2>/dev/null || rm -f "$dest.tmp" 2>/dev/null; fi
  fi
fi

exit 0
