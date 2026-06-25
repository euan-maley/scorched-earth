# Scorched Earth — First-Run Setup

You are Claude, running the guided first-run setup for the Scorched Earth plugin.
Work through the five steps below in order. Deliver the experience conversationally —
the user does not see this file directly.

---

## STEP 1 — Familiarize yourself (silent — no user output yet)

Read this primer so you can guide knowledgeably. **Caveat:** this primes the
**current session only**. Claude is not persistently trained across sessions;
ongoing sessions continue to rely on `CLAUDE.md` and `docs/` as usual.

### The green-light guarantee

Scorched Earth solves one problem: Claude's weekly usage budget does not roll
over. Unused credit at the weekly reset is forfeit. The plugin watches the
statusline's live rate-limit data and emits a **hard signal** when remaining
budget can only be spent by maxing every remaining 5-hour window.

The signal has four tiers:
- **🟢 green** — you literally cannot spend the weekly budget unless you max
  every remaining 5-hour window. Guaranteed green light: torch it all.
- **🟡 amber** — close but not yet guaranteed. Sustain ~N% of each remaining
  window and all budget is spent by reset. Hold the line.
- **⚪ off** — deep reserves. Even a light pace clears the budget by reset.
  No rationing needed; advance as hard as you like.
- **❔ unknown** — no live snapshot yet (statusline needs a reading from an
  active Claude Code session) or R is not calibrated.

### R — the self-measured conversion factor

**R** is the fraction of the weekly cap that one full 5-hour window burns.
It is self-measured from the user's own statusline deltas — not hardcoded.
With R and the current budget readings, the math asks: does maxing every
remaining window exactly exhaust the weekly cap? If yes → green.

R refines itself over a few weeks as more data accumulates. It can be pinned
manually (`scorch --set-r <value>`) or used for a single readout only
(`scorch --r <value>`) without persisting.

### The sitrep

`/sitrep` (or `scorch --sitrep`) generates a self-contained HTML war/crop-field
HUD — an 8-bit pixel farm with a Stardew-style field showing LAST WEEK / AVERAGE
/ THIS WEEK burn history, live countdowns, and the burn verdict. Same data source
as the CLI readout; richer visual.

### The COA advisor model

The COA (Course of Action) advisor proposes a prioritized queue of jobs from
linked repos and plans what to run during a burn window.

**DEFCON 1–5 criticality:**
- DEFCON 1 = biggest blast radius, highest risk, most disruptive. Needs the
  most careful review before running. NOT "do first" — it means "highest
  stakes." Think: production migrations, cross-repo refactors.
- DEFCON 5 = low-stakes background task (docs, tests, lints). Safe to run
  unattended.
- The advisor surfaces DEFCON levels so the user can decide what to approve
  or skip. It is not a run order.

**`auto_run_min_defcon` (default: 3):** Jobs with DEFCON < `auto_run_min_defcon`
require explicit approval before the queue-runner will execute them. With the
default of 3, DEFCON 3/4/5 jobs auto-run; DEFCON 1/2 need a thumbs-up first.
Configurable per-repo via `/roe`.

**Queue-runner:** Drains `.scorched/queue.json` in DEFCON order under the ROE
leash. Halts on a real usage-limit hit — no budget envelope. Started with
`scorch coa run`.

**Live war-room cockpit (`/war-room`):** Launches a 127.0.0.1 HTTP server
hosting an event-driven kanban board. Jobs advance stage by stage; SSE pushes
board state live to the browser. One-time access token for safety. Started
with `scorch coa --serve`.

**Entry points (slash commands):**
- `/coa` — generate a Course of Action (what to run this burn window)
- `/roe` — view and edit the Rules of Engagement (limits, approval gates,
  allowed job types)
- `/war-room` — open the live cockpit; `/war-room stop` kills it

Repos must be linked (`scorch link <path>`) before `/coa` or `/war-room` do
anything useful. Jobs are defined in `.scorched/jobs.json` within each repo.

Once you have read this primer, proceed to STEP 2.

---

## STEP 2 — Explain to the user

Give a short, conversational tour (a few sentences, not a wall of text):

1. **The statusline light** — the 🔥/🟢/🟡/⚪ signal in their Claude Code
   statusline tells them at a glance whether to burn hard. Green means every
   remaining 5-hour window must be maxed or some weekly budget is forfeit.
2. **`/sitrep`** — the full visual dashboard: pixel-farm HUD, burn history,
   live countdown. Run it any time they want the whole picture.
3. **The COA advisor + `/war-room`** — once repos are linked, `/coa` proposes
   a DEFCON-rated job queue and `/war-room` opens a live kanban cockpit to
   drain it during a burn window.
4. **This setup runs once.** They can redo it any time:
   - Ask "redo scorched-earth setup" in any session.
   - Or `rm ~/.claude/scorched-earth/onboarded` then invoke `/scorched-earth`.

---

## STEP 3 — Pick the light style

Ask the user which statusline style they'd like. Present the options:

| Style     | Appearance                                          |
|-----------|-----------------------------------------------------|
| `fire`    | 🔥 BURN IT ALL (animated flames — the default)      |
| `emoji`   | 🟢 BURN IT ALL / 🟡 burn N%                        |
| `text`    | BURN IT ALL / burn N% (colored words, no emoji)     |
| `minimal` | ● green / ● amber dot                              |
| `off`     | no statusline light (CLI / skill only)              |

If they have no preference, keep `fire` — the install hook already seeded it.
Once they choose, set it:

```bash
scorch --style <chosen-style> 2>/dev/null || ~/scorched-earth/bin/scorch --style <chosen-style>
```

The command prints the style name and a preview. Confirm the choice aloud.

---

## STEP 4 — Link repos (optional)

Explain that the COA advisor watches linked repos for `.scorched/jobs.json`
(job definitions). A user who only wants the green-light signal can **skip
this step** — the COA features stay idle until they link something later.

If they want to link repos:
- Accept pasted absolute paths.
- As a convenience, if they name a parent directory (e.g. `~/dev`), offer to
  scan it for git repos:

  ```bash
  find ~/dev -maxdepth 2 -name ".git" -type d 2>/dev/null | sed 's|/.git$||'
  ```

  Adjust the path and depth to match what they named. Show the results and let
  them pick.

For each repo path they choose, link it (substitute the real absolute path):

```bash
scorch link /absolute/path/to/repo 2>/dev/null || ~/scorched-earth/bin/scorch link /absolute/path/to/repo
```

The command prints "Linked /resolved/path" on success and adds `.scorched/`
to the repo's `.gitignore` so linking never dirties the working tree. Surface
that output — do not fabricate success if the command errors.

After all repos are linked, confirm the full registry:

```bash
cat ~/.claude/scorched-earth/repos.json 2>/dev/null
```

If they skip linking, acknowledge it and tell them they can link repos later
with `scorch link <path>` or by redoing this setup.

---

## STEP 5 — Finish

1. Ensure the state directory exists and write the sentinel:

   ```bash
   mkdir -p ~/.claude/scorched-earth && date > ~/.claude/scorched-earth/onboarded
   ```

2. Tell the user setup is complete and that future `/scorched-earth`
   invocations go straight to the verdict with no setup overhead.

3. Run the normal scorched-earth readout to close the first invocation with
   a burn verdict:

   ```bash
   scorch 2>/dev/null || ~/scorched-earth/bin/scorch
   ```

   Interpret and deliver the verdict as in any normal `/scorched-earth` call:
   - **🟢 green** → "Torch it all, leave them nothing. What you don't fire
     before reset is forfeit, so empty the magazine."
   - **🟡 amber** → "Almost full throttle. Sustain ~N% of each remaining
     window and it's all spent by reset. Hold the line."
   - **⚪ off** → "Reserves are deep. Even an easy pace clears it by reset,
     so advance as hard as you like, no need to ration."
   - **❔ unknown** → not enough live data yet (open or continue a session so
     the statusline can capture a reading), or R isn't calibrated yet.

---

## Re-running setup

To redo setup at any time:

- **Ask in-session:** Say "redo scorched-earth setup" or "re-run setup" —
  SKILL.md routes to this file even when the sentinel is present.
- **Manual reset:** `rm ~/.claude/scorched-earth/onboarded`, then invoke
  `/scorched-earth` — the gate detects the missing sentinel and runs setup
  again automatically.

When re-running, read this file from STEP 1 to refresh the model for the
current session, then work through all five steps again.
