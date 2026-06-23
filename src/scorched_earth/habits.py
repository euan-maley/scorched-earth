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


def forecast(history: List[dict], now: int, current_used: float, weekly_reset: int) -> Forecast:
    """Project end-of-week usage from habits. current_used = seven_day used %, 0..100."""
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
        days_elapsed = max(0.25, (now - start_of_week) / DAY_SECONDS)
        rate_per_day = current_used / days_elapsed
        days_left = seconds_left / DAY_SECONDS
        expected_remaining = rate_per_day * days_left
        confidence = "low"
        basis = "linear estimate (building day-of-week profile)"

    projected_end = min(100.0, current_used + expected_remaining)
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


def _consumed_today(history: List[dict], now: int, current_used: float) -> float:
    """How much weekly budget was consumed since the start of today (best effort)."""
    today = _day_key(now)
    firsts = [o["used"] for o in history if _day_key(o["ts"]) == today]
    if not firsts:
        return 0.0
    return max(0.0, current_used - min(firsts))
