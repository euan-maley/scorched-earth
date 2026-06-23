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

exit 0
