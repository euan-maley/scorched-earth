# Design Brief: COA Cockpit HTML

**For:** Claude design (HTML mockup generation)
**Date:** 2026-06-24
**Context:** Scorched Earth, a Claude-usage tool. This brief is for the **COA Cockpit** — the live command surface you use to enqueue, reorder, and monitor jobs while the autonomous queue-runner drains them. It is the fourth sibling of the sitrep, COA report, and AAR, and must feel like the same product.

## What this is

Scorched Earth signals when to burn down your weekly Claude budget. The COA advisor builds the work plan; the queue-runner drains it overnight. The **COA Cockpit** is the browser UI that bridges the two: a live, event-driven kanban board served on localhost that lets you drag proposed jobs into the queue, reorder the queue, stop or resume the runner, and watch jobs transition through states in real time.

The cockpit is served by `scorch coa --serve`, which starts a `make_server`-based localhost server (see `src/scorched_earth/coa_serve.py`). `render_cockpit(token, state)` fills the template and returns UTF-8 bytes. The page then keeps itself live via a Server-Sent Events (SSE) stream — no full reloads.

## Visual language (match the sitrep, COA, and AAR)

Same 8-bit war / scorched-earth aesthetic. Reuse it exactly so all four surfaces read as one product.

- **Palette:** background `#0b0705`; fire accents `#ff3b1f`, `#ff6a1f`, `#ff8a1f`, `#ffd24a`, `#ffe7a0`; muted text `#f4e4c8` / `#e9c08a`; HUD teal `#86abab` / `#6f8a8a`; charred `#1a120b`; soil/brown `#6b4a2b`; secured/green for finished-pass jobs `#7bb04a` / `#9fd36a`.
- **Type:** monospace, pixel feel (`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`), wide letter-spacing on headings.
- **Frame:** corner HUD brackets, faint CRT scanline overlay, vignette — same as the sitrep/COA/AAR panel.
- **Headline treatment:** the title uses the animated fire-gradient sweep (the `.firetext` effect, as on "BURN IT ALL" and the AAR header).
- **Register:** military. The cockpit is the **operations room**: the general watching the board, moving pieces, issuing orders. Voice is terse, command-oriented.
- **Respect `prefers-reduced-motion`:** all fire/ember animations must freeze under it.

## What the cockpit must present

The cockpit is a **four-column kanban board** with a **per-repo tab toggle** when multiple repos are registered.

### Layout

1. **Header.** "COA COCKPIT", a sector/date stamp, corner-bracket frame, fire-gradient title. Show a `● LIVE` tag (pulsing) while the engine is busy; `● IDLE` when not.

2. **Repo tabs.** When `STATE.repos` has more than one entry, render a tab strip — one tab per repo (labeled `repo.name`). Active tab shows that repo's kanban columns. Single-repo installs skip the tab strip.

3. **Kanban columns (four, left to right):**
   - **PROPOSED** — jobs available to queue (from `repo.proposed`). Draggable out into QUEUED.
   - **QUEUED** — jobs waiting to run (from `repo.queued`). Draggable to reorder within the column.
   - **RUNNING** — at most one card, the currently executing job (from `STATE.running` where `running.repo === repo.repo`). Not draggable.
   - **DONE** — completed jobs (from `repo.finished`). Pass cards in secured/green, fail cards charred.

4. **Job cards.** Each card shows: `id` (monospace, small), `title`, `type` tag, and — for DONE cards — the outcome badge (SECURED / CRATERED).

5. **Status bar.** A one-line footer: jobs done / total, budget spent estimated, engine state (IDLE / WORKING / STOPPED).

### Interactions

- **Drag Proposed → Queued:** fires `POST /queue` with `{repo, id}`. The card appears at the bottom of QUEUED.
- **Drag to reorder within Queued:** fires `POST /reorder` with `{repo, ids}` (the new full ordered id list).
- **Stop button (header):** fires `POST /stop`.
- **Run button (header):** fires `POST /run` with `{repo}` for the active repo tab.
- All POSTs carry the `X-Scorch-Token` header. The body contains **job ids only** — never commands, never shell strings.

### Live updates (SSE)

On connect the page opens `GET /events?t=TOKEN` (same-origin EventSource). The server emits `event: board` whenever board state changes (job enqueued, job started, job finished, stop/run). On each `board` event the page **patches the DOM in place** — no full reload, no flicker. The `render(state)` function is idempotent: call it with the new state and it rebuilds only what changed.

## Security note

Every POST sends the `X-Scorch-Token` header (value = `TOKEN`). The server validates it; absent or wrong token → 403. The body carries **job ids only**. The server never reads `cmd`, `launch`, or any shell-string field from the body — those fields are ignored even if sent. The cockpit HTML must never construct or send shell commands.

## Data contract

The template is filled once by `render_cockpit(token, state)`, which substitutes two injection sites and returns UTF-8 bytes. All subsequent board updates arrive via SSE and are handled entirely in JS.

```js
const TOKEN = __COCKPIT_TOKEN__;   // injected: JSON-encoded string, e.g. "abc-123"
const STATE = __COCKPIT_JSON__;    // injected: the board state object (see shape below)
```

`render_cockpit` does a literal string replacement of the tokens `__COCKPIT_TOKEN__` and `__COCKPIT_JSON__` with `json.dumps(token)` and `json.dumps(state)` respectively. The template must contain each token exactly once (at the two `const` assignment sites above) and nowhere else — not in comments, not in strings.

### `state_json` shape

```js
{
  repos: [
    {
      repo: "/abs/path/to/repo",      // unique key; used in POST bodies
      name: "my-project",             // display label (basename or configured)
      proposed: [                     // jobs not yet queued
        { id: "cov-core", title: "Exhaustive test coverage for core/", type: "test",
          est_windows: 1.5, value: 9 }
      ],
      queued: [                       // jobs waiting to run, in order
        { id: "err-audit", title: "Harden error handling", type: "audit",
          est_windows: 1.0, value: 7 }
      ],
      finished: [                     // completed jobs (pass or fail only, not skipped)
        { id: "d1", title: "Done1", type: "perf", tier: "M",
          outcome: "pass", est_windows: 1.0, branch: "scorched/d1" },
        { id: "d2", title: "Done2", type: "test", tier: "S",
          outcome: "fail", est_windows: 0.5, branch: "scorched/d2" }
      ]
    }
  ],
  running: { repo: "/abs/path/to/repo", id: "err-audit" } | null,
  busy: true | false
}
```

### Sample STATE (for populating the design mockup)

```js
const STATE = {
  repos: [
    {
      repo: "/Users/ops/wake-up",
      name: "wake-up",
      proposed: [
        { id: "perf-render", title: "Profile + speed up render pipeline", type: "perf", est_windows: 1.0, value: 6 },
        { id: "rewrite-cli", title: "Rewrite the CLI arg parser", type: "refactor", est_windows: 1.5, value: 5 }
      ],
      queued: [
        { id: "err-audit", title: "Harden error handling in I/O layer", type: "audit", est_windows: 1.0, value: 7 }
      ],
      finished: [
        { id: "cov-core", title: "Exhaustive test coverage for core/", type: "test", tier: "L",
          outcome: "pass", est_windows: 1.0, branch: "scorched/cov-core" },
        { id: "docs-sweep", title: "Doc-comment sweep across modules", type: "docs", tier: "S",
          outcome: "fail", est_windows: 0.5, branch: "scorched/docs-sweep" }
      ]
    },
    {
      repo: "/Users/ops/tools",
      name: "tools",
      proposed: [
        { id: "add-lint", title: "Add lint step to CI", type: "test", est_windows: 0.5, value: 4 }
      ],
      queued: [],
      finished: []
    }
  ],
  running: { repo: "/Users/ops/wake-up", id: "err-audit" },
  busy: true
};
```

## Deliverable

One self-contained HTML file that replaces `src/scorched_earth/cockpit_template.html` with no Python change. It must:

1. Assign `const TOKEN = __COCKPIT_TOKEN__;` and `const STATE = __COCKPIT_JSON__;` exactly as written (these are the injection sites).
2. Open `GET /events?t=TOKEN` as an EventSource and apply `event: board` payloads via in-place DOM patching (no full reload).
3. Render the four-column kanban per repo, with the tab strip for multi-repo installs.
4. Support drag-from-Proposed-to-Queued (POST /queue) and drag-to-reorder-within-Queued (POST /reorder), with `X-Scorch-Token` header on every POST.
5. Show a Stop / Run button in the header wired to POST /stop and POST /run.
6. Match the war-HUD identity: AAR palette, corner-bracket frame, scanline overlay, `.firetext` title, monospace type.
7. Freeze all animation under `prefers-reduced-motion`.
8. Be fully self-contained: no external assets, fonts, CDNs, or network calls (the same-origin EventSource and POSTs to `/events`, `/queue`, `/reorder`, `/run`, `/stop` are fine).

We drop it in as the template `render_cockpit` fills. We own the Python injection; you own the look, the kanban interactions, the SSE live-patch logic, and the military-operations-room feel.
