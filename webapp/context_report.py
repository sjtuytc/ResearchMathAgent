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


# ── LaTeX helpers (used by the PDF book builder) ─────────────────────────────

_TEX_CHARS: dict[int, str] = {
    ord("\\"): r"\textbackslash{}",
    ord("&"):  r"\&",
    ord("%"):  r"\%",
    ord("$"):  r"\$",
    ord("#"):  r"\#",
    ord("_"):  r"\_",
    ord("{"):  r"\{",
    ord("}"):  r"\}",
    ord("~"):  r"\textasciitilde{}",
    ord("^"):  r"\^{}",
}


def _tex_escape(s: str) -> str:
    """Escape plain text for verbatim inclusion in LaTeX.
    str.translate is single-pass so replacements cannot re-escape each other.
    """
    return s.translate(_TEX_CHARS)


def _strip_md(s: str) -> str:
    """Strip markdown bold / italic / code markers before passing to _tex_escape."""
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*",     r"\1", s)
    s = re.sub(r"`([^`]+)`",       r"\1", s)
    return s


# Book-style LaTeX preamble — no \title/\author/\date/\begin{document}.
# Those are injected dynamically in _build_problem_latex_body().

_BOOK_PREAMBLE = r"""\documentclass[12pt,oneside]{report}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{microtype}
\usepackage[margin=1.15in,top=1.3in,bottom=1.3in]{geometry}
\usepackage{amsmath,amsthm,amssymb,mathtools}
\usepackage{booktabs}
\usepackage{enumitem}
\usepackage[dvipsnames]{xcolor}
\usepackage[hidelinks,pdfusetitle]{hyperref}
\usepackage{parskip}
\usepackage{fancyhdr}

%% score-bar glyphs for the evaluation chapter
\newcommand{\scorefull}{\textcolor{black}{\rule{7pt}{7pt}}}
\newcommand{\scoreempty}{\framebox[9pt]{\rule{0pt}{7pt}\hspace{2pt}}}

%% theorem environments — proof bodies use these
\newtheorem{theorem}{Theorem}[chapter]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{claim}[theorem]{Claim}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}[theorem]{Example}
\theoremstyle{remark}
\newtheorem{remark}[theorem]{Remark}
\newtheorem*{theorem*}{Theorem}
\newtheorem*{lemma*}{Lemma}
\newtheorem*{corollary*}{Corollary}
\newtheorem*{remark*}{Remark}

%% common math abbreviations
\newcommand{\R}{\mathbb{R}}
\newcommand{\N}{\mathbb{N}}
\newcommand{\Z}{\mathbb{Z}}
\newcommand{\Q}{\mathbb{Q}}
\newcommand{\C}{\mathbb{C}}
\newcommand{\F}{\mathbb{F}}
\newcommand{\eps}{\varepsilon}
\DeclareMathOperator*{\argmin}{arg\,min}

%% running headers
\pagestyle{fancy}
\fancyhf{}
\fancyhead[R]{\small\nouppercase{\leftmark}}
\fancyfoot[C]{\small\thepage}
\renewcommand{\headrulewidth}{0.4pt}

%% Citation fallback: show [key] in gray when no .bib file is loaded.
%% \mbox prevents the key from being hyphenated across a line break.
%% \AtBeginDocument wins over any package that might redefine \cite.
\AtBeginDocument{%
  \renewcommand{\cite}[2][]{[\textcolor{gray}{\mbox{#2}}]}%
  \providecommand{\citep}[2][]{[\textcolor{gray}{\mbox{#2}}]}%
  \providecommand{\citet}[2][]{[\textcolor{gray}{\textit{\mbox{#2}}}]}%
  \providecommand{\citealt}[2][]{[\textcolor{gray}{\mbox{#2}}]}%
  \providecommand{\citealp}[2][]{[\textcolor{gray}{\mbox{#2}}]}%
  \providecommand{\citenum}[1]{\textcolor{gray}{\mbox{#1}}}%
}
"""

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


def _build_problem_latex_body(repo_root: Path, pid: str,
                               dataset: str = "first_proof_1") -> tuple[str, str]:
    """Build a book-style LaTeX report for one problem.

    Returns:
        preamble — everything before \\begin{document} (ready for stub injection)
        body     — everything between \\begin{document} and \\end{document}

    Chapter map:
        1  Problem Statement   (raw LaTeX from problem file — inserted verbatim)
        2  Evaluation          (score bars + verdict + analysis)
        3  Best Proof          (raw LaTeX proof body — inserted verbatim)
        4  Key Concepts        (omitted when none)
        5  Meetings            (omitted when none)
        6  Open Issues         (omitted when none)
        7  Resolved Issues     (omitted when none)
        8  Insights
    """
    prof       = _profile(pid)
    issues     = _issues(repo_root, pid, dataset)
    best       = _best_proof(pid, dataset)
    meetings   = _meetings(repo_root, pid)
    qinsight   = _question_insight(repo_root, pid, dataset)
    proof_eval = _proof_eval(repo_root, pid)
    concepts   = _concepts(repo_root, pid)

    open_issues     = [i for i in issues if i.get("status") in ("open", "in_progress")]
    resolved_issues = [i for i in issues if i.get("status") == "resolved"]

    # title
    title = prof.get("title") or ""
    if not title:
        try:
            from .dataset_store import get_problem as _ds_get
            title = (_ds_get(dataset, pid) or {}).get("title") or ""
        except Exception:
            pass
    title = title or pid.upper()

    # proof quality label — use proof_eval, not the flaky automated verifier
    has_proof = bool(best and best.get("has_solution"))
    sol_tex   = ((best or {}).get("solution_tex") or "").strip()
    pe        = proof_eval if (proof_eval and "error" not in proof_eval) else {}
    pe_aa     = pe.get("answer_accuracy")
    if pe_aa is True or pe_aa == 1:
        quality_tex = r"\textcolor{OliveGreen}{\textbf{Answer correct}}"
    elif pe_aa is False or pe_aa == 0:
        quality_tex = r"\textcolor{BrickRed}{\textbf{Answer incorrect}}"
    elif has_proof:
        quality_tex = r"\textcolor{Goldenrod}{\textbf{Awaiting evaluation}}"
    else:
        quality_tex = r"\textbf{---}"

    # preamble (static macros + dynamic \title / \author / \date)
    area_tex   = _tex_escape(prof.get("area",   "") or "")
    author_tex = _tex_escape(prof.get("author", "") or "")
    meta_line  = r"  $\cdot$  ".join(filter(None, [area_tex, author_tex]))

    preamble_lines = [_BOOK_PREAMBLE]
    preamble_lines.append(
        rf"\title{{\Large\bfseries {_tex_escape(title)}\\"
        rf"\large RMA Context Report}}"
    )
    if meta_line:
        preamble_lines.append(rf"\author{{{meta_line}}}")
    preamble_lines.append(
        rf"\date{{Generated "
        rf"{_tex_escape(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}}}"
    )
    preamble = "\n".join(preamble_lines)

    # body
    B: list[str] = []

    B.append(r"\maketitle")
    B.append("")

    # ── Executive Summary (unnumbered, before ToC) ────────────────────────────
    B.append(r"\chapter*{Executive Summary}")
    B.append(r"\addcontentsline{toc}{chapter}{Executive Summary}")
    B.append("")

    # Opening: proof_eval scores table first (always fresh after rma push), then
    # verdict + notes as structured paragraphs.  qinsight.summary is an LLM
    # snapshot that may lag between rma push runs — omit it here to avoid stale
    # text; the Insights chapter (Chapter 7) still shows it in full.

    # Evaluation scores table
    if pe:
        aa = pe.get("answer_accuracy")
        lc = pe.get("logical_correctness")
        pc = pe.get("proof_completeness")
        cl = pe.get("proof_clarity")

        def _bar_row(val: int | None, mx: int) -> str:
            if val is None:
                return r"\textcolor{gray}{---}"
            v = int(val)
            return r"\scorefull{}" * v + r"\scoreempty{}" * (mx - v)

        B.append(r"\section*{Proof Evaluation}")
        B.append(r"\begin{center}")
        B.append(r"\begin{tabular}{lccl}")
        B.append(r"\toprule")
        B.append(r"Criterion & Score & Max & Rating \\")
        B.append(r"\midrule")

        if aa is not None:
            aa_cell = (r"\textcolor{OliveGreen}{\textbf{Correct}}" if aa
                       else r"\textcolor{BrickRed}{\textbf{Incorrect}}")
            B.append(rf"Answer Accuracy & {1 if aa else 0} & 1 & {aa_cell} \\")
        for val, label, mx in (
            (lc, "Logical Correctness", 5),
            (pc, "Proof Completeness",  5),
            (cl, "Proof Clarity",       5),
        ):
            if val is not None:
                B.append(rf"{label} & {int(val)} & {mx} & {_bar_row(val, mx)} \\")

        score_vals = [1 if aa else 0 if aa is not None else None,
                      int(lc) if lc is not None else None,
                      int(pc) if pc is not None else None,
                      int(cl) if cl is not None else None]
        max_vals   = [1 if aa is not None else None,
                      5 if lc is not None else None,
                      5 if pc is not None else None,
                      5 if cl is not None else None]
        s_total = sum(x for x in score_vals if x is not None)
        m_total = sum(x for x in max_vals   if x is not None)
        if m_total:
            B.append(r"\midrule")
            B.append(
                rf"\textbf{{Total}} & \textbf{{{s_total}}} & \textbf{{{m_total}}} & \\"
            )
        B.append(r"\bottomrule")
        B.append(r"\end{tabular}")
        B.append(r"\end{center}")
        B.append("")

        if pe.get("verdict"):
            B.append(r"\paragraph{Verdict.}\ " + _tex_escape(_strip_md(pe["verdict"])))
            B.append("")
        if pe.get("notes"):
            B.append(r"\paragraph{Analysis.}\ " + _tex_escape(_strip_md(pe["notes"])))
            B.append("")
    else:
        B.append(
            rf"This report documents the research and proof effort for "
            rf"\emph{{{_tex_escape(title)}}}."
        )
        B.append("")

    # Research status
    B.append(r"\section*{Research Status}")
    B.append(r"\begin{description}[leftmargin=5cm,labelwidth=4.8cm,noitemsep]")
    B.append(rf"\item[Proof quality] {quality_tex}")
    B.append(
        rf"\item[Open issues] \textbf{{{len(open_issues)}}}"
        + (r" \textcolor{gray}{--- none}" if not open_issues else "")
    )
    if resolved_issues:
        B.append(rf"\item[Resolved issues] {len(resolved_issues)}")
    B.append(rf"\item[Research meetings] {len(meetings)}")
    B.append(r"\end{description}")
    B.append("")

    if open_issues:
        B.append(r"\paragraph{Open issues:}")
        B.append(r"\begin{itemize}[noitemsep]")
        for oi in open_issues:
            sev_color = {"open": "BrickRed", "in_progress": "Goldenrod"}.get(
                oi.get("status", ""), "Gray")
            oi_title = _tex_escape(oi.get("title", oi["id"]))
            oi_id    = _tex_escape(oi["id"])
            B.append(
                rf"\item \textcolor{{{sev_color}}}{{{oi_title}}}"
                rf"\ \textcolor{{gray}}{{\texttt{{{oi_id}}}}}"
            )
        B.append(r"\end{itemize}")
        B.append("")

    B.append(r"\tableofcontents")
    B.append(r"\clearpage")
    B.append("")

    # ── Chapter 1: Problem Statement ──────────────────────────────────────────
    B.append(r"\chapter{Problem Statement}")
    stmt = _problem_statement(repo_root, pid, dataset)
    if stmt:
        B.append(stmt)           # already LaTeX — insert verbatim
    else:
        B.append(r"\textit{Problem statement not found.}")
    B.append("")

    # ── Chapter 2: Evaluation ─────────────────────────────────────────────────
    B.append(r"\chapter{Evaluation}")
    if pe:
        aa = pe.get("answer_accuracy")
        lc = pe.get("logical_correctness")
        pc = pe.get("proof_completeness")
        cl = pe.get("proof_clarity")

        def _bar(val: int | None, mx: int) -> str:
            if val is None:
                return ""
            v = int(val)
            return r"\scorefull{}" * v + r"\scoreempty{}" * (mx - v) + rf"\ \ {v}/{mx}"

        B.append(r"\begin{description}[leftmargin=5.5cm,labelwidth=5.3cm,labelsep=0.4em]")
        if aa is not None:
            aa_tex = (r"\textcolor{OliveGreen}{Correct\ (1/1)}" if aa
                      else r"\textcolor{BrickRed}{Incorrect\ (0/1)}")
            B.append(rf"\item[Answer Accuracy] {aa_tex}")
        for val, label, mx in (
            (lc, "Logical Correctness", 5),
            (pc, "Proof Completeness",  5),
            (cl, "Proof Clarity",       5),
        ):
            if val is not None:
                B.append(rf"\item[{label}] {_bar(val, mx)}")
        B.append(r"\end{description}")
        B.append("")
        if pe.get("verdict"):
            B.append(r"\paragraph{Verdict.}\ " + _tex_escape(_strip_md(pe["verdict"])))
            B.append("")
        if pe.get("notes"):
            B.append(r"\paragraph{Analysis.}\ " + _tex_escape(_strip_md(pe["notes"])))
            B.append("")
    else:
        B.append(r"\textit{No proof evaluation recorded yet.}")
        B.append("")

    # ── Chapter 3: Best Proof ─────────────────────────────────────────────────
    B.append(r"\chapter{Best Proof}")
    if has_proof and sol_tex:
        when = (best.get("updated_at") or best.get("created_at") or "")[:10]
        if when:
            B.append(rf"\textit{{Last updated: {_tex_escape(when)}}}")
            B.append(r"\medskip")
            B.append("")
        # Strip the proof's own \documentclass preamble and insert the body verbatim.
        proof_body = _full_proof_latex(repo_root, pid, dataset)
        B.append(proof_body)
    elif has_proof:
        B.append(r"\textit{Proof file exists but source is unavailable.}")
    else:
        B.append(
            r"\textit{No consolidated proof yet. "
            r"Run solve\,+\,Consolidate in the Proofs tab.}"
        )
    B.append("")

    # ── Chapter 4: Key Concepts ───────────────────────────────────────────────
    if concepts:
        core = [c for c in concepts if c.get("category") == "core"]
        bg   = [c for c in concepts if c.get("category") != "core"]
        B.append(r"\chapter{Key Concepts}")
        B.append(
            rf"\textit{{{len(concepts)} concepts"
            r" --- full definitions in the Concept PDF.}}"
        )
        B.append("")
        if core:
            B.append(r"\section*{Core Concepts}")
            B.append(r"\begin{description}[noitemsep]")
            for c in core[:10]:
                name = _tex_escape(c.get("name", ""))
                nota = c.get("notation", "")
                nota_str = rf" (${nota}$)" if nota else ""
                defn = _tex_escape(_strip_md(c.get("definition", "") or ""))[:400]
                B.append(rf"\item[\textbf{{{name}}}]{nota_str} {defn}")
            B.append(r"\end{description}")
            B.append("")
        if bg:
            B.append(r"\section*{Background Concepts}")
            B.append(r"\begin{itemize}[noitemsep]")
            for c in bg[:8]:
                name = _tex_escape(c.get("name", ""))
                nota = c.get("notation", "")
                nota_str = rf" (${nota}$)" if nota else ""
                B.append(rf"\item {name}{nota_str}")
            B.append(r"\end{itemize}")
            B.append("")

    # ── Chapter 5: Meetings ───────────────────────────────────────────────────
    if meetings:
        B.append(r"\chapter{Meetings}")
        for room in meetings:
            topic = _tex_escape(room.get("topic") or room.get("id") or "—")
            when  = _tex_escape((room.get("created_at") or "")[:10])
            parts = _tex_escape(", ".join(room.get("participants", [])))
            B.append(rf"\section{{{topic}}}")
            meta_items = [x for x in [when, parts] if x]
            if meta_items:
                B.append(rf"\textit{{{r'  $\cdot$  '.join(meta_items)}}}")
                B.append(r"\medskip")
                B.append("")
            plan = room.get("plan") or {}
            if plan.get("summary"):
                B.append(
                    r"\paragraph{Action plan.}\ "
                    + _tex_escape(_strip_md(plan["summary"]))
                )
                B.append("")
            steps = plan.get("steps", [])
            if steps:
                B.append(r"\begin{enumerate}[noitemsep]")
                for s in steps:
                    agent  = _tex_escape(s.get("agent", ""))
                    stitle = _tex_escape(s.get("title", "Step"))
                    sbody  = _tex_escape(_strip_md((s.get("body") or "")[:300]))
                    atag   = rf"\ \emph{{({agent})}}" if agent else ""
                    B.append(rf"\item \textbf{{{stitle}}}{atag}: {sbody}")
                B.append(r"\end{enumerate}")
                B.append("")
            hl = _highlights(room, n=5)
            if hl:
                B.append(r"\paragraph{Discussion highlights.}")
                B.append(r"\begin{itemize}[noitemsep]")
                for h in hl:
                    B.append(rf"\item {_tex_escape(_strip_md(h))}")
                B.append(r"\end{itemize}")
                B.append("")

    # ── Chapter 6: Open Issues ────────────────────────────────────────────────
    if open_issues:
        B.append(r"\chapter{Open Issues}")
        for i in open_issues:
            sev_word  = {"open": "Open", "in_progress": "In Progress"}.get(
                         i.get("status", ""), "Unknown")
            sev_color = {"open": "BrickRed", "in_progress": "Goldenrod"}.get(
                         i.get("status", ""), "Gray")
            ititle  = _tex_escape(i.get("title", i["id"]))
            iid     = _tex_escape(i["id"])
            labels  = _tex_escape(", ".join(i.get("labels", [])))
            B.append(rf"\section{{{ititle}}}")
            meta_str = rf"\texttt{{{iid}}}"
            if labels:
                meta_str += rf"\ $\cdot$\ {labels}"
            meta_str += (
                rf"\ $\cdot$\ \textcolor{{{sev_color}}}{{\textbf{{{sev_word}}}}}"
            )
            B.append(meta_str)
            B.append(r"\medskip")
            body_txt = _tex_escape(_strip_md((i.get("body") or "").strip()))[:1000]
            if body_txt:
                B.append(body_txt)
                B.append("")
            analysis = _latest_analysis(i, limit=800)
            if analysis:
                B.append(
                    r"\paragraph{Latest analysis.}\ "
                    + _tex_escape(_strip_md(analysis))
                )
            B.append("")

    # ── Chapter 7: Resolved Issues ────────────────────────────────────────────
    if resolved_issues:
        B.append(r"\chapter{Resolved Issues}")
        B.append(r"\begin{itemize}[noitemsep]")
        for i in resolved_issues:
            ititle = _tex_escape(i.get("title", i["id"]))
            iid    = _tex_escape(i["id"])
            B.append(rf"\item \textbf{{{ititle}}}\ $\cdot$\ \texttt{{{iid}}}")
        B.append(r"\end{itemize}")
        B.append("")

    # ── Chapter 8: Insights ───────────────────────────────────────────────────
    B.append(r"\chapter{Insights}")
    wrote = False
    if qinsight:
        if qinsight.get("summary"):
            B.append(_tex_escape(_strip_md(qinsight["summary"])))
            B.append(""); wrote = True
        for key, head in (
            ("highlights", "Highlights"),
            ("mistakes",   "Mistakes and lessons"),
        ):
            vals = qinsight.get(key) or []
            if vals:
                B.append(rf"\paragraph{{{head}.}}")
                B.append(r"\begin{itemize}[noitemsep]")
                for v in vals[:6]:
                    B.append(rf"\item {_tex_escape(_strip_md(v))}")
                B.append(r"\end{itemize}")
                B.append(""); wrote = True
    if not wrote:
        B.append(r"\textit{No problem-specific insight generated yet.}")
        B.append("")

    return preamble, "\n".join(B)


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

    title = prof.get("title") or ""
    if not title:
        try:
            from .dataset_store import get_problem as _ds_get
            _p = _ds_get(dataset, pid) or {}
            title = _p.get("title") or ""
        except Exception:
            pass
    if not title:
        title = pid.upper()

    # Derive a clean verification label from proof_eval (not the automated verifier flag,
    # which is often "not yet verified" even when the proof is correct).
    has_proof = bool(best and best.get("has_solution"))
    pe_aa = (proof_eval or {}).get("answer_accuracy") if proof_eval and "error" not in (proof_eval or {}) else None
    if pe_aa is True or pe_aa == 1:
        proof_quality = "✅ Answer correct"
    elif pe_aa is False or pe_aa == 0:
        proof_quality = "❌ Answer incorrect"
    elif has_proof:
        proof_quality = "⚠️ Awaiting evaluation"
    else:
        proof_quality = "—"

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
    L.append(f"**Proof quality:** {proof_quality}  ·  "
             f"**Open issues:** {len(open_issues)}  ·  "
             f"**Meetings:** {len(meetings)}")
    L.append("")
    L.append("---")

    # ── 1. PROBLEM STATEMENT ────────────────────────────────────────────────
    stmt = _problem_statement(repo_root, pid, dataset)
    if stmt:
        L.append("## Problem Statement")
        L.append(stmt[:4000])
        L.append("")

    # ── 2. EVALUATION ───────────────────────────────────────────────────────
    L.append("## Evaluation")
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
        L.append("_No proof evaluation recorded yet._")
        L.append("")

    # ── 3. BEST PROOF ───────────────────────────────────────────────────────
    L.append("## Best Proof")
    if best and best.get("has_solution"):
        when = (best.get("updated_at") or best.get("created_at") or "")[:10]
        if when:
            L.append(f"_{when}_")
            L.append("")
        sol = (best.get("solution_tex") or "").strip()
        if sol:
            # Always show the proof excerpt — the PDF pages are appended separately.
            excerpt = _proof_excerpt(sol, max_chars=2400)
            if excerpt:
                L.append(excerpt)
        else:
            L.append("_Proof source not available._")
    else:
        L.append("_No consolidated proof yet. Run a solve + Consolidate in the Proofs tab._")
    L.append("")

    # ── 4. KEY CONCEPTS ─────────────────────────────────────────────────────
    if concepts:
        core = [c for c in concepts if c.get("category") == "core"]
        bg   = [c for c in concepts if c.get("category") != "core"]
        L.append("## Key Concepts")
        L.append(f"_{len(concepts)} concepts — full definitions in the Concept PDF._")
        L.append("")
        for c in core[:8]:
            name = c.get("name", "")
            nota = c.get("notation", "")
            nota_str = f" — ${nota}$" if nota else ""
            L.append(f"- **{name}**{nota_str}")
        if bg:
            for c in bg[:5]:
                name = c.get("name", "")
                nota = c.get("notation", "")
                nota_str = f" — ${nota}$" if nota else ""
                L.append(f"- {name}{nota_str}")
        L.append("")

    # ── 5. MEETING RESULTS ──────────────────────────────────────────────────
    if prof.get("candidate"):
        L.append("## Candidate Answer")
        L.append(prof["candidate"])
        L.append("")
    if prof.get("strategy"):
        L.append("## Core Approach")
        L.append(prof["strategy"])
        L.append("")

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

    # ── 6. OPEN ISSUES ──────────────────────────────────────────────────────
    L.append(f"## Open Issues ({len(open_issues)})")
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
        L.append("_None._")
        L.append("")

    # ── 7. RESOLVED ISSUES ──────────────────────────────────────────────────
    if resolved_issues:
        L.append(f"## Resolved Issues ({len(resolved_issues)})")
        if full:
            for i in resolved_issues:
                L.append(_issue_thread_md(i))
        else:
            for i in resolved_issues:
                L.append(f"- ✅ {i.get('title', i['id'])}  ·  `{i['id']}`")
        L.append("")

    # ── 8. INSIGHTS & LESSONS ───────────────────────────────────────────────
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

    # ── 9. STRATEGY ─────────────────────────────────────────────────────────
    if prof.get("difficulty") or attempts:
        L.append("## Strategy & Difficulty")
        if prof.get("difficulty"):
            L.append(prof["difficulty"])
            L.append("")
        if attempts:
            outcomes: dict[str, int] = {}
            for a in attempts:
                outcomes[a.get("outcome", "?")] = outcomes.get(a.get("outcome", "?"), 0) + 1
            summary = ", ".join(f"{k}: {v}" for k, v in sorted(outcomes.items()))
            L.append(f"**Attempt history:** {len(attempts)} recorded ({summary}).")
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
    from .proofs import _missing_from_log, _safety_block

    safe_scope = re.sub(r"[^A-Za-z0-9_-]", "_", f"{scope}_{dataset}")
    name     = f"report_{safe_scope}"
    pdf_dir  = repo_root / "documents" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    dest      = pdf_dir / f"{name}.pdf"
    hash_file = pdf_dir / f"{name}.hash"

    tectonic = (
        _TECTONIC if (os.path.isfile(_TECTONIC) and os.access(_TECTONIC, os.X_OK))
        else shutil.which("tectonic") or shutil.which("pdflatex")
    )
    if not tectonic:
        return {"ok": False, "pdf_url": None, "log": "No LaTeX toolchain"}
    is_tec = "tectonic" in tectonic

    def _run(cmd, cwd):
        try:
            p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=180)
            return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return 1, "timed out"

    # ── system report: keep the existing markdown→LaTeX path ──────────────────
    if scope == "system":
        from .doc_bundle import _md_to_tex
        report = build_report(repo_root, scope, dataset, full=True)
        md = report["markdown"]
        _md_for_hash = re.sub(
            r"\*Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC[^*]*\*", "", md
        )
        cur_hash = hashlib.md5(_md_for_hash.encode()).hexdigest()[:12]
        if not force and dest.is_file() and hash_file.is_file() \
                and hash_file.read_text().strip() == cur_hash:
            return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "cached"}

        safe_t = (report.get("title") or scope).replace("_", r"\_").replace("&", r"\&")
        sys_body = "\n".join([
            rf"\begin{{center}}{{\Large\bfseries {safe_t}}}\end{{center}}",
            r"\medskip\hrule\bigskip",
            _md_to_tex(md),
        ])
        cs_s: set = set(); env_s: set = set()

        def _sys_doc():
            return "\n".join([
                _PREAMBLE, _safety_block(cs_s, env_s),
                r"\begin{document}", sys_body, r"\end{document}",
            ])

        with tempfile.TemporaryDirectory(prefix="rma_sys_") as tmp:
            b = Path(tmp)
            cmd = ([tectonic, "--keep-logs", "main.tex"] if is_tec
                   else ["pdflatex", "-interaction=nonstopmode", "main.tex"])
            for _ in range(24):
                (b / "main.tex").write_text(_sys_doc(), encoding="utf-8")
                rc, stdio = _run(cmd, b)
                if rc == 0 and (b / "main.pdf").is_file():
                    break
                lf = b / "main.log"
                log = (lf.read_text(encoding="utf-8", errors="replace")
                       if lf.is_file() else "") + "\n" + stdio
                found = _missing_from_log(log)
                if not found:
                    break
                kind, nm = found
                (cs_s if kind == "cs" else env_s).add(nm)
            if not (b / "main.pdf").is_file():
                (b / "main.tex").write_text(_sys_doc(), encoding="utf-8")
                _run(([tectonic, "--keep-logs", "-Z", "continue-on-errors", "main.tex"]
                      if is_tec else ["pdflatex", "-interaction=nonstopmode", "main.tex"]), b)
            if (b / "main.pdf").is_file():
                dest.write_bytes((b / "main.pdf").read_bytes())
                hash_file.write_text(cur_hash)
                return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "OK (system)"}
        return {"ok": False, "pdf_url": None, "log": "system report compile failed"}

    # ── problem report: native LaTeX book ─────────────────────────────────────
    # _build_problem_latex_body() assembles a \documentclass{report} document
    # with \chapter sections and the proof body inserted inline in Chapter 3.
    preamble, body = _build_problem_latex_body(repo_root, scope, dataset)

    # Stable hash — strip the timestamp so the cache survives across requests.
    _body_for_hash = re.sub(
        r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", "TS", body
    )
    cur_hash = hashlib.md5((_body_for_hash + preamble).encode()).hexdigest()[:12]
    if not force and dest.is_file() and hash_file.is_file() \
            and hash_file.read_text().strip() == cur_hash:
        return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "cached"}

    cs_stubs: set = set()
    env_stubs: set = set()

    def _doc() -> str:
        # _safety_block stubs any \cmd or {env} the proof uses that our preamble omits.
        return "\n".join([
            preamble,
            _safety_block(cs_stubs, env_stubs),
            r"\begin{document}",
            body,
            r"\end{document}",
        ])

    def _flog(stdio: str, b: Path) -> str:
        lf = b / "main.log"
        return (lf.read_text(encoding="utf-8", errors="replace") if lf.is_file() else "") \
               + "\n" + stdio

    with tempfile.TemporaryDirectory(prefix="rma_rep_") as tmp:
        b = Path(tmp)
        cmd = ([tectonic, "--keep-logs", "main.tex"] if is_tec
               else ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"])

        for _ in range(24):
            (b / "main.tex").write_text(_doc(), encoding="utf-8")
            rc, stdio = _run(cmd, b)
            if rc == 0 and (b / "main.pdf").is_file():
                break
            found = _missing_from_log(_flog(stdio, b))
            if not found:
                break
            kind, nm = found
            if nm in (cs_stubs if kind == "cs" else env_stubs):
                break
            (cs_stubs if kind == "cs" else env_stubs).add(nm)

        # forgiving fallback — continue-on-errors so partial PDFs are still useful
        if not (b / "main.pdf").is_file():
            (b / "main.tex").write_text(_doc(), encoding="utf-8")
            _run(([tectonic, "--keep-logs", "-Z", "continue-on-errors", "main.tex"]
                  if is_tec else ["pdflatex", "-interaction=nonstopmode", "main.tex"]), b)

        if (b / "main.pdf").is_file():
            dest.write_bytes((b / "main.pdf").read_bytes())
            hash_file.write_text(cur_hash)
            return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "OK"}

    return {"ok": False, "pdf_url": None, "log": "compile failed"}


# ── dataset master report: ONE huge PDF of everything (all problems, all tabs) ──

def compile_master_pdf(repo_root: Path, dataset: str = "first_proof_1", force: bool = False) -> dict:
    """Compile ONE huge PDF for a whole dataset: the system overview followed by
    every problem's full combined report (statement, concepts, insights, issues,
    meetings, and the full proof). Reuses ``compile_report_pdf`` per scope and
    merges the resulting PDFs in order.
    """
    import shutil
    import subprocess

    pdf_dir = repo_root / "documents" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    def _report_path(scope: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", f"{scope}_{dataset}")
        return pdf_dir / f"report_{safe}.pdf"

    parts: list[Path] = []
    logs: list[str] = []

    # 1) every problem's full combined report first (problem → evaluation →
    #    best proof → others within each), so the document leads with problems.
    for pid in problem_ids(dataset):
        r = compile_report_pdf(repo_root, pid, dataset, force=force)
        fp = _report_path(pid)
        if r.get("ok") and fp.is_file():
            parts.append(fp)
            logs.append(f"{pid}=ok")
        else:
            logs.append(f"{pid}=fail")

    # 2) system overview (cross-problem dashboard) last
    sysr = compile_report_pdf(repo_root, "system", dataset, force=force)
    if sysr.get("ok") and _report_path("system").is_file():
        parts.append(_report_path("system"))
    logs.append(f"system={'ok' if sysr.get('ok') else 'fail'}")

    if not parts:
        return {"ok": False, "pdf_url": None, "log": "no report parts; " + " ".join(logs)}

    dest = pdf_dir / f"master_{dataset}.pdf"
    ok = False
    if len(parts) == 1:
        shutil.copyfile(parts[0], dest); ok = dest.is_file()
    else:
        pu = shutil.which("pdfunite")
        if pu:
            try:
                subprocess.run([pu, *[str(p) for p in parts], str(dest)],
                               check=True, timeout=600, capture_output=True)
                ok = dest.is_file()
            except Exception:
                ok = False
        if not ok and shutil.which("gs"):
            try:
                subprocess.run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
                                f"-sOutputFile={dest}", *[str(p) for p in parts]],
                               check=True, timeout=600, capture_output=True)
                ok = dest.is_file()
            except Exception:
                ok = False
    if not ok:
        return {"ok": False, "pdf_url": None, "log": "merge failed; " + " ".join(logs)}
    return {"ok": True, "pdf_url": f"/api/pdf/master_{dataset}.pdf",
            "parts": len(parts), "log": "OK; " + " ".join(logs)}
