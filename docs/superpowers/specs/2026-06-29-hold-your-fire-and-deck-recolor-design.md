# Design: "hold your fire" state + deck rename/recolor

Date: 2026-06-29
Status: approved (brainstormed with user), ready for implementation plan.

## Summary

Add a fifth burn signal, **hold your fire** (an "ease off" warning for when you are
on pace to exhaust the weekly budget early and sit locked out), and rename + recolor the
whole signal deck so every state is a marksmanship call with its own color and glyph.

This is the missing pole of the model: today every state pushes you to burn more (you are
probably under-using). Nothing warns about the opposite failure, burning out early and
forfeiting *time*. `hold your fire` fills it.

## The deck (final)

| Key (new) | Old key | Token | Color | Glyph | Headline |
|-----------|---------|-------|-------|-------|----------|
| `max`    | green   | BURN IT ALL | red (animated fire in fire style) | 🔥 | "Torch it all. Leave them nothing." |
| `push`   | amber   | clear shot, take it | green | 🟢 | "Clear shot, take it. Sustain ~N% a window and it's all spent by reset." |
| `steady` | low     | eyes on the target | white | ⚪ (🎯 in fire style) | "Eyes on the target. Dead on pace to spend it all, hold steady." |
| `ease`   | (new)   | hold your fire | yellow (caution) | ⚠️ | "Hold your fire. Save rounds for tomorrow or you'll run dry before reinforcements." |
| `done`   | off     | good job, soldier | purple (Purple Heart) | 🎖️ | "Good job, soldier. Burned to the last drop, rest up for reinforcements." |
| `unknown`| unknown | (blank) | n/a | n/a | "No read yet. Hold your horses." |

Notes:
- The deck reads as a firing ladder: `hold your fire` (off the trigger) -> `eyes on the
  target` (steady, on pace) -> `clear shot, take it` (engage) -> `BURN IT ALL` (unload).
  `good job, soldier` is the after-action praise (not a firing command, so it sits outside
  the ladder deliberately). Purple + medal = Purple Heart: the soldier who gave everything.
- **Behavior change:** `done` now PRINTS its token (`good job, soldier`) until the weekly
  reset, instead of the current blank statusline. `unknown` stays blank.
- `push` (old amber) drops the live `burn N%` token in favor of the vibe token; the precise
  N% moves into the headline/reason, where it already lives.

## The new state: trigger math

`hold your fire` fires when, at your *recent actual rate*, you would run the weekly budget
dry meaningfully before the reset, leaving usable windows stranded.

Computed in the model's native unit, windows-left (`wl`, which `core.windows_left`
already produces and which already discounts sleep via `active_fraction`):

```
windows_to_dry = weekly_left / recent_per_window      # %/window actual pace
idle_windows   = wl - windows_to_dry                  # usable windows you'd be locked out of
fire `ease` when idle_windows > EASE_IDLE_WINDOWS      # default 3.0 ("Balanced")
```

Self-disengaging by construction (no special-casing of "the last window"):
- Near the reset `wl` -> 0, so `idle_windows` cannot exceed the threshold; it goes silent on
  its own. In the final day it physically cannot fire. Burn-it-all is never interrupted.
- In `max` (you couldn't spend it all even maxed), `windows_to_dry > wl`, so
  `idle_windows < 0`; mutually exclusive with `max` automatically.
- It lives in the deep-reserve zone: lots of budget + lots of time, but you are sprinting.

`EASE_IDLE_WINDOWS = 3.0` is the single "gentleness" knob (~one active day of lockout).
Twitchy ~1, Relaxed ~5; default Balanced = 3.

### Where it is computed (preserve invariants)

`core.py` stays pure/stdlib/no-I/O (hot-path invariant). `core.compute` gains one optional
param `recent_per_window: Optional[float] = None`. When supplied and the otherwise-computed
level is `push` or `steady` (never `max`/`done`), core does the `idle_windows > W` check and
returns level `ease`. The caller (`statusline.py`) computes `recent_per_window` from habits
history and passes it in. Verdict stays in one place (core); core stays pure (caller supplies
the number).

### Recent-rate data source

`habits.py` gains a pure helper for the trailing actual rate: average %/window over the last
~2 observed days (reuse `_daily_consumption`), converting %/day to %/window via active
windows/day (`active_hours/5`). Fallback to today's extrapolated rate when there is less than
~2 days of signal (reuse `_consumed_today` + `_fraction_of_day_left`). Returns `None` when
there is too little history, in which case `ease` cannot fire (degrades to `steady`).

## Rendering (statusline.py)

New ANSI palette constants: RED (`\033[1;31m`), GREEN (`\033[1;32m`), WHITE (`\033[1;37m`),
CAUTION/yellow (`\033[1;33m`), PURPLE (`\033[1;35m`). Glyphs per style:

| Style | max | push | steady | ease | done |
|-------|-----|------|--------|------|------|
| emoji | 🔥 BURN IT ALL | 🟢 clear shot, take it | ⚪ eyes on the target | ⚠️ hold your fire | 🎖️ good job, soldier |
| text | (red words) | (green words) | (white words) | (yellow words) | (purple words) |
| minimal | red ● | green ● | white ● | yellow ● | purple ● |
| fire | 🔥 animated flame BURN IT ALL | 🟢 clear shot, take it | 🎯 eyes on the target | ⚠️ hold your fire | 🎖️ good job, soldier |

`token()` returns the `ease` token whenever `rec.level == "ease"`. `done` now returns its
token instead of `""`. Minimal dots are five distinct colors (no collision).

## Surfaces that must follow the same palette ("all levels")

- `core.py`: rename level keys, `HEADLINE` dict, reason sentences; add `ease` threshold +
  `recent_per_window` param.
- `statusline.py`: palette + glyphs + `token()` + compute recent rate from habits + print
  `done`.
- `habits.py`: recent-rate helper; rename any burn-level key refs (the projected-day soil
  `_projected_state` uses its own charred/golden/lush, unrelated, leave as-is).
- `report.py` + sitrep template: recolor accents per the palette, render `ease` + renamed
  keys. (`report.py` already treats max as fire, not green.)
- `coa_report.py` / COA templates: only if they read the burn level for an accent; the DEFCON
  badges and CSS color names there are NOT burn-level keys and must NOT be renamed.
- `bin/scorch`: the CLI readout headline/colors.
- Tests: update `test_scorched.py` (level keys, headlines, tokens) and add cases for `ease`
  (fires when idle>W, silent near reset, silent in max, silent without recent rate). Do not
  touch COA test keys that are unrelated.

## Docs (rebrand to the new palette, drop "green light")

- `README.md`: replace the "A green light for Claude usage" tagline with a fire-team framing
  (e.g. "a fire-team readout for spending every token before the week resets"); document the
  five-state deck + `hold your fire`.
- `CLAUDE.md`: architecture lines (`core.py` new param + `ease`, `habits.py` recent-rate
  helper), the deck, the invariant that `core` stays pure with the rate passed in.
- `docs/the-math.md`: the `ease` trigger math (windows-idle, self-disengage, the W knob).
- `TODO.md` + `docs/playbook.md`: session close-out + Current Status.

## Invariants preserved

- `core.py` stays pure/stdlib (the recent rate is passed in, not fetched).
- The statusline still degrades to empty on any failure.
- No em/en dashes in any docs, UI strings, CLI output, or commit text.
- R remains a measured plan constant, untouched.
- The rename is scoped to the burn level only; COA/DEFCON color/badge code is left alone.

## Out of scope (v1)

- A real-time `hold your fire` notification (the once-weekly forecast nudge stays as-is; an
  ease-specific push notification can come later, rate-limited).
- Per-repo/ROE configurability of `EASE_IDLE_WINDOWS` (ship the constant first).
