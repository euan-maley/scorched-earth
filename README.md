<p align="center">
  <img src="assets/banner.png" alt="Scorched Earth: torch it all, leave them nothing behind" width="760">
</p>

# Scorched Earth

A green light for your Claude usage. It tells you when your remaining **weekly**
budget can no longer be spent unless you max out **every remaining 5-hour
window**, so you never leave credits on the table at the weekly reset.

Unused weekly usage doesn't roll over. When you have lots of weekly budget left
but few windows before the reset, the rational move is to go scorched earth: burn
100% every window. It surfaces that moment as **🔥 BURN IT ALL** in your Claude Code
statusline, plus a `scorch` CLI / `/scorched-earth` skill readout.

## The idea

Claude Code exposes two live rate-limit buckets to the statusline: a **5-hour**
rolling window and a **7-day** (weekly) window. Scorched Earth compares:

- how much weekly budget you have left, against
- how many 5-hour windows remain before the weekly reset.

If you couldn't possibly spend your remaining weekly budget even by maxing every
remaining window, the light goes green. Pacing yourself just wastes credits.

## Two signals

The **🟢 hard light** is the certain one. It goes green only when you can't spend your
remaining weekly budget even by maxing every 5-hour window left before the reset. It fires
late, and it's never wrong. In the default fire style that green reads **🔥 BURN IT ALL**.
One notch back is amber, **🟡 burn ~N%**: close to the line, not over it. Any other time the
bar stays empty, either you have budget to spare or there's no live reading yet.

The **🔥 forecast nudge** comes earlier, and for most people it's the more useful of the two.
Scorched Earth learns your day-of-week pattern and projects where the week is heading. If
you're tracking to leave budget unused at your usual pace, it fires one desktop nudge per
weekly cycle. It starts rough and sharpens over a few weeks, same as the calibration. Most
people never max every window, so this usually lands well before the hard light would.

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

<p align="center">
  <a href="assets/sitrep-demo.mp4"><img src="assets/sitrep-poster.png" alt="Scorched Earth sitrep, green / burn-mode (click to play the 15s clip)" width="640"></a>
</p>

<!-- Inline player: open this README in github.com's web editor and drag assets/sitrep-demo.mp4
     onto this line. GitHub uploads it to user-attachments and renders an autoplaying HTML5
     player. (A repo-relative <video> tag is stripped from rendered READMEs, so we link the
     full-res poster to the mp4 instead.) -->

When the verdict goes green, the whole sitrep catches fire. Toggle the field across the
three views:

<p align="center">
  <img src="assets/sitrep-lastweek.png" alt="THE FIELD: last week" width="240">
  <img src="assets/sitrep-average.png" alt="THE FIELD: average" width="240">
  <img src="assets/sitrep-thisweek.png" alt="THE FIELD: this week (projected)" width="240">
</p>

<sub><i>Sample data. The poster links to a 15s clip (<a href="assets/sitrep-demo.mp4">mp4, 1512×944</a>). Stills and footage rendered from the real report pipeline.</i></sub>

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

Then it's automatic. A SessionStart hook wires the light into your statusline (wrapping
any statusline you already have, never replacing it), and `/scorched-earth`, `/sitrep`, and
`scorch` are available in-session. `/sitrep` generates and opens the HTML field report. Ask
the assistant to set your preferred light style, or run `scorch --style <x>`.

**Manually (clone):**

```bash
git clone https://github.com/euan-maley/scorched-earth ~/scorched-earth
~/scorched-earth/install.sh   # puts `scorch` on PATH, picks a style, wires the statusline
```

Requires `python3` ≥ 3.8 (no pip deps). The light and CLI are cross-platform; the desktop
notification and `--sitrep` auto-open use macOS (`osascript`/`open`) with a Linux fallback
(`notify-send`/`xdg-open`) and otherwise no-op.

The three layers that make it work: a **statusline script** (the engine, and the only
surface Claude Code feeds live usage data to), the **`scorch` CLI / `/scorched-earth` skill**
(read the cached state), and the **plugin** (bundles them plus the install-time wiring). See
`docs/playbook.md`.
