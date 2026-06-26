---
name: scorched-earth
description: Use when the user says 'scorch', 'scorched earth', 'burn rate', 'should I max out', 'am I wasting usage', wants to change the burn-rate statusline light style, or asks whether to go hard on Claude usage before the weekly reset. Reports whether remaining weekly budget can only be spent by maxing every remaining 5-hour window.
---

# Scorched Earth

Tells the user whether to burn 100% of their Claude usage now, because unused weekly
budget doesn't roll over. The math and data source are in the project's
`docs/the-math.md`.

## Setting the statusline light style

If the user wants to change (or is choosing for the first time) how the 🟢 light looks,
run one of these and confirm:

```bash
scorch --style fire      # 🔥 BURN IT ALL / 🟡 burn N%   (animated flames, default)
scorch --style emoji     # 🟢 BURN IT ALL / 🟡 burn N%
scorch --style text      # BURN IT ALL / burn N%         (colored words, no emoji)
scorch --style minimal   # ● green dot / ● amber dot
scorch --style off       # no statusline light (CLI / skill only)
```

When a user first installs the plugin, it's fine to ask which style they'd like and set
it for them — that's the natural place for the install-time choice.

## Other knobs

These are occasional, so handle them conversationally here rather than as separate commands.

- **Recalibrate R.** R (the fraction of the weekly cap one full 5h window burns) is
  self-measured, but the user can pin it. If they ask to set or reset it:

  ```bash
  scorch --set-r 0.06        # persist a manual R into calibration and exit
  scorch --r 0.06            # use an R for one readout only, without persisting
  ```

  Only do this if they ask. The measured value is usually better once it has data.

- **Preview the fire gradient.** If they want to see the animated flame text without
  waiting for a green verdict:

  ```bash
  scorch --fire-demo
  ```

## What to do

0. **First-run gate.** Before anything else, route as follows:

   1. **Explicit re-run request** (e.g. "redo scorched-earth setup", "re-run
      setup"): read `setup.md` from this skill's own directory (the same directory
      this SKILL.md lives in); if you can't locate it there, try
      `~/scorched-earth/skills/scorched-earth/setup.md`. It ends with the normal
      readout — stop following these steps, setup.md takes over from here.
   2. **Otherwise**, check the sentinel:

      ```bash
      test -f ~/.claude/scorched-earth/onboarded && echo onboarded || echo first-run
      ```

      - **`first-run`**: read and follow setup.md (same path instructions as
        above).
      - **`onboarded`**: continue with step 1 below.

1. Run the CLI and show its output verbatim (it reads the live snapshot the statusline
   caches at `~/.claude/scorched-earth/state.json`):

   ```bash
   scorch 2>/dev/null || ~/scorched-earth/bin/scorch
   ```

2. Summarize the verdict in one line:
   - **🟢 green** → "Torch it all, leave them nothing. What you don't fire before reset is forfeit, so empty the magazine."
   - **🟡 amber** → "Almost full throttle. Sustain ~N% of each remaining window and it's all spent by reset. Hold the line."
   - **⚪ low (no rush)** → "Reserves are deep. Even an easy pace clears it by reset, so advance as hard as you like, no need to ration."
   - **off (budget spent)** → "Mission accomplished, burned to the last drop. Nothing left to ration until the weekly reset."
   - **❔ unknown** → not enough live data yet (open or continue a session so the
     statusline can capture a reading), or R isn't calibrated yet.

3. If the user is outside a Claude Code session or there's no cached snapshot, offer the
   manual form:

   ```bash
   scorch --weekly-left 62 --weekly-reset 11h --window 80 --window-reset 1h
   ```

## The sitrep (HTML report)

If the user wants the full visual dashboard — the 8-bit war / scorched-earth crop-field
HUD with the pixel farm and burn-mode fire — generate it with the `/sitrep` command, or
directly:

```bash
scorch --sitrep 2>/dev/null || ~/scorched-earth/bin/scorch --sitrep
```

It writes a self-contained HTML file and opens it in the browser. Same data source as the
CLI; it just recomputes the verdict + forecast live and renders them.

## Notes

- The 🟢 light is the *guaranteed* signal: you literally cannot spend your weekly budget
  unless you max every remaining window.
- The forecast/preemptive signal (based on the user's habitual pace) is softer. It flags
  that *at their usual rate* they'll leave credit on the table, even if maxing is still
  technically possible. Call it out as a heads-up, not a guarantee.
- Don't invent numbers. Only report what `scorch` prints.
