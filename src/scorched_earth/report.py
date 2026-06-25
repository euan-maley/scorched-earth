"""Generate a self-contained stylized HTML sitrep.

8-bit war / scorched-earth crop-field HUD. THE FIELD is a top-down Stardew-style pixel
farm where each weekday plot grows lush when you burn light and chars when you burn heavy.
A toggle switches the field between LAST WEEK (actual), AVERAGE (all-time habit), and THIS
WEEK (actual so far + projected ahead). The pixel-art engine is ported faithfully from the
design handoff; Python computes the data and the surrounding HUD stats.
"""

from __future__ import annotations

import html as _html
import json
import os
import time

from dataclasses import asdict

from . import habits
from .core import HEADLINE, Snapshot, compute  # canonical voice + math, shared with the CLI

# green = "burn it all", so its accent is fire, not green.
STATUS_COLOR = {"green": "#ff6a1f", "amber": "#e2a04d", "low": "#8a9a3c", "off": "#6f8a8a", "unknown": "#6f8a8a"}


def _num(x):
    return None if x is None else round(x)


def _stats(state: dict, history: list, active_fraction: float = 1.0) -> dict:
    cached = state.get("recommendation", {}) if state else {}
    fc = state.get("forecast", {}) if state else {}
    snap = state.get("snapshot", {}) if state else {}
    # Recompute the recommendation AND forecast from the snapshot so the verdict/reason and the
    # projected numbers always reflect the current math (voice, sleep discount, capacity cap),
    # never values cached on disk by an earlier reading.
    if snap.get("seven_day_pct") is not None:
        rec_obj = compute(Snapshot.from_dict(snap), cached.get("r"),
                          r_provisional=cached.get("r_provisional", False),
                          active_fraction=active_fraction)
        rec = asdict(rec_obj)
        fc = asdict(habits.forecast(history, snap.get("now"), snap.get("seven_day_pct"),
                                    snap.get("seven_day_reset"),
                                    max_burnable=rec_obj.max_burnable_weekly))
    else:
        rec = cached
    level = rec.get("level", "unknown")

    weekly = _num(rec.get("weekly_left"))
    win_used = snap.get("five_hour_pct")
    ammo = None if win_used is None else round(max(0.0, 100.0 - win_used))
    pe = fc.get("projected_end_used")

    # Most you could realistically still burn = min(what you hold, what the windows allow).
    maxb = rec.get("max_burnable_weekly")
    if maxb is not None and rec.get("weekly_left") is not None:
        maxb = min(maxb, rec["weekly_left"])

    dash = "—"
    return {
        "statusLevel": level.upper(),
        "statusColor": STATUS_COLOR.get(level, STATUS_COLOR["unknown"]),
        "verdict": HEADLINE.get(level, "").upper(),
        "reason": (rec.get("reason") or "Recon's not in yet. Open a session and the field fills in."),
        "weeklyRemaining": weekly if weekly is not None else dash,
        "weeklyW": f"{weekly or 0}%",
        "weeklyResetTs": snap.get("seven_day_reset") or 0,
        "windowRemaining": ammo if ammo is not None else dash,
        "windowW": f"{ammo or 0}%",
        "windowResetTs": snap.get("five_hour_reset") or 0,
        "windowsLeft": (f"{rec['windows_left']:.1f}" if rec.get("windows_left") is not None else dash),
        "recommendedBurn": (f"{rec['burn_pct']:.0f}%" if rec.get("burn_pct") is not None else dash),
        "valuePerWindow": (f"{(rec.get('r') or 0) * 100:.0f}%" if rec.get("r") else dash),
        "maxBurnable": (f"{maxb:.0f}%" if maxb is not None else dash),
        "projectedEnd": (round(pe) if pe is not None else dash),
        "projectedW": (f"{round(pe)}%" if pe is not None else "0%"),
        "projectedLeftover": (f"{round(fc['projected_leftover'])}%" if fc.get("projected_leftover") is not None else dash),
        "confidence": (fc.get("confidence") or "none").upper(),
        "preemptive": bool(fc.get("preemptive")),
        "weeks": fc.get("weeks_observed") or len({o.get("seven_day_reset") for o in history}),
    }


def _modes(history: list, state: dict) -> dict:
    snap = (state or {}).get("snapshot", {})
    rec = (state or {}).get("recommendation", {})
    cur = snap.get("seven_day_reset")
    now = snap.get("now") or int(time.time())
    last = habits.last_completed_reset(history, cur)
    # THIS WEEK colors future days by projected burn STATUS (charred=scorched-earth,
    # golden=on the fence, lush=no limit); past days keep their actual magnitude.
    af = habits.active_fraction(history)
    current = habits.current_week_days(history, cur, now, r=rec.get("r"),
                                       weekly_left=rec.get("weekly_left"), active_fraction=af)
    average = habits.average_days(history)
    lastweek = habits.week_days(history, last)
    # Order the plots by the weekly cycle: leftmost = the weekday the budget resets fresh,
    # rightmost = the day before the next reset, so scorched-earth days sit on the right.
    if cur:
        anchor = time.localtime(cur).tm_wday
        order = [(anchor + k) % 7 for k in range(7)]
    else:
        order = list(range(7))
    ro = lambda a: [a[i] for i in order]
    return {"current": ro(current), "average": ro(average), "lastweek": ro(lastweek)}


# ---- page assembly ------------------------------------------------------------

def render_html(state: dict | None, history: list, generated_at: int) -> str:
    snap = (state or {}).get("snapshot", {})
    active_h, active_prov = habits.active_hours(history)
    st = _stats(state, history, active_fraction=active_h / 24.0)
    modes = _modes(history, state)
    weeks = st.pop("weeks", 0) or len({o.get("seven_day_reset") for o in history})
    has_current = any(d.get("kind") != "projected" or d.get("pct") not in (None,) for d in modes["current"])
    default_mode = "current"

    data = {
        "modes": modes,
        "defaultMode": default_mode,
        "stats": st,
        "weeklyResetTs": st["weeklyResetTs"],
        "windowResetTs": st["windowResetTs"],
    }
    e = _html.escape
    burn = st["statusLevel"] == "GREEN"
    lvl_html = ('<span class="lvl firetext">BURN IT ALL</span>' if burn
                else f'<span class="lvl">{e(st["statusLevel"])}</span>')
    conf = st["confidence"]
    conf_fill = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(conf, 0)
    pips = "".join(
        f'<span style="width:13px;height:13px;background:{"#9fc0c0" if i < conf_fill else "#1b2a30"};border:1px solid #000;display:inline-block;"></span>'
        for i in range(3)
    )
    preflag = ""
    if st["preemptive"]:
        preflag = (
            '<div style="display:flex;gap:10px;align-items:center;margin-top:13px;border:1px solid #e2541d;'
            'background:rgba(226,84,29,.12);padding:8px 13px;font-family:VT323;font-size:19px;letter-spacing:1px;color:#f0a86a;">'
            '<span style="font-size:19px;">&#9888;</span>'
            f'<span>PREEMPTIVE FLAG. ON TRACK TO FORFEIT {st["projectedLeftover"]} OF WEEKLY RESERVES AT RESET. ADVANCE HARDER.</span></div>'
        )
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(generated_at))
    rst = snap.get("seven_day_reset")
    fmt_dt = lambda ts: time.strftime("%a %d %b %H:%M", time.localtime(ts)).upper() if ts else "—"
    cyc_start = fmt_dt(rst - 7 * 86400) if rst else "—"
    cyc_end = fmt_dt(rst) if rst else "—"

    deck = f"""
    <div class="mod banner" style="--ac:{st['statusColor']}">
      <div class="acc"></div>
      <div class="brow"><span class="sl">SITREP //</span>
        <span class="pill"><span class="hudDot dot"></span>{lvl_html}</span></div>
      <div class="verdict">{e(st['verdict'])}</div>
      <div class="reason">{e(st['reason'])}</div>
    </div>

    <div class="g2">
      <div class="mod">
        <div class="mh"><span>RESERVES</span><span class="sub">WEEKLY BUDGET</span></div>
        <div class="brow2"><div class="big">{st['weeklyRemaining']}<span class="pc">%</span><div class="cap">REMAINING</div></div>
          <div class="rt"><div class="rl">REINFORCEMENTS IN</div><div class="cd" data-cd="{st['weeklyResetTs']}">&mdash;</div></div></div>
        <div class="meter"><div class="fill" style="width:{st['weeklyW']};background:linear-gradient(#c7a356,#a87f33);"></div><div class="seg"></div></div>
        <div class="tx">how much of your weekly limit is still available</div>
      </div>
      <div class="mod">
        <div class="mh"><span>AMMO</span><span class="sub">5-HOUR WINDOW</span></div>
        <div class="brow2"><div class="big">{st['windowRemaining']}<span class="pc">%</span><div class="cap">IN MAGAZINE</div></div>
          <div class="rt"><div class="rl">RELOAD IN</div><div class="cd" data-cd="{st['windowResetTs']}">&mdash;</div></div></div>
        <div class="meter"><div class="fill" style="width:{st['windowW']};background:linear-gradient(#5fae62,#46813f);"></div><div class="seg"></div></div>
        <div class="tx">what's left in your current 5-hour cap</div>
      </div>
    </div>

    <div class="mod">
      <div class="mh single">TACTICAL</div>
      <div class="tac">
        <div class="tc"><div class="tl">WINDOWS LEFT</div><div class="tv" style="color:#eef3f3;">~{st['windowsLeft']}</div><div class="tx">usable 5-hour windows left (your sleep hours excluded)</div></div>
        <div class="tc"><div class="tl">REC. BURN / WINDOW</div><div class="tv" style="color:#7cb342;">{st['recommendedBurn']}</div><div class="tx">aim to use about this much each window</div></div>
        <div class="tc"><div class="tl">VALUE / WINDOW</div><div class="tv" style="color:#c1dada;">{st['valuePerWindow']}</div><div class="tx">one maxed window = this much of your week</div></div>
        <div class="tc"><div class="tl">MAX BURNABLE</div><div class="tv" style="color:#e2a04d;">{st['maxBurnable']}</div><div class="tx">the most you could still spend before reset</div></div>
      </div>
      <div class="note">Window counts exclude the hours you're usually asleep, since you can't burn a window at 4am. It assumes you're around ~{active_h:.0f}h a day{', estimated until it learns your real hours' if active_prov else ', learned from when you actually use Claude'}.</div>
    </div>

    <div class="mod">
      <div class="mh"><span>INTEL</span><span class="sub">END-OF-WEEK FORECAST</span></div>
      <div class="intel">
        <div class="ip"><div class="iprow"><span class="tl">PROJECTED END USAGE</span><span class="iv">{st['projectedEnd']}%</span></div>
          <div class="meter"><div class="fill" style="width:{st['projectedW']};background:linear-gradient(#d98a3c,#b35f24);"></div><div class="seg"></div></div>
          <div class="tx">where you'll finish the week at your usual pace</div></div>
        <div><div class="tl">PROJECTED LEFTOVER</div><div class="iv2">{st['projectedLeftover']} <span class="ff">FORFEIT</span></div><div class="tx">wasted at reset if you don't burn more</div></div>
        <div><div class="tl">CONFIDENCE</div><div class="pips">{pips}<span class="cv">{e(conf)}</span></div><div class="tx">how sure this forecast is</div></div>
      </div>
      {preflag}
    </div>

    <div class="meta"><span>GENERATED {stamp}</span><span>// FIELD INTEL &middot; {weeks} WEEK{'S' if weeks != 1 else ''} OF DATA &middot; ~{active_h:.0f}H ACTIVE/DAY{' (EST)' if active_prov else ''}</span></div>
    """

    return (_SHELL.replace("__DECK__", deck).replace("__DATA__", json.dumps(data))
            .replace("__STAMP__", stamp)
            .replace("__CYCLE_START__", cyc_start).replace("__CYCLE_END__", cyc_end)
            .replace("__BURN__", "burn" if burn else ""))


def generate(state, history, path, generated_at) -> str:
    out = render_html(state, history, generated_at)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(out)
    os.replace(tmp, path)
    return path


# ---- the page shell: CSS + static markup + the ported JS engine ----------------

_SHELL = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scorched Earth · Sitrep</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}
html,body{margin:0;background:#05080a}
body{font-family:'VT323',monospace;padding:22px 16px}
@keyframes fieldSway{0%,100%{transform:rotate(-1.3deg)}50%{transform:rotate(1.3deg)}}
@keyframes fieldEmber{0%,100%{opacity:.3}50%{opacity:1}}
@keyframes fieldSmoke{0%{opacity:.55;transform:translate(0,0)}100%{opacity:0;transform:translate(-3px,-12px)}}
@keyframes fieldSpark{0%,100%{opacity:.15}50%{opacity:1}}
@keyframes hudBlink{0%,100%{opacity:1}50%{opacity:.25}}
.cropsway{transform-box:fill-box;transform-origin:50% 100%;animation:fieldSway 4.6s ease-in-out infinite}
.embers{animation:fieldEmber 1.05s steps(2,end) infinite}
.smoke{transform-box:fill-box;transform-origin:50% 100%;animation:fieldSmoke 3.4s ease-out infinite}
.sparkle{animation:fieldSpark 2.6s ease-in-out infinite}
.hudDot{animation:hudBlink 1.4s steps(1,end) infinite}
@media (prefers-reduced-motion:reduce){.cropsway,.embers,.smoke,.sparkle,.hudDot{animation:none!important}}

.panel{max-width:820px;margin:0 auto;background:#0b0f12;border:1px solid #243639;position:relative;overflow:hidden;z-index:1;box-shadow:0 0 0 1px #05080a,0 14px 50px rgba(0,0,0,.6)}
.tick{position:absolute;width:10px;height:10px;z-index:8}
.t1{left:5px;top:5px;border-left:2px solid #3a5a5a;border-top:2px solid #3a5a5a}
.t2{right:5px;top:5px;border-right:2px solid #3a5a5a;border-top:2px solid #3a5a5a}
.t3{left:5px;bottom:5px;border-left:2px solid #3a5a5a;border-bottom:2px solid #3a5a5a}
.t4{right:5px;bottom:5px;border-right:2px solid #3a5a5a;border-bottom:2px solid #3a5a5a}

.hdr{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 16px;border-bottom:1px solid #1b2a30;background:linear-gradient(#0f161a,#0b0f12)}
.hdr .l{display:flex;align-items:center;gap:11px;min-width:0}
.hdr .d{width:9px;height:9px;background:#e2541d;border-radius:50%;box-shadow:0 0 7px #e2541d;flex:none}
.hdr .ti{font-family:'Press Start 2P';font-size:11px;color:#cdd9d9;letter-spacing:1px;white-space:nowrap}
.hdr .su{font-size:18px;color:#86abab;letter-spacing:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hdr .pk{font-size:20px;color:#8fb8b8;letter-spacing:1px;white-space:nowrap;flex:none}
.hdr .pk b{color:#e2a04d;font-weight:400} .hdr .pk i{color:#86abab;font-style:normal}

.fieldwrap{padding:16px;background:linear-gradient(#3a2817,#2c1e11)}
.toggle{display:flex;margin-bottom:12px}
.tbtn{font-family:'VT323';font-size:17px;letter-spacing:1px;padding:4px 13px 3px;border:1px solid #2c4444;background:#10181d;color:#9ec1c1;cursor:pointer;line-height:1}
.tbtn+.tbtn{border-left:none}
.tbtn.on{background:#e2a04d;color:#0b0f12;border-color:#e2a04d}
.soil{padding:15px 13px;border:1px solid #19110a;background:repeating-linear-gradient(90deg,rgba(0,0,0,.05) 0 2px,transparent 2px 9px),repeating-linear-gradient(0deg,rgba(0,0,0,.05) 0 2px,transparent 2px 9px),linear-gradient(#5a4126,#4a3520);box-shadow:inset 0 0 28px rgba(0,0,0,.5)}
.cyclebar{display:flex;justify-content:space-between;margin-top:9px;font-family:'VT323';font-size:15px;letter-spacing:1px;color:#caa86a}
.cyclebar .cend{color:#e2a04d}
.row{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}
.cell{position:relative;aspect-ratio:8/7;overflow:visible;background:#3a2817}
.cell.proj{opacity:.5}
.cell.today{outline:2px solid #e2a04d;outline-offset:-2px}
.chip{position:absolute;left:4px;top:4px;z-index:3;background:rgba(7,11,13,.86);border:1px solid #2c4444;padding:1px 7px 2px;font-family:'VT323';font-size:21px;line-height:1.05;display:flex;gap:8px;align-items:baseline;box-shadow:0 1px 4px rgba(0,0,0,.5)}
.chip .c{color:#eaf2f2;letter-spacing:1px} .chip .p{color:#e2a04d}
.stlabel{position:absolute;right:5px;bottom:4px;z-index:3;font-family:'VT323';font-size:16px;letter-spacing:1px;color:#f0dcae;text-shadow:0 1px 0 #000,0 0 4px #000}
.cell.proj .stlabel{color:#9ec1c1}
.nowtag{position:absolute;right:5px;top:4px;z-index:3;font-family:'VT323';font-size:19px;color:#0b0f12;background:#e2a04d;padding:1px 8px 2px;letter-spacing:1px;box-shadow:0 1px 4px rgba(0,0,0,.5)}
.road{position:relative;height:36px;margin:9px 0;background:repeating-linear-gradient(90deg,#6b4a2b 0 3px,#5e4023 3px 8px);border-top:2px solid #3a2615;border-bottom:2px solid #3a2615;box-shadow:inset 0 0 12px rgba(0,0,0,.45)}
.rut{position:absolute;left:0;right:0;height:2px;background:#4a3520;opacity:.7}
.scare{position:absolute;left:50%;top:-32px;transform:translateX(-50%);width:38px;height:66px;z-index:4}

.deck{background:#0b0f12;border-top:1px solid #1b2a30;padding:16px;display:flex;flex-direction:column;gap:12px}
.mod{border:1px solid #2b3d44;background:#10181d;padding:13px 15px}
.mh{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #2b3d44;padding-bottom:7px;margin-bottom:11px;font-family:'VT323';letter-spacing:2px}
.mh>span:first-child,.mh.single{font-size:16px;color:#8fb8b8} .mh .sub{font-size:13px;color:#86abab}
.banner{position:relative;border:1px solid #2a3338;background:linear-gradient(90deg,color-mix(in srgb,var(--ac) 16%,transparent),rgba(11,15,18,0) 65%);padding:13px 15px 14px 19px;overflow:hidden}
.banner .acc{position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--ac)}
.banner .brow{display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.banner .sl{font-size:15px;letter-spacing:2px;color:#86abab}
.banner .pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--ac);padding:3px 10px 2px}
.banner .dot{width:8px;height:8px;border-radius:50%;background:var(--ac);box-shadow:0 0 6px var(--ac)}
.banner .lvl{font-family:'Press Start 2P';font-size:9px;color:var(--ac);letter-spacing:1px}
.banner .verdict{font-family:'Press Start 2P';font-size:14px;color:#eef3f3;letter-spacing:1px;margin:12px 0 9px;line-height:1.55}
.banner .reason{font-size:20px;color:#c1dada;line-height:1.18;max-width:74ch}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.brow2{display:flex;align-items:flex-end;justify-content:space-between;gap:12px}
.big{font-family:'VT323';line-height:.8;font-size:54px;color:#eef3f3} .big .pc{font-size:26px;color:#e2a04d}
.big .cap{font-size:13px;letter-spacing:2px;color:#93b9b9;margin-top:5px}
.rt{text-align:right;font-family:'VT323'} .rt .rl{font-size:14px;letter-spacing:1px;color:#9ec1c1} .rt .cd{font-size:28px;color:#c1dada;line-height:1}
.meter{position:relative;height:15px;margin-top:12px;background:#070b0d;border:1px solid #243a3a}
.fill{position:absolute;top:0;left:0;bottom:0}
.seg{position:absolute;inset:0;background:repeating-linear-gradient(90deg,transparent 0 9px,#0b0f12 9px 12px)}
.tac{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#2b3d44;border:1px solid #2b3d44}
.tc{background:#10181d;padding:9px 11px} .tl{font-family:'VT323';font-size:15px;letter-spacing:1px;color:#a8c8c8}
.tx{font-family:'VT323';font-size:16px;letter-spacing:.5px;color:#b7d2d2;margin-top:5px;line-height:1.15}
.note{font-family:'VT323';font-size:15px;letter-spacing:.5px;color:#8aa6a6;margin-top:11px;padding-top:9px;border-top:1px dashed #2b3d44;line-height:1.25}
.tv{font-family:'VT323';font-size:32px;line-height:1.05}
.intel{display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end} .ip{flex:1;min-width:200px}
.iprow{display:flex;justify-content:space-between;align-items:baseline;font-family:'VT323'} .iv{font-size:30px;color:#e2a04d;line-height:1}
.iv2{font-family:'VT323';font-size:30px;color:#c0653a;line-height:1} .iv2 .ff{font-size:15px;color:#93b9b9}
.pips{display:flex;align-items:center;gap:7px;margin-top:5px} .pips .cv{font-size:20px;color:#c1dada}
.meta{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;font-family:'VT323';font-size:14px;letter-spacing:1px;color:#7a9d9d}
.legend{display:flex;align-items:center;gap:15px;flex-wrap:wrap;padding:10px 16px;border-top:1px solid #1b2a30;background:#0a0e11;font-size:16px;letter-spacing:1px;color:#9ec1c1}
.legend .sw{width:12px;height:12px;border:1px solid #000;display:inline-block}
.legend span.i{display:inline-flex;align-items:center;gap:6px}
.scan{position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px);mix-blend-mode:multiply;z-index:6}
.vig{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse at center,transparent 58%,rgba(0,0,0,.4) 100%);z-index:6}
/* --- burn mode: green status sets the page on fire --- */
.pagefire{position:fixed;left:0;bottom:0;width:100vw;height:52vh;z-index:0;display:none;image-rendering:pixelated;pointer-events:none}
.pageembers{position:fixed;inset:0;z-index:0;display:none;pointer-events:none}
body.burn .pagefire,body.burn .pageembers{display:block}
body.burn .panel{box-shadow:0 0 0 1px #ff6a1f,0 0 40px rgba(255,90,20,.5),0 14px 50px rgba(0,0,0,.6);border-color:#ff6a1f;animation:panelpulse 2.4s ease-in-out infinite}
@keyframes panelpulse{0%,100%{box-shadow:0 0 0 1px #ff6a1f,0 0 32px rgba(255,90,20,.4),0 14px 50px rgba(0,0,0,.6)}50%{box-shadow:0 0 0 1px #ff8a3f,0 0 52px rgba(255,110,30,.62),0 14px 50px rgba(0,0,0,.6)}}
.firetext{background:linear-gradient(90deg,#ff3b1f,#ff8a1f,#ffd24a,#ff8a1f,#ff3b1f);background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:firetext 1.6s linear infinite}
@keyframes firetext{to{background-position:200% 0}}
@media (prefers-reduced-motion:reduce){body.burn .panel,.firetext{animation:none}}
@media (max-width:520px){.g2,.tac{grid-template-columns:1fr 1fr}.tac{grid-template-columns:1fr 1fr}}
</style></head>
<body class="__BURN__"><div class="panel">
<span class="tick t1"></span><span class="tick t2"></span><span class="tick t3"></span><span class="tick t4"></span>

<div class="hdr"><div class="l"><span class="hudDot d"></span><span class="ti">THE FIELD</span>
<span class="su">// WEEKLY BURN · SECTOR 07</span></div>
<div class="pk">PEAK <b id="peakV">—</b> <i id="peakD"></i></div></div>

<div class="fieldwrap">
  <div class="toggle" id="toggle"></div>
  <div class="soil">
    <div class="row" id="rowTop"></div>
    <div class="road"><div class="rut" style="top:11px"></div><div class="rut" style="bottom:11px"></div><div class="scare" id="scare"></div></div>
    <div class="row" id="rowBottom"></div>
  </div>
  <div class="cyclebar"><span class="cstart">&#9658; START &middot; __CYCLE_START__</span><span class="cend">RESET &middot; __CYCLE_END__ &#9668;</span></div>
</div>

<div class="deck">__DECK__</div>

<div class="legend"><span style="color:#86abab">SOIL&nbsp;STATE</span>
<span class="i"><span class="sw" style="background:#7cb342"></span>LUSH</span>
<span class="i"><span class="sw" style="background:#e7c24c"></span>WHEAT</span>
<span class="i"><span class="sw" style="background:#b08a3c"></span>DRYING</span>
<span class="i"><span class="sw" style="background:#1a120b"></span>SCORCHED</span>
<span class="i"><span class="sw" style="background:#6b4a2b"></span>UNSOWN</span></div>

<div class="scan"></div><div class="vig"></div>
</div>
<canvas class="pageembers"></canvas>
<canvas class="pagefire" width="340" height="104"></canvas>

<script>
const SITREP = __DATA__;
const MULT = 1;
const MODE_LABELS = {lastweek:"LAST WEEK", average:"AVERAGE", current:"THIS WEEK"};
const MODE_ORDER = ["lastweek","average","current"];
const STN = {lush:"LUSH",golden:"WHEAT",dry:"DRYING",charred:"SCORCHED",nodata:"UNSOWN"};

function rng(seed){let s=(seed>>>0)||1;return()=>{s=(s*1664525+1013904223)>>>0;return s/4294967296;};}
function classify(p){if(p==null)return"nodata";if(p<=3)return"lush";if(p<=9)return"golden";if(p<=11)return"dry";return"charred";}
function pushSprite(out,map,pal,ox,oy){for(let r=0;r<map.length;r++){const row=map[r];for(let c=0;c<row.length;c++){const f=pal[row[c]];if(!f)continue;out.push({x:ox+c,y:oy+r,w:1,h:1,f});}}}
function rectsSvg(arr){return arr.map(r=>`<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="${r.f}"${r.o==null?"":` opacity="${r.o}"`}/>`).join("");}
function grp(arr,cls,delay){if(!arr.length)return"";const c=cls?` class="${cls}"`:"";const s=delay!=null?` style="animation-delay:${delay}s"`:"";return `<g${c}${s}>${rectsSvg(arr)}</g>`;}

function addFence(out){const FR="#7a5a34",FD="#3a2615",FH="#9a7a4e";
  out.push({x:0,y:1,w:64,h:2,f:FR},{x:0,y:0,w:64,h:1,f:FH},{x:0,y:3,w:64,h:1,f:FD});
  out.push({x:0,y:53,w:64,h:2,f:FR},{x:0,y:52,w:64,h:1,f:FH},{x:0,y:55,w:64,h:1,f:FD});
  out.push({x:0,y:0,w:2,h:56,f:FR},{x:62,y:0,w:2,h:56,f:FR});
  const px=[2,20,38,56,61];
  for(const x of px){out.push({x:x,y:-3,w:3,h:9,f:FR},{x:x,y:-3,w:1,h:9,f:FH},{x:x+2,y:-3,w:1,h:9,f:FD});}
  for(const x of px){out.push({x:x,y:50,w:3,h:6,f:FR},{x:x,y:50,w:1,h:6,f:FH});}
}
function buildPlot(state,seed,mult){
  const rnd=rng(seed*7+13);
  const SOIL={lush:{base:"#523620",ridge:"#3a2615",hi:"#62442a",speck:"#6e5236"},
    golden:{base:"#6b4a2b",ridge:"#4f3620",hi:"#7d5832",speck:"#8a6a3e"},
    dry:{base:"#5a4126",ridge:"#3f2c19",hi:"#6a4d2c",speck:"#7d7060"},
    charred:{base:"#1a120b",ridge:"#0c0805",hi:"#251a10",speck:"#3a2c1e"},
    nodata:{base:"#6b4a2b",ridge:"#503620",hi:"#7d5832",speck:"#5e4023"}}[state];
  const soil=[],crops=[],embers=[],smoke=[],sparkle=[],fence=[];
  soil.push({x:0,y:0,w:64,h:56,f:SOIL.base});
  for(let y=3;y<56;y+=6){soil.push({x:0,y:y,w:64,h:1,f:SOIL.ridge});soil.push({x:0,y:y+1,w:64,h:1,f:SOIL.hi});
    for(let i=0;i<14;i++){if(rnd()<0.35)soil.push({x:Math.floor(rnd()*64),y:y+2+Math.floor(rnd()*2),w:1,h:1,f:SOIL.speck});}}
  if(state==="lush"){
    for(let i=0;i<6;i++){const x=Math.floor(rnd()*52),y=Math.floor(rnd()*46)+5;soil.push({x:x,y:y,w:6+Math.floor(rnd()*4),h:2,f:"#3e2917",o:.55});}
    for(let i=0;i<3;i++){const x=8+Math.floor(rnd()*48),y=9+Math.floor(rnd()*40);
      sparkle.push({x:x,y:y-1,w:1,h:1,f:"#cdecff"},{x:x-1,y:y,w:1,h:1,f:"#cdecff"},{x:x+1,y:y,w:1,h:1,f:"#ffffff"},{x:x,y:y+1,w:1,h:1,f:"#cdecff"},{x:x,y:y,w:1,h:1,f:"#ffffff"});}}
  if(state==="dry"||state==="charred"){
    for(let i=0;i<4;i++){let x=8+Math.floor(rnd()*48),y=8+Math.floor(rnd()*38);
      for(let k=0;k<5;k++){soil.push({x:x,y:y,w:1,h:1,f:state==="charred"?"#000000":"#2e2014"});x+=rnd()<.5?1:0;y+=1;}}}
  if(state==="charred"){const gc=Math.round(6*mult);
    for(let i=0;i<gc;i++){const x=6+Math.floor(rnd()*52),y=6+Math.floor(rnd()*44);embers.push({x:x,y:y,w:1,h:1,f:rnd()<.5?"#e2541d":"#ff9a3d"});}}
  const M={lush:["  HHg  "," HGGGg ","HGGGGGg","gGGGGGg","gGGfGGg"," gGGGg ","  gsg  ","   s   "],
    wheat:[" H ","HWH","WWW","HWH","WWW"," W "," s "," s ","sss"],
    dry:["  d  "," dDd ","dDDd "," Dddd"," dDd ","  ss ","  s  "," sss "],
    char:["k   E","k k  ","kek e","Kkkk ","KkKkK","KKKKK"]};
  const P={lush:{H:"#9ccc5a",G:"#7cb342",g:"#5a8a32",f:"#e7c24c",s:"#4a7028"},
    wheat:{H:"#f2d873",W:"#e7c24c",w:"#b8942f",s:"#9a8a3a"},
    dry:{D:"#cda14e",d:"#9c7838",s:"#7a5e34",e:"#e2541d"},
    char:{k:"#241910",K:"#0c0805",e:"#e2541d",E:"#ff9a3d",a:"#6b5e4c"}};
  const stamp=(map,pal,cx,by)=>{const w=map[0].length,h=map.length;pushSprite(crops,map,pal,cx-(w>>1),by-h);};
  const place=(cols,rowsN,fn)=>{for(let r=0;r<rowsN;r++)for(let c=0;c<cols;c++){
    const x=Math.round(9+46*(cols>1?c/(cols-1):.5)+(rnd()-.5)*3);
    const y=Math.round(16+34*(rowsN>1?r/(rowsN-1):.5)+(rnd()-.5)*2);fn(x,y);}};
  if(state==="lush")place(4,3,(x,y)=>stamp(M.lush,P.lush,x,y));
  else if(state==="golden")place(5,3,(x,y)=>stamp(M.wheat,P.wheat,x,y));
  else if(state==="dry")place(5,3,(x,y)=>{stamp(M.dry,P.dry,x,y);if(rnd()<.5*mult+.2)embers.push({x:x+(rnd()<.5?-1:1),y:y-1,w:1,h:1,f:rnd()<.5?"#e2541d":"#ff9a3d"});});
  else if(state==="charred")place(4,3,(x,y)=>{stamp(M.char,P.char,x,y);
    embers.push({x:x,y:y-2,w:1,h:1,f:rnd()<.5?"#ff9a3d":"#e2541d"});
    if(rnd()<.45*mult+.25){const sx=x-1,sy=y-10,grey=["#9a8d76","#b5ab98","#7d7263"];
      for(let p=0;p<6;p++)smoke.push({x:sx+Math.floor(rnd()*4),y:sy+Math.floor(rnd()*5),w:1,h:1,f:grey[Math.floor(rnd()*3)],o:.7});}});
  else if(state==="nodata")for(let i=0;i<6;i++){const x=8+Math.floor(rnd()*48),y=10+Math.floor(rnd()*38);soil.push({x:x,y:y,w:1,h:1,f:"#8a6a3e"});}
  addFence(fence);
  const sway=(state==="lush"||state==="golden");
  return `<svg viewBox="0 0 64 56" preserveAspectRatio="xMidYMid slice" shape-rendering="crispEdges" style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;image-rendering:pixelated">`
    +grp(soil)+grp(crops,sway?"cropsway":"",sway?((seed%5)*0.4):null)
    +grp(smoke,"smoke",(seed%4)*0.5)+grp(embers,"embers",(seed%3)*0.3)
    +grp(sparkle,"sparkle",(seed%3)*0.6)+grp(fence)+`</svg>`;
}
function buildTrough(seed){const rnd=rng(seed*7+13);const soil=[],sparkle=[],fence=[];
  soil.push({x:0,y:0,w:64,h:56,f:"#523620"});
  for(let y=3;y<56;y+=6){soil.push({x:0,y:y,w:64,h:1,f:"#3a2615"},{x:0,y:y+1,w:64,h:1,f:"#62442a"});}
  const tx=11,ty=22,tw=42,th=20;
  soil.push({x:tx,y:ty,w:tw,h:th,f:"#6b4a2b"},{x:tx,y:ty,w:tw,h:2,f:"#8a6a3e"},{x:tx,y:ty+th-2,w:tw,h:2,f:"#3a2615"},
    {x:tx,y:ty,w:2,h:th,f:"#7d5832"},{x:tx+tw-2,y:ty,w:2,h:th,f:"#4f3620"},
    {x:tx+3,y:ty+3,w:tw-6,h:th-7,f:"#2f6fa6"},{x:tx+3,y:ty+3,w:tw-6,h:3,f:"#4f9bd5"},{x:tx+3,y:ty+th-6,w:tw-6,h:2,f:"#23527d"});
  for(let i=0;i<4;i++){const x=tx+5+Math.floor(rnd()*(tw-10)),y=ty+5+Math.floor(rnd()*(th-11));sparkle.push({x:x,y:y,w:2,h:1,f:"#bfe3ff"},{x:x,y:y-1,w:1,h:1,f:"#ffffff"});}
  addFence(fence);
  return `<svg viewBox="0 0 64 56" preserveAspectRatio="xMidYMid slice" shape-rendering="crispEdges" style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;image-rendering:pixelated">`
    +grp(soil)+grp(sparkle,"sparkle")+grp(fence)+`</svg>`;
}
function buildScarecrow(){const o=[];
  o.push({x:7,y:4,w:2,h:24,f:"#6b4a2b"},{x:9,y:4,w:1,h:24,f:"#4a3220"},{x:2,y:11,w:12,h:2,f:"#6b4a2b"},{x:2,y:13,w:12,h:1,f:"#4a3220"},
    {x:1,y:11,w:1,h:4,f:"#e7c24c"},{x:14,y:11,w:1,h:4,f:"#e7c24c"},{x:5,y:13,w:6,h:8,f:"#9a4a2a"},{x:5,y:13,w:6,h:1,f:"#b85a34"},{x:5,y:20,w:6,h:1,f:"#5a2a16"},
    {x:7,y:16,w:2,h:1,f:"#d4a24a"},{x:5,y:5,w:6,h:6,f:"#e7c24c"},{x:5,y:5,w:6,h:1,f:"#f2d873"},{x:6,y:7,w:1,h:1,f:"#2a1c0e"},{x:9,y:7,w:1,h:1,f:"#2a1c0e"},
    {x:7,y:9,w:2,h:1,f:"#8a6a2f"},{x:3,y:4,w:10,h:1,f:"#2a1c10"},{x:5,y:1,w:6,h:3,f:"#52301c"},{x:5,y:1,w:6,h:1,f:"#6b4226"},{x:5,y:3,w:6,h:1,f:"#241208"});
  return `<svg viewBox="0 0 16 28" shape-rendering="crispEdges" style="width:100%;height:100%;overflow:visible;image-rendering:pixelated;filter:drop-shadow(0 2px 2px rgba(0,0,0,.5))">`+rectsSvg(o)+`</svg>`;
}

function cell(d){
  // seed by weekday so a plot's pixel art stays stable regardless of display order
  const seed=(["MON","TUE","WED","THU","FRI","SAT","SUN"].indexOf(d.code)+1)||1;
  const st=d.state||classify(d.pct);   // future days carry a status-derived state
  const proj=d.kind==="projected", today=d.kind==="today";
  const pl=d.pct==null?"—":(proj?"~":"")+d.pct+"%";
  const sl=STN[st];
  const cls="cell"+(proj?" proj":"")+(today?" today":"");
  return `<div class="${cls}">${buildPlot(st,seed,MULT)}`
    +`<div class="chip"><span class="c">${d.code}</span><span class="p">${pl}</span></div>`
    +`<div class="stlabel">${sl}</div>${today?'<div class="nowtag">NOW</div>':""}</div>`;
}
function troughCell(){return `<div class="cell">${buildTrough(99)}`
  +`<div class="stlabel">WATER</div></div>`;}

function renderField(mode){
  const days=SITREP.modes[mode]||[];
  const top=days.slice(0,4).map(d=>cell(d)).join("");
  const bot=days.slice(4).map(d=>cell(d)).join("")+troughCell();
  document.getElementById("rowTop").innerHTML=top;
  document.getElementById("rowBottom").innerHTML=bot;
  const vals=days.map(d=>d.pct).filter(v=>v!=null);
  const peak=vals.length?Math.max(...vals):0;
  const pd=days.find(d=>d.pct===peak&&peak>0);
  document.getElementById("peakV").textContent=peak+"%";
  document.getElementById("peakD").textContent=pd?pd.code:"";
}
function buildToggle(){
  const t=document.getElementById("toggle");
  t.innerHTML=MODE_ORDER.map(m=>`<button class="tbtn" data-m="${m}">${MODE_LABELS[m]}</button>`).join("");
  t.querySelectorAll(".tbtn").forEach(b=>b.addEventListener("click",()=>{
    t.querySelectorAll(".tbtn").forEach(x=>x.classList.remove("on"));
    b.classList.add("on"); renderField(b.dataset.m);
  }));
}
function fmtCd(s){if(s<=0)return"NOW";const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60),x=Math.floor(s%60);
  if(d)return d+"d "+h+"h";if(h)return h+"h "+m+"m";if(m)return m+"m "+x+"s";return x+"s";}
function tick(){const now=Date.now()/1000;document.querySelectorAll("[data-cd]").forEach(el=>{
  const t=parseInt(el.getAttribute("data-cd"));if(!t){el.textContent="—";return;}el.textContent=fmtCd(t-now);});}

document.getElementById("scare").innerHTML=buildScarecrow();
buildToggle();
const dm=SITREP.defaultMode||"current";
document.querySelector('.tbtn[data-m="'+dm+'"]').classList.add("on");
renderField(dm);
tick(); setInterval(tick,1000);

// 8-bit pixel fire (Doom-fire algorithm): yellow core -> orange -> red tips, on transparent.
function initFire(cv){
  const COLS=cv.width, ROWS=cv.height, ctx=cv.getContext("2d");
  const PAL=[[0,0,0,0],[150,24,20,255],[210,32,24,255],[255,52,28,255],[255,96,30,255],[255,140,32,255],[255,180,44,255],[255,214,78,255],[255,236,140,255]];
  const N=PAL.length-1, buf=new Uint8Array(COLS*ROWS), img=ctx.createImageData(COLS,ROWS);
  for(let x=0;x<COLS;x++) buf[(ROWS-1)*COLS+x]=N;
  let ph=0;
  // per-column flame height (0..1), low+high frequency, drifting over time -> peaks and valleys
  function heat(x){ const u=x/COLS;
    return 0.5+0.34*Math.sin(u*9+ph)+0.22*Math.sin(u*23+ph*0.6)+0.13*Math.sin(u*57+ph*1.4); }
  function step(){
    ph+=0.013;
    for(let x=0;x<COLS;x++) buf[(ROWS-1)*COLS+x]= Math.random()<0.88 ? N : N-2;  // flicker the source
    for(let x=0;x<COLS;x++){
      const dp=0.66-0.57*Math.max(0,Math.min(1,heat(x)));   // tall columns decay slower -> reach higher peaks
      for(let y=1;y<ROWS;y++){
        const v=buf[y*COLS+x], rnd=(Math.random()*3)|0;
        let nx=x-(rnd-1); if(nx<0)nx=0; else if(nx>=COLS)nx=COLS-1;
        buf[(y-1)*COLS+nx]= v>0 ? v-((Math.random()<dp)?1:0) : 0;   // rise, drift, height-varied decay
      }
    }
    const d=img.data;
    for(let i=0;i<COLS*ROWS;i++){ const c=PAL[buf[i]], j=i*4; d[j]=c[0];d[j+1]=c[1];d[j+2]=c[2];d[j+3]=c[3]; }
    ctx.putImageData(img,0,0);
  }
  step();
  if(!matchMedia("(prefers-reduced-motion: reduce)").matches) setInterval(step,75);
}

// The sky above the fire: rising embers with an irregular, asymmetric silhouette that grows
// over ~11s, plus a smog layer that thickens and drifts at the top to fill the upper space.
function initSky(cv){
  const ctx=cv.getContext("2d");
  function resize(){ cv.width=window.innerWidth; cv.height=window.innerHeight; }
  resize(); window.addEventListener("resize",resize);
  // jagged per-column height profile: taller flames in some columns, with sharp high-freq variation
  function prof(x){ const u=x/Math.max(1,cv.width);
    let v=(0.5+0.5*Math.sin(u*9.0+0.7)+0.32*Math.sin(u*23.0+2.1)+0.22*Math.sin(u*53.0+5.0)+0.13*Math.sin(u*103.0+1.0))/1.5;
    return Math.max(0.22,Math.min(1.05,v)); }
  // per-column growth delay: some columns ignite/climb earlier than others (asymmetric growth)
  function dly(x){ const u=x/Math.max(1,cv.width);
    return Math.max(0,0.48*(0.5+0.5*Math.sin(u*4.0+2.0)+0.3*Math.sin(u*11.0+0.5))/1.3); }

  const EM=["#ffe7a0","#ffd24a","#ffae26","#ff8a1f","#ff6a1f","#ff3b1f"];
  const EMAX=180, E=[];
  function mkE(top){ const H=cv.height;
    return {x:Math.random()*cv.width, y: top? Math.random()*H : H+Math.random()*30,
            vy:0.3+Math.random()*1.0, ph:Math.random()*6.283, amp:0.4+Math.random()*1.4,
            sz:1+((Math.random()*2)|0), jit:(Math.random()-0.5)*0.22}; }
  for(let i=0;i<EMAX;i++) E.push(mkE(true));

  const S=[], SMAX=54;
  function mkS(){ const W=cv.width,H=cv.height;
    return {x:Math.random()*W, y:Math.random()*H*0.52, r:80+Math.random()*210,
            vx:(Math.random()-0.5)*0.26, ph:Math.random()*6.283, amax:0.2+Math.random()*0.22}; }
  for(let i=0;i<SMAX;i++) S.push(mkS());

  let t=0; const start=performance.now();
  function frame(now){
    const W=cv.width,H=cv.height;
    const grow=Math.min(1,(now-start)/11000);
    const smokeGrow=Math.min(1,(now-start)/16000);
    ctx.clearRect(0,0,W,H); t+=0.016;

    // smog at the top: thickens and drifts over time, band spreads downward
    const band=H*(0.36+0.3*smokeGrow);
    const scount=Math.floor(SMAX*(0.25+0.75*smokeGrow));
    for(let i=0;i<scount;i++){ const p=S[i];
      p.x+=p.vx; if(p.x<-p.r)p.x=W+p.r; else if(p.x>W+p.r)p.x=-p.r;
      const yy=p.y+Math.sin(t*0.4+p.ph)*10;
      const a=p.amax*smokeGrow*(0.78+0.22*Math.sin(t*0.5+p.ph))*(yy<band?1:Math.max(0,1-(yy-band)/200));
      const warm=Math.max(0,Math.min(1, yy/Math.max(1,band)));   // 0 up top -> 1 near the fire
      const col=((60+78*warm)|0)+","+((48+30*warm)|0)+","+((42-10*warm)|0);  // ember-lit near fire, brown up top
      const g=ctx.createRadialGradient(p.x,yy,0,p.x,yy,p.r);
      g.addColorStop(0,"rgba("+col+","+a.toFixed(3)+")");
      g.addColorStop(0.6,"rgba("+col+","+(a*0.6).toFixed(3)+")");
      g.addColorStop(1,"rgba("+col+",0)");
      ctx.fillStyle=g; ctx.beginPath(); ctx.arc(p.x,yy,p.r,0,6.283); ctx.fill();
    }

    // embers with asymmetric ceiling
    const ecount=Math.floor(EMAX*(0.28+0.72*grow));
    for(let i=0;i<ecount;i++){ const p=E[i];
      const eg=Math.max(0,Math.min(1,(grow-dly(p.x))/(1-dly(p.x)+0.001)));   // staggered per column
      p.y-=p.vy*(0.6+1.1*eg);
      const px=p.x+Math.sin(t*1.25+p.ph)*p.amp*1.6;
      const ceiling=H*(1-eg*Math.max(0.05,Math.min(1.1,prof(p.x)+p.jit)));
      if(p.y<ceiling||p.y<-4){ E[i]=mkE(false); continue; }
      const frac=(H-p.y)/Math.max(1,H-ceiling);
      ctx.globalAlpha=Math.max(0,0.92-frac*0.92);
      ctx.fillStyle=EM[Math.min(EM.length-1,(frac*EM.length)|0)];
      ctx.fillRect(px|0,p.y|0,p.sz,p.sz);
    }
    ctx.globalAlpha=1; requestAnimationFrame(frame);
  }
  if(!matchMedia("(prefers-reduced-motion: reduce)").matches) requestAnimationFrame(frame);
}

if(document.body.classList.contains("burn")){
  document.querySelectorAll(".pagefire").forEach(initFire);
  document.querySelectorAll(".pageembers").forEach(initSky);
}
</script>
</body></html>"""
