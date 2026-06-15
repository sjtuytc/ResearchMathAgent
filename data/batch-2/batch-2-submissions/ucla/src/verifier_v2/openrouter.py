"""OpenRouter API client for Gemini and Claude models.

Uses the OpenAI-compatible /v1/chat/completions endpoint.
Synchronous (no background mode), so calls block until completion.
"""
from __future__ import annotations
import os, json
from time import monotonic, sleep
import openai

# Reasoning budget mapping: effort name → token budget for each model family
_CLAUDE_THINKING_BUDGET = {
    "medium": 8_000,
    "high":   16_000,
    "xhigh":  32_000,
}

_GEMINI_THINKING_BUDGET = {
    "medium": 8192,
    "high":   16384,
    "xhigh":  32768,
}

_COST_LOG: list[dict] = []


def get_openrouter_client() -> openai.OpenAI:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        # Check .env files
        for env_path in [
            os.path.join(os.path.dirname(__file__), "..", "Harness", ".env"),
            os.path.join(os.path.dirname(__file__), "..", ".env"),
        ]:
            try:
                for line in open(env_path).read().splitlines():
                    if line.startswith("OPENROUTER_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
            except Exception:
                pass
    return openai.OpenAI(
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
    )


def call_openrouter(
    prompt: str,
    stage: str,
    model: str,
    reasoning: str = "xhigh",
    max_tokens: int = 32_000,
    max_retries: int = 5,
) -> str:
    """Call an OpenRouter model synchronously. Returns output text.

    model examples:
        "anthropic/claude-opus-4-7"
        "google/gemini-2.5-pro"  (or "google/gemini-3.1-pro" when available)
    """
    client = get_openrouter_client()

    extra_body: dict = {}
    if "claude" in model.lower() or "anthropic" in model.lower():
        budget = _CLAUDE_THINKING_BUDGET.get(reasoning, 16_000)
        extra_body["thinking"] = {"type": "enabled", "budget_tokens": budget}
    elif "gemini" in model.lower() or "google" in model.lower():
        budget = _GEMINI_THINKING_BUDGET.get(reasoning, 16384)
        extra_body["thinking_config"] = {"thinking_budget": budget}

    for attempt in range(1, max_retries + 1):
        try:
            started = monotonic()
            print(f"[{stage}] submitting to OpenRouter model={model} reasoning={reasoning}", flush=True)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                extra_body=extra_body if extra_body else None,
            )
            elapsed = monotonic() - started
            text = response.choices[0].message.content or ""

            usage = response.usage
            inp = getattr(usage, "prompt_tokens", 0) if usage else 0
            out = getattr(usage, "completion_tokens", 0) if usage else 0
            # OpenRouter pricing varies; use 0 as placeholder (actual cost in dashboard)
            cost = 0.0
            _COST_LOG.append({
                "stage": stage, "model": model,
                "cost_usd": cost, "input_tokens": inp, "output_tokens": out,
            })
            print(f"[{stage}] done {elapsed:.1f}s in={inp} out={out}", flush=True)
            return text

        except Exception as e:
            print(f"[{stage}] attempt {attempt} error: {e}", flush=True)
            if attempt < max_retries:
                sleep(10 * attempt)

    print(f"[{stage}] all retries exhausted", flush=True)
    return ""


def get_openrouter_cost_log() -> list[dict]:
    return list(_COST_LOG)
