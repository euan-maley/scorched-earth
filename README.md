# Scorched Earth

A green light for your Claude usage. It tells you when your remaining **weekly**
budget can no longer be spent unless you max out **every remaining 5-hour
window** — so you never leave credits on the table at the weekly reset.

Unused weekly usage doesn't roll over. When you have lots of weekly budget left
but few windows before the reset, the rational move is to go scorched earth: burn
100% every window. This surfaces that moment as a 🟢 in your Claude Code statusline
and a `scorch` CLI / `/scorched-earth` skill readout.

## The idea

Claude Code exposes two live rate-limit buckets to the statusline: a **5-hour**
rolling window and a **7-day** (weekly) window. Scorched Earth compares:

- how much weekly budget you have left, against
- how many 5-hour windows remain before the weekly reset.

If you couldn't possibly spend your remaining weekly budget even by maxing every
remaining window, the light goes green — pacing yourself just wastes credits.

## Two signals

- **🟢 Hard light** — *certain*: you literally can't spend your weekly budget unless you
  max every remaining window. Fires late, never wrong. It's the green end of a three-state
  gauge: **🟢 green** "burn it all", **🟡 amber** "burn ~N% each window — you're near the
  line", and nothing shown when you have slack (**off**) or there's no reading yet (**unknown**).
- **🔥 Forecast nudge** — *earlier, habit-based*: Scorched Earth learns your day-of-week
  usage pattern and, when it projects you're trending to leave budget unused at your
  usual pace, gives a once-per-week preemptive heads-up. Starts rough and sharpens over
  a few weeks (like the calibration). Because most people never use 100% of every window,
  this is usually the more useful, earlier cue.

See `docs/the-math.md` for the full derivation (both signals) and `docs/playbook.md`
for how it's built.

## Quick start

```bash
scorch            # full readout from the latest live snapshot
scorch --watch    # re-print as data updates
scorch --style fire      # change the statusline light (fire|emoji|text|minimal|off)
scorch --sitrep   # open a stylized HTML field report (8-bit war / scorched crop field)
```

The **sitrep** (`scorch --sitrep`, alias `--report`) renders a war-HUD situation report
with THE FIELD: a Stardew-style pixel farm where each weekday plot grows lush when you
burn light and chars when you burn heavy. Toggle the field between **LAST WEEK** (what you
actually burned), **AVERAGE** (your all-time habit), and **THIS WEEK** (actual so far plus
projected/recommended for the days ahead).

## Install

**As a plugin (recommended).** This repo is its own marketplace. In Claude Code:

```
# from a local clone (works today, no remote needed):
/plugin marketplace add ~/scorched-earth
/plugin install scorched-earth@scorched-earth

# or, from GitHub:
/plugin marketplace add euan-maley/scorched-earth
/plugin install scorched-earth@scorched-earth
```

Then it's automatic — a SessionStart hook wires the light into your statusline (wrapping
any statusline you already have, never replacing it) and `/scorched-earth` + `scorch` are
available in-session. Ask the assistant to set your preferred light style, or run
`scorch --style <x>`.

**Manually (clone):**

```bash
git clone https://github.com/euan-maley/scorched-earth ~/scorched-earth
~/scorched-earth/install.sh   # puts `scorch` on PATH, picks a style, wires the statusline
```

Requires `python3` ≥ 3.8 (no pip deps). The light and CLI are cross-platform; the desktop
notification and `--sitrep` auto-open use macOS (`osascript`/`open`) with a Linux fallback
(`notify-send`/`xdg-open`) and otherwise no-op.

The three layers that make it work: a **statusline script** (the only surface Claude Code
feeds live usage data to — the engine), the **`scorch` CLI / `/scorched-earth` skill**
(read the cached state), and the **plugin** (bundles them + the install-time wiring). See
`docs/playbook.md`.
