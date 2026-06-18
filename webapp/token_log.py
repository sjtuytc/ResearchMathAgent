"""Persistent append-only token-usage log at webapp/token_log.jsonl."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _log_path(repo_root: Path) -> Path:
    return repo_root / "webapp" / "token_log.jsonl"


def append_usage(
    repo_root: Path,
    problem_id: str,
    kind: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None = None,
    *,
    provider: str = "",
    model: str = "",
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "problem": problem_id,
        "kind": kind,
        "in": int(input_tokens),
        "out": int(output_tokens),
        "cost": float(cost_usd) if cost_usd is not None else None,
        "provider": provider or "",
        "model": model or "",
    }
    with open(_log_path(repo_root), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_log(repo_root: Path, days: int = 14) -> list[dict]:
    path = _log_path(repo_root)
    if not path.is_file():
        return []
    cutoff = time.time() - days * 86400
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if _ts_epoch(e.get("ts", "")) > cutoff:
                    entries.append(e)
            except Exception:  # noqa: BLE001
                pass
    return entries


def daily_summary(entries: list[dict]) -> list[dict]:
    """Group by date → [{date, in, out, cost, runs}] sorted ascending."""
    by_date: dict[str, dict] = defaultdict(lambda: {"in": 0, "out": 0, "cost": 0.0, "runs": 0})
    for e in entries:
        d = (e.get("ts") or "")[:10]
        if not d:
            continue
        by_date[d]["in"] += e.get("in", 0)
        by_date[d]["out"] += e.get("out", 0)
        by_date[d]["cost"] += e.get("cost") or 0.0
        by_date[d]["runs"] += 1
    return [{"date": d, **v} for d, v in sorted(by_date.items())]


def per_problem_summary(entries: list[dict]) -> list[dict]:
    """Group by problem → [{problem, in, out, cost, runs}] sorted by total desc."""
    by_prob: dict[str, dict] = defaultdict(lambda: {"in": 0, "out": 0, "cost": 0.0, "runs": 0})
    for e in entries:
        p = e.get("problem") or "unknown"
        by_prob[p]["in"] += e.get("in", 0)
        by_prob[p]["out"] += e.get("out", 0)
        by_prob[p]["cost"] += e.get("cost") or 0.0
        by_prob[p]["runs"] += 1
    rows = [{"problem": p, **v} for p, v in by_prob.items()]
    rows.sort(key=lambda x: x["in"] + x["out"], reverse=True)
    return rows


def today_summary(repo_root: Path) -> dict:
    """Aggregate all usage for the current UTC date, broken down by kind and problem."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_entries = read_log(repo_root, days=2)
    entries = [e for e in all_entries if (e.get("ts") or "")[:10] == today]

    by_kind: dict[str, dict] = defaultdict(lambda: {"in": 0, "out": 0, "cost": 0.0, "runs": 0})
    by_prob: dict[str, dict] = defaultdict(lambda: {"in": 0, "out": 0, "cost": 0.0, "runs": 0})
    total_in = total_out = 0
    total_cost = 0.0

    for e in entries:
        k = e.get("kind") or "unknown"
        p = e.get("problem") or "unknown"
        inp, out = e.get("in", 0), e.get("out", 0)
        cost = e.get("cost") or 0.0
        for d in (by_kind[k], by_prob[p]):
            d["in"] += inp; d["out"] += out; d["cost"] += cost; d["runs"] += 1
        total_in += inp; total_out += out; total_cost += cost

    by_kind_list = sorted(
        [{"kind": k, **v} for k, v in by_kind.items()],
        key=lambda x: x["in"] + x["out"], reverse=True,
    )
    by_prob_list = sorted(
        [{"problem": p, **v} for p, v in by_prob.items()],
        key=lambda x: x["in"] + x["out"], reverse=True,
    )
    return {
        "date": today,
        "total_in": total_in,
        "total_out": total_out,
        "total_cost": round(total_cost, 6),
        "runs": len(entries),
        "by_kind": by_kind_list,
        "by_problem": by_prob_list,
    }


def _ts_epoch(ts: str) -> float:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _entry_cost_usd(entry: dict) -> float:
    stored = entry.get("cost")
    if stored is not None:
        return float(stored)
    from .vertex import DEFAULT_MODEL, estimate_vertex_cost_usd

    return estimate_vertex_cost_usd(
        entry.get("model") or DEFAULT_MODEL,
        entry.get("in", 0),
        entry.get("out", 0),
    )


def _dedupe_cumulative_entries(entries: list[dict]) -> list[dict]:
    """Keep the largest cumulative snapshot per run (problem + kind + minute)."""
    best: dict[tuple, dict] = {}
    for e in entries:
        key = (e.get("problem"), e.get("kind"), (e.get("ts") or "")[:16])
        tok = int(e.get("in", 0)) + int(e.get("out", 0))
        prev = best.get(key)
        if prev is None or tok > int(prev.get("in", 0)) + int(prev.get("out", 0)):
            best[key] = e
    return list(best.values())


def log_usage_delta(
    repo_root: Path,
    problem_id: str,
    kind: str,
    data: dict,
    prev: dict,
    *,
    provider: str = "",
    model: str = "",
) -> dict:
    """Append one usage row using token deltas vs the previous cumulative snapshot."""
    cur_in = int(data.get("input_tokens", 0))
    cur_out = int(data.get("output_tokens", 0))
    delta_in = max(0, cur_in - int(prev.get("input_tokens", 0)))
    delta_out = max(0, cur_out - int(prev.get("output_tokens", 0)))
    prev.update({"input_tokens": cur_in, "output_tokens": cur_out})
    if not delta_in and not delta_out:
        return prev

    cost = data.get("cost_usd")
    if cost is None and provider == "vertex":
        from .vertex import estimate_vertex_cost_usd

        cost = estimate_vertex_cost_usd(model, delta_in, delta_out)
    elif cost is not None and prev.get("cost_usd") is not None:
        cost = max(0.0, float(cost) - float(prev.get("cost_usd", 0)))
    prev["cost_usd"] = float(cost) if cost is not None else prev.get("cost_usd")

    append_usage(
        repo_root,
        problem_id,
        kind,
        delta_in,
        delta_out,
        cost,
        provider=provider,
        model=model,
    )
    return prev


def vertex_usage_summary(repo_root: Path, *, days: int = 365) -> dict:
    """Aggregate webapp token log as estimated Vertex/GCP spend."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = _dedupe_cumulative_entries(read_log(repo_root, days=days))

    def _accum(bucket: dict, entry: dict) -> None:
        bucket["in"] += entry.get("in", 0)
        bucket["out"] += entry.get("out", 0)
        bucket["cost"] += _entry_cost_usd(entry)
        bucket["runs"] += 1

    total = {"in": 0, "out": 0, "cost": 0.0, "runs": 0}
    today_tot = {"in": 0, "out": 0, "cost": 0.0, "runs": 0}
    for e in entries:
        prov = (e.get("provider") or "").lower()
        if prov and prov not in {"vertex", "api"}:
            continue
        _accum(total, e)
        if (e.get("ts") or "")[:10] == today:
            _accum(today_tot, e)

    return {
        "days": days,
        "total_in": total["in"],
        "total_out": total["out"],
        "total_cost": round(total["cost"], 4),
        "total_runs": total["runs"],
        "today_in": today_tot["in"],
        "today_out": today_tot["out"],
        "today_cost": round(today_tot["cost"], 4),
        "today_runs": today_tot["runs"],
        "estimated": True,
    }
