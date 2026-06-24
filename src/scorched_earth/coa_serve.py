"""The COA live cockpit: a localhost server hosting an event-driven engine that drives the
Phase 2a runner. The Engine holds shared board state behind a lock and runs an `advance`
step (no background loop) on a worker thread; HTTP/SSE wiring is added in Task 6. I/O tier;
never imported by the statusline hot path."""

from __future__ import annotations

import os
import threading
import time

from . import coa_io
from . import runner
from . import state as st


class Engine:
    """Event-driven cockpit engine. `advance` runs ONE eligible affordable job and chains on
    completion. Re-entrancy is blocked by a global BUSY flag (one job at a time across all
    repos, since budget is one pool). Terminates by default: empty/over-budget/ROE-blocked
    queue or stop -> idle. A crashing job is recorded fail, dropped, and the chain continues."""

    def __init__(self, repos, *, execute=None, broadcast=None, load_state=None, now=None):
        self.repos = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        self._execute = execute or runner.execute_job
        self._broadcast = broadcast or (lambda: None)
        self._load_state = load_state or st.load_state
        self._now = now or (lambda: int(time.time()))
        self._lock = threading.Lock()
        self._busy = False
        self._stop = False
        self._running = None                       # {"repo","id"} or None
        self._trackers = {}                        # repo -> EnvelopeTracker
        self._results = {}                         # repo -> RunResult (accumulating)

    # ---- public mutations (called by HTTP handlers) ----
    def queue(self, repo, job_id):
        from .jobs import parse_jobs
        # promote a proposed job into the queue by id
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            coa_io.enqueue(repo, [jobs[job_id]])
        self._broadcast()
        self.advance(repo)

    def unqueue(self, repo, job_id):
        coa_io.unqueue(repo, job_id)
        self._broadcast()

    def reorder(self, repo, ids):
        coa_io.reorder(repo, ids)
        self._broadcast()

    def run(self, repo):
        self.advance(repo)

    def stop(self):
        with self._lock:
            self._stop = True

    # ---- state ----
    def state_json(self):
        with self._lock:
            running = dict(self._running) if self._running else None
            busy = self._busy
        return {"repos": [coa_io.board_state(r) for r in self.repos],
                "running": running, "busy": busy}

    # ---- the event-driven step ----
    def advance(self, repo):
        repo = os.path.realpath(os.path.expanduser(repo))
        # one-at-a-time guard + stop check, atomically
        with self._lock:
            if self._busy or self._stop:
                return
            roe = coa_io.load_roe(repo)
            tracker = self._trackers.get(repo)
            if tracker is None:
                tracker = runner.EnvelopeTracker(roe)
                self._trackers[repo] = tracker
            avail = tracker.available(self._load_state(), self._now())
            if avail is None:
                return                              # stale/absent snapshot -> refuse
            job = runner.pick_next(coa_io.read_queue(repo), avail, roe)
            if job is None:
                return                              # idle: nothing eligible/affordable
            self._busy = True
            self._running = {"repo": repo, "id": job.id}
            coa_io.unqueue(repo, job.id)            # remove-on-pick: can never run twice
            rr = self._results.get(repo)
            if rr is None:
                rr = runner.RunResult(
                    generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                    state="running", repo=repo, verdict="unknown", note="",
                    available_windows=avail, spent_estimated=0.0)
                self._results[repo] = rr
            seq = len(rr.jobs) + 1
        self._broadcast()

        # execute OUTSIDE the lock (long-running, sandboxed)
        oc = runner.run_one(repo, job, roe, repo, seq, execute=self._execute)

        with self._lock:
            tracker.charge(job.est_windows)
            rr.jobs.append(oc)
            rr.spent_estimated = tracker.spent
            self._persist(repo, rr)
            self._busy = False
            self._running = None
            stopped = self._stop
        self._broadcast()

        if not stopped:
            self.advance(repo)                      # chain to the next card

    def _persist(self, repo, rr):
        from . import review_report
        rr.note = runner._summary(rr)
        coa_io.write_run_record(repo, runner._dataclass_dict(rr), rr.generated_at)
        with open(os.path.join(coa_io.runs_dir(repo), rr.generated_at + ".html"), "w") as f:
            f.write(review_report.render_review_html(rr))
