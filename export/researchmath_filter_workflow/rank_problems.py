#!/usr/bin/env python3
"""
ResearchMath Problem Ranker
----------------------------
Uses the Anthropic Claude API to score and rank math research problems
from the ResearchMath datasets for AI-assisted investigation suitability.

Usage:
    python rank_problems.py --help
    python rank_problems.py --dataset researchmath_14k --limit 50
    python rank_problems.py --all-datasets --limit 20
    python rank_problems.py --local-data /path/to/data/datasets --dataset erdos_problems
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed.\n  Run: pip install anthropic")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────

import os
FILTER_API_URL = os.environ.get("FILTER_API_URL", "https://<your-ngrok-domain>/rmac/filter")

DATASETS = [
    "researchmath_14k",
    "erdos_problems",
    "aim_problem_lists",
    "formal_conjectures",
    "unsolved_math",
]

# Scoring dimension weights (must sum to 1.0)
RANK_WEIGHTS: dict[str, float] = {
    "importance":        0.30,
    "ai_tractability":   0.25,
    "verifiability":     0.20,
    "clarity":           0.15,
    "self_containedness": 0.10,
}

DEFAULT_MODEL = "claude-opus-4-8"

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an expert mathematical research evaluator. "
    "Your task is to assess open math research problems to determine their "
    "suitability for AI-assisted investigation. "
    "You will evaluate each problem on five dimensions (each scored 1–5) "
    "and return a structured JSON response."
)

SCORING_PROMPT = """\
Evaluate the following math research problem for AI-assisted research suitability.

## Scoring Dimensions (1 = lowest, 5 = highest)

**Clarity** — Is the problem precisely stated? Are all terms defined? Is it
unambiguous what a valid solution would look like?

**Importance** — Mathematical/scientific significance. How central is this to its
field? How many researchers would care? Does it connect important areas?

**AI Tractability** — How amenable is this to AI exploration? Can systematic search
help? Are there computable verification steps? Would generating many candidate
approaches be useful?

**Verifiability** — Can a proposed solution be rigorously verified? Are success
criteria concrete and checkable without deep domain expertise?

**Self-Containedness** — Can the problem be understood from the statement alone,
without consulting specific papers or having very narrow background knowledge?

## Problem

Title: {title}
Dataset: {dataset}
Domain: {domain}
Status: {status}
{difficulty_line}

Statement:
{statement}

## Response Format

Return ONLY a JSON object — no markdown fences, no commentary outside the JSON:
{{
  "clarity": <int 1-5>,
  "importance": <int 1-5>,
  "ai_tractability": <int 1-5>,
  "verifiability": <int 1-5>,
  "self_containedness": <int 1-5>,
  "brief_reasoning": "<2-3 sentences explaining the key considerations>",
  "recommendation": "<include|borderline|exclude>"
}}"""


def build_prompt(problem: dict[str, Any], dataset: str) -> str:
    domain = (
        problem.get("taxonomy_level_1")
        or problem.get("taxonomy_level_2")
        or "Unknown"
    )
    diff = problem.get("difficulty")
    diff_line = f"Difficulty estimate: {round(diff * 100)}%" if diff is not None else ""
    stmt = (problem.get("statement") or "").strip()
    # Cap statement length to keep API costs predictable
    if len(stmt) > 3000:
        stmt = stmt[:3000] + "\n[… truncated …]"
    return SCORING_PROMPT.format(
        title=problem.get("title") or problem.get("id", "?"),
        dataset=dataset,
        domain=domain,
        status=problem.get("open_status", "unknown"),
        difficulty_line=diff_line,
        statement=stmt or "(no statement available)",
    )


# ── Data fetching ─────────────────────────────────────────────────────────────

def _api_get(url: str) -> Any:
    import urllib.request
    req = urllib.request.Request(url, headers={"ngrok-skip-browser-warning": "1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_problems_api(dataset: str, limit: int, status: str = "") -> list[dict]:
    """Fetch problem list from the hosted filter API (no local data needed)."""
    import urllib.parse
    problems: list[dict] = []
    page = 1
    page_size = min(limit, 200)
    while len(problems) < limit:
        params: dict[str, Any] = {
            "dataset": dataset, "page": page, "page_size": page_size,
        }
        if status:
            params["status"] = status
        url = f"{FILTER_API_URL}/api/problems?" + urllib.parse.urlencode(params)
        data = _api_get(url)
        batch = data.get("problems", [])
        if not batch:
            break
        problems.extend(batch)
        if page >= data.get("pages", 1):
            break
        page += 1
    return problems[:limit]


def fetch_problems_local(data_dir: Path, dataset: str, limit: int) -> list[dict]:
    """Read problem list from local _index.json."""
    idx = data_dir / dataset / "_index.json"
    if not idx.is_file():
        raise FileNotFoundError(f"Index not found: {idx}")
    return json.loads(idx.read_text(encoding="utf-8"))[:limit]


def load_full_problem(data_dir: Path | None, dataset: str, problem_id: str) -> dict:
    """Load full problem JSON (with statement). Local first, then API fallback."""
    if data_dir:
        p = data_dir / dataset / "problems" / f"{problem_id}.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    return _api_get(f"{FILTER_API_URL}/api/problem/{dataset}/{problem_id}")


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_problem(
    client: anthropic.Anthropic,
    problem: dict[str, Any],
    dataset: str,
    model: str,
    weights: dict[str, float],
) -> dict[str, Any] | None:
    """Send one problem to Claude for scoring. Returns score dict or None."""
    prompt = build_prompt(problem, dataset)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip accidental markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        scores: dict[str, Any] = json.loads(raw)

        # Compute rank_score from configured weights (authoritative)
        scores["rank_score"] = round(
            sum(scores.get(dim, 3) * w for dim, w in weights.items()), 3
        )
        return scores
    except json.JSONDecodeError as e:
        print(f"\n    [WARN] JSON parse error: {e}")
        return None
    except anthropic.APIError as e:
        print(f"\n    [ERROR] API error: {e}")
        return None


# ── Output helpers ────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "rank", "dataset", "id", "title", "domain", "status",
    "rank_score", "recommendation",
    "clarity", "importance", "ai_tractability", "verifiability", "self_containedness",
    "brief_reasoning",
]


def save_results(results: list[dict], out_dir: Path, name: str) -> None:
    results.sort(key=lambda r: r.get("rank_score", 0), reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    json_path = out_dir / f"{name}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = out_dir / f"{name}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    inc = sum(1 for r in results if r.get("recommendation") == "include")
    brd = sum(1 for r in results if r.get("recommendation") == "borderline")
    exc = sum(1 for r in results if r.get("recommendation") == "exclude")
    print(f"  Saved {json_path.name} + {csv_path.name} "
          f"[{inc} include | {brd} borderline | {exc} exclude]")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score and rank ResearchMath problems using Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Score 50 problems from the main dataset
  python rank_problems.py --dataset researchmath_14k --limit 50

  # Score all datasets, 20 problems each, with a cheaper model
  python rank_problems.py --all-datasets --limit 20 --model claude-haiku-4-5-20251001

  # Score only 'open' problems from the Erdős dataset, reading from local files
  python rank_problems.py --dataset erdos_problems --status open \\
      --local-data /path/to/data/datasets

  # Run with a YAML config
  python rank_problems.py --config config.yaml
""",
    )
    parser.add_argument("--dataset", default="researchmath_14k",
                        help="Dataset slug (default: researchmath_14k)")
    parser.add_argument("--all-datasets", action="store_true",
                        help="Score all 5 datasets")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max problems per dataset (default: 50)")
    parser.add_argument("--status", default="",
                        help="Filter by status: open|solved|partially_solved|unknown")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model (default: {DEFAULT_MODEL})")
    parser.add_argument("--output", default="ranked_output",
                        help="Output directory (default: ranked_output/)")
    parser.add_argument("--local-data", default="",
                        help="Path to local data/datasets/ directory")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds between API calls (default: 0.5)")
    parser.add_argument("--api-key", default="",
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--config", default="",
                        help="Path to YAML config file (overrides CLI args)")
    args = parser.parse_args()

    # Load YAML config if provided
    cfg: dict[str, Any] = {}
    if args.config:
        try:
            import yaml  # type: ignore
            cfg = yaml.safe_load(Path(args.config).read_text()) or {}
        except ImportError:
            print("WARN: PyYAML not installed; ignoring --config. Run: pip install pyyaml")
        except FileNotFoundError:
            print(f"ERROR: config file not found: {args.config}")
            sys.exit(1)

    api_key = args.api_key or cfg.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: Anthropic API key required.\n"
              "  Set ANTHROPIC_API_KEY environment variable, or pass --api-key KEY")
        sys.exit(1)

    model = cfg.get("model", args.model)
    limit = cfg.get("limit_per_dataset", args.limit)
    status = cfg.get("status_filter", args.status)
    delay = cfg.get("delay_between_calls", args.delay)
    out_dir = Path(cfg.get("output_dir", args.output))
    local_data_str = cfg.get("local_data_dir", args.local_data)
    local_data = Path(local_data_str) if local_data_str else None
    weights = {**RANK_WEIGHTS, **cfg.get("weights", {})}

    datasets = (cfg.get("datasets") or DATASETS) if args.all_datasets else [args.dataset]

    out_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic(api_key=api_key)
    all_results: list[dict] = []

    print(f"Model: {model}  |  Limit: {limit}/dataset  |  Output: {out_dir}/")

    for dataset in datasets:
        print(f"\n── {dataset} {'─' * max(0, 48 - len(dataset))}")

        # Fetch problem list
        try:
            if local_data:
                print(f"  Reading local index…")
                problems = fetch_problems_local(local_data, dataset, limit)
            else:
                print(f"  Fetching from API…")
                problems = fetch_problems_api(dataset, limit, status)
        except Exception as e:
            print(f"  [SKIP] Could not fetch: {e}")
            continue

        print(f"  Scoring {len(problems)} problems…")
        scored: list[dict] = []

        for i, prob in enumerate(problems, 1):
            pid = prob.get("id", "?")
            label = (prob.get("title") or pid)[:55]
            print(f"  [{i:3}/{len(problems)}] {label:<55}", end="", flush=True)

            # Load full problem text if statement missing (index has summaries)
            if not prob.get("statement"):
                try:
                    prob = load_full_problem(local_data, dataset, pid)
                except Exception as e:
                    print(f" (skip: {e})")
                    continue

            scores = score_problem(client, prob, dataset, model, weights)
            if scores is None:
                print(" [failed]")
                continue

            result: dict[str, Any] = {
                "dataset": dataset,
                "id": prob.get("id"),
                "title": prob.get("title", ""),
                "domain": prob.get("taxonomy_level_1", ""),
                "status": prob.get("open_status", "unknown"),
                **scores,
            }
            scored.append(result)
            all_results.append(result)

            rec = scores.get("recommendation", "?")
            rs = scores.get("rank_score", 0)
            marker = "✓" if rec == "include" else "~" if rec == "borderline" else "✗"
            print(f" {marker} {rs:.2f}")

            if i < len(problems):
                time.sleep(delay)

        if scored:
            save_results(scored, out_dir, f"{dataset}_ranked")

    # Combined output (all datasets)
    if len(datasets) > 1 and all_results:
        print(f"\n── Combined ─────────────────────────────────────────────────")
        save_results(all_results, out_dir, "all_datasets_ranked")

    print(f"\nDone. Open ranked_output/ to review results.")


if __name__ == "__main__":
    main()
