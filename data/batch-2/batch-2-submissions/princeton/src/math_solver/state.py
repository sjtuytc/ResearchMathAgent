"""Disk-persistent run state via SQLite + structured file tree."""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from .config import RUNS_DIR, MIN_FREE_DISK_GB
from .models import AgentCall, RunState, TelemetryEvent


def _db_path(run_dir: Path) -> Path:
    return run_dir / "run.db"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_calls (
            call_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            notebook_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            inputs TEXT NOT NULL,
            output TEXT NOT NULL,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            tokens_think INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event TEXT NOT NULL,
            data TEXT NOT NULL,
            ts REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agent_calls_run ON agent_calls(run_id);
        CREATE INDEX IF NOT EXISTS idx_telemetry_run ON telemetry(run_id);
    """)
    conn.commit()


class RunStore:
    """All persistence for a single problem run."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.run_dir = RUNS_DIR / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "papers").mkdir(exist_ok=True)
        (self.run_dir / "agent_calls").mkdir(exist_ok=True)

        self._conn = sqlite3.connect(str(_db_path(self.run_dir)), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        _init_db(self._conn)

    # ── Run state ────────────────────────────────────────────────────────────

    def save_run_state(self, state: RunState) -> None:
        state.updated_at = time.time()
        self._set("run_state", state.model_dump_json())

    def load_run_state(self) -> RunState | None:
        raw = self._get("run_state")
        return RunState.model_validate_json(raw) if raw else None

    # ── Agent calls ──────────────────────────────────────────────────────────

    def load_stage_calls(self, stage: int, agent_prefix: str) -> list[AgentCall]:
        """Return completed agent calls for a given stage and agent prefix.

        Relies on `stage` being stored in the inputs JSON (added after the
        mid-stage resume fix). Calls recorded before that fix will be missing
        the key and are silently ignored.
        """
        cur = self._conn.execute(
            """SELECT call_id, run_id, notebook_id, agent, inputs, output,
                      tokens_in, tokens_out, tokens_think, duration_ms, created_at
               FROM agent_calls
               WHERE run_id=? AND agent LIKE ?
                 AND json_extract(inputs, '$.stage') = ?
               ORDER BY created_at""",
            (self.run_id, f"{agent_prefix}%", stage),
        )
        calls = []
        for row in cur.fetchall():
            calls.append(AgentCall(
                call_id=row[0], run_id=row[1], notebook_id=row[2],
                agent=row[3], inputs=json.loads(row[4]), output=row[5],
                tokens_in=row[6] or 0, tokens_out=row[7] or 0,
                tokens_think=row[8] or 0, duration_ms=row[9] or 0,
                created_at=row[10],
            ))
        return calls

    def record_agent_call(self, call: AgentCall) -> None:
        payload = call.model_dump_json()
        dest = self.run_dir / "agent_calls" / f"{call.call_id}.json"
        self._atomic_write(dest, payload)

        self._conn.execute(
            """INSERT OR REPLACE INTO agent_calls
               (call_id, run_id, notebook_id, agent, inputs, output,
                tokens_in, tokens_out, tokens_think, duration_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call.call_id, call.run_id, call.notebook_id, call.agent,
                json.dumps(call.inputs), call.output,
                call.tokens_in, call.tokens_out, call.tokens_think,
                call.duration_ms, call.created_at,
            ),
        )
        self._conn.commit()

    # ── Telemetry ────────────────────────────────────────────────────────────

    def log_event(self, event: TelemetryEvent) -> None:
        self._conn.execute(
            "INSERT INTO telemetry (run_id, event, data, ts) VALUES (?,?,?,?)",
            (event.run_id, event.event, json.dumps(event.data), event.ts),
        )
        self._conn.commit()

    def telemetry_summary(self) -> dict:
        cur = self._conn.execute(
            "SELECT event, COUNT(*) FROM telemetry WHERE run_id=? GROUP BY event",
            (self.run_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    # ── PDF storage ──────────────────────────────────────────────────────────

    def pdf_path(self, arxiv_id: str) -> Path:
        return self.run_dir / "papers" / f"{arxiv_id}.pdf"

    def check_disk_space(self) -> bool:
        usage = shutil.disk_usage(self.run_dir)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= MIN_FREE_DISK_GB

    def disk_free_gb(self) -> float:
        return shutil.disk_usage(self.run_dir).free / (1024 ** 3)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO state (key, value, updated_at) VALUES (?,?,?)",
            (key, value, time.time()),
        )
        self._conn.commit()

    def _get(self, key: str) -> str | None:
        cur = self._conn.execute("SELECT value FROM state WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    def close(self) -> None:
        self._conn.close()


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def find_incomplete_runs() -> list[str]:
    """Return run IDs whose state is not DONE or FAILED."""
    if not RUNS_DIR.exists():
        return []
    incomplete = []
    for d in RUNS_DIR.iterdir():
        if not d.is_dir():
            continue
        store = RunStore(d.name)
        state = store.load_run_state()
        store.close()
        if state and state.status.value not in ("DONE", "FAILED"):
            incomplete.append(d.name)
    return incomplete
