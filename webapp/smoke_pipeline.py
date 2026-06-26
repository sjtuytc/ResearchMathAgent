"""End-to-end single-problem pipeline: solve + LLM evaluation, push-forward rounds.

Used by the external smoke-test endpoint (`POST /api/solve`). Given one problem,
it runs the full RMA loop:

    round 1: solve  -> LLM evaluation
    round k: if not APPROVED and rounds remain, feed the evaluation back, refine
             the proof, evaluate again.

Returns the final proof and the evaluation(s). Everything is ephemeral — a
throwaway temp workspace deleted afterward, no stored context seeded in, nothing
written to the issue/document/strategy stores (per NDA).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from .agent import DEFAULT_MODEL, AgentConfig, run_agent, run_agent_vertex


def _provider() -> str:
    """Which LLM backend the smoke endpoint bills to.

    Default ``claude-code`` = the user's Claude Pro/Max subscription via the local
    `claude` CLI (no API key, no Vertex/GCP). Override with RMA_SMOKE_PROVIDER=
    api (Anthropic API key) or vertex (Google Cloud) only when explicitly intended.
    """
    prov = (os.environ.get("RMA_SMOKE_PROVIDER") or "").strip().lower()
    if prov:
        return prov
    from .claude_code import claude_code_available
    if claude_code_available():
        return "claude-code"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    return "claude-code"


def _complete_anthropic(prompt: str, system: str, model: str, max_tokens: int = 4096) -> str | None:
    """Single-shot completion via the Anthropic API (billed to our account)."""
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    client = anthropic.Anthropic(api_key=key)
    kwargs: dict = {"model": model, "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    parts = [getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip() or None

_EVAL_SYSTEM = (
    "You are a rigorous mathematical proof verifier and evaluator. You read a "
    "problem and a candidate solution and judge correctness and completeness, "
    "erring toward rejection: approving a wrong proof is worse than rejecting a "
    "correct one. Be specific about gaps."
)

_EVAL_PROMPT = """Evaluate the candidate solution to the following research-level problem.

--- PROBLEM ---
{problem}
--- CANDIDATE SOLUTION ---
{proof}
--- END ---

Assess: (1) is the argument mathematically correct and complete? (2) what gaps,
errors, or unjustified steps remain? (3) an overall score 0-100 (100 = fully
correct and complete).

Respond with ONLY valid JSON, no prose outside it:
{{
  "verdict": "APPROVED" | "REJECTED",
  "score": <integer 0-100>,
  "issues": ["<gap or error>", "..."],
  "summary": "<2-3 sentence assessment>"
}}"""


def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def evaluate_proof(problem: str, proof: str, model: str = DEFAULT_MODEL) -> dict:
    """LLM evaluation of a proof: verdict + score + remaining issues."""
    prompt = _EVAL_PROMPT.format(problem=problem[:8000], proof=(proof or "")[:16000])
    prov = _provider()
    if prov == "vertex":
        from .vertex_llm import complete
        raw = complete(prompt, system=_EVAL_SYSTEM, model=model, max_tokens=4096)
    elif prov == "claude-code":
        from .claude_code import complete_via_cli
        raw = complete_via_cli(prompt, system=_EVAL_SYSTEM, model=model)
    else:
        raw = _complete_anthropic(prompt, _EVAL_SYSTEM, model, max_tokens=4096)
    ev = _parse_json(raw) or {}
    score = ev.get("score")
    try:
        score = int(max(0, min(100, int(score))))
    except (TypeError, ValueError):
        score = None
    verdict = str(ev.get("verdict", "")).upper().strip() or "UNKNOWN"
    issues = ev.get("issues") if isinstance(ev.get("issues"), list) else []
    return {"verdict": verdict, "score": score,
            "issues": [str(i) for i in issues][:12], "summary": str(ev.get("summary", ""))}


def _run_solver(repo_root: Path, problem: str, workspace: Path,
                prior_proof: str, feedback: str, model: str, max_wall: int) -> tuple[str, str | None]:
    """One agentic solve/refine pass; returns (proof_text, error)."""
    if prior_proof:
        (workspace / "solution.tex").write_text(prior_proof, encoding="utf-8")
    provider = _provider()
    cfg = AgentConfig(
        problem_id=f"smoke-{uuid.uuid4().hex[:8]}",   # random id => no stored context seeded
        problem_text=problem,
        model=model,
        repo_root=repo_root,
        workspace=workspace,
        thinking=True,
        provider=provider,
        prefix_context=feedback or "",
        max_wall_seconds=max_wall,
    )
    if provider == "vertex":
        runner = run_agent_vertex
    elif provider == "claude-code":
        from .claude_code import run_claude_code_agent
        runner = run_claude_code_agent      # Claude Pro/Max subscription via the CLI
    else:
        runner = run_agent                  # Anthropic API key
    proof, text, err = "", [], None
    for ev in runner(cfg, None):
        if ev.type == "artifact":
            c = (ev.data or {}).get("content") or ""
            if c.strip():
                proof = c
        elif ev.type == "text_delta":
            text.append((ev.data or {}).get("text", ""))
        elif ev.type == "error":
            err = (ev.data or {}).get("message", "error")
    if not proof.strip():
        proof = "".join(text).strip()
    return proof, err


def solve_and_evaluate(repo_root: Path, problem: str, rounds: int = 1,
                       model: str = DEFAULT_MODEL, max_wall: int = 900) -> dict:
    """Run the end-to-end solve + evaluation loop for `rounds` push-forward rounds.

    Returns {answer, evaluation, evaluations, rounds_run, [error]}. Ephemeral.
    """
    rounds = max(1, min(int(rounds or 1), 6))
    workspace = Path(tempfile.mkdtemp(prefix="rma_smoke_"))
    proof, evals, rounds_run, err = "", [], 0, None
    try:
        (workspace / "problem.tex").write_text(problem, encoding="utf-8")
        for r in range(1, rounds + 1):
            rounds_run = r
            feedback = ""
            if proof and evals:
                last = evals[-1]
                issue_lines = "\n".join(f"- {i}" for i in last.get("issues", [])[:8])
                feedback = (
                    "<prior_evaluation>\n"
                    f"The previous proof attempt was judged {last.get('verdict')} "
                    f"(score {last.get('score')}/100).\n"
                    f"Remaining issues to fix:\n{issue_lines or '- (none listed)'}\n"
                    "Revise and complete solution.tex so every issue above is resolved.\n"
                    "</prior_evaluation>"
                )
            proof, serr = _run_solver(repo_root, problem, workspace,
                                      proof if r > 1 else "", feedback, model, max_wall)
            if serr and not proof:
                err = serr
                break
            ev = evaluate_proof(problem, proof, model)
            evals.append(ev)
            if ev.get("verdict", "").startswith("APPROV"):
                break
        out = {
            "answer": proof,
            "rounds_run": rounds_run,
            "evaluation": evals[-1] if evals else None,
            "evaluations": evals,
        }
        if err and not proof:
            out["error"] = err
        return out
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
