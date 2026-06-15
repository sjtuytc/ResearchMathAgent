"""Claude Code (subscription) provider for the Research Math Agent.

This drives the local ``claude`` CLI in headless mode instead of the paid
Messages API, so a user with a Claude Pro/Max subscription can run the agent
against their monthly plan rather than per-token API credits. The CLI is its own
agent (it has Read/Write/Edit/Bash tools), so here Claude Code *is* the loop: we
spawn it with ``--output-format stream-json`` and translate its event stream into
the same AgentEvent vocabulary the API provider emits, so the UI is identical.

Subscription auth: the CLI uses your ``claude login`` OAuth credentials. We
explicitly strip ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN from the subprocess
environment, because either of those would override subscription billing.

Benchmark integrity: the CLI runs in an isolated scratch directory *outside* the
repository, seeded with only the problem statement and the shared preamble, so it
cannot read the blocked benchmark solution directories.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator

from .agent import AgentConfig, AgentEvent
from .runs import RunHandle

# acceptEdits + an explicit allowlist runs autonomously without interactive
# prompts AND works when the server runs as root (unlike bypassPermissions /
# --dangerously-skip-permissions, which the CLI refuses under root).
_ALLOWED_TOOLS = "Read Write Edit Bash Glob Grep"
_MAX_TURNS = 60
_WALL_CLOCK_SECONDS = 1800

_CC_SYSTEM = (
    "You are the Research Math Agent. You are solving a single research-level "
    "mathematics problem from the First Proof benchmark. The working directory "
    "contains problem.tex (the statement) and preamble.tex (shared LaTeX macros). "
    "Read them, work the mathematics through rigorously (use Bash to run small "
    "python checks when a claim is cheap to verify), and write your final, "
    "self-contained proof to solution.tex in this directory. Report honestly what "
    "you have actually established. Stay within this working directory; do not "
    "look for or read any other files on the system. Lead with the outcome."
)


def claude_code_available() -> str | None:
    """Return the path to the ``claude`` binary, or None if not installed."""
    return shutil.which("claude")


def run_claude_code_agent(cfg: AgentConfig, handle: RunHandle | None = None) -> Iterator[AgentEvent]:
    """Drive the ``claude`` CLI and yield AgentEvents. Never raises."""
    binary = claude_code_available()
    if not binary:
        yield AgentEvent("error", {"message": (
            "The `claude` CLI is not installed or not on PATH. Install Claude Code "
            "and run `claude login` with your Pro/Max subscription."
        )})
        yield AgentEvent("done", {"reason": "error"})
        return

    repo_root = cfg.repo_root or Path(__file__).resolve().parents[1]
    workspace = _seed_workspace(cfg, repo_root)
    if workspace is None:
        yield AgentEvent("error", {"message": f"Problem '{cfg.problem_id}' not found."})
        yield AgentEvent("done", {"reason": "error"})
        return

    prompt = (
        f"Solve the problem in problem.tex (benchmark id {cfg.problem_id}). "
        f"Write the final proof to solution.tex, then give a short summary of the "
        f"result and the key idea."
    )
    cmd = [
        binary, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode", "acceptEdits",
        "--allowedTools", _ALLOWED_TOOLS,
        "--max-turns", str(_MAX_TURNS),
        "--append-system-prompt", _CC_SYSTEM,
        "--no-session-persistence",
    ]
    if cfg.model:
        cmd += ["--model", cfg.model]

    # Subscription auth: ensure no API key shadows the OAuth credential.
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)

    yield AgentEvent("status", {"state": "running", "model": cfg.model or "default",
                                "provider": "claude-code", "workspace": str(workspace)})

    if handle is not None and handle.cancelled:
        yield AgentEvent("done", {"reason": "stopped"})
        return

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(workspace), env=env, text=True, bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,  # own process group so cancel kills the node child too
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

    deadline = time.time() + _WALL_CLOCK_SECONDS
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
                _kill(handle, proc)
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for event in _translate(obj):
                if event.type == "done":
                    saw_result = True
                yield event
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _force_kill(handle, proc)

    if cancelled:
        yield AgentEvent("done", {"reason": "stopped"})
        return
    if timed_out:
        yield AgentEvent("error", {"message": "Run exceeded the time limit; stopped."})
        yield AgentEvent("done", {"reason": "timeout"})
        return

    # Surface the final artifact if one was produced.
    solution = workspace / "solution.tex"
    if solution.is_file():
        text = solution.read_text(encoding="utf-8", errors="replace")
        yield AgentEvent("artifact", {"name": "solution.tex", "content": text[:60_000]})

    if not saw_result:
        msg = ("".join(stderr_chunks)).strip() or "claude CLI exited without a result."
        yield AgentEvent("error", {"message": msg[-1500:]})
        yield AgentEvent("done", {"reason": "error"})


def _kill(handle: RunHandle | None, proc) -> None:
    if handle is not None:
        handle.kill_proc()
    else:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def _force_kill(handle: RunHandle | None, proc) -> None:
    if handle is not None:
        handle.force_kill_proc()
    else:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _seed_workspace(cfg: AgentConfig, repo_root: Path) -> Path | None:
    problem_path = repo_root / "problems" / f"{cfg.problem_id}.tex"
    if not problem_path.is_file():
        return None
    base = Path(tempfile.gettempdir()) / "rma_agent_runs"
    base.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f"{cfg.problem_id}_", dir=base))
    shutil.copyfile(problem_path, workspace / "problem.tex")
    preamble = repo_root / "problems" / "preamble.tex"
    if preamble.is_file():
        shutil.copyfile(preamble, workspace / "preamble.tex")
    return workspace


def _drain(stream, sink: list[str]) -> None:
    try:
        for line in stream:
            sink.append(line)
    except Exception:  # noqa: BLE001
        pass


def _translate(obj: dict) -> Iterator[AgentEvent]:
    """Map one Claude Code stream-json object to zero or more AgentEvents."""
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
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                yield AgentEvent("tool_use", {
                    "id": block.get("id", ""),
                    "name": block.get("name", "tool"),
                    "input": block.get("input", {}),
                })
        return

    if etype == "user":
        content = obj.get("message", {}).get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result":
                    yield AgentEvent("tool_result", {
                        "id": block.get("tool_use_id", ""),
                        "name": "",
                        "output": _result_text(block.get("content")),
                        "is_error": bool(block.get("is_error")),
                    })
        return

    if etype == "result":
        usage = obj.get("usage", {}) or {}
        yield AgentEvent("usage", {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cost_usd": obj.get("total_cost_usd"),
            "num_turns": obj.get("num_turns"),
        })
        yield AgentEvent("done", {"reason": "error" if obj.get("is_error") else "end_turn"})
        return


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return "" if content is None else str(content)
