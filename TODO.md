# TODO

## Current Session — COA advisor (Phase 1 BUILT, Phase 2 next) · branch `feat/burn-advisor` (LOCAL, unpushed)

New feature: the **COA advisor** — turns the budget signal into actionable work. Link repos →
adversarial+constructive scan agent finds expensive jobs → pure-Python tier-and-fill matcher
sizes them to the available burn → ranked Course of Action (MD record + war-HUD HTML). All on
`feat/burn-advisor`, kept **local and unpushed** by choice so public `main` stays clean.

Phase 1 (advisor) — DONE, brainstormed → spec → plan → built via subagent-driven dev:
- [x] Modules: `jobs.py` (schema), `roe.py` (rules of engagement), `advisor.py` (tier-and-fill matcher), `coa_report.py` (MD + HTML), `coa_io.py` (registry/ROE/jobs/COA I/O, JSON throughout)
- [x] CLI verbs `scorch link|advise|roe`; standalone `/coa` + `/roe` commands
- [x] War-HUD HTML template `coa_template.html` (from design handoff) wired into `render_html`; per-job **COPY** buttons (clipboard + execCommand fallback)
- [x] Scan-agent **personality** defined (spec + `/coa`): fit-for-burn-window (compute-hungry, bounded/verifiable, low-coordination, batchable), ground in user intent first, adversarial fills gaps, additive-leaning for autonomy, size to tokens, skip trivia
- [x] Dogfooded live vs `~/wake-up` (green, 1.4 win): grounded suggestions, tier-and-fill forfeits big high-value jobs that don't fit; **surfaced + fixed** the `.gitignore`-on-link gotcha
- [x] 25 advisor checks + 57 existing, both green; final whole-branch review: Ready to merge
- Spec: `docs/superpowers/specs/2026-06-24-coa-advisor-design.md`; plan: `docs/superpowers/plans/2026-06-24-coa-advisor-phase1.md`; SDD ledger + Phase-1 Minor findings: `.superpowers/sdd/progress.md`

**What's next — Phase 2** (brainstorm was just initiated, resume there):
- [ ] Queue-runner: drain the COA queue, autonomous local exec with guardrails (worktree/branch isolation, commit-not-push, tests-after, re-check budget between jobs, morning-after review surface). Execution path B.
- [ ] `scorch coa --serve` bridge: localhost server, **Queue** then **Run** buttons; security model (bind 127.0.0.1, one-time token, accept only COA job-ids not raw commands, enforce ROE server-side) is in the spec's Phase-2 section.
- Phase 3 (later): scheduling + cloud routine.

Voice/approach decisions (don't lose): officer-briefs-you (not commander barking); additive-leaning for unsupervised runs (transformative = review-required); JSON config; standalone commands. Phase-1 Minors deferred to backlog (roe_from_dict null-clear; advisor epsilon side; render_md markdown-fidelity escaping; write_coa plain open).

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

- [x] Pre-public prep: MIT `LICENSE` file added; `homepage`/`repository` in `plugin.json`; untracked `kivna/` + `.slainte` (gitignored, kept local — no second machine so the handoff loss is fine). Repo is publish-clean except for the deliberate choice to leave `TODO.md` tracked.
- [x] **Published public** (2026-06-24). Logo + landscape banner, sitrep screenshots, embedded mp4 player in the README, `/sitrep` command. README skriv-passed.
- [x] Slimmed git history: stripped dead demo binaries (old gif/webm, burn/poster PNGs) via `filter-branch` + force-push. `.git` 20M → 7.1M (fresh clones get the small pack; GitHub's reported size lags until their server gc). Pre-strip backup bundle at `~/Downloads/scorched-earth-preslim.bundle`.
- [ ] `scorch --watch` live re-print (flag exists; field-test it)
- [ ] Optional: surface the 🔥 forecast nudge on the statusline too (not just notify)
- [ ] Let users tune "active hours" manually (currently learned only)
- [ ] Fire perf: it's canvas-animated; consider pausing when tab hidden (visibilitychange)
- [ ] R/active-hours still learning on this machine (~2 readings); sharpen over a couple weeks
