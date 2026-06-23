"""Plain-stdlib tests. Run: python3 tests/test_scorched.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scorched_earth.core import Snapshot, compute, windows_left, WINDOW_SECONDS  # noqa: E402
from scorched_earth import calibrate  # noqa: E402

NOW = 1_000_000
HOUR = 3600
passed = 0


def check(name, cond):
    global passed
    assert cond, f"FAIL: {name}"
    passed += 1
    print(f"  ok  {name}")


# --- windows_left ---------------------------------------------------------------
# current window 80% used, resets in 1h; weekly resets in 11h.
snap = Snapshot(
    now=NOW,
    five_hour_pct=80, five_hour_reset=NOW + 1 * HOUR,
    seven_day_pct=38, seven_day_reset=NOW + 11 * HOUR,
)
wl = windows_left(snap)
# 0.20 (rest of current window) + tail (11h-1h)=10h / 5h = 2.0  -> 2.2
check("windows_left = 2.2", abs(wl - 2.2) < 1e-9)

# --- green: worked example (R=0.07) --------------------------------------------
rec = compute(snap, r=0.07)
check("green when weekly budget can't be burned in time", rec.level == "green")
check("burn_pct clamps to 100 on green", rec.burn_pct == 100.0)
check("max_burnable ~15.4%", abs(rec.max_burnable_weekly - 15.4) < 0.1)
check("weekly_left = 62", rec.weekly_left == 62)

# --- amber: tune R so target lands in [0.70, 1.0) ------------------------------
# target = (weekly_left/wl)/(r*100). weekly_left=62, wl=2.2 -> 28.18/(r*100).
# want ~0.85 -> r*100 = 28.18/0.85 = 33.2 -> r = 0.332
rec_amber = compute(snap, r=0.332)
check("amber band", rec_amber.level == "amber")

# --- off: lots of windows, little weekly left ----------------------------------
slack = Snapshot(
    now=NOW,
    five_hour_pct=10, five_hour_reset=NOW + 4 * HOUR,
    seven_day_pct=20, seven_day_reset=NOW + 6 * 24 * HOUR,  # ~6 days left
)
rec_off = compute(slack, r=0.05)
check("off when plenty of runway", rec_off.level == "off")
check("off burn_pct < 70", rec_off.burn_pct < 70)

# --- unknown: no weekly data ---------------------------------------------------
noweek = Snapshot(now=NOW, five_hour_pct=50, five_hour_reset=NOW + HOUR)
check("unknown without weekly bucket", compute(noweek, r=0.05).level == "unknown")
check("unknown without R", compute(snap, r=None).level == "unknown")

# --- weekly reset imminent but budget remains -> burn now ----------------------
imminent = Snapshot(
    now=NOW,
    five_hour_pct=100, five_hour_reset=NOW + 30,
    seven_day_pct=40, seven_day_reset=NOW + 30,
)
check("imminent reset with budget -> green", compute(imminent, r=0.05).level == "green")

# --- calibration: recover R from synthetic burn --------------------------------
# Same window & week; weekly rises 0.7pp per 10pp of window -> R should be ~0.07.
samples = []
w_reset = NOW + 7 * 24 * HOUR
h_reset = NOW + 5 * HOUR
for i in range(11):
    samples = calibrate.append_sample(
        samples,
        {
            "now": NOW + i * 600,
            "five_hour_pct": i * 10.0,
            "five_hour_reset": h_reset,
            "seven_day_pct": 30.0 + i * 0.7,
            "seven_day_reset": w_reset,
        },
    )
r_est, provisional = calibrate.estimate_r(samples)
check("R measured ~0.07", abs(r_est - 0.07) < 1e-6)
check("R not provisional with enough pairs", provisional is False)

# weekly reset rolls -> samples reset
rolled = calibrate.append_sample(
    samples,
    {"now": NOW + 999999, "five_hour_pct": 5.0, "five_hour_reset": h_reset + 1,
     "seven_day_pct": 2.0, "seven_day_reset": w_reset + 1},
)
check("weekly rollover clears old samples", len(rolled) == 1)

# no samples -> provisional default
r_def, prov_def = calibrate.estimate_r([])
check("fallback R is provisional", prov_def is True and r_def == calibrate.DEFAULT_R)

# --- habits / forecast ---------------------------------------------------------
from scorched_earth import habits  # noqa: E402

DAY = 86400

# Linear fallback (no history): 2 days into the week, 20% used, 5 days to reset.
start = NOW
weekly_reset = start + 7 * DAY
now2 = start + 2 * DAY
fc = habits.forecast([], now2, current_used=20.0, weekly_reset=weekly_reset)
# rate = 20/2 = 10%/day; 5 days left -> +50 -> ~70% end, ~30% unused.
check("linear projected_end ~70", abs(fc.projected_end_used - 70.0) < 0.5)
check("linear leftover ~30", abs(fc.projected_leftover - 30.0) < 0.5)
check("linear preemptive (trending to waste)", fc.preemptive is True)
check("linear confidence low", fc.confidence == "low")

# On pace to finish ~full -> not preemptive.
fc2 = habits.forecast([], start + 6 * DAY, current_used=96.0, weekly_reset=start + 7 * DAY)
check("near-full not preemptive", fc2.preemptive is False)

# DOW profile path: 7 daily readings in one week, +6%/day -> day_samples >= 5.
hist = []
for i in range(7):
    hist = habits.record_observation(
        hist,
        {"now": start + i * DAY + 12 * 3600, "five_hour_pct": 0.0, "five_hour_reset": 0,
         "seven_day_pct": 6.0 * i, "seven_day_reset": weekly_reset},
    )
prof = habits.dow_profile(hist)
check("dow profile has >=5 day samples", prof["day_samples"] >= 5)
check("dow avg ~6%/day", abs(sum(prof["avg"].values()) / len(prof["avg"]) - 6.0) < 0.5)
fc3 = habits.forecast(hist, start + 2 * DAY + 12 * 3600, current_used=12.0,
                      weekly_reset=weekly_reset)
check("dow-based confidence not low", fc3.confidence in ("medium", "high"))
check("dow projected_end >= current", fc3.projected_end_used >= 12.0)

# Cross-week history is retained (calibration resets weekly; habits must not).
hist2 = habits.record_observation(
    hist, {"now": weekly_reset + DAY, "five_hour_pct": 0.0, "five_hour_reset": 0,
           "seven_day_pct": 3.0, "seven_day_reset": weekly_reset + 7 * DAY})
check("habits retain prior week", len({o["seven_day_reset"] for o in hist2}) == 2)

print(f"\n{passed} checks passed.")
