"""AI insight generation — one LLM call per level (system / dataset / question).

Uses _vertex_one_shot from issue_agents to call Claude via Vertex AI.
All generated insights are attributed to "document-manager".
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are an AI research project analyst called document-manager. "
    "You produce concise, actionable intelligence reports for a mathematics research team. "
    "Always respond with valid JSON only — no markdown fences, no commentary."
)

_JSON_SCHEMA = (
    '{"summary":"<2-3 sentence overview>","problems":["<issue 1>","..."],'
    '"highlights":["<positive finding 1>","..."],'
    '"suggested_todos":[{"title":"<action>","priority":"high|medium|low"},"..."]}'
)


def _one_shot(prompt: str) -> dict:
    """Call Vertex one-shot, parse JSON, return dict."""
    from .issue_agents import _vertex_one_shot

    raw = _vertex_one_shot(prompt, timeout=120)
    raw = raw.strip()
    # Strip markdown fences if model added them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except Exception:
        # Partial parse fallback — return raw text as summary
        return {
            "summary": raw[:500] if raw else "Generation failed.",
            "problems": [],
            "highlights": [],
            "suggested_todos": [],
        }


def _gather_system_context(repo_root: Path) -> str:
    """Build a text summary of the whole project for the LLM."""
    lines: list[str] = ["# System Context\n"]

    # Issue stats across all problems
    try:
        from .issues import list_issues
        issue_root = repo_root / "webapp" / "issues"
        total_open = total_resolved = total_in_prog = 0
        per_q: list[str] = []
        if issue_root.is_dir():
            for ds_dir in sorted(issue_root.iterdir()):
                if not ds_dir.is_dir():
                    continue
                for prob_dir in sorted(ds_dir.iterdir()):
                    if not prob_dir.is_dir():
                        continue
                    pid = prob_dir.name
                    try:
                        issues = list_issues(repo_root, pid, ds_dir.name)
                    except Exception:
                        continue
                    o = sum(1 for i in issues if i.get("status") == "open")
                    ip = sum(1 for i in issues if i.get("status") == "in_progress")
                    r = sum(1 for i in issues if i.get("status") == "resolved")
                    total_open += o; total_resolved += r; total_in_prog += ip
                    per_q.append(f"  {ds_dir.name}/{pid}: {o} open, {ip} in-progress, {r} resolved")
        lines.append(f"## Issue Summary\nOpen: {total_open}  In-progress: {total_in_prog}  Resolved: {total_resolved}")
        lines.extend(per_q[:20])
    except Exception as e:
        lines.append(f"## Issue Summary\n(unavailable: {e})")

    # Token / run stats
    try:
        from .token_log import today_summary, per_problem_summary
        today = today_summary(repo_root)
        lines.append(f"\n## Today's Usage\nRuns: {today.get('runs',0)}  Cost: ${today.get('total_cost',0):.4f}  In: {today.get('total_in',0):,}  Out: {today.get('total_out',0):,}")
        by_prob = per_problem_summary(repo_root)
        if by_prob:
            lines.append("\n## Per-Problem Run Counts")
            for pid, s in list(by_prob.items())[:10]:
                lines.append(f"  {pid}: {s.get('total_runs',0)} runs, {s.get('success_runs',0)} success")
    except Exception:
        pass

    # Best proofs
    try:
        from .proofs import list_best_proofs
        best = list_best_proofs()
        if best:
            lines.append("\n## Best Proofs")
            for b in best[:10]:
                vflag = "✓ verified" if b.get("verification_passed") else f"{b.get('issue_count','?')} issues"
                lines.append(f"  {b.get('problem_id','?')}: {vflag}, model={b.get('model','?')}")
    except Exception:
        pass

    # Solvability scores
    try:
        from .solvability_eval import load_eval
        lines.append("\n## Solvability Scores (Opus eval)")
        for qid in [f"q{i}" for i in range(1, 11)]:
            ev = load_eval(repo_root, qid)
            if ev and ev.get("score") is not None:
                lines.append(f"  {qid}: {ev['score']}%")
    except Exception:
        pass

    return "\n".join(lines)


def _gather_dataset_context(repo_root: Path, slug: str) -> str:
    lines: list[str] = [f"# Dataset Context: {slug}\n"]

    try:
        from .dataset_store import get_dataset_meta, list_problems
        meta = get_dataset_meta(slug)
        if meta:
            lines.append(f"Name: {meta.get('name','')}")
            lines.append(f"Problems: {meta.get('problem_count','?')}")
            lines.append(f"Description: {(meta.get('description') or '')[:200]}")
    except Exception:
        pass

    try:
        from .issues import list_issues
        issue_dir = repo_root / "webapp" / "issues" / slug
        if issue_dir.is_dir():
            lines.append("\n## Issues Per Problem")
            for prob_dir in sorted(issue_dir.iterdir()):
                if not prob_dir.is_dir():
                    continue
                pid = prob_dir.name
                issues = list_issues(repo_root, pid, slug)
                o = sum(1 for i in issues if i.get("status") == "open")
                r = sum(1 for i in issues if i.get("status") == "resolved")
                lines.append(f"  {pid}: {o} open, {r} resolved — titles: {', '.join(i.get('title','')[:40] for i in issues[:3])}")
    except Exception:
        pass

    try:
        from .proofs import list_best_proofs
        best = [b for b in list_best_proofs() if True]  # all for now
        if best:
            lines.append("\n## Proof Status")
            for b in best[:10]:
                vflag = "verified" if b.get("verification_passed") else f"{b.get('issue_count','?')} issues"
                lines.append(f"  {b.get('problem_id','?')}: {vflag}")
    except Exception:
        pass

    return "\n".join(lines)


def _gather_question_context(repo_root: Path, qid: str, dataset: str) -> str:
    lines: list[str] = [f"# Question Context: {qid} (dataset={dataset})\n"]

    # Problem statement (first 500 chars of tex)
    prob_tex = repo_root / "problems" / f"{qid}.tex"
    if prob_tex.is_file():
        lines.append("## Problem Statement (excerpt)")
        lines.append(prob_tex.read_text(encoding="utf-8", errors="replace")[:600])

    # Issues
    try:
        from .issues import list_issues
        issues = list_issues(repo_root, qid, dataset)
        lines.append(f"\n## Issues ({len(issues)} total)")
        for iss in issues[:15]:
            lines.append(f"  [{iss.get('status','?')}] {iss.get('title','')[:80]}")
            comments = iss.get("comments", [])
            agent_comments = [c for c in comments if c.get("role") == "agent"]
            if agent_comments:
                last = agent_comments[-1]
                lines.append(f"    Last agent comment by {last.get('author','?')}: {(last.get('body') or '')[:120]}...")
    except Exception:
        pass

    # Best proof status
    try:
        from .proofs import get_best_proof
        best = get_best_proof(qid)
        if best:
            vflag = "verified ✓" if best.get("verification_passed") else f"{best.get('issue_count','?')} open issues"
            lines.append(f"\n## Best Proof\nStatus: {vflag}\nModel: {best.get('model','?')}\nExperiment: {best.get('experiment','?')}")
    except Exception:
        pass

    # Solvability eval
    try:
        from .solvability_eval import load_eval
        ev = load_eval(repo_root, qid)
        if ev and ev.get("score") is not None:
            lines.append(f"\n## Solvability Score\n{ev['score']}% — {(ev.get('reasoning') or '')[:200]}")
    except Exception:
        pass

    # TODOs
    try:
        from .todos import list_todos
        todos = list_todos(repo_root, qid)
        if todos:
            lines.append(f"\n## Existing TODOs ({len(todos)})")
            for t in todos[:8]:
                done = "✓" if t.get("done") else "○"
                lines.append(f"  {done} [{t.get('priority','?')}] {t.get('title','')}")
    except Exception:
        pass

    return "\n".join(lines)


def generate_system_insight(repo_root: Path) -> dict:
    log.info("[insight] generating system-level insight")
    ctx = _gather_system_context(repo_root)
    prompt = (
        f"{_SYSTEM}\n\n"
        f"{ctx}\n\n"
        "Based on the above system-wide context, produce a research project insight report.\n\n"
        "Focus on:\n"
        "- Overall progress and blockers across all problems\n"
        "- Which problems are closest to being solved vs. most stuck\n"
        "- Resource usage and efficiency\n"
        "- High-level strategic recommendations\n\n"
        f"Respond with ONLY valid JSON matching this schema:\n{_JSON_SCHEMA}"
    )
    data = _one_shot(prompt)
    from .insights import save_system_insight
    return save_system_insight(repo_root, data)


def generate_dataset_insight(repo_root: Path, slug: str) -> dict:
    log.info(f"[insight] generating dataset insight for {slug}")
    ctx = _gather_dataset_context(repo_root, slug)
    prompt = (
        f"{_SYSTEM}\n\n"
        f"{ctx}\n\n"
        f"Based on the above context for dataset '{slug}', produce a dataset insight report.\n\n"
        "Focus on:\n"
        "- Which problems in this dataset have the most activity or traction\n"
        "- Common patterns in the open issues\n"
        "- Which problems are likely solvable soon\n"
        "- Suggested priorities for the next week\n\n"
        f"Respond with ONLY valid JSON matching this schema:\n{_JSON_SCHEMA}"
    )
    data = _one_shot(prompt)
    from .insights import save_dataset_insight
    return save_dataset_insight(repo_root, slug, data)


def generate_question_insight(repo_root: Path, qid: str, dataset: str = "first_proof_1") -> dict:
    log.info(f"[insight] generating question insight for {dataset}/{qid}")
    ctx = _gather_question_context(repo_root, qid, dataset)
    prompt = (
        f"{_SYSTEM}\n\n"
        f"{ctx}\n\n"
        f"Based on the above context for question {qid}, produce a per-question insight report.\n\n"
        "Focus on:\n"
        "- Mathematical blockers: what specific gap prevents a complete proof\n"
        "- Quality of the current best proof attempt\n"
        "- Which open issues are most critical to resolve\n"
        "- Concrete next proof-writing or issue-resolution steps\n\n"
        f"Respond with ONLY valid JSON matching this schema:\n{_JSON_SCHEMA}"
    )
    data = _one_shot(prompt)
    from .insights import save_question_insight
    return save_question_insight(repo_root, qid, dataset, data)


def run_all_insights(repo_root: Path) -> dict:
    """Generate insights for system + all active datasets + all first_proof_1 questions."""
    results: list[dict] = []

    # System
    try:
        generate_system_insight(repo_root)
        results.append({"level": "system", "ok": True})
    except Exception as e:
        log.warning(f"[insight] system failed: {e}")
        results.append({"level": "system", "ok": False, "error": str(e)})

    # Datasets — run for first_proof_1 and any that have issues
    datasets_to_run: set[str] = {"first_proof_1"}
    issue_root = repo_root / "webapp" / "issues"
    if issue_root.is_dir():
        for ds_dir in issue_root.iterdir():
            if ds_dir.is_dir():
                datasets_to_run.add(ds_dir.name)

    for slug in sorted(datasets_to_run):
        try:
            generate_dataset_insight(repo_root, slug)
            results.append({"level": "dataset", "id": slug, "ok": True})
        except Exception as e:
            log.warning(f"[insight] dataset {slug} failed: {e}")
            results.append({"level": "dataset", "id": slug, "ok": False, "error": str(e)})

    # Questions — only first_proof_1 q1-q10
    for i in range(1, 11):
        qid = f"q{i}"
        if not (repo_root / "problems" / f"{qid}.tex").is_file():
            continue
        try:
            generate_question_insight(repo_root, qid, "first_proof_1")
            results.append({"level": "question", "id": qid, "ok": True})
        except Exception as e:
            log.warning(f"[insight] question {qid} failed: {e}")
            results.append({"level": "question", "id": qid, "ok": False, "error": str(e)})

    ok = sum(1 for r in results if r.get("ok"))
    log.info(f"[insight] all done: {ok}/{len(results)} succeeded")
    return {"total": len(results), "ok": ok, "results": results}
