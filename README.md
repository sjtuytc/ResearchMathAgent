# AgentForMath

> A math-agent research system from problem statement to verifiable proof artifacts.

Built by researchers at **Georgia Institute of Technology**.

**Quick Links**: [Paper (arXiv)](https://arxiv.org/abs/2605.22875) | [Final Solutions](final_solutions/) | [Problems](problems/)

`AgentForMath` is the implementation workspace for **RMA (Research Math Agents)**, a framework for solving research-level mathematical problems with multi-agent iterative refinement and verifier feedback.

This repository focuses on hard benchmark problems and organizes agent-generated outputs into reproducible proof artifacts (LaTeX/PDF). The current repository already contains problem sets, project skills, and merged final solutions.

This README is both:
- a research-facing project entrypoint linked to the RMA paper, and
- a **vNext system design draft** inspired by `PoggioAI_MSc`, tailored to math-agent workflows.

---

## Paper

- **Title**: *RMA: an Agentic System for Research-Level Mathematical Problems*
- **Authors**: Zelin Zhao, Bo Yuan, Jaemoo Choi, Yongxin Chen
- **Institution**: Georgia Institute of Technology
- **arXiv**: https://arxiv.org/abs/2605.22875

### Paper Summary

RMA targets **research-level mathematics** (not just competition math or formal theorem proving) by combining specialized modules for:
- problem analysis,
- literature search and understanding,
- fair comparison,
- knowledge-bank construction, and
- proof verification.

Within a multi-role, multi-round workflow, initializer/proposer/verifier agents share structured memory to iteratively generate, refine, and validate candidate proofs. On the First Proof benchmark, the paper reports stronger results than strong baselines through the combination of structured modules, iterative refinement, and verifier-based feedback.

---

## 1) Project Goal

- Build a reliable math-agent pipeline: `problem -> reasoning -> proof draft -> verification -> final artifact`.
- Keep all outputs reproducible and auditable (inputs, prompts, intermediate drafts, final files).
- Support iterative research runs without losing prior artifacts.

---

## 2) Current Repository Snapshot

- `problems/`: benchmark problem statements.
- `skills/`: project skills for math reasoning/research.
- `final_solutions/`: merged and per-author final proof artifacts.
- `main.tex` and related TeX files: paper/report side.

Current strength: strong proof artifacts and benchmark focus.  
Current gap: no unified executable pipeline interface yet (CLI/config/run registry/checkpointing).

---

## 3) What We Can Borrow from PoggioAI_MSc

The following patterns are highly reusable for math agents and should be ported first:

1. **Single entry CLI**
   - Example target: `afm run "Solve Q6 with strict verification"`.
   - Why: one stable entrypoint drastically lowers operational friction.

2. **Tiered execution profiles**
   - Example: `budget / standard / pro`.
   - Why: explicit control over model cost, runtime, and quality level.

3. **Config + setup + doctor commands**
   - Example: `afm setup`, `afm doctor`, `afm config set ...`.
   - Why: avoid hidden environment bugs before expensive runs.

4. **Artifact contracts between stages**
   - Each stage must output structured files (e.g., `claims.json`, `proof.tex`, `checks.json`).
   - Why: prevents silent degradation and makes failures diagnosable.

5. **Run registry and resumability**
   - Save each run under timestamped folders with metadata and logs.
   - Why: enables compare/retry/resume rather than restarting from scratch.

6. **Campaign mode for multi-problem programs**
   - Orchestrate multi-stage plans across several questions.
   - Why: math-agent work often spans related tasks, not one-off prompts.

---

## 4) vNext Architecture for Math Agents

Recommended staged graph:

1. **Problem Parsing**
   - Normalize problem statement, assumptions, notation.

2. **Strategy Proposer**
   - Generate candidate proof strategies and required lemmas.

3. **Proof Constructor**
   - Produce structured proof draft in LaTeX + machine-readable skeleton.

4. **Verifier**
   - Multi-pass checks: logical consistency, missing assumptions, symbol mismatch.

5. **Refiner**
   - Patch weak steps and regenerate only failed proof sections.

6. **Writer/Packager**
   - Produce final `proof.tex`, `proof.pdf`, and run report.

Each node should emit both human-readable and machine-readable artifacts.

---

## 5) Proposed Folder Layout (vNext)

```text
AgentForMath/
  cli/                     # afm command entry
  config/                  # default configs and tiers
  agents/                  # pipeline nodes (parser, prover, verifier, ...)
  pipelines/               # graph orchestration
  schemas/                 # artifact contracts (json schema / pydantic)
  runs/                    # timestamped run outputs and logs
  problems/                # benchmark tasks
  final_solutions/         # finalized publishable outputs
  tests/                   # unit + integration tests
```

This keeps existing benchmark assets while adding production-grade execution structure.

---

## 6) Suggested CLI Surface

```bash
# one-time setup
afm setup
afm doctor

# run one problem
afm run --problem q6 --tier standard

# run from custom task file
afm run --task-file tasks/q6_strict.txt --tier pro

# inspect and resume
afm runs
afm status <run_id>
afm resume <run_id>

# compare two runs
afm diff <run_id_a> <run_id_b>
```

---

## 7) Quality Gates (Math-Specific)

Before a run is marked complete:

- **Gate A**: all theorem/lemma references resolve.
- **Gate B**: assumptions are explicit and non-contradictory.
- **Gate C**: symbolic notation is consistent globally.
- **Gate D**: proof contains no placeholder claims.
- **Gate E**: output compiles to TeX/PDF without errors.

---

## 8) Migration Plan (from current state)

### Phase 1 (immediate, low risk)
- Add CLI skeleton (`afm run`, `afm doctor`).
- Add `config/default.yaml` and tier presets.
- Standardize run output directory schema.

### Phase 2 (core capability)
- Implement node-based pipeline (`parser -> prover -> verifier -> refiner`).
- Add artifact contracts and failure reporting.
- Add resumable checkpoints.

### Phase 3 (advanced)
- Add campaign mode for multi-problem execution.
- Add optional multi-model counsel for difficult proof branches.
- Add run-to-run regression tests on selected benchmark questions.

---

## 9) Review Checklist (for this README draft)

Please review and confirm:

1. Is the vNext scope aligned with your target system?
2. Should we prioritize CLI + checkpointing before multi-model features?
3. Do you want `runs/` committed partially (metadata only) or fully ignored?
4. Which benchmark questions should be used as golden regression cases first?

Once approved, I will convert this README design into a concrete implementation backlog and start Phase 1 directly in this repo.

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
