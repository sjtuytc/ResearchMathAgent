# AgentForMath — Research Project

## Overview
This project studies the **$\varepsilon$-light subset problem** in spectral graph theory.

**Core question**: Does there exist a universal constant $c > 0$ such that for every graph $G=(V,E)$ and every $\varepsilon \in [0,1]$, there is an $\varepsilon$-light subset $S \subseteq V$ with $|S| \geq c\varepsilon|V|$?

**Status**: Yes — proven with $c = 1/42$ (Spielman). Conjectured tight: $c = 1/2$.

## Repository Structure

### Problems
All 10 problems from the *First Proof* benchmark live in `problems/`:
- `problems/q1.tex` — Stochastic Analysis: $\Phi^4_3$ measure equivalence under shift (Hairer)
- `problems/q2.tex` — Representation Theory: Whittaker functions & Rankin--Selberg integrals (Nelson)
- `problems/q3.tex` — Algebraic Combinatorics: Markov chain with Macdonald stationary distribution (Williams)
- `problems/q4.tex` — Spectral Graph Theory: Subharmonicity of $1/\Phi_n$ under finite free convolution (Srivastava)
- `problems/q5.tex` — Algebraic Topology: Slice filtration for $N_\infty$ operads (Blumberg)
- `problems/q6.tex` — Spectral Graph Theory: $\varepsilon$-light subsets (**current focus**, Spielman)
- `problems/q7.tex` — Lattices in Lie Groups: Uniform lattices with 2-torsion (Weinberger)
- `problems/q8.tex` — Symplectic Geometry: Lagrangian smoothings (Abouzaid)
- `problems/q9.tex` — Tensor Analysis: Algebraic relations on determinantal tensors (Kileel)
- `problems/q10.tex` — Numerical Linear Algebra: Preconditioned CG for RKHS-CP decomposition (Kolda, Ward)
- `problems/preamble.tex` — Shared LaTeX preamble for all problems

### Baselines (reference only)
- `baselines/Claude_solution.tex` — Claude's earlier proof sketch
- `baselines/true_answer.tex` — Spielman's rigorous proof (c = 1/42)
- `baselines/gemni_solution.tex` — Gemini's solution
- `baselines/background.tex` — Background material

### AI Assignments
- `ai_assignments/proof_v1.tex` — Proof attempt v1 (flawed dense case)
- `ai_assignments/proof_v2.tex` — Proof v2 (corrected, barrier function, c = 1/42)

### Skills
- `skills/math-research/SKILL.md` — General math research skill (proof strategies + paper reading)
- `.claude/skills/math-research/SKILL.md` — Project-local skill install

## Active Work
Currently focused on **Q6** ($\varepsilon$-light subsets). Solutions go in `ai_assignments/`.
