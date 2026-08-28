"""Debounced rolling autosave — the `_Autosaver` class.

Moved verbatim from the old api.py so the autosave machinery lives
next to (not inside) the route-registration code.
"""

import asyncio
import logging
import os

log = logging.getLogger(__name__)


class _Autosaver:
    """Polls the engine's change counter and writes a debounced, rate-
    capped ping-pong autosave snapshot so a reboot — including a hard
    power cut — resumes the last edited state. The cadence: never more
    often than MIN_INTERVAL; after edits go quiet for DEBOUNCE it writes
    promptly; during a long continuous edit it still writes every
    MAX_WAIT so you can't lose an unbounded amount on a cut."""

    POLL = 3.0
    DEBOUNCE = 6.0
    MIN_INTERVAL = 15.0
    MAX_WAIT = 30.0

    def __init__(self, engine, config, snapshot):
        self._engine = engine
        self._config = config
        self._snapshot = snapshot
        self._last_seq = engine._change_seq
        self._last_write = 0.0
        self._running = True
        self._suspended = False
        # pid of an in-flight background autosave child (fork_write_autosave),
        # or None. Reaped non-blocking on the next poll; we never stack two.
        self._child_pid: int | None = None

    def _reap_child(self, block: bool) -> None:
        """Reap the background autosave child if present. block=False is
        the periodic non-blocking reap (clears _child_pid once the child
        exits); block=True waits for it (shutdown / before a durable
        write, so its rw/ro remount window can't overlap ours)."""
        if self._child_pid is None:
            return
        try:
            flags = 0 if block else os.WNOHANG
            reaped, _status = os.waitpid(self._child_pid, flags)
        except ChildProcessError:
            reaped = self._child_pid  # already gone
        if block or reaped == self._child_pid:
            self._child_pid = None

    async def run(self) -> None:
        import time as _t
        # Anchor MIN_INTERVAL to start-up so we don't write in the first
        # few seconds of boot while things settle.
        self._last_write = _t.monotonic()
        while self._running:
            await asyncio.sleep(self.POLL)
            try:
                self._reap_child(block=False)  # clear a finished prior child
                if self._child_pid is not None:
                    continue  # previous encode still running — don't stack forks
                seq = self._engine._change_seq
                if seq == self._last_seq:
                    continue  # nothing changed since the last autosave
                now = _t.monotonic()
                since_write = now - self._last_write
                if since_write < self.MIN_INTERVAL:
                    continue  # rate cap
                idle = now - self._engine._last_change_t
                if idle < self.DEBOUNCE and since_write < self.MAX_WAIT:
                    continue  # still actively editing and not yet overdue
                # Build the plain snapshot on the loop (cheap, shallow,
                # race-free vs hotplug), then fork: the GIL-heavy encode
                # runs in the child off the isolated core, so the loop
                # is free the instant fork() returns.
                self._snapshot()
                self._child_pid = self._config.fork_write_autosave()
                self._last_write = now
                self._last_seq = seq
            except Exception:
                log.exception("autosave loop error")

    def flush(self, force: bool = False) -> None:
        """Synchronous final autosave for the shutdown path — captures a
        clean stop even if the debounce hadn't fired. No-op if nothing
        changed since the last autosave, UNLESS `force` is set.

        `force=True` is used right after Load / Restore / Import: the
        live state *is* the new state and the user expects it to be the
        resume point, but those paths clear_dirty() (so _change_seq ==
        _last_seq and the debounced loop would never fire) — without a
        forced write a power cut just after a Load would resume the
        PRE-Load state."""
        try:
            if self._suspended:
                return  # factory reset cleared the snapshot; don't recreate it
            # Wait for any in-flight background child first so its rw/ro
            # remount window can't overlap this synchronous write.
            self._reap_child(block=True)
            if not force and self._engine._change_seq == self._last_seq:
                return
            self._snapshot()
            # Shutdown path: encode in-process. The loop is going away,
            # so the GIL hold doesn't matter, and an in-process write
            # can't be orphaned by the process exiting before a child
            # finishes.
            self._config.write_autosave()
            self._last_seq = self._engine._change_seq
            import time as _t
            self._last_write = _t.monotonic()
        except Exception:
            log.exception("autosave flush error")

    async def autosave_now(self) -> None:
        """Async force-autosave for the request handlers (Load / Restore
        / Import). The new state must be durable as the resume point
        before we return, so we fork the encode child and WAIT for it —
        but on a worker thread, where the waitpid blocks without holding
        the GIL, leaving the loop free while the child encodes off-core.
        Falls back to an in-process write if fork fails."""
        try:
            # Don't overlap a background child's remount window.
            self._reap_child(block=True)
            self._snapshot()
            await asyncio.to_thread(self._fork_and_wait)
            self._last_seq = self._engine._change_seq
            import time as _t
            self._last_write = _t.monotonic()
        except Exception:
            log.exception("autosave_now error")

    def _fork_and_wait(self) -> None:
        """Fork the encode child and block (on a worker thread) until it
        has durably written the slot. The waitpid is a GIL-releasing
        syscall, so the loop keeps running while the child encodes."""
        pid = self._config.fork_write_autosave()
        if pid is None:
            self._config.write_autosave()  # fork failed: in-process fallback
            return
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def stop(self) -> None:
        self._running = False

    def disable(self) -> None:
        """Permanently silence autosave (factory reset): stop the poll
        loop AND neuter the shutdown flush, so the just-cleared resume
        snapshot can't be recreated from the still-live old engine state
        before the reboot."""
        self._running = False
        self._suspended = True


