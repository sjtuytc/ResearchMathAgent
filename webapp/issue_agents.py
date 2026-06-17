"""Multi-agent issue discovery, resolution, and verification.

Each agent runs the local ``claude`` CLI in an isolated scratch workspace.
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
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator

from .agent import AgentEvent
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


def save_working_proof(repo_root: Path, problem_id: str, tex: str) -> None:
    p = working_proof_path(repo_root, problem_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tex, encoding="utf-8")


# ── workspace seeding ────────────────────────────────────────────────────────

def _seed_workspace(
    repo_root: Path,
    problem_id: str,
    issue_data: dict | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create and populate a temp directory for an issue agent."""
    base = Path(tempfile.gettempdir()) / "rma_issue_agents"
    base.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix=f"{problem_id}_", dir=base))

    prob = repo_root / "problems" / f"{problem_id}.tex"
    pre = repo_root / "problems" / "preamble.tex"
    if prob.is_file():
        shutil.copyfile(prob, ws / "problem.tex")
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

    return ws


# ── discovery agent ──────────────────────────────────────────────────────────

_DISCOVERY_SYSTEM = (
    "You are a mathematical critic agent for the First Proof benchmark. "
    "Your workspace contains problem.tex (the problem) and solution.tex (the current "
    "proof attempt, if any). You have Bash available to call the issue tracker API "
    "via curl. Be precise and mathematical. Only raise genuine gaps, not style issues. "
    "Write your full mathematical analysis (background, gap identification, difficulty assessment) "
    "to analysis.md in the workspace — this feeds the documentation system."
)


def run_discovery_agent(
    repo_root: Path,
    problem_id: str,
    handle: RunHandle | None = None,
    dataset: str = "first_proof_1",
) -> Iterator[AgentEvent]:
    """Critic agent: reads proof, discovers issues, posts them via the API."""
    ws = _seed_workspace(repo_root, problem_id)

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

    prompt = f"""You are the critic-agent reviewing problem {problem_id}.

{proof_section}
Your tasks:
1. Read problem.tex to understand exactly what must be proved.
2. {"Read solution.tex and identify mathematical gaps, errors, unproven claims, or missing cases." if has_proof else "Identify the key mathematical sub-lemmas needed to solve the problem."}

3. Write a detailed mathematical analysis to analysis.md in your workspace:
   - Section "## Background": key theorems, definitions, and tools relevant to this problem
   - Section "## Proof Structure": outline of what a complete proof requires
   - Section "## Gap Analysis": specific gaps or open sub-lemmas found
   - Section "## Difficulty Assessment": why each gap is hard to close
   - Section "## Suggested Approaches": concrete proof strategies to try

4. For each genuine mathematical gap found, create it in the tracker:

   curl -s -X POST {_API_BASE}/api/issues/{problem_id} \\
     -H 'Content-Type: application/json' \\
     -d '{{"title": "SHORT TITLE", "body": "DETAILED DESCRIPTION WITH MATH", "author": "critic-agent", "labels": ["proof-gap"]}}'

5. Post your full analysis as a comment on the main issue:
   First get the issue list:
   curl -s {_API_BASE}/api/issues/{problem_id}
   Then post to the first issue's id (e.g. {problem_id}-1):
   curl -s -X POST {_API_BASE}/api/issues/{problem_id}/{problem_id}-1/comment \\
     -H 'Content-Type: application/json' \\
     -d '{{"author": "critic-agent", "body": "## Mathematical Review\\n\\nFull analysis here..."}}'

Be specific. Cite exact theorems by name. Include the mathematical details that would help
a solver agent understand exactly what needs to be proved.
After all curl calls, summarize what you found."""

    yield from _run_agent(
        ws, prompt, _DISCOVERY_SYSTEM, handle, f"critic/{problem_id}",
        on_done=lambda: _merge_analysis_into_document(repo_root, problem_id, ws),
    )


# ── resolver agent ───────────────────────────────────────────────────────────

_RESOLVER_SYSTEM = (
    "You are a mathematical solver agent for the First Proof benchmark. "
    "You have Read, Write, Edit, Bash, and Glob tools. Your workspace has problem.tex "
    "(the problem), preamble.tex, solution.tex (the current proof), and issue.json "
    "(the issue you must resolve). Use Bash(curl) to post updates to the issue tracker. "
    "Write your improved proof to solution.tex. Be rigorous and honest."
)


def run_resolver_agent(
    repo_root: Path,
    problem_id: str,
    issue_id: str,
    handle: RunHandle | None = None,
    dataset: str = "first_proof_1",
) -> Iterator[AgentEvent]:
    """Solver agent: works a specific open issue, updates proof, posts resolution."""
    from .issues import get_issue
    issue = get_issue(repo_root, problem_id, issue_id, dataset)
    if issue is None:
        yield AgentEvent("error", {"message": f"Issue {issue_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    ws = _seed_workspace(repo_root, problem_id, issue_data=issue)

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
        ws, prompt, _RESOLVER_SYSTEM, handle, f"solver/{problem_id}/{issue_id}",
        on_done=lambda: _save_improved_proof(repo_root, problem_id, ws),
    )


def _save_improved_proof(repo_root: Path, problem_id: str, ws: Path) -> None:
    """If the agent wrote solution.tex, save it as the working proof."""
    sol = ws / "solution.tex"
    if sol.is_file():
        tex = sol.read_text(encoding="utf-8", errors="replace")
        if tex.strip():
            save_working_proof(repo_root, problem_id, tex)


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
    "unless you have checked the mathematics step by step."
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

    ws = _seed_workspace(repo_root, problem_id, issue_data=issue)

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

    yield from _run_agent(ws, prompt, _VERIFIER_SYSTEM, handle, f"verifier/{problem_id}/{issue_id}")


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


def _claude_one_shot(prompt: str, repo_root: Path, timeout: int = 120) -> str:
    binary = shutil.which("claude")
    if not binary:
        return "(claude CLI not found)"
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    try:
        result = subprocess.run(
            [binary, "-p", prompt, "--output-format", "text",
             "--no-session-persistence", "--permission-mode", "acceptEdits"],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(repo_root), env=env,
        )
        return result.stdout.strip() or result.stderr.strip() or "(empty response)"
    except subprocess.TimeoutExpired:
        return "(timed out)"
    except Exception as exc:
        return f"(error: {exc})"


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

        response = _claude_one_shot(prompt, repo_root)
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
    updated = add_issue_document(repo_root, problem_id, issue_id, title, rel_path, dataset=dataset)
    return {"ok": True, "path": rel_path, "title": title, "issue": updated}


# ── internal: generic agent driver ──────────────────────────────────────────

def _run_agent(
    workspace: Path,
    prompt: str,
    system_extra: str,
    handle: RunHandle | None,
    label: str,
    on_done: "callable | None" = None,
    max_turns: int | None = None,
    allowed_tools: str | None = None,
) -> Iterator[AgentEvent]:
    binary = shutil.which("claude")
    if not binary:
        yield AgentEvent("error", {"message": "claude CLI not found on PATH"})
        yield AgentEvent("done", {"reason": "error"})
        return

    cmd = [
        binary, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode", "acceptEdits",
        "--allowedTools", allowed_tools or _ALLOWED_TOOLS,
        "--max-turns", str(max_turns if max_turns is not None else _MAX_TURNS),
        "--append-system-prompt", system_extra,
        "--no-session-persistence",
    ]

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)

    yield AgentEvent("status", {"state": "running", "label": label, "workspace": str(workspace)})

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(workspace), env=env, text=True, bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        yield AgentEvent("error", {"message": f"Failed to start claude CLI: {exc}"})
        yield AgentEvent("done", {"reason": "error"})
        return

    if handle is not None:
        handle.attach_proc(proc)

    stderr_chunks: list[str] = []
    drain = threading.Thread(target=_drain, args=(proc.stderr, stderr_chunks), daemon=True)
    drain.start()

    deadline = time.time() + _WALL_SECONDS
    saw_result = False
    cancelled = False
    timed_out = False

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if handle is not None and handle.cancelled:
                cancelled = True
                handle.kill_proc()
                break
            if time.time() > deadline:
                timed_out = True
                if handle:
                    handle.kill_proc()
                else:
                    proc.terminate()
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for ev in _translate(obj):
                if ev.type == "done":
                    saw_result = True
                yield ev
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if on_done:
        try:
            on_done()
        except Exception:  # noqa: BLE001
            pass

    if cancelled:
        yield AgentEvent("done", {"reason": "stopped"})
        return
    if timed_out:
        yield AgentEvent("error", {"message": "Agent exceeded time limit."})
        yield AgentEvent("done", {"reason": "timeout"})
        return
    if not saw_result:
        msg = "".join(stderr_chunks).strip() or "claude CLI exited without a result"
        yield AgentEvent("error", {"message": msg[-1500:]})
        yield AgentEvent("done", {"reason": "error"})


def _drain(stream, sink: list[str]) -> None:
    try:
        for line in stream:
            sink.append(line)
    except Exception:  # noqa: BLE001
        pass


def _translate(obj: dict) -> Iterator[AgentEvent]:
    """Map one Claude Code stream-json line to AgentEvents."""
    etype = obj.get("type")
    if etype == "stream_event":
        event = obj.get("event", {})
        if event.get("type") == "content_block_delta":
            delta = event.get("delta", {})
            dtype = delta.get("type")
            if dtype == "text_delta" and delta.get("text"):
                yield AgentEvent("text_delta", {"text": delta["text"]})
            elif dtype == "thinking_delta" and delta.get("thinking"):
                yield AgentEvent("thinking_delta", {"text": delta["thinking"]})
        return
    if etype == "assistant":
        msg = obj.get("message", {})
        usage = msg.get("usage") or {}
        if usage.get("input_tokens") or usage.get("output_tokens"):
            yield AgentEvent("turn_usage", {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            })
        for block in msg.get("content", []):
            if block.get("type") == "tool_use":
                yield AgentEvent("tool_use", {
                    "id": block.get("id", ""),
                    "name": block.get("name", "tool"),
                    "input": block.get("input", {}),
                })
        return
    if etype == "result":
        usage = obj.get("usage") or {}
        yield AgentEvent("usage", {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cost_usd": obj.get("total_cost_usd"),
            "num_turns": obj.get("num_turns"),
        })
        yield AgentEvent("done", {"reason": "error" if obj.get("is_error") else "end_turn"})
