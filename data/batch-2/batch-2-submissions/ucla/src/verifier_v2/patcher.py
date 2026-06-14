"""§4: Targeted patching — locate gap, send repair prompt, apply patch."""
from __future__ import annotations
import re
from ._api import call_api

REPAIR_PROMPT = """\
You are fixing a specific gap in a mathematical proof.

# Problem
PROBLEM_PLACEHOLDER

# Accumulated Context (previously established results)
CONTEXT_PLACEHOLDER

# Current Section with Gap
CHUNK_PLACEHOLDER

# Gap to Fix
GAP_PLACEHOLDER

# Instructions
Fix ONLY this specific gap. Do not change the overall proof strategy.
Do not modify other parts of the proof. Make the minimum necessary change to close the gap.
The fix should be self-contained within this section.

Output the corrected section text only (no preamble, no explanation).
"""


def _locate_gap_in_chunk(gap: str, chunks: list[str]) -> int:
    """Find which chunk index most likely contains the gap. Returns -1 if not found."""
    gap_words = gap.lower().split()[:8]
    best_idx = -1
    best_score = 0
    for i, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        score = sum(1 for w in gap_words if w in chunk_lower)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score >= 2 else -1


def _apply_patch(proof: str, old_chunk: str, new_chunk: str) -> str:
    """Replace old_chunk with new_chunk in proof. Falls back to appending if not found."""
    if old_chunk in proof:
        return proof.replace(old_chunk, new_chunk, 1)
    # Fuzzy: find by first 100 chars
    prefix = old_chunk.strip()[:100]
    idx = proof.find(prefix)
    if idx >= 0:
        end_idx = idx + len(old_chunk)
        return proof[:idx] + new_chunk + proof[end_idx:]
    return proof  # can't locate, return unchanged


def patch_minor_gaps(
    proof_text: str,
    chunks: list[str],
    minor_gaps: list[str],
    accumulated_context: str,
    problem: str = "",
    reasoning: str = "high",
    max_attempts: int = 2,
) -> tuple[str, list[tuple[str, str]]]:
    """
    For each minor gap, locate the relevant chunk, send a targeted repair prompt,
    and apply the patch to the proof.

    Returns: (patched_proof, escalated_gaps)
    - patched_proof: the proof with patches applied
    - escalated_gaps: list of (gap, "escalated") for gaps that failed after max_attempts
    """
    current_proof = proof_text
    escalated: list[tuple[str, str]] = []

    for gap in minor_gaps:
        chunk_idx = _locate_gap_in_chunk(gap, chunks)
        if chunk_idx < 0:
            escalated.append((gap, "escalated"))
            continue

        chunk = chunks[chunk_idx]
        patched = False

        for attempt in range(1, max_attempts + 1):
            prompt = (
                REPAIR_PROMPT
                .replace("PROBLEM_PLACEHOLDER", problem or "(problem not provided)")
                .replace("CONTEXT_PLACEHOLDER", accumulated_context or "(no prior context)")
                .replace("CHUNK_PLACEHOLDER", chunk)
                .replace("GAP_PLACEHOLDER", gap)
            )
            fixed_chunk = call_api(
                prompt,
                f"patch_gap_attempt{attempt}",
                reasoning=reasoning,
                max_tokens=32_000,
            )
            if fixed_chunk and fixed_chunk.strip() and fixed_chunk.strip() != chunk.strip():
                current_proof = _apply_patch(current_proof, chunk, fixed_chunk)
                chunks[chunk_idx] = fixed_chunk  # update chunk for future context
                patched = True
                print(f"[patcher] gap patched on attempt {attempt}: {gap[:60]}")
                break

        if not patched:
            escalated.append((gap, "escalated"))
            print(f"[patcher] gap escalated after {max_attempts} attempts: {gap[:60]}")

    return current_proof, escalated
