# A visible "no rush" tier for the statusline (split the overloaded `off` level)

**Date:** 2026-06-25
**Scope:** The weekly-burn signal — `core.py`, `statusline.py`, `report.py`, `bin/scorch`,
and their tests. No COA changes. `core.py` stays pure/stdlib (statusline hot path).

## Problem

The statusline only renders two of the three verdict tiers. `token()` (statusline.py:54)
returns an empty string for `off`/`unknown`, so when the user has plenty of budget and
plenty of time — e.g. right after a weekly reset — the bar goes **blank**. There's no
positive "you're fine, no rush" signal; absence reads the same as "plugin not working."

Underneath, `compute()` overloads the `off` level for two **opposite** states:

- **deep reserves** (`target < AMBER_THRESHOLD`, core.py:172) — lots of budget + time. This
  is the "no rush" state the user wants surfaced.
- **budget exhausted** (`weekly_left <= 0.5`, core.py:146) — nothing left to burn.

Because both are `off`, they share one banner — and `HEADLINE["off"]` is *"Well stocked.
Burn at whatever pace suits you."*, which is **wrong for the exhausted case** (it says
"well stocked" when you're empty). So this isn't just a display gap; the overload is a
latent correctness bug.

## Goals

1. Surface a **visible lowest tier** on the statusline reading **`⚪ no rush`**.
2. **Disambiguate** deep-reserves from budget-exhausted so each gets its true voice.
3. Keep the three actionable tiers as a clean ladder: **`low` → `amber` → `green`**.
4. Preserve the engine's purity and the "statusline never errors" invariant.

## Non-goals

- No change to amber or green wording/behavior (user confirmed: keep `🟡 burn N%`).
- No threshold changes. The deep-reserve / amber boundary stays `AMBER_THRESHOLD` (0.70);
  the green boundary stays `GREEN_THRESHOLD` (1.0).
- No new styles or config. The five existing light styles each gain a `low` rendering.

## The model change

Split the overloaded `off` into two distinct levels. Final enum:
**`green` | `amber` | `low` | `off` | `unknown`**.

- **`low`** — *deep reserves / no rush.* Returned where core.py:172 currently returns `off`
  (the `target < AMBER_THRESHOLD` else-branch). Budget remains and even a relaxed pace
  clears it by reset.
- **`off`** — *budget exhausted / terminal.* Returned where core.py:146 currently returns
  `off` (`weekly_left <= 0.5`). Mission accomplished; nothing left to burn.
- `green`, `amber`, `unknown` — unchanged.

`HEADLINE` (core.py:24) gains a `low` entry and `off` is corrected:

- `HEADLINE["low"]` = `"Well stocked. Burn at whatever pace suits you."` (moved from the old
  `off` — it was always the deep-reserve voice).
- `HEADLINE["off"]` = a true exhausted-state banner, consistent with the existing reason at
  core.py:148 (e.g. `"Mission accomplished. Burned to the last drop."`).

The two `reason` strings already differ correctly (core.py:148 vs 173); only the `level`
they carry and the shared `HEADLINE` need to change.

## Statusline rendering (statusline.py)

`token()` gains a `low` case for each style. The `low` token is low-key (dim), not green —
green stays reserved for "burn." Exhausted (`off`) and `unknown` continue to render nothing,
and the `off` *style* (no statusline at all) is unchanged.

| Style | `low` token |
|-------|-------------|
| fire | `⚪ {DIM}no rush{RESET}` (no flame) |
| emoji | `⚪ {DIM}no rush{RESET}` |
| text | `{DIM}no rush{RESET}` (no glyph) |
| minimal | `{DIM}●{RESET}` (dim dot) |

`DIM = "\033[2m"` (matches the dim already used in `bin/scorch`). Add `"low"` keys to the
`STYLES` dict for emoji/text/minimal and a branch in the `fire` path, mirroring how `green`
and `amber` are handled. `green`/`amber` branches are untouched.

## CLI + sitrep (bin/scorch, report.py)

- `bin/scorch`: add `"low"` to `LIGHT` (`⚪`) and `COLOR` (dim `\033[2m`). The headline comes
  from the shared `HEADLINE`, so the corrected banners flow through automatically. `off`
  keeps `⚪` (the exhausted case is rare; the headline text distinguishes it).
- `report.py`: add `"low"` to `STATUS_COLOR` (a calm tone — reuse the old `off` olive
  `#8a9a3c`); give `off` a greyer exhausted tone (`#6f8a8a`). The sitrep banner reads
  `HEADLINE[level]` + `STATUS_COLOR[level]`, so both update with no template change.

## Error handling / edge cases

- **Unknown level fallthrough.** All consumer dicts use `.get(level, <default>)` already, so
  an unmapped level can't crash; we add the `low` keys so it never falls back.
- **`off` as catch-all.** After the split, the only paths to `off` are the explicit
  exhausted branch and any future addition — deep reserves no longer land there.
- **Invariant preserved.** `token()` still returns `""` for anything it doesn't render, and
  `main()` still swallows exceptions → the bar degrades to empty, never errors.

## Testing

Extend `tests/test_scorched.py`:

1. **Deep reserves → `low`.** A snapshot with high `weekly_left` and many `windows_left`
   (so `target < 0.70`) now asserts `level == "low"` (was `"off"`). Update any existing
   deep-reserve assertions accordingly.
2. **Exhausted → `off`.** `weekly_left <= 0.5` asserts `level == "off"` and that
   `HEADLINE["off"]` reads as exhausted (not "well stocked").
3. **Statusline token.** `token(low_rec, style)` returns a non-empty `no rush` string for
   fire/emoji/text and a dot for minimal; returns `""` for an `off` (exhausted) rec.
4. **Banner correctness regression.** Assert `HEADLINE["low"] != HEADLINE["off"]` and that
   the exhausted banner doesn't contain "well stocked" — pins the latent bug closed.

The other three suites (advisor/runner/cockpit) don't touch `level` semantics and stay green.

## Doc impact

- `docs/the-math.md` — the verdict now has a named `low`/"no rush" tier distinct from the
  exhausted state; describe the 5-state enum.
- `CLAUDE.md` — no architecture-line change (no new module); the level enum note lives in
  the math doc.
- `README.md` — if it lists the light states, add `⚪ no rush`.
- `TODO.md` — session close-out.
