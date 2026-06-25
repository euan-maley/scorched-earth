# The Math

## Inputs (live, per statusline refresh)

| Symbol | Source | Meaning |
|--------|--------|---------|
| `h`        | `rate_limits.five_hour.used_percentage` | % of the current 5h window used |
| `h_reset`  | `rate_limits.five_hour.resets_at`       | unix s when the 5h window resets |
| `w`        | `rate_limits.seven_day.used_percentage` | % of the weekly budget used |
| `w_reset`  | `rate_limits.seven_day.resets_at`        | unix s when the weekly budget resets |
| `now`      | clock                                    | current unix s |

Window length `L = 5h = 18000s`.

## Derived quantities

**Weekly budget remaining (% of weekly):**

```
weekly_left = 100 − w
```

**Windows of capacity left before the weekly reset.** The current window is partly
spent; after it resets, full windows tick by until the weekly reset:

```
windows_left = (100 − h)/100  +  max(0, w_reset − h_reset) / L
```

The first term is the unused capacity of the *current* window (in window-units); the
second is how many further windows of time remain before the weekly reset. Their sum
is fractional window-capacity remaining.

## The unknown: R

`h` and `w` are percentages of *different* caps. To compare them we need **R** =
fraction of the **weekly** cap that one full 5h window consumes.

```
one full window  =  R  of the weekly budget   (e.g. R = 0.07 → a maxed window burns 7% of the week)
```

R is a **constant for a plan** (the ratio of the 5h cap to the weekly cap; Claude
exposes no per-model bucket, so both percentages share one underlying unit). We don't
hardcode it — we **measure** it from the user's own data: across two snapshots where
the 5h window didn't reset, `Δw / Δh` (with Δh in window-units) estimates R. A rolling
median over clean samples is stable and self-correcting. See `calibrate.py`.

Until enough samples exist, R is provisional and falls back to **`DEFAULT_R = 0.05`** (a
maxed window ≈ 5% of the week, ~20 windows/week); the readout marks it provisional and can
ask the user for a starting value (their plan, or observed "windows per week at full burn" =
1/R). The worked example below uses `R = 0.07` for round numbers, not the default.

### Caveat: one bucket assumption

The model treats the weekly `used_percentage` as a single budget with a single R. On plans
with **multiple weekly limits** (e.g. Max's separate all-models and Sonnet-only caps, plus
Opus budgets), the statusline reports one binding percentage that can switch which underlying
cap it tracks (e.g. when you change models). If the binding bucket changes mid-week, `Δw/Δh`
mixes two caps and R degrades. The guardrails (in-band filter + `MIN_PAIRS`) blunt this, and a
wrong R surfaces as a provisional/odd readout rather than silent confidence, but treat the
green light as advisory on multi-bucket plans rather than gospel.

## The recommendation

**Per-window burn target** — to spend the remaining weekly budget evenly across the
remaining windows, each window should consume this fraction of one 5h window:

```
target_per_window = (weekly_left / windows_left) / (R × 100)     # as a fraction of a 5h window
```

- `target_per_window ≥ 1.0` → **🟢 GREEN, scorched earth.** You cannot spend your
  remaining weekly budget even by maxing every remaining window. Pacing wastes
  credits — burn 100% every window.
- `0.70 ≤ target_per_window < 1.0` → **🟡 AMBER.** Burn hard; you're close to the line.
- `target_per_window < 0.70` → **low (no rush) / off.**
  - **`low`** — deep reserves and plenty of time; the statusline shows `⚪ no rush`. No
    urgency; pace normally.
  - **`off`** — budget-exhausted terminal state: weekly budget is spent, no credits left.

The verdict `level` enum is therefore five states: `green | amber | low | off | unknown`.

Equivalent green condition without dividing by zero risk:

```
green  ⇔  weekly_left ≥ windows_left × R × 100
```

i.e. remaining weekly budget exceeds the most you could possibly burn in the windows
you have left.

## Worked example

Plan where a maxed window burns ~7% of the week (`R = 0.07`).

- `w = 38` → `weekly_left = 62`
- `h = 80`, current window resets in ~1h; weekly resets in ~11h.
- `windows_left = (100−80)/100 + (11h−1h)/5h = 0.20 + 2.0 = 2.2` windows
  (the tail counts time *after* the current window resets, so 10h not 11h).
- max burnable = `2.2 × 0.07 × 100 = 15.4%` of the week, but you have `62%` left.
- `62 ≥ 15.4` → **GREEN.** Even maxing every remaining window leaves ~47% of your
  weekly budget unused, so there is zero reason to pace. Go scorched earth.

## The forecast layer (preemptive nudge)

The 🟢 light above is *certain* but late — it only fires when maxing out is the
**only** way to spend the budget. In practice almost nobody uses 100% of every window,
so a second, earlier signal asks: **at your habitual pace, are you trending to leave
budget unused?** (See `habits.py`.)

We keep a rolling, cross-week history of weekly-usage observations and learn a
**day-of-week consumption profile** — how much of the weekly budget you typically burn
on a Monday, a Saturday, etc. Then we project the rest of this week:

```
projected_end = current_used + Σ (typical consumption for each remaining day, by day-of-week)
projected_leftover = 100 − projected_end
```

The current day counts only its *unspent* typical remainder; the day the weekly window
resets counts only the fraction before the reset.

- **Cold start:** with < ~5 day-samples we fall back to a **linear** projection (average
  rate so far this week × days left) and mark it `low` confidence. It sharpens to
  `medium`/`high` as the day-of-week profile fills in over a few weeks.
- **Preemptive nudge** fires when `projected_leftover > 8%` **and** there's still
  meaningful runway (`weekly_left > 8%`, more than ~2h left). Surfaced as a 🔥 line in
  the `scorch` readout always, and as a **once-per-week desktop notification** only once
  confidence is `medium`+ (so we don't nudge on a noisy week-1 guess).

This is a forecast, not a guarantee — the 🟢 light remains the certain signal; the 🔥
nudge is the "you'll probably waste credit if you keep coasting" heads-up.
