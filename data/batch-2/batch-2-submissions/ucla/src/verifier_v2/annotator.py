"""Generate annotated LaTeX files with red/blue footnote annotations."""
from __future__ import annotations
import re

TEX_PREAMBLE = r"""
\usepackage{xcolor}
\usepackage[normalem]{ulem}
\newcounter{verifierissue}
\definecolor{issuecolor}{rgb}{0.85,0.1,0.1}
\definecolor{minorcolor}{rgb}{0.8,0.5,0.0}
\definecolor{commentcolor}{rgb}{0.0,0.2,0.75}
\newcommand{\verifierissue}[2]{%
  \stepcounter{verifierissue}%
  \textcolor{issuecolor}{\uline{#1}}%
  \footnote{\textcolor{commentcolor}{\textbf{[V2 Issue \theverifierissue]:} #2}}}
\newcommand{\verifierminor}[2]{%
  \stepcounter{verifierissue}%
  \textcolor{minorcolor}{#1}%
  \footnote{\textcolor{minorcolor}{\textbf{[V2 Minor \theverifierissue]:} #2}}}
"""

def _inject_preamble(tex: str) -> str:
    idx = tex.find(r'\begin{document}')
    return (tex[:idx] + TEX_PREAMBLE + "\n" + tex[idx:]) if idx != -1 else (TEX_PREAMBLE + tex)

def _esc(s: str) -> str:
    return (s.replace('\\', r'\textbackslash{}')
             .replace('{', r'\{').replace('}', r'\}')
             .replace('%', r'\%').replace('$', r'\$')
             .replace('#', r'\#').replace('&', r'\&')
             .replace('^', r'\^{}').replace('_', r'\_')
             .replace('\n', ' '))

def _annotate_excerpt(tex: str, excerpt: str, comment: str, minor: bool = False) -> str:
    words = re.sub(r'\s+', ' ', excerpt).strip().split()
    if len(words) < 2:
        return tex
    pattern = r'\s+'.join(re.escape(w) for w in words[:8])
    m = re.search(pattern, tex)
    if not m:
        return tex
    cmd = r'\verifierminor' if minor else r'\verifierissue'
    repl = cmd + '{' + m.group(0) + '}{' + _esc(comment) + '}'
    return tex[:m.start()] + repl + tex[m.end():]

def generate_prechecked_tex(original_tex: str, precheck_issues: list[dict]) -> str:
    """Annotate pre-check issues (citations + numerical) inline."""
    tex = _inject_preamble(original_tex)
    for issue in precheck_issues:
        excerpt = issue.get("excerpt") or issue.get("statement", "")
        ctype = issue.get("ctype", issue.get("severity", ""))
        detail = issue.get("detail", "")
        is_minor = issue.get("severity") == "minor"
        tag = f"Type {ctype}" if ctype else "Issue"
        if excerpt:
            tex = _annotate_excerpt(tex, excerpt, f"{tag}: {detail}", minor=is_minor)
    return tex

def generate_verified_tex(original_tex: str, precheck_issues: list[dict],
                           score: int, major_gaps: list[str],
                           minor_gaps: list[str]) -> str:
    """Annotate pre-check issues + add main verifier gaps as numbered list."""
    tex = generate_prechecked_tex(original_tex, precheck_issues)

    all_gaps = major_gaps + minor_gaps
    if not all_gaps:
        return tex

    def _esc_item(s):
        return (s.replace('\\', r'\textbackslash{}')
                 .replace('%', r'\%').replace('$', r'\$')
                 .replace('#', r'\#').replace('&', r'\&')
                 .replace('^', r'\^{}').replace('_', r'\_'))

    verdict = "VERIFIED" if score >= 9 else "NOT VERIFIED"
    section = (
        "\n\n\\clearpage\n"
        f"\\section*{{\\textcolor{{issuecolor}}{{Main Verifier: Score {score}/10 — {verdict}}}}}\n"
        "{\\color{commentcolor}\n"
        f"\\textbf{{Major gaps ({len(major_gaps)}):}}\n\\begin{{enumerate}}\n"
    )
    for i, g in enumerate(major_gaps, 1):
        section += f"\\item \\textbf{{Gap {i}:}} {_esc_item(g.strip())}\n"
    section += "\\end{enumerate}\n"
    if minor_gaps:
        section += f"\\textbf{{Minor gaps ({len(minor_gaps)}):}}\n\\begin{{enumerate}}\n"
        for i, g in enumerate(minor_gaps, 1):
            section += f"\\item {_esc_item(g.strip())}\n"
        section += "\\end{enumerate}\n"
    section += "}\n"

    end = tex.rfind(r'\end{document}')
    return (tex[:end] + section + tex[end:]) if end != -1 else (tex + section)
