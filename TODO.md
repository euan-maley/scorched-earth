# TODO

## Current Session — sitrep + modeling fixes + fire

Sitrep (`scorch --sitrep`):
- [x] HTML sitrep: 8-bit war / scorched crop-field HUD; THE FIELD = Stardew pixel farm (engine ported from the design handoff)
- [x] Field view toggle: LAST WEEK / AVERAGE / THIS WEEK (this-week = actual-so-far + projected-ahead)
- [x] Field ordered by reset cycle (left = fresh reset day, right = pre-reset) + START/RESET cycle labels
- [x] THIS WEEK future days colored by projected burn STATUS (charred = scorched-earth, golden = fence, lush = no-limit)
- [x] Plain-English explainer line under every stat; live "active hours" in the meta line
- [x] Burn mode (green only): full-page pixel fire (Doom-fire, varied column heights), rising embers (asymmetric, jagged), thickening ember-lit smog up top, ember panel glow, "🔥 BURN IT ALL" fire-gradient

Modeling fixes (apply to statusline + CLI + sitrep):
- [x] Sleep-aware windows: usable windows = raw x (active hours / 24); active hours LEARNED from history (16h fallback)
- [x] R calibration guardrails: plausible band (1–20%) + need >=3 clean pairs before trusting (fixed a noisy 0.25 flipping verdict)
- [x] Forecast capped by physical capacity (projected leftover never understated); report recomputes rec + forecast live
- [x] Canonical war-general HEADLINE moved to core.py, shared by CLI + sitrep (no drift)

## Earlier Session

- [x] Scaffold kerd structure + git
- [x] Core burn-rate math module + state/calibration
- [x] `scorch` CLI (hard signal + forecast, manual overrides)
- [x] Statusline segment + wire into ~/.claude/statusline.sh
- [x] Package: skill + plugin manifest + installer with light-style options
- [x] Habits/forecast: day-of-week profile, projection, preemptive once-per-week nudge
- [x] Plugin packaging: SessionStart hook wires statusline (wraps existing), bin/skill auto-discovered, `scorch --style`
- [x] Verdict: ship all three layers as one plugin (statusline engine + CLI + skill); see CLAUDE.md packaging facts

- [x] Marketplace entry (`.claude-plugin/marketplace.json`, single-repo `source: "./"`)

## Readiness Audit (2026-06-24) — fixed before publish

Multi-agent audit (correctness / safety / packaging / testing / arch / design+dx / concept):
- [x] **Correctness:** windows_left straddle over-count (credited next-week capacity); forecast cold-start rate inflation + >7d-out reset; concurrent-statusline `.tmp` write race (now pid-unique); report dead-code weeks bug
- [x] **Safety/robustness:** report KeyError on unknown level; tolerant `Snapshot.from_dict` (schema drift no longer crashes CLI/report); state files now `0600`
- [x] **DX/UX honesty:** partial manual flags now error instead of silently ignoring; `--report` refuses to fabricate a zeros dashboard before any reading; cross-platform open (`xdg-open`) + notify (`notify-send`)
- [x] **Docs truth:** SKILL.md "SCORCH"→"BURN IT ALL" + fire style listed; default-style clarified (fire seeded at install); the-math.md default-R note + multi-bucket caveat; playbook test count; README placeholders + platform note + light states
- [x] **Tests/CI:** 33→57 checks (straddle, verdict-flip regression, cold-start, from_dict, report render, state round-trip + corruption recovery, statusline never-errors invariant); harness collects failures instead of aborting; GitHub Actions CI added
- [x] **Packaging:** `pyproject.toml` (python ≥3.8 floor); gradient.py documented in CLAUDE.md
- [x] **Add a git remote + push** (private GitHub)

## Backlog

- [ ] Before public launch: untrack `kivna/` + `.slainte` (kept now to preserve the kerd git-handoff; they'd ship in the plugin clone once public)
- [ ] `scorch --watch` live re-print (flag exists; field-test it)
- [ ] Optional: surface the 🔥 forecast nudge on the statusline too (not just notify)
- [ ] Let users tune "active hours" manually (currently learned only)
- [ ] Fire perf: it's canvas-animated; consider pausing when tab hidden (visibilitychange)
- [ ] R/active-hours still learning on this machine (~2 readings); sharpen over a couple weeks
