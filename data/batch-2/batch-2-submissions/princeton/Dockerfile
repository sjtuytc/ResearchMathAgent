# First Proof submission image.
# Runs the full benchmark: one JSON of problems in -> one JSON of LaTeX
# solutions out. Bundles a TeX Live subset so each solution is compile-verified
# (pdflatex) inside the container before it is written to the output JSON.
#
# NOTE (2026-05-28): this root Dockerfile is the one First Proof's run.sh builds
# (`docker build` at the repo root → default ./Dockerfile). It is kept byte-for-
# byte in sync with deploy/Dockerfile, which is the validated AWS image, PLUS the
# WIDTH/DEPTH ENV below. On AWS those two are injected via the Terraform task env
# (variables.tf); First Proof's run only passes secrets via --env-file, so they
# must be baked into the image here or the contest silently runs at 4x4.
# See docs/firstproof_build_audit_2026-05-28.md.
#
# Python 3.12 + pinned deps (deploy/requirements.lock.txt) so the image matches
# the validated local environment exactly — reproducible builds, no version drift.
FROM python:3.12-slim

# TeX Live subset: enough for documentclass{article} + amsmath/amssymb/amsthm/
# mathtools/hyperref, which is all the typesetter is allowed to load.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-science \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pinned dependencies first (cache-friendly + reproducible: this is the
# exact set validated locally). Then install the package itself with --no-deps so
# pip can't pull newer/different transitive versions.
COPY deploy/requirements.lock.txt /app/requirements.lock.txt
RUN pip install --no-cache-dir -r /app/requirements.lock.txt
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir --no-deps .

# scripts/ contains the Grader 3 chain (grader3.py, librarian.py,
# fetch_and_distill.py, verify_pipeline.py) which batch.run_firstproof
# imports on demand to auto-verify each accepted proof. Not part of the
# math_solver package (sibling to src/), so we COPY explicitly and put
# /app/scripts on PYTHONPATH so the imports resolve. Without this the
# container completed 2026-05-27 18:14 with Q8 SOLVED 7/7 by Gemini but
# grader3.verdict=UNKNOWN (ModuleNotFoundError) — no rework, no
# cross-provider check, no UNVERIFIABLE downgrade for thin coverage.
COPY scripts /app/scripts
ENV PYTHONPATH=/app/scripts

# UTF-8 locale. Without this the Ubuntu base's POSIX/ASCII default makes
# Python's stdlib encode-as-ascii in transport paths (observed 2026-05-28
# Q2+Q5 smoke: every OpenAI grader call failed with "'ascii' codec can't
# encode character ' '" on proof text containing unicode line
# separators, falling back to gauntlet-only exits — silently disabling
# the cross-model gate).
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# OpenAI SDK for the optional cross-provider grader fallback (2026-05-27).
# Not in requirements.lock.txt because it's a separate dependency surface
# and we don't want to invalidate the Gemini-deps cache layer above when
# the OpenAI SDK bumps versions. The grader path in src treats OpenAI as
# strictly optional: if OPENAI_API_KEY is unset, only the Gemini grader
# runs (current behavior); if set, an independent OpenAI grading call
# runs alongside, with disagreements flagged for grader3 / rework.
RUN pip install --no-cache-dir 'openai>=2.0,<3'

# Where runs and intermediate state live inside the container.
ENV RUNS_DIR=/app/runs
# Per-problem Gemini concurrency. Total in-flight calls ~= this x num_problems.
ENV GEMINI_CONCURRENCY=6

# Validated search config (deploy/terraform/variables.tf, 2026-05-27): W=9 needed
# for hard problems (Q4/Q7/Q8) to find dual-gate-confirmed proofs; D=6 so the
# conjecture-extraction trigger (no_progress>=2, earliest at stage 3) has room to
# fire. The firstproof entrypoint reads these via os.environ.get in main.py
# (the Click --width/--depth options default to None, then fall back to the env
# var, then to 4). First Proof's --env-file carries only secrets, so bake them in.
ENV WIDTH=9
ENV DEPTH=6

# Inputs/outputs are bind-mounted (local) or synced from S3 (AWS) at /data.
VOLUME ["/data"]

# Default working dirs for the firstproof entrypoint. The container reads
# /data/input/input.json (mounted by the operator / S3 sync) and writes per-id
# .tex incrementally to /data/output/, plus token_log.jsonl and solutions.json.
# Per-problem run state lives under /data/runs/ so it survives the --rm of the
# container itself (useful for post-mortem of any single problem that failed).
ENV RUNS_DIR=/data/runs

# GEMINI_API_KEY (required) and OPENAI_API_KEY (optional, for cross-provider
# grader fallback) must be provided at runtime via -e or the AWS task's
# secret pull. The firstproof entrypoint runs the autonomous loop:
#   solver -> .tex written -> Grader 3 -> optional rework -> .tex overwritten
# (per batch.py:run_firstproof). All glitches caught and logged so the
# container exits cleanly with whatever best-so-far .tex it produced.
ENTRYPOINT ["math-solver", "firstproof"]
CMD ["--input", "/data/input/input.json", "--output-dir", "/data/output"]
