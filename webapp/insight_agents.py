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
    '"suggested_todos":[{"title":"<action>","priority":"high|medium|low"}]}'
)

_SYSTEM_JSON_SCHEMA = (
    '{"summary":"<2-3 sentence strategic overview>","problems":["<blocker 1>","..."],'
    '"highlights":["<positive finding 1>","..."],'
    '"suggested_todos":[{"title":"<action>","priority":"high|medium|low"}],'
    '"mistakes":["<recurring mistake or lesson learned 1>","..."]}'
)


_INSIGHT_MODEL = "claude-opus-4-8"


def _one_shot(prompt: str) -> dict:
    """Call Vertex one-shot using Sonnet (fast, low quota usage), parse JSON, return dict."""
    from .vertex_llm import complete

    raw = complete(prompt, max_tokens=4096, model=_INSIGHT_MODEL) or ""
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
    """Build system-architecture context for RMAC meta-improvement analysis."""
    lines: list[str] = ["# RMAC System Context\n"]

    # Aggregate issue pipeline health (no per-problem breakdown)
    try:
        from .issues import list_issues
        issue_root = repo_root / "webapp" / "issues"
        total_open = total_resolved = total_in_prog = 0
        dataset_count = problem_count = 0
        if issue_root.is_dir():
            for ds_dir in sorted(issue_root.iterdir()):
                if not ds_dir.is_dir():
                    continue
                dataset_count += 1
                for prob_dir in sorted(ds_dir.iterdir()):
                    if not prob_dir.is_dir():
                        continue
                    problem_count += 1
                    try:
                        issues = list_issues(repo_root, prob_dir.name, ds_dir.name)
                    except Exception:
                        continue
                    total_open += sum(1 for i in issues if i.get("status") == "open")
                    total_in_prog += sum(1 for i in issues if i.get("status") == "in_progress")
                    total_resolved += sum(1 for i in issues if i.get("status") == "resolved")
        total_issues = total_open + total_in_prog + total_resolved
        resolution_rate = (total_resolved / total_issues * 100) if total_issues else 0
        lines.append(
            f"## Issue Pipeline (aggregate)\n"
            f"Datasets: {dataset_count}  Problems tracked: {problem_count}\n"
            f"Total issues ever: {total_issues}  Open: {total_open}  "
            f"In-progress: {total_in_prog}  Resolved: {total_resolved}\n"
            f"Overall resolution rate: {resolution_rate:.0f}%"
        )
    except Exception as e:
        lines.append(f"## Issue Pipeline\n(unavailable: {e})")

    # Cumulative token / cost budget usage
    try:
        from .token_log import today_summary
        today = today_summary(repo_root)
        lines.append(
            f"\n## Resource Usage (today)\n"
            f"Runs: {today.get('runs', 0)}  "
            f"Cost: ${today.get('total_cost', 0):.4f}  "
            f"Tokens in: {today.get('total_in', 0):,}  out: {today.get('total_out', 0):,}"
        )
        try:
            from .token_log import vertex_usage_summary
            all_time = vertex_usage_summary(repo_root, days=3650)
            lines.append(
                f"Cumulative cost: ${all_time.get('total_cost', 0):.2f}  "
                f"Total runs: {all_time.get('total_runs', 0)}"
            )
        except Exception:
            pass
    except Exception:
        pass

    # Meeting / collaboration system stats
    try:
        meet_root = repo_root / "webapp" / "meetings"
        total_rooms = total_messages = 0
        problems_with_meetings: set[str] = set()
        if meet_root.is_dir():
            for pid_dir in meet_root.iterdir():
                if not pid_dir.is_dir():
                    continue
                for room_dir in pid_dir.iterdir():
                    if not room_dir.is_dir():
                        continue
                    total_rooms += 1
                    problems_with_meetings.add(pid_dir.name)
                    msg_file = room_dir / "messages.json"
                    if msg_file.is_file():
                        try:
                            msgs = json.loads(msg_file.read_text(encoding="utf-8"))
                            total_messages += len(msgs) if isinstance(msgs, list) else 0
                        except Exception:
                            pass
        lines.append(
            f"\n## Meeting / Discussion System\n"
            f"Total rooms created: {total_rooms}  "
            f"Problems with meetings: {len(problems_with_meetings)}\n"
            f"Total messages across all rooms: {total_messages}"
        )
    except Exception:
        pass

    # Push-forward automation history
    try:
        pf_state_file = repo_root / "webapp" / "push_forward_state.json"
        if pf_state_file.is_file():
            pf_state = json.loads(pf_state_file.read_text(encoding="utf-8"))
            runs = pf_state.get("runs", [])
            last_date = pf_state.get("last_run_date", "never")
            lines.append(
                f"\n## Push-Forward Automation\n"
                f"Total daily runs completed: {len(runs)}\n"
                f"Last run date: {last_date}"
            )
    except Exception:
        pass

    # Agent architecture inventory
    lines.append(
        "\n## Agent Architecture\n"
        "Agents in use:\n"
        "  critic-agent — discovers proof gaps and opens issues\n"
        "  solver-agent — attempts to resolve open issues\n"
        "  meeting-participants — mathematician personas for collaborative discussion (per-field)\n"
        "  solvability-evaluator — scores proof quality 0-100%\n"
        "  insight-generator (this agent) — meta-analysis\n"
        "Pipeline steps: issue discovery → issue resolution → meeting discussion → solvability eval\n"
        "Automation: daily push-forward triggers all steps across all problems\n"
        "LLM backend: Vertex AI (AnthropicVertex via ADC)\n"
        "LaTeX compilation: tectonic (local binary)\n"
        "Proof storage: best-proof JSON + .tex files per problem"
    )

    # Proof pipeline health (aggregate only)
    try:
        from .proofs import list_best_proofs
        best = list_best_proofs()
        verified = sum(1 for b in best if b.get("verification_passed"))
        models_used = set(b.get("model", "") for b in best if b.get("model"))
        lines.append(
            f"\n## Proof Pipeline Health\n"
            f"Problems with a best proof: {len(best)}\n"
            f"Verified proofs: {verified}/{len(best)}\n"
            f"Models used for proof generation: {', '.join(sorted(models_used)) or 'none'}"
        )
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

    # Problem statement — search problems/<qid>.tex then the dataset store
    # (fp2 / RM14k problems have no problems/<qid>.tex; without this every
    # non-fp1 question insight was generated with no statement → identical).
    try:
        from .dataset_store import find_problem_tex
        stmt = find_problem_tex(repo_root, qid, dataset)
    except Exception:
        stmt = ""
    if stmt.strip():
        lines.append("## Problem Statement (excerpt)")
        lines.append(stmt[:600])

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

    # Best proof status (dataset-aware — fp2/RM14k live under their own dataset)
    try:
        from .proofs import get_best_proof
        best = get_best_proof(qid, dataset)
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
        "Based on the above system-wide context, produce a meta-level improvement report for the "
        "RMAC (Research Math Agent Cluster) system itself — NOT about any specific math problem.\n\n"
        "Your goal is to give the engineering team concrete suggestions on how to improve the RMAC "
        "system: its architecture, agents, pipeline, tooling, and methodology.\n\n"
        "Focus on:\n"
        "- Agent quality: Are critic/solver/meeting prompts well-designed? Where do they likely fail?\n"
        "- Pipeline design: Are the steps (discover → resolve → discuss → eval) well-sequenced? "
        "What's missing or redundant?\n"
        "- Model and strategy diversity: Is the system over-reliant on a single model or approach?\n"
        "- Automation gaps: What manual steps could be automated? What does the daily push-forward miss?\n"
        "- Meeting system effectiveness: Are the mathematician persona discussions producing useful output?\n"
        "- Resource efficiency: Is compute being used well? Any obvious waste or underutilization?\n"
        "- Benchmark methodology: How sound is the issue-based solvability evaluation? What could bias it?\n"
        "- Observability and debugging: Can engineers tell when an agent goes wrong? What's invisible?\n"
        "- Common systemic mistakes: Recurring failure modes in the SYSTEM (not in individual proofs)\n\n"
        "Do NOT mention specific problem IDs (q1, q2, etc.) or individual math results. "
        "This report is about improving the RMAC infrastructure and methodology.\n\n"
        f"Respond with ONLY valid JSON matching this schema:\n{_SYSTEM_JSON_SCHEMA}"
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

    # Questions — first_proof_1 (q1-q10) and first_proof_2 (prob-01..10)
    question_sets = [
        ("first_proof_1", [f"q{i}" for i in range(1, 11)]),
        ("first_proof_2", [f"prob-{i:02d}" for i in range(1, 11)]),
    ]
    for ds, qids in question_sets:
        for qid in qids:
            try:
                generate_question_insight(repo_root, qid, ds)
                results.append({"level": "question", "id": f"{ds}/{qid}", "ok": True})
            except Exception as e:
                log.warning(f"[insight] question {ds}/{qid} failed: {e}")
                results.append({"level": "question", "id": f"{ds}/{qid}", "ok": False, "error": str(e)})

    ok = sum(1 for r in results if r.get("ok"))
    log.info(f"[insight] all done: {ok}/{len(results)} succeeded")
    return {"total": len(results), "ok": ok, "results": results}
