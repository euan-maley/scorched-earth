"""File I/O and statusline-JSON parsing. Keeps core.py / calibrate.py pure.

State lives under ~/.claude/scorched-earth/:
  - calibration.json : {"samples": [...], "r": float, "r_provisional": bool}
  - state.json       : latest snapshot + computed recommendation (for the CLI / skill)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Optional

from . import calibrate
from . import habits
from .core import Snapshot, compute, Recommendation

STATE_DIR = os.path.expanduser("~/.claude/scorched-earth")
CALIB_PATH = os.path.join(STATE_DIR, "calibration.json")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
HISTORY_PATH = os.path.join(STATE_DIR, "habits.json")


def now() -> int:
    return int(time.time())


def _ensure_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def _read_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return default


def _write_json(path: str, obj) -> None:
    _ensure_dir()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


# --- statusline payload parsing -------------------------------------------------

def _num(d, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur or cur[k] is None:
            return None
        cur = cur[k]
    return cur


def snapshot_from_statusline(data: dict, at: Optional[int] = None) -> Snapshot:
    """Build a Snapshot from the Claude Code statusline stdin JSON.

    `rate_limits` and either bucket may be absent (early session, non-Pro/Max).
    """
    rl = data.get("rate_limits") or {}
    five = rl.get("five_hour") or {}
    seven = rl.get("seven_day") or {}
    return Snapshot(
        now=at if at is not None else now(),
        five_hour_pct=_num(five, "used_percentage"),
        five_hour_reset=_num(five, "resets_at"),
        seven_day_pct=_num(seven, "used_percentage"),
        seven_day_reset=_num(seven, "resets_at"),
    )


def _snap_dict(snap: Snapshot) -> dict:
    return {
        "now": snap.now,
        "five_hour_pct": snap.five_hour_pct,
        "five_hour_reset": snap.five_hour_reset,
        "seven_day_pct": snap.seven_day_pct,
        "seven_day_reset": snap.seven_day_reset,
    }


# --- calibration ----------------------------------------------------------------

def load_calibration() -> dict:
    return _read_json(CALIB_PATH, {"samples": [], "r": None, "r_provisional": True})


def record_and_calibrate(snap: Snapshot) -> tuple[float, bool]:
    """Append the snapshot, recompute R, persist, and return (r, provisional).

    Skips the disk write when the sample set is unchanged (the statusline refreshes far
    more often than usage actually moves) to avoid churn on the hot path. A user-set R
    (provisional False with no measured pairs) is preserved.
    """
    calib = load_calibration()
    old = calib.get("samples", [])
    samples = calibrate.append_sample(old, _snap_dict(snap))
    r, provisional = calibrate.estimate_r(samples)
    # Respect a manually pinned R (--set-r) until enough real pairs exist to measure one.
    if provisional and calib.get("r") is not None and calib.get("r_provisional") is False:
        r, provisional = calib["r"], False
    if samples is not old and samples != old:
        _write_json(CALIB_PATH, {"samples": samples, "r": r, "r_provisional": provisional})
    return r, provisional


# --- habits / forecast ----------------------------------------------------------

def load_history() -> list:
    return _read_json(HISTORY_PATH, {"history": []}).get("history", [])


def record_history(snap: Snapshot) -> list:
    """Append a weekly-usage observation to the long (cross-week) history."""
    hist = load_history()
    new = habits.record_observation(hist, _snap_dict(snap))
    if new is not hist and new != hist:
        _write_json(HISTORY_PATH, {"history": new})
    return new


# --- live snapshot / recommendation --------------------------------------------

def save_state(snap: Snapshot, rec: Recommendation, fc: habits.Forecast) -> None:
    _write_json(STATE_PATH, {
        "snapshot": _snap_dict(snap),
        "recommendation": asdict(rec),
        "forecast": asdict(fc),
    })


def load_state() -> Optional[dict]:
    return _read_json(STATE_PATH, None)


@dataclass
class Result:
    snap: Snapshot
    rec: Recommendation
    forecast: habits.Forecast


def update_from_statusline(data: dict, at: Optional[int] = None) -> Result:
    """The statusline hot path: parse -> calibrate -> forecast -> compute -> persist."""
    snap = snapshot_from_statusline(data, at=at)
    r, provisional = record_and_calibrate(snap)
    hist = record_history(snap)
    af = habits.active_fraction(hist) if snap.has_weekly else 1.0
    rec = compute(snap, r, r_provisional=provisional, active_fraction=af)
    fc = (
        habits.forecast(hist, snap.now, snap.seven_day_pct, snap.seven_day_reset,
                        max_burnable=rec.max_burnable_weekly)
        if snap.has_weekly else habits.Forecast()
    )
    # Don't let a partial refresh (no weekly bucket early in a session) clobber the last
    # good snapshot that the CLI / skill read.
    if snap.has_weekly:
        save_state(snap, rec, fc)
    return Result(snap=snap, rec=rec, forecast=fc)
