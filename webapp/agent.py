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

from .tools import TOOL_DEFINITIONS, ToolContext, ToolError, execute_tool

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 32_000
MAX_ITERATIONS = 50

SYSTEM_PROMPT = """\
You are the Research Math Agent, an autonomous mathematician working on the \
problems in the *First Proof* benchmark (advanced research-level mathematics: \
spectral graph theory, probability, representation theory, topology, and more).

Your job: produce a correct, rigorous, self-contained proof or solution to the \
problem you are given, and convince yourself it is right.

You have tools: read the problem statement and any allowed reference files, \
write your work into a scratch workspace, run small Python checks, and compile \
LaTeX. Working method:
- Read the problem carefully and restate what must be shown.
- Think through the mathematics before writing. Use run_python to test claims \
on small cases, search for counterexamples, or check algebra/constants — do not \
assert numeric or combinatorial facts you have not checked when checking is cheap.
- Draft the proof into `solution.tex` in your workspace (use the LaTeX style of \
the problem files). Iterate on it. Optionally latex_check it.
- Report outcomes faithfully: if a step is unproven, say so; if a check fails, \
say so with the output. State what you have actually established, not what you \
hoped to.

Boundaries: only the problems/ and skills/ directories and your own workspace are \
readable. Do not attempt to read existing benchmark solutions — those tools will \
refuse. When you have a complete solution written to solution.tex and you are \
confident in it, give a short final summary of the result and the key idea, and \
stop. Lead with the outcome. Pick reasonable options on minor choices rather than \
asking; you are operating autonomously and no one is watching in real time.\
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
    provider: str = "api"


def _initial_user_message(cfg: AgentConfig) -> str:
    return (
        f"Solve benchmark problem `{cfg.problem_id}`. Its LaTeX statement is "
        f"below. Work it through with your tools and write the final proof to "
        f"`solution.tex` in your workspace.\n\n"
        f"<problem id=\"{cfg.problem_id}\">\n{cfg.problem_text}\n</problem>"
    )


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
    ctx = ToolContext(repo_root=repo_root, workspace=workspace)

    client = anthropic.Anthropic(api_key=api_key)

    # The tool list and system prompt are the stable cache prefix.
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    create_kwargs: dict = {
        "model": cfg.model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "tools": TOOL_DEFINITIONS,
    }
    if cfg.thinking:
        create_kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}

    messages: list[dict] = [{"role": "user", "content": _initial_user_message(cfg)}]

    yield AgentEvent("status", {"state": "running", "model": cfg.model,
                                "workspace": str(workspace.relative_to(repo_root)) if _within(workspace, repo_root) else str(workspace)})

    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    for iteration in range(1, MAX_ITERATIONS + 1):
        if _cancelled(handle):
            yield AgentEvent("done", {"reason": "stopped"})
            return
        yield AgentEvent("turn_start", {"iteration": iteration})
        try:
            final_message, stream_events, cancelled = _stream_turn(
                client, create_kwargs, messages, handle
            )
        except anthropic.APIStatusError as exc:
            yield AgentEvent("error", {"message": f"Anthropic API error {exc.status_code}: {exc.message}"})
            yield AgentEvent("done", {"reason": "error"})
            return
        except anthropic.APIError as exc:
            yield AgentEvent("error", {"message": f"Anthropic API error: {exc}"})
            yield AgentEvent("done", {"reason": "error"})
            return

        yield from stream_events
        if cancelled or final_message is None:
            yield AgentEvent("done", {"reason": "stopped"})
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
            yield AgentEvent("done", {"reason": final_message.stop_reason or "end_turn"})
            return

        if _cancelled(handle):
            yield AgentEvent("done", {"reason": "stopped"})
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
    yield AgentEvent("done", {"reason": "max_iterations"})


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

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not project_id:
        try:
            import google.auth
            _, project_id = google.auth.default()
        except Exception:
            pass
    if not project_id:
        yield AgentEvent("error", {"message": "Could not determine Google Cloud project. Set GOOGLE_CLOUD_PROJECT or configure a default project via ADC."})
        yield AgentEvent("done", {"reason": "error"})
        return

    region = os.environ.get("GOOGLE_CLOUD_REGION", "global")

    repo_root = cfg.repo_root or Path(__file__).resolve().parents[1]
    workspace = cfg.workspace or (repo_root / "webapp" / ".runs" / f"{cfg.problem_id}_{int(time.time())}")
    ctx = ToolContext(repo_root=repo_root, workspace=workspace)

    client = AnthropicVertex(region=region, project_id=project_id)

    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    create_kwargs: dict = {
        "model": cfg.model or DEFAULT_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "tools": TOOL_DEFINITIONS,
    }
    if cfg.thinking:
        create_kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}

    messages: list[dict] = [{"role": "user", "content": _initial_user_message(cfg)}]

    yield AgentEvent("status", {"state": "running", "model": cfg.model,
                                "workspace": str(workspace.relative_to(repo_root)) if _within(workspace, repo_root) else str(workspace)})

    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    for iteration in range(1, MAX_ITERATIONS + 1):
        if _cancelled(handle):
            yield AgentEvent("done", {"reason": "stopped"})
            return
        yield AgentEvent("turn_start", {"iteration": iteration})
        try:
            final_message, stream_events, cancelled = _stream_turn(
                client, create_kwargs, messages, handle
            )
        except anthropic.APIStatusError as exc:
            yield AgentEvent("error", {"message": f"Vertex AI API error {exc.status_code}: {exc.message}"})
            yield AgentEvent("done", {"reason": "error"})
            return
        except anthropic.APIError as exc:
            yield AgentEvent("error", {"message": f"Vertex AI API error: {exc}"})
            yield AgentEvent("done", {"reason": "error"})
            return

        yield from stream_events
        if cancelled or final_message is None:
            yield AgentEvent("done", {"reason": "stopped"})
            return

        usage = getattr(final_message, "usage", None)
        if usage is not None:
            for k in totals:
                totals[k] += getattr(usage, k, 0) or 0
            yield AgentEvent("usage", dict(totals))

        messages.append({"role": "assistant", "content": final_message.content})

        tool_uses = [b for b in final_message.content if getattr(b, "type", None) == "tool_use"]
        if final_message.stop_reason != "tool_use" or not tool_uses:
            yield AgentEvent("done", {"reason": final_message.stop_reason or "end_turn"})
            return

        if _cancelled(handle):
            yield AgentEvent("done", {"reason": "stopped"})
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
    yield AgentEvent("done", {"reason": "max_iterations"})


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
