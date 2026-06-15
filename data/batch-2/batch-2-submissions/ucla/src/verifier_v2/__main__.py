"""CLI: python -m verifier_v2 proof.tex [--problem p.txt] [--output-dir ./out] [--reasoning xhigh]"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Verify a proof (verifier_v2)")
    parser.add_argument("proof", help="Path to proof file (.tex)")
    parser.add_argument("--problem", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--output-name", default=None)
    parser.add_argument("--reasoning", default="high", choices=["medium","high","xhigh"])
    parser.add_argument("--precheck-only", action="store_true",
                        help="Run pre-checker only and annotate tex; skip main verifier")
    args = parser.parse_args()

    proof_path = Path(args.proof)
    proof_text = proof_path.read_text()
    problem_text = Path(args.problem).read_text() if args.problem else "(problem not provided)"

    from verifier_v2.prechecker import run_prechecker
    from verifier_v2.scorer import run_verify, ACCEPT_THRESHOLD
    from verifier_v2.annotator import generate_prechecked_tex, generate_verified_tex
    from verifier_v2._api import get_total_cost, save_cost_log

    print(f"[verifier_v2] proof: {proof_path.name} ({len(proof_text)} chars)")
    print(f"[verifier_v2] reasoning: {args.reasoning}")

    print("[verifier_v2] running pre-checker...")
    precheck_report, precheck_issues = run_prechecker(proof_text, in_loop=False,
                                                       return_issues=True)
    print("[verifier_v2] pre-check done")
    print(precheck_report)

    if args.precheck_only:
        total_cost = get_total_cost()
        print(f"\n[verifier_v2] total cost: ${total_cost:.4f}")
        if args.output_dir and proof_path.suffix == ".tex":
            out_dir = Path(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            base = args.output_name or proof_path.stem
            prechecked_tex = generate_prechecked_tex(proof_text, precheck_issues)
            (out_dir / f"{base}_prechecked.tex").write_text(prechecked_tex)
            print(f"[verifier_v2] → {out_dir}/{base}_prechecked.tex")
            cost_path = out_dir / f"{base}_cost.jsonl"
            save_cost_log(cost_path)
            print(f"[verifier_v2] cost log → {cost_path}")
        return

    print(f"[verifier_v2] running main verifier ({args.reasoning})...")
    score, major_gaps, minor_gaps, raw = run_verify(
        solution=proof_text, problem=problem_text,
        precheck_report=precheck_report, reasoning=args.reasoning)

    verdict = "VERIFIED" if score >= ACCEPT_THRESHOLD else "NOT VERIFIED"
    print(f"\n{'='*60}")
    print(f"SCORE: {score}/10  (threshold: {ACCEPT_THRESHOLD}/10)")
    print(f"VERDICT: {verdict}")
    if major_gaps:
        print("\nMAJOR GAPS:")
        for g in major_gaps: print(f"  - {g[:200]}")
    if minor_gaps:
        print("\nMINOR GAPS:")
        for g in minor_gaps: print(f"  - {g[:200]}")
    print('='*60)

    total_cost = get_total_cost()
    print(f"\n[verifier_v2] total cost: ${total_cost:.4f}")

    if args.output_dir and proof_path.suffix == ".tex":
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = args.output_name or proof_path.stem

        prechecked_tex = generate_prechecked_tex(proof_text, precheck_issues)
        verified_tex = generate_verified_tex(proof_text, precheck_issues,
                                              score, major_gaps, minor_gaps)
        (out_dir / f"{base}_prechecked.tex").write_text(prechecked_tex)
        (out_dir / f"{base}_verified.tex").write_text(verified_tex)
        print(f"[verifier_v2] → {out_dir}/{base}_prechecked.tex")
        print(f"[verifier_v2] → {out_dir}/{base}_verified.tex")

        cost_path = out_dir / f"{base}_cost.jsonl"
        save_cost_log(cost_path)
        print(f"[verifier_v2] cost log → {cost_path}")

if __name__ == "__main__":
    main()
