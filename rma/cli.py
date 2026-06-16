from __future__ import annotations

import argparse
from collections.abc import Sequence

from .doctor import run_doctor
from .solve import run_diff, run_parse, run_propose, run_refine, run_solve, run_verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rma",
        description="Research Math Agent command-line tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check whether the local repository is ready for RMA development.",
    )
    doctor.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to inspect. Defaults to the current directory or its parents.",
    )
    doctor.set_defaults(func=run_doctor)

    parse = subparsers.add_parser(
        "parse",
        help="Parse one or all First Proof problem statements into structured run artifacts.",
    )
    _add_pipeline_arguments(parse, render=False, max_rounds=False)
    parse.set_defaults(func=run_parse)

    propose = subparsers.add_parser(
        "propose",
        help="Generate complete initial solution proposals from parsed problem artifacts.",
    )
    _add_pipeline_arguments(propose, render=False, max_rounds=False)
    propose.set_defaults(func=run_propose)

    verify = subparsers.add_parser(
        "verify",
        help="Run verifier checks on proposed/current solution artifacts.",
    )
    _add_pipeline_arguments(verify, render=True, max_rounds=False)
    verify.set_defaults(func=run_verify)

    refine = subparsers.add_parser(
        "refine",
        help="Apply verifier feedback to the current solution artifact.",
    )
    _add_pipeline_arguments(refine, render=False, max_rounds=False)
    refine.set_defaults(func=run_refine)

    solve = subparsers.add_parser(
        "solve",
        help="Run parser -> proposer -> verifier/refiner pipeline for one or all First Proof problems.",
    )
    _add_pipeline_arguments(solve, render=True, max_rounds=True)
    solve.add_argument(
        "--resume",
        action="store_true",
        help="Skip problems that are already marked verified in the output folder.",
    )
    solve.add_argument(
        "--fast",
        action="store_true",
        help="Skip verify and refine stages — only parse and propose. Useful for quick first-pass proof generation.",
    )
    solve.set_defaults(func=run_solve)

    diff = subparsers.add_parser(
        "diff",
        help="Compare verification results between two experiment output folders.",
    )
    diff_target = diff.add_mutually_exclusive_group(required=True)
    diff_target.add_argument("--exp-a", default=None, help="First experiment name (under outputs/first_proof_1/).")
    diff_target.add_argument("--output-a", default=None, help="Absolute path to first experiment folder.")
    diff_b = diff.add_mutually_exclusive_group(required=True)
    diff_b.add_argument("--exp-b", default=None, help="Second experiment name (under outputs/first_proof_1/).")
    diff_b.add_argument("--output-b", default=None, help="Absolute path to second experiment folder.")
    diff.add_argument("--repo-root", default=None)
    diff.set_defaults(func=run_diff)

    return parser


def _add_pipeline_arguments(parser: argparse.ArgumentParser, *, render: bool, max_rounds: bool) -> None:
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "problem",
        nargs="?",
        help="Problem id, e.g. q6.",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="Run this stage for all q1 through q10 problems.",
    )
    parser.add_argument(
        "--tier",
        choices=("budget", "standard", "pro"),
        default="standard",
        help="Execution profile to record for the run.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output experiment directory. Defaults to outputs/first_proof_1/<exp-name>_<model-name>.",
    )
    parser.add_argument(
        "--exp-name",
        default=None,
        help="Experiment name for the output subfolder. Defaults to proofs_v1_<month><day>.",
    )
    parser.add_argument(
        "--model-name",
        default="rma-skeleton",
        help="Model name for generation and the output subfolder.",
    )
    parser.add_argument(
        "--model-provider",
        choices=("auto", "offline", "anthropic", "claude-code"),
        default="auto",
        help="Generation backend. auto uses offline for rma-skeleton, Anthropic API for claude-* models, and Claude Code for claude-code.",
    )
    if render:
        parser.add_argument(
            "--no-render",
            action="store_true",
            help="Skip rendering qN_solution.tex to PDF during verification.",
        )
    else:
        parser.set_defaults(no_render=True)
    if max_rounds:
        parser.add_argument(
            "--max-rounds",
            type=int,
            default=3,
            help="Maximum verifier/refiner rounds per problem.",
        )
    parser.add_argument(
        "--skill-path",
        default="skills/math-research/SKILL.md",
        help="Math research skill instructions to load for this pipeline stage.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to inspect. Defaults to the current directory or its parents.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
