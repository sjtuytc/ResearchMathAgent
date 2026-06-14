"""§1: Pre-checker — NumericalChecker + CitationChecker."""
from __future__ import annotations
import json
import re
import subprocess
import sys
import tempfile
import os
from dataclasses import dataclass, asdict
from ._api import call_api

NUMERICAL_PROMPT = """\
You are a mathematical claim extractor. Read the proof and extract only claims that are
LITERALLY WRITTEN as explicit numbers/polynomials and can be verified with sympy or numpy.

INCLUSION RULE: Only include if a specific formula is literally written AND it is purely
about numbers or polynomials. Every code string MUST assign `result = <value>` where value
is 0 or True if the claim holds.

SKIP: functions, operators, random variables, entropy, convergence, monotonicity,
standard analysis facts (L² density, regularity of measures, contractions, Urysohn, DCT).

INCLUDE examples:
  "(1+x)^2 = 1+2x+x^2" →
    {"tool":"sympy","statement":"...","code":"from sympy import symbols,expand; x=symbols('x'); result=expand((1+x)**2-(1+2*x+x**2))"}
  "det([[1,-1,0],[0,0,1],[1,0,-1]])=-1" →
    {"tool":"sympy","statement":"...","code":"from sympy import Matrix; result=Matrix([[1,-1,0],[0,0,1],[1,0,-1]]).det()+1"}
  "a+b≥2√(ab) for positive a,b" →
    {"tool":"numpy","statement":"...","code":"import numpy as np; result=all(a+b>=2*np.sqrt(a*b) for a,b in [(1,2),(3,4)])"}

Output one JSON per line, or: {"status":"no_claims_found"}

Proof:
PROOF_PLACEHOLDER
"""

CITATION_PROMPT = """\
You are a mathematical citation verifier. Read the proof, extract all authority invocations, and verify named citations using web search.

Types:
  A: Named external reference with explicit claim — "by Lemma 3.2 in [Smith2020]"
  B: Named external reference, broad — "by results of [Hairer2014]"
  C: Named theorem, no citation — "by Cauchy-Schwarz"
  D: Unnamed citation needed — "by a result of Smith" (no key)
  E: Implicit authority asserting a claim without proof or prior reference.
     Examples: "by a standard argument, X holds", "it is well known that X", "by a classical result"
  F: Numbered internal reference (Lemma X.Y) with no corresponding definition in this document.

For Type A and B: use web search to verify the citation.
  - Does the paper exist?
  - Does it contain the claimed lemma/theorem?
  - Do the hypotheses of the cited result match the current proof's setting?
  If the citation is hallucinated, the paper does not exist, the theorem says something different,
  or the hypotheses do not match: add "verified":false and "verification_issue":"..." explaining the problem.
  If the citation checks out: add "verified":true.
  If you cannot find the paper via web search: add "verified":null and "verification_issue":"paper not found".

For Type C (named theorem): verify the standard theorem statement is correct as used.
  If Cauchy-Schwarz or another named theorem is misapplied: add "verified":false.

For Type E, add a boolean field "minor":
  minor=true  — standard graduate-level fact any expert proves in 2-3 lines:
    e.g. regularity of finite Borel measures, density of bounded functions in L²,
    L²-contraction of OU operator, Urysohn's lemma, dominated convergence,
    Fubini's theorem, density arguments, continuity of inner products
  minor=false — non-trivial claim that requires real work, a non-obvious theorem,
    or a result specific to the problem that is simply asserted without proof

DO NOT FLAG as Type E:
  - Introductory phrases before an inline proof ("We begin with...", "We now prove...")
  - Logical transitions from prior results ("Combining these...", "Therefore...", "Hence...")

DO NOT FLAG as Type F:
  - LaTeX cross-references \\ref{...}, \\eqref{...} — these resolve to \\label{...} in doc
  - References by label name rather than number

Output one JSON per line:
  {"type":"A","excerpt":"...","claim":"...","reference":"Smith2020","verified":true}
  {"type":"A","excerpt":"...","claim":"...","reference":"Jones2019","verified":false,"verification_issue":"paper does not contain this lemma"}
  {"type":"E","excerpt":"...","claim":"...","reference":null,"minor":true}
Or: {"status":"no_citations_found"}

Proof:
PROOF_PLACEHOLDER
"""


@dataclass
class NumericalIssue:
    severity: str
    statement: str
    detail: str


@dataclass
class CitationIssue:
    severity: str  # "CRITICAL" or "minor"
    ctype: str
    excerpt: str
    claim: str
    detail: str


def _run_code(code: str, timeout: int = 10) -> tuple[bool, str]:
    """Execute verification code. Returns (passed, error_msg)."""
    wrapper = f"""
import sys
def _check(v):
    if v is None: return False
    if v is True or v == True: return True
    try:
        import sympy
        if v is sympy.true: return True
        v2 = sympy.simplify(v)
        return v2 == 0 or v2 is sympy.true
    except: pass
    try: return float(v) == 0
    except: return False
try:
    result = eval(compile({repr(code)}, "<c>", "eval"))
    sys.exit(0 if _check(result) else 1)
except SyntaxError: pass
except: pass
try:
    ns = {{}}
    exec({repr(code)}, ns)
    result = ns.get("result", None)
    if result is None:
        print("NO_RESULT", file=sys.stderr); sys.exit(1)
    sys.exit(0 if _check(result) else 1)
except AssertionError as ae:
    print(f"ASSERT: {{ae}}", file=sys.stderr); sys.exit(1)
except Exception as ex:
    print(f"ERROR: {{ex}}", file=sys.stderr); sys.exit(2)
"""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(wrapper); fname = f.name
        r = subprocess.run([sys.executable, fname], capture_output=True, text=True, timeout=timeout)
        os.unlink(fname)
        if r.returncode == 0: return True, ""
        return False, r.stderr.strip()[:200]
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        return False, str(e)


def _check_numerical(proof: str, in_loop: bool = False) -> list[NumericalIssue]:
    if in_loop or os.getenv("DISABLE_NUMERICAL_CHECK", "").lower() in ("1", "true", "yes"):
        return []  # skip in-loop for speed, or when explicitly disabled
    # raw = call_api(NUMERICAL_PROMPT.replace("PROOF_PLACEHOLDER", proof), "numerical_check",
    #                reasoning="medium", max_tokens=4_000)
    raw = call_api(NUMERICAL_PROMPT.replace("PROOF_PLACEHOLDER", proof), "numerical_check",
                   reasoning="medium", max_tokens=128000)
    issues = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            claim = json.loads(line)
        except Exception:
            continue
        if claim.get("status") == "no_claims_found":
            continue
        code = claim.get("code", "")
        stmt = claim.get("statement", "")
        tool = claim.get("tool", "")
        if not code or tool not in ("sympy", "numpy"):
            continue
        passed, err = _run_code(code)
        if not passed:
            if "NO_RESULT" in err or "ERROR" in err:
                # Try LLM rewrite
                rewrite_prompt = (
                    f"Rewrite this Python verification code so it assigns `result = <True|0>` "
                    f"if the claim holds. Claim: {stmt}\nFailed code: {code}\nError: {err}\n"
                    f"Output only corrected code."
                )
                # rewritten = call_api(rewrite_prompt, "num_rewrite", reasoning="medium",
                #                      max_tokens=500, max_retries=2)
                rewritten = call_api(rewrite_prompt, "num_rewrite", reasoning="medium",
                                     max_tokens=128000, max_retries=2)
                rewritten = rewritten.strip().strip("`")
                if rewritten and rewritten != code:
                    passed2, err2 = _run_code(rewritten)
                    if passed2:
                        continue
                    issues.append(NumericalIssue("WARNING", stmt, f"Code failed: {err2[:150]}"))
                else:
                    issues.append(NumericalIssue("WARNING", stmt, f"Code execution: {err[:150]}"))
            else:
                issues.append(NumericalIssue("ERROR", stmt, f"Check failed: {err[:150]}"))
    return issues


def _check_citations(proof: str) -> list[CitationIssue]:
    # raw = call_api(CITATION_PROMPT.replace("PROOF_PLACEHOLDER", proof), "citation_check",
    #                reasoning="medium", max_tokens=8_000, web_search=True)
    raw = call_api(CITATION_PROMPT.replace("PROOF_PLACEHOLDER", proof), "citation_check",
                   reasoning="medium", max_tokens=128000, web_search=True)
    issues = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            cit = json.loads(line)
        except Exception:
            continue
        if cit.get("status") == "no_citations_found":
            continue
        ctype = cit.get("type", "?")
        excerpt = cit.get("excerpt", "")
        claim = cit.get("claim", "")
        # Type A/B/C: flag if web search found verification issue
        if ctype in ("A", "B", "C"):
            verified = cit.get("verified")
            if verified is False:
                issue_desc = cit.get("verification_issue", "Citation could not be verified.")
                detail = f"Hallucinated/incorrect citation: {issue_desc}"
                issues.append(CitationIssue("CRITICAL", ctype, excerpt, claim, detail))
            elif verified is None:
                issue_desc = cit.get("verification_issue", "Paper not found via web search.")
                detail = f"Unverifiable citation: {issue_desc}"
                issues.append(CitationIssue("minor", ctype, excerpt, claim, detail))
            # verified=True: no issue
        elif ctype in ("D", "E", "F"):
            detail = {
                "D": "Unnamed citation — specific paper or theorem key missing.",
                "E": "Implicit authority invocation — no theorem or paper named.",
                "F": "Undefined internal reference — not stated or proved in this document.",
            }.get(ctype, "")
            is_minor = ctype == "E" and bool(cit.get("minor", False))
            severity = "minor" if is_minor else "CRITICAL"
            issues.append(CitationIssue(severity, ctype, excerpt, claim, detail))
    return issues


def run_prechecker(proof: str, in_loop: bool = False,
                   return_issues: bool = False):
    """
    Run the pre-checker on a proof.

    in_loop=True: CitationChecker only (fast, for in-loop verification).
    in_loop=False: NumericalChecker + CitationChecker (full, for finalize).

    Returns a formatted pre-check report string to inject into Run_Verify.
    """
    lines = ["# Pre-Verification Report", ""]

    # Numerical
    lines.append("## Numerical Checker")
    if in_loop:
        lines.append("  (skipped in-loop for speed)")
    else:
        num_issues = _check_numerical(proof, in_loop=False)
        errors = [x for x in num_issues if x.severity == "ERROR"]
        warnings = [x for x in num_issues if x.severity == "WARNING"]
        if errors:
            lines.append(f"  **{len(errors)} ERROR(S):**")
            for x in errors:
                lines.append(f"  - {x.statement[:100]} → {x.detail}")
        if warnings:
            lines.append(f"  {len(warnings)} WARNING(S): {', '.join(x.statement[:60] for x in warnings[:3])}")
        if not num_issues:
            lines.append("  (none found)")

    # Citation
    lines.append("\n## Citation Checker")
    cit_issues = _check_citations(proof)
    criticals = [x for x in cit_issues if x.severity == "CRITICAL"]
    minors = [x for x in cit_issues if x.severity == "minor"]
    if criticals:
        lines.append(f"  **{len(criticals)} CRITICAL:**")
        for x in criticals:
            tag = {
                "A": "Type A (hallucinated/wrong citation)",
                "B": "Type B (hallucinated/wrong citation)",
                "C": "Type C (misapplied theorem)",
                "E": "Type E (implicit)",
                "F": "Type F (undefined ref)",
                "D": "Type D (unnamed)",
            }.get(x.ctype, x.ctype)
            lines.append(f"  - [{tag}] \"{x.excerpt[:80]}\"")
            lines.append(f"    Claim: {x.claim[:80]}")
            lines.append(f"    → {x.detail}")
    if minors:
        lines.append(f"  {len(minors)} minor (standard facts, cite or leave):")
        for x in minors:
            lines.append(f"  - [Type E minor] \"{x.excerpt[:80]}\"")
    if not criticals and not minors:
        lines.append("  (none flagged)")

    report = "\n".join(lines)
    if return_issues:
        # Return (report, flat list of issue dicts for annotation)
        all_issues = []
        if not in_loop:
            for x in (num_issues if not in_loop else []):
                all_issues.append({"severity": x.severity, "statement": x.statement,
                                    "detail": x.detail, "excerpt": x.statement})
        for x in cit_issues:
            all_issues.append({"severity": x.severity, "ctype": x.ctype,
                                "excerpt": x.excerpt, "claim": x.claim,
                                "detail": x.detail})
        return report, all_issues
    return report
