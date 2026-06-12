# RMA: an Agentic System for Research-Level Mathematical Problems

[[Paper (arXiv)](https://arxiv.org/abs/2605.22875)] [[Final Solutions on First Proofs](final_solutions/)]

Official code release for **RMA**.
RMA is a research math agent system that turns problem statements into verifiable proof artifacts.

- Multi-agent iterative workflow (`initializer -> proposer -> verifier -> refiner`).
- Benchmark-oriented repository with problem sets and merged final solutions.
- Reproducible outputs in structured artifacts (e.g., LaTeX/PDF + machine-readable files).

## Abstract

We present **Research Math Agents (RMA)**, an agentic framework for automated reasoning on research-level mathematical problems. Unlike prior studies centered on competition mathematics or formal theorem proving, RMA targets research-level mathematical problems that require long-horizon reasoning, literature grounding, and iterative proof refinement. RMA decomposes research-level proof solving into specialized modules for problem analysis, literature search and understanding, fair comparison, knowledge-bank construction, and proof verification, all coordinated by initializer, proposer, and verifier agents through a shared structured memory. Within this unified framework, these agents operate in a multi-role, multi-round workflow, collaboratively generating, refining, and verifying candidate proofs through iterative feedback. We evaluate RMA on the First Proof benchmark, which consists of ten research-level problems contributed by expert mathematicians across diverse domains. Through comprehensive expert evaluation, RMA outperforms strong baselines on the First Proof benchmark, including GPT-5.2R and Aletheia, solving eight out of ten research problems and producing more logically sound and readable proofs. Our comprehensive ablation studies further show that performance gains arise from the interaction of structured reasoning modules, iterative refinement, and verifier-based feedback, rather than any single component.

---

## Overview

RMA targets **research-level mathematics** (not just competition math or formal theorem proving) by combining specialized modules for:
- problem analysis,
- literature search and understanding,
- fair comparison,
- knowledge-bank construction, and
- proof verification.

Within a multi-role, multi-round workflow, initializer/proposer/verifier agents share structured memory to iteratively generate, refine, and validate candidate proofs. On the First Proof benchmark, RMA reports stronger results than strong baselines through structured modules, iterative refinement, and verifier feedback.

---

## Repository Structure

- `problems/`: benchmark problem statements.
- `skills/`: project skills for math reasoning/research.
- `final_solutions/`: merged and per-author final proof artifacts.
- `main.tex` and related TeX files: the paper source.

A unified executable pipeline (CLI, configs, run registry) is under development; see [TODO.md](TODO.md) for the engineering roadmap.

---

## Acknowledgement

We thank **PoggioAI** for open-sourcing `PoggioAI_MSc`, which inspired the system-organization direction and README structure of this project.

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
