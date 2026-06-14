"""Core data models."""
from __future__ import annotations

import re
import time
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


def extract_notebook_sections(content: str, section_names: list[str]) -> str:
    """Extract one or more `## HEADER` sections from notebook content,
    keeping each header line and its body until the next `## ` header or EOF.
    Returns the concatenation of all matched sections joined by blank lines,
    or the empty string if none matched. Header matching is case-insensitive
    and trims trailing punctuation; missing sections are silently skipped.

    Used by RunState.vetted_facts_text() to pull only VERIFIED FACTS and
    STANDARD NAMED THEOREMS out of the notebook for the grader, excluding
    OCs, IPTs, PSes, RHs, and prose.
    """
    if not content.strip():
        return ""
    wanted = {name.strip().upper() for name in section_names}
    # Match a `## HEADER` line; capture the header text and the body up to the
    # next `## ` line at the start of a line, or end-of-string.
    pattern = re.compile(
        r"^##\s+([^\n]+?)\s*\n(.*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    out: list[str] = []
    for m in pattern.finditer(content):
        header = re.sub(r"[^\w\s]", "", m.group(1)).strip().upper()
        if header in wanted:
            section_text = f"## {m.group(1).strip()}\n{m.group(2).rstrip()}"
            out.append(section_text)
    return "\n\n".join(out)


class RunStatus(str, Enum):
    INIT = "INIT"
    SOLVING = "SOLVING"
    DONE = "DONE"
    FAILED = "FAILED"
    PAUSED_FOR_CHILD = "PAUSED_FOR_CHILD"   # extractor yielded 1 conjecture; supervisor spawned


class SearchMode(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class NotebookMode(str, Enum):
    UPDATE = "UPDATE"
    AUDIT = "AUDIT"


class EpistemicLevel(str, Enum):
    SUPPORTED = "SUPPORTED"     # highest level: grader ≥6/7 on three separate attempts
    SPECULATIVE = "SPECULATIVE"
    DISCARDED = "DISCARDED"


class Paper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    date: str               # YYYY-MM-DD
    abstract: str
    primary_category: str
    pdf_path: str | None = None
    fetched_at: float | None = None

    @property
    def citation_key(self) -> str:
        return f"arxiv:{self.arxiv_id}"


class SearchQuery(BaseModel):
    purpose: str
    arxiv_query: str
    web_query: str
    recency_hint: str           # "recent" | "any" | "unknown"
    expected_artifact: str      # "paper" | "survey" | "lecture notes" | ...
    source_gap: str = ""        # which Active Paper Question triggered this


class TriageResult(BaseModel):
    arxiv_id: str
    decision: str               # "KEEP" | "DROP"
    reason: str
    rank: int | None = None     # rank among KEEPs (1 = most promising)


class TriageOutput(BaseModel):
    shortlist: list[TriageResult]
    no_relevant: bool = False
    no_relevant_reason: str = ""


class GraderResult(BaseModel):
    solver_index: int
    score: float                # 0–7 analog or 0–1 normalized
    feedback: str
    is_complete: bool = False
    raw: str = ""
    # Verbatim "**Overall Strategy:**" block extracted from the grader's
    # report (cut-and-paste, typically 3-6 sentences). Used by the
    # conjecture adjudicator to annotate PROVED / DISPROVED status.
    # Empty if the block was absent (e.g. aggregator output, which
    # doesn't produce a strategy block).
    summary: str = ""


class BSDetectorResult(BaseModel):
    solver_index: int
    feedback: str
    raw: str = ""


class ConjectureResolution(BaseModel):
    """Bookkeeping record for how a conjecture was resolved (PROVED / DISPROVED).

    Populated by the adjudicator when a Mode-A child run produces an all-draws-7/7
    + bs_clean confirmation on either the conjecture's statement (PROVED) or its
    negation (DISPROVED).
    """
    solver_index: int
    stage: int
    run_id: str                 # the child run that produced the confirming proof
    target: str                 # "statement" or "negation"
    summary: str                # Overall Strategy block, verbatim from highest-scoring grader


class Conjecture(BaseModel):
    id: str                     # e.g. "C1", "C2"
    statement: str
    negation: str
    bisection_sufficient: bool  # BISECTION SUFFICIENT flag from extractor
    needs_child_notebook: bool
    status: str = "OPEN"        # OPEN | DISPROVED | PROVED | ABANDONED
    resolution: ConjectureResolution | None = None


class ConjectureExtractOutput(BaseModel):
    conjectures: list[Conjecture]
    synthesized_partial_proof: str = ""
    raw: str = ""


class NotebookOutput(BaseModel):
    content: str                # full notebook text (both levels)
    next_priority: str
    active_paper_questions: list[str]
    search_queries: list[SearchQuery]
    level1_summary: str = ""    # extracted Level 1 for solver input


class SolutionRecord(BaseModel):
    stage: int
    solver_index: int
    score: float
    output: str
    grader_feedback: str
    # Dual-gate BS verdict, recorded only for solutions that went through the
    # extended-grading exit gauntlet (verify_solution / bs_and_grade_ensemble).
    # None means "not evaluated" (e.g. low-score solvers that never triggered
    # the gauntlet); True means BS aggregator reported no surviving gaps;
    # False means BS aggregator flagged gaps. Used by top_solutions() to break
    # ties / preference BS-clean proofs of equal grader score. Backward-compat:
    # old run.db rows lack this field; Pydantic defaults to None on load.
    bs_clean: bool | None = None
    # "parent" = solver attempt on the parent problem (the run's headline target).
    # "conjecture" = solver attempt fired inside _run_conjecture_stage on an
    # extracted conjecture (prove or disprove). top_solutions() filters to
    # "parent" so a high-scoring conjecture proof does not surface as the
    # run's top solution. Backward-compat: old run.db rows default to "parent".
    stage_type: str = "parent"
    # Cross-model second opinion: populated when the OpenAI gate fires
    # on this proof. `openai_score` is gpt-5.5-pro's gauntlet-style 0-7
    # rating; `openai_feedback` is its critique (already stripped to
    # Areas for Improvement + Scaffolding Questions via the 3-tier
    # _extract_critique_only). Both None when the gate didn't fire (or
    # the call errored). Grader 3 reads both when composing its
    # critique-informed `gap_report.txt`. Backward-compat: old run.db
    # rows default to None.
    openai_score: float | None = None
    openai_feedback: str | None = None


class AgentCall(BaseModel):
    call_id: str
    run_id: str
    notebook_id: str
    agent: str
    inputs: dict[str, Any]
    output: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_think: int = 0
    duration_ms: int = 0
    created_at: float = Field(default_factory=time.time)


class TelemetryEvent(BaseModel):
    run_id: str
    event: str
    data: dict[str, Any]
    ts: float = Field(default_factory=time.time)


class NotebookState(BaseModel):
    notebook_id: str
    parent_id: str | None
    depth: int = 0
    content: str = ""
    round: int = 0
    best_score: float = 0.0
    consecutive_no_progress: int = 0
    conjectures: list[Conjecture] = Field(default_factory=list)
    paper_library: list[str] = Field(default_factory=list)   # citation keys
    exhausted_search_gaps: list[str] = Field(default_factory=list)
    status: str = "ACTIVE"      # ACTIVE | DONE | ABANDONED


class RunState(BaseModel):
    run_id: str
    problem: str
    status: RunStatus = RunStatus.INIT
    root_notebook: NotebookState | None = None
    notebooks: dict[str, NotebookState] = Field(default_factory=dict)
    papers: dict[str, Paper] = Field(default_factory=dict)
    all_solutions: list[SolutionRecord] = Field(default_factory=list)
    total_rounds: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def top_solutions(self, n: int = 2) -> list[SolutionRecord]:
        """Return the highest-scoring solution(s). Returns two if there is a tie at the top.

        Ranking key (descending): (score, bs_clean is True). On equal grader
        score, a dual-gate-confirmed solution (bs_clean=True) ranks above one
        with BS-flagged gaps (bs_clean=False) and above one that was never
        gauntletted (bs_clean=None). This prevents the operator-facing
        top_solution_1.txt from promoting a 7/7 proof that the BS detector
        flagged — observed on run 91c86086f126 (IMO 2024 P6, 2026-05-22)
        where Solver 2 (7/7, BS open) ranked above Solver 3 (7/7, BS clean).
        """
        if not self.all_solutions:
            return []
        # Sort key prefers (a) higher score, then (b) bs_clean True over False/None.
        # bool comparison: True > False; None falls into the "unknown" bucket
        # treated as False here so confirmed solutions beat unevaluated ones.
        # Only parent-problem proofs are eligible to surface as the run's top
        # solution. Conjecture-stage proofs (stage_type == "conjecture") are
        # graded against a sub-claim, not the parent, so they would mislead the
        # operator if ranked here. Filter first, then apply the dual-gate key.
        parent_only = [s for s in self.all_solutions if s.stage_type == "parent"]
        if not parent_only:
            return []
        # Ranking (2026-05-28 PM): strict BS-clean + sum-of-two-graders.
        #   1. Hard filter: bs_clean is True. BS-flagged candidates never
        #      ship, regardless of how high they scored.
        #   2. Among BS-clean candidates with BOTH a gauntlet score and an
        #      openai_score (i.e. rec.openai_score is not None), sort
        #      descending by total = score + openai_score. The orchestrator
        #      no longer demotes rec.score to min() on OAI-disagreement,
        #      so rec.score is the raw gauntlet aggregator score and the
        #      sum is well-defined.
        #   3. BS-clean candidates that lack an openai_score are excluded
        #      from the shipping pool entirely (Sanjeev's "1(b)" rule):
        #      the caller is expected to prefetch OAI scores on every
        #      BS-clean parent (batch.py:_prefetch_oai_for_bs_clean)
        #      before invoking top_solutions, so this exclusion bites
        #      only on transient failures or runs where OAI is fully
        #      unavailable.
        #   4. Empty pool fallback: if NO BS-clean candidate has an
        #      openai_score, fall back to the prior (bs_clean, score)
        #      ranking on the full parent_only list so the run still
        #      ships something rather than the unsolved-fallback document.
        eligible = [s for s in parent_only
                    if s.bs_clean is True and s.openai_score is not None]
        if eligible:
            def _sum_key(s: SolutionRecord) -> float:
                return s.score + (s.openai_score or 0.0)
            ranked = sorted(eligible, key=_sum_key, reverse=True)
            top_total = _sum_key(ranked[0])
            tied = [s for s in ranked if _sum_key(s) == top_total]
            return tied[:n] if len(tied) > 1 else ranked[:1]

        # Fallback when no BS-clean parent has been OAI-graded.
        def _fallback_key(s: SolutionRecord) -> tuple:
            return (s.bs_clean is True, s.score)
        ranked = sorted(parent_only, key=_fallback_key, reverse=True)
        top_key = _fallback_key(ranked[0])
        tied = [s for s in ranked if _fallback_key(s) == top_key]
        return tied[:n] if len(tied) > 1 else ranked[:1]

    def get_notebook(self, nid: str) -> NotebookState:
        if nid == "ROOT":
            assert self.root_notebook is not None
            return self.root_notebook
        return self.notebooks[nid]

    def paper_library_text(self, notebook: NotebookState) -> str:
        lines = []
        for key in notebook.paper_library:
            p = self.papers.get(key.replace("arxiv:", ""))
            if p:
                lines.append(
                    f"[{p.citation_key}] {p.title} — {', '.join(p.authors[:3])} ({p.date})\n"
                    f"  Abstract: {p.abstract[:300]}..."
                )
        return "\n\n".join(lines) if lines else "(empty)"

    def references_text(self, notebook: NotebookState) -> str:
        # Working-context block (BS detector channel): full notebook content
        # plus paper-library citations. The BS detector needs to see the
        # entire working state — OCs, IPTs, prose — to identify where a
        # solver's claim is leaning on internal hypothesis vs. external fact.
        # The grader uses vetted_facts_text() instead.
        nb_text = notebook.content.strip() or "(empty)"
        papers_text = self.paper_library_text(notebook)
        return (
            f"=== Notebook ===\n{nb_text}\n\n"
            f"=== Paper Library ===\n{papers_text}"
        )

    def vetted_facts_text(
        self,
        notebook: NotebookState,
        additional_materials: str = "",
    ) -> str:
        """Vetted-facts channel for the grader. Includes ONLY externally-vetted
        content the grader is licensed to treat as authoritative:

          - VERIFIED FACTS section from the notebook (immutable, VF promotion
            requires external evidence + two independent runs per
            docs/vf_promotion_design.md)
          - STANDARD NAMED THEOREMS section from the notebook (named results
            from established literature)
          - Paper-library bibliographic metadata (title / authors / abstract)
          - Caller-supplied summarized references (passed via
            --additional-materials — typically the compact .md summaries
            produced by the literature_summarizer)

        Pointedly EXCLUDED: Open Conjectures (even CLOSED-pending-vetting),
        Research Hypotheses, Proof Skeletons, Ideas Previously Tried, and
        narrative prose. These are pipeline-internal working state and the
        grader must not treat them as authoritative — doing so produced the
        Q7 C2 contamination on run 9d66f0e53f8d (2026-05-24).
        """
        vetted_sections = extract_notebook_sections(
            notebook.content,
            ["VERIFIED FACTS", "STANDARD NAMED THEOREMS"],
        )
        papers_text = self.paper_library_text(notebook)
        parts: list[str] = [
            f"=== Vetted Facts (from notebook) ===\n{vetted_sections or '(none)'}",
            f"=== Paper Library ===\n{papers_text}",
        ]
        am = (additional_materials or "").strip()
        if am and am != "(none)":
            parts.append(f"=== Summarized References ===\n{am}")
        return "\n\n".join(parts)
