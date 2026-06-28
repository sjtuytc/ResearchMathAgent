"""Persist interactive solve runs into the document system.

After the live agent finishes (API, Vertex, or Claude Code), this module
saves solution.tex, updates strategy memory, refreshes per-question docs,
runs background discovery, and returns UI-friendly links.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from .documents import write_or_append_report
from .issue_agents import save_working_proof, run_discovery_agent
from .issues import append_activity
from .rich_documents import PROFILES, question_dir, update_discussion_index, update_question_document

try:
    from rma.memory import record_attempt
except ImportError:  # pragma: no cover - package layout fallback
    import sys

    _repo = Path(__file__).resolve().parents[1]
    if str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))
    from rma.memory import record_attempt


def maybe_compile_pdf(repo_root: Path, content: str, name: str) -> str | None:
    if not content.strip():
        return None
    from .latex import compile_tex, latex_available

    if not latex_available():
        return None
    try:
        result = compile_tex(repo_root, content, name)
        return result.get("pdf") if result.get("ok") else None
    except Exception:  # noqa: BLE001
        return None


def _build_report_section(
    problem_id: str,
    started: str,
    transcript: str,
    artifact: dict | None,
    usage: dict | None,
    reason: str,
    provider: str,
    model: str,
    pdf_name: str | None,
    attempt_path: str | None,
) -> str:
    summary = transcript.strip()[-1800:] or "_(no text output)_"
    usage = usage or {}
    lines = [
        f"## {problem_id} — interactive solve ({started})",
        "",
        f"**Provider:** {provider or 'unknown'} · **Model:** {model or 'default'}",
        "",
        "**Outcome summary:**",
        "",
        summary,
        "",
    ]
    bits = []
    if usage.get("cost_usd") is not None:
        bits.append(f"est. cost ${float(usage['cost_usd']):.4f}")
    if usage.get("num_turns") is not None:
        bits.append(f"turns {usage['num_turns']}")
    bits.append(f"tokens in {usage.get('input_tokens', 0)} / out {usage.get('output_tokens', 0)}")
    bits.append(f"stop: {reason}")
    lines.append("**Run:** " + " · ".join(bits))
    if attempt_path:
        lines += ["", f"**Attempt record:** [`{attempt_path}`](/api/document/{attempt_path})"]
    if pdf_name:
        lines += ["", f"**Compiled PDF:** [`{pdf_name}`](/api/pdf/{pdf_name})"]
    if artifact and artifact.get("content"):
        content = artifact["content"]
        lines += [
            "",
            "<details><summary>solution.tex (%d chars)</summary>" % len(content),
            "",
            "```latex",
            content[:8000],
            "```",
            "",
            "</details>",
        ]
    return "\n".join(lines)


_STRATEGY_SUMMARY_SYSTEM = (
    "You are a research assistant summarizing a math proof attempt. "
    "Be concise and precise — 3-6 bullet points max."
)
_STRATEGY_SUMMARY_PROMPT = """\
The following is the output of an autonomous math agent attempting to prove problem {pid}.
Model: {model}. Stop reason: {reason}.

Agent transcript (last 3000 chars):
{transcript_tail}

Summarize what the agent tried, what worked, and what failed or was left unproven.
Output ONLY a markdown bullet list (no header, no prose outside bullets). Example:
- Tried X approach but it failed because Y.
- Established lemma Z correctly.
- Left gap: the case W was not handled.
"""


def _append_solve_to_strategies(
    repo_root: Path,
    problem_id: str,
    transcript: str,
    model: str,
    reason: str,
    solution_tex: str,
) -> None:
    """Summarise this run and append the entry to strategies.md (background-safe)."""
    from .llm import complete

    strat_path = question_dir(repo_root, problem_id) / "strategies.md"
    if not strat_path.is_file():
        return

    transcript_tail = transcript.strip()[-3000:] or "(no transcript)"
    prompt = _STRATEGY_SUMMARY_PROMPT.format(
        pid=problem_id, model=model, reason=reason, transcript_tail=transcript_tail
    )
    summary = complete(prompt, system=_STRATEGY_SUMMARY_SYSTEM, max_tokens=512)
    if not summary:
        # Fallback: use the raw tail without LLM summarization
        summary = f"- Agent ran ({model}, {reason}). Transcript tail:\n```\n{transcript_tail[-600:]}\n```"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    has_proof = bool(solution_tex.strip())
    outcome_badge = "✅ solution produced" if has_proof else "❌ no solution"
    section = (
        f"\n\n---\n\n### Solve run — {now} ({outcome_badge})\n\n"
        f"**Model:** {model or 'unknown'} · **Stop:** {reason}\n\n"
        f"{summary.strip()}\n"
    )
    try:
        existing = strat_path.read_text(encoding="utf-8", errors="replace")
        strat_path.write_text(existing.rstrip() + section, encoding="utf-8")
    except OSError:
        pass


def _run_discovery_background(repo_root: Path, problem_id: str) -> None:
    """Run the discovery (critic) agent in a background thread after solve."""
    try:
        for _ in run_discovery_agent(repo_root, problem_id):
            pass
    except Exception:  # noqa: BLE001
        pass


def finalize_solve_run(
    repo_root: Path,
    problem_id: str,
    *,
    transcript: str = "",
    artifact: dict | None = None,
    usage: dict | None = None,
    reason: str = "end_turn",
    provider: str = "",
    model: str = "",
) -> dict:
    """Save solve output under documents/ and return link metadata for the UI."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    date_str = now.strftime("%Y-%m-%d")
    started = now.strftime("%H:%M UTC")

    solution_tex = (artifact or {}).get("content", "").strip()
    links: list[dict[str, str]] = []
    saved: dict[str, str] = {}
    attempt_rel: str | None = None

    if solution_tex:
        attempts_dir = question_dir(repo_root, problem_id) / "attempts"
        attempts_dir.mkdir(parents=True, exist_ok=True)

        tex_rel = f"questions/{problem_id}/attempts/solution_{ts}.tex"
        tex_path = repo_root / "documents" / tex_rel
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        tex_path.write_text(solution_tex, encoding="utf-8")
        saved["solution_tex"] = tex_rel
        links.append({
            "label": "Solution (LaTeX)",
            "path": tex_rel,
            "url": f"/api/document/{tex_rel}",
        })

        attempt_rel = f"questions/{problem_id}/attempts/{ts}.md"
        attempt_path = repo_root / "documents" / attempt_rel
        summary = transcript.strip()[-1200:] or "_(no agent transcript)_"
        attempt_md = "\n".join([
            f"# {problem_id.upper()} solve attempt — {ts}",
            "",
            f"- **Model:** {model or provider or 'default'}",
            f"- **Provider:** {provider or 'unknown'}",
            f"- **Stop reason:** {reason}",
            "",
            "## Agent summary",
            "",
            summary,
            "",
            "## Solution",
            "",
            f"LaTeX source: [`solution_{ts}.tex`](solution_{ts}.tex)",
            "",
            "```latex",
            solution_tex[:12000],
            "```",
            "",
        ])
        attempt_path.write_text(attempt_md, encoding="utf-8")
        saved["attempt_md"] = attempt_rel
        links.append({
            "label": "Attempt record",
            "path": attempt_rel,
            "url": f"/api/document/{attempt_rel}",
        })

        save_working_proof(repo_root, problem_id, solution_tex)

        pdf_name = maybe_compile_pdf(repo_root, solution_tex, f"solve_{problem_id}_{ts}")
        if pdf_name:
            saved["pdf"] = pdf_name
            links.append({
                "label": "Solution PDF",
                "path": pdf_name,
                "url": f"/api/pdf/{pdf_name}",
            })

    profile = PROFILES.get(problem_id, {})
    outcome = "partial" if solution_tex else "fail"
    if reason in ("error", "timeout", "max_iterations", "disconnected"):
        outcome = "fail"
    record_attempt(
        repo_root / "documents",
        problem_id=problem_id,
        problem_area=profile.get("area", "mathematics"),
        strategy_summary=(transcript.strip()[-400:] or "interactive solve run"),
        outcome=outcome,
        issue_count=-1,
        model=model or provider or "agent",
        notes=f"reason={reason}",
    )

    update_question_document(
        repo_root,
        problem_id,
        reasoning_trace=transcript,
        model_used=model or provider,
        run_outcome=reason,
    )
    progress_rel = f"questions/{problem_id}/progress.md"
    links.append({
        "label": "Progress",
        "path": progress_rel,
        "url": f"/api/document/{progress_rel}",
    })

    section = _build_report_section(
        problem_id, started, transcript, artifact, usage, reason, provider, model,
        saved.get("pdf"), attempt_rel,
    )
    report_path = write_or_append_report(repo_root, date_str, section)
    report_rel = report_path.relative_to(repo_root / "documents").as_posix()
    links.append({
        "label": f"Daily report ({date_str})",
        "path": report_rel,
        "url": f"/api/document/{report_rel}",
    })

    try:
        update_discussion_index(repo_root)
    except Exception:  # noqa: BLE001
        pass

    try:
        append_activity(
            repo_root,
            problem_id,
            f"Interactive solve ({model or provider}, {reason}). "
            + (f"Saved to documents/{attempt_rel}." if attempt_rel else "No solution.tex produced."),
        )
    except Exception:  # noqa: BLE001
        pass

    # Append a strategy entry so the next run starts with richer context
    try:
        threading.Thread(
            target=_append_solve_to_strategies,
            args=(repo_root, problem_id, transcript, model or provider, reason, solution_tex),
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001
        pass

    # Auto-run discovery after a successful solve so gaps are caught immediately
    if solution_tex and reason not in ("error", "stopped"):
        threading.Thread(
            target=_run_discovery_background,
            args=(repo_root, problem_id),
            daemon=True,
        ).start()

    ok = bool(solution_tex)
    message = (
        f"Solution saved to the document system ({len(links)} links)."
        if ok
        else "Run finished but no solution.tex was produced — nothing to save."
    )
    return {"ok": ok, "saved": saved, "links": links, "message": message}
