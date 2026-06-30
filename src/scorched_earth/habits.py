"""Learn the user's usage habits and forecast where the week is headed.

The hard 🟢 light is certain but late. Most people never max every window, so this
module asks the softer, earlier question: *at your habitual pace, are you trending to
leave weekly budget unused?* If so, nudge preemptively while there's still time to act.

It builds a day-of-week consumption profile from a rolling history of weekly-usage
observations, then projects end-of-week usage. Pure functions; I/O lives in state.py.

Cold start: with little history it falls back to a linear projection (provisional) and
sharpens as the per-day profile fills in over a few weeks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

WEEK_SECONDS = 7 * 24 * 3600
DAY_SECONDS = 24 * 3600

MAX_OBS = 1200            # ~50 days of hourly observations
LEFTOVER_MARGIN = 8.0     # project to leave > this % unused -> preemptive nudge
MIN_DAY_SAMPLES = 5       # day-of-week samples needed before trusting the DOW profile


@dataclass
class Forecast:
    projected_end_used: Optional[float] = None   # % of weekly budget you'll have used at reset
    projected_leftover: Optional[float] = None   # % you'll leave unused
    expected_remaining: Optional[float] = None   # % you'll still consume from now to reset
    preemptive: bool = False                     # True -> worth nudging early
    confidence: str = "none"                     # none | low | medium | high
    basis: str = ""                              # human note on how it was derived
    weeks_observed: int = 0


# --- helpers --------------------------------------------------------------------

def _dow_hour(ts: int) -> tuple[int, int]:
    lt = time.localtime(ts)
    return lt.tm_wday, lt.tm_hour  # Monday=0


def _day_key(ts: int) -> str:
    lt = time.localtime(ts)
    return f"{lt.tm_year}-{lt.tm_yday}"


def record_observation(history: List[dict], snap_dict: dict) -> List[dict]:
    """Append a weekly-usage observation, bucketed to ~hourly, trimmed to MAX_OBS.

    Keeps cross-week history (unlike the calibration samples, which reset weekly) so the
    day-of-week profile can accumulate.
    """
    used = snap_dict.get("seven_day_pct")
    reset = snap_dict.get("seven_day_reset")
    ts = snap_dict.get("now")
    if used is None or reset is None or ts is None:
        return history

    out = list(history)
    dow, hour = _dow_hour(ts)
    if out:
        last = out[-1]
        same_bucket = (
            last.get("seven_day_reset") == reset
            and last.get("dow") == dow
            and last.get("hour") == hour
        )
        # Within the same hour bucket, just keep the latest reading (update in place)
        # unless usage barely moved.
        if same_bucket:
            if abs((last.get("used") or 0) - used) < 0.1:
                return out
            out[-1] = {**last, "ts": ts, "used": used}
            return out

    out.append({"ts": ts, "used": used, "seven_day_reset": reset, "dow": dow, "hour": hour})
    if len(out) > MAX_OBS:
        out = out[-MAX_OBS:]
    return out


def _daily_consumption(history: List[dict]) -> List[dict]:
    """Per calendar-day consumption, tagged with day-of-week.

    Weekly `used` is monotonic within a weekly cycle, so we sum the positive deltas
    between consecutive observations and attribute each increment to the day of the later
    observation. This captures overnight jumps and works even with one reading per day.
    """
    weeks: dict = {}
    for o in history:
        weeks.setdefault(o["seven_day_reset"], []).append(o)

    by_day: dict = {}  # (reset, day_key) -> {dow, consumed}
    for reset, obs in weeks.items():
        obs = sorted(obs, key=lambda x: x["ts"])
        prev = None
        for o in obs:
            if prev is not None:
                delta = max(0.0, o["used"] - prev["used"])
                k = (reset, _day_key(o["ts"]))
                rec = by_day.setdefault(k, {"dow": o["dow"], "consumed": 0.0})
                rec["consumed"] += delta
            prev = o
    return [{"dow": rec["dow"], "consumed": rec["consumed"]} for rec in by_day.values()]


def dow_profile(history: List[dict]) -> dict:
    """Average daily consumption (% of weekly budget) per day-of-week, with sample counts."""
    days = _daily_consumption(history)
    sums: dict = {}
    counts: dict = {}
    for d in days:
        sums[d["dow"]] = sums.get(d["dow"], 0.0) + d["consumed"]
        counts[d["dow"]] = counts.get(d["dow"], 0) + 1
    avg = {dow: sums[dow] / counts[dow] for dow in sums}
    return {"avg": avg, "counts": counts, "day_samples": len(days)}


def _weeks_observed(history: List[dict]) -> int:
    return len({o["seven_day_reset"] for o in history})


def forecast(history: List[dict], now: int, current_used: float, weekly_reset: int,
             max_burnable: float = None) -> Forecast:
    """Project end-of-week usage from habits. current_used = seven_day used %, 0..100.

    `max_burnable` (% of weekly you could physically still spend before reset, from the
    recommendation) caps the projection: you can't burn more than capacity allows, so the
    leftover is never understated."""
    if weekly_reset is None or now is None or current_used is None:
        return Forecast(basis="no weekly data")

    weekly_left = max(0.0, 100.0 - current_used)
    seconds_left = max(0, weekly_reset - now)
    if seconds_left <= 0:
        return Forecast(projected_end_used=current_used, projected_leftover=weekly_left,
                        expected_remaining=0.0, basis="week is over")

    prof = dow_profile(history)
    weeks = _weeks_observed(history)

    # Enough per-day signal -> use the day-of-week profile; else linear fallback.
    if prof["day_samples"] >= MIN_DAY_SAMPLES and prof["avg"]:
        avg = prof["avg"]
        overall = sum(avg.values()) / len(avg)  # fill gaps for days never observed
        expected_remaining = 0.0
        cursor = now
        # Today: only the unspent remainder of today's typical consumption.
        dow_now, _ = _dow_hour(now)
        today_typical = avg.get(dow_now, overall)
        today_done = _consumed_today(history, now, current_used)
        frac_day_left = _fraction_of_day_left(now)
        expected_remaining += min(max(0.0, today_typical - today_done),
                                  today_typical * frac_day_left)
        # Whole future days until the reset day, plus the partial reset day.
        cursor = _start_of_next_day(now)
        while cursor < weekly_reset:
            dow, _ = _dow_hour(cursor)
            day_typical = avg.get(dow, overall)
            day_end = cursor + DAY_SECONDS
            if day_end <= weekly_reset:
                expected_remaining += day_typical
            else:
                frac = (weekly_reset - cursor) / DAY_SECONDS
                expected_remaining += day_typical * frac
            cursor = day_end
        confidence = "high" if weeks >= 3 else "medium"
        basis = "day-of-week profile"
    else:
        # Linear: average rate so far this week, projected to the reset.
        start_of_week = weekly_reset - WEEK_SECONDS
        days_elapsed = (now - start_of_week) / DAY_SECONDS
        if days_elapsed < 1.0:
            # Too little of the cycle elapsed to extrapolate a daily rate (or a clock-skew /
            # >7d reset that puts the cycle start in the future). Extrapolating here either
            # inflates the rate ~N× or goes negative, so don't project a forfeit — assume the
            # budget gets spent and hold the nudge until there's a real day of signal.
            return Forecast(
                projected_end_used=current_used, projected_leftover=weekly_left,
                expected_remaining=weekly_left, preemptive=False, confidence="low",
                basis="too early in the cycle to forecast", weeks_observed=weeks,
            )
        rate_per_day = current_used / days_elapsed
        days_left = seconds_left / DAY_SECONDS
        expected_remaining = rate_per_day * days_left
        confidence = "low"
        basis = "linear estimate (building day-of-week profile)"

    # You can't burn more than you have, nor more than the windows physically allow.
    cap = weekly_left if max_burnable is None else min(weekly_left, max_burnable)
    expected_remaining = min(expected_remaining, cap)
    projected_end = current_used + expected_remaining
    projected_leftover = max(0.0, 100.0 - projected_end)
    # Preemptive only if you're trending to waste a meaningful slice AND there's still
    # runway to do something about it.
    preemptive = (
        projected_leftover > LEFTOVER_MARGIN
        and weekly_left > LEFTOVER_MARGIN
        and seconds_left > 2 * 3600
    )
    return Forecast(
        projected_end_used=projected_end,
        projected_leftover=projected_leftover,
        expected_remaining=expected_remaining,
        preemptive=preemptive,
        confidence=confidence,
        basis=basis,
        weeks_observed=weeks,
    )


def _fraction_of_day_left(now: int) -> float:
    lt = time.localtime(now)
    secs_into_day = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    return max(0.0, (DAY_SECONDS - secs_into_day) / DAY_SECONDS)


def _start_of_next_day(now: int) -> int:
    lt = time.localtime(now)
    secs_into_day = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    return now - secs_into_day + DAY_SECONDS


DOWCODE = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _day_start(t: int) -> int:
    lt = time.localtime(t)
    return t - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)


def active_hours(history: List[dict]) -> tuple[float, bool]:
    """Estimate how many hours a day you're actually around to burn, from when the statusline
    fires (history covers an hour-of-day only when you're in Claude that hour). Returns
    (hours, provisional). Falls back to 16h (assume 8h sleep) until there's enough history."""
    if len(history) < 12:
        return 16.0, True
    if len({_day_key(o["ts"]) for o in history}) < 3:
        return 16.0, True
    hrs = len({time.localtime(o["ts"]).tm_hour for o in history})
    return float(max(4, min(24, hrs))), False


def active_fraction(history: List[dict]) -> float:
    """Fraction of the day you can actually burn (usable windows = raw windows x this)."""
    return active_hours(history)[0] / 24.0


def recent_per_window(history: List[dict], now: int, current_used: Optional[float],
                      weekly_reset: Optional[int], active_hours_per_day: float,
                      lookback_days: float = 2.0) -> Optional[float]:
    """Measured *recent* burn, in % of the weekly budget per 5h window. Feeds core's
    "hold your fire" check. Returns None (so the warning can't fire) when history is too thin.

    Primary: actual consumption over the trailing `lookback_days` within the current weekly
    cycle. Fallback: today's burn so far, extrapolated across the elapsed part of the day,
    when there's under ~half a day of trailing signal. Never reads I/O; pure over `history`."""
    if (current_used is None or weekly_reset is None or now is None
            or not active_hours_per_day or active_hours_per_day <= 0):
        return None
    windows_per_day = active_hours_per_day / 5.0
    if windows_per_day <= 0:
        return None
    rate_per_day = None
    cur = sorted((o for o in history
                  if o.get("seven_day_reset") == weekly_reset and o.get("ts") is not None),
                 key=lambda o: o["ts"])
    if cur:
        cutoff = now - lookback_days * DAY_SECONDS
        trailing = [o for o in cur if o["ts"] >= cutoff] or cur
        base = trailing[0]
        elapsed = (now - base["ts"]) / DAY_SECONDS
        if elapsed >= 0.5:
            rate_per_day = max(0.0, current_used - base["used"]) / elapsed
    if rate_per_day is None:
        consumed_today = _consumed_today(history, now, current_used)
        elapsed_today = 1.0 - _fraction_of_day_left(now)
        if elapsed_today >= 0.25 and consumed_today > 0:
            rate_per_day = consumed_today / elapsed_today
    if not rate_per_day or rate_per_day <= 0:
        return None
    return rate_per_day / windows_per_day


def average_days(history: List[dict]) -> List[dict]:
    """7 plots (Mon..Sun) of your all-time average burn per weekday."""
    avg = dow_profile(history).get("avg", {})
    return [{"code": DOWCODE[i], "pct": (round(avg[i]) if i in avg else None)} for i in range(7)]


def _week_consumption_by_dow(history: List[dict], reset) -> dict:
    """Sum of burn per weekday within a single weekly cycle (the one with `reset`)."""
    obs = sorted((o for o in history if o["seven_day_reset"] == reset), key=lambda x: x["ts"])
    by, prev = {}, None
    for o in obs:
        if prev is not None:
            by[o["dow"]] = by.get(o["dow"], 0.0) + max(0.0, o["used"] - prev["used"])
        prev = o
    return by


def last_completed_reset(history: List[dict], current_reset):
    """The weekly-reset value of the most recent week strictly before the current one."""
    resets = sorted({o["seven_day_reset"] for o in history})
    prior = [r for r in resets if current_reset is None or r < current_reset]
    return prior[-1] if prior else None


def week_days(history: List[dict], reset) -> List[dict]:
    """7 plots of actual burn per weekday for one specific week (None = unobserved)."""
    if reset is None:
        return [{"code": c, "pct": None} for c in DOWCODE]
    by = _week_consumption_by_dow(history, reset)
    observed = {o["dow"] for o in history if o["seven_day_reset"] == reset}
    return [{"code": DOWCODE[i], "pct": (round(by.get(i, 0.0)) if i in observed else None)}
            for i in range(7)]


def _projected_state(weekly_left_at_day: float, secs_to_reset: int, r: float,
                     active_fraction: float = 1.0) -> str:
    """Soil state for a future day, from the burn STATUS you're projected to be in that day.
    Mirrors core.compute's thresholds: scorched-earth -> charred, on-the-fence -> wheat,
    plenty/no-limit -> lush green. Windows are discounted by active_fraction (sleep)."""
    if weekly_left_at_day <= 0.5:
        return "lush"                      # nothing left to burn; no pressure
    windows = (secs_to_reset / (5 * 3600)) * active_fraction
    if windows <= 0:
        return "charred"                   # reset imminent, budget remains -> burn it
    target = (weekly_left_at_day / windows) / (r * 100)
    if target >= 1.0:
        return "charred"                   # can't spend it all even maxed -> scorched earth
    if target >= 0.70:
        return "golden"                    # on the fence -> wheat
    return "lush"                          # plenty of runway -> green grass


def current_week_days(history: List[dict], reset, now: int, r=None, weekly_left=None,
                      active_fraction: float = 1.0) -> List[dict]:
    """7 plots for the CURRENT week: actual burn for elapsed days, and for days still ahead a
    projection. When r + weekly_left are given, each future day also carries a `state` set from
    the burn STATUS you're estimated to be in that day (charred = scorched-earth/should-burn,
    golden = on the fence, lush = no limit). Each entry carries kind=actual|today|projected."""
    if reset is None:
        return [{"code": c, "pct": None, "kind": "projected"} for c in DOWCODE]
    avg = dow_profile(history).get("avg", {})
    by = _week_consumption_by_dow(history, reset)
    observed = {o["dow"] for o in history if o["seven_day_reset"] == reset}
    start = reset - WEEK_SECONDS
    nd = _day_start(now)
    out: List = [None] * 7
    proj_spent = 0.0  # cumulative projected burn on prior future days (drains the reserve)
    for off in range(7):
        ts = start + off * DAY_SECONDS + 12 * 3600
        dow = _dow_hour(ts)[0]
        td = _day_start(ts)
        if td < nd:
            pct = round(by.get(dow, 0.0)) if dow in observed else 0
            out[dow] = {"code": DOWCODE[dow], "pct": pct, "kind": "actual"}
        elif td == nd:
            out[dow] = {"code": DOWCODE[dow], "pct": round(by.get(dow, 0.0)), "kind": "today"}
        else:
            a = avg.get(dow)
            day = {"code": DOWCODE[dow], "pct": (None if a is None else round(a)), "kind": "projected"}
            if r and weekly_left is not None:
                wlft = max(0.0, weekly_left - proj_spent)
                day["state"] = _projected_state(wlft, max(0, reset - td), r, active_fraction)
                proj_spent += (a or 0.0)
            out[dow] = day
    return [out[i] or {"code": DOWCODE[i], "pct": None, "kind": "projected"} for i in range(7)]


def _consumed_today(history: List[dict], now: int, current_used: float) -> float:
    """How much weekly budget was consumed since the start of today (best effort)."""
    today = _day_key(now)
    firsts = [o["used"] for o in history if _day_key(o["ts"]) == today]
    if not firsts:
        return 0.0
    return max(0.0, current_used - min(firsts))
