#!/bin/bash
# Scorched Earth installer.
# - puts `scorch` on PATH
# - lets you pick how the statusline light looks
# - wires the light into your Claude Code statusline (with your approval)
#
# Re-runnable: it converges, never duplicates.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
STATE_DIR="$CLAUDE_DIR/scorched-earth"
STATUSLINE="$CLAUDE_DIR/statusline.sh"
SEGMENT="$REPO/statusline-segment.sh"
MARKER="scorched-earth/statusline-segment.sh"   # how we detect prior wiring

say() { printf '\033[1;32m›\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }

command -v python3 >/dev/null 2>&1 || { warn "python3 is required."; exit 1; }
mkdir -p "$STATE_DIR"
chmod +x "$REPO/bin/scorch" "$SEGMENT" 2>/dev/null || true

# 1) Put `scorch` on PATH ------------------------------------------------------
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
ln -sf "$REPO/bin/scorch" "$BIN_DIR/scorch"
say "Linked: $BIN_DIR/scorch"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR isn't on your PATH. Add it to your shell profile to use 'scorch' bare." ;;
esac

# 2) Pick the light style ------------------------------------------------------
echo
echo "How should the statusline light look?"
echo "  1) fire     🔥 BURN IT ALL   /  🟡 burn 85%   (animated flames, default)"
echo "  2) emoji    🟢 BURN IT ALL   /  🟡 burn 85%"
echo "  3) text     BURN IT ALL      /  burn 85%      (colored, no emoji)"
echo "  4) minimal  ● green dot      /  ● amber dot"
echo "  5) off      don't show a statusline light (CLI / skill only)"
printf "Choice [1-5]: "
read -r choice || choice=1
case "${choice:-1}" in
  2) STYLE=emoji ;;
  3) STYLE=text ;;
  4) STYLE=minimal ;;
  5) STYLE=off ;;
  *) STYLE=fire ;;
esac
echo "$STYLE" > "$STATE_DIR/style"
say "Light style: $STYLE"

# 3) Wire into the statusline --------------------------------------------------
if [ "$STYLE" = "off" ]; then
  say "Skipping statusline wiring (style is off). Use 'scorch' or /scorched-earth."
  exit 0
fi

WIRE_SNIPPET='
# Scorched Earth: weekly burn-rate light (auto-added by install.sh)
SCORCH_STR=""
SCORCH_SEGMENT="'"$SEGMENT"'"
if [ -x "$SCORCH_SEGMENT" ]; then
    SCORCH=$(printf '"'"'%s'"'"' "$DATA" | "$SCORCH_SEGMENT" 2>/dev/null)
    [ -n "$SCORCH" ] && SCORCH_STR="  │  ${SCORCH}"
fi
printf '"'"'%s\n'"'"' "$SCORCH_STR"'

if [ -f "$STATUSLINE" ] && grep -q "$MARKER" "$STATUSLINE"; then
  say "Statusline already wired. Nothing to do."
elif [ -f "$STATUSLINE" ]; then
  warn "You already have a statusline at $STATUSLINE."
  echo "  Add the light by piping your statusline JSON (\$DATA) through:"
  echo "    $SEGMENT"
  echo "  and appending its output. See README 'Wiring' for the exact 4 lines."
  printf "Append a standalone scorch line to your statusline now? [y/N]: "
  read -r ok || ok=n
  if [ "${ok:-n}" = "y" ] || [ "${ok:-n}" = "Y" ]; then
    printf '%s\n' "$WIRE_SNIPPET" >> "$STATUSLINE"
    say "Appended scorch segment to $STATUSLINE."
  fi
else
  cat > "$STATUSLINE" <<EOF
#!/bin/bash
# Minimal statusline created by Scorched Earth installer.
DATA=\$(cat)
$WIRE_SNIPPET
EOF
  chmod +x "$STATUSLINE"
  # Point Claude Code at it if no statusLine is configured.
  python3 - "$CLAUDE_DIR/settings.json" "$STATUSLINE" <<'PY'
import json, os, sys
path, sl = sys.argv[1], sys.argv[2]
try:
    with open(path) as f: cfg = json.load(f)
except (FileNotFoundError, ValueError): cfg = {}
cfg.setdefault("statusLine", {"type": "command", "command": sl})
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f: json.dump(cfg, f, indent=2)
print("Configured statusLine in", path)
PY
  say "Created and configured $STATUSLINE."
fi

echo
say "Done. Fire up a Claude Code session and the light shows up when it's time to burn."
