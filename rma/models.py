from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_KEYCHAIN_SERVICE = "rma_anthropic_api_key"


class ModelConfigurationError(RuntimeError):
    """Raised when a requested model backend is not configured."""


class ModelRequestError(RuntimeError):
    """Raised when a configured model backend rejects or fails a request."""


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str


def should_use_anthropic(model_name: str, provider: str | None = None) -> bool:
    provider = _model_provider(provider)
    if provider == "anthropic":
        return True
    if provider in {"offline", "claude-code"}:
        return False
    return model_name.lower().startswith("claude-") and not should_use_claude_code(model_name, provider)


def should_use_claude_code(model_name: str, provider: str | None = None) -> bool:
    provider = _model_provider(provider)
    name = model_name.lower()
    return provider == "claude-code" or name in {"claude-code", "claude-code-sonnet", "claude-code-opus", "claude-code-haiku"}


def _model_provider(provider: str | None) -> str:
    return (provider or os.environ.get("RMA_MODEL_PROVIDER", "auto")).lower()


def call_anthropic(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 8192,
    temperature: float = 0.2,
) -> ModelResponse:
    api_key = _load_anthropic_api_key()
    if not api_key:
        raise ModelConfigurationError(
            "Claude model requested, but no Anthropic API key was found. "
            "Set ANTHROPIC_API_KEY or store a key in the macOS Keychain service "
            f"`{ANTHROPIC_KEYCHAIN_SERVICE}` before running RMA."
        )

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300, context=_ssl_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelRequestError(f"Anthropic API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ModelRequestError(f"Anthropic API request failed: {exc.reason}") from exc

    data = json.loads(raw)
    parts = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise ModelRequestError("Anthropic API returned no text content.")
    return ModelResponse(text=text, provider="anthropic", model=model)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _load_anthropic_api_key() -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    return _load_anthropic_api_key_from_keychain()


def _load_anthropic_api_key_from_keychain() -> str | None:
    security_bin = shutil.which("security")
    if security_bin is None:
        return None

    service = os.environ.get("RMA_ANTHROPIC_KEYCHAIN_SERVICE", ANTHROPIC_KEYCHAIN_SERVICE)
    command = [security_bin, "find-generic-password", "-s", service, "-w"]
    account = os.environ.get("RMA_ANTHROPIC_KEYCHAIN_ACCOUNT") or os.environ.get("USER")
    if account:
        command[2:2] = ["-a", account]

    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def call_claude_code(
    *,
    model: str,
    system: str,
    prompt: str,
    cwd: Path,
    timeout: int = 1800,
) -> ModelResponse:
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise ModelConfigurationError(
            "Claude Code backend requested, but the `claude` command is not installed or not on PATH. "
            "Install Claude Code and log in before running RMA with --model-provider claude-code."
        )

    timeout = int(os.environ.get("RMA_CLAUDE_CODE_TIMEOUT", timeout))
    max_turns = int(os.environ.get("RMA_CLAUDE_CODE_MAX_TURNS", "5"))

    command = [
        claude_bin,
        "-p",
        "Generate the requested Research Math Agent proof artifact from the prompt on stdin.",
        "--output-format",
        "text",
        "--append-system-prompt",
        system,
        "--max-turns",
        str(max_turns),
        "--no-session-persistence",
    ]
    model_arg = _claude_code_model_arg(model)
    if model_arg is not None:
        command.extend(["--model", model_arg])

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        if stdout and stdout.strip():
            return ModelResponse(text=stdout.strip(), provider="claude-code", model=model_arg or "claude-code")
        raise ModelRequestError("Claude Code request timed out and produced no output.")

    if proc.returncode != 0:
        detail = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
        raise ModelRequestError(f"Claude Code returned exit code {proc.returncode}: {detail[-4000:]}")

    text = stdout.strip()
    if not text:
        raise ModelRequestError("Claude Code returned no result text.")
    return ModelResponse(text=text, provider="claude-code", model=model_arg or "claude-code")


def _claude_code_model_arg(model: str) -> str | None:
    name = model.lower()
    if name in {"claude-code", "claude-code-default"}:
        return None
    if name == "claude-code-sonnet":
        return "sonnet"
    if name == "claude-code-opus":
        return "opus"
    if name == "claude-code-haiku":
        return "haiku"
    return model
