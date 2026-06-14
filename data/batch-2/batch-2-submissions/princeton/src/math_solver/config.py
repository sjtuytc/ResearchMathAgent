"""Runtime configuration — override via environment variables."""
import os
from pathlib import Path

GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")
GEMINI_FLASH_MODEL: str = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.1-flash-lite")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

# Fallback chains for model-deprecation resilience (FirstProof 2026-05-27).
# When the primary model returns 404 / NOT_FOUND / "is no longer available",
# call_gemini walks the fallback list and caches the first model that works.
# Lists are comma-separated env-var overrides; ordering is best-first.
# Pro fallback: gemini-3-pro-preview (current GA-ish preview). Flash fallback:
# gemini-2.5-flash-lite (older but stable, schema-compliant JSON output).
GEMINI_FALLBACK_MODELS: tuple[str, ...] = tuple(
    m.strip() for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS", "gemini-3-pro-preview"
    ).split(",") if m.strip()
)
GEMINI_FLASH_FALLBACK_MODELS: tuple[str, ...] = tuple(
    m.strip() for m in os.environ.get(
        "GEMINI_FLASH_FALLBACK_MODELS", "gemini-2.5-flash-lite"
    ).split(",") if m.strip()
)

RUNS_DIR: Path = Path(os.environ.get("RUNS_DIR", Path(__file__).parents[3] / "runs"))

# Core loop knobs
WIDTH: int = int(os.environ.get("WIDTH", "3"))          # W parallel solvers per stage
DEPTH: int = int(os.environ.get("DEPTH", "10"))         # D max stages (sanity ceiling)
PREV_CTX_SIZE: int = int(os.environ.get("PREV_CTX_SIZE", "3"))  # max prev-stage outputs per solver
CONJECTURE_ROUNDS: int = int(os.environ.get("CONJECTURE_ROUNDS", "2"))   # R rounds per conjecture stage

# Search
ARXIV_MAX_RESULTS: int = int(os.environ.get("ARXIV_MAX_RESULTS", "20"))
MAX_KEEP_PAPERS: int = int(os.environ.get("MAX_KEEP_PAPERS", "5"))
MAX_TRIAGE_REFUSALS: int = int(os.environ.get("MAX_TRIAGE_REFUSALS", "2"))
MIN_FREE_DISK_GB: float = float(os.environ.get("MIN_FREE_DISK_GB", "5.0"))

# Gemini generation
TEMPERATURE: float = float(os.environ.get("TEMPERATURE", "1.0"))
SOLVER_TEMPERATURE: float = float(os.environ.get("SOLVER_TEMPERATURE", "1.0"))
MAX_OUTPUT_TOKENS: int = int(os.environ.get("MAX_OUTPUT_TOKENS", "65536"))
