"""One-shot LLM completions on the Claude Pro/Max subscription.

Replaces the former Vertex AI helpers. Everything routes through the local
``claude`` CLI (subscription billing, no API key, no Google Cloud), so there is
no per-token API spend and nothing can fan out onto a paid backend.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"


def complete(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 8192,  # noqa: ARG001 - accepted for call-site compatibility
    thinking_budget: int = 0,  # noqa: ARG001 - accepted for call-site compatibility
) -> str | None:
    """Run a single-turn completion on the Claude subscription via the `claude`
    CLI. Returns text, or None on failure.

    ``max_tokens`` / ``thinking_budget`` are accepted for backwards compatibility
    with the previous Vertex helper but are managed by the CLI itself.
    """
    from .claude_code import complete_via_cli

    return complete_via_cli(prompt, system=system, model=model or DEFAULT_MODEL)


def estimate_cost_usd(*_args, **_kwargs) -> float:
    """The subscription has no marginal per-call cost, so estimated spend is 0.

    Kept as a no-op shim so historical token-log accounting keeps working.
    """
    return 0.0
