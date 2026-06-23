"""One-shot Google Cloud Vertex AI completions.

Replaces the local ``claude`` CLI for simple prompt/response calls
(solvability eval, literature discovery, concept extraction, issue discussion).
"""

from __future__ import annotations

import logging
import os
import time

from .vertex import DEFAULT_MODEL, vertex_adc_project, vertex_region

logger = logging.getLogger(__name__)

# Per-minute quota on Vertex is shared with streaming agent runs and other researchers
# on this NAIRR shared project.  Back off aggressively so we eventually get through.
_RETRY_INITIAL = (60, 120, 300)   # ramp-up delays on 429
_RETRY_STEADY = 600               # steady-state delay after ramp-up
_RETRY_MAX_ATTEMPTS = 200         # ~33 hours of retries at 600s each
_RETRY_DELAYS = (*_RETRY_INITIAL, *([_RETRY_STEADY] * (_RETRY_MAX_ATTEMPTS - len(_RETRY_INITIAL))))


def complete(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 8192,
    thinking_budget: int = 0,
) -> str | None:
    """Run a single-turn Vertex completion. Returns text or None on failure.

    Retries automatically on quota errors (HTTP 429) with exponential backoff.
    Set thinking_budget > 0 to enable extended thinking (budget in tokens).
    """
    if os.environ.get("RMA_PROVIDER") == "claude-code":
        # Subscription path — no Vertex, no API key. One-shot via the claude CLI.
        from .claude_code import complete_via_cli
        return complete_via_cli(prompt, system=system, model=model or DEFAULT_MODEL)
    try:
        from anthropic import AnthropicVertex
    except ImportError:
        logger.warning("anthropic[vertex] not installed; skipping Vertex completion")
        return None

    project_id = vertex_adc_project().strip()
    if not project_id:
        logger.warning("No GCP project ID found; skipping Vertex completion")
        return None

    use_model = model or DEFAULT_MODEL
    client = AnthropicVertex(region=vertex_region(), project_id=project_id)
    effective_max_tokens = max(max_tokens, thinking_budget + 4096) if thinking_budget > 0 else max_tokens
    kwargs: dict = {
        "model": use_model,
        "max_tokens": effective_max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    if thinking_budget > 0:
        # Opus 4.8 on Vertex uses adaptive thinking; the older
        # {"type":"enabled","budget_tokens":N} form is rejected with a 400.
        kwargs["thinking"] = {"type": "adaptive"}

    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS):
        try:
            msg = client.messages.create(**kwargs)
            parts: list[str] = []
            for block in msg.content:
                if getattr(block, "type", None) == "text":
                    parts.append(getattr(block, "text", "") or "")
            text = "".join(parts).strip()
            return text or None
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            # If the model rejects the thinking config, strip it and retry once
            # without extended thinking (keeps synthesis working across models).
            if "thinking" in err_str and "thinking" in kwargs:
                logger.info("Model rejected thinking config; retrying without extended thinking")
                kwargs.pop("thinking", None)
                continue
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                logger.info("Vertex quota exceeded, retrying in %ds (attempt %d)…", delay, attempt + 1)
                time.sleep(delay)
                continue
            logger.warning("Vertex completion failed (model=%s): %s", use_model, exc)
            return None

    logger.warning("Vertex completion exhausted retries (model=%s): %s", use_model, last_exc)
    return None
