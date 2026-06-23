"""Multi-agent issue discovery, resolution, and verification.

Each agent runs via Google Cloud Vertex AI in an isolated scratch workspace.
Agents communicate back to the issue tracker via ``curl`` calls to
``http://localhost:8000/api/...`` — the same FastAPI server that hosts the UI.

Three agent roles
-----------------
critic-agent    Reads problem + current proof; discovers mathematical gaps;
                opens new issues via the API.
solver-agent    Reads a specific open issue + current proof; proposes and writes
                a fix in solution.tex; posts progress; closes the issue when done.
verifier-agent  Reads an issue + the comments on it; checks whether the latest
                fix is mathematically sound; posts a verdict.

Working-proof lifecycle
-----------------------
``webapp/issues/{pid}/working_solution.tex``  is the shared "current best proof"
for a problem.  It is seeded from the merged final solutions on first use.
When a solver agent successfully improves it, the updated solution.tex is
copied back here so subsequent agents see the improvement.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterator

from .agent import AgentConfig, DEFAULT_MODEL, AgentEvent, run_agent_vertex
from .runs import RunHandle

_ALLOWED_TOOLS = "Read Write Edit Bash Glob"
_MAX_TURNS = 50
_WALL_SECONDS = 1200   # 20 min hard ceiling per agent
_API_BASE = "http://localhost:8000"

# ── working proof helpers ────────────────────────────────────────────────────

def working_proof_path(repo_root: Path, problem_id: str) -> Path:
    return repo_root / "webapp" / "issues" / problem_id / "working_solution.tex"


def get_working_proof(repo_root: Path, problem_id: str) -> str:
    """Return the best available proof tex for problem_id."""
    ws = working_proof_path(repo_root, problem_id)
    if ws.is_file():
        return ws.read_text(encoding="utf-8", errors="replace")
    # Fall back to the merged final-solutions file in the sibling repo
    merged = (
        repo_root.parent / "ResearchMathAgent" / "data"
        / "first_proof_1" / "final_solutions" / "all_proofs_merged.tex"
    )
    if merged.is_file():
        text = merged.read_text(encoding="utf-8", errors="replace")
        chunks = re.split(r"% =====\s*Begin (q\d+)_solution\.tex\s*=====", text)
        for i in range(1, len(chunks), 2):
            if chunks[i] == problem_id:
                body = chunks[i + 1] if i + 1 < len(chunks) else ""
                body = re.sub(r"\s*% =====\s*End.*?=====\s*$", "", body.rstrip())
                proof = body.strip()
                if proof:
                    # Cache it for next time
                    ws.parent.mkdir(parents=True, exist_ok=True)
                    ws.write_text(proof, encoding="utf-8")
                    return proof
    return ""


def save_working_proof(
    repo_root: Path,
    problem_id: str,
    tex: str,
    issue_id: str | None = None,
    issue_title: str | None = None,
    agent: str | None = None,
) -> None:
    from .proof_history import record_proof_version
    old_tex = get_working_proof(repo_root, problem_id)
    p = working_proof_path(repo_root, problem_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tex, encoding="utf-8")
    try:
        record_proof_version(
            repo_root, problem_id, tex,
            old_tex=old_tex or None,
            issue_id=issue_id,
            issue_title=issue_title,
            agent=agent,
        )
    except Exception:
        pass


# ── workspace seeding ────────────────────────────────────────────────────────

def _seed_workspace(
    repo_root: Path,
    problem_id: str,
    issue_data: dict | None = None,
    extra_files: dict[str, str] | None = None,
    dataset: str | None = None,
) -> Path:
    """Create and populate a temp directory for an issue agent."""
    base = Path(tempfile.gettempdir()) / "rma_issue_agents"
    base.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix=f"{problem_id}_", dir=base))

    prob = repo_root / "problems" / f"{problem_id}.tex"
    pre = repo_root / "problems" / "preamble.tex"
    if prob.is_file():
        shutil.copyfile(prob, ws / "problem.tex")
    else:
        # Non-fp1 datasets (fp2, RM14k subdomains, …) have no problems/<pid>.tex;
        # pull the statement from the dataset store so the agent has the problem.
        try:
            from .dataset_store import find_problem_tex
            txt = find_problem_tex(repo_root, problem_id, dataset)
            if txt.strip():
                (ws / "problem.tex").write_text(txt, encoding="utf-8")
        except Exception:
            pass
    if pre.is_file():
        shutil.copyfile(pre, ws / "preamble.tex")

    proof = get_working_proof(repo_root, problem_id)
    if proof:
        (ws / "solution.tex").write_text(proof, encoding="utf-8")

    if issue_data:
        (ws / "issue.json").write_text(
            json.dumps(issue_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    for name, content in (extra_files or {}).items():
        (ws / name).write_text(content, encoding="utf-8")

    # Copy question-level documents into workspace for agent context
    q_docs_dir = repo_root / "documents" / "questions" / problem_id
    if q_docs_dir.is_dir():
        doc_index_lines = []
        for doc_file in sorted(q_docs_dir.glob("*.md")):
            dest = ws / f"docs_{doc_file.name}"
            try:
                shutil.copyfile(doc_file, dest)
                doc_index_lines.append(f"- {dest.name} ({doc_file.stat().st_size} bytes)")
            except Exception:
                pass
        if doc_index_lines:
            (ws / "docs_index.txt").write_text(
                f"Existing documents for {problem_id}:\n" + "\n".join(doc_index_lines),
                encoding="utf-8",
            )

    # Write enabled prefix entries as prefix.md for agent context
    from .prefix import build_prefix_md
    pfx_md = build_prefix_md(repo_root, problem_id)
    if pfx_md:
        (ws / "prefix.md").write_text(pfx_md, encoding="utf-8")

    return ws


# ── discovery agent ──────────────────────────────────────────────────────────

_DISCOVERY_SYSTEM = (
    "You are a mathematical critic agent for the First Proof benchmark. "
    "Your workspace contains problem.tex (the problem) and solution.tex (the current "
    "proof attempt, if any). You have Bash available to call the issue tracker API "
    "via curl. Be precise and mathematical. Only raise genuine gaps, not style issues. "
    "Write your full mathematical analysis (background, gap identification, difficulty assessment) "
    "to analysis.md in the workspace — this feeds the documentation system. "
    "IMPORTANT: When querying the issue tracker, always use ?status=open,in_progress to filter "
    "out resolved issues. Only open and in-progress issues are in scope for your work; "
    "do not re-open or comment on resolved issues."
)


def run_discovery_agent(
    repo_root: Path,
    problem_id: str,
    handle: RunHandle | None = None,
    dataset: str = "first_proof_1",
) -> Iterator[AgentEvent]:
    """Critic agent: reads proof, discovers issues, posts them via the API."""
    ws = _seed_workspace(repo_root, problem_id, dataset=dataset)

    has_proof = (ws / "solution.tex").is_file()
    if has_proof:
        proof_section = (
            "The current proof attempt is in solution.tex. Read it carefully.\n"
        )
    else:
        proof_section = (
            "There is no proof attempt yet (solution.tex does not exist). "
            "Based on the problem statement alone, create issues for the key "
            "sub-lemmas that must be proved.\n"
        )

    has_prefix = (ws / "prefix.md").is_file()
    docs_note = (
        "Existing documentation is in docs_*.md files in your workspace — read them first "
        "to understand prior progress and avoid duplicating known gaps. docs_index.txt lists them."
        if (repo_root / "documents" / "questions" / problem_id).is_dir()
        else ""
    )
    prefix_note = (
        "A curated context prefix is in prefix.md — read it first for background theorems, "
        "definitions, key papers, and proof strategies relevant to this problem."
        if has_prefix else ""
    )

    prompt = f"""You are the critic-agent reviewing problem {problem_id}.

{prefix_note}
{proof_section}
{docs_note}

Your tasks:
1. Read problem.tex to understand exactly what must be proved.
   {"Also read docs_*.md files (prior strategies, progress notes) before reviewing." if docs_note else ""}
2. {"Read solution.tex and identify mathematical gaps, errors, unproven claims, or missing cases." if has_proof else "Identify the key mathematical sub-lemmas needed to solve the problem."}

3. Write a detailed mathematical analysis to analysis.md in your workspace:
   - Section "## Background": key theorems, definitions, and tools relevant to this problem
   - Section "## Proof Structure": outline of what a complete proof requires
   - Section "## Gap Analysis": specific gaps or open sub-lemmas found (cite solution.tex line/step)
   - Section "## Difficulty Assessment": why each gap is hard to close
   - Section "## Suggested Approaches": concrete proof strategies to try
   - Section "## References": prior docs you read, theorems cited

4. For each genuine mathematical gap found, create it in the tracker:

   curl -s -X POST {_API_BASE}/api/issues/{problem_id} \\
     -H 'Content-Type: application/json' \\
     -d '{{"title": "SHORT TITLE", "body": "DETAILED DESCRIPTION WITH MATH", "author": "critic-agent", "labels": ["proof-gap"]}}'

5. Post your full analysis as a comment on the main issue:
   First get the open issue list (never query resolved issues):
   curl -s "{_API_BASE}/api/issues/{problem_id}?status=open,in_progress"
   Then post to the first issue's id (e.g. {problem_id}-1):
   curl -s -X POST {_API_BASE}/api/issues/{problem_id}/{problem_id}-1/comment \\
     -H 'Content-Type: application/json' \\
     -d '{{"author": "critic-agent", "body": "## Mathematical Review\\n\\nFull analysis here..."}}'

6. Link the analysis document to the main issue (so it appears in the Issue tab):
   curl -s -X POST {_API_BASE}/api/issues/{problem_id}/{problem_id}-1/doc \\
     -H 'Content-Type: application/json' \\
     -d '{{"path": "questions/{problem_id}/analysis.md", "title": "Critic Analysis"}}'

Be specific. Cite exact theorems by name. Include the mathematical details that would help
a solver agent understand exactly what needs to be proved.
Always reference the docs you read. After all curl calls, summarize what you found."""

    yield from _run_agent(
        repo_root, ws, prompt, _DISCOVERY_SYSTEM, handle, f"critic/{problem_id}",
        on_done=lambda: _merge_analysis_into_document(repo_root, problem_id, ws),
    )


# ── resolver agent ───────────────────────────────────────────────────────────

_RESOLVER_SYSTEM = (
    "You are a mathematical solver agent for the First Proof benchmark. "
    "You have Read, Write, Edit, Bash, and Glob tools. Your workspace has problem.tex "
    "(the problem), preamble.tex, solution.tex (the current proof), and issue.json "
    "(the issue you must resolve). Use Bash(curl) to post updates to the issue tracker. "
    "Write your improved proof to solution.tex. Be rigorous and honest. "
    "IMPORTANT: Only work on the issue assigned to you in issue.json. If you query the "
    "issue tracker for context, always use ?status=open,in_progress — never read or "
    "act on resolved issues."
)


def run_resolver_agent(
    repo_root: Path,
    problem_id: str,
    issue_id: str,
    handle: RunHandle | None = None,
    dataset: str = "first_proof_1",
) -> Iterator[AgentEvent]:
    """Solver agent: works a specific open issue, updates proof, posts resolution."""
    from .prefix import build_prefix_md
    from .issues import get_issue
    issue = get_issue(repo_root, problem_id, issue_id, dataset)
    if issue is None:
        yield AgentEvent("error", {"message": f"Issue {issue_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    ws = _seed_workspace(repo_root, problem_id, issue_data=issue, dataset=dataset)

    comments_text = "\n".join(
        f"[{c['author']} @ {c.get('created_at','')[:16]}]\n{c['body']}"
        for c in issue.get("comments", [])
    )

    prompt = f"""You are the solver-agent working on issue {issue_id} for problem {problem_id}.

Issue title: {issue.get('title', '')}
Issue body (from issue.json): read it with: cat issue.json

Previous comments:
{comments_text[:3000] if comments_text else '(none)'}

Your tasks:
1. Read problem.tex to understand the full mathematical context.
2. Read solution.tex for the current proof (if it exists).
3. Read issue.json for the issue details.
4. Work on the specific mathematical gap described. Use rigorous mathematics.
   You may use Bash to run small Python checks on claims.
5. Write your improved proof to solution.tex (fix the gap in-place).
6. Post a comment with your findings:
   curl -s -X POST {_API_BASE}/api/issues/{problem_id}/{issue_id}/comment \\
     -H 'Content-Type: application/json' \\
     -d '{{"author": "solver-agent", "body": "YOUR ANALYSIS AND FIX"}}'
7. If fully resolved, close the issue:
   curl -s -X PATCH {_API_BASE}/api/issues/{problem_id}/{issue_id} \\
     -H 'Content-Type: application/json' \\
     -d '{{"status": "resolved"}}'
   If partially resolved:
   curl -s -X PATCH {_API_BASE}/api/issues/{problem_id}/{issue_id} \\
     -H 'Content-Type: application/json' \\
     -d '{{"status": "in_progress"}}'

Report what you actually established, not what you hoped to prove."""

    yield from _run_agent(
        repo_root, ws, prompt, _RESOLVER_SYSTEM, handle, f"solver/{problem_id}/{issue_id}",
        on_done=lambda: _save_improved_proof(
            repo_root, problem_id, ws,
            issue_id=issue_id,
            issue_title=issue.get("title", ""),
        ),
    )


def _save_improved_proof(
    repo_root: Path,
    problem_id: str,
    ws: Path,
    issue_id: str | None = None,
    issue_title: str | None = None,
) -> None:
    """If the agent wrote solution.tex, save it as the working proof and record history."""
    sol = ws / "solution.tex"
    if sol.is_file():
        tex = sol.read_text(encoding="utf-8", errors="replace")
        if tex.strip():
            save_working_proof(
                repo_root, problem_id, tex,
                issue_id=issue_id,
                issue_title=issue_title,
                agent="solver-agent",
            )


def _merge_analysis_into_document(repo_root: Path, problem_id: str, ws: Path) -> None:
    """Append the critic agent's analysis.md into the question strategies and progress docs."""
    analysis_path = ws / "analysis.md"
    if not analysis_path.is_file():
        return
    analysis = analysis_path.read_text(encoding="utf-8", errors="replace").strip()
    if not analysis:
        return
    try:
        from .rich_documents import question_dir
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        section = f"\n\n---\n\n### Critic Agent — {now}\n\n{analysis}\n"
        # Append to strategies.md (agent insights section)
        strat_path = question_dir(repo_root, problem_id) / "strategies.md"
        if strat_path.is_file():
            existing = strat_path.read_text(encoding="utf-8", errors="replace")
            strat_path.write_text(existing.rstrip() + section, encoding="utf-8")
        # Also append a brief note to progress.md
        prog_path = question_dir(repo_root, problem_id) / "progress.md"
        if prog_path.is_file():
            brief = f"\n\n---\n\n### Critic Agent Note — {now}\n\n> Analysis written to [strategies.md](strategies.md). Summary: {analysis[:400]}\n"
            existing = prog_path.read_text(encoding="utf-8", errors="replace")
            prog_path.write_text(existing.rstrip() + brief, encoding="utf-8")
    except Exception:
        pass


# ── verifier agent ───────────────────────────────────────────────────────────

_VERIFIER_SYSTEM = (
    "You are a mathematical verifier agent for the First Proof benchmark. "
    "You check whether a proposed fix for a proof gap is mathematically correct. "
    "Use Bash(curl) to post your verdict. Be rigorous — do not approve a fix "
    "unless you have checked the mathematics step by step. "
    "IMPORTANT: Only verify the issue assigned to you. When querying the issue tracker, "
    "always filter with ?status=open,in_progress — never read or act on resolved issues."
)


def run_verifier_agent(
    repo_root: Path,
    problem_id: str,
    issue_id: str,
    handle: RunHandle | None = None,
    dataset: str = "first_proof_1",
) -> Iterator[AgentEvent]:
    """Verifier agent: checks whether the latest fix on an issue is correct."""
    from .issues import get_issue
    issue = get_issue(repo_root, problem_id, issue_id, dataset)
    if issue is None:
        yield AgentEvent("error", {"message": f"Issue {issue_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    ws = _seed_workspace(repo_root, problem_id, issue_data=issue, dataset=dataset)

    last_comment = ""
    for c in reversed(issue.get("comments", [])):
        if c.get("author") not in ("verifier-agent", "system"):
            last_comment = f"[{c['author']}]\n{c['body']}"
            break

    prompt = f"""You are the verifier-agent checking issue {issue_id} for problem {problem_id}.

Issue title: {issue.get('title', '')}
Status: {issue.get('status', 'open')}
Most recent substantive comment:
{last_comment[:2000] if last_comment else '(none — check the full issue.json)'}

Your tasks:
1. Read problem.tex to understand the full requirements.
2. Read solution.tex for the current proof state.
3. Read issue.json for the full comment thread.
4. Determine: does the current solution.tex address the gap described in this issue?
   Check the mathematics step by step. Use Bash to run small Python verifications if helpful.
5. Post your verdict:
   curl -s -X POST {_API_BASE}/api/issues/{problem_id}/{issue_id}/comment \\
     -H 'Content-Type: application/json' \\
     -d '{{"author": "verifier-agent", "body": "**VERDICT: APPROVED/REJECTED**\\n\\nReasoning: ..."}}'
6. If the fix is correct and the issue is resolved:
   curl -s -X PATCH {_API_BASE}/api/issues/{problem_id}/{issue_id} \\
     -H 'Content-Type: application/json' \\
     -d '{{"status": "resolved"}}'
   If not yet correct, leave the status as-is (open or in_progress).

Be thorough. A false positive (approving a wrong proof) is worse than a false negative."""

    yield from _run_agent(repo_root, ws, prompt, _VERIFIER_SYSTEM, handle, f"verifier/{problem_id}/{issue_id}")


# ── daily issue cycle ────────────────────────────────────────────────────────

def run_issue_cycle(
    repo_root: Path,
    problem_id: str,
    max_resolve: int = 2,
    dataset: str = "first_proof_1",
) -> list[str]:
    """Run discovery then resolve up to max_resolve open issues. Returns log lines."""
    from .issues import list_issues
    log: list[str] = []

    log.append(f"[issue-cycle] {problem_id}: running discovery agent")
    for ev in run_discovery_agent(repo_root, problem_id, dataset=dataset):
        if ev.type in ("text_delta", "error"):
            log.append(ev.data.get("text", ev.data.get("message", "")))

    issues = list_issues(repo_root, problem_id, dataset)
    open_issues = [i for i in issues if i.get("status") in ("open", "in_progress")]
    log.append(f"[issue-cycle] {problem_id}: {len(open_issues)} open issues")

    for issue in open_issues[:max_resolve]:
        iid = issue["id"]
        log.append(f"[issue-cycle] {problem_id}: resolving {iid} — {issue.get('title','')[:60]}")
        for ev in run_resolver_agent(repo_root, problem_id, iid, dataset=dataset):
            if ev.type in ("text_delta", "error"):
                log.append(ev.data.get("text", ev.data.get("message", "")))

    return log


# ── multi-agent discussion ───────────────────────────────────────────────────

_DISCUSSION_PERSONAS: dict[str, str] = {
    "critic-agent": (
        "You are a sharp mathematical critic. Read the discussion and find remaining gaps, "
        "errors, or unproven claims not yet addressed. Be specific: cite exact steps, explain "
        "why they fail. Do NOT repeat issues already raised. 3–6 sentences or bullets max."
    ),
    "solver-agent": (
        "You are a rigorous mathematical problem solver. Read the discussion and propose a "
        "concrete fix for the most critical open gap. Write the key argument (inline LaTeX ok). "
        "State the lemma clearly, sketch the proof, note remaining conditions. 3–8 sentences max."
    ),
    "verifier-agent": (
        "You are a mathematical verifier. Read the discussion. Confirm what is now correct, "
        "flag what still needs work, and give an honest assessment of how close the proof is "
        "to complete. Be brief and direct. 3–6 sentences max."
    ),
    "strategist-agent": (
        "You are a research strategist. Read the discussion. Decide: which issues are most "
        "critical to resolve next and what is the clearest path to a complete proof? "
        "Give a brief action plan (2–4 bullets). Assess overall proof status: nearly done or "
        "major rework needed?"
    ),
}

_DISCUSS_ROTATION = ["critic-agent", "solver-agent", "verifier-agent", "strategist-agent"]


def _thread_to_text(issue: dict, max_chars: int = 6000) -> str:
    lines = [f"# Issue: {issue.get('title', '')}", f"Status: {issue.get('status', 'open')}", ""]
    for c in issue.get("comments", []):
        if c.get("role") == "event":
            continue
        lines.append(f"### {c.get('author', '?')}")
        lines.append((c.get("body") or "").strip())
        lines.append("")
    text = "\n".join(lines)
    return text[-max_chars:] if len(text) > max_chars else text


def _vertex_one_shot(prompt: str, timeout: int = 120) -> str:
    from .vertex_llm import complete

    text = complete(prompt, max_tokens=4096)
    if text:
        return text
    return "(Vertex AI returned no response)"


def run_discussion_agent(
    repo_root: Path,
    problem_id: str,
    issue_id: str,
    dataset: str = "first_proof_1",
    n_turns: int = 3,
    handle: RunHandle | None = None,
) -> Iterator[AgentEvent]:
    """Run N round-robin discussion turns on an issue thread."""
    from .issues import get_issue, add_comment

    issue = get_issue(repo_root, problem_id, issue_id, dataset)
    if issue is None:
        yield AgentEvent("error", {"message": f"Issue {issue_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    last_agent = None
    for c in reversed(issue.get("comments", [])):
        if c.get("role") == "agent" and c.get("author") in _DISCUSS_ROTATION:
            last_agent = c.get("author")
            break

    start_idx = 0
    if last_agent and last_agent in _DISCUSS_ROTATION:
        start_idx = (_DISCUSS_ROTATION.index(last_agent) + 1) % len(_DISCUSS_ROTATION)

    for turn in range(n_turns):
        if handle is not None and handle.cancelled:
            yield AgentEvent("done", {"reason": "cancelled"})
            return

        agent_name = _DISCUSS_ROTATION[(start_idx + turn) % len(_DISCUSS_ROTATION)]
        persona = _DISCUSSION_PERSONAS[agent_name]

        issue = get_issue(repo_root, problem_id, issue_id, dataset)
        if issue is None:
            break

        thread_text = _thread_to_text(issue)
        prompt = (
            f"{persona}\n\n---\n\nCURRENT DISCUSSION THREAD:\n{thread_text}\n\n---\n\n"
            f"Write your response as {agent_name}. Be concise and mathematical. "
            "Do not open with meta-commentary — post your message directly."
        )

        yield AgentEvent("text_delta", {"text": f"[discuss] {agent_name} thinking…\n"})

        response = _vertex_one_shot(prompt)
        if response:
            add_comment(repo_root, problem_id, issue_id, agent_name, response, dataset)
            yield AgentEvent("text_delta", {"text": f"[discuss] {agent_name} posted.\n"})
            yield AgentEvent("result", {"agent": agent_name, "body": response})

        time.sleep(1)

    yield AgentEvent("done", {"reason": "done"})


def generate_issue_summary(
    repo_root: Path,
    problem_id: str,
    issue_id: str,
    dataset: str = "first_proof_1",
) -> dict:
    """Synthesize an issue thread into a structured markdown document."""
    from .issues import get_issue, add_issue_document

    issue = get_issue(repo_root, problem_id, issue_id, dataset)
    if issue is None:
        return {"error": "issue not found"}

    thread_text = _thread_to_text(issue, max_chars=8000)
    prompt = (
        "You are a mathematical research coordinator. Synthesize the following issue "
        "discussion thread into a structured markdown document.\n\n"
        f"ISSUE THREAD:\n{thread_text}\n\n---\n\n"
        "Write a structured markdown document with exactly these sections:\n\n"
        "## Summary\n(2–3 sentence overview)\n\n"
        "## Key Findings\n(bullet list of main mathematical findings / gaps / fixes)\n\n"
        "## Current Status\n(what is resolved vs. still open; overall completeness)\n\n"
        "## Open Questions\n(unresolved mathematical questions)\n\n"
        "## Next Steps\n(concrete actions to close this issue)\n\n"
        "Write only the markdown. Be precise and mathematical."
    )

    doc_text = _claude_one_shot(prompt, repo_root, timeout=180)

    doc_dir = repo_root / "documents" / "questions" / problem_id / "issues"
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / f"{issue_id}-summary.md"
    doc_path.write_text(doc_text, encoding="utf-8")

    rel_path = f"questions/{problem_id}/issues/{issue_id}-summary.md"
    title = f"Discussion Summary — {(issue.get('title') or issue_id)[:50]}"
    updated = add_issue_document(repo_root, problem_id, issue_id, title, rel_path,
                                 created_by="document-manager", dataset=dataset)
    return {"ok": True, "path": rel_path, "title": title, "issue": updated}


# ── internal: generic agent driver ──────────────────────────────────────────

def _run_agent(
    repo_root: Path,
    workspace: Path,
    prompt: str,
    system_extra: str,
    handle: RunHandle | None,
    label: str,
    on_done: "callable | None" = None,
    max_turns: int | None = None,
) -> Iterator[AgentEvent]:
    """Drive an issue/meet agent via Vertex AI tool loop."""
    cfg = AgentConfig(
        problem_id=label.replace("/", "_")[:32] or "issue",
        problem_text="",
        initial_message=prompt,
        system_prompt=system_extra,
        status_label=label,
        model=DEFAULT_MODEL,
        workspace=workspace,
        repo_root=repo_root,
        provider="vertex",
        thinking=False,
        max_wall_seconds=_WALL_SECONDS,
        max_iterations=max_turns or _MAX_TURNS,
    )

    saw_done = False
    reason = "error"
    try:
        for ev in run_agent_vertex(cfg, handle):
            if ev.type == "done":
                saw_done = True
                reason = ev.data.get("reason", "end_turn")
            yield ev
    finally:
        if on_done and saw_done and reason not in ("error", "timeout", "stopped"):
            try:
                on_done()
            except Exception:  # noqa: BLE001
                pass


# Legacy CLI helpers removed — all agents use Vertex AI.
