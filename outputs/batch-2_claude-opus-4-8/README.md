# Batch-2 solver outputs — claude-opus-4-8

Independent attempts at the 10 First Proof **batch-2** problems, in the benchmark
output format (`prob-XXX.tex`, standalone LaTeX).

## Provenance / fairness
- Problem statements were taken from `batch-2-raw-outputs/Batch2Problems/problems.json`
  in the migrated `data/` tree and saved under `statements/`.
- Each problem was attempted by an **independent solver** given *only* its statement.
  No solver read any other solver's output, any `*/Output/prob-*.tex`, any `*thinking*`,
  any `human-solution`/`AI-solutions`/`reviews`/`submissions` folder, or anything under
  `output_solutions/`, `final_solutions/`, `baselines/`. The attempts are not informed by
  any existing solution.
- `scratch/` and `../../experiments/` hold numerical sanity-check scripts used by some
  solvers (prob-006, prob-008, prob-009).

## Results summary

| # | Area | Answer / result | Status |
|---|------|-----------------|--------|
| 001 | Computable structure theory | **No** (sharper dichotomy proved) | Complete, modulo 2 classical theorems (AKMS/AKS, pairs-of-structures) |
| 002 | Geometric topology | Optimal ratio **√3** (polyhedral Möbius band) | Partial: upper bound complete; sharp lower bound cites Schwartz/Halpern–Weaver |
| 003 | Probability | Holds iff **p ∈ [0,⅓] ∪ {½} ∪ {1}** | Complete (one step via extremal reduction) |
| 004 | Metric geometry (k-dilation) | Volume inequality + full dichotomy | Partial: Case A complete; Case B = Guth directional coarea (cited) |
| 005 | Singular SPDE | **Unique** invariant measure | Partial: Doob–Khasminskii architecture rigorous; n-uniform gradient bound = [ABLM24] mechanism (cited) |
| 006 | Lattices on trees | Irreducible vertex = **v** (the one with w(v)<d(v)) | Partial: main cases proved; one degree-regime case flagged |
| 007 | Topology / GGT | **F_w is contractible** | Complete, modulo Nerve Lemma + Ω²(aspherical) (standard, cited) |
| 008 | Tropical geometry (Dressian) | **Yes** | Partial: proved for Boolean family; verified all matroids ≤5 elements |
| 009 | Algebraic combinatorics | Hook coeffs c_λ(n): single-row = #{σ: maj(σ)=a}; general hook = Weyl alt. sum / parking-fn | Partial: single-row complete; general hook validated n≤5 |
| 010 | Von Neumann algebras | **Properly proximal** | Partial: structural reduction complete; DEP amalgam permanence cited |

## Honesty note
These are genuine research-frontier problems. One answer (prob-003) is a complete
self-contained proof; the rest range from "complete modulo a cited classical theorem"
to "rigorous reduction + verified special cases with an honestly-flagged gap." Every
file begins with its own `Status:` line stating precisely what is and is not proved.
No solver fabricated a complete proof; gaps are marked, not hidden.
