# RMA: an Agentic System for Research-Level Mathematical Problems

<div align="center">

[![arXiv](https://img.shields.io/badge/arXiv-2605.22875-b31b1b.svg)](https://arxiv.org/abs/2605.22875)
[![GitHub Stars](https://img.shields.io/github/stars/sjtuytc/ResearchMathAgent?style=flat-square)](https://github.com/sjtuytc/ResearchMathAgent/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/sjtuytc/ResearchMathAgent?style=flat-square)](https://github.com/sjtuytc/ResearchMathAgent/network/members)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://github.com/sjtuytc/ResearchMathAgent/pulls)

**Language:** English | [中文](README_zh.md)

![Web UI Overview](figures/web1.png)

</div>

---

## Highlights

> RMA is the first agentic framework that targets **research-level mathematical proof** — not competition problems, not formal theorem proving — by combining specialized agents, structured memory, and iterative verifier feedback.

| Feature | Detail |
|---------|--------|
| **7 research-level datasets** | First Proof Rounds 1 & 2, Erdős Problems, Formal Conjectures, ResearchMath-14k, Unsolved Math, AIM Problem Lists — totalling 22,000+ problems |
| **Multi-agent pipeline** | Initializer → Proposer → Verifier → Refiner, coordinated through shared structured memory |
| **State-of-the-art results** | Solves **8 / 10** First Proof Round 1 problems; outperforms GPT-5.2R and Aletheia |
| **Two Claude backends** | Anthropic Messages API (pay-per-token) *or* Claude Code local CLI (Pro/Max subscription) |
| **Live web UI** | Streaming step-by-step viewer, live PDF preview, per-question issue tracker, token cost display with provider attribution and pie charts |
| **Autonomous daily worker** | Runs the solver overnight with no human in the loop, writes dated reports to `documents/` |
| **Benchmark-fair sandbox** | Contamination boundary enforced in code — prior solutions are never read by the solver |
| **Agentic GitHub Issues API** | REST API (`/api/gh/issues`) so multiple agents can coordinate on real GitHub Issues |

---

## ⚡ Quickstart

Solve a research-level math problem on **your own Claude subscription** in three steps — no API key, no Google Cloud / Vertex, no per-token billing:

```bash
git clone https://github.com/sjtuytc/ResearchMathAgent
cd ResearchMathAgent
./scripts/quick_install.sh     # sets up an isolated env + the `rma` CLI + Claude Code
source .venv/bin/activate      # activate it (the installer prints this line)
claude login                   # log in with YOUR Claude Pro/Max subscription
rma solve q6                   # solve a problem — billed to your subscription
```

`rma solve <q>` uses the **Claude Code** backend by default, so every run is billed to your `claude login` subscription and **never** to a developer's API account or Vertex AI. Pick any First Proof problem `q1`–`q10` (or a dataset problem with `--dataset <slug>`). Want a no-LLM dry run? `rma solve q6 --model-name rma-skeleton`.

---

## Abstract

<details>
<summary>Read full abstract</summary>

We present **Research Math Agents (RMA)**, an agentic framework for automated reasoning on research-level mathematical problems. Unlike prior studies centered on competition mathematics or formal theorem proving, RMA targets research-level mathematical problems that require long-horizon reasoning, literature grounding, and iterative proof refinement. RMA decomposes research-level proof solving into specialized modules for problem analysis, literature search and understanding, fair comparison, knowledge-bank construction, and proof verification, all coordinated by initializer, proposer, and verifier agents through a shared structured memory. Within this unified framework, these agents operate in a multi-role, multi-round workflow, collaboratively generating, refining, and verifying candidate proofs through iterative feedback. We evaluate RMA on the First Proof benchmark, which consists of ten research-level problems contributed by expert mathematicians across diverse domains. Through comprehensive expert evaluation, RMA outperforms strong baselines on the First Proof benchmark, including GPT-5.2R and Aletheia, solving eight out of ten research problems and producing more logically sound and readable proofs. Our comprehensive ablation studies further show that performance gains arise from the interaction of structured reasoning modules, iterative refinement, and verifier-based feedback, rather than any single component.

</details>

![Teaser](figures/teaser.png)

---

## Overview

![Model](figures/model.png)

RMA targets **research-level mathematics** (not competition math or formal theorem proving) by combining specialized modules for problem analysis, literature search and understanding, fair comparison, knowledge-bank construction, and proof verification.

Within a multi-role, multi-round workflow, initializer/proposer/verifier agents share structured memory to iteratively generate, refine, and validate candidate proofs. On the First Proof benchmark, RMA reports stronger results than strong baselines through structured modules, iterative refinement, and verifier feedback.

---

## Supported Datasets

RMA works with any of the following benchmark collections out of the box. Switch datasets by pointing `config/default.yaml` to `data/datasets/<slug>/problems/`.

| Dataset | Problems | Description | License |
|---------|----------|-------------|---------|
| **First Proof — Round 1** | 10 | 10 open research-level math problems posed by leading mathematicians across 10 distinct fields (stochastic analysis, representation theory, spectral graph theory, …). Our primary evaluation benchmark. | CC BY 4.0 |
| **First Proof — Round 2** | 10 | Second batch (June 2026) spanning descriptive set theory, piecewise-linear geometry, probability, Riemannian geometry, stochastic PDE, combinatorics, group theory, tropical geometry, and operator algebras. | CC BY 4.0 |
| **Erdős Problems** | 1,217 | 1,179 open problems posed by Paul Erdős, maintained by Terence Tao. Includes cash prizes, OEIS references, and current open/solved status. | Apache-2.0 |
| **Formal Conjectures** *(Google DeepMind)* | 4,557 | 2,571 formal mathematical conjectures in Lean 4, including 1,029 open problems (marked `sorry`). Covers number theory, combinatorics, analysis, and algebra. | Apache-2.0 / CC-BY-4.0 |
| **ResearchMath-14k** | 14,056 | 14k research-level problems collected from arXiv papers and workshop lists, spanning 11 domains, annotated with open/solved/partially-solved status. ([arXiv:2605.28003](https://arxiv.org/abs/2605.28003)) | CC BY 4.0 |
| **Unsolved Math** | 2,084 | Open problems drawn from 12 curated sets: Millennium Prize, Hilbert's 23, Erdős (632), Ben Green's 100, DARPA 23, Smale's, Landau's, Hardy-Littlewood, Richard Guy's Primes, Kourovka Notebook, Kirby Topology, OpenGarden. | CC-BY-4.0 |
| **AIM Problem Lists** | 101 | Open problem lists from American Institute of Mathematics workshops, covering 80+ topics in pure and applied mathematics. | Academic / attribution required |

> **Total: 22,035 problems across 7 collections.**

---

## Quick Start

**Fastest path — your Claude subscription, no API key** (see [⚡ Quickstart](#-quickstart) above):

```bash
./scripts/quick_install.sh     # isolated env + `rma` CLI + Claude Code backend
source .venv/bin/activate      # activate it (the installer prints this)
claude login                   # your Claude Pro/Max subscription
rma solve q6                   # solve on your subscription (default backend)
```

**Other options:**

```bash
# Web UI — streaming solver, live PDF preview, per-question issue tracker
pip install -e ".[webapp]"
python -m webapp               # → http://127.0.0.1:8000

# Pay-per-token Anthropic API instead of the subscription
export ANTHROPIC_API_KEY="<your key>"
rma solve q6 --model-name claude-opus-4-8
```

---

## Repository Structure

<details>
<summary>Expand file tree</summary>

```
ResearchMathAgent/
├── problems/             # Benchmark problem statements (q1..q10 .tex files)
├── skills/               # Math-research skill instructions for the solver
├── final_solutions/      # Published/reference proofs — NOT solver inputs
├── outputs/              # Solver outputs (write destination, on shared storage)
├── rma/                  # CLI tooling: parse / propose / verify / refine / solve
├── webapp/               # Live web app (FastAPI + vanilla JS)
│   └── README.md         # Web app details
├── documents/            # Daily reports from the autonomous worker
├── config/default.yaml   # Project paths and execution tier presets
└── main.tex              # Paper source
```

- `problems/` → `final_solutions/` boundary is enforced; the solver never reads prior solutions.
- `outputs/` (symlink to shared storage) is the write destination for all `rma solve` runs.
- See [TODO.md](TODO.md) for the remaining engineering roadmap.

</details>

---

## Codebase Architecture

One-sentence description of every Python module in the project.

### `rma/` — CLI entry points

| File | Role |
|------|------|
| `cli.py` | Top-level `rma` argument parser; dispatches to `solve`, `push`, `memory`, `doctor` subcommands. |
| `push.py` | `rma push` — runs push-forward (issues + meetings + documents), refreshes concepts/insights/proof-eval, then builds the master context-report PDF. |
| `solve.py` | `rma solve` — runs a full solver agent on one problem: parse → propose → verify → refine → consolidate. |
| `models.py` | Model name constants and aliases used across CLI flags and API calls. |
| `memory.py` | `rma memory` — prints or clears the push-forward state file. |
| `doctor.py` | `rma doctor` — environment health check: Python version, tectonic, Claude CLI / API keys. |
| `__main__.py` | `python -m rma` entry point; delegates to `cli.py`. |

### `webapp/` — FastAPI server

| File | Role |
|------|------|
| `server.py` | All API endpoints for the research web app (proof CRUD, PDF compile, issues, meetings, insights, context reports, literature). |
| `agent.py` | Base agent class and prompt-execution loop shared by all agent types (critic, solver, meeting, document). |
| `claude_code.py` | Claude Code CLI driver — runs the `claude` binary for subscription-based (Pro/Max) LLM calls, plus the one-shot `complete_via_cli()` helper. |
| `llm.py` | One-shot completion helper (`complete()`) routed through the Claude subscription CLI. |
| `context_report.py` | Builds book-style LaTeX context reports per problem (Problem → Evaluation → Best Proof → Meetings → Issues → Insights) and compiles them to PDF via tectonic; also builds the combined master PDF for `rma push`. |
| `proof_eval.py` | LLM rubric evaluation of the best proof: answer accuracy, logical correctness, proof completeness, proof clarity — stored in `documents/questions/<pid>/proof_eval.json`. |
| `insight_agents.py` | LLM agents that generate system-level, dataset-level, and per-question insight summaries from current project state. |
| `insight_loop.py` | Background polling loop that periodically regenerates insight summaries. |
| `insights.py` | Load/save insight JSON files from `webapp/insights/<level>/`. |
| `issue_agents.py` | Critic agent (discovers proof gaps → opens issues) and solver agent (resolves open issues via LLM proof-writing). |
| `issue_loop.py` | Background loop that auto-runs the issue solver on open issues while the server is running. |
| `issue_pdf.py` | Compiles a single issue thread or all issues for a problem into a PDF. |
| `issues.py` | CRUD for issue JSON files under `webapp/issues/<dataset>/<pid>/`. |
| `meet_agents.py` | Mathematician-persona discussion agents that run multi-round research meetings and produce action plans. |
| `meet.py` | CRUD for meeting rooms stored under `documents/questions/<pid>/meets/`. |
| `meet_pdf.py` | Compiles a meeting room's notes (plan + discussion transcript) into a PDF. |
| `push_forward.py` | Orchestrator: for each problem runs issue-discovery → solver → meeting → document update; called by `rma push` and the nightly cron. |
| `push_forward_cli.py` | CLI wrapper so `push_forward` can run outside uvicorn's auto-reload process. |
| `concepts.py` | Load/save/generate per-problem concept lists (core + background) from problem LaTeX. |
| `concepts_pdf.py` | Compiles a problem's concept list into a standalone PDF. |
| `proofs.py` | Load/store best-proof records; `get_best_proof`, `consolidate_best`, `compile_best_pdf`. |
| `proof_history.py` | Load and summarize the version history of proof attempts for a problem. |
| `problem_pdf.py` | Compiles a raw problem `.tex` file (with shared preamble) into a standalone PDF. |
| `problem_export.py` | Export problem statements in various formats (JSON, plain text, LaTeX). |
| `latex.py` | tectonic / pdflatex wrapper: `compile_tex`, `compile_problem_pdf`, `safe_pdf_name`, PDF directory helpers. |
| `dataset_store.py` | Read/query problem metadata from `data/datasets/<slug>/` (titles, statements, solution status). |
| `documents.py` | List and read document files under `documents/questions/<pid>/` (overview, strategies, timeline, etc.). |
| `rich_documents.py` | Regenerate question overview/progress documents with AI-written content after each push. |
| `doc_bundle.py` | Build the combined "bundle.pdf" from all documents for a question or dataset. |
| `literature.py` | Search, download, and seed the global paper library for a problem's area. |
| `hero.py` | Generates the overview/strategy document for a problem (the "hero" document shown in the Documents tab). |
| `runs.py` | Track experiment run metadata: start time, model name, experiment name, completion status. |
| `smoke_pipeline.py` | External eval pipeline: `POST /api/solve` → async proof generation + LLM rubric evaluation. |
| `solvability_eval.py` | Load/save per-problem solvability scores produced by the filter app. |
| `solve_finalize.py` | Post-solve cleanup: consolidate proof files, update best-proof record, write summary. |
| `todos.py` | Per-problem TODO list CRUD (stored in `documents/questions/<pid>/todos.json`). |
| `token_log.py` | Track and display LLM token usage and cost per session, with provider attribution. |
| `tools.py` | Tool definitions (file read/write/search/run) available to claude_code agents during solving. |
| `github_issues.py` | GitHub Issues REST API wrapper for agent-coordinated issue tracking on real GitHub repositories. |
| `devlog.py` | Append timestamped entries to `documents/devlog.jsonl` for session and event history. |
| `daily.py` | Scheduled daily tasks — currently wraps push-forward as a cron-style target. |
| `seed_fp2.py` | One-shot importer: seeds the `first_proof_2` dataset from the GitHub `1stproof/batch-2` repository. |
| `prefix.py` | `API_PREFIX` constant (`/rmac/solve`) shared by modules that generate absolute API URLs. |
| `__main__.py` | `python -m webapp` entry point: starts uvicorn with `HOST`/`PORT` env vars. |

### Root-level scripts

| File | Role |
|------|------|
| `proxy_server.py` | Lightweight reverse proxy: routes `/rmac/solve/*` → solve app on :8011 and `/rmac/filter/*` → filter app on :8012. |
| `run_fp2_init.py` | One-shot script that seeds the `first_proof_2` dataset and initializes per-problem issue/insight directories. |
| `run_pf_standalone.py` | Alias/wrapper for running push-forward outside the uvicorn process (keeps logs separate from the server). |

---

## CLI

Install once for the `rma` command:

```bash
pip install -e .
rma doctor        # health check
```

Or run without installing:

```bash
python -m rma doctor
```

<details>
<summary>Staged pipeline (parse / propose / verify / refine)</summary>

The pipeline is:

```
parse → propose → verify → refine
```

Each stage can be run individually. Later stages auto-initialize missing earlier artifacts.

```bash
rma parse q6
rma propose q6
rma verify q6
rma refine q6
```

With explicit experiment/model controls:

```bash
rma parse q6    --exp-name proofs_v1_june13 --model-name rma-skeleton
rma propose q6  --exp-name proofs_v1_june13 --model-name rma-skeleton
rma verify q6   --exp-name proofs_v1_june13 --model-name rma-skeleton
rma refine q6   --exp-name proofs_v1_june13 --model-name rma-skeleton
```

Stage outputs:

| Stage | Writes |
|-------|--------|
| `parse` | `parsed_problem.json`, `problem_analysis.md` |
| `propose` | `qN_solution.tex`, versioned proposal artifacts |
| `verify` | Verification report (JSON + Markdown), renders PDF |
| `refine` | Rewrites `qN_solution.tex` based on the latest report |

`verify` checks LaTeX/artifact correctness **and** mathematical-completeness gates (proof length, subclaim structure, subproofs, hypothesis audits, citations, boundary-case proofs).

</details>

<details>
<summary>rma solve — full solver loop</summary>

`rma solve` orchestrates `parse → propose → verify` and calls `refine` on failure, repeating up to `--max-rounds`. A run is marked `verified` only when ALL verifier gates pass.

```bash
# Solve one problem
rma solve q6

# Solve all 10 problems
rma solve --all

# Named experiment + skeleton model (pipeline test)
rma solve --all --exp-name proofs_test_all_june13 --model-name rma-skeleton

# Execution tier (recorded in metadata)
rma solve q6 --tier budget      # or standard / pro

# Limit refiner rounds
rma solve q6 --max-rounds 3

# Use math-research skill
rma solve q6 --skill-path skills/math-research/SKILL.md

# Write only .tex (skip PDF render)
rma solve q6 --no-render
```

**Output folder layout:**

```
outputs/first_proof_1/proofs_v1_june13_rma-skeleton/
  q6_solution.tex
  q6_solution.pdf
  q6/
    input/problem.tex
    artifacts/
      metadata.json
      status.json
      report.md
      parsed_problem.json
      problem_analysis.md
      proposals/proposal_001.tex
      verifications/verification_001.json
      refinements/
```

**Example terminal output:**

```
RMA solve
tier: standard
skill: skills/math-research/SKILL.md
status: needs_refinement
output: outputs/first_proof_1/proofs_v1_june13_rma-skeleton
solution: outputs/first_proof_1/proofs_v1_june13_rma-skeleton/q6_solution.tex
verification: .../verification_003.json
```

</details>

<details>
<summary>Claude backends — API key vs subscription</summary>

**Anthropic Messages API** (pay-per-token):

```bash
export ANTHROPIC_API_KEY="<your key>"
rma solve q6 --model-name claude-opus-4-8
rma solve --all --model-name claude-sonnet-4-6 --max-rounds 3
```

On macOS, store the key in Keychain to avoid exporting it:

```bash
security add-generic-password -U -a "$USER" -s rma_anthropic_api_key -w "<key>"
rma solve q6 --model-name claude-sonnet-4-6    # picks up from Keychain
```

Force the API backend explicitly:

```bash
rma solve q6 --model-provider anthropic --model-name claude-opus-4-8
```

**Claude Code** (Pro/Max subscription — no API credits consumed):

```bash
claude                  # complete browser login once
rma solve q6 --model-provider claude-code --model-name claude-code
rma solve --all --model-provider claude-code --model-name claude-code --max-rounds 3
```

`claude-code` drives the local `claude -p` headless CLI. Unset `ANTHROPIC_API_KEY` if you want subscription billing (not API billing).

**Auto-detect:** `--model-provider auto` (default) uses Claude Code for `rma-skeleton` and the Anthropic API for any `claude-*` model name.

</details>

---

## Web App

```bash
pip install -e ".[webapp]"
python -m webapp          # → http://127.0.0.1:8000
```

On a remote server, forward the port:

```bash
ssh -L 8000:localhost:8000 user@server
```

<details>
<summary>Web app feature list</summary>

- **Overview tab** — 3-level hierarchy (System → Dataset → Question) with SVG donut pie charts; cost attribution by purpose (proof research vs website dev); hover tooltips on all charts and info icons
- **Question tab** — renders the `.tex` problem statement with KaTeX; toggle raw/rendered
- **Issue tab** — GitHub-style per-problem issue tracker (multi-agent comment threads, status, labels); full LaTeX / MathJax rendering; also exposes `/api/gh/issues` for direct GitHub Issues control
- **Agent tab** — run the solver live with streaming thinking + tool calls + rendered math + token cost
- **Documents tab** — browse dated daily reports; trigger a manual agent run; full LaTeX rendering for equations
- **Dev Log tab** — website change history accessible from the command palette (`Ctrl K → devlog`)
- **Two Claude backends** — API key or local Claude Code subscription (the `claude` CLI in headless mode, so runs draw from your Pro/Max subscription, not API credits)
- **Live step-by-step stream** — every thinking block, assistant text, tool call, and result appear in real time
- **Stop button** — `POST /api/cancel` kills the backend process group immediately, stopping subscription consumption
- **Active runs panel** — lists every in-flight run with per-run Stop buttons for parallel-run control
- **PDF preview** — compile `solution.tex` inline (requires server-side LaTeX); degrades gracefully
- **Token / cost display** — per-turn usage chart and per-card annotation
- **Autonomous daily worker** — `python -m webapp.daily` runs the solver nightly, writes `documents/YYYY-MM-DD.md`, logs each run to the question's issue thread

</details>

<details>
<summary>Agentic GitHub Issues API</summary>

Many solver agents can coordinate on real GitHub Issues via the web app's REST API.  All endpoints are under `/api/gh/`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/gh/status` | GET | Token availability + repo name |
| `/api/gh/issues?problem_id=q6` | GET | List issues (filtered by `problem:q6` label) |
| `/api/gh/issues` | POST | Create issue `{problem_id, title, body, labels}` |
| `/api/gh/issues/{n}` | GET | Get issue + comments |
| `/api/gh/issues/{n}/comment` | POST | Add comment `{body}` |
| `/api/gh/issues/{n}` | PATCH | Update `{title, state, labels, body}` |
| `/api/gh/issues/{n}/close` | POST | Close issue |
| `/api/gh/issues/{n}/reopen` | POST | Reopen issue |
| `/api/gh/search?q=...` | GET | GitHub search syntax |

Requires `GITHUB_TOKEN` env var for writes (fine-grained PAT, Issues read/write).  Reads work unauthenticated (60 req/hr).

</details>

---

## Solver Contamination Boundary

<details>
<summary>Fair-evaluation rules</summary>

The solver must treat First Proof official solutions and prior AI-generated solutions as **blocked input**. The solving process may read:

- `problems/` — benchmark problem statements
- `skills/` — math-research skill instructions
- Same-run artifacts (created by earlier stages of the same run)

The solver must **never** read, grep, glob, summarize, render, or otherwise use existing files under:

- `final_solutions/`
- `outputs/`
- `baselines/`
- Public First Proof official-solution pages or derivative writeups

`outputs/` is allowed as a **write** destination only.  Prior output folders and unrelated existing solution artifacts remain blocked solver context.

The primary solver command:

```bash
rma solve q6      # reads problems/q6.tex only; writes fresh artifacts
rma solve --all   # benchmark-fair over all 10 problems
```

</details>

---

## Paper Build

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

---

## Acknowledgements

We thank **PoggioAI** for open-sourcing `PoggioAI_MSc`, which inspired the system-organization direction and README structure of this project. We also thank the **[TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany)** team for open-sourcing their agent-loop-over-model framework and questions/issues workspace design, which inspired the architecture of the RMA web app. We additionally acknowledge **[Andrej Karpathy](https://github.com/karpathy)**'s [autoresearch](https://github.com/karpathy/autoresearch) project for pioneering the idea of fully automated AI-driven scientific discovery, which served as an important conceptual inspiration for RMA's autonomous solver pipeline.

We gratefully acknowledge the creators and maintainers of the benchmark datasets integrated in RMA:

- **First Proof** (Rounds 1 & 2) — [firstproof.ai](https://firstproof.ai) / [github.com/1stproof/batch-2](https://github.com/1stproof/batch-2). Research-level open problems contributed by expert mathematicians. Licensed CC BY 4.0.
- **Erdős Problems** — [Terence Tao](https://terrytao.wordpress.com/) and contributors, [github.com/teorth/erdosproblems](https://github.com/teorth/erdosproblems). Licensed Apache-2.0.
- **Formal Conjectures** — Google DeepMind, [github.com/google-deepmind/formal-conjectures](https://github.com/google-deepmind/formal-conjectures). Licensed Apache-2.0 / CC-BY-4.0.
- **ResearchMath-14k** — [arXiv:2605.28003](https://arxiv.org/abs/2605.28003), available on [Hugging Face](https://huggingface.co/datasets/amphora/ResearchMath-14k). Licensed CC BY 4.0.
- **Unsolved Math** — [ulamai/UnsolvedMath](https://huggingface.co/datasets/ulamai/UnsolvedMath) on Hugging Face. Licensed CC-BY-4.0.
- **AIM Problem Lists** — [American Institute of Mathematics](http://aimpl.org/). Academic use with attribution.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sjtuytc/ResearchMathAgent&type=Date)](https://star-history.com/#sjtuytc/ResearchMathAgent&Date)

---

## Citation

```bibtex
@article{zhao2026rma,
  title={RMA: an Agentic System for Research-Level Mathematical Problems},
  author={Zhao, Zelin and Yuan, Bo and Choi, Jaemoo and Chen, Yongxin},
  journal={arXiv preprint arXiv:2605.22875},
  year={2026}
}
```
