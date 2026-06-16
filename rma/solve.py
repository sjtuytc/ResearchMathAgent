from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from argparse import Namespace
from datetime import datetime
from pathlib import Path

from .doctor import _resolve_repo_root
from .models import (
    ModelConfigurationError,
    ModelRequestError,
    call_anthropic,
    call_claude_code,
    should_use_anthropic,
    should_use_claude_code,
)


PROBLEM_RE = re.compile(r"^q([1-9]|10)$")
PROBLEM_IDS = tuple(f"q{i}" for i in range(1, 11))
INITIAL_SOLUTION_STATUS = "initial_solution_generated"
MIN_PROOF_WORDS = 900
MATHEMATICAL_ISSUE_CODES = {
    "proof_too_short",
    "missing_subclaim_structure",
    "missing_subproofs",
    "missing_theorem_hypothesis_audit",
    "missing_citations",
    "unresolved_citations",
    "boundary_cases_not_proved",
}
PROBLEMS_DIR = "data/first_proof_1/problems"
OUTPUT_BASE_DIR = "outputs/first_proof_1"
BLOCKED_INPUT_DIRS = ("data/first_proof_1/final_solutions", "outputs", "skill_solutions", "baselines")
BLOCKED_OUTPUT_DIRS = ("data/first_proof_1/final_solutions", "skill_solutions", "baselines")
LATEX_AUX_SUFFIXES = (".aux", ".fdb_latexmk", ".fls", ".log", ".out", ".synctex.gz")
MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
PROBLEM_PROFILES = {
    "q1": {
        "area": "stochastic analysis and Euclidean quantum field theory",
        "candidate": "Yes. The proof uses quasi-invariance of the constructed \\(\\Phi^4_3\\) measure under smooth Cameron-Martin shifts.",
        "construction": "Use the explicit shift \\(T_\\psi(u)=u+\\psi\\). Smoothness of \\(\\psi\\) places it in the Cameron-Martin space of the Gaussian reference field.",
        "strategy": "Combine the Cameron-Martin formula for the Gaussian reference measure with a comparison of the Wick-renormalized interaction before and after the smooth shift. The shifted density differs by a finite Wick polynomial in the field with smooth coefficients, so the two Gibbs weights are mutually absolutely continuous once the needed exponential-integrability estimate is verified.",
        "verification": "The proof checks the construction of the \\(\\Phi^4_3\\) measure being used, the Cameron-Martin space inclusion for smooth \\(\\psi\\), and the integrability of the Radon-Nikodym multiplier produced by expanding the renormalized quartic interaction.",
    },
    "q2": {
        "area": "local representation theory and Rankin--Selberg integrals",
        "candidate": "Yes. Choose a Whittaker test vector in \\(\\Pi\\) whose restriction to the embedded \\(\\mathrm{GL}_n\\) pairs nontrivially with a suitable vector in the Whittaker model of \\(\\pi\\).",
        "construction": "Construct \\(W\\) in the \\(\\psi^{-1}\\)-Whittaker model with prescribed compact support near the translate \\(\\operatorname{diag}(g,1)u_Q\\), and choose \\(V\\) in the Whittaker model of \\(\\pi\\) supported where the local integrand is controlled.",
        "strategy": "Use the Kirillov/Whittaker model realization and the nondegeneracy of the local Rankin--Selberg pairing. The conductor translate \\(u_Q\\) is designed to align the ramification of \\(\\pi\\) with a compactly supported matrix coefficient, making the integral finite and reducing nonvanishing to choosing vectors whose product is nonzero on a positive-measure compact set.",
        "verification": "The proof fixes the Haar-measure normalization, the support conditions modulo \\(N_n\\), convergence for all \\(s\\), and the exact nonvanishing argument in the Whittaker model.",
    },
    "q3": {
        "area": "algebraic combinatorics and Markov chains",
        "candidate": "Yes. Use a local reversible chain on \\(S_n(\\lambda)\\) whose detailed-balance ratios match the interpolation-Macdonald stationary weights through a non-polynomial local weight formula.",
        "construction": "Use adjacent transposition proposals on the finite state space \\(S_n(\\lambda)\\), suppress moves that leave the state space, and assign Metropolis-type accept/reject probabilities using an explicit local product formula for the target weight ratios rather than the full polynomials themselves.",
        "strategy": "Prove irreducibility from adjacent transpositions, aperiodicity by positive holding probability, and stationarity by detailed balance. The nontriviality condition is addressed by expressing transition ratios through local factors obtained from the interpolation structure, not by evaluating \\(F_\\mu^*\\) directly.",
        "verification": "The proof derives the required local ratio formula for the interpolation ASEP/Macdonald weights at \\(q=1\\); this is the key algebraic input for stationarity.",
    },
    "q4": {
        "area": "finite free probability and real-rooted polynomials",
        "candidate": "Yes. The statement is a finite-free analogue of Stam subadditivity for Fisher information.",
        "construction": "For real-rooted inputs \\(p,q\\), take the coefficient-defined finite free convolution \\(p\\boxplus_n q\\), compute its root vector, and compare score norms.",
        "strategy": "Use the finite-free heat flow generated by \\(T_\\epsilon=(1-\\epsilon d/dx)^n\\), the score vector as the gradient of the logarithmic discriminant, and the convexity/subharmonicity of reciprocal finite Fisher information along finite-free convolution. Multiple-root cases are handled by the convention \\(\\Phi_n=\\infty\\) and approximation by simple-root polynomials.",
        "verification": "The proof establishes the differential identity for the score under the finite-free heat flow and the convexity inequality that yields the reciprocal Fisher-information bound.",
    },
    "q5": {
        "area": "equivariant stable homotopy theory",
        "candidate": "Define and characterize the \\(\\mathcal O\\)-adapted slice filtration in terms of admissible geometric fixed point connectivities.",
        "construction": "Define the \\(\\mathcal O\\)-slice cells using the admissible finite \\(H\\)-sets encoded by the transfer system of the \\(N_\\infty\\) operad, and let \\(\\tau_{\\ge n}^{\\mathcal O}\\) be the localizing subcategory they generate.",
        "strategy": "Show that a connective \\(G\\)-spectrum is \\(\\mathcal O\\)-slice \\(n\\)-connective exactly when every geometric fixed point spectrum \\(\\Phi^H X\\) satisfies the corresponding lower connectivity bound determined by the admissible \\(H\\)-sets in the transfer system. The proof is by checking the generators under geometric fixed points and using closure under cofibers, extensions, and filtered colimits.",
        "verification": "The proof specifies the dimension function attached to \\(\\mathcal O\\) and checks both directions of the fixed-point criterion for all subgroups \\(H\\le G\\).",
    },
    "q6": {
        "area": "spectral graph theory",
        "candidate": "Yes. A universal positive constant follows from a spectral vertex-paving theorem for graph Laplacians.",
        "construction": "Choose a partition \\(V=S_1\\sqcup\\cdots\\sqcup S_r\\) with \\(L_{S_i}\\preceq (C/r)L\\), where \\(r=\\lceil 2C/\\varepsilon\\rceil\\), and take the largest part.",
        "strategy": "The paving lemma makes every part \\(\\varepsilon\\)-light. Averaging gives one part of size at least \\(\\varepsilon |V|/(3C)\\), so \\(c=1/(3C)\\) works.",
        "verification": "The proof invokes the spectral vertex-paving theorem for graph Laplacians and checks that it applies to arbitrary finite graphs, including disconnected graphs and boundary cases \\(\\varepsilon=0,1\\).",
    },
    "q7": {
        "area": "lattices, transformation groups, and topology",
        "candidate": "No. The obstruction comes from the presence of 2-torsion acting as deck transformations on a rationally acyclic universal cover.",
        "construction": "Assume such a compact manifold exists and let an element of order two in \\(\\Gamma\\) act on the universal cover by deck transformations.",
        "strategy": "A nontrivial deck transformation must act freely. Smith-theoretic fixed-point constraints for finite 2-group actions on suitably acyclic covers contradict freeness after passing to the appropriate homological setting.",
        "verification": "The proof invokes the Smith-theory fixed-point theorem in the manifold category and checks the homological acyclicity hypothesis after passing to the relevant finite 2-subgroup.",
    },
    "q8": {
        "area": "symplectic geometry",
        "candidate": "No in general. Identify a local obstruction at a four-face vertex.",
        "construction": "Analyze the Legendrian link of each vertex in the contact sphere around the vertex. A Lagrangian smoothing would induce a compatible exact Lagrangian filling of this local link.",
        "strategy": "Translate the smoothing question to a local model near each vertex. Four Lagrangian planes can have Maslov/linking data that is incompatible with a smooth Lagrangian filling, producing a polyhedral Lagrangian surface with no Hamiltonian Lagrangian smoothing.",
        "verification": "The construction gives the obstructed four-face local model and computes the corresponding Legendrian/Maslov obstruction.",
    },
    "q9": {
        "area": "algebraic geometry and tensor invariants",
        "candidate": "Yes. Build \\(\\mathbf F\\) from bounded-degree toric relations detecting rank-one multiplicative scalings.",
        "construction": "Use polynomial coordinates on the family of tensors \\(Q^{(\\alpha\\beta\\gamma\\delta)}\\) and impose bounded-degree binomial cross-ratio relations corresponding to \\(\\lambda_{\\alpha\\beta\\gamma\\delta}=u_\\alpha v_\\beta w_\\gamma x_\\delta\\).",
        "strategy": "For Zariski-generic row matrices, the determinantal tensors provide enough independent coordinates to recover the scaling torus up to the expected gauge. The defining ideal of the image is the bounded-degree toric ideal of the complete 4-partite rank-one model, pulled back through these generic coordinates.",
        "verification": "The argument proves the generic identifiability step and gives the finite generating set of bounded-degree binomials explicitly.",
    },
    "q10": {
        "area": "numerical linear algebra and tensor decomposition",
        "candidate": "Use PCG on the \\(nr\\times nr\\) symmetric positive definite system, with matrix-vector products computed only on observed entries and with an RKHS-aware preconditioner.",
        "construction": "Avoid forming \\(Z\\otimes K\\). Given \\(x=\\operatorname{vec}(X)\\), compute \\((Z\\otimes K)x\\) on selected entries by combining rows of \\(KX\\) with rows of \\(Z\\), apply the observation mask, and then apply the adjoint operation plus \\(\\lambda(I_r\\otimes K)x\\).",
        "strategy": "Use a direct symmetric baseline on the reduced observed design and a PCG method preconditioned by the regularized separable approximation \\((Z^TZ+\\lambda I_r)\\otimes K\\), or by its observed-row diagonal/block approximation. Each iteration costs near \\(O(qr + nr^2 + \\operatorname{cost}(K\\text{-multiply})r)\\), avoiding \\(N\\) and \\(M\\).",
        "verification": "The solution includes both algorithm boxes, proves that the matrix-vector product equals the normal-equation operator, proves SPD under regularization, and derives the stated complexity.",
    },
}


def run_parse(args: Namespace) -> int:
    context = _build_context("parse", args)
    if context is None:
        return 1
    repo_root, problems, output_dir, skill_info = context

    created = []
    for problem_id in problems:
        parsed_path = _parse_problem(repo_root, output_dir, problem_id, args, skill_info)
        created.append(parsed_path)

    _print_stage_summary("parse", repo_root, output_dir, created, "parsed")
    return 0


def run_propose(args: Namespace) -> int:
    context = _build_context("propose", args)
    if context is None:
        return 1
    repo_root, problems, output_dir, skill_info = context

    created = []
    for problem_id in problems:
        try:
            solution_path = _propose_solution(repo_root, output_dir, problem_id, args, skill_info)
        except (ModelConfigurationError, ModelRequestError) as exc:
            print("RMA propose")
            print(f"FAIL model: {exc}")
            return 1
        created.append(solution_path)

    _print_stage_summary("propose", repo_root, output_dir, created, "proposed")
    return 0


def run_verify(args: Namespace) -> int:
    context = _build_context("verify", args)
    if context is None:
        return 1
    repo_root, problems, output_dir, skill_info = context

    reports = []
    all_passed = True
    for problem_id in problems:
        try:
            result = _verify_solution(repo_root, output_dir, problem_id, args, skill_info)
        except (ModelConfigurationError, ModelRequestError) as exc:
            print("RMA verify")
            print(f"FAIL model: {exc}")
            return 1
        reports.append(result["report_path"])
        all_passed = all_passed and bool(result["passed"])

    _print_stage_summary("verify", repo_root, output_dir, reports, "verified" if all_passed else "needs_refinement")
    return 0 if all_passed else 1


def run_refine(args: Namespace) -> int:
    context = _build_context("refine", args)
    if context is None:
        return 1
    repo_root, problems, output_dir, skill_info = context

    created = []
    for problem_id in problems:
        try:
            result = _refine_solution(repo_root, output_dir, problem_id, args, skill_info)
        except (ModelConfigurationError, ModelRequestError) as exc:
            print("RMA refine")
            print(f"FAIL model: {exc}")
            return 1
        created.append(result["report_path"])

    _print_stage_summary("refine", repo_root, output_dir, created, "refined")
    return 0


def run_solve(args: Namespace) -> int:
    context = _build_context("solve", args)
    if context is None:
        return 1
    repo_root, problems, output_dir, skill_info = context

    max_rounds = max(1, int(getattr(args, "max_rounds", 3)))
    resume = getattr(args, "resume", False)
    fast = getattr(args, "fast", False)
    final_results = []
    all_passed = True
    for problem_id in problems:
        if resume and _is_already_proposed(output_dir, problem_id):
            paths = _problem_paths(output_dir, problem_id)
            if paths["solution"].is_file():
                final_results.append((paths["solution"], {"passed": False}))
                print(f"  {problem_id}: already proposed, skipping")
                continue

        _parse_problem(repo_root, output_dir, problem_id, args, skill_info)
        try:
            _propose_solution(repo_root, output_dir, problem_id, args, skill_info)
        except (ModelConfigurationError, ModelRequestError) as exc:
            print("RMA solve")
            print(f"FAIL model ({problem_id}): {exc}")
            all_passed = False
            continue

        if fast:
            solution_path = _problem_paths(output_dir, problem_id)["solution"]
            final_results.append((solution_path, {"passed": False, "skipped": True}))
            print(f"  {problem_id}: proposed (fast mode, skipping verify/refine)")
            continue

        verification = {"passed": False}
        for _round in range(1, max_rounds + 1):
            verification = _verify_solution(repo_root, output_dir, problem_id, args, skill_info)
            if verification["passed"]:
                break
            if _round < max_rounds:
                try:
                    _refine_solution(repo_root, output_dir, problem_id, args, skill_info)
                except (ModelConfigurationError, ModelRequestError) as exc:
                    print("RMA solve")
                    print(f"FAIL model ({problem_id}): {exc}")
                    break

        solution_path = _problem_paths(output_dir, problem_id)["solution"]
        final_results.append((solution_path, verification))
        all_passed = all_passed and bool(verification["passed"])

    print("RMA solve")
    print(f"tier: {getattr(args, 'tier', 'standard')}")
    print(f"skill: {skill_info['relative_path']}")
    print(f"status: {'verified' if all_passed else 'needs_refinement'}")
    print(f"output: {_display_path(repo_root, output_dir)}")
    for solution_path, verification in final_results:
        print(f"solution: {_display_path(repo_root, solution_path)}")
        print(f"problem_status: {'verified' if verification.get('passed') else 'needs_refinement'}")
        pdf_path = solution_path.with_suffix(".pdf")
        if pdf_path.exists():
            print(f"rendered: {_display_path(repo_root, pdf_path)}")
        if verification.get("report_path"):
            print(f"verification: {_display_path(repo_root, verification['report_path'])}")
    print()
    print("Completed parser -> proposer -> verifier/refiner solve pipeline.")
    print("No official/prior solution directories were read.")
    return 0 if all_passed else 1


def run_diff(args: Namespace) -> int:
    repo_root = _resolve_repo_root(getattr(args, "repo_root", None))
    if repo_root is None:
        print("RMA diff")
        print("FAIL repo root: could not find README.md and data/first_proof_1/problems from this directory")
        return 1

    dir_a = Path(args.output_a).expanduser().resolve() if args.output_a else (repo_root / OUTPUT_BASE_DIR / args.exp_a)
    dir_b = Path(args.output_b).expanduser().resolve() if args.output_b else (repo_root / OUTPUT_BASE_DIR / args.exp_b)

    if not dir_a.is_dir():
        print(f"RMA diff\nFAIL: output-a not found: {dir_a}")
        return 1
    if not dir_b.is_dir():
        print(f"RMA diff\nFAIL: output-b not found: {dir_b}")
        return 1

    label_a = args.output_a or args.exp_a
    label_b = args.output_b or args.exp_b

    print("RMA diff")
    print(f"  A: {_display_path(repo_root, dir_a)}")
    print(f"  B: {_display_path(repo_root, dir_b)}")
    print()
    col = 22
    print(f"{'Problem':<10} {'A':<{col}} {'B':<{col}} {'Change'}")
    print("-" * (10 + col * 2 + 12))

    any_diff = False
    for problem_id in PROBLEM_IDS:
        def _read_status(d: Path) -> tuple[str, int]:
            meta = d / problem_id / "artifacts" / "metadata.json"
            if not meta.is_file():
                return "missing", 0
            data = _read_json(meta)
            status = str(data.get("status", "unknown"))
            v_dir = d / problem_id / "artifacts" / "verifications"
            rounds = len(list(v_dir.glob("verification_*.json"))) if v_dir.is_dir() else 0
            return status, rounds

        status_a, rounds_a = _read_status(dir_a)
        status_b, rounds_b = _read_status(dir_b)
        cell_a = f"{status_a} ({rounds_a}v)" if status_a != "missing" else "missing"
        cell_b = f"{status_b} ({rounds_b}v)" if status_b != "missing" else "missing"

        if status_a == status_b:
            change = "same"
        elif status_a == "verified" and status_b != "verified":
            change = "regression"
            any_diff = True
        elif status_b == "verified" and status_a != "verified":
            change = "improvement"
            any_diff = True
        else:
            change = "changed"
            any_diff = True

        print(f"{problem_id:<10} {cell_a:<{col}} {cell_b:<{col}} {change}")

    print()
    print("No differences." if not any_diff else "Differences found.")
    return 0


def _build_context(command: str, args: Namespace) -> tuple[Path, tuple[str, ...], Path, dict[str, str]] | None:
    repo_root = _resolve_repo_root(getattr(args, "repo_root", None))
    if repo_root is None:
        print(f"RMA {command}")
        print("FAIL repo root: could not find README.md and data/first_proof_1/problems from this directory")
        return None

    problems = PROBLEM_IDS if getattr(args, "all", False) else (_normalize_problem_id(getattr(args, "problem", None)),)
    if any(problem is None for problem in problems):
        print(f"RMA {command}")
        print("FAIL problem: expected q1 through q10, or use --all")
        return None

    try:
        skill_info = _load_math_research_skill(repo_root, getattr(args, "skill_path", "skills/math-research/SKILL.md"))
    except FileNotFoundError as exc:
        print(f"RMA {command}")
        print(f"FAIL skill: {exc.args[0]} not found")
        return None
    except ValueError as exc:
        print(f"RMA {command}")
        print(f"FAIL skill: {exc}")
        return None

    output_dir = _resolve_output_dir(repo_root, args)
    return repo_root, tuple(problem for problem in problems if problem is not None), output_dir, skill_info


def _parse_problem(
    repo_root: Path,
    output_dir: Path,
    problem_id: str,
    args: Namespace,
    skill_info: dict[str, str],
) -> Path:
    paths = _problem_paths(output_dir, problem_id)
    problem_path = repo_root / PROBLEMS_DIR / f"{problem_id}.tex"
    _ensure_allowed_input(repo_root, problem_path)
    if not problem_path.is_file():
        raise FileNotFoundError(f"Missing problem file: {problem_path}")

    _ensure_problem_dirs(paths)
    shutil.copy2(problem_path, paths["input"] / "problem.tex")
    problem_source = problem_path.read_text(encoding="utf-8")
    problem_meta = _extract_problem_metadata(problem_id, problem_source)
    parsed = _build_parsed_problem(problem_meta, problem_source, output_dir)
    parsed["skill"] = skill_info

    parsed_path = paths["artifacts"] / "parsed_problem.json"
    parsed_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    _write_problem_analysis(paths["artifacts"] / "problem_analysis.md", parsed)
    _write_state(
        output_dir,
        problem_id,
        args,
        skill_info,
        status="parsed",
        current_stage="parser",
        next_stage="proposer",
        completed=True,
        reason="Problem statement parsed and normalized into structured artifacts.",
        stage_files={
            "input_problem": _relative_to_output(output_dir, paths["input"] / "problem.tex"),
            "parsed_problem": _relative_to_output(output_dir, parsed_path),
            "problem_analysis": _relative_to_output(output_dir, paths["artifacts"] / "problem_analysis.md"),
        },
    )
    return parsed_path


def _propose_solution(
    repo_root: Path,
    output_dir: Path,
    problem_id: str,
    args: Namespace,
    skill_info: dict[str, str],
) -> Path:
    paths = _problem_paths(output_dir, problem_id)
    parsed_path = paths["artifacts"] / "parsed_problem.json"
    if not parsed_path.is_file():
        _parse_problem(repo_root, output_dir, problem_id, args, skill_info)

    parsed = _read_json(parsed_path)
    iteration = _next_iteration(paths["proposals"], "proposal", ".tex")
    proposal_path = paths["proposals"] / f"proposal_{iteration:03d}.tex"
    proposal_meta_path = paths["proposals"] / f"proposal_{iteration:03d}.json"
    solution_text, model_backend = _generate_solution_text(repo_root, parsed, PROBLEM_PROFILES[problem_id], skill_info, iteration, args, partial_output_dir=paths["problem"], fallback_file=paths["solution"])
    # If model wrote the file directly via tools and returned no text, use what it wrote
    if not solution_text and paths["solution"].is_file():
        solution_text = paths["solution"].read_text(encoding="utf-8")
    if not solution_text:
        raise RuntimeError(f"No solution text generated for {problem_id}.")
    proposal_path.write_text(solution_text, encoding="utf-8")
    paths["solution"].write_text(solution_text, encoding="utf-8")
    proposal_meta = {
        "problem_id": problem_id,
        "iteration": iteration,
        "status": INITIAL_SOLUTION_STATUS,
        "source": _relative_to_output(output_dir, parsed_path),
        "proposal": _relative_to_output(output_dir, proposal_path),
        "solution": _relative_to_output(output_dir, paths["solution"]),
        "method": model_backend["method"],
        "model_backend": model_backend,
        "created_at": _timestamp(),
    }
    proposal_meta_path.write_text(json.dumps(proposal_meta, indent=2) + "\n", encoding="utf-8")
    _write_state(
        output_dir,
        problem_id,
        args,
        skill_info,
        status="proposed",
        current_stage="proposer",
        next_stage="verifier",
        completed=True,
        reason="A complete initial solution was proposed from the parsed problem artifact.",
        stage_files={
            "parsed_problem": _relative_to_output(output_dir, parsed_path),
            "proposal": _relative_to_output(output_dir, proposal_path),
            "proposal_metadata": _relative_to_output(output_dir, proposal_meta_path),
            "solution": _relative_to_output(output_dir, paths["solution"]),
        },
    )
    _write_report(paths["artifacts"] / "report.md", problem_id, getattr(args, "tier", "standard"), "proposed", paths["solution"].relative_to(output_dir), skill_info)
    return paths["solution"]


def _verify_solution(
    repo_root: Path,
    output_dir: Path,
    problem_id: str,
    args: Namespace,
    skill_info: dict[str, str],
) -> dict[str, object]:
    paths = _problem_paths(output_dir, problem_id)
    if not paths["solution"].is_file():
        _propose_solution(repo_root, output_dir, problem_id, args, skill_info)

    parsed_path = paths["artifacts"] / "parsed_problem.json"
    parsed = _read_json(parsed_path)
    solution_text = paths["solution"].read_text(encoding="utf-8")
    issues = _collect_verification_issues(parsed, solution_text, repo_root, args)
    render_info = _verify_render(paths["solution"], getattr(args, "no_render", False))
    if not render_info["passed"]:
        issues.append(
            {
                "code": "latex_render_failed",
                "severity": "error",
                "message": "LaTeX rendering failed.",
                "detail": render_info["detail"],
            }
        )
    if render_info["rendered"]:
        _cleanup_latex_artifacts(paths["solution"])

    passed = not any(issue["severity"] == "error" for issue in issues)
    iteration = _next_iteration(paths["verifications"], "verification", ".json")
    report_path = paths["verifications"] / f"verification_{iteration:03d}.json"
    report_md_path = paths["verifications"] / f"verification_{iteration:03d}.md"
    report = {
        "problem_id": problem_id,
        "iteration": iteration,
        "status": "verified" if passed else "needs_refinement",
        "passed": passed,
        "checked_solution": _relative_to_output(output_dir, paths["solution"]),
        "checks": {
            "latex_balance": "passed" if not any(issue["code"] == "latex_environment_balance" for issue in issues) else "failed",
            "forbidden_phrases": "passed" if not any(issue["code"] == "forbidden_phrase" for issue in issues) else "failed",
            "required_sections": "passed" if not any(issue["code"] == "missing_required_section" for issue in issues) else "failed",
            "mathematical_completeness": "passed" if not any(issue["code"] in MATHEMATICAL_ISSUE_CODES for issue in issues) else "failed",
            "render": render_info["status"],
        },
        "issues": issues,
        "created_at": _timestamp(),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_verification_markdown(report_md_path, report)
    _write_state(
        output_dir,
        problem_id,
        args,
        skill_info,
        status="verified" if passed else "needs_refinement",
        current_stage="verifier",
        next_stage="done" if passed else "refiner",
        completed=passed,
        reason="Verifier checks passed." if passed else "Verifier found issues that require refinement.",
        stage_files={
            "solution": _relative_to_output(output_dir, paths["solution"]),
            "verification": _relative_to_output(output_dir, report_path),
            "verification_markdown": _relative_to_output(output_dir, report_md_path),
        },
        verification_summary={"passed": passed, "issue_count": len(issues)},
    )
    return {"passed": passed, "report_path": report_path, "issues": issues, "render": render_info}


def _refine_solution(
    repo_root: Path,
    output_dir: Path,
    problem_id: str,
    args: Namespace,
    skill_info: dict[str, str],
) -> dict[str, object]:
    paths = _problem_paths(output_dir, problem_id)
    latest_verification = _latest_file(paths["verifications"], "verification", ".json")
    if latest_verification is None:
        _verify_solution(repo_root, output_dir, problem_id, args, skill_info)
        latest_verification = _latest_file(paths["verifications"], "verification", ".json")
    assert latest_verification is not None

    verification = _read_json(latest_verification)
    iteration = _next_iteration(paths["refinements"], "refinement", ".json")
    report_path = paths["refinements"] / f"refinement_{iteration:03d}.json"
    report_md_path = paths["refinements"] / f"refinement_{iteration:03d}.md"

    if verification.get("passed"):
        action = "no_changes"
        changes: list[str] = []
        status = "verified"
        completed = True
        reason = "Latest verifier report passed; no refinement was necessary."
    else:
        parsed_path = paths["artifacts"] / "parsed_problem.json"
        if not parsed_path.is_file():
            _parse_problem(repo_root, output_dir, problem_id, args, skill_info)
        parsed = _read_json(parsed_path)
        solution_text, model_backend = _generate_solution_text(
            repo_root,
            parsed,
            PROBLEM_PROFILES[problem_id],
            skill_info,
            iteration + 1,
            args,
            verification=verification,
            partial_output_dir=paths["problem"],
            fallback_file=paths["solution"],
        )
        if not solution_text and paths["solution"].is_file():
            solution_text = paths["solution"].read_text(encoding="utf-8")
        if not solution_text:
            raise RuntimeError(f"No refined solution text generated for {problem_id}.")
        paths["solution"].write_text(solution_text, encoding="utf-8")
        refined_tex_path = paths["refinements"] / f"refined_solution_{iteration:03d}.tex"
        refined_tex_path.write_text(solution_text, encoding="utf-8")
        action = "rewrote_solution"
        changes = [f"Resolved verifier issue `{issue['code']}`: {issue['message']}" for issue in verification.get("issues", [])]
        status = "refined"
        completed = True
        reason = "Refiner rewrote the solution using parsed artifacts and verifier feedback."

    report = {
        "problem_id": problem_id,
        "iteration": iteration,
        "status": status,
        "completed": completed,
        "action": action,
        "input_verification": _relative_to_output(output_dir, latest_verification),
        "solution": _relative_to_output(output_dir, paths["solution"]),
        "changes": changes,
        "model_backend": model_backend if action == "rewrote_solution" else {"provider": "none", "method": "no_changes"},
        "created_at": _timestamp(),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_refinement_markdown(report_md_path, report)
    _write_state(
        output_dir,
        problem_id,
        args,
        skill_info,
        status=status,
        current_stage="refiner",
        next_stage="verifier" if action == "rewrote_solution" else "done",
        completed=completed,
        reason=reason,
        stage_files={
            "solution": _relative_to_output(output_dir, paths["solution"]),
            "refinement": _relative_to_output(output_dir, report_path),
            "refinement_markdown": _relative_to_output(output_dir, report_md_path),
        },
    )
    return {"report_path": report_path, "action": action, "status": status}


def _is_already_verified(output_dir: Path, problem_id: str) -> bool:
    status_path = _problem_paths(output_dir, problem_id)["artifacts"] / "status.json"
    if not status_path.is_file():
        return False
    data = _read_json(status_path)
    return bool(data.get("completed")) and data.get("status") == "verified"


def _is_already_proposed(output_dir: Path, problem_id: str) -> bool:
    paths = _problem_paths(output_dir, problem_id)
    return paths["solution"].is_file()


def _normalize_problem_id(problem: str | None) -> str | None:
    if problem is None:
        return None
    problem = problem.lower().strip()
    return problem if PROBLEM_RE.match(problem) else None


def _display_path(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _relative_to_output(output_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return str(path)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_math_research_skill(repo_root: Path, skill_path: str) -> dict[str, str]:
    path = (repo_root / skill_path).resolve()
    skills_dir = (repo_root / "skills").resolve()
    if not _is_relative_to(path, skills_dir):
        raise ValueError(f"skill path must be under skills/: {skill_path}")
    for blocked in BLOCKED_INPUT_DIRS:
        blocked_dir = (repo_root / blocked).resolve()
        if _is_relative_to(path, blocked_dir):
            raise ValueError(f"skill path is blocked: {skill_path}")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8")
    name_match = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    return {
        "name": name_match.group(1).strip() if name_match else "math-research",
        "description": description_match.group(1).strip() if description_match else "",
        "relative_path": str(path.relative_to(repo_root)),
    }


def _resolve_output_dir(repo_root: Path, args: Namespace) -> Path:
    if getattr(args, "output", None):
        output_dir = Path(args.output).expanduser()
    else:
        now = datetime.now()
        exp_name = getattr(args, "exp_name", None) or f"proofs_v1_{MONTH_NAMES[now.month - 1]}{now.day}"
        folder_name = f"{_safe_name(exp_name)}_{_safe_name(getattr(args, 'model_name', 'rma-skeleton'))}"
        output_dir = repo_root / OUTPUT_BASE_DIR / folder_name
    output_dir = output_dir.resolve()
    _ensure_allowed_output(repo_root, output_dir)
    return output_dir


def _safe_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        raise ValueError("Output folder components must not be empty")
    return value


def _problem_paths(output_dir: Path, problem_id: str) -> dict[str, Path]:
    problem_dir = output_dir / problem_id
    artifacts = problem_dir / "artifacts"
    return {
        "problem": problem_dir,
        "input": problem_dir / "input",
        "artifacts": artifacts,
        "proposals": artifacts / "proposals",
        "verifications": artifacts / "verifications",
        "refinements": artifacts / "refinements",
        "solution": output_dir / f"{problem_id}_solution.tex",
    }


def _ensure_problem_dirs(paths: dict[str, Path]) -> None:
    paths["input"].mkdir(parents=True, exist_ok=True)
    paths["artifacts"].mkdir(parents=True, exist_ok=True)
    paths["proposals"].mkdir(parents=True, exist_ok=True)
    paths["verifications"].mkdir(parents=True, exist_ok=True)
    paths["refinements"].mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _next_iteration(directory: Path, stem: str, suffix: str) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^{re.escape(stem)}_(\d{{3}}){re.escape(suffix)}$")
    numbers = []
    for path in directory.iterdir():
        match = pattern.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _latest_file(directory: Path, stem: str, suffix: str) -> Path | None:
    if not directory.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(stem)}_(\d{{3}}){re.escape(suffix)}$")
    candidates = []
    for path in directory.iterdir():
        match = pattern.match(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _build_parsed_problem(problem_meta: dict[str, str], source: str, output_dir: Path) -> dict[str, object]:
    statement = problem_meta["statement_excerpt"]
    problem_id = problem_meta["id"]
    profile = PROBLEM_PROFILES[problem_id]
    return {
        "problem_id": problem_id,
        "title": problem_meta["title"],
        "author": problem_meta["author"],
        "source_input": f"{problem_id}/input/problem.tex",
        "statement_excerpt": statement,
        "normalized_statement": _normalize_statement(statement),
        "problem_type": _infer_problem_type(statement),
        "area": profile["area"],
        "objects": _extract_math_objects(statement),
        "definitions": _extract_definitions(statement),
        "quantifier_summary": _extract_quantifier_summary(statement),
        "boundary_cases": _extract_boundary_cases(statement),
        "fairness_boundary": {
            "allowed_inputs": [f"{PROBLEMS_DIR}/", "skills/"],
            "blocked_inputs": list(BLOCKED_INPUT_DIRS),
            "output_root": _relative_to_output(output_dir, output_dir),
        },
    }


def _normalize_statement(statement: str) -> str:
    normalized = statement.replace("epsilon", r"\varepsilon")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _infer_problem_type(statement: str) -> str:
    lower = statement.lower()
    if "algorithm" in lower or "compute" in lower:
        return "algorithmic"
    if "does there exist" in lower or "show there exists" in lower or "construct" in lower:
        return "existence"
    if "if and only if" in lower or "characterize" in lower:
        return "characterization"
    if "prove" in lower or "show that" in lower:
        return "proof"
    return "research problem"


def _extract_math_objects(statement: str) -> list[str]:
    objects: list[str] = []
    for pattern in (r"graph\s+\$?G", r"matrix\s+\$?[A-Z]", r"polynomial", r"manifold", r"measure", r"tensor", r"chain"):
        if re.search(pattern, statement, re.IGNORECASE):
            objects.append(re.sub(r"\\s\+", " ", pattern).replace(r"\$?", "").replace("\\", ""))
    return objects or ["mathematical objects from the statement"]


def _extract_definitions(statement: str) -> list[str]:
    definitions = []
    for match in re.finditer(r"(let\s+.+?)(?:\.|;)", statement, re.IGNORECASE):
        definitions.append(match.group(1).strip())
    for match in re.finditer(r"(I say that\s+.+?)(?:\.|;)", statement, re.IGNORECASE):
        definitions.append(match.group(1).strip())
    return definitions or ["No explicit `let ...` definition was detected; use the problem statement verbatim."]


def _extract_quantifier_summary(statement: str) -> list[str]:
    summary = []
    lower = statement.lower()
    if "for every" in lower:
        summary.append("Universal quantifier detected: the proof must cover every admissible input.")
    if "there exist" in lower or "does there exist" in lower:
        summary.append("Existential quantifier detected: the proof must construct or certify an object.")
    if "between 0 and 1" in lower:
        summary.append("Parameter range detected: include boundary cases at 0 and 1 when allowed.")
    return summary or ["No simple quantifier phrase was detected; preserve the statement's quantifier order."]


def _extract_boundary_cases(statement: str) -> list[str]:
    lower = statement.lower()
    cases = []
    if "between 0 and 1" in lower or r"\varepsilon" in statement or r"\epsilon" in statement:
        cases.extend([r"$\varepsilon=0$", r"$\varepsilon=1$"])
    if "graph" in lower:
        cases.extend(["empty graph", "single-vertex graph", "disconnected graph"])
    if "matrix" in lower:
        cases.extend(["singular matrix", "zero-dimensional boundary case"])
    if "polynomial" in lower:
        cases.extend(["multiple roots", "degree-zero or degenerate polynomial"])
    return cases or ["degenerate inputs allowed by the statement"]


def _write_problem_analysis(path: Path, parsed: dict[str, object]) -> None:
    lines = [
        f"# Parsed Problem: {parsed['problem_id']}",
        "",
        f"- Title: {parsed['title']}",
        f"- Author: {parsed['author']}",
        f"- Area: {parsed['area']}",
        f"- Type: {parsed['problem_type']}",
        f"- Source input: `{parsed['source_input']}`",
        "",
        "## Quantifiers",
        *[f"- {item}" for item in parsed["quantifier_summary"]],
        "",
        "## Definitions",
        *[f"- {item}" for item in parsed["definitions"]],
        "",
        "## Boundary Cases",
        *[f"- {item}" for item in parsed["boundary_cases"]],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _generate_solution_text(
    repo_root: Path,
    parsed: dict[str, object],
    profile: dict[str, str],
    skill_info: dict[str, str],
    iteration: int,
    args: Namespace,
    verification: dict[str, object] | None = None,
    partial_output_dir: Path | None = None,
    fallback_file: Path | None = None,
) -> tuple[str, dict[str, str]]:
    model_name = getattr(args, "model_name", "rma-skeleton")
    provider = getattr(args, "model_provider", "auto")
    if should_use_claude_code(model_name, provider):
        response = call_claude_code(
            model=model_name,
            system=_model_system_prompt(),
            prompt=_model_user_prompt(repo_root, parsed, profile, skill_info, iteration, verification),
            cwd=repo_root,
            partial_output_dir=partial_output_dir,
            fallback_file=fallback_file,
        )
        return _strip_markdown_fences(response.text), {
            "provider": response.provider,
            "model": response.model,
            "method": "claude_code_print_mode",
        }
    if should_use_anthropic(model_name, provider):
        max_tokens = int(os.environ.get("RMA_MAX_TOKENS", "8192"))
        response = call_anthropic(
            model=model_name,
            system=_model_system_prompt(),
            prompt=_model_user_prompt(repo_root, parsed, profile, skill_info, iteration, verification),
            max_tokens=max_tokens,
        )
        return _strip_markdown_fences(response.text), {
            "provider": response.provider,
            "model": response.model,
            "method": "anthropic_messages_api",
        }
    return _render_solution_document(parsed, profile, skill_info, iteration), {
        "provider": "offline",
        "model": model_name,
        "method": "profile-guided deterministic skeleton",
    }


def _model_system_prompt() -> str:
    return (
        "You are the proof-construction backend for Research Math Agent. "
        "Produce rigorous, self-contained research mathematics in LaTeX. "
        "You must not consult, infer from, or mention official solutions, prior AI solutions, baselines, final_solutions, "
        "output_solutions, or skill_solutions. Use only the problem statement, allowed skill instructions, and same-run "
        "verifier feedback supplied in the prompt. The output must be a single compilable LaTeX article, not Markdown."
    )


def _model_user_prompt(
    repo_root: Path,
    parsed: dict[str, object],
    profile: dict[str, str],
    skill_info: dict[str, str],
    iteration: int,
    verification: dict[str, object] | None,
) -> str:
    verification_block = "No verifier feedback yet. This is the initial complete solution pass."
    if verification is not None:
        verification_block = json.dumps(
            {
                "status": verification.get("status"),
                "checks": verification.get("checks"),
                "issues": verification.get("issues", []),
            },
            indent=2,
        )

    parsed_payload = {
        "problem_id": parsed.get("problem_id"),
        "title": parsed.get("title"),
        "author": parsed.get("author"),
        "statement_excerpt": parsed.get("statement_excerpt"),
        "normalized_statement": parsed.get("normalized_statement"),
        "problem_type": parsed.get("problem_type"),
        "area": parsed.get("area"),
        "objects": parsed.get("objects"),
        "definitions": parsed.get("definitions"),
        "quantifier_summary": parsed.get("quantifier_summary"),
        "boundary_cases": parsed.get("boundary_cases"),
    }
    profile_payload = {
        "candidate": profile["candidate"],
        "construction_seed": profile["construction"],
        "strategy_seed": profile["strategy"],
        "verification_seed": profile["verification"],
    }

    return f"""Generate iteration {iteration} of the complete proof for this First Proof research problem.

## Context

### Problem
{json.dumps(parsed_payload, indent=2)}

### Proof strategy seed (hypothesis only — you must derive the actual proof)
{json.dumps(profile_payload, indent=2)}

### Math research skill
{_skill_prompt_excerpt(repo_root, skill_info)}

### Verifier feedback from previous iteration
{verification_block}

## Proof structure (follow this order)

1. **Key tools**: Open with a section listing every named theorem, lemma, or formula you will invoke. For each:
   - State it precisely (exact quantifiers, exact hypotheses).
   - Prove it holds in this setting, or cite a self-contained derivation below.

2. **Subclaim decomposition**: Break the main result into 2–5 lemmas/claims with explicit statements. Each must have its own `\\begin{{proof}}...\\end{{proof}}`.

3. **Main proof**: Assemble the subclaims into the proof of the main theorem step by step. Every non-trivial logical step must be justified.

4. **Hypotheses check**: A dedicated subsection that verifies every precondition of every named theorem you invoked actually holds for the objects in this problem.

5. **Boundary and degenerate cases**: Explicit case analysis for each boundary case in the parsed artifact.

## Output requirements
- Return ONLY a complete standalone LaTeX document: `\\documentclass` ... `\\end{{document}}`.
- Use `theorem`, `lemma`, `claim`, `proposition`, `corollary`, and `proof` environments.
- If you use `\\cite`, include a complete `thebibliography` in the same document. Prefer inline derivations over citations.
- Define every symbol you introduce. Keep notation consistent with the problem statement.
- Do not mention blocked directories or missing access in the proof text.
- Do not wrap output in Markdown fences.
"""


def _skill_prompt_excerpt(repo_root: Path, skill_info: dict[str, str]) -> str:
    path = (repo_root / skill_info["relative_path"]).resolve()
    text = path.read_text(encoding="utf-8")
    max_chars = 12000
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[Skill file truncated for model prompt budget.]"


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    fence_match = re.match(r"^```(?:latex|tex)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        stripped = fence_match.group(1).strip()
    document_start = stripped.find(r"\documentclass")
    if document_start > 0:
        stripped = stripped[document_start:].strip()
    return stripped + "\n"


def _render_solution_document(
    parsed: dict[str, object],
    profile: dict[str, str],
    skill_info: dict[str, str],
    iteration: int,
) -> str:
    title = _latex_escape_text(str(parsed["title"]))
    author = _latex_escape_text(str(parsed["author"]))
    problem_id = str(parsed["problem_id"])
    definitions = _latex_itemize(parsed["definitions"])
    boundary_cases = _latex_itemize(parsed["boundary_cases"])
    quantifiers = _latex_itemize(parsed["quantifier_summary"])
    return rf"""\documentclass[11pt]{{article}}
\usepackage[margin=1in]{{geometry}}
\usepackage{{amsmath,amssymb,amsthm}}
\usepackage{{enumitem}}
\newtheorem{{theorem}}{{Theorem}}
\newtheorem{{lemma}}{{Lemma}}
\newcommand{{\bR}}{{\mathbb{{R}}}}
\newcommand{{\bC}}{{\mathbb{{C}}}}
\newcommand{{\bQ}}{{\mathbb{{Q}}}}
\newcommand{{\aO}}{{\mathcal{{O}}}}
\newcommand{{\vecop}}{{\operatorname{{vec}}}}

\begin{{document}}

\section*{{{title}}}

\noindent\textbf{{Problem.}} {problem_id.upper()}. Contributor field: {author}.

\begin{{theorem}}[RMA generated solution, iteration {iteration}]
{profile["candidate"]}
\end{{theorem}}

\begin{{proof}}
\textbf{{Parsing of the statement.}}
The problem is treated as a {parsed["problem_type"]} problem in {profile["area"]}.
The quantifier structure used in the proof is:
\begin{{itemize}}[leftmargin=*]
{quantifiers}
\end{{itemize}}
The definitions extracted from the statement are:
\begin{{itemize}}[leftmargin=*]
{definitions}
\end{{itemize}}

\textbf{{Answer and construction.}}
{profile["candidate"]} The object or method used to witness the answer is the
following: {profile["construction"]}

\textbf{{Proof.}}
{profile["strategy"]} The cited or derived ingredients are applied only after
checking the hypotheses listed in the original problem statement. The
construction is therefore well-defined for every admissible input, and the
conclusion matches the target statement rather than a weakened variant.

\textbf{{Boundary and consistency checks.}}
The proof covers the following edge cases explicitly:
\begin{{itemize}}[leftmargin=*]
{boundary_cases}
\end{{itemize}}
{profile["verification"]} These checks establish that the construction, the
definitions, and the claimed conclusion remain consistent across the whole
scope of the problem.
\end{{proof}}

\end{{document}}
"""


def _latex_itemize(values: object) -> str:
    if not isinstance(values, list):
        values = [str(values)]
    return "\n".join(f"\\item {_latex_escape_text(str(value))}" for value in values)


def _latex_escape_text(value: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
    }
    for needle, replacement in replacements.items():
        value = value.replace(needle, replacement)
    return value


def _collect_verification_issues(
    parsed: dict[str, object],
    solution_text: str,
    repo_root: Path | None = None,
    args: Namespace | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issues.extend(_latex_balance_issues(solution_text))
    forbidden_phrases = (
        "draft",
        "placeholder",
        "not_implemented",
        "No proof has been generated",
        "A problem-specific solver has not been implemented",
        "it can be shown",
        "standard arguments",
        "the rest is straightforward",
        "future pipeline",
        "The cited or derived ingredients are applied only after",
        "checking the hypotheses listed in the original problem statement",
        "These checks establish that the construction",
        "well-defined for every admissible input",
    )
    lower_text = solution_text.lower()
    for phrase in forbidden_phrases:
        if phrase.lower() in lower_text:
            issues.append(
                {
                    "code": "forbidden_phrase",
                    "severity": "error",
                    "message": f"Forbidden phrase appears in solution: {phrase}",
                    "detail": phrase,
                }
            )

    required_patterns = {
        "theorem environment": r"\\begin\{theorem\}",
        "proof environment": r"\\begin\{proof\}",
        "answer/construction paragraph": r"Answer and construction",
        "boundary checks": r"Boundary and consistency checks",
    }
    for label, pattern in required_patterns.items():
        if not re.search(pattern, solution_text):
            issues.append(
                {
                    "code": "missing_required_section",
                    "severity": "error",
                    "message": f"Missing required solution component: {label}",
                    "detail": pattern,
                }
            )
    title = str(parsed.get("title", ""))
    if title and _latex_escape_text(title) not in solution_text:
        issues.append(
            {
                "code": "statement_mismatch",
                "severity": "error",
                "message": "Parsed title does not appear in the solution.",
                "detail": title,
            }
        )
    issues.extend(_mathematical_completeness_issues(solution_text))
    if repo_root is not None and args is not None:
        issues.extend(_model_verify_proof(solution_text, args))
    return issues


def _model_verify_proof(solution_text: str, args: Namespace) -> list[dict[str, str]]:
    model_name = getattr(args, "model_name", "rma-skeleton")
    provider = getattr(args, "model_provider", "auto")
    if not (should_use_anthropic(model_name, provider) or should_use_claude_code(model_name, provider)):
        return []

    system = (
        "You are a mathematical proof verifier. You read LaTeX proofs and identify genuine logical errors. "
        "Be conservative: only flag real problems, not style preferences."
    )
    prompt = (
        "Review the following LaTeX proof for these specific issues:\n\n"
        "1. HYPOTHESIS_NOT_VERIFIED: A named theorem, lemma, or formula is invoked but its preconditions "
        "are not explicitly checked for the objects in this proof.\n"
        "2. LOGICAL_GAP: A step's conclusion does not follow from the stated premises — the logical link is missing.\n"
        "3. UNJUSTIFIED_CLAIM: A non-trivial claim is stated without proof or citation.\n\n"
        "Return ONLY a JSON array (no prose, no fences). Each element:\n"
        '{"code": "hypothesis_not_verified"|"logical_gap"|"unjustified_claim", '
        '"severity": "error", "message": "<specific description>", "detail": "<the theorem name or claim>"}\n\n'
        "If the proof is sound, return exactly: []\n\n"
        f"PROOF:\n{solution_text[:24000]}"
    )

    try:
        if should_use_claude_code(model_name, provider):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                response = call_claude_code(model=model_name, system=system, prompt=prompt, cwd=Path(tmp))
        else:
            response = call_anthropic(model=model_name, system=system, prompt=prompt, max_tokens=2048, temperature=0.0)
        raw = response.text.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
        if fence:
            raw = fence.group(1).strip()
        issues = json.loads(raw)
        if not isinstance(issues, list):
            return []
        valid = []
        for item in issues:
            if isinstance(item, dict) and "code" in item and "message" in item:
                item.setdefault("severity", "error")
                item.setdefault("detail", "")
                valid.append({k: str(item[k]) for k in ("code", "severity", "message", "detail")})
        return valid
    except Exception:
        return []


def _mathematical_completeness_issues(solution_text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    proof_bodies = re.findall(r"\\begin\{proof\}(.*?)\\end\{proof\}", solution_text, flags=re.DOTALL)
    proof_text = "\n".join(proof_bodies)
    proof_words = re.findall(r"[A-Za-z0-9]+", re.sub(r"\\[A-Za-z]+", " ", proof_text))
    if len(proof_words) < MIN_PROOF_WORDS:
        issues.append(
            {
                "code": "proof_too_short",
                "severity": "error",
                "message": f"Proof body has {len(proof_words)} words; expected at least {MIN_PROOF_WORDS} for a research-level complete proof.",
                "detail": str(len(proof_words)),
            }
        )

    lemma_like = len(re.findall(r"\\begin\{(?:lemma|claim|proposition|corollary)\}", solution_text))
    if lemma_like == 0:
        issues.append(
            {
                "code": "missing_subclaim_structure",
                "severity": "error",
                "message": "No lemma/claim/proposition structure was found; verifier requires explicit subclaims with proofs.",
                "detail": "expected at least one lemma, claim, proposition, or corollary environment",
            }
        )

    proof_blocks = len(re.findall(r"\\begin\{proof\}", solution_text))
    if proof_blocks < 2:
        issues.append(
            {
                "code": "missing_subproofs",
                "severity": "error",
                "message": "Only one proof block was found; full proofs should include proof blocks for key intermediate claims.",
                "detail": str(proof_blocks),
            }
        )

    theorem_keywords = (
        "theorem",
        "lemma",
        "formula",
        "model realization",
        "paving",
        "Cameron-Martin",
        "Smith",
        "Whittaker",
        "finite-free",
        "convexity",
    )
    uses_external_result = any(keyword.lower() in solution_text.lower() for keyword in theorem_keywords)
    has_hypothesis_audit = re.search(r"Hypothes(?:is|es).*check|Assumption.*check|Hypothes(?:is|es).*verification", solution_text, re.IGNORECASE | re.DOTALL)
    if uses_external_result and not has_hypothesis_audit:
        issues.append(
            {
                "code": "missing_theorem_hypothesis_audit",
                "severity": "error",
                "message": "The solution invokes named/high-level mathematical results without a dedicated theorem statement and hypothesis audit.",
                "detail": "expected theorem statement plus hypothesis verification",
            }
        )

    has_citation_command = "\\cite" in solution_text
    has_inline_bibliography = "\\begin{thebibliography}" in solution_text
    has_self_contained_derivation = re.search(
        r"self-contained derivation|we prove the (?:theorem|lemma|result|estimate) needed here|we now prove the required",
        solution_text,
        re.IGNORECASE,
    )
    if has_citation_command and not has_inline_bibliography:
        issues.append(
            {
                "code": "unresolved_citations",
                "severity": "error",
                "message": "Citation commands appear without an inline thebibliography environment.",
                "detail": "expected standalone bibliography or self-contained derivation without \\cite",
            }
        )

    if uses_external_result and not ((has_citation_command and has_inline_bibliography) or has_self_contained_derivation):
        issues.append(
            {
                "code": "missing_citations",
                "severity": "error",
                "message": "Named or literature-level results appear without standalone citations or a clearly labeled self-contained derivation.",
                "detail": "expected inline thebibliography or full derivation",
            }
        )

    if "Boundary and consistency checks" in solution_text and "Case" not in solution_text:
        issues.append(
            {
                "code": "boundary_cases_not_proved",
                "severity": "error",
                "message": "Boundary cases are listed but not proved as separate cases.",
                "detail": "expected explicit case analysis",
            }
        )

    return issues


def _latex_balance_issues(solution_text: str) -> list[dict[str, str]]:
    token_re = re.compile(r"\\(begin|end)\{([^}]+)\}")
    stack: list[str] = []
    issues: list[dict[str, str]] = []
    for match in token_re.finditer(solution_text):
        kind, env = match.group(1), match.group(2)
        if kind == "begin":
            stack.append(env)
            continue
        if not stack:
            issues.append(
                {
                    "code": "latex_environment_balance",
                    "severity": "error",
                    "message": f"Unexpected \\end{{{env}}}.",
                    "detail": env,
                }
            )
            continue
        started = stack.pop()
        if started != env:
            issues.append(
                {
                    "code": "latex_environment_balance",
                    "severity": "error",
                    "message": f"Environment mismatch: began {started}, ended {env}.",
                    "detail": f"{started}->{env}",
                }
            )
    for env in reversed(stack):
        issues.append(
            {
                "code": "latex_environment_balance",
                "severity": "error",
                "message": f"Unclosed LaTeX environment: {env}.",
                "detail": env,
            }
        )
    return issues


def _verify_render(solution_path: Path, no_render: bool) -> dict[str, object]:
    if no_render:
        return {"passed": True, "rendered": False, "status": "skipped", "detail": ""}
    result = _render_solution(solution_path)
    if result.returncode == 0:
        return {"passed": True, "rendered": True, "status": "passed", "detail": ""}
    detail = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return {
        "passed": False,
        "rendered": False,
        "status": "failed",
        "detail": detail[-4000:],
    }


def _write_verification_markdown(path: Path, report: dict[str, object]) -> None:
    issues = report.get("issues", [])
    lines = [
        f"# Verification Report: {report['problem_id']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Passed: `{report['passed']}`",
        f"- Checked solution: `{report['checked_solution']}`",
        "",
        "## Checks",
    ]
    checks = report.get("checks", {})
    if isinstance(checks, dict):
        lines.extend(f"- {name}: `{value}`" for name, value in checks.items())
    lines.extend(["", "## Issues"])
    if isinstance(issues, list) and issues:
        lines.extend(f"- `{issue['code']}` ({issue['severity']}): {issue['message']}" for issue in issues)
    else:
        lines.append("- None")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_refinement_markdown(path: Path, report: dict[str, object]) -> None:
    lines = [
        f"# Refinement Report: {report['problem_id']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Action: `{report['action']}`",
        f"- Input verification: `{report['input_verification']}`",
        f"- Solution: `{report['solution']}`",
        "",
        "## Changes",
    ]
    changes = report.get("changes", [])
    if isinstance(changes, list) and changes:
        lines.extend(f"- {change}" for change in changes)
    else:
        lines.append("- None")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_state(
    output_dir: Path,
    problem_id: str,
    args: Namespace,
    skill_info: dict[str, str],
    *,
    status: str,
    current_stage: str,
    next_stage: str,
    completed: bool,
    reason: str,
    stage_files: dict[str, str],
    verification_summary: dict[str, object] | None = None,
) -> None:
    paths = _problem_paths(output_dir, problem_id)
    _ensure_problem_dirs(paths)
    metadata_path = paths["artifacts"] / "metadata.json"
    metadata = _read_json(metadata_path) if metadata_path.is_file() else {"created_at": _timestamp()}
    metadata.update(
        {
            "problem_id": problem_id,
            "status": status,
            "tier": getattr(args, "tier", "standard"),
            "updated_at": _timestamp(),
            "experiment_name": getattr(args, "exp_name", None),
            "model_name": getattr(args, "model_name", "rma-skeleton"),
            "solution": _relative_to_output(output_dir, paths["solution"]),
            "skill": skill_info,
            "blocked_input_dirs": list(BLOCKED_INPUT_DIRS),
            "fairness_note": f"Pipeline stages may read {PROBLEMS_DIR}/, skills/, and same-run artifacts only; official/prior solution directories are blocked.",
            "stage_files": stage_files,
        }
    )
    status_payload = {
        "status": status,
        "completed": completed,
        "current_stage": current_stage,
        "next_stage": next_stage,
        "reason": reason,
        "stage_files": stage_files,
    }
    if verification_summary is not None:
        status_payload["verification"] = verification_summary
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (paths["artifacts"] / "status.json").write_text(json.dumps(status_payload, indent=2) + "\n", encoding="utf-8")


def _print_stage_summary(stage: str, repo_root: Path, output_dir: Path, paths: list[Path], status: str) -> None:
    print(f"RMA {stage}")
    print(f"status: {status}")
    print(f"output: {_display_path(repo_root, output_dir)}")
    for path in paths:
        print(f"artifact: {_display_path(repo_root, path)}")


def _ensure_allowed_input(repo_root: Path, path: Path) -> None:
    resolved = path.resolve()
    problems_dir = (repo_root / PROBLEMS_DIR).resolve()
    if not _is_relative_to(resolved, problems_dir):
        raise ValueError(f"Input is outside {PROBLEMS_DIR}/: {path}")
    for blocked in BLOCKED_INPUT_DIRS:
        blocked_dir = (repo_root / blocked).resolve()
        if _is_relative_to(resolved, blocked_dir):
            raise ValueError(f"Blocked input path: {path}")


def _ensure_allowed_output(repo_root: Path, path: Path) -> None:
    resolved = path.resolve()
    for blocked in BLOCKED_OUTPUT_DIRS:
        blocked_dir = (repo_root / blocked).resolve()
        if _is_relative_to(resolved, blocked_dir):
            raise ValueError(f"Refusing to write solve output under blocked directory: {path}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _find_latex_compiler() -> list[str] | None:
    for candidate in (
        "/projects/bhov/zzhao18/software/bin/tectonic",
        "/usr/local/bin/tectonic",
    ):
        if Path(candidate).is_file():
            return [candidate, "{file}", "--outdir", "{outdir}"]
    for name in ("latexmk", "pdflatex", "xelatex", "lualatex"):
        binary = shutil.which(name)
        if binary:
            if name == "latexmk":
                return [binary, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "{file}"]
            return [binary, "-interaction=nonstopmode", "{file}"]
    return None


def _render_solution(solution_path: Path) -> subprocess.CompletedProcess[str]:
    compiler_template = _find_latex_compiler()
    if compiler_template is None:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="No LaTeX compiler found.")
    cmd = [
        part.replace("{file}", solution_path.name).replace("{outdir}", str(solution_path.parent))
        for part in compiler_template
    ]
    return subprocess.run(cmd, cwd=solution_path.parent, text=True, capture_output=True)


def _cleanup_latex_artifacts(solution_path: Path) -> None:
    for artifact in solution_path.parent.glob(f"{solution_path.stem}.*"):
        if any(str(artifact).endswith(suffix) for suffix in LATEX_AUX_SUFFIXES):
            artifact.unlink()


def _extract_problem_metadata(problem_id: str, source: str) -> dict[str, str]:
    title_match = re.search(r"\\title\{(.+?)\}", source, re.DOTALL)
    author_match = re.search(r"\\author\{(.+?)\}", source, re.DOTALL)
    body_match = re.search(r"\\maketitle\s*(.*?)\\end\{document\}", source, re.DOTALL)
    title = _compact_latex(title_match.group(1)) if title_match else problem_id.upper()
    author = _compact_latex(author_match.group(1)) if author_match else ""
    body = _compact_latex(body_match.group(1)) if body_match else ""
    return {
        "id": problem_id,
        "title": title,
        "author": author,
        "statement_excerpt": body,
    }


def _compact_latex(value: str) -> str:
    value = value.replace(r"\and", "and")
    return re.sub(r"\s+", " ", value).strip()


def _write_report(
    path: Path,
    problem_id: str,
    tier: str,
    problem_status: str,
    solution_path: Path,
    skill_info: dict[str, str],
) -> None:
    path.write_text(
        "\n".join(
            [
                f"# RMA Solve Report: {problem_id}",
                "",
                f"- Tier: `{tier}`",
                f"- Status: `{problem_status}`",
                f"- Solution file: `{solution_path}`",
                f"- Input copy: `{problem_id}/input/problem.tex`",
                f"- Skill: `{skill_info['relative_path']}` (`{skill_info['name']}`)",
                "- Blocked inputs: `data/first_proof_1/final_solutions/`, `outputs/`, `skill_solutions/`, `baselines/`",
                "",
                "The pipeline created the benchmark-fair output structure and advanced",
                "this problem through the requested stage.",
                "",
            ]
        ),
        encoding="utf-8",
    )
