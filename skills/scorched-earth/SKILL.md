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

## What to do

1. Run the CLI and show its output verbatim (it reads the live snapshot the statusline
   caches at `~/.claude/scorched-earth/state.json`):

   ```bash
   scorch 2>/dev/null || ~/scorched-earth/bin/scorch
   ```

2. Summarize the verdict in one line:
   - **🟢 green** → "Torch it all, leave them nothing. What you don't fire before reset is forfeit, so empty the magazine."
   - **🟡 amber** → "Almost full throttle. Sustain ~N% of each remaining window and it's all spent by reset. Hold the line."
   - **⚪ off** → "Reserves are deep. Even an easy pace clears it by reset, so advance as hard as you like, no need to ration."
   - **❔ unknown** → not enough live data yet (open or continue a session so the
     statusline can capture a reading), or R isn't calibrated yet.

3. If the user is outside a Claude Code session or there's no cached snapshot, offer the
   manual form:

   ```bash
   scorch --weekly-left 62 --weekly-reset 11h --window 80 --window-reset 1h
   ```

## Notes

- The 🟢 light is the *guaranteed* signal: you literally cannot spend your weekly budget
  unless you max every remaining window.
- The forecast/preemptive signal (based on the user's habitual pace) is softer. It flags
  that *at their usual rate* they'll leave credit on the table, even if maxing is still
  technically possible. Call it out as a heads-up, not a guarantee.
- Don't invent numbers. Only report what `scorch` prints.
