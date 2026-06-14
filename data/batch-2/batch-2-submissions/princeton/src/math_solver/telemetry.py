"""Structured telemetry events and summary reporting."""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from .models import TelemetryEvent

console = Console()


class Telemetry:
    def __init__(self, run_id: str, store):
        self._run_id = run_id
        self._store = store

    def emit(self, event: str, **data: Any) -> None:
        ev = TelemetryEvent(run_id=self._run_id, event=event, data=data)
        self._store.log_event(ev)
        console.log(f"[dim][{event}][/dim] {data}")

    # ── Named events ─────────────────────────────────────────────────────────

    def solver_round(self, notebook_id: str, round_n: int, scores: list[float]) -> None:
        self.emit("solver_round", notebook_id=notebook_id, round=round_n, scores=scores)

    def notebook_update(self, notebook_id: str, round_n: int, best_score: float,
                        progress: bool) -> None:
        self.emit("notebook_update", notebook_id=notebook_id, round=round_n,
                  best_score=best_score, progress=progress)

    def search_issued(self, notebook_id: str, query: str, recency: str) -> None:
        self.emit("search_issued", notebook_id=notebook_id, query=query, recency=recency)

    def triage_result(self, notebook_id: str, total: int, kept: int) -> None:
        self.emit("triage_result", notebook_id=notebook_id, total=total, kept=kept)

    def paper_fetched(self, arxiv_id: str, from_cache: bool) -> None:
        self.emit("paper_fetched", arxiv_id=arxiv_id, from_cache=from_cache)

    def paper_used(self, arxiv_id: str, notebook_id: str) -> None:
        self.emit("paper_used", arxiv_id=arxiv_id, notebook_id=notebook_id)

    def conjecture_extraction(self, notebook_id: str, n_conjectures: int) -> None:
        self.emit("conjecture_extraction", notebook_id=notebook_id,
                  n_conjectures=n_conjectures)

    def conjecture_disproved(self, notebook_id: str, conjecture_id: str) -> None:
        self.emit("conjecture_disproved", notebook_id=notebook_id,
                  conjecture_id=conjecture_id)

    def child_notebook_spawned(self, parent_id: str, child_id: str,
                               conjecture_id: str) -> None:
        self.emit("child_notebook_spawned", parent_id=parent_id, child_id=child_id,
                  conjecture_id=conjecture_id)

    def run_done(self, final_score: float, total_rounds: int) -> None:
        self.emit("run_done", final_score=final_score, total_rounds=total_rounds)

    # ── Summary ──────────────────────────────────────────────────────────────

    def call_stats(self) -> dict:
        """Total calls, tokens-in, tokens-out across all agent calls for this run."""
        cur = self._store._conn.execute(
            """SELECT COUNT(*), SUM(tokens_in), SUM(tokens_out), SUM(tokens_think), SUM(duration_ms)
               FROM agent_calls WHERE run_id = ?""",
            (self._run_id,),
        )
        row = cur.fetchone()
        total_calls  = row[0] or 0
        tokens_in    = row[1] or 0
        tokens_out   = row[2] or 0
        tokens_think = row[3] or 0
        duration_ms  = row[4] or 0
        return {
            "total_calls":   total_calls,
            "tokens_in":     tokens_in,
            "tokens_out":    tokens_out,
            "tokens_think":  tokens_think,
            "total_tokens":  tokens_in + tokens_out + tokens_think,
            "duration_s":    duration_ms // 1000,
        }

    def print_summary(self) -> None:
        # ── Call / token summary ─────────────────────────────────────────────
        stats = self.call_stats()
        summary = Table(title=f"Run summary — {self._run_id}")
        summary.add_column("Metric")
        summary.add_column("Value", justify="right")
        summary.add_row("Total agent calls",  str(stats["total_calls"]))
        summary.add_row("Tokens in",          f"{stats['tokens_in']:,}")
        summary.add_row("Tokens out",         f"{stats['tokens_out']:,}")
        summary.add_row("Tokens thinking",    f"{stats['tokens_think']:,}")
        summary.add_row("Total tokens",       f"{stats['total_tokens']:,}")
        summary.add_row("Wall time",          f"{stats['duration_s']}s")
        console.print(summary)

        # ── Per-agent breakdown ──────────────────────────────────────────────
        cur = self._store._conn.execute(
            """SELECT agent,
                      COUNT(*) as calls,
                      SUM(tokens_in) as tin,
                      SUM(tokens_out) as tout,
                      SUM(tokens_think) as tthink
               FROM agent_calls WHERE run_id = ?
               GROUP BY agent ORDER BY calls DESC""",
            (self._run_id,),
        )
        breakdown = Table(title="Calls by agent")
        breakdown.add_column("Agent")
        breakdown.add_column("Calls",         justify="right")
        breakdown.add_column("Tokens in",     justify="right")
        breakdown.add_column("Tokens out",    justify="right")
        breakdown.add_column("Thinking",      justify="right")
        for agent, calls, tin, tout, tthink in cur.fetchall():
            breakdown.add_row(agent, str(calls), f"{tin or 0:,}",
                              f"{tout or 0:,}", f"{tthink or 0:,}")
        console.print(breakdown)
