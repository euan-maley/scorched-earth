"""Plain-stdlib tests. Run: python3 tests/test_scorched.py"""

import json
import os
import subprocess
import sys
import tempfile

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

from scorched_earth.core import Snapshot, compute, windows_left, WINDOW_SECONDS  # noqa: E402
from scorched_earth import calibrate  # noqa: E402

NOW = 1_000_000
HOUR = 3600
passed = 0
failures = []


def check(name, cond):
    """Record a check without aborting the run, so one failure doesn't hide the rest."""
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}")


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

# --- max: worked example (R=0.07) ----------------------------------------------
rec = compute(snap, r=0.07)
check("max when weekly budget can't be burned in time", rec.level == "max")
check("burn_pct clamps to 100 on green", rec.burn_pct == 100.0)
check("max_burnable ~15.4%", abs(rec.max_burnable_weekly - 15.4) < 0.1)
check("weekly_left = 62", rec.weekly_left == 62)

# --- amber: tune R so target lands in [0.70, 1.0) ------------------------------
# target = (weekly_left/wl)/(r*100). weekly_left=62, wl=2.2 -> 28.18/(r*100).
# want ~0.85 -> r*100 = 28.18/0.85 = 33.2 -> r = 0.332
rec_push = compute(snap, r=0.332)
check("push band", rec_push.level == "push")

# --- off: lots of windows, little weekly left ----------------------------------
slack = Snapshot(
    now=NOW,
    five_hour_pct=10, five_hour_reset=NOW + 4 * HOUR,
    seven_day_pct=20, seven_day_reset=NOW + 6 * 24 * HOUR,  # ~6 days left
)
rec_steady = compute(slack, r=0.05)
check("steady when plenty of runway", rec_steady.level == "steady")
check("steady burn_pct < 70", rec_steady.burn_pct < 70)

# --- exhausted: weekly_left <= 0.5 -> "off" ------------------------------------
empty = Snapshot(
    now=NOW,
    five_hour_pct=100, five_hour_reset=NOW + 1 * HOUR,
    seven_day_pct=99.7, seven_day_reset=NOW + 3 * 24 * HOUR,
)
rec_empty = compute(empty, r=0.05)
check("done when budget exhausted", rec_empty.level == "done")

# --- banner correctness regression -------------------------------------------
from scorched_earth.core import HEADLINE as _HEADLINE
check("steady and done have distinct banners", _HEADLINE["steady"] != _HEADLINE["done"])
check("exhausted banner praises the soldier", "good job" in _HEADLINE["done"].lower())

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
check("imminent reset with budget -> max", compute(imminent, r=0.05).level == "max")

# --- ease ("hold your fire"): a measured recent overpace overrides steady/push ------
# slack is steady (deep reserves). A fast recent pace that would strand >3 windows -> ease.
rec_ease = compute(slack, r=0.05, recent_per_window=6.0)
check("ease when recent pace runs dry early", rec_ease.level == "ease")
check("ease reason says hold your fire", "hold your fire" in rec_ease.reason.lower())
check("sustainable recent pace stays steady",
      compute(slack, r=0.05, recent_per_window=2.0).level == "steady")
check("no ease without a measured recent rate", compute(slack, r=0.05).level == "steady")
check("ease never overrides max", compute(snap, r=0.07, recent_per_window=50.0).level == "max")
# self-disengage near the reset: few windows left -> lockout below threshold -> silent.
near = Snapshot(now=NOW, five_hour_pct=50, five_hour_reset=NOW + 2 * HOUR,
                seven_day_pct=95, seven_day_reset=NOW + 8 * HOUR)
check("ease self-disengages near the reset",
      compute(near, r=0.1, recent_per_window=10.0).level == "steady")

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

# guardrails: one/two pairs are NOT trusted (hold the default), implausible spikes discarded
two = []
for i in range(2):
    two = calibrate.append_sample(two, {"now": NOW + i * 600, "five_hour_pct": i * 10.0,
        "five_hour_reset": h_reset, "seven_day_pct": 30.0 + i * 0.7, "seven_day_reset": w_reset})
r2, prov2 = calibrate.estimate_r(two)
check("one clean pair still uses provisional default", r2 == calibrate.DEFAULT_R and prov2 is True)
spike = []
for i in range(6):  # weekly jumps 5pp per 10pp window -> R=0.5, out of band, all discarded
    spike = calibrate.append_sample(spike, {"now": NOW + i * 600, "five_hour_pct": i * 10.0,
        "five_hour_reset": h_reset, "seven_day_pct": 10.0 + i * 5.0, "seven_day_reset": w_reset})
r_spk, prov_spk = calibrate.estimate_r(spike)
check("implausible R spikes are discarded -> default", r_spk == calibrate.DEFAULT_R and prov_spk is True)

# --- statusline tokens: the renamed/recolored deck ----------------------------
from scorched_earth.statusline import token as _sl_token
from scorched_earth.core import Recommendation as _Rec

def _rec(level, **kw):
    base = dict(level=level, weekly_left=80.0, windows_left=20.0, target_per_window=0.1,
                burn_pct=10.0, max_burnable_weekly=50.0, hours_to_weekly_reset=120.0,
                hours_to_window_reset=2.0, r=0.05, r_provisional=False, reason="x")
    base.update(kw)
    return _Rec(**base)

_steady_rec = _rec("steady")
_ease_rec = _rec("ease")
_done_rec = _rec("done", weekly_left=0.0)
for _style in ("fire", "emoji", "text"):
    check(f"steady token ({_style}) says eyes on the target",
          "eyes on the target" in _sl_token(_steady_rec, _style))
    check(f"ease token ({_style}) says hold your fire",
          "hold your fire" in _sl_token(_ease_rec, _style))
check("steady token (minimal) is a white dot",
      _sl_token(_steady_rec, "minimal") == "\033[1;37m●\033[0m")
check("ease token (minimal) is a yellow dot",
      _sl_token(_ease_rec, "minimal") == "\033[1;33m●\033[0m")
check("done token (emoji) now prints", "good job, soldier" in _sl_token(_done_rec, "emoji"))
check("unknown token stays blank", _sl_token(_rec("unknown"), "emoji") == "")

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

# capacity cap: can't project burning more than max_burnable; leftover = weekly_left - cap
fc_cap = habits.forecast([], now2, 20.0, weekly_reset, max_burnable=15.0)
check("forecast capped by physical capacity", abs(fc_cap.projected_leftover - 65.0) < 0.5)

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

# --- active-hours (sleep) discount ------------------------------------------------
afull = windows_left(snap, 1.0)
ahalf = windows_left(snap, 0.5)
check("sleep discount reduces usable windows", ahalf < afull)
check("current window is not discounted", ahalf >= (100 - 80) / 100 - 1e-9)
rec_full = compute(snap, 0.05, active_fraction=1.0)
rec_disc = compute(snap, 0.05, active_fraction=0.5)
check("fewer usable windows -> higher per-window burn", (rec_disc.burn_pct or 0) >= (rec_full.burn_pct or 0))
ah, ah_prov = habits.active_hours([])
check("active hours falls back to 16h provisional", ah == 16.0 and ah_prov is True)
check("default active_fraction leaves windows unchanged", windows_left(snap) == windows_left(snap, 1.0))

# --- straddle: current window crossing the weekly reset isn't over-counted -----
# Fresh window (0% used) but the weekly reset is 30min away. Only ~0.1 window of capacity
# is physically spendable, not a full window -> must read green, not amber.
straddle = Snapshot(
    now=NOW,
    five_hour_pct=0, five_hour_reset=NOW + int(4.5 * HOUR),
    seven_day_pct=85, seven_day_reset=NOW + 30 * 60,
)
wl_str = windows_left(straddle)
check("straddle: current window credited by time-to-reset, not in full", wl_str < 0.2)
check("straddle: still max (can't spend 15% in ~0.1 window)",
      compute(straddle, r=0.20).level == "max")
# Sanity: far-off weekly reset leaves the current-window credit untouched.
check("no straddle when weekly reset is far off",
      abs(windows_left(snap) - 2.2) < 1e-9)

# --- verdict-flip regression: two noisy pairs must NOT swing the call --------------
# The exact bug that bit us: a sparse R (~0.25 from few readings) flipping green<->off.
# With < MIN_PAIRS clean pairs (and 0.25 out of band anyway) we must hold the default.
flip = []
for i in range(2):  # weekly +2.5pp per 10pp window -> R=0.25
    flip = calibrate.append_sample(flip, {"now": NOW + i * 600, "five_hour_pct": i * 10.0,
        "five_hour_reset": h_reset, "seven_day_pct": 10.0 + i * 2.5, "seven_day_reset": w_reset})
r_flip, prov_flip = calibrate.estimate_r(flip)
check("noisy R=0.25 from 2 pairs holds the provisional default",
      r_flip == calibrate.DEFAULT_R and prov_flip is True)

# --- forecast cold-start: don't extrapolate < 1 day in or a >7d-out reset ----------
# 1h into the cycle, 3% used: the old max(0.25, elapsed) floor projected ~4x too high.
fc_early = habits.forecast([], start + HOUR, current_used=3.0, weekly_reset=start + 7 * DAY)
check("cold start <1 day: no fabricated forfeit", fc_early.preemptive is False)
check("cold start <1 day: flagged too-early", fc_early.basis == "too early in the cycle to forecast")
# A reset more than 7 days out (clock skew) must not produce a negative/garbage rate.
fc_skew = habits.forecast([], NOW, current_used=20.0, weekly_reset=NOW + 8 * DAY)
check("reset >7d out doesn't crash or over-warn", fc_skew.preemptive is False)

# --- Snapshot.from_dict tolerates schema drift -------------------------------------
check("from_dict ignores unknown keys",
      Snapshot.from_dict({"now": NOW, "bogus": 1, "seven_day_pct": 50}).seven_day_pct == 50)
check("from_dict fills missing now", Snapshot.from_dict({"seven_day_pct": 50}).now == 0)

# --- report renders without leftover placeholders / crashes -------------------------
from scorched_earth import report as rpt  # noqa: E402

good_state = {
    "snapshot": {"now": NOW, "five_hour_pct": 80, "five_hour_reset": NOW + HOUR,
                 "seven_day_pct": 38, "seven_day_reset": NOW + 11 * HOUR},
    "recommendation": {"r": 0.07, "r_provisional": False},
    "forecast": {},
}
html = rpt.render_html(good_state, [], NOW)
check("report substitutes all placeholders", "__DECK__" not in html and "__DATA__" not in html
      and "__STAMP__" not in html and "__BURN__" not in html and "__REFRESH__" not in html)
# Phase 2 (#12): served sitrep gets a Refresh button (reloads /sitrep); the offline file does not.
_served = rpt.render_html(good_state, [], NOW, served=True)
check("served sitrep shows a Refresh button that reloads",
      "refreshbtn" in _served and "location.reload()" in _served and "__REFRESH__" not in _served)
check("offline sitrep (default) ships no Refresh button", "location.reload()" not in html)
check("report is non-trivial HTML", html.lstrip().startswith("<") and len(html) > 1000)
# None state (never any reading) must not throw.
check("report handles None state", isinstance(rpt.render_html(None, [], NOW), str))
# A corrupted/unknown recommendation level must not KeyError.
weird = {"snapshot": {}, "recommendation": {"level": "bogus_level"}, "forecast": {}}
check("report tolerates an unknown status level", isinstance(rpt.render_html(weird, [], NOW), str))

# --- state.py round-trip + corruption recovery (isolated temp dir) ------------------
from scorched_earth import state as st  # noqa: E402

_orig = (st.STATE_DIR, st.CALIB_PATH, st.STATE_PATH, st.HISTORY_PATH)
_tmp = tempfile.mkdtemp()
st.STATE_DIR = _tmp
st.CALIB_PATH = os.path.join(_tmp, "calibration.json")
st.STATE_PATH = os.path.join(_tmp, "state.json")
st.HISTORY_PATH = os.path.join(_tmp, "habits.json")
try:
    payload = {"rate_limits": {
        "five_hour": {"used_percentage": 80, "resets_at": NOW + HOUR},
        "seven_day": {"used_percentage": 38, "resets_at": NOW + 11 * HOUR}}}
    res = st.update_from_statusline(payload, at=NOW)
    check("update_from_statusline parses the full payload", res.snap.seven_day_pct == 38)
    reloaded = st.load_state()
    check("state.json round-trips", reloaded["snapshot"]["seven_day_pct"] == 38)
    check("state file is owner-only (0600)", (os.stat(st.STATE_PATH).st_mode & 0o777) == 0o600)
    # Partial payloads must not raise and must not clobber the last good snapshot.
    st.update_from_statusline({}, at=NOW + 1)
    st.update_from_statusline({"rate_limits": None}, at=NOW + 2)
    st.update_from_statusline({"rate_limits": {"five_hour": {"used_percentage": 5}}}, at=NOW + 3)
    check("partial payloads don't clobber good state", st.load_state()["snapshot"]["seven_day_pct"] == 38)
    # Corrupt JSON on disk recovers to defaults rather than crashing.
    with open(st.STATE_PATH, "w") as f:
        f.write("{ not valid json ]")
    check("corrupt state.json recovers to None", st.load_state() is None)
finally:
    st.STATE_DIR, st.CALIB_PATH, st.STATE_PATH, st.HISTORY_PATH = _orig
    __import__("shutil").rmtree(_tmp, ignore_errors=True)

# --- statusline never errors: any input -> exit 0, valid-or-empty stdout -----------
_env = {**os.environ, "PYTHONPATH": _SRC, "HOME": tempfile.mkdtemp()}
for label, stdin in [
    ("empty stdin", ""),
    ("garbage", "not json at all"),
    ("json array", "[]"),
    ("null", "null"),
    ("empty object", "{}"),
    ("valid payload", json.dumps({"rate_limits": {
        "five_hour": {"used_percentage": 80, "resets_at": NOW + HOUR},
        "seven_day": {"used_percentage": 38, "resets_at": NOW + 11 * HOUR}}})),
]:
    proc = subprocess.run([sys.executable, "-m", "scorched_earth.statusline"],
                          input=stdin, capture_output=True, text=True, env=_env)
    check(f"statusline exits 0 on {label}", proc.returncode == 0)
__import__("shutil").rmtree(_env["HOME"], ignore_errors=True)


print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
