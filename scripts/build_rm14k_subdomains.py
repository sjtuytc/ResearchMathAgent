#!/usr/bin/env python3
"""Split ResearchMath-14k into per-domain curated subdomain datasets.

For each of the 11 broad domains (taxonomy_level_1, from arXiv:2605.28003) this
selects the 10 most *promising, valuable, and unsolved* problems and writes a
standalone dataset under data/datasets/<slug>/ that the filter app discovers
automatically (metadata.json + _index.json + problems/ + solvability caches).

Ranking (unsolved only, i.e. open_status != "solved"):
  promise   = AI-solvability score (0..1)           -> "promising"
  value     = difficulty (0..1) + provenance bonus   -> "valuable"
  status_w  = open 1.0 / partially_solved 0.9 / unknown 0.7
  composite = (0.6*promise + 0.4*value + provenance) * status_w
Problems are bucketed by solvability tier first (plausible+ before hard before
open) so the selection is genuinely promising, then ranked by composite within.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASETS = REPO / "data" / "datasets"
SRC = DATASETS / "researchmath_14k"
TOP_N = 10

# taxonomy_level_1  ->  (slug, display name, short label)
DOMAINS: dict[str, tuple[str, str]] = {
    "Theoretical Computer Science":              ("tcs_rm14k", "TCS-RM14k"),
    "Discrete Mathematics and Combinatorics":    ("discretemath_rm14k", "DiscreteMath-RM14k"),
    "Mathematical Physics":                      ("mathphysics_rm14k", "MathPhysics-RM14k"),
    "Probability, Statistics, and ML":           ("probstat_rm14k", "ProbStat-RM14k"),
    "Analysis, PDEs, and Dynamics":              ("analysis_rm14k", "Analysis-RM14k"),
    "Number Theory":                             ("numbertheory_rm14k", "NumberTheory-RM14k"),
    "Geometry and Topology":                     ("geomtopology_rm14k", "GeomTopology-RM14k"),
    "Algebra and Representation Theory":         ("algebra_rm14k", "Algebra-RM14k"),
    "Applied and Computational Mathematics":     ("appliedmath_rm14k", "AppliedMath-RM14k"),
    "Logic and Foundations":                     ("logic_rm14k", "Logic-RM14k"),
    "Other / Cross-disciplinary":                ("crossdisc_rm14k", "CrossDisc-RM14k"),
}


def _load(p: Path, default):
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def composite(p: dict, promise: float) -> float:
    value = p.get("difficulty")
    value = value if isinstance(value, (int, float)) else 0.5
    prov = (0.10 if (p.get("status_summary") or "").strip() else 0.0) \
         + (0.05 if (p.get("source_url") or "").strip() else 0.0)
    status_w = {"open": 1.0, "partially_solved": 0.9, "unknown": 0.7}.get(
        p.get("open_status", ""), 0.5)
    return (0.6 * promise + 0.4 * value + prov) * status_w


def tier_bucket(promise: float) -> int:
    if promise >= 0.40:   # likely / plausible
        return 2
    if promise >= 0.20:   # hard
        return 1
    return 0              # open


def main() -> None:
    index = _load(SRC / "_index.json", [])
    cache = _load(SRC / "solvability_cache.json", {})
    evals = _load(SRC / "solvability_eval.json", {})
    assert index, "researchmath_14k _index.json missing/empty"

    # group by domain
    by_domain: dict[str, list[dict]] = {}
    for p in index:
        by_domain.setdefault(p.get("taxonomy_level_1") or "Other / Cross-disciplinary", []).append(p)

    summary = []
    for domain, (slug, name) in DOMAINS.items():
        pool = by_domain.get(domain, [])
        # unsolved only
        cand = [p for p in pool if p.get("open_status") != "solved"]
        # rank: promising tier first, then composite
        def key(p):
            promise = cache.get(p.get("id", ""), 0.0) or 0.0
            return (tier_bucket(promise), composite(p, promise))
        cand.sort(key=key, reverse=True)
        chosen = cand[:TOP_N]

        out = DATASETS / slug
        # clean rebuild
        if out.is_dir():
            shutil.rmtree(out)
        (out / "problems").mkdir(parents=True, exist_ok=True)

        sub_index, sub_cache, sub_evals = [], {}, {}
        tiers = {"likely": 0, "plausible": 0, "hard": 0, "open": 0, "none": 0}
        for p in chosen:
            pid = p["id"]
            sub_index.append(p)
            if pid in cache:
                sub_cache[pid] = cache[pid]
            if pid in evals:
                sub_evals[pid] = evals[pid]
            # copy full problem detail (with tex)
            src_p = SRC / "problems" / f"{pid}.json"
            if src_p.is_file():
                shutil.copyfile(src_p, out / "problems" / f"{pid}.json")
            t = (evals.get(pid) or {}).get("tier") or "none"
            tiers[t] = tiers.get(t, 0) + 1

        (out / "_index.json").write_text(json.dumps(sub_index, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "solvability_cache.json").write_text(json.dumps(sub_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "solvability_eval.json").write_text(json.dumps(sub_evals, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = {
            "slug": slug,
            "name": name,
            "description": (
                f"The 10 most promising, valuable, and unsolved {domain} problems, "
                f"curated from ResearchMath-14k (arXiv:2605.28003). Ranked by AI-solvability "
                f"(promising) and difficulty + provenance (valuable), restricted to unsolved problems."
            ),
            "source": "https://huggingface.co/datasets/amphora/ResearchMath-14k",
            "paper": "https://arxiv.org/abs/2605.28003",
            "license": "CC BY 4.0",
            "parent_dataset": "researchmath_14k",
            "domain": domain,
            "curated": True,
            "selection": "top-10 unsolved by (solvability tier, 0.6*solvability + 0.4*difficulty + provenance, status-weighted)",
            "version": "1.0.0",
            "year": 2025,
            "problem_count": len(chosen),
            "tags": ["research-level", "open-problems", "curated", "RM14k-subdomain"],
        }
        (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        tier_str = " ".join(f"{k}:{v}" for k, v in tiers.items() if v)
        summary.append((name, len(pool), len(cand), len(chosen), tier_str))

    print(f"{'dataset':<22} {'domain_total':>12} {'unsolved':>9} {'picked':>7}  tiers")
    for name, total, unsolved, picked, tier_str in summary:
        print(f"  {name:<20} {total:>12} {unsolved:>9} {picked:>7}  {tier_str}")
    print(f"\nWrote {len(DOMAINS)} curated subdomain datasets under {DATASETS}")


if __name__ == "__main__":
    main()
