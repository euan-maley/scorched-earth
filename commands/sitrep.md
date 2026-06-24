---
description: Generate and open the Scorched Earth HTML sitrep (8-bit war / scorched-earth crop-field HUD)
argument-hint: "[output path]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*)
---

Generate the Scorched Earth **sitrep** — the self-contained HTML situation report
(8-bit war / scorched-earth crop-field HUD: a Stardew-style pixel farm with a
LAST WEEK / AVERAGE / THIS WEEK toggle, the war-HUD stats, and the green-status
burn-mode fire). It recomputes the verdict and forecast live from the snapshot the
statusline caches at `~/.claude/scorched-earth/state.json`.

Run it (the second form is the fallback if `scorch` isn't on PATH):

```bash
scorch --sitrep $ARGUMENTS 2>/dev/null || ~/scorched-earth/bin/scorch --sitrep $ARGUMENTS
```

`scorch --sitrep` writes the HTML and opens it in the browser; pass a path argument to
write somewhere specific, or add `--no-open` to skip auto-opening.

Then:

- Report the path it printed (`Sitrep written to <path>`).
- If it errors with a "no reading yet" message, tell the user to open or continue a
  Claude Code session so the statusline can capture a live snapshot first — the sitrep
  deliberately refuses to fabricate a zeros dashboard before there's real data.
- Don't invent numbers; only relay what the command prints.
