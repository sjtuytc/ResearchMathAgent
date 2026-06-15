"""Extract a proof-local theorem/lemma inventory from a candidate proof.

Single narrow-task Gemini call: list every `Theorem N` / `Lemma N` /
`Proposition N` / `Corollary N` / `Claim N` block stated in full in the proof,
with the line where each begins.

Why this exists as a separate agent: when the same task is folded into the BS
detector's paranoid Council-of-Interrogators persona, Gemini stops recognizing
proof-local theorem statements and flags them as fabricated (verified
empirically 2026-05-19). The same model asked the same question outside that
persona returns perfect output in ~88 tokens. So we extract the static scan into
a focused agent and feed its result into the BS detector as authoritative
pre-computed inventory.

This lives in the package (imported by ``agents/bs_detector.py``). A thin CLI
wrapper remains at ``scripts/extract_proof_local_inventory.py``.
"""
from __future__ import annotations

import asyncio
import json

from google.genai import types as gtypes

from .config import GEMINI_MODEL
from .gemini import _SEMAPHORE, _get_client

_PROMPT = (
    "Here is a math proof.  List every `Theorem N` / `Lemma N` / `Proposition "
    "N` / `Corollary N` / `Claim N` block that is stated in full in the "
    "proof, with the line number where each begins.  For each block, give "
    "the label (e.g. 'Theorem 1'), the named result if attributed in "
    "parentheses (e.g. 'Bernstein-Zelevinsky Restriction Theorem'), and the "
    "line number.  If no such blocks are present, return an empty list."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "proof_local_labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label":             {"type": "string"},
                    "name":              {"type": "string"},
                    "line_first_stated": {"type": "integer"},
                },
                "required": ["label", "line_first_stated"],
            },
        },
    },
    "required": ["proof_local_labels"],
}


def _numbered(text: str) -> str:
    """Prefix each line with its line number so the model can cite lines."""
    return "\n".join(f"{i:4d}  {line}" for i, line in enumerate(text.splitlines(), 1))


async def extract_proof_local_inventory(proof: str) -> list[dict]:
    """Return a list of `{label, name, line_first_stated}` records."""
    client = _get_client()
    prompt = (
        f"{_PROMPT}\n\n"
        f"**Candidate Proof (with line numbers):**\n\n"
        f"{_numbered(proof)}"
    )
    config = gtypes.GenerateContentConfig(
        max_output_tokens=4096,
        response_mime_type="application/json",
        response_schema=_SCHEMA,
        thinking_config=gtypes.ThinkingConfig(thinking_level="MEDIUM"),
    )
    backoff = 2.0
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _SEMAPHORE:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=GEMINI_MODEL,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=120.0,
                )
            data = json.loads(response.text or "{}")
            return data.get("proof_local_labels", [])
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(backoff)
                backoff *= 2
    raise RuntimeError(
        f"extract_proof_local_inventory failed after 3 attempts: {last_exc}"
    ) from last_exc


def format_inventory_markdown(items: list[dict]) -> str:
    """Render the inventory as a small markdown list for inclusion in a prompt."""
    if not items:
        return "(no proof-local theorem/lemma/proposition blocks detected)"
    lines = []
    for it in items:
        label = it.get("label", "?")
        name = it.get("name", "").strip()
        line = it.get("line_first_stated", "?")
        if name:
            lines.append(f"- **{label}** ({name}) — stated at proof line {line}")
        else:
            lines.append(f"- **{label}** — stated at proof line {line}")
    return "\n".join(lines)
