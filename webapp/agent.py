"""The Research Math Agent loop.

This is the math-research analog of TheAgentCompany's OpenHands loop: observe →
call Claude (with tools) → execute the tool in a sandbox → feed the result back
→ repeat until the model stops calling tools. The whole loop is exposed as a
generator of structured events so the web UI can render each step live (the
"watch the agent work" effect).

The model is called through the official Anthropic SDK with streaming, native
tool use, adaptive thinking, and prompt caching on the stable prefix.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import anthropic

from .tools import TOOL_DEFINITIONS, ToolContext, ToolError, execute_tool, seed_workspace
from .vertex import estimate_vertex_cost_usd, vertex_adc_project, vertex_region

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 32_000
MAX_ITERATIONS = 50
THINKING_BUDGET = 16_000  # tokens budgeted for extended thinking per turn

SYSTEM_PROMPT = """\
You are the Research Math Agent, an autonomous mathematician working on the \
*First Proof* benchmark (advanced research-level mathematics: spectral graph \
theory, probability, representation theory, algebraic topology, and more).

Your job: produce a correct, rigorous, self-contained proof or solution to the \
problem you are given, and convince yourself it is right.

## Workspace files seeded for you

- `problem.tex` — full problem statement with preamble inlined
- `preamble.tex` — shared LaTeX preamble
- `SKILL.md` — math-research methodology guidance
- `ctx_overview.md` — per-question research overview (if exists)
- `ctx_strategies.md` — accumulated proof strategies and attempts (if exists)
- `ctx_progress.md` — proof progress log (if exists)
- `ctx_timeline.md` — timeline of work on this problem (if exists)
- `solution.tex` — best proof attempt so far (if one exists; improve it)

**Read these context files first.** They contain prior analysis, known gaps, \
and strategies that have already been tried. Do not ignore accumulated knowledge.

## Working method

1. Read `problem.tex` to understand exactly what must be proved.
2. Read all `ctx_*.md` files for prior analysis and strategy context.
3. If `solution.tex` exists, read it and assess what is correct vs. what needs fixing.
4. Think through the mathematics. Use `run_python` to test claims on small cases, \
search for counterexamples, or check algebra/constants — do not assert facts \
you have not checked when checking is cheap.
5. Write or improve the proof in `solution.tex` using the LaTeX style of the problem.
6. Iterate: identify gaps, fix them, re-check. Use `latex_check` to confirm it compiles.
7. Report faithfully: if a step is unproven say so; if a check fails include the output.

## Boundaries

Only `problems/`, `skills/`, and `documents/` directories plus your workspace \
are readable. Do not attempt to read benchmark solution directories — they will \
refuse. When you have a complete, confident solution in `solution.tex`, give a \
short final summary and stop. Lead with the outcome.\
"""


@dataclass
class AgentEvent:
    """A structured step in the agent run, streamed to the UI."""

    type: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, **self.data}


@dataclass
class AgentConfig:
    problem_id: str
    problem_text: str
    model: str = DEFAULT_MODEL
    workspace: Path | None = None
    repo_root: Path | None = None
    thinking: bool = True
    provider: str = "vertex"
    gcp_project: str = ""
    system_prompt: str | None = None
    initial_message: str | None = None
    status_label: str = ""
    max_wall_seconds: int | None = None
    max_iterations: int | None = None
    prefix_context: str = ""  # accumulated docs (strategies, progress, issues, etc.)


def build_prefix_context(repo_root: Path, problem_id: str) -> str:
    """Assemble all accumulated research context for a problem into one string.

    This is injected as a cached prefix block before the solve instruction so
    the model has full situational awareness without tool round-trips.
    """
    parts: list[str] = []
    qdir = repo_root / "documents" / "questions" / problem_id
    doc_map = [
        ("overview",   "## Research Overview"),
        ("strategies", "## Known Strategies and Attempts"),
        ("progress",   "## Proof Progress Log"),
        ("timeline",   "## Work Timeline"),
    ]
    for stem, heading in doc_map:
        # Prefer .tex; fall back to .md for legacy files
        fpath = qdir / f"{stem}.tex"
        if not fpath.is_file():
            fpath = qdir / f"{stem}.md"
        if not fpath.is_file():
            # Also check workspace-style ctx_ prefix
            for ext in (".tex", ".md"):
                alt = qdir / f"ctx_{stem}{ext}"
                if alt.is_file():
                    fpath = alt
                    break
        if fpath.is_file():
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    parts.append(f"{heading}\n\n{text}")
            except OSError:
                pass

    # Open issues summary
    try:
        issues_dir = repo_root / "webapp" / "issues" / "first_proof_1" / problem_id
        if issues_dir.is_dir():
            issue_lines: list[str] = []
            for f in sorted(issues_dir.glob("*.json")):
                import json
                try:
                    issue = json.loads(f.read_text(encoding="utf-8"))
                    status = issue.get("status", "")
                    if status in ("open", "in_progress"):
                        title = issue.get("title", "")
                        body = (issue.get("body") or "")[:300]
                        issue_lines.append(f"- [{status.upper()}] {title}: {body}")
                except Exception:  # noqa: BLE001
                    pass
            if issue_lines:
                parts.append("## Open Issues\n\n" + "\n".join(issue_lines))
    except Exception:  # noqa: BLE001
        pass

    if not parts:
        return ""
    return (
        f"<research_context problem=\"{problem_id}\">\n"
        + "\n\n---\n\n".join(parts)
        + "\n</research_context>"
    )


def _initial_user_message(cfg: AgentConfig) -> str:
    """Build the full initial user message with problem + rich prefix context."""
    lines: list[str] = []

    # Block 1: problem statement (the primary cache anchor per-problem)
    lines.append(
        f"<problem id=\"{cfg.problem_id}\">\n"
        f"{cfg.problem_text}\n"
        f"</problem>"
    )

    # Block 2: accumulated research context (strategies, progress, issues)
    if cfg.prefix_context:
        lines.append(cfg.prefix_context)

    # Block 3: the actual instruction
    ctx_note = (
        " Your workspace also contains `ctx_*.md` files with prior research "
        "context — read them before attempting the proof."
        if cfg.prefix_context else ""
    )
    lines.append(
        f"Solve benchmark problem `{cfg.problem_id}`. "
        f"Work through it rigorously with your tools and write the final proof "
        f"to `solution.tex` in your workspace.{ctx_note} "
        f"If `solution.tex` already exists, read it first and improve rather "
        f"than starting from scratch."
    )

    return "\n\n".join(lines)


def _build_first_message_content(cfg: AgentConfig) -> list[dict]:
    """Build the first user message as a list of content blocks.

    Structure for maximum prompt-cache efficiency:
      Block 0: problem statement — stable per problem, cached across runs
      Block 1: accumulated research context — changes slowly, cached when stable
      Block 2: instruction — short, never cached (always last)

    Each cache_control block marks the END of a cacheable prefix.
    """
    blocks: list[dict] = []

    # ── Block 0: problem statement (primary cache anchor) ──────────────────
    problem_block_text = (
        f"<problem id=\"{cfg.problem_id}\">\n"
        f"{cfg.problem_text}\n"
        f"</problem>"
    )
    blocks.append({
        "type": "text",
        "text": problem_block_text,
        "cache_control": {"type": "ephemeral"},
    })

    # ── Block 1: accumulated research context (secondary cache anchor) ──────
    if cfg.prefix_context:
        blocks.append({
            "type": "text",
            "text": cfg.prefix_context,
            "cache_control": {"type": "ephemeral"},
        })

    # ── Block 2: solve instruction (always last, not cached) ─────────────────
    ctx_note = (
        " Your workspace also contains `ctx_*.md` files with prior research "
        "context (strategies, progress, issues) — **read them before attempting "
        "the proof**, they contain accumulated knowledge about this problem."
        if cfg.prefix_context else
        " Your workspace contains `problem.tex`, `preamble.tex`, and `SKILL.md`."
    )
    sol_note = (
        " `solution.tex` in your workspace is seeded with the best proof so far — "
        "read it first and improve it rather than starting from scratch."
        if cfg.prefix_context else ""  # only mention if we know there's context
    )
    blocks.append({
        "type": "text",
        "text": (
            f"Solve benchmark problem `{cfg.problem_id}` — work through it "
            f"rigorously using your tools and write the complete, correct proof "
            f"to `solution.tex` in your workspace.{ctx_note}{sol_note}"
        ),
    })

    return blocks


def _artifact_from_workspace(ctx: ToolContext) -> AgentEvent | None:
    sol = ctx.workspace / "solution.tex"
    if not sol.is_file():
        return None
    text = sol.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    return AgentEvent("artifact", {"name": "solution.tex", "content": text[:60_000]})


def _finish_turn(ctx: ToolContext, reason: str) -> Iterator[AgentEvent]:
    artifact = _artifact_from_workspace(ctx)
    if artifact is not None:
        yield artifact
    yield AgentEvent("done", {"reason": reason})


def run_agent(cfg: AgentConfig, handle=None) -> Iterator[AgentEvent]:
    """Drive the agent loop, yielding AgentEvents. Never raises — failures are
    emitted as ``error`` events so the UI stream stays well-formed.

    ``handle`` is an optional RunHandle (webapp.runs) carrying a cancel signal so
    the loop can be stopped between turns / mid-stream from another thread."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield AgentEvent("error", {"message": "ANTHROPIC_API_KEY is not set in the server environment."})
        yield AgentEvent("done", {"reason": "error"})
        return

    repo_root = cfg.repo_root or Path(__file__).resolve().parents[1]
    workspace = cfg.workspace or (repo_root / "webapp" / ".runs" / f"{cfg.problem_id}_{int(time.time())}")
    seed_workspace(repo_root, cfg.problem_id, workspace)
    ctx = ToolContext(repo_root=repo_root, workspace=workspace)

    client = anthropic.Anthropic(api_key=api_key)

    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    create_kwargs: dict = {
        "model": cfg.model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "tools": TOOL_DEFINITIONS,
    }
    if cfg.thinking:
        # Opus 4.8 uses adaptive thinking; the old {"type":"enabled","budget_tokens":N}
        # form is rejected with a 400. effort=high maximizes reasoning depth.
        create_kwargs["thinking"] = {"type": "adaptive"}
        create_kwargs["output_config"] = {"effort": "high"}

    # First user message: problem + cached prefix context + instruction
    first_msg_content = _build_first_message_content(cfg)
    messages: list[dict] = [{"role": "user", "content": first_msg_content}]

    yield AgentEvent("status", {"state": "running", "model": cfg.model,
                                "workspace": str(workspace.relative_to(repo_root)) if _within(workspace, repo_root) else str(workspace)})

    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    for iteration in range(1, MAX_ITERATIONS + 1):
        if _cancelled(handle):
            yield from _finish_turn(ctx, "stopped")
            return
        yield AgentEvent("turn_start", {"iteration": iteration})
        try:
            final_message, stream_events, cancelled = _stream_turn(
                client, create_kwargs, messages, handle
            )
        except anthropic.APIStatusError as exc:
            yield AgentEvent("error", {"message": f"Anthropic API error {exc.status_code}: {exc.message}"})
            yield from _finish_turn(ctx, "error")
            return
        except anthropic.APIError as exc:
            yield AgentEvent("error", {"message": f"Anthropic API error: {exc}"})
            yield from _finish_turn(ctx, "error")
            return

        yield from stream_events
        if cancelled or final_message is None:
            yield from _finish_turn(ctx, "stopped")
            return

        usage = getattr(final_message, "usage", None)
        if usage is not None:
            for k in totals:
                totals[k] += getattr(usage, k, 0) or 0
            yield AgentEvent("usage", dict(totals))

        # Record the assistant turn verbatim (preserves tool_use + thinking blocks).
        messages.append({"role": "assistant", "content": final_message.content})

        tool_uses = [b for b in final_message.content if getattr(b, "type", None) == "tool_use"]
        if final_message.stop_reason != "tool_use" or not tool_uses:
            yield from _finish_turn(ctx, final_message.stop_reason or "end_turn")
            return

        if _cancelled(handle):
            yield from _finish_turn(ctx, "stopped")
            return

        tool_results = []
        for block in tool_uses:
            yield AgentEvent("tool_use", {"id": block.id, "name": block.name, "input": block.input})
            output, is_error = _run_tool(ctx, block.name, block.input)
            yield AgentEvent("tool_result", {"id": block.id, "name": block.name,
                                             "output": output, "is_error": is_error})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": tool_results})

    yield AgentEvent("error", {"message": f"Stopped after {MAX_ITERATIONS} turns without finishing."})
    yield from _finish_turn(ctx, "max_iterations")


def run_agent_vertex(cfg: AgentConfig, handle=None) -> Iterator[AgentEvent]:
    """Same as run_agent() but authenticates via Google Cloud Application Default Credentials.

    Set up ADC first: bash <(curl -sSL https://storage.googleapis.com/cloud-samples-data/adc/setup_adc.sh)
    Then set GOOGLE_CLOUD_PROJECT (required) and GOOGLE_CLOUD_REGION (default: global)."""
    try:
        from anthropic import AnthropicVertex
    except ImportError:
        yield AgentEvent("error", {"message": "anthropic[vertex] is not installed. Run: pip install 'anthropic[vertex]'"})
        yield AgentEvent("done", {"reason": "error"})
        return

    project_id = (cfg.gcp_project or vertex_adc_project()).strip()
    if not project_id:
        yield AgentEvent("error", {"message": "GCP project not set. Enter your Project ID in the UI, set GOOGLE_CLOUD_PROJECT on the server, or configure ADC with a quota project."})
        yield AgentEvent("done", {"reason": "error"})
        return

    region = vertex_region()

    repo_root = cfg.repo_root or Path(__file__).resolve().parents[1]
    workspace = cfg.workspace or (repo_root / "webapp" / ".runs" / f"{cfg.problem_id}_{int(time.time())}")
    seed_workspace(repo_root, cfg.problem_id, workspace)
    ctx = ToolContext(repo_root=repo_root, workspace=workspace)

    client = AnthropicVertex(region=region, project_id=project_id)

    system_text = cfg.system_prompt or SYSTEM_PROMPT
    system = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
    create_kwargs: dict = {
        "model": cfg.model or DEFAULT_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "tools": TOOL_DEFINITIONS,
    }
    if cfg.thinking:
        # Opus 4.8 uses adaptive thinking; the old {"type":"enabled","budget_tokens":N}
        # form is rejected with a 400. effort=high maximizes reasoning depth.
        create_kwargs["thinking"] = {"type": "adaptive"}
        create_kwargs["output_config"] = {"effort": "high"}

    if cfg.initial_message:
        first_msg_content: list[dict] | str = cfg.initial_message
    else:
        first_msg_content = _build_first_message_content(cfg)
    messages: list[dict] = [{"role": "user", "content": first_msg_content}]

    status_data: dict = {
        "state": "running",
        "model": cfg.model,
        "provider": "vertex",
        "workspace": str(workspace.relative_to(repo_root)) if _within(workspace, repo_root) else str(workspace),
    }
    if cfg.status_label:
        status_data["label"] = cfg.status_label
    yield AgentEvent("status", status_data)

    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    max_iter = cfg.max_iterations or MAX_ITERATIONS
    deadline = time.time() + cfg.max_wall_seconds if cfg.max_wall_seconds else None

    for iteration in range(1, max_iter + 1):
        if deadline is not None and time.time() > deadline:
            yield AgentEvent("error", {"message": "Agent exceeded time limit."})
            yield from _finish_turn(ctx, "timeout")
            return
        if _cancelled(handle):
            yield from _finish_turn(ctx, "stopped")
            return
        yield AgentEvent("turn_start", {"iteration": iteration})
        try:
            final_message, stream_events, cancelled = _stream_turn(
                client, create_kwargs, messages, handle
            )
        except anthropic.APIStatusError as exc:
            yield AgentEvent("error", {"message": f"Vertex AI API error {exc.status_code}: {exc.message}"})
            yield from _finish_turn(ctx, "error")
            return
        except anthropic.APIError as exc:
            yield AgentEvent("error", {"message": f"Vertex AI API error: {exc}"})
            yield from _finish_turn(ctx, "error")
            return

        yield from stream_events
        if cancelled or final_message is None:
            yield from _finish_turn(ctx, "stopped")
            return

        usage = getattr(final_message, "usage", None)
        if usage is not None:
            for k in totals:
                totals[k] += getattr(usage, k, 0) or 0
            yield AgentEvent("usage", _vertex_usage_payload(totals, cfg.model))

        messages.append({"role": "assistant", "content": final_message.content})

        tool_uses = [b for b in final_message.content if getattr(b, "type", None) == "tool_use"]
        if final_message.stop_reason != "tool_use" or not tool_uses:
            yield from _finish_turn(ctx, final_message.stop_reason or "end_turn")
            return

        if _cancelled(handle):
            yield from _finish_turn(ctx, "stopped")
            return

        tool_results = []
        for block in tool_uses:
            yield AgentEvent("tool_use", {"id": block.id, "name": block.name, "input": block.input})
            output, is_error = _run_tool(ctx, block.name, block.input)
            yield AgentEvent("tool_result", {"id": block.id, "name": block.name,
                                             "output": output, "is_error": is_error})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": tool_results})

    yield AgentEvent("error", {"message": f"Stopped after {max_iter} turns without finishing."})
    yield from _finish_turn(ctx, "max_iterations")


def _vertex_usage_payload(totals: dict, model: str) -> dict:
    payload = dict(totals)
    payload["cost_usd"] = estimate_vertex_cost_usd(
        model,
        totals.get("input_tokens", 0),
        totals.get("output_tokens", 0),
        cache_read_input_tokens=totals.get("cache_read_input_tokens", 0),
        cache_creation_input_tokens=totals.get("cache_creation_input_tokens", 0),
    )
    return payload


def _cancelled(handle) -> bool:
    return handle is not None and handle.cancelled


def _stream_turn(client: anthropic.Anthropic, create_kwargs: dict, messages: list[dict], handle=None):
    """Stream one assistant turn, buffering delta events to yield after the
    stream context closes. Returns (final_message, buffered_events, cancelled).
    On cancel, aborts the stream and returns final_message=None."""
    buffered: list[AgentEvent] = []
    block_types: dict[int, str] = {}
    with client.messages.stream(messages=messages, **create_kwargs) as stream:
        for event in stream:
            if _cancelled(handle):
                return None, buffered, True
            etype = getattr(event, "type", "")
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                btype = getattr(block, "type", "")
                block_types[event.index] = btype
                if btype == "tool_use":
                    buffered.append(AgentEvent("tool_use_pending", {"name": getattr(block, "name", "")}))
            elif etype == "content_block_delta":
                delta = event.delta
                dtype = getattr(delta, "type", "")
                if dtype == "text_delta":
                    buffered.append(AgentEvent("text_delta", {"text": delta.text}))
                elif dtype == "thinking_delta":
                    buffered.append(AgentEvent("thinking_delta", {"text": delta.thinking}))
        final_message = stream.get_final_message()
    return final_message, buffered, False


def _run_tool(ctx: ToolContext, name: str, tool_input) -> tuple[str, bool]:
    if not isinstance(tool_input, dict):
        return (f"Invalid tool input (expected object): {tool_input!r}", True)
    try:
        return (execute_tool(ctx, name, tool_input), False)
    except ToolError as exc:
        return (f"Error: {exc}", True)
    except Exception as exc:  # noqa: BLE001 - surface any tool crash to the model
        return (f"Unexpected tool error: {exc}", True)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
