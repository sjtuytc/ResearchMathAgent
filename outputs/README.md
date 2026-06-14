# Solution attempts

Independent attempts at the First Proof benchmark problems. Derived only from
`problems/`, `CLAUDE.md`, and the shared preamble — no prior solutions
(`output_solutions/`, `final_solutions/`, `baselines/`, or the migrated
`data/` tree) were read.

## q6 — ε-light subsets (Spielman)

`q6_solution.tex` (compile with `pdflatex q6_solution.tex`; a local copy of
`preamble.tex` is included).

**Answer: Yes** — a universal constant `c > 0` exists.

What is proved in full and self-contained:
- Spectral reformulation `S is ε-light ⇔ Σ_{e⊆S} A_e ⪯ ε·Π`, with
  `Σ_e A_e = Π`, `Σ_e Tr A_e = n−1` (effective-resistance / leverage identity).
- Monotonicity of lightness under taking subsets; reduction to connected graphs.
- All boundary cases (`ε=0`, `ε=1`, edgeless).
- Sparse/independent-set regime: an `ε`-light set of size `≥ n/(d̄+1)` always
  exists, settling all graphs with `ε ≤ 1/(d̄+1)` with `c = 1`.
- Exact extremal analysis of `K_n`: the maximum `ε`-light set has size
  `⌊εn⌋`; hence the order `Θ(εn)` is sharp and `c ≤ 1`.
- The barrier (potential-function) construction with the upper-barrier
  Woodbury update lemma, its validity proof, and the aggregate per-step cost
  bound (the global leverage budget).

Remaining ingredient (flagged honestly in the writeup, Remark on status): the
two-barrier constant accounting that turns the expected-size estimate into
`Ω(εn)` with an explicit absolute constant. This is the established
Batson–Spielman–Srivastava-type bookkeeping; optimized it gives `c = 1/42`.
The conjectured optimal constant is `c = 1/2` (not addressed).
