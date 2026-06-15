"""verifier_v2 — Improved verifier pipeline for Moonshot harness."""
from .chunker import split_into_chunks, build_dependency_graph
from .prechecker import run_prechecker
from .scorer import run_verify, ACCEPT_THRESHOLD
from .gap_classifier import record_major_gap, get_failed_approaches
from .memory import LemmaDB, CitationDB, FailedGapDB
from .patcher import patch_minor_gaps
from .pipeline import finalize

__all__ = [
    "split_into_chunks", "build_dependency_graph",
    "run_prechecker",
    "run_verify", "ACCEPT_THRESHOLD",
    "record_major_gap", "get_failed_approaches",
    "LemmaDB", "CitationDB", "FailedGapDB",
    "patch_minor_gaps",
    "finalize",
]
