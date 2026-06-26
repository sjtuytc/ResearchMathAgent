# Query Pack — "research math agents"

> Compressed, context-window-friendly summary (budget 8000 chars). Bootstrapped by hand;
> normally regenerated deterministically by `research_wiki.py query`. Source for project
> direction: CLAUDE.md (no RESEARCH_BRIEF.md present).

## Project direction

**Research subject (math).** The $\varepsilon$-light subset problem in spectral graph theory.
Core question: does there exist a universal constant $c>0$ such that for every graph $G=(V,E)$
and every $\varepsilon\in[0,1]$ there is an $\varepsilon$-light subset $S\subseteq V$ with
$|S|\ge c\varepsilon|V|$? Status: yes, proven with $c=1/42$ (Spielman); conjectured tight at
$c=1/2$. Current focus is problem q6.

**Research subject (agents).** The repo (ResearchMathAgent) builds a benchmark-fair
`rma solve` pipeline that runs an LLM math-research agent against the *First Proof* benchmark
(10 graduate-level problems, `problems/q1`–`q10`, spanning stochastic analysis, representation
theory, algebraic combinatorics, spectral graph theory, algebraic topology, lattices, symplectic
geometry, tensor analysis, numerical linear algebra). Solver outputs go to
`outputs/output_solutions/<exp>_<model>/`.

**Hard constraint (contamination).** STRICT RULE: never read prior solutions under
`outputs/output_solutions/`, `final_solutions/`, or `baselines/`. Reading them invalidates the
benchmark. Permitted reads for solving: `problems/`, `skills/`, `CLAUDE.md`, preamble files only.

## Top gaps

- **G1** — Tight constant for $\varepsilon$-light subsets: $1/42$ proven vs. $1/2$ conjectured. Open.
- **G2** — Benchmark-fair evaluation of LLM math-research agents without solution contamination.

## Paper clusters

_None yet — no papers ingested. Seed clusters once `/research-lit` / `/arxiv` populate `papers/`._
Suggested seed searches for "research math agents": LLM theorem proving & autoformalization;
LLM agents for open math problems; benchmark contamination / data leakage in math reasoning;
proof verification with cross-model review.

## Failed ideas

_None recorded yet._ (This section is never pruned — highest anti-repetition value.)

## Top papers

_None._

## Active chains

_None._

## Open unknowns

- Where does the true constant for the $\varepsilon$-light subset problem lie in $[1/42, 1/2]$?
- What evaluation protocol makes an LLM-math-agent benchmark robust to memorized solutions?
