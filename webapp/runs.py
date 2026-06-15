"""Run lifecycle control shared by the frontend and backend.

Every agent run (API or Claude Code) is registered here with a cancellation
signal and, for subprocess-backed providers, a handle to the OS process group.
The SSE endpoint registers a run; a separate ``/api/cancel`` request flips the
cancel flag and kills the process group immediately, so the **Stop** button
actually terminates backend work instead of only closing the browser stream.
"""

from __future__ import annotations

import os
import signal
import threading
import time

_POSIX = hasattr(os, "killpg") and hasattr(os, "getpgid")


class RunHandle:
    """Tracks one in-flight run: cancel signal + optional subprocess."""

    def __init__(self, run_id: str, meta: dict) -> None:
        self.run_id = run_id
        self.meta = meta
        self.cancel_event = threading.Event()
        self.proc = None  # set by subprocess-backed providers
        self.status = "running"
        self.created_at = time.time()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def attach_proc(self, proc) -> None:
        self.proc = proc
        # If a cancel landed between spawn and attach, honor it now.
        if self.cancelled:
            self.kill_proc()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self.status = "stopping"
        self.kill_proc()

    def kill_proc(self) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        # Kill the whole process group — the `claude` CLI spawns a node child.
        try:
            if _POSIX:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    def force_kill_proc(self) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if _POSIX:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._lock = threading.Lock()

    def register(self, run_id: str, meta: dict) -> RunHandle:
        handle = RunHandle(run_id, meta)
        with self._lock:
            self._runs[run_id] = handle
        return handle

    def get(self, run_id: str) -> RunHandle | None:
        with self._lock:
            return self._runs.get(run_id)

    def cancel(self, run_id: str) -> bool:
        handle = self.get(run_id)
        if handle is None:
            return False
        handle.request_cancel()
        return True

    def cancel_all(self) -> int:
        with self._lock:
            handles = list(self._runs.values())
        for handle in handles:
            handle.request_cancel()
        return len(handles)

    def unregister(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)

    def active(self) -> list[dict]:
        with self._lock:
            handles = list(self._runs.values())
        now = time.time()
        return [
            {"run_id": h.run_id, "status": h.status,
             "age_s": round(now - h.created_at, 1), **h.meta}
            for h in handles
        ]


REGISTRY = RunRegistry()
