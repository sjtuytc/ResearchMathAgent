# ResearchMathAgent — Research Project

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

### AI Assignments
- `ai_assignments/proof_v1.tex` — Proof attempt v1 (flawed dense case)
- `ai_assignments/proof_v2.tex` — Proof v2 (corrected, barrier function, c = 1/42)

### Skills
- `skills/math-research/SKILL.md` — General math research skill (proof strategies + paper reading)
- `.claude/skills/math-research/SKILL.md` — Project-local skill install

## Active Work
Currently building the benchmark-fair `rma solve` pipeline. New solver outputs go in `output_solutions/<exp-name>_<model-name>/`.

## ⛔ STRICT RULE: DO NOT READ PREVIOUS SOLUTIONS

**Never read, glob, or grep existing files inside `output_solutions/`, `final_solutions/`, or `baselines/` directories.**

These directories contain prior AI-generated solutions to the benchmark problems. Reading them constitutes cheating on the benchmark and invalidates the evaluation. `.claudeignore` suppresses them from automatic context, but tool-based access (`Read`, `Glob`, `Grep`) is also forbidden.

This rule applies to Claude itself, all sub-agents, and any automated process. Violation includes:
- Reading any existing file under `output_solutions/`
- Reading any file under `final_solutions/`
- Reading any file under `baselines/`
- Using prior solutions to "understand the format" before writing new ones
- Asking a sub-agent to do any of the above

The only permitted reads for solving are: `problems/`, `skills/`, `CLAUDE.md`, and preamble files. The solver may write fresh files under its own new `output_solutions/<exp-name>_<model-name>/` folder, but must not read prior solution files from that tree.
