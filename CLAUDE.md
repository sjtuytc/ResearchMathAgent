# AgentForMath — Research Project

## Overview
This project studies the **$\varepsilon$-light subset problem** in spectral graph theory.

**Core question**: Does there exist a universal constant $c > 0$ such that for every graph $G=(V,E)$ and every $\varepsilon \in [0,1]$, there is an $\varepsilon$-light subset $S \subseteq V$ with $|S| \geq c\varepsilon|V|$?

**Status**: Yes — proven with $c = 1/42$ (Spielman). Conjectured tight: $c = 1/2$.

## Key Files
- `problem.tex` — Problem statement (English + Chinese)
- `Claude_solution.tex` — Claude's proof sketch (c = 1/4 argument)
- `true_answer.tex` — Spielman's proof (c = 1/42, rigorous)
- `gemni_solution.tex` — Gemini's solution
- `background.tex` — Background material, examples, references
- `ai_assignments/` — AI agent work assignments

## Active Skill
Use the **epsilon-light-proof** skill (at `skills/epsilon-light-proof/SKILL.md`) when working on proofs, examples, or LaTeX for this problem.

## Workflow
- Solutions go in `ai_assignments/` or named `*_solution.tex`
- Always compile with `pdflatex` to check LaTeX before committing
