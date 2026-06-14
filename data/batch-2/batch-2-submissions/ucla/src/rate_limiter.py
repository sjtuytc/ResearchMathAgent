"""Cross-process injection rate limiter (fcntl-based).

Used to enforce a minimum interval between API call submissions across
multiple harness subprocesses sharing the same container. State is a single
timestamp file guarded by an exclusive POSIX file lock.
"""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path


def acquire_slot(min_interval_sec: float, lock_path: str | os.PathLike) -> float:
    """Block until at least min_interval_sec has elapsed since the last
    slot was issued via this lock_path. Returns the wait duration in seconds
    (0 if no wait was needed). Cross-process safe across any processes that
    can see the same lock_path on the same filesystem."""
    if min_interval_sec <= 0:
        return 0.0

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    waited = 0.0
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 64).decode("ascii", errors="ignore").strip()
            try:
                last_at = float(raw) if raw else 0.0
            except ValueError:
                last_at = 0.0

            now = time.time()
            wait = min_interval_sec - (now - last_at)
            if wait > 0:
                time.sleep(wait)
                waited = wait
                now = time.time()

            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, f"{now:.6f}\n".encode("ascii"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    return waited
