"""§0: One-time chunk generation. Generate once and reuse throughout the pipeline."""
from __future__ import annotations
import re

SHORT = 120  # chars — segments shorter than this merge into the next


def split_into_chunks(text: str, split: bool = True) -> list[str]:
    """
    Split proof text into structural chunks.

    When split=False (or SPLIT_CHUNKS=false env var), return the full document
    as a single chunk — best for short proofs to avoid cross-chunk false positives.

    When split=True, split at structural LaTeX boundaries:
      \\begin{lemma/theorem/proposition/corollary/claim/proof/remark/definition/example/*}
      \\section, \\subsection, \\subsubsection
    Short consecutive headers (< SHORT chars) merge into the next segment.

    Generate chunks ONCE and reuse the same list throughout pre-checker,
    verifier, and patching stages for consistent boundaries.
    """
    import os
    if not split or os.getenv("SPLIT_CHUNKS", "true").lower() == "false":
        return [text.strip()]
    if len(text) <= 4000:
        return [text.strip()]

    struct_re = re.compile(
        r'(?:^|\n)(?:'
        r'\\(?:section|subsection|subsubsection|chapter)\*?\{[^}]*\}'
        r'|#{1,3} .+'
        r'|\\begin\{(?:lemma|theorem|proposition|corollary|claim|proof|remark|definition|example)\*?\}'
        r'|Lemma \d+|Proposition \d+|Theorem \d+|Proof(?: of)?'
        r')',
        re.MULTILINE,
    )
    boundaries = [m.start() for m in struct_re.finditer(text)]
    if not boundaries:
        return [text.strip()]

    all_bounds = sorted(set([0] + boundaries + [len(text)]))
    segments = [text[all_bounds[i]:all_bounds[i + 1]] for i in range(len(all_bounds) - 1)]
    segments = [s for s in segments if s.strip()]

    merged: list[str] = []
    buf = ""
    for seg in segments:
        if len(seg.strip()) <= SHORT:
            buf += seg
        else:
            if buf:
                merged.append((buf + seg).strip())
                buf = ""
            else:
                merged.append(seg.strip())
    if buf.strip():
        merged.append(buf.strip())

    return merged or [text.strip()]


def build_dependency_graph(chunks: list[str]) -> dict[int, list[int]]:
    """
    Build a dependency graph: chunk_index → [indices of chunks it depends on].
    Currently a placeholder returning an empty graph (no dependencies detected).
    Future: parse \\ref{} and Lemma X.Y patterns to detect cross-chunk deps.
    """
    return {i: [] for i in range(len(chunks))}


def get_accumulated_context(
    chunks: list[str],
    verified_status: dict[int, str],  # {chunk_idx: "verified"|"minor_gap"|"major_gap"|"blocked"}
    current_idx: int,
) -> str:
    """
    Build the "Previously Established Results" context for verifying chunk current_idx.
    Only includes chunks that are "verified" or "minor_gap" (usable).
    Chunks with "major_gap" are omitted entirely.
    Blocked chunks (depend on major-gap chunks) are also omitted.
    """
    lines = []
    for i in range(current_idx):
        status = verified_status.get(i, "unknown")
        if status == "verified":
            tag = "✅ verified"
        elif status == "minor_gap":
            tag = "⚠️ minor gap (usable)"
        else:
            continue  # major_gap or blocked → omit
        # Extract a brief excerpt (first 200 chars) as the "statement"
        excerpt = chunks[i].strip()[:200].replace("\n", " ")
        lines.append(f"- Chunk {i} ({tag}): {excerpt}...")
    if not lines:
        return ""
    return "# Previously Established Results\n" + "\n".join(lines) + "\n\n"
