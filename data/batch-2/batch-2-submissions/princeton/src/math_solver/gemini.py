"""Async Gemini API client — google-genai SDK, with retry and PDF support."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import google.genai as genai
from google.genai import types as gtypes

from .config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_FLASH_MODEL,
    GEMINI_FALLBACK_MODELS,
    GEMINI_FLASH_FALLBACK_MODELS,
)
from .models import AgentCall

logger = logging.getLogger(__name__)

# Concurrency cap on in-flight Gemini API calls per Python process. Driven
# by the GEMINI_CONCURRENCY env var (default 6 for backwards compat with the
# original hard-coded value). Terraform's `gemini_concurrency` variable and
# the container's `-e GEMINI_CONCURRENCY=...` env both already exist; this
# line is what finally lets them have an effect. Bump to match W when
# running W parallel solvers (otherwise the W solver calls queue in 2+
# batches and the stage wallclock takes a ~1.5× hit).
_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("GEMINI_CONCURRENCY", "6")))

_client: genai.Client | None = None

# Model fallback cache: when a configured model returns 404/NOT_FOUND, we walk
# the configured fallback list and cache the first one that works. All
# subsequent calls reroute to the cached one without re-trying the dead model.
# Keyed by the configured name (e.g. "gemini-3.1-flash-lite") -> effective name
# (e.g. "gemini-2.5-flash-lite"). Cleared on process restart, which is intended
# behavior: a fresh restart re-probes the configured model.
_MODEL_OVERRIDES: dict[str, str] = {}


def _is_model_unavailable(exc: BaseException) -> bool:
    """Heuristic: does this exception indicate the model name is invalid /
    retired / not yet released? These are permanent for the lifetime of a
    run; retrying the same model is pointless, but a fallback may work.

    Distinguishes from transient errors (rate limit, 500, network) which
    are caught by the existing retry loop and should NOT trigger fallback.
    """
    s = str(exc)
    sigils = (
        "404", "NOT_FOUND", "is no longer available", "is not found for API",
        "is not supported", "model is not found", "Model not found",
    )
    return any(sig in s for sig in sigils)


async def _call_with_model_fallback(
    *,
    configured_model: str,
    fallback_models: tuple[str, ...],
    make_call,            # async (model_name) -> SDK response
    log_context: str,     # short label for log messages, e.g. agent="grader"
):
    """Wrap an SDK call with model-deprecation fallback.

    Behavior:
      1. If the configured model has a cached override (we already walked the
         fallback list once this process), use the override directly.
      2. Otherwise try the configured model. If it returns 404/NOT_FOUND,
         walk the fallback list. Cache the first model that responds.
      3. If all options exhaust, raise the last exception.

    Non-availability errors (rate limit, network, 500) are re-raised
    unchanged so the existing retry loop in the caller handles them.
    """
    if configured_model in _MODEL_OVERRIDES:
        return await make_call(_MODEL_OVERRIDES[configured_model])
    try:
        return await make_call(configured_model)
    except Exception as exc:
        if not _is_model_unavailable(exc):
            raise
        logger.error(
            "Configured model %s unavailable (%s); walking fallback chain %s",
            configured_model, log_context, list(fallback_models),
        )
    last_exc: Exception | None = None
    for m in fallback_models:
        try:
            response = await make_call(m)
            _MODEL_OVERRIDES[configured_model] = m
            logger.warning(
                "Model fallback ACTIVE for %s: %s -> %s. Cached for the "
                "rest of this process. Update config to make permanent.",
                log_context, configured_model, m,
            )
            return response
        except Exception as exc:
            last_exc = exc
            if not _is_model_unavailable(exc):
                # Transient error from a fallback — surface to caller's retry.
                raise
    raise RuntimeError(
        f"All model fallbacks exhausted for {log_context} "
        f"(configured={configured_model}, tried={list(fallback_models)}): "
        f"{last_exc}"
    ) from last_exc

# Socket-level read timeout (ms) on every Gemini HTTP call. Set slightly
# below the longest asyncio.wait_for cap in call_gemini (600s) so the
# socket fires first and the worker thread can complete with an error
# rather than blocking indefinitely on a half-dead TCP connection.
# Without this, worker threads stuck in SSL_read_ex orphan the process
# even after asyncio.wait_for raises TimeoutError on the coroutine side.
_HTTP_TIMEOUT_MS = 540_000  # 540 s = 9 min


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=gtypes.HttpOptions(timeout=_HTTP_TIMEOUT_MS),
        )
    return _client


async def call_gemini(
    prompt: str,
    *,
    run_id: str,
    notebook_id: str,
    agent: str,
    inputs: dict[str, Any],
    pdf_paths: list[Path] | None = None,
    temperature: float | None = None,
    use_google_search: bool = False,
    system_instruction: str | None = None,
    store=None,
) -> AgentCall:
    """
    Single Gemini API call with retry, PDF attachment, and call logging.
    Returns an AgentCall with response text and token counts.

    `system_instruction`: when set, behavior-shaping content (personas,
    discipline rules, execution protocol, output format spec) lives here
    rather than in the user prompt.  Models give system content priority
    attention, which improves adherence to discipline rules.
    """
    call_id = uuid.uuid4().hex[:12]
    client = _get_client()

    # Use SDK defaults for temperature and max_output_tokens (Sanjeev's rule:
    # 2026-05-20).  Only thinking_level is set explicitly — HIGH is Google's
    # default for gemini-3.1-pro-preview and we want that pinned so future
    # SDK default changes don't silently alter pipeline behavior.
    # Callers may still override temperature via the parameter when needed
    # (e.g., the Flash utility extractors that want deterministic JSON output).
    config = gtypes.GenerateContentConfig(
        thinking_config=gtypes.ThinkingConfig(thinking_level="HIGH"),
        **({"temperature": temperature} if temperature is not None else {}),
        **({"system_instruction": system_instruction} if system_instruction else {}),
    )
    if use_google_search:
        config.tools = [gtypes.Tool(google_search=gtypes.GoogleSearch())]

    # Build content parts
    parts: list[Any] = []

    if pdf_paths:
        for pdf_path in pdf_paths:
            if not pdf_path.exists():
                raise FileNotFoundError(
                    f"Injected PDF not found: {pdf_path}. "
                    "Aborting — run cannot proceed without required papers."
                )
            try:
                uploaded = await asyncio.to_thread(
                    client.files.upload,
                    file=str(pdf_path),
                    config={"mime_type": "application/pdf"},
                )
                parts.append(uploaded)
            except Exception as pdf_exc:
                raise RuntimeError(
                    f"PDF upload failed for {pdf_path.name}: {pdf_exc}. "
                    "Aborting — run cannot proceed without required papers."
                ) from pdf_exc

    parts.append(prompt)
    contents = gtypes.Content(role="user", parts=[gtypes.Part(text=p) if isinstance(p, str) else gtypes.Part(file_data=gtypes.FileData(file_uri=p.uri, mime_type="application/pdf")) for p in parts])

    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=contents,
                config=config,
            ),
            timeout=600.0,  # 10 min hard cap per call (large PDF contexts)
        )

    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                t0 = time.time()
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_MODEL,
                    fallback_models=GEMINI_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context=f"call_gemini agent={agent}",
                )
                elapsed_ms = int((time.time() - t0) * 1000)

            output_text = response.text or ""
            meta = response.usage_metadata
            tokens_in    = getattr(meta, "prompt_token_count",    0) or 0
            tokens_out   = getattr(meta, "candidates_token_count", 0) or 0
            tokens_think = getattr(meta, "thoughts_token_count",   0) or 0

            call = AgentCall(
                call_id=call_id,
                run_id=run_id,
                notebook_id=notebook_id,
                agent=agent,
                inputs=inputs,
                output=output_text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_think=tokens_think,
                duration_ms=elapsed_ms,
            )
            if store is not None:
                store.record_agent_call(call)
            return call

        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
            continue

    raise RuntimeError(f"Gemini call failed after 3 attempts: {last_exc}") from last_exc


async def flash_extract_proof(solver_output: str) -> str | None:
    """
    Fallback proof extractor: ask Flash to isolate the final clean proof
    from a solver output that lacks the PROOF_START sentinel.
    Returns the proof text, or None if extraction fails.
    """
    client = _get_client()
    prompt = (
        "The text below is a math solver's output structured in three parts: "
        "a process log, a synthesis summary, and a final clean proof. "
        "Extract ONLY the final clean proof section (Part 3). "
        "Return a JSON object with a single string field 'proof' containing the proof text verbatim. "
        "If no distinct proof section exists, set 'proof' to the empty string.\n\n"
        f"{solver_output}"
    )
    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"proof": {"type": "string"}}, "required": ["proof"]},
        temperature=0.0,
        max_output_tokens=8192,
    )
    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=120.0,
        )

    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_FLASH_MODEL,
                    fallback_models=GEMINI_FLASH_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context="flash_extract_proof",
                )
            import json as _json
            data = _json.loads(response.text or "{}")
            proof = data.get("proof", "").strip()
            return proof if proof else None
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    logger.error(
        "flash_extract_proof failed after 3 attempts (model=%s): %s. "
        "Falling back to None — caller will use full solver output.",
        GEMINI_FLASH_MODEL, last_exc,
    )
    return None  # extraction failed — caller will use full output


async def flash_tag_conjectures(extractor_output: str) -> str:
    """
    Post-processing pass: ask Flash to locate the conjectures, their negations,
    and the proof block inside a free-form extractor output, and re-emit them
    with unambiguous XML tags. Returns the tagged string; on failure returns
    the original text unchanged (caller falls back to empty parse).
    """
    client = _get_client()
    prompt = (
        "The text below is the output of a mathematical conjecture extractor. "
        "Your only job is to find and re-emit specific sections using XML tags. "
        "Do not paraphrase, summarise, or add any content.\n\n"
        "Rules:\n"
        "1. Find every conjecture statement (self-contained mathematical claims). "
        "Wrap each one as <conjecture_N>...</conjecture_N> where N=1,2,...\n"
        "2. Find the negation of each conjecture. "
        "Wrap each as <negation_N>...</negation_N> matching the same N.\n"
        "3. Find the full proof block (the rigorous proof that assumes the conjectures). "
        "Wrap it as <proof>...</proof>.\n"
        "4. Output ONLY the tagged sections, nothing else.\n\n"
        f"{extractor_output}"
    )
    _config = gtypes.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=8192,
    )

    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=_config,
            ),
            timeout=120.0,
        )

    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_FLASH_MODEL,
                    fallback_models=GEMINI_FLASH_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context="flash_tag_conjectures",
                )
            return response.text or extractor_output
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    logger.error(
        "flash_tag_conjectures failed after 3 attempts (model=%s): %s. "
        "Falling back to original extractor output — downstream parse will be empty.",
        GEMINI_FLASH_MODEL, last_exc,
    )
    return extractor_output  # fallback: return original, parser will return empty


async def flash_extract_score(grader_output: str) -> float:
    """
    Fallback score extractor: call Gemini Flash with JSON structured output
    to pull the numeric score out of a grader response that lacks the SCORE: line.
    Returns the score as a float, or raises RuntimeError if extraction fails.
    """
    client = _get_client()
    prompt = (
        "Extract the final numeric score from the grader report below. "
        "The score is out of 7. Return ONLY a JSON object with a single integer field 'score'.\n\n"
        f"{grader_output[-3000:]}"  # tail is sufficient — grade is always near the end
    )
    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]},
        temperature=0.0,
        max_output_tokens=32,
    )
    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=120.0,
        )

    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_FLASH_MODEL,
                    fallback_models=GEMINI_FLASH_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context="flash_extract_score",
                )
            import json
            data = json.loads(response.text or "{}")
            if "score" in data:
                return float(data["score"])
            raise ValueError(f"No 'score' key in Flash response: {response.text!r}")
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    logger.error(
        "flash_extract_score failed after 3 attempts (model=%s): %s. Raising.",
        GEMINI_FLASH_MODEL, last_exc,
    )
    raise RuntimeError(f"Flash score extraction failed after 3 attempts: {last_exc}") from last_exc


async def flash_extract_critique(grader_output: str) -> str | None:
    """Tier-2 fallback for stripping a grader/aggregator output to its
    actionable critique (Areas for Improvement, Scaffolding Questions,
    or equivalent flaw lists). Drops praise (Strengths), Council
    deliberation, "Coroner's Report" / "Summary" paragraphs, and the
    "SCORE: N/7" line. Returns None on extraction failure — caller
    falls through to the full-text safety net.

    Used by grader.py:_extract_critique_only and orchestrator.py:
    _extract_grader_critique when the Tier-1 regex (which targets
    bold-header "**Areas for Improvement:**" / "**Scaffolding
    Questions:**" sections) misses — most commonly on aggregator
    output, which uses a different schema (numbered flaws + Summary
    + SCORE) and lacks the Areas/Scaffolding headers entirely.
    """
    client = _get_client()
    prompt = (
        "The text below is a math grader's output, which mixes praise, "
        "Council deliberation, a numerical grade, and actionable critique. "
        "Extract ONLY the actionable critique: specific flaws in the proof, "
        "areas for improvement, scaffolding questions, or numbered lists "
        "of mistakes/slips/fallacies. EXCLUDE: praise (Strengths), Council "
        "deliberation prose (any reasoning ABOUT the grading process), "
        "Coroner's Report or Summary paragraphs that describe the grade, "
        "and the literal 'SCORE: N/7' line. Return a JSON object with "
        "a single string field 'critique' containing the verbatim "
        "extracted text (preserve original wording and formatting). "
        "If no actionable critique exists, set 'critique' to the empty "
        "string.\n\n"
        f"{grader_output}"
    )
    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"critique": {"type": "string"}}, "required": ["critique"]},
        temperature=0.0,
        max_output_tokens=8192,
    )
    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=120.0,
        )

    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_FLASH_MODEL,
                    fallback_models=GEMINI_FLASH_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context="flash_extract_critique",
                )
            import json as _json
            data = _json.loads(response.text or "{}")
            # Return the literal string (may be empty). An empty string
            # is a VALID response from Flash meaning "no actionable
            # critique in this grader output" — typically when the
            # aggregator praised the proof as having no errors. The
            # caller should TRUST this empty return; falling back to
            # full text in that case leaks the praise prose downstream.
            # None is reserved for actual call failure (after retries).
            return data.get("critique", "").strip()
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    logger.error(
        "flash_extract_critique failed after 3 attempts (model=%s): %s. "
        "Falling back to None — caller will use full grader output.",
        GEMINI_FLASH_MODEL, last_exc,
    )
    return None


async def flash_extract_part2(agent_output: str) -> str | None:
    """Tier-2 fallback for stripping the Part 1 'Grading Log' / Council
    deliberation prefix from an agent's output (extractor, aggregator),
    returning Part 2 onward (the substantive deliverable: conjectures,
    proof, structured output). Returns None on extraction failure —
    caller falls through to the full-text safety net.

    Used by extractor.py:_strip_part1 when the Tier-1 marker scan
    (`**Part 2`, `Part 2:`, etc.) misses because the model wrote the
    section header in a non-standard way.
    """
    client = _get_client()
    prompt = (
        "The text below is an agent's output structured in two parts: "
        "a Part 1 'Grading Log' or 'Council deliberation' describing the "
        "agent's internal reasoning, followed by a Part 2 with the final "
        "structured deliverable (conjectures, proof, judgement, etc.). "
        "Extract ONLY Part 2 — the final structured deliverable, verbatim. "
        "EXCLUDE: any Council/Forum prose, reasoning rounds, Haiku "
        "summaries, persona deliberation, or critique of the inputs. "
        "Return a JSON object with a single string field 'part2' "
        "containing the verbatim Part 2 text. If no distinct Part 2 "
        "deliverable exists, set 'part2' to the empty string.\n\n"
        f"{agent_output}"
    )
    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"part2": {"type": "string"}}, "required": ["part2"]},
        temperature=0.0,
        max_output_tokens=16384,
    )
    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=120.0,
        )

    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_FLASH_MODEL,
                    fallback_models=GEMINI_FLASH_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context="flash_extract_part2",
                )
            import json as _json
            data = _json.loads(response.text or "{}")
            part2 = data.get("part2", "").strip()
            return part2 if part2 else None
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    logger.error(
        "flash_extract_part2 failed after 3 attempts (model=%s): %s. "
        "Falling back to None — caller will use full agent output.",
        GEMINI_FLASH_MODEL, last_exc,
    )
    return None


async def flash_classify_proof_verdict(proof_text: str) -> str:
    """
    Classify a proof's actual conclusion as PROVED / DISPROVED / UNCLEAR,
    independent of what the author was asked to do. Used by the supervisor
    to derive a conjecture's verdict from the child run's best proof —
    sometimes a child asked to prove a statement instead disproves it
    (or vice versa).

    Returns one of: "PROVED", "DISPROVED", "UNCLEAR".
    On all retries failing, returns "UNCLEAR" so the supervisor can
    fall back to "conjecture remains open" without crashing.
    """
    client = _get_client()
    prompt = (
        "You are classifying the conclusion of a mathematical proof attempt.\n\n"
        "Below is the final portion of a proof. The author was asked to "
        "either prove or disprove a specific statement. Determine what "
        "the proof's conclusion actually establishes — which may differ "
        "from what the author was asked to do (e.g., asked to prove, but "
        "ended up showing the statement is false).\n\n"
        "Output EXACTLY one of these three tokens, with no other text, "
        "no quotes, no punctuation:\n"
        "  PROVED    — the proof's final conclusion affirms the problem statement\n"
        "  DISPROVED — the proof's final conclusion refutes the problem statement\n"
        "              (e.g., provides a counterexample, derives a contradiction\n"
        "              from the statement, or explicitly states the statement is false)\n"
        "  UNCLEAR   — the conclusion is ambiguous, partial, halts at a gap, or\n"
        "              the proof terminates without resolving the statement\n"
        "              either way\n\n"
        "---\n"
        "Proof excerpt (final portion):\n\n"
        f"{proof_text[-2000:]}\n"
        "---\n\n"
        "Output (one token only, PROVED / DISPROVED / UNCLEAR):"
    )
    config = gtypes.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=8,
    )
    async def _do_call(model_name: str):
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=120.0,
        )

    backoff = 2.0
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await _call_with_model_fallback(
                    configured_model=GEMINI_FLASH_MODEL,
                    fallback_models=GEMINI_FLASH_FALLBACK_MODELS,
                    make_call=_do_call,
                    log_context="flash_classify_proof_verdict",
                )
            token = (response.text or "").strip().upper()
            for valid in ("PROVED", "DISPROVED", "UNCLEAR"):
                if valid in token:
                    return valid
            # Unknown token — treat as UNCLEAR
            return "UNCLEAR"
        except Exception:
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    return "UNCLEAR"
