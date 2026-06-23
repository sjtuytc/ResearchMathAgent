"""Comprehensive per-problem (and system) context reports.

Assembles everything the system has produced for a problem into a single clean,
readable markdown document: problem statement, best proof status, remaining and
resolved issues, meeting results (action plans + discussion highlights),
insights, and strategy/attempt history.

This replaces the old Documents tab, which exposed raw auto-generated .tex
fragments (overview.tex / progress.tex / timeline.tex / strategies.tex) in a
file tree — unreadable and redundant. Reports are rendered as markdown in the
UI and can be compiled to a focused PDF via the issue_pdf tectonic pipeline.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ── problem id helpers ────────────────────────────────────────────────────────

def problem_ids(dataset: str) -> list[str]:
    if dataset == "first_proof_2":
        return [f"prob-{i:02d}" for i in range(1, 11)]
    return [f"q{i}" for i in range(1, 11)]


# ── data-source accessors (lazy imports to avoid cycles) ──────────────────────

def _profile(pid: str) -> dict:
    try:
        from .rich_documents import PROFILES
        return PROFILES.get(pid, {})
    except Exception:
        return {}


def _problem_statement(repo_root: Path, pid: str, dataset: str) -> str:
    """Return the cleaned problem statement body (LaTeX kept for MathJax)."""
    tex = repo_root / "problems" / f"{pid}.tex"
    raw = ""
    if tex.is_file():
        raw = tex.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            from .dataset_store import get_problem as ds_get
            full = ds_get(dataset, pid) or {}
            raw = full.get("statement") or full.get("tex") or ""
        except Exception:
            raw = ""
    if not raw:
        return ""
    m = re.search(r"\\begin\{document\}([\s\S]*?)\\end\{document\}", raw)
    body = m.group(1) if m else raw
    body = re.sub(r"\\(maketitle|title\{[^}]*\}|author\{[^}]*\}|date\{[^}]*\}|input\{[^}]*\})", "", body)
    return body.strip()


def _issues(repo_root: Path, pid: str, dataset: str) -> list[dict]:
    try:
        from .issues import list_issues
        return list_issues(repo_root, pid, dataset)
    except Exception:
        return []


def _best_proof(pid: str, dataset: str) -> dict | None:
    try:
        from .proofs import get_best_proof
        return get_best_proof(pid, dataset)
    except Exception:
        return None


def _meetings(repo_root: Path, pid: str) -> list[dict]:
    try:
        from .meet import list_rooms
        from .meet_pdf import room_is_substantive
        return [r for r in list_rooms(repo_root, pid) if room_is_substantive(r)]
    except Exception:
        return []


def _question_insight(repo_root: Path, pid: str, dataset: str) -> dict | None:
    try:
        from .insights import get_question_insight
        return get_question_insight(repo_root, pid, dataset)
    except Exception:
        return None


def _concepts(repo_root: Path, pid: str) -> list[dict]:
    try:
        from .concepts import load_concepts
        return load_concepts(repo_root, pid) or []
    except Exception:
        return []


def _proof_eval(repo_root: Path, pid: str) -> dict | None:
    try:
        from .proof_eval import load_proof_eval
        return load_proof_eval(repo_root, pid)
    except Exception:
        return None


def _attempts(repo_root: Path, pid: str) -> list[dict]:
    mem = repo_root / "documents" / "strategy_memory.jsonl"
    if not mem.is_file():
        return []
    out = []
    for line in mem.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("problem_id") == pid:
            out.append(e)
    return out


# ── formatting helpers ────────────────────────────────────────────────────────

def _latest_analysis(issue: dict, limit: int = 420) -> str:
    """Most recent substantive agent comment on an issue."""
    best = ""
    for c in issue.get("comments", []):
        if c.get("role") == "event":
            continue
        author = c.get("author", "")
        body = (c.get("body") or "").strip()
        if author in ("critic-agent", "solver-agent", "verifier-agent") and len(body) > 60:
            best = body
    if not best:
        # fall back to any substantive non-event comment
        for c in issue.get("comments", []):
            if c.get("role") != "event" and len((c.get("body") or "").strip()) > 60:
                best = c["body"].strip()
    best = re.sub(r"\n{3,}", "\n\n", best)
    if len(best) > limit:
        best = best[:limit].rsplit(" ", 1)[0] + "…"
    return best


def _status_label(pid: str, issues: list[dict], best: dict | None) -> tuple[str, str]:
    """Return (emoji, label)."""
    open_n = sum(1 for i in issues if i.get("status") in ("open", "in_progress"))
    verified = bool(best and best.get("verification_passed"))
    has_proof = bool(best and best.get("has_solution"))
    if verified and open_n == 0:
        return "✅", "Verified"
    if has_proof and open_n == 0:
        return "🟡", "Proof drafted, no open issues"
    if has_proof:
        return "🟠", f"Proof drafted, {open_n} open issue(s)"
    return "🔴", "No proof yet"


def _highlights(room: dict, n: int = 3) -> list[str]:
    """First-sentence highlights from substantive discussion messages."""
    out = []
    for m in room.get("messages", []):
        if m.get("role") == "event":
            continue
        body = (m.get("body") or "").strip()
        if len(body) < 40:
            continue
        author = m.get("author", "")
        sent = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0]
        if len(sent) > 240:
            sent = sent[:240].rsplit(" ", 1)[0] + "…"
        out.append(f"**{author}:** {sent}")
        if len(out) >= n:
            break
    return out


# ── per-problem report ────────────────────────────────────────────────────────

_PROOF_MARKER = "RMAFULLPROOFBODYMARKER"  # replaced with the raw proof LaTeX in the PDF



def _issue_thread_md(issue: dict) -> str:
    """Full markdown for one issue: title, body, and every (non-event) comment."""
    sev = {"open": "🔴", "in_progress": "🟡", "resolved": "✅"}.get(issue.get("status", ""), "⚪")
    out = [f"### {sev} {issue.get('title', issue['id'])}"]
    labels = ", ".join(issue.get("labels", []))
    out.append(f"`{issue['id']}`  ·  status: {issue.get('status', '?')}" + (f"  ·  {labels}" if labels else ""))
    body = (issue.get("body") or "").strip()
    if body:
        out += ["", body]
    for c in issue.get("comments", []):
        if c.get("role") == "event":
            continue
        b = (c.get("body") or "").strip()
        if not b:
            continue
        ts = (c.get("created_at") or "")[:16].replace("T", " ")
        out += ["", f"**{c.get('author', '?')}** ({ts}):", "", b]
    out.append("")
    return "\n".join(out)


def _meeting_full_md(room: dict) -> str:
    """Full markdown for one meeting: plan + complete discussion transcript."""
    out = [f"### {room.get('topic', room.get('id', ''))}"]
    out.append(f"_{(room.get('created_at') or '')[:10]}  ·  {', '.join(room.get('participants', []))}_")
    plan = room.get("plan") or {}
    if plan.get("summary"):
        out += ["", f"**Action plan.** {plan['summary']}"]
    for st in plan.get("steps", []):
        agent = st.get("agent", "")
        out.append(f"- **{st.get('title', 'Step')}**" + (f" _({agent})_" if agent else "") + f": {st.get('body', '')}")
    msgs = [m for m in room.get("messages", []) if m.get("role") != "event" and (m.get("body") or "").strip()]
    if msgs:
        out += ["", "**Discussion transcript:**"]
        for m in msgs:
            out += ["", f"**{m.get('author', '?')}:** {(m.get('body') or '').strip()}"]
    out.append("")
    return "\n".join(out)


def _full_proof_latex(repo_root: Path, pid: str, dataset: str) -> str:
    """Raw LaTeX body of the consolidated proof (preamble + file-includes stripped)."""
    best = _best_proof(pid, dataset)
    sol = ((best or {}).get("solution_tex") or "").strip()
    if not sol:
        return r"\textit{No consolidated proof yet.}"
    m = re.search(r"\\begin\{document\}([\s\S]*?)\\end\{document\}", sol)
    body = m.group(1) if m else sol
    body = re.sub(r"\\(maketitle|tableofcontents)\b", "", body)
    body = re.sub(r"\\(title|author|date)\{[^}]*\}", "", body)
    body = re.sub(r"\\(input|include|bibliography|bibliographystyle)\{[^}]*\}", "", body)
    return body.strip() or r"\textit{(empty proof)}"


def build_problem_report(repo_root: Path, pid: str, dataset: str = "first_proof_1", full: bool = False) -> dict:
    prof = _profile(pid)
    issues = _issues(repo_root, pid, dataset)
    best = _best_proof(pid, dataset)
    meetings = _meetings(repo_root, pid)
    qinsight = _question_insight(repo_root, pid, dataset)
    attempts = _attempts(repo_root, pid)
    proof_eval = _proof_eval(repo_root, pid)
    concepts = _concepts(repo_root, pid)

    open_issues = [i for i in issues if i.get("status") in ("open", "in_progress")]
    resolved_issues = [i for i in issues if i.get("status") == "resolved"]
    emoji, status = _status_label(pid, issues, best)

    title = prof.get("title", pid.upper())
    L: list[str] = []
    L.append(f"# {title}")
    meta = []
    if prof.get("area"):
        meta.append(prof["area"])
    if prof.get("author"):
        meta.append(prof["author"])
    if meta:
        L.append("  ·  ".join(meta))
    L.append("")
    L.append(f"**Status:** {emoji} {status}  ·  "
             f"**Issues:** {len(open_issues)} open / {len(resolved_issues)} resolved  ·  "
             f"**Meetings:** {len(meetings)}  ·  **Attempts:** {len(attempts)}")
    L.append("")
    L.append("---")

    # 1. Candidate answer + approach
    if prof.get("candidate"):
        L.append("## Candidate Answer")
        L.append(prof["candidate"])
        L.append("")
    if prof.get("strategy"):
        L.append("## Core Approach")
        L.append(prof["strategy"])
        L.append("")

    # 2. Problem statement
    stmt = _problem_statement(repo_root, pid, dataset)
    if stmt:
        L.append("## Problem Statement")
        L.append(stmt[:4000])
        L.append("")

    # 3. Best proof
    L.append("## Best Proof")
    if best and best.get("has_solution"):
        v = "✅ verified" if best.get("verification_passed") else "⚠️ not yet verified"
        ic = best.get("issue_count", 100)
        ic_txt = "" if (isinstance(ic, int) and ic >= 100) else f"  ·  {ic} verifier issue(s)"
        model = best.get("model", "—")
        when = (best.get("updated_at") or best.get("created_at") or "")[:10]
        L.append(f"{v}{ic_txt}  ·  model: `{model}`  ·  {when}")
        L.append("")
        sol = (best.get("solution_tex") or "").strip()
        L.append("")
        if full and sol:
            L.append("### Full Proof")
            L.append("")
            L.append("_The complete proof is included on the following pages._")
        elif sol:
            excerpt = _proof_excerpt(sol, max_chars=1600)
            if excerpt:
                L.append("**Proof (opening excerpt):**")
                L.append("")
                L.append(excerpt)
    else:
        L.append("_No consolidated proof yet. Run a solve + Consolidate in the Proofs tab._")
    L.append("")

    # 4. Remaining (open) issues
    L.append(f"## Remaining Issues ({len(open_issues)})")
    if open_issues:
        for i in open_issues:
            if full:
                L.append(_issue_thread_md(i))
            else:
                sev = {"open": "🔴", "in_progress": "🟡"}.get(i.get("status", ""), "⚪")
                labels = ", ".join(i.get("labels", []))
                L.append(f"### {sev} {i.get('title', i['id'])}")
                L.append(f"`{i['id']}`" + (f"  ·  {labels}" if labels else ""))
                analysis = _latest_analysis(i)
                if analysis:
                    L.append("")
                    L.append(f"> {analysis}")
                L.append("")
    else:
        L.append("_None — all issues resolved._")
        L.append("")

    # 5. Resolved issues (compact)
    if resolved_issues:
        L.append(f"## Resolved Issues ({len(resolved_issues)})")
        if full:
            for i in resolved_issues:
                L.append(_issue_thread_md(i))
        else:
            for i in resolved_issues:
                L.append(f"- ✅ {i.get('title', i['id'])}  ·  `{i['id']}`")
        L.append("")

    # 6. Meeting results
    L.append(f"## Meeting Results ({len(meetings)})")
    if meetings and full:
        for room in meetings:
            L.append(_meeting_full_md(room))
    elif meetings:
        for room in meetings:
            topic = room.get("topic", room.get("id", ""))
            when = (room.get("created_at") or "")[:10]
            parts = ", ".join(room.get("participants", []))
            L.append(f"### {topic}")
            L.append(f"_{when}  ·  {parts}_")
            plan = room.get("plan") or {}
            if plan.get("summary"):
                L.append("")
                L.append(f"**Action plan.** {plan['summary']}")
            steps = plan.get("steps", [])
            if steps:
                for s in steps:
                    agent = s.get("agent", "")
                    tag = f" _({agent})_" if agent else ""
                    L.append(f"- **{s.get('title', 'Step')}**{tag}: {s.get('body', '')[:240]}")
            hl = _highlights(room)
            if hl:
                L.append("")
                L.append("**Discussion highlights:**")
                for h in hl:
                    L.append(f"- {h}")
            L.append("")
    else:
        L.append("_No substantive meetings recorded yet._")
        L.append("")

    # 7. Insights
    L.append("## Insights & Lessons")
    wrote_insight = False
    if qinsight:
        if qinsight.get("summary"):
            L.append(qinsight["summary"]); L.append(""); wrote_insight = True
        for key, head in (("highlights", "Highlights"), ("mistakes", "Mistakes & lessons")):
            vals = qinsight.get(key) or []
            if vals:
                L.append(f"**{head}:**")
                for v in vals[:6]:
                    L.append(f"- {v}")
                L.append("")
                wrote_insight = True
    if not wrote_insight:
        L.append("_No problem-specific insight generated yet._")
        L.append("")

    # 8. Strategy / attempt history (compact)
    if prof.get("difficulty") or attempts:
        L.append("## Strategy & Difficulty")
        if prof.get("difficulty"):
            L.append(prof["difficulty"])
            L.append("")
        if attempts:
            outcomes = {}
            for a in attempts:
                outcomes[a.get("outcome", "?")] = outcomes.get(a.get("outcome", "?"), 0) + 1
            summary = ", ".join(f"{k}: {v}" for k, v in sorted(outcomes.items()))
            L.append(f"**Attempt history:** {len(attempts)} recorded ({summary}).")
            L.append("")

    # 9. Proof evaluation (4-dimension rubric)
    L.append("## Proof Evaluation")
    if proof_eval and "error" not in proof_eval:
        aa  = proof_eval.get("answer_accuracy", None)
        lc  = proof_eval.get("logical_correctness", None)
        pc  = proof_eval.get("proof_completeness", None)
        cl  = proof_eval.get("proof_clarity", None)
        verdict = proof_eval.get("verdict", "")
        notes   = proof_eval.get("notes", "")
        score_rows = []
        if aa is not None:
            score_rows.append(f"**Answer Accuracy:** {'✅ Correct (1/1)' if aa else '❌ Incorrect (0/1)'}")
        for val, label, mx in ((lc, "Logical Correctness", 5), (pc, "Proof Completeness", 5), (cl, "Proof Clarity", 5)):
            if val is not None:
                bar = "█" * val + "░" * (mx - val)
                score_rows.append(f"**{label}:** {bar}  {val}/{mx}")
        if score_rows:
            L.extend(score_rows)
            L.append("")
        if verdict:
            L.append(f"**Verdict:** {verdict}")
            L.append("")
        if notes:
            L.append(f"**Analysis:** {notes}")
            L.append("")
    else:
        L.append("_No proof evaluation recorded yet. Run evaluation in the Evaluation tab._")
        L.append("")

    # 10. Key concepts (names + notation only — full definitions live in the Concept PDF)
    if concepts:
        core = [c for c in concepts if c.get("category") == "core"]
        bg   = [c for c in concepts if c.get("category") != "core"]
        L.append("## Key Concepts")
        L.append(f"_{len(concepts)} concepts extracted — see the Concept PDF (Documents tab) for full definitions._")
        L.append("")
        L.append("**Core concepts:**")
        for c in core[:8]:
            name = c.get("name", "")
            nota = c.get("notation", "")
            nota_str = f" — ${nota}$" if nota else ""
            L.append(f"- **{name}**{nota_str}")
        if bg:
            L.append("")
            L.append("**Background / supporting concepts:**")
            for c in bg[:6]:
                name = c.get("name", "")
                nota = c.get("notation", "")
                nota_str = f" — ${nota}$" if nota else ""
                L.append(f"- {name}{nota_str}")
        L.append("")

    L.append("---")
    L.append(f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
             f"from live run data (issues, proofs, meetings, insights, concepts).*")

    return {
        "scope": pid,
        "title": title,
        "status": status,
        "status_emoji": emoji,
        "counts": {
            "open_issues": len(open_issues),
            "resolved_issues": len(resolved_issues),
            "meetings": len(meetings),
            "attempts": len(attempts),
            "has_proof": bool(best and best.get("has_solution")),
        },
        "markdown": "\n".join(L),
    }


def _proof_excerpt(sol_tex: str, max_chars: int = 700) -> str:
    """Extract a readable opening from a proof .tex (skip preamble).

    Truncation can cut mid-command (e.g. inside ``\\emph{...}``) or mid-math,
    leaving unbalanced braces/``$`` that abort the report compile, so we repair
    the excerpt afterwards.
    """
    m = re.search(r"\\begin\{document\}([\s\S]*?)\\end\{document\}", sol_tex)
    body = m.group(1) if m else sol_tex
    body = re.sub(r"\\(maketitle|title\{[^}]*\}|author\{[^}]*\}|date\{[^}]*\}|tableofcontents)", "", body)
    body = body.strip()
    if len(body) > max_chars:
        body = body[:max_chars].rsplit(" ", 1)[0]
        body = _balance_tex(body) + " …"
    return body


def _balance_tex(s: str) -> str:
    """Make a truncated LaTeX snippet self-consistent: drop a dangling trailing
    control word, close unbalanced ``$`` math, and append missing ``}``."""
    s = re.sub(r"\\[a-zA-Z]*$", "", s)      # dangling partial command at the end
    if s.count("$") % 2:                     # unclosed inline math
        s += "$"
    opens = s.count("{") - s.count("}")      # unbalanced groups
    if opens > 0:
        s += "}" * opens
    return s


# ── system-level report ───────────────────────────────────────────────────────

def build_system_report(repo_root: Path, dataset: str = "first_proof_1") -> dict:
    pids = problem_ids(dataset)
    L: list[str] = []
    L.append("# System Overview — Comprehensive Report")
    L.append(f"_{dataset}  ·  generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    L.append("")
    L.append("---")

    # Per-problem dashboard
    rows = []
    tot_open = tot_resolved = tot_meet = tot_proof = 0
    for pid in pids:
        issues = _issues(repo_root, pid, dataset)
        best = _best_proof(pid, dataset)
        meetings = _meetings(repo_root, pid)
        open_n = sum(1 for i in issues if i.get("status") in ("open", "in_progress"))
        res_n = sum(1 for i in issues if i.get("status") == "resolved")
        emoji, status = _status_label(pid, issues, best)
        tot_open += open_n
        tot_resolved += res_n
        tot_meet += len(meetings)
        tot_proof += 1 if (best and best.get("has_solution")) else 0
        prof = _profile(pid)
        short = prof.get("area", "")[:32]
        rows.append(f"| {emoji} `{pid}` | {short} | {status} | {open_n} | {res_n} | {len(meetings)} |")

    L.append("## Problem Dashboard")
    L.append("")
    L.append(f"**Totals:** {tot_proof}/{len(pids)} with proofs  ·  "
             f"{tot_open} open issues  ·  {tot_resolved} resolved  ·  {tot_meet} meetings")
    L.append("")
    L.append("| Problem | Area | Status | Open | Resolved | Meetings |")
    L.append("|---------|------|--------|------|----------|----------|")
    L.extend(rows)
    L.append("")

    # System insight
    try:
        from .insights import get_system_insight
        sysi = get_system_insight(repo_root)
    except Exception:
        sysi = None
    if sysi:
        L.append("---")
        L.append("## System Insights")
        if sysi.get("summary"):
            L.append(sysi["summary"]); L.append("")
        for key, head in (("highlights", "Highlights"),
                          ("problems", "Systemic problems"),
                          ("mistakes", "Mistakes & lessons")):
            vals = sysi.get(key) or []
            if vals:
                L.append(f"### {head}")
                for v in vals[:8]:
                    L.append(f"- {v}")
                L.append("")
        todos = sysi.get("suggested_todos") or []
        if todos:
            L.append("### Suggested To-Dos")
            for t in todos[:8]:
                if isinstance(t, dict):
                    L.append(f"- **{t.get('title', '')}** {t.get('detail', t.get('body', ''))}".rstrip())
                else:
                    L.append(f"- {t}")
            L.append("")
        vr = sysi.get("verification_report")
        if isinstance(vr, dict) and vr.get("verdict_summary"):
            L.append("### External Verification")
            L.append(f"_{vr.get('date', '')}_ — {vr['verdict_summary']}")
            L.append("")

    L.append("---")
    L.append("*Each problem above has its own comprehensive report — select it on the left.*")

    return {
        "scope": "system",
        "title": "System Overview",
        "counts": {
            "problems": len(pids),
            "with_proofs": tot_proof,
            "open_issues": tot_open,
            "resolved_issues": tot_resolved,
            "meetings": tot_meet,
        },
        "markdown": "\n".join(L),
    }


def build_report(repo_root: Path, scope: str, dataset: str = "first_proof_1", full: bool = False) -> dict:
    if scope == "system":
        return build_system_report(repo_root, dataset)
    return build_problem_report(repo_root, scope, dataset, full=full)


# ── PDF compilation (reuse issue_pdf tectonic pipeline) ───────────────────────

def compile_report_pdf(repo_root: Path, scope: str, dataset: str = "first_proof_1",
                       force: bool = False) -> dict:
    import hashlib
    import os
    import shutil
    import subprocess
    import tempfile
    from .issue_pdf import _PREAMBLE, _TECTONIC
    # Robust markdown->LaTeX converter (math-protected, emoji-safe, balanced
    # bold/italic) — the older issue_pdf.md_to_latex emits unbalanced \emph{...}.
    from .doc_bundle import _md_to_tex

    report = build_report(repo_root, scope, dataset, full=True)
    md = report["markdown"]
    proof_doc = ""
    if scope != "system":
        best = _best_proof(scope, dataset)
        proof_doc = ((best or {}).get("solution_tex") or "").strip()

    safe_scope = re.sub(r"[^A-Za-z0-9_-]", "_", f"{scope}_{dataset}")
    name = f"report_{safe_scope}"
    pdf_dir = repo_root / "documents" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    dest = pdf_dir / f"{name}.pdf"
    hash_file = pdf_dir / f"{name}.hash"
    cur_hash = hashlib.md5((md + proof_doc).encode("utf-8")).hexdigest()[:12]

    if not force and dest.is_file() and hash_file.is_file() and hash_file.read_text().strip() == cur_hash:
        return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "cached"}

    tectonic = _TECTONIC if (os.path.isfile(_TECTONIC) and os.access(_TECTONIC, os.X_OK)) \
        else shutil.which("tectonic") or shutil.which("pdflatex")
    if not tectonic:
        return {"ok": False, "pdf_url": None, "log": "No LaTeX toolchain available"}
    is_tec = "tectonic" in tectonic
    from .proofs import _missing_from_log, _safety_block

    def _compile(cmd, cwd):
        try:
            p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=180)
            return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return 1, "timed out"

    def _compile_report_body(markdown: str, title: str) -> bytes | None:
        """Resilient compile of a markdown report (own preamble + macro stubbing)."""
        safe_title = title.replace("\\", "").replace("_", r"\_").replace("&", r"\&").replace("#", r"\#").replace("%", r"\%")
        body = "\n".join([
            rf"\begin{{center}}{{\Large\bfseries {safe_title}}}\end{{center}}",
            r"\medskip\hrule\bigskip",
            _md_to_tex(markdown),
        ])
        with tempfile.TemporaryDirectory(prefix="rma_rep_") as tmp:
            b = Path(tmp)
            cmd = [tectonic, "--keep-logs", "main.tex"] if is_tec else ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
            cs_stubs: set = set(); env_stubs: set = set()
            def _doc():
                return "\n".join([_PREAMBLE, _safety_block(cs_stubs, env_stubs), r"\begin{document}", body, r"\end{document}"])
            def _flog(stdio):
                lf = b / "main.log"
                return (lf.read_text(encoding="utf-8", errors="replace") if lf.is_file() else "") + "\n" + stdio
            for _ in range(24):
                (b / "main.tex").write_text(_doc(), encoding="utf-8")
                rc, log = _compile(cmd, b)
                if rc == 0 and (b / "main.pdf").is_file():
                    return (b / "main.pdf").read_bytes()
                found = _missing_from_log(_flog(log))
                if not found:
                    break
                kind, nm = found
                tgt = cs_stubs if kind == "cs" else env_stubs
                if nm in tgt:
                    break
                tgt.add(nm)
            # forgiving fallback
            (b / "main.tex").write_text(_doc(), encoding="utf-8")
            if is_tec:
                _compile([tectonic, "--keep-logs", "-Z", "continue-on-errors", "main.tex"], b)
            else:
                _compile(["pdflatex", "-interaction=nonstopmode", "main.tex"], b)
            return (b / "main.pdf").read_bytes() if (b / "main.pdf").is_file() else None

    def _compile_proof_doc(tex: str) -> bytes | None:
        """Compile the proof's own complete document (its own preamble = reliable)."""
        with tempfile.TemporaryDirectory(prefix="rma_proof_") as tmp:
            b = Path(tmp)
            (b / "main.tex").write_text(tex, encoding="utf-8")
            if is_tec:
                rc, _ = _compile([tectonic, "main.tex"], b)
                if not (b / "main.pdf").is_file():
                    _compile([tectonic, "-Z", "continue-on-errors", "main.tex"], b)
            else:
                _compile(["pdflatex", "-interaction=nonstopmode", "main.tex"], b)
            return (b / "main.pdf").read_bytes() if (b / "main.pdf").is_file() else None

    def _merge(parts: list[bytes]) -> bytes | None:
        if len(parts) == 1:
            return parts[0]
        with tempfile.TemporaryDirectory(prefix="rma_merge_") as tmp:
            b = Path(tmp)
            files = []
            for k, pb in enumerate(parts):
                fp = b / f"p{k}.pdf"; fp.write_bytes(pb); files.append(str(fp))
            out = b / "merged.pdf"
            pu = shutil.which("pdfunite")
            if pu:
                _compile([pu, *files, str(out)], b)
            if not out.is_file():
                gs = shutil.which("gs")
                if gs:
                    _compile([gs, "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", f"-sOutputFile={out}", *files], b)
            return out.read_bytes() if out.is_file() else parts[0]

    # 1. report body — try full; fall back to the summary if the big agent text breaks LaTeX
    report_bytes = _compile_report_body(md, report.get("title", scope))
    if report_bytes is None:
        summary_md = build_report(repo_root, scope, dataset, full=False)["markdown"]
        report_bytes = _compile_report_body(summary_md, report.get("title", scope))

    # 2. full proof as its own pages
    proof_bytes = _compile_proof_doc(proof_doc) if proof_doc else None

    parts = [p for p in (report_bytes, proof_bytes) if p]
    if not parts:
        return {"ok": False, "pdf_url": None, "log": "Report and proof both failed to compile"}
    final = _merge(parts)
    if not final:
        return {"ok": False, "pdf_url": None, "log": "PDF merge failed"}
    dest.write_bytes(final)
    hash_file.write_text(cur_hash)
    pieces = ("report" if report_bytes else "") + ("+proof" if proof_bytes else "")
    return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": f"OK ({pieces})"}
