"""Hero inference — assembles maximum-context prompt for a single high-quality solve pass.

Design philosophy: the context window is the product.  Every token of budget should be
filled with the most decision-relevant information, ordered so that the model sees the
most important facts first (problem, curated prefix, best proof, P0/P1 issues, documents,
literature, history).

Context section ordering (model sees top → bottom):
  0  system      — hero agent instruction
  1  problem     — problem.tex statement
  2  prefix      — curated background: theorems, definitions, strategies
  3  proof       — current best proof (working_solution.tex)
  4  issues      — open P0/P1 issues with full bodies
  5  documents   — analysis.md, strategies.md, progress.md
  6  literature  — relevant paper excerpts from literature index
  7  history     — recent agent comments summary
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Iterator

# Token estimate: 1 token ≈ 4 chars (rough but consistent)
def _tok(text: str) -> int:
    return max(1, len(text) // 4)

# Colors for the context diagram (hex)
SECTION_COLORS = {
    "system":     "#58a6ff",   # blue  — instruction
    "problem":    "#a371f7",   # purple — problem statement
    "prefix":     "#3fb950",   # green  — curated background
    "proof":      "#f0883e",   # orange — best proof
    "issues":     "#f85149",   # red    — open P0/P1 issues
    "documents":  "#e3a00a",   # amber  — research docs
    "literature": "#6e7cd6",   # indigo — paper excerpts
    "history":    "#6e7681",   # gray   — agent history
}

SECTION_LABELS = {
    "system":     "System Instruction",
    "problem":    "Problem Statement",
    "prefix":     "Background Prefix",
    "proof":      "Best Proof",
    "issues":     "Open Issues (P0/P1)",
    "documents":  "Research Documents",
    "literature": "Literature Excerpts",
    "history":    "Agent History",
}

_HERO_SYSTEM = textwrap.dedent("""\
    You are a mathematical hero agent for the First Proof benchmark.
    Your task: produce a complete, rigorous, publishable proof of the given problem.

    You have access to the best current proof attempt, curated background context,
    open mathematical issues, research documents, and relevant literature.

    Instructions:
    1. Read the problem statement carefully.
    2. Study the background prefix — it contains key theorems and definitions.
    3. Read the current best proof and identify its weaknesses.
    4. Address every open P0/P1 issue explicitly in your new proof.
    5. Write the complete improved proof to solution.tex.
    6. The proof must be LaTeX-formatted, self-contained, and mathematically rigorous.
    7. Every claim must be justified. No hand-waving.

    Context budget usage is shown in the context diagram.
    Prioritize fixing the highest-priority issues first.
""")


def assemble_context(
    repo_root: Path,
    problem_id: str,
    dataset: str = "first_proof_1",
    max_tokens: int = 180_000,
    enabled_sections: list[str] | None = None,
) -> list[dict]:
    """
    Assemble context sections for a hero inference run.
    Returns ordered list of section dicts, each with:
      id, name, content, tokens, enabled, color, order, truncated
    """
    from .prefix import build_prefix_md
    from .issues import list_issues, PRIORITY_LEVELS
    from .issue_agents import get_working_proof
    from .literature import load_index as lit_load
    from .documents import read_document

    if enabled_sections is None:
        enabled_sections = list(SECTION_LABELS.keys())

    sections = []

    # ── 0: system ────────────────────────────────────────────────────────────
    sections.append({
        "id": "system",
        "name": SECTION_LABELS["system"],
        "content": _HERO_SYSTEM,
        "enabled": "system" in enabled_sections,
        "color": SECTION_COLORS["system"],
        "order": 0,
    })

    # ── 1: problem statement ─────────────────────────────────────────────────
    prob_path = repo_root / "problems" / f"{problem_id}.tex"
    pre_path  = repo_root / "problems" / "preamble.tex"
    prob_text = ""
    if prob_path.is_file():
        prob_text = prob_path.read_text(encoding="utf-8", errors="replace")
    if pre_path.is_file():
        prob_text = pre_path.read_text(encoding="utf-8", errors="replace") + "\n\n" + prob_text
    sections.append({
        "id": "problem",
        "name": SECTION_LABELS["problem"],
        "content": prob_text.strip(),
        "enabled": "problem" in enabled_sections,
        "color": SECTION_COLORS["problem"],
        "order": 1,
    })

    # ── 2: prefix ────────────────────────────────────────────────────────────
    pfx = build_prefix_md(repo_root, problem_id)
    sections.append({
        "id": "prefix",
        "name": SECTION_LABELS["prefix"],
        "content": pfx or "(no prefix entries — add background context in the Documents → Prefix tab)",
        "enabled": "prefix" in enabled_sections,
        "color": SECTION_COLORS["prefix"],
        "order": 2,
    })

    # ── 3: best proof ─────────────────────────────────────────────────────────
    proof = get_working_proof(repo_root, problem_id) or ""
    if not proof:
        # fall back to best/ directory
        from .proofs import get_best_proof
        best = get_best_proof(problem_id)
        if best:
            proof_path = repo_root / "webapp" / "best" / problem_id / "proof.tex"
            if proof_path.is_file():
                proof = proof_path.read_text(encoding="utf-8", errors="replace")
    sections.append({
        "id": "proof",
        "name": SECTION_LABELS["proof"],
        "content": proof.strip() or "(no proof attempt yet)",
        "enabled": "proof" in enabled_sections,
        "color": SECTION_COLORS["proof"],
        "order": 3,
    })

    # ── 4: open issues P0/P1 ─────────────────────────────────────────────────
    issues = list_issues(repo_root, problem_id, dataset)
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    top_issues = sorted(
        [i for i in issues if i.get("status") != "resolved"
         and i.get("priority", "P2") in ("P0", "P1", "P2")],
        key=lambda i: (priority_order.get(i.get("priority", "P2"), 2), i.get("created_at", "")),
    )
    issue_parts = []
    for iss in top_issues[:20]:
        body = ""
        for c in iss.get("comments", []):
            if c.get("role") not in ("event",) and c.get("body", "").strip():
                body = c["body"].strip()
                break
        prio  = iss.get("priority", "P2")
        itype = iss.get("issue_type", "")
        issue_parts.append(
            f"### [{prio}] {iss['title']}"
            + (f" [{itype}]" if itype else "")
            + f"\n{body}"
        )
    issues_text = "\n\n".join(issue_parts) or "(no open issues)"
    sections.append({
        "id": "issues",
        "name": SECTION_LABELS["issues"],
        "content": issues_text,
        "enabled": "issues" in enabled_sections,
        "color": SECTION_COLORS["issues"],
        "order": 4,
    })

    # ── 5: research documents ─────────────────────────────────────────────────
    q_docs_dir = repo_root / "documents" / "questions" / problem_id
    doc_parts = []
    for fname in ("analysis.md", "strategies.md", "progress.md", "overview.md"):
        doc_path = q_docs_dir / fname if q_docs_dir.is_dir() else None
        if doc_path and doc_path.is_file():
            txt = doc_path.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                doc_parts.append(f"## {fname}\n\n{txt}")
    docs_text = "\n\n---\n\n".join(doc_parts) or "(no research documents yet)"
    sections.append({
        "id": "documents",
        "name": SECTION_LABELS["documents"],
        "content": docs_text,
        "enabled": "documents" in enabled_sections,
        "color": SECTION_COLORS["documents"],
        "order": 5,
    })

    # ── 6: literature excerpts ────────────────────────────────────────────────
    papers = lit_load(repo_root, problem_id)
    lit_parts = []
    for p in papers[:10]:
        title  = p.get("title", "Unknown")
        notes  = p.get("notes", "").strip()
        abstract = p.get("abstract", "").strip()
        if notes or abstract:
            lit_parts.append(f"### {title}\n{notes or abstract}")
    lit_text = "\n\n".join(lit_parts) or "(no literature indexed — use the Literature tab)"
    sections.append({
        "id": "literature",
        "name": SECTION_LABELS["literature"],
        "content": lit_text,
        "enabled": "literature" in enabled_sections,
        "color": SECTION_COLORS["literature"],
        "order": 6,
    })

    # ── 7: agent history ──────────────────────────────────────────────────────
    from .issues import get_activity_log
    activity = get_activity_log(repo_root, problem_id, dataset, limit=50)
    hist_lines = [
        f"[{e.get('timestamp','')[:10]}] {e.get('agent','')} — {e.get('entry','')[:200]}"
        for e in activity if e.get("entry", "").strip()
    ]
    hist_text = "\n".join(hist_lines) or "(no agent history yet)"
    sections.append({
        "id": "history",
        "name": SECTION_LABELS["history"],
        "content": hist_text,
        "enabled": "history" in enabled_sections,
        "color": SECTION_COLORS["history"],
        "order": 7,
    })

    # ── Annotate token counts and truncation ──────────────────────────────────
    total_budget = max_tokens
    used = 0
    for s in sections:
        raw_tok = _tok(s["content"])
        s["tokens_raw"] = raw_tok
        s["tokens"] = raw_tok
        s["truncated"] = False
        if s["enabled"]:
            used += raw_tok

    # If we'd exceed budget, truncate lower-priority sections
    if used > total_budget:
        remaining = total_budget
        for s in sorted(sections, key=lambda x: x["order"]):
            if not s["enabled"]:
                continue
            if remaining <= 0:
                s["content"] = "(truncated — budget exhausted)"
                s["tokens"] = 0
                s["truncated"] = True
            elif s["tokens"] > remaining:
                # truncate content to fit remaining budget
                max_chars = remaining * 4
                s["content"] = s["content"][:max_chars] + "\n\n[… truncated to fit context budget …]"
                s["tokens"] = remaining
                s["truncated"] = True
                remaining = 0
            else:
                remaining -= s["tokens"]

    return sections


def build_hero_prompt(sections: list[dict]) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) from assembled sections."""
    system = ""
    parts = []
    for s in sorted(sections, key=lambda x: x["order"]):
        if not s["enabled"] or not s["content"].strip():
            continue
        if s["id"] == "system":
            system = s["content"]
            continue
        parts.append(f"# {s['name'].upper()}\n\n{s['content']}")
    user = "\n\n" + ("=" * 60) + "\n\n".join(parts)
    user += "\n\n" + ("=" * 60) + "\n\nNow write the complete, rigorous proof. Be mathematically precise."
    return system, user


def context_stats(sections: list[dict], budget: int = 180_000) -> dict:
    """Aggregate stats for the context diagram."""
    enabled = [s for s in sections if s["enabled"]]
    total_tok = sum(s["tokens"] for s in enabled)
    return {
        "total_tokens": total_tok,
        "budget": budget,
        "pct_used": round(total_tok / budget * 100, 1),
        "sections": len(enabled),
        "truncated": any(s["truncated"] for s in enabled),
        "by_section": [
            {"id": s["id"], "name": s["name"], "tokens": s["tokens"],
             "pct": round(s["tokens"] / budget * 100, 1),
             "color": s["color"], "enabled": s["enabled"],
             "truncated": s["truncated"]}
            for s in sorted(sections, key=lambda x: x["order"])
        ],
    }
