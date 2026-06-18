"""Compile an issue thread to PDF via tectonic.

Issues are written in markdown with embedded LaTeX math ($...$, $$...$$).
We convert the markdown structure to LaTeX and compile with tectonic.
Results are cached in documents/pdf/ and invalidated when the issue mtime changes.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_TECTONIC = "/projects/bhov/zzhao18/software/bin/tectonic"

_PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,amsthm,mathtools}
\usepackage[margin=0.85in,top=0.75in]{geometry}
\usepackage{microtype,parskip,xcolor,hyperref}
\usepackage{mdframed}
\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}

\newtheorem{theorem}{Theorem}
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{claim}[theorem]{Claim}
\newtheorem{conjecture}[theorem]{Conjecture}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}[theorem]{Example}
\theoremstyle{remark}
\newtheorem{remark}[theorem]{Remark}

\definecolor{agentbg}{rgb}{0.10,0.13,0.18}
\definecolor{agentborder}{rgb}{0.18,0.25,0.38}
\definecolor{authorcol}{rgb}{0.35,0.65,1.0}
\definecolor{agenttext}{rgb}{0.90,0.93,0.95}

\setlength{\parindent}{0pt}
"""

_MATH_PLACEHOLDER = "\x00MATH\x00"


def _protect_math(text: str) -> tuple[str, list[str]]:
    """Extract all math spans (explicit and inferred), replace with numbered placeholders."""
    stores: list[str] = []

    def _store(m: re.Match) -> str:
        stores.append(m.group(0))
        return f"\x00M{len(stores)-1}\x00"

    # display math: $$...$$ or \[...\]
    text = re.sub(r"\$\$[\s\S]*?\$\$", _store, text)
    text = re.sub(r"\\\[[\s\S]*?\\\]", _store, text)
    # inline math: $...$ single dollar (allow single newlines, not blank lines)
    text = re.sub(r"\$(?!\$)(?:[^\$\n]|\n(?!\n))+?\$", _store, text)
    # \(...\)
    text = re.sub(r"\\\([\s\S]*?\\\)", _store, text)

    # ── Auto-wrap bare math notation not inside $..$ or \cmd{} ────────────────
    # Handles AI content that writes sigma_k, J^T, R^{2n} without $ delimiters.
    # IMPORTANT: inner placeholders must have their $..$ stripped to avoid nested $.
    def _strip_ph(s: str) -> str:
        """Expand placeholders, stripping their outer $ so they nest cleanly."""
        def _exp(mm: re.Match) -> str:
            i = int(mm.group(1))
            inner = stores[i] if i < len(stores) else mm.group(0)
            if inner.startswith("$$") and inner.endswith("$$"):
                return inner[2:-2]
            if inner.startswith("$") and inner.endswith("$"):
                return inner[1:-1]
            return inner
        return re.sub(r"\x00M(\d+)\x00", _exp, s)

    def _auto_math(m: re.Match) -> str:
        # Eagerly resolve inner placeholders so we don't get nested $...$
        content = _strip_ph(m.group(0))
        stores.append(f"${content}$")
        return f"\x00M{len(stores)-1}\x00"

    # word_subscript  e.g.  sigma_k  c_n  T_eps  (skip path components after /)
    # Subscript braces allow one level of nesting: _{S,{t}}
    _SB = r"_(?:\{(?:[^{}]|\{[^{}]*\})*\}|[A-Za-z0-9]+)"
    _SP = r"\^(?:\{(?:[^{}]|\{[^{}]*\})*\}|\([^)]+\)|[A-Za-z0-9]+)"
    text = re.sub(r"(?<![\\\{/])\b([A-Za-z]\w*(?:" + _SB + r")+)", _auto_math, text)
    # word^superscript  e.g.  J^T  R^{2n}  H^(i)  (skip path components after /)
    text = re.sub(r"(?<![\\\{/])\b([A-Za-z]\w*(?:" + _SP + r")+)", _auto_math, text)
    # ||expr||^N  norm-squared patterns  e.g.  ||S(alpha)||^2
    text = re.sub(r"(\|\|[^|]+\|\|(?:\^\{[^}]+\}|\^\w+)?)", _auto_math, text)
    # placeholder^superscript: e.g.  $sum_{k=1}$^{n-1}  where ^ was intended inside the math
    text = re.sub(r"(\x00M\d+\x00)(\^\{[^}]+\}|\^\([^)]+\)|\^[A-Za-z0-9]+)", _auto_math, text)

    return text, stores


def _restore_math(text: str, stores: list[str]) -> str:
    def _sub(m: re.Match) -> str:
        i = int(m.group(1))
        return stores[i] if i < len(stores) else m.group(0)
    # Loop until stable: auto-wrap may create placeholders containing other placeholders
    prev = None
    for _ in range(8):
        if text == prev:
            break
        prev = text
        text = re.sub(r"\x00M(\d+)\x00", _sub, text)
    return text


def _text_escape(s: str) -> str:
    """Escape LaTeX special chars that appear OUTSIDE math (math already protected)."""
    s = s.replace("&", r"\&")
    s = s.replace("%", r"\%")
    s = s.replace("#", r"\#")
    s = s.replace("~", r"\textasciitilde{}")
    # Escape bare _ and ^ not caught by auto-math wrap
    s = re.sub(r"(?<!\\)_", r"\\_", s)
    s = re.sub(r"(?<!\\)\^", r"\\textasciicircum{}", s)
    # Escape bare balanced braces {content} not preceded by letter/backslash (set notation)
    # Matches " {v0} " but not "\textbf{bold}" (preceded by 'f')
    s = re.sub(r"(?<![\\A-Za-z])(\{)([^{}\n]*)(\})", lambda m: r"\{" + m.group(2) + r"\}", s)
    # Fix \{content} → \{content\} where closing } is bare (not \})
    # Prevents "Extra }" LaTeX errors from set-minus notation V\{v0}
    s = re.sub(r"\\\{([^{}\\]*)\}", lambda m: r"\{" + m.group(1) + r"\}", s)
    return s


def _inline_md(s: str) -> str:
    """Convert inline markdown: bold, code, links.  Intentionally skips *italic* to avoid
    false positives from * used as multiplication or bullet continuation."""
    # bold-italic (triple stars)
    s = re.sub(r"\*\*\*(.+?)\*\*\*", r"\\textbf{\\textit{\1}}", s)
    # bold (double stars or double underscores)
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"__(.+?)__", r"\\textbf{\1}", s)
    # inline code  `...`
    s = re.sub(r"`([^`\n]+)`", lambda m: r"\texttt{" + m.group(1) + "}", s)
    # markdown links [text](url)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\\href{\2}{\1}", s)
    # bare urls
    s = re.sub(r"(?<![{(])(https?://[^\s)>]+)", r"\\url{\1}", s)
    # Arrow shorthand
    s = s.replace("->", r"\(\to\)").replace("<->", r"\(\leftrightarrow\)")
    # Escape remaining problem chars in text mode (after all substitutions)
    s = _text_escape(s)
    return s


_UNICODE_MAP = {
    '✓': r'\checkmark', '✗': r'\(\times\)', '✘': r'\(\times\)',
    '→': r'\(\to\)', '←': r'\(\leftarrow\)', '↔': r'\(\leftrightarrow\)',
    '⟹': r'\(\implies\)', '⟺': r'\(\iff\)', '⇒': r'\(\Rightarrow\)', '⇔': r'\(\Leftrightarrow\)',
    '≤': r'\(\leq\)', '≥': r'\(\geq\)', '≠': r'\(\neq\)', '≈': r'\(\approx\)',
    '≺': r'\(\prec\)', '≻': r'\(\succ\)', '⪯': r'\(\preceq\)', '⪰': r'\(\succeq\)',
    '∈': r'\(\in\)', '∉': r'\(\notin\)', '∅': r'\(\emptyset\)',
    '∀': r'\(\forall\)', '∃': r'\(\exists\)',
    '∩': r'\(\cap\)', '∪': r'\(\cup\)', '⊂': r'\(\subset\)', '⊆': r'\(\subseteq\)',
    '∞': r'\(\infty\)', '∂': r'\(\partial\)', '∇': r'\(\nabla\)',
    '⊞': r'\(\boxplus\)', '⊗': r'\(\otimes\)', '⊕': r'\(\oplus\)',
    '·': r'\(\cdot\)', '×': r'\(\times\)', '÷': r'\(\div\)',
    '⌊': r'\(\lfloor\)', '⌋': r'\(\rfloor\)', '⌈': r'\(\lceil\)', '⌉': r'\(\rceil\)',
    'α': r'\(\alpha\)', 'β': r'\(\beta\)', 'γ': r'\(\gamma\)', 'δ': r'\(\delta\)',
    'ε': r'\(\varepsilon\)', 'ζ': r'\(\zeta\)', 'η': r'\(\eta\)', 'θ': r'\(\theta\)',
    'λ': r'\(\lambda\)', 'μ': r'\(\mu\)', 'ν': r'\(\nu\)', 'ξ': r'\(\xi\)',
    'π': r'\(\pi\)', 'ρ': r'\(\rho\)', 'σ': r'\(\sigma\)', 'τ': r'\(\tau\)',
    'φ': r'\(\phi\)', 'χ': r'\(\chi\)', 'ψ': r'\(\psi\)', 'ω': r'\(\omega\)',
    'Γ': r'\(\Gamma\)', 'Δ': r'\(\Delta\)', 'Θ': r'\(\Theta\)', 'Λ': r'\(\Lambda\)',
    'Ξ': r'\(\Xi\)', 'Π': r'\(\Pi\)', 'Σ': r'\(\Sigma\)', 'Φ': r'\(\Phi\)',
    'Ψ': r'\(\Psi\)', 'Ω': r'\(\Omega\)',
    '—': '---', '–': '--', '’': "'", '‘': '`',
    '“': '``', '”': "''",
}

# Bare math-mode equivalents (no \(...\) delimiters — for inside existing $...$ spans)
# Add {} suffix to command-name replacements to prevent bleeding into adjacent letters
# e.g. "≠i" → "\neq{}i" not "\neqi" (undefined)
_UNICODE_MAP_MATH = {}
for _ch, _rep in _UNICODE_MAP.items():
    if _rep.startswith(r'\(') and _rep.endswith(r'\)'):
        _bare = _rep[2:-2]  # strip \( and \)
        # Add {} if bare command ends with a letter (prevents command-name bleeding)
        if _bare.startswith('\\') and _bare[-1].isalpha():
            _bare = _bare + '{}'
        _UNICODE_MAP_MATH[_ch] = _bare
    else:
        _UNICODE_MAP_MATH[_ch] = _rep
del _ch, _rep, _bare


_COMBINING = {
    "̃": r"\tilde",   # combining tilde  → \tilde{X}
    "̂": r"\hat",     # combining circumflex
    "́": r"\acute",   # combining acute
    "̀": r"\grave",   # combining grave
    "̈": r"\ddot",    # combining diaeresis
    "̇": r"\dot",     # combining dot above
    "̄": r"\bar",     # combining macron
    "̆": r"\breve",   # combining breve
    "̌": r"\check",   # combining caron
}


def _unicode_to_latex_math(s: str) -> str:
    """Apply unicode→LaTeX for text already inside math mode (no $ delimiters)."""
    for ch, rep in _UNICODE_MAP_MATH.items():
        s = s.replace(ch, rep)
    return s


def _unicode_to_latex(s: str) -> str:
    import unicodedata
    # Apply explicit map
    for ch, rep in _UNICODE_MAP.items():
        s = s.replace(ch, rep)
    # Handle base + combining diacritic pairs → $\cmd{X}$
    result: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if i + 1 < len(s) and s[i + 1] in _COMBINING:
            cmd = _COMBINING[s[i + 1]]
            base = ch if ch.isascii() else "?"
            result.append(f"\\({cmd}{{{base}}}\\)")
            i += 2
            continue
        if ord(ch) > 127:
            # Remaining non-ASCII: try to find a LaTeX equivalent via category
            cat = unicodedata.category(ch)
            if cat.startswith("L"):   # letter — transliterate
                result.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode() or "?")
            elif cat.startswith("P"):  # punctuation
                result.append("--" if ch in "–—" else "?")
            else:
                result.append("?")
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def md_to_latex(md: str) -> str:
    """Convert a markdown+LaTeX-math string to a LaTeX document body (no preamble/begin/end)."""
    # 1. Protect explicit math first (before unicode, so chars inside $...$ stay as-is)
    text, stores = _protect_math(md)
    # 2. Apply unicode→LaTeX inside stored math spans (bare commands, no \(\) delimiters)
    stores = [_unicode_to_latex_math(s) for s in stores]
    # 3. Apply unicode→LaTeX to the non-math text parts (uses \(...\) delimiters)
    parts = re.split(r'\x00M\d+\x00', text)
    ph_list = re.findall(r'\x00M\d+\x00', text)
    parts = [_unicode_to_latex(p) for p in parts]
    text = ''.join(p + ph for p, ph in zip(parts, ph_list + ['']))

    lines = text.splitlines()
    out: list[str] = []
    i = 0
    in_itemize = False
    in_enumerate = False
    in_code_block = False

    def close_lists():
        nonlocal in_itemize, in_enumerate
        if in_itemize:
            out.append(r"\end{itemize}"); in_itemize = False
        if in_enumerate:
            out.append(r"\end{enumerate}"); in_enumerate = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        # ── Fenced code block ──────────────────────────────────────────────────
        if line.startswith("```") or line.startswith("~~~"):
            close_lists()
            if not in_code_block:
                out.append(r"\begin{verbatim}")
                in_code_block = True
            else:
                out.append(r"\end{verbatim}")
                in_code_block = False
            i += 1; continue
        if in_code_block:
            out.append(raw)
            i += 1; continue

        # ── Pass-through LaTeX environments ───────────────────────────────────
        if re.match(r"\\(begin|end)\{", line):
            close_lists()
            out.append(line)
            i += 1; continue

        # ── ATX headings ──────────────────────────────────────────────────────
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            close_lists()
            depth = len(m.group(1))
            # Process markdown first (placeholders safe), then restore math
            title = _restore_math(_inline_md(m.group(2)), stores)
            cmds = {1: r"\section*", 2: r"\subsection*", 3: r"\subsubsection*", 4: r"\paragraph*"}
            out.append(f"{cmds.get(depth, r'\\paragraph*')}{{{title}}}")
            i += 1; continue

        # ── Horizontal rule ────────────────────────────────────────────────────
        if re.match(r"^[-*_]{3,}\s*$", line):
            close_lists()
            out.append(r"\medskip\hrule\medskip")
            i += 1; continue

        # ── Unordered list ─────────────────────────────────────────────────────
        m = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if m:
            if in_enumerate: out.append(r"\end{enumerate}"); in_enumerate = False
            if not in_itemize: out.append(r"\begin{itemize}"); in_itemize = True
            content = _restore_math(_inline_md(m.group(2)), stores)
            out.append(r"\item " + content)
            i += 1; continue

        # ── Ordered list ───────────────────────────────────────────────────────
        m = re.match(r"^(\s*)\d+[.)]\s+(.*)", line)
        if m:
            if in_itemize: out.append(r"\end{itemize}"); in_itemize = False
            if not in_enumerate: out.append(r"\begin{enumerate}"); in_enumerate = True
            content = _restore_math(_inline_md(m.group(2)), stores)
            out.append(r"\item " + content)
            i += 1; continue

        # ── Blank line ─────────────────────────────────────────────────────────
        if not line.strip():
            close_lists()
            out.append("")
            i += 1; continue

        # ── Blockquote ─────────────────────────────────────────────────────────
        if line.startswith("> "):
            close_lists()
            content = _restore_math(_inline_md(line[2:]), stores)
            out.append(r"\begin{quote}" + content + r"\end{quote}")
            i += 1; continue

        # ── Normal paragraph line ──────────────────────────────────────────────
        close_lists()
        # All lines go through _inline_md (markdown+escaping), then math restoration
        out.append(_restore_math(_inline_md(line), stores))
        i += 1

    close_lists()
    if in_code_block:
        out.append(r"\end{verbatim}")

    return "\n".join(out)


def _build_issue_tex(issue: dict) -> str:
    """Assemble a full LaTeX document from an issue thread."""
    title = issue.get("title", "Issue")
    status = issue.get("status", "open")
    pid = issue.get("problem_id", "")
    issue_id = issue.get("id", "")

    parts = [_PREAMBLE]
    parts.append(r"\begin{document}")
    # Title block
    safe_title = title.replace("_", r"\_").replace("&", r"\&").replace("#", r"\#").replace("%", r"\%")
    parts.append(rf"""\begin{{center}}
{{\Large\bfseries {safe_title}}}\\[4pt]
{{\small\color{{gray}} {pid} / {issue_id} \quad|\quad status: {status}}}
\end{{center}}
\medskip\hrule\bigskip""")

    # Body (if present)
    body = (issue.get("body") or "").strip()
    if body:
        parts.append(md_to_latex(body))
        parts.append(r"\bigskip")

    # Comments
    comments = issue.get("comments", [])
    for c in comments:
        cbody = (c.get("body") or "").strip()
        if not cbody:
            continue
        author = c.get("author", "")
        role = c.get("role", "")
        created = (c.get("created_at") or "")[:16].replace("T", " ")
        safe_author = author.replace("_", r"\_")
        role_label = f"[{role}]" if role else ""

        parts.append(rf"""\begin{{mdframed}}[backgroundcolor=white,linecolor=black!25,linewidth=0.8pt,innerleftmargin=8pt,innerrightmargin=8pt,innertopmargin=6pt,innerbottommargin=6pt]
{{\small\bfseries\color{{black!70}} {safe_author} {role_label}}} \hfill {{\small\color{{black!50}} {created}}}
\medskip

""")
        parts.append(md_to_latex(cbody))
        parts.append(r"\end{mdframed}" + "\n")

    parts.append(r"\end{document}")
    return "\n".join(parts)


def _pdf_cache_path(repo_root: Path, problem_id: str, issue_id: str) -> Path:
    d = repo_root / "documents" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"issue_{problem_id}_{issue_id}.pdf"


def _issue_hash(issue: dict) -> str:
    s = json.dumps(issue, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(s.encode()).hexdigest()[:12]


def _hash_file(repo_root: Path, problem_id: str, issue_id: str) -> Path:
    return repo_root / "documents" / "pdf" / f"issue_{problem_id}_{issue_id}.hash"


def compile_issue_pdf(repo_root: Path, issue: dict, force: bool = False) -> dict:
    """Compile issue thread to PDF. Returns {ok, pdf_url, log}."""
    problem_id = issue.get("problem_id", "")
    issue_id = issue.get("id", "")
    if not problem_id or not issue_id:
        return {"ok": False, "pdf_url": None, "log": "Missing problem_id or issue id"}

    dest = _pdf_cache_path(repo_root, problem_id, issue_id)
    hash_file = _hash_file(repo_root, problem_id, issue_id)
    cur_hash = _issue_hash(issue)

    # Serve from cache if hash matches
    if not force and dest.is_file() and hash_file.is_file():
        if hash_file.read_text().strip() == cur_hash:
            return {"ok": True, "pdf_url": f"/api/pdf/issue_{problem_id}_{issue_id}.pdf", "log": "cached"}

    import os
    tectonic = _TECTONIC if os.path.isfile(_TECTONIC) and os.access(_TECTONIC, os.X_OK) else shutil.which("tectonic") or shutil.which("pdflatex")
    if not tectonic:
        return {"ok": False, "pdf_url": None, "log": "No LaTeX toolchain available"}

    tex = _build_issue_tex(issue)

    with tempfile.TemporaryDirectory(prefix="rma_issue_") as tmp:
        build = Path(tmp)
        (build / "main.tex").write_text(tex, encoding="utf-8")

        def _try_compile(cmd: list[str]) -> tuple[int, str, Path]:
            try:
                proc = subprocess.run(cmd, cwd=build, capture_output=True, timeout=120)
                log = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
                return proc.returncode, log, build / "main.pdf"
            except subprocess.TimeoutExpired:
                return 1, "Compilation timed out", build / "main.pdf"

        # Primary: tectonic (strict pass first for clean output)
        if "tectonic" in tectonic:
            rc, log, out_pdf = _try_compile([tectonic, "main.tex"])
            # On error, retry with continue-on-errors to produce a partial PDF
            if rc != 0:
                rc2, log2, _ = _try_compile([tectonic, "-Z", "continue-on-errors", "main.tex"])
                if (build / "main.pdf").is_file():
                    rc, log = 0, log2
        else:
            rc, log, out_pdf = _try_compile(["pdflatex", "-interaction=nonstopmode", "main.tex"])

        if out_pdf.is_file():
            shutil.copyfile(out_pdf, dest)
            hash_file.write_text(cur_hash)
            return {"ok": True, "pdf_url": f"/api/pdf/issue_{problem_id}_{issue_id}.pdf", "log": "OK"}
        return {"ok": False, "pdf_url": None, "log": f"Build failed (exit {rc})\n{log[-3000:]}"}
