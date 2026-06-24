# COA Live Cockpit (Phase 2b) — Design Spec

**Date:** 2026-06-24
**Branch:** `feat/burn-advisor` (local, not pushed until ready to ship)
**Status:** Design approved in brainstorming, pending implementation plan.

## The idea

Phase 1 produces a plan (the COA, with COPY buttons). Phase 2a runs it autonomously and emits a
live-updating After-Action Report — but as a *static file the browser polls*, a one-way mirror:
a click has nowhere to go. The **cockpit** closes that loop. `scorch coa --serve` runs a tiny
localhost server that turns the report into one **live, interactive kanban board**: drag a job
into the queue, reorder what burns first, hit Run, and watch cards advance Proposed → Queued →
Running → Secured/Cratered in place as work completes.

It unifies today's two separate HTMLs (the COA plan and the AAR debrief) into a single served
cockpit. The static COA/AAR files remain as the no-server fallback; `--serve` is the live upgrade.

## Scope

**In scope:**
- A localhost server (`scorch coa --serve [<repo>]`) with the mandatory security model.
- One unified cockpit board: a per-repo tab toggle across the top; four columns per repo.
- Live updates pushed to the browser (SSE); in-place DOM patching (no full-page reload).
- Token-guarded mutations: queue / unqueue / reorder / run / stop — job-ids only, never commands.
- An **event-driven** execution engine (one `advance` step, no background loop) reusing Phase 2a's
  sandboxed `execute_job`, with a **refreshing budget envelope** checked at pick time.

**Out of scope (later):**
- Multiple repos draining at once (one job runs at a time, globally — budget is one pool).
- Phase 3: scheduling + the cloud-routine execution path.
- Mid-task interactivity beyond queue/run/stop (no live log streaming in v1; the AAR card +
  diffstat is the per-job result surface).

## The board

One served HTML cockpit (`cockpit_template.html`), same scorched-earth war-HUD identity as the
sitrep / COA / AAR. **Tabs across the top — one per linked repo** — toggle which repo's board is
shown. Each repo's board is a kanban with four columns:

```
PROPOSED   →   QUEUED   →   RUNNING   →   SECURED / CRATERED
```

- **Proposed** — jobs from the latest COA not yet queued.
- **Queued** — `queue.json`, in run order (top drains first).
- **Running** — the one job currently executing (at most one, globally).
- **Secured / Cratered** — finished jobs (pass / fail), each with diffstat + copyable
  merge/discard commands (the AAR's per-job treatment).

Cards reuse the AAR identity: tier badge, type tag, est-windows, the six outcome colors.
**Drag** a Proposed card into Queued = enqueue; **drag within Queued** = reorder. Reordering
overrides the advisor's tier-and-fill rank — deliberate; the user gets agency over what burns
first. Cards blocked by ROE (`unattended_types`) show fenced in Proposed and cannot be queued
for autonomous run.

## Execution engine — event-driven, no background loop

This is the heart, and it is deliberately **not** a continuously-running daemon (no `while True`,
no polling timer). It is a single step function, called only on real events:

```
advance(repo):
    if a job is already running:            return        # one-at-a-time guard
    job = first card in queue.json that fits the envelope and ROE
    if no such job:                         return        # idle: nothing to do
    mark BUSY; remove job from queue.json
    run job via Phase 2a execute_job (sandboxed worktree, pre-warm, gate)
    record outcome into the RunResult; broadcast to the board
    clear BUSY
    advance(repo)                            # chain to the next card
```

`advance` is invoked on exactly three triggers: **Run pressed**, a **job completing** (the
chain link), and a **card dragged into Queued while idle**. There is no other clock. The BUSY
flag is **global** (one job across all repos, since budget is one pool): the chain re-calls
`advance` for the *same* repo whose job just finished; starting a different repo's queue is a
user action (Run on that tab) once the active repo is idle or Stopped — it never auto-hands-off.

**Why it cannot run away** (the four guards):
1. **One job at a time** — a BUSY flag blocks re-entry; no concurrency, no overlapping runs.
2. **A card is removed from `queue.json` the instant it is picked** — the same job can never run
   twice; no repeat loop.
3. **It terminates by default** — empty queue, exhausted budget, or Stop → `advance` returns and
   nothing is scheduled. Idle is the resting state; running is the exception.
4. **A failed job is recorded and dropped, not retried** — no crash-retry-crash loop.

**Stop** (`POST /stop`) sets a flag the chain checks before the next pick: the current job finishes,
then `advance` returns instead of chaining. **One job runs at a time globally** — budget is a
single weekly pool, so switching which repo drains means Stop, then Run on the other tab.

### Refreshing budget envelope (checked at pick time, not on a timer)

The server cannot read live `rate_limits` (statusline-only). So at the moment `advance` is about
to pick a card:

```
available = current_snapshot.windows_left − predictive_spend_since(current_snapshot)
```

The engine **predicts** spend between snapshots (decrement `est_windows` as each job runs). When
an interactive Claude Code session refreshes `state.json` (the snapshot timestamp advances), that
new `windows_left` is ground truth from `rate_limits` — it already reflects the engine's real
headless burn — so the engine **resets `predictive_spend` to 0 and re-syncs** to the new figure.
Predict between snapshots; re-sync to truth on every refresh. If `available` won't fit the next
card, it idles (cards sit in Queued marked "waiting — over budget"); nothing runs until budget
refreshes out-of-band (the user's own Claude Code usage) and a later event re-triggers `advance`.
Spend is always labeled **estimated**, never claimed as measured (the Phase 2a honesty rule).

## Server architecture (stdlib, in-process)

`scorch coa --serve [<repo>]` starts a `ThreadingHTTPServer` bound to **127.0.0.1** on an
ephemeral port, mints a **one-time token**, prints the tokened URL, and opens the browser. It is
the host for the execution engine (calls `execute_job` on a worker thread; the chain runs there
so the HTTP handlers stay responsive). It serves the cockpit and these endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | the cockpit HTML (token embedded for same-origin calls) |
| `/state` | GET | full board state JSON (all repos: proposed + queued + run history) |
| `/events` | GET | **SSE** stream: pushes a board-state event on every mutation and every `advance` step |
| `/queue` | POST | `{repo, id}` → Proposed → Queued (append to `queue.json`); triggers `advance` if idle |
| `/unqueue` | POST | `{repo, id}` → Queued → Proposed (remove from `queue.json`) |
| `/reorder` | POST | `{repo, ids[]}` → rewrite `queue.json` order (drag) |
| `/run` | POST | `{repo}` → trigger `advance(repo)` |
| `/stop` | POST | set the stop flag |

Live updates use **SSE** (a long-lived `text/event-stream` HTTP response — pure stdlib, no
websocket library). The server holds the set of connected `/events` clients and writes a
`board-state` event to each whenever anything changes. The browser **patches the DOM** (moves the
affected cards), so an in-progress drag is never interrupted by a reload — this replaces the AAR's
`<meta refresh>` for the served view.

## Security model (mandatory — load-bearing)

A localhost endpoint that runs autonomous commands is an attack surface any browser tab (or local
process) can hit. The controls:

- **Bind 127.0.0.1 only** — never `0.0.0.0`; not reachable off-host.
- **One-time token** minted at launch, required on **every** request — query param for `GET /events`
  and `/`, an `X-Scorch-Token` header (or body field) for POSTs. Wrong/absent token → `403`.
- **Job-ids only, never commands** — a mutation/run names a job by `id`; the server runs **only the
  agent-supplied `launch` for a job-id that exists in the COA/queue it loaded**. A command string in
  a request body is ignored. The browser can name a job; it can never inject a command.
- **ROE enforced server-side** — `unattended_types` leash, cost caps, per-job ceiling all re-checked
  on the server at pick time, regardless of what the page sends.
- **Short-lived** — the server dies on Ctrl-C; it is a foreground process the user runs and closes,
  not a background service.
- The sandbox (Phase 2a) still contains every executed job; `--serve` adds a *trigger* surface, not
  a new execution path — execution is still `execute_job` with the full containment stack.

## Module structure (building on Phase 2a)

Keeps `core.py` / statusline untouched (invariant). The server and engine are I/O tier.

| Module | Role |
|--------|------|
| `coa_serve.py` (new) | The localhost server: routing, token mint/check, SSE client registry + broadcast, POST handlers, the worker thread that hosts the `advance` chain. |
| `cockpit_template.html` (new) | The unified board — tabs, four columns, drag, the SSE client that patches the DOM. From a design handoff (a brief, like the AAR). One JSON blob + token injected by Python. |
| `runner.py` (extend) | Extract the per-job unit `run_one(repo, job, roe, base_sha) -> JobOutcome` out of `run_queue`. Add `advance(...)`-style step logic usable by the server: pick-next + refreshing-envelope. The batch `run_queue` stays for the `scorch coa run` CLI (built on `run_one`). |
| `coa_io.py` (extend) | `unqueue(repo, id)`, `reorder(repo, ids)` queue ops (alongside `enqueue`); a board-state assembler that gathers Proposed (COA minus queued) + Queued (`queue.json`) + finished (last `RunResult`) for a repo. |
| `bin/scorch` | The `coa --serve [<repo>]` verb. |
| design brief | `docs/design/2026-06-24-coa-cockpit-brief.md` — the cockpit HTML handoff, sibling of the AAR/COA briefs. |

### Refreshing-envelope accounting — a pure function
`available_windows(state, predictive_spend, now) -> float` (and a small accumulator that resets
`predictive_spend` when the snapshot timestamp advances) is pure and unit-tested in isolation,
exactly like Phase 2a's `read_envelope` / `plan_run`.

## Testing

- **Pure / unit (hermetic, injected `execute`):** the board-state assembler; `unqueue` / `reorder`
  queue ops (round-trip + order); the refreshing-envelope accounting (predict between snapshots,
  re-sync on snapshot advance); the `advance` step (one-at-a-time guard, removes-on-pick,
  idle-on-empty, idle-on-over-budget, stop-flag honored, failed-job-dropped-not-retried) — all with
  a stub executor, no real claude/git/network.
- **Server (stdlib `http.client` against a `ThreadingHTTPServer` on 127.0.0.1):** token rejection
  (no/wrong token → 403); **job-id-only enforcement** (a POST carrying a raw command runs nothing);
  `/queue` mutates `queue.json`; `/reorder` reorders it; `/events` returns a `text/event-stream` and
  receives a board-state event after a mutation (SSE smoke); loopback bind asserted via
  `server_address`.
- `core.py` and the statusline / Phase 2a suites stay green and untouched.

## Open decisions resolved in brainstorming

- **Engine:** event-driven `advance` step (Run / job-done / drag triggers), **no background loop**;
  four runaway guards (one-at-a-time, remove-on-pick, terminate-by-default, no-retry).
- **Budget:** refreshing envelope, checked at pick time, predict-between-snapshots + re-sync-on-refresh.
- **Board scope:** multi-repo cockpit with a per-repo tab toggle; one job runs at a time globally.
- **Transport:** SSE push + in-place DOM patch (replaces `<meta refresh>` for the served view); POSTs
  for mutations.
- **Security:** 127.0.0.1, one-time token on every request, job-ids-not-commands, ROE server-side,
  short-lived; execution still goes through the Phase 2a sandbox stack.
- **Relationship to Phase 2a/1:** the cockpit is a **third template**; the static COA/AAR files remain
  the offline fallback. `run_one` is extracted so both the CLI batch runner and the server share one
  per-job execution path.
