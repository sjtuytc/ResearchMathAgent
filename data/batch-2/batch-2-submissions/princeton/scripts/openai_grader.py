"""OpenAI grader — same prompt as agents/grader.py, different model.

Standalone wrapper around the Responses API for gpt-5.5-pro (or any other
OpenAI model). Mirrors agents/grader.py's `grade_attempt` shape but runs
on the OpenAI Responses API. Not yet wired into the pipeline — exists for
cross-provider disagreement studies (run via scripts/grade_existing_with_openai.py).

Why Responses API: gpt-5.5-pro is a reasoning model and rejects the
v1/chat/completions endpoint (404 NOT_FOUND). Responses API is OpenAI's
post-2025 path for reasoning models — system prompt becomes `instructions`,
user prompt becomes `input`, response text is `response.output_text`.

If OPENAI_API_KEY is unset, all calls raise immediately. The caller is
expected to gate on env-var presence so the wider pipeline can run
Gemini-only when OpenAI is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Concurrency cap for OpenAI calls — separate from Gemini's. gpt-5.5-pro
# is rate-limited per-org; 4 in flight is conservative on a paid plan.
_SEMAPHORE = asyncio.Semaphore(4)

# Lazy client — instantiated on first call so the module imports cleanly
# even when OPENAI_API_KEY is absent (the standalone script path may
# legitimately skip OpenAI on environments without the key).
_client: Any | None = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is unset. Cross-provider grader cannot run "
                "without it. Set the env var or unload this module."
            )
        # Defensive: strip any trailing whitespace / Unicode line separators
        # that crept in via copy-paste (U+2028, U+2029, NBSP, etc.). The
        # OpenAI SDK builds an "Authorization: Bearer <key>" header which
        # httpx encodes as ASCII; one bad char at the tail of the key
        # silently breaks every call with
        # "'ascii' codec can't encode character ' ' in position N"
        # (observed 2026-05-28 — SSM-stored key had a trailing U+2028).
        key = key.strip().rstrip("   ​﻿")
        _client = OpenAI(api_key=key)
    return _client


@dataclass
class OpenAIGraderResult:
    score: float                     # parsed from "SCORE: N/7"; -1.0 if unparsed
    output: str                      # full response text (verbatim model output)
    model: str                       # the model id actually called
    duration_s: float                # wallclock for the call
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_reasoning: int = 0        # output_tokens_details.reasoning_tokens
    error: str | None = None         # set if the call failed; score is -1.0


_SCORE_RE = re.compile(r"SCORE:\s*(\d+(?:\.\d+)?)/7", re.IGNORECASE)


async def grade_with_openai(
    *,
    system_instruction: str,
    user_prompt: str,
    model: str = "gpt-5.5-pro",
    timeout_s: float = 900.0,        # 15 min hard cap — gpt-5.5-pro can be slow
    retries: int = 2,
) -> OpenAIGraderResult:
    """Single OpenAI grader call. Returns OpenAIGraderResult with score parsed
    from `SCORE: N/7`. On error after retries: score=-1.0, error field set."""
    client = _get_client()
    backoff = 2.0
    last_exc: Exception | None = None

    # Defensive Unicode sanitization (belt-and-suspenders with the
    # container's LANG=C.UTF-8 setting). U+2028 LINE SEPARATOR and
    # U+2029 PARAGRAPH SEPARATOR survive most prompts but reliably blow
    # up any path that runs str.encode("ascii"). Observed 2026-05-28
    # Q2+Q5 smoke: every OpenAI gate call failed with
    # "'ascii' codec can't encode character ' '" on proof text,
    # forcing the gate to fall back to gauntlet-only exits. The same
    # proofs handed to the same model from the laptop (UTF-8 locale)
    # graded fine.
    def _sanitize_for_api(s: str) -> str:
        return s.replace(" ", "\n").replace(" ", "\n\n")

    safe_system = _sanitize_for_api(system_instruction)
    safe_user = _sanitize_for_api(user_prompt)

    for attempt in range(retries + 1):
        try:
            async with _SEMAPHORE:
                t0 = time.time()
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.responses.create,
                        model=model,
                        instructions=safe_system,
                        input=safe_user,
                    ),
                    timeout=timeout_s,
                )
                elapsed = time.time() - t0

            out = response.output_text or ""
            m = _SCORE_RE.search(out)
            score = float(m.group(1)) if m else -1.0

            usage = response.usage
            tin = getattr(usage, "input_tokens", 0) or 0
            tout = getattr(usage, "output_tokens", 0) or 0
            treason = 0
            details = getattr(usage, "output_tokens_details", None)
            if details is not None:
                treason = getattr(details, "reasoning_tokens", 0) or 0

            return OpenAIGraderResult(
                score=score, output=out, model=model,
                duration_s=elapsed,
                tokens_in=tin, tokens_out=tout, tokens_reasoning=treason,
            )
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                logger.warning(
                    "OpenAI grader call attempt %d/%d failed: %s. "
                    "Retrying after %.0fs.",
                    attempt + 1, retries + 1, exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff *= 2

    logger.error("OpenAI grader call failed after %d attempts: %s",
                 retries + 1, last_exc)
    return OpenAIGraderResult(
        score=-1.0, output="", model=model, duration_s=0.0,
        error=f"{type(last_exc).__name__}: {str(last_exc)[:400]}",
    )


async def grade_proof(
    *,
    problem: str,
    proof: str,
    additional_materials: str = "(none)",
    bs_flags: str = "(BS detector not run — external grader)",
    model: str = "gpt-5.5-pro",
    timeout_s: float = 900.0,
) -> OpenAIGraderResult:
    """High-level wrapper that loads the canonical grader prompts and runs
    OpenAI on them. Returns a parsed result.

    Mirrors the (system_instruction, user_template) split that agents/grader.py
    uses for the Gemini grader — same words, different model.
    """
    from math_solver.agents.grader import _SYSTEM_INSTRUCTION, _USER_TEMPLATE
    user_prompt = _USER_TEMPLATE.format(
        problem=problem,
        solver_output=proof,
        additional_materials=additional_materials,
        bs_flags=bs_flags,
    )
    return await grade_with_openai(
        system_instruction=_SYSTEM_INSTRUCTION,
        user_prompt=user_prompt,
        model=model,
        timeout_s=timeout_s,
    )
