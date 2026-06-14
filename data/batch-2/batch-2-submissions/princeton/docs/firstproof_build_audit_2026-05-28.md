# FirstProof Challenge 2 — Build Audit

**Date:** 2026-05-28
**Worktree:** `~/claudecode/math_solver_fix`
**Branch:** `fix/bs-gate-ranking-and-double-extract` (HEAD `06e1216`)
**Context:** FirstProof's `run.sh` builds the container with `docker build` at the
repo root, then runs `docker run --rm -v input.json -v output --env-file secrets.env <image>`.

---

## Verdict: FirstProof will build the wrong image

`docker build` at the repo root uses the default **`./Dockerfile`** — **not**
`deploy/Dockerfile`. The root Dockerfile is frozen at merge commit `e610091` and
is missing **every** fix the team landed on `deploy/Dockerfile` over the last two
days. The contest would run a degraded pipeline: grader3 disabled, cross-provider
grader disabled, PDF distillation broken, and at **4×4 instead of the validated 9×6**.

The team believes they are shipping the `deploy/Dockerfile` pipeline (the one
validated on AWS). They are not.

---

## Evidence

All validated work went into `deploy/Dockerfile` only:

```
deploy/Dockerfile:  ff9116e  poppler-utils (pdftotext)          ─┐
                    3c7d9fb  OpenAI U+2028 encode-crash fix      │  none of these
                    34b421d  make grader3 importable in container │  touched ./Dockerfile
                    3e0f9f0  ENTRYPOINT firstproof; W=9 D=6; OpenAI key ─┘
./Dockerfile:       e610091  (merge) — and nothing since
```

Both files are committed with no uncommitted edits. `.dockerignore` does **not**
exclude `scripts/`, so the build context contains it — but the root Dockerfile
never copies it.

---

## Divergences (root image is missing each)

| # | Missing from `./Dockerfile` | Runtime consequence | Fixed by |
|---|---|---|---|
| 1 | `COPY scripts /app/scripts` + `PYTHONPATH=/app/scripts` | `batch.py:535` looks for `/app/scripts`, which won't exist → grader3 import fails → `grader3.verdict=UNKNOWN`; **no rework, no cross-provider check, no UNVERIFIABLE downgrade**. Exact bug from the Q8 "SOLVED 7/7 but verdict=UNKNOWN" incident (2026-05-27 18:14). | `34b421d` |
| 2 | UTF-8 locale env (`LANG`/`LC_ALL`/`PYTHONIOENCODING`) | OpenAI grader crashes with ascii-codec error on unicode proof text → **cross-model gate silently disabled**, falls back to gauntlet-only exits. | `3c7d9fb` |
| 3 | `pip install 'openai>=2.0,<3'` | No OpenAI SDK → **cross-provider grader can't import** even when a key is set. | `3e0f9f0` |
| 4 | `poppler-utils` (apt) | No `pdftotext` → **paper distillation breaks**. | `ff9116e` |
| 5 | Width/Depth | Root **hardcodes `ENV WIDTH=4 DEPTH=4`**. Validated **9×6** lives only in `deploy/terraform/variables.tf:66,72` → injected via AWS task env, which does **not** exist in FirstProof's `--env-file secrets.env` (secrets only). So the contest runs **4×4**. The variables.tf note states Q4/Q7/Q8 *need* W=9 for dual-gate-confirmed proofs and D=6 for conjecture extraction. | — |

### Minor (worth noting, not blocking)
- Root sets `FIRSTPROOF_MAX_PARALLEL=3` vs code default 10.
- Root sets `RUNS_DIR=/app/runs` vs `/data/runs` → per-problem run state lost on `--rm` (post-mortem only).

### Checked — **not** a problem
- Root `CMD ["math-solver","firstproof"]` passes no I/O args, but the CLI defaults
  are `--input=/data/input/input.json` and `--output-dir=/data/output`
  (`main.py:281-285`), so the input/output contract still holds.

---

## Recommended fix (before launch)

Make the root `./Dockerfile` **be** the validated image:

1. Replace the contents of `./Dockerfile` with `deploy/Dockerfile`.
2. **Add** `ENV WIDTH=9` and `ENV DEPTH=6` to it — FirstProof's env-file won't
   supply them, unlike the AWS path.

Build-context paths resolve from the repo root unchanged: `deploy/Dockerfile`
already copies `deploy/requirements.lock.txt`, `pyproject.toml`, `src`, and
`scripts` relative to the root context, which is exactly what FirstProof's
root `docker build` uses.

After editing, rebuild and confirm in the image:
- `python -c "import grader3"` succeeds (scripts on path),
- `pdftotext -v` present,
- `python -c "import openai"` succeeds,
- `locale` shows UTF-8,
- the firstproof entrypoint logs W=9 D=6.

### Why not just point run.sh at `deploy/Dockerfile`?
FirstProof controls `run.sh`; the team does not. It builds the root Dockerfile
with the default filename. The only thing under the team's control is what
`./Dockerfile` contains.
