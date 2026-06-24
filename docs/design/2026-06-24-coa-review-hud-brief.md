# Design Brief: After-Action Report (COA runner review) HTML mockup

**For:** Claude design (HTML mockup generation)
**Date:** 2026-06-24
**Context:** Scorched Earth, a Claude-usage tool. This brief is for the **runner review** — the surface you watch *while* the autonomous queue-runner works and wake up to *after*. It is the third sibling of the existing **sitrep** and **COA** reports and must feel like the same product.

## What this is

Scorched Earth signals when to burn down your weekly Claude budget. The COA advisor produces a ranked work plan (the **Course of Action**); the **queue-runner** then drains that plan autonomously on your machine overnight — each job runs headless in an isolated git worktree, under a sandbox, with a test gate. This report is the **After-Action Report (AAR)**: the outcome of that run.

It has a crucial twist the COA report does not: it is **live**. The runner rewrites it after every job, so the *same file* is both the thing you monitor mid-run (jobs filling in one by one, one currently "on fire") and the final debrief you read in the morning. There is no server — while the run is in progress the page simply refreshes itself; when the run finishes, the runner re-renders it one last time without the refresh.

The renderer will be `src/scorched_earth/review_report.py` (`render_review_html`). You design the template it fills.

## Visual language (match the sitrep & COA)

Same 8-bit war / scorched-earth aesthetic. Reuse it exactly so the three reports read as one product.

- **Palette:** background `#0b0705`; fire accents `#ff3b1f`, `#ff6a1f`, `#ff8a1f`, `#ffd24a`, `#ffe7a0`; muted text `#f4e4c8` / `#e9c08a`; HUD teal `#86abab` / `#6f8a8a`; charred `#1a120b`; soil/brown `#6b4a2b`. Add a **secured/green** for passed jobs (a lush crop green, e.g. `#7bb04a` / `#9fd36a`) — this is the one report where "success" has its own color.
- **Type:** monospace, pixel feel (`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`), wide letter-spacing on headings.
- **Frame:** corner HUD brackets, faint CRT scanline overlay, vignette — same as the sitrep/COA panel.
- **Headline treatment:** the title uses the animated fire-gradient sweep (the `.firetext` effect, as on "BURN IT ALL").
- **Register:** military. This report's name is **AAR = After-Action Report** (the debrief of an operation). Voice is a war-general reviewing the battlefield. The metaphor is **battle-damage assessment of the field after the burn**: ground that was taken, ground that was cratered, ground left untouched.

Existing assets to draw from (same repo / same look): the sitrep HTML (`src/scorched_earth/report.py` — pixel-farm field, HUD stat cards, scanline/vignette/corner frame, burn-mode fire) and the COA template (`src/scorched_earth/coa_template.html` — the mission-card list, the ammo/envelope gauge, the JSON-blob template contract).

## What the report must present

An AAR is a run state, a budget envelope (estimated), and a list of jobs each with its outcome.

1. **Header.** "AFTER-ACTION REPORT", a sector/date stamp (e.g. `// SECTOR 07 · 2026-06-24 03:14`), corner-bracket frame, fire-gradient title. While the run is live, the header reads as an **operation in progress** (e.g. a pulsing "● OPERATION LIVE" tag); when done, it reads settled ("OPERATION COMPLETE").

2. **The run banner (state at a glance).** One line that tells you instantly where things stand: jobs done / total, how many passed / failed / blocked, and the **estimated** budget spent. Because the runner cannot measure live usage, budget is always labeled *estimated* (e.g. "~2.0 of 2.5 windows · estimated"). Show it as an ammo/fuel gauge like the COA's envelope, but here it represents **spent so far**, draining as the run proceeds.

3. **The objectives list (the heart — battle-damage assessment).** The jobs, in run order. Each job is one objective card showing:
   - a rank/sequence number,
   - the **title** and **type** tag (test / docs / refactor / audit / …),
   - a **tier badge** (S / M / L / XL),
   - the **outcome**, which drives the card's whole visual state (see below),
   - the **branch** it produced (`scorched/<job-id>`, monospace),
   - a **diffstat** (files changed, +insertions / −deletions) — the "ground taken",
   - **estimated windows spent**,
   - a one-line **note** (e.g. the gate command that failed, or why it was blocked),
   - **merge / discard** commands (monospace, copyable — same COPY-button pattern as the COA's launch commands). These are *copyable git commands* in this version, **not** live buttons (live buttons are a later phase).

   **Outcome states — each should look distinct on the field:**
   - `running` — **on fire**: the active fire accent, a pulsing/animated ember, "WORKING…". This is the one currently being executed. At most one card is `running`.
   - `pass` — **secured / harvested**: the green crop color, a planted-flag feel, gate ✓. Ground taken.
   - `fail` — **cratered / scorched**: charred, damaged, gate ✗. Branch kept for inspection. Render it as a burn scar, not an error dialog.
   - `blocked-roe` — **fenced off**: dimmed with a fence/barrier motif and an "ROE" stamp. The rules forbade running it unattended; it was never started.
   - `skipped-budget` — **forfeit / out of ammo**: dimmed like the COA's spillover; "no budget left". The run ran out of envelope before reaching it.
   - `pending` — **queued, not yet reached**: faint outline, waiting its turn (only meaningful while live).

4. **The verdict line.** A commander's one-line summary of the run (e.g. "3 secured, 1 cratered, 1 forfeit. ~2.0 windows spent."), styled as the after-action conclusion.

Optional flourish if it fits without clutter: a tiny **field strip** echoing the sitrep — one cell per job, colored by outcome (green secured / charred fail / fenced blocked / dim forfeit / fire running) — a one-glance battlefield map of the whole run.

## Technical constraints (important)

- **Single self-contained HTML file.** No external assets, fonts, CDNs, or network calls. All CSS/SVG/JS inline. Opens offline; ships in the plugin.
- **It is a template, not a one-off.** Python computes the data and injects it; JS renders. Follow the COA/sitrep pattern exactly: a single JSON blob assigned to `const AAR = {…}` near the bottom, replaced by Python (or a `__REVIEW_JSON__` token) at render time. All data access goes through that one object so the Python side has a clean seam.
- **Live refresh, done cleanly.** When `AAR.state === "running"`, the page must auto-refresh every `AAR.refreshSeconds` seconds — emit a `<meta http-equiv="refresh" content="…">` (or an equivalent inline timeout that reloads). When `AAR.state === "done"`, **no refresh** — the page is static and final. The runner re-renders the whole file after each job and once more at the end; you do not fetch anything, you just render the object you're given and set the refresh based on `state`.
- **Determinism / no clock:** the timestamp is passed in preformatted (`generatedAt`); do not call `Date()` for it. No live JS countdowns needed.
- **Respect `prefers-reduced-motion`:** the running-job fire/ember and any animation must freeze under it.
- **Responsive enough** to read at ~640 to 1100px wide.

## Data contract

Design the JS against exactly this shape (Python fills it). Numbers are window-units except `value` and diffstat counts.

```js
const AAR = {
  generatedAt: "2026-06-24 03:14",
  state: "running",                 // "running" | "done"  -> drives header + auto-refresh
  refreshSeconds: 6,                // only used while state === "running"
  sector: "SECTOR 07",
  repo: "~/wake-up",
  verdict: "GREEN",                 // GREEN | AMBER | OFF | UNKNOWN -> header accent
  note: "2 secured so far · 1 working · ~1.5 of 2.5 windows.",
  envelope: { available: 2.5, spentEstimated: 1.5 },   // spent drains the gauge; labeled "estimated"
  jobs: [
    { seq: 1, id: "cov-core", title: "Exhaustive test coverage for core/", type: "test",
      tier: "L", outcome: "pass", branch: "scorched/cov-core",
      estWindows: 1.0, diff: { files: 6, insertions: 240, deletions: 12 },
      note: "gate: 82 checks passed.",
      mergeCmd: "git -C ~/wake-up merge scorched/cov-core",
      discardCmd: "git -C ~/wake-up worktree remove .scorched/wt/cov-core && git -C ~/wake-up branch -D scorched/cov-core" },

    { seq: 2, id: "err-audit", title: "Harden error handling in the I/O layer", type: "audit",
      tier: "M", outcome: "fail", branch: "scorched/err-audit",
      estWindows: 0.5, diff: { files: 3, insertions: 60, deletions: 40 },
      note: "gate FAILED: test_io.py::test_retry — branch kept for triage.",
      mergeCmd: "git -C ~/wake-up merge scorched/err-audit",
      discardCmd: "git -C ~/wake-up worktree remove .scorched/wt/err-audit && git -C ~/wake-up branch -D scorched/err-audit" },

    { seq: 3, id: "perf-render", title: "Profile + speed up the render pipeline", type: "perf",
      tier: "M", outcome: "running", branch: "scorched/perf-render",
      estWindows: 1.0, diff: null, note: "WORKING…",
      mergeCmd: null, discardCmd: null },

    { seq: 4, id: "rewrite-cli", title: "Rewrite the CLI arg parser", type: "refactor",
      tier: "L", outcome: "blocked-roe", branch: null,
      estWindows: 1.5, diff: null,
      note: "type 'refactor' is not in unattended_types — not run.",
      mergeCmd: null, discardCmd: null },

    { seq: 5, id: "docs-sweep", title: "Doc-comment sweep across modules", type: "docs",
      tier: "S", outcome: "skipped-budget", branch: null,
      estWindows: 0.5, diff: null,
      note: "no budget left when reached.",
      mergeCmd: null, discardCmd: null }
  ]
};
```

Notes on fields:
- `state` drives both the header treatment and whether the page auto-refreshes. The same template renders the live monitor and the final debrief.
- `outcome` drives each card's visual state (the six states above). At most one job is `running`; `pending` cards may appear while live.
- `diff` is `null` for jobs that produced no branch (running/blocked/skipped) — render a placeholder, not zeros.
- `mergeCmd` / `discardCmd` are `null` unless the job produced a branch worth acting on (i.e. `pass` or `fail`).
- Budget is **always** estimated — never imply it was measured. Keep the "estimated" qualifier visible near the gauge.

## Deliverable

One self-contained `review.html` mockup, populated with the sample `AAR` above (use the `state: "running"` sample so the live treatment is visible; note in a comment how `state: "done"` should drop the refresh and settle the header). We drop it in as the template `render_review_html` fills. Match the sitrep/COA frame, palette, type, and fire treatment so all three reports read as one product. We wire the Python injection and the per-job re-render on our side; you own the look, the six outcome states, the live-vs-done behavior, and the JS that turns `AAR` into the layout.
