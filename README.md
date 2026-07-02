https://github.com/user-attachments/assets/52706f21-19d8-49f1-b5cc-1a5ec865a508

# Scorched Earth

*Claude Code plugin for weekly Claude usage and rate-limit tracking, with a DEFCON-ranked autonomous task runner (Course of Action) for your linked repos.*

A fire-team readout for your Claude usage. It tells you when your remaining **weekly**
budget can no longer be spent unless you max out **every remaining 5-hour window**, and,
now, when you're burning so fast you'll run dry before the reset, so you never leave
credits on the table and never burn out early.

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
remaining window, it calls **BURN IT ALL**. Pacing yourself just wastes credits.

## The deck

The statusline shows one of a five-state firing deck, each with its own token and color:

- **🔥 BURN IT ALL** (red) - you can't spend the rest of your weekly budget even by maxing
  every window left. Torch it; pacing wastes credits. The certain, late, never-wrong signal.
- **🟢 clear shot, take it** (green) - near full throttle, close to the line.
- **⚪ eyes on the target** (white) - deep reserves, dead on pace; hold steady, no rush.
- **⚠️ hold your fire** (yellow) - at your recent pace you'll run the budget dry before the
  reset and sit locked out. Ease off so you keep some for tomorrow. It self-disengages near
  the reset, so it never fights BURN IT ALL.
- **🎖️ good job, soldier** (purple) - weekly budget spent; rest up for reinforcements.

The bar is only empty when there's no live reading yet.

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

When the verdict goes green, the whole sitrep catches fire. Toggle the field across the
three views:

<p align="center">
  <img src="assets/sitrep-lastweek.png" alt="THE FIELD: last week" width="240">
  <img src="assets/sitrep-average.png" alt="THE FIELD: average" width="240">
  <img src="assets/sitrep-thisweek.png" alt="THE FIELD: this week (projected)" width="240">
</p>

<sub><i>Sample data. The clip and stills are rendered from the real report pipeline (<a href="https://github.com/user-attachments/assets/52706f21-19d8-49f1-b5cc-1a5ec865a508">download the mp4</a>).</i></sub>

## Burn it on something

The deck tells you to burn (or ease off). It doesn't tell you what on. That's the Course of
Action layer.

Link a repo or a few with `scorch link <path>`, and a scan agent reads them the way you
would: TODO and FIXME markers, recent commit themes, the roadmap, whatever open issues it
can reach. It surfaces the expensive work, the jobs big enough to be worth a window you'd
otherwise waste, and rates each one DEFCON 5 down to 1 by impact on the project rather than
effort. DEFCON 1 is the biggest blast radius: a whole-codebase security audit, a full
regression and UI-capability test harness, a backend built out in one pass. The scale
measures stakes, not urgency, so a DEFCON 1 is the most consequential job, not the one you
necessarily start with.

`/coa` generates the ranked plan and opens it as a live report in your browser: one tab per
linked repo, with a Refresh button that re-reads each repo's jobs without re-scanning. From
there you can queue jobs and let them run headless in
a sandboxed git worktree (`scorch coa run`), each one committed but never pushed and checked
against a test command you set. The Rules of Engagement (`/roe`) decide what's allowed to run
unattended: DEFCON 1 and 2 sit behind an approval gate by default, and `max_jobs` caps a run
so an overnight campaign can't sprawl.

`/war-room` opens the unified **War Room shell**: one localhost page with three big tabs,
SITREP (the field report), COURSE OF ACTION (the ranked plan), and WAR ROOM (the live cockpit,
a kanban board with drag-to-queue and a runner that drains your linked repos in parallel). One
server, one token, switch freely between all three; `/coa` and `/sitrep` open the same shell on
their tab. The cockpit flags a HALTED state (with a resume hint) when it hits the weekly usage
ceiling, shows each running job's latest step live, and each surface has an honest Refresh. The
URL carries a one-time access token, so treat it like a credential and don't paste it around.

**Run modes.** Headless is the default (sandboxed worktree, unattended), but a job can run
in the mode you pick, set globally or per repo in the ROE: **takeover** hands it to your
current terminal window (still network-sandboxed), and **session** opens a fresh Claude Code
session in the repo, optionally running a context command like your session-start first. Each
job picks its own model by weight (haiku for knockouts, opus for the big campaigns) and leaves
a deliverable you can read.

**Roadblock safety net.** If an unattended job gets stuck or fails its gate, Scorched Earth
tries a recovery agent first; if that can't fix it, the job pauses, writes up what happened and
how to fix it, pings you, and keeps the branch so you can pick it back up with
`scorch coa resume`. One roadblock doesn't stop the rest of the run.

`/roe` opens the Rules of Engagement editor in your browser: a RULES OF ENGAGEMENT tab in the
War Room shell with a GLOBAL scope (rules for every repo) plus per-repo tabs, each with a
rules-source toggle (follow global, or go repo-specific; switching back and forth never loses
your overrides). Every click saves instantly. Attended runs skip permission prompts by default
(hit go and it works), dialable per repo to `edits` or `prompt`. The same editor lives in the
terminal as `scorch roe` (arrow keys, space to toggle, `s` to save; `--global` edits the
global rules).

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
any statusline you already have, never replacing it), and `/scorched-earth`, `/sitrep`,
`/coa`, `/roe`, `/war-room`, and `scorch` are available in-session. The first time you run
`/scorched-earth` it walks you through a quick setup: it picks a light style and links any
repos you want the COA layer watching. You can redo it anytime, or just run
`scorch --style <x>` to change the light on its own.

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


<p align="center">
  <img src="assets/banner.png" alt="Scorched Earth: torch it all, leave them nothing behind" width="760">
</p>
