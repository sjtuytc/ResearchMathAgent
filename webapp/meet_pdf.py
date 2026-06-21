"""Compile a meeting room (discussion + action plan) to PDF via tectonic.

Reuses the markdown→LaTeX machinery and preamble from issue_pdf.py.
Meeting transcripts are participant messages written in markdown with
embedded LaTeX math; the synthesized action plan is rendered as a numbered
list. Results are cached in documents/pdf/ keyed on the room mtime/hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .issue_pdf import _PREAMBLE, _TECTONIC, md_to_latex


def room_is_substantive(room: dict | None) -> bool:
    """True if a room has real discussion content or a synthesized plan.

    Empty shells (only the 'Meeting opened' event, no plan) are not
    substantive and should be hidden from the UI / not rendered.
    """
    if not room:
        return False
    real_msgs = [
        m for m in room.get("messages", [])
        if m.get("role") != "event" and (m.get("body") or "").strip()
    ]
    plan = room.get("plan") or {}
    has_plan = bool(plan.get("summary") or plan.get("steps"))
    return len(real_msgs) >= 1 or has_plan


def _safe(s: str) -> str:
    return (
        str(s)
        .replace("\\", r"\textbackslash{}")
        .replace("_", r"\_")
        .replace("&", r"\&")
        .replace("#", r"\#")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _build_meet_tex(room: dict) -> str:
    """Assemble a full LaTeX document from a meeting room."""
    topic = room.get("topic", "Meeting")
    goal = room.get("goal", "")
    status = room.get("status", "open")
    pid = room.get("problem_id", "")
    room_id = room.get("id", "")
    participants = room.get("participants", [])
    created = (room.get("created_at") or "")[:10]

    parts = [_PREAMBLE, r"\begin{document}"]

    # Title block
    parts.append(rf"""\begin{{center}}
{{\Large\bfseries {_safe(topic)}}}\\[4pt]
{{\small\color{{gray}} {_safe(pid)} / {_safe(room_id)} \quad|\quad status: {_safe(status)} \quad|\quad {_safe(created)}}}
\end{{center}}
\medskip\hrule\bigskip""")

    if goal:
        parts.append(r"\textbf{Goal.} " + md_to_latex(goal))
        parts.append(r"\medskip")

    if participants:
        parts.append(r"\textbf{Participants.} " + _safe(", ".join(participants)))
        parts.append(r"\bigskip\hrule\bigskip")

    # ── Action Plan (results) ────────────────────────────────────────────────
    plan = room.get("plan") or {}
    if plan.get("summary") or plan.get("steps"):
        parts.append(r"\section*{Action Plan}")
        if plan.get("summary"):
            parts.append(r"\textbf{Summary.} " + md_to_latex(plan.get("summary", "")))
            parts.append(r"\medskip")
        steps = plan.get("steps", [])
        if steps:
            executed = {e.get("step") for e in plan.get("executed_steps", [])}
            parts.append(r"\begin{enumerate}")
            for step in steps:
                idx = step.get("idx", 0)
                title = step.get("title", f"Step {idx+1}")
                body = step.get("body", step.get("description", ""))
                agent = step.get("agent", "")
                done = " \\textcolor{authorcol}{(done)}" if idx in executed else ""
                head = rf"\item \textbf{{{_safe(title)}}}"
                if agent:
                    head += rf" \quad\textit{{[{_safe(agent)}]}}"
                head += done
                parts.append(head)
                if body:
                    parts.append(md_to_latex(body))
            parts.append(r"\end{enumerate}")
        parts.append(r"\bigskip\hrule\bigskip")

    # ── Discussion transcript ────────────────────────────────────────────────
    parts.append(r"\section*{Discussion}")
    real_msgs = [m for m in room.get("messages", []) if (m.get("body") or "").strip()]
    if not real_msgs:
        parts.append(r"\textit{No discussion was recorded for this meeting.}")
    for m in real_msgs:
        body = (m.get("body") or "").strip()
        role = m.get("role", "")
        if role == "event":
            parts.append(r"\begin{center}\small\color{gray}" + _safe(body) + r"\end{center}")
            continue
        author = m.get("author", "")
        created = (m.get("created_at") or "")[:16].replace("T", " ")
        parts.append(rf"""\begin{{mdframed}}[backgroundcolor=white,linecolor=black!25,linewidth=0.8pt,innerleftmargin=8pt,innerrightmargin=8pt,innertopmargin=6pt,innerbottommargin=6pt]
{{\small\bfseries\color{{black!70}} {_safe(author)}}} \hfill {{\small\color{{black!50}} {_safe(created)}}}
\medskip

""")
        parts.append(md_to_latex(body))
        parts.append(r"\end{mdframed}" + "\n")

    parts.append(r"\end{document}")
    return "\n".join(parts)


def _pdf_cache_path(repo_root: Path, problem_id: str, room_id: str) -> Path:
    d = repo_root / "documents" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"meet_{problem_id}_{room_id}.pdf"


def _room_hash(room: dict) -> str:
    s = json.dumps(room, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(s.encode()).hexdigest()[:12]


def _hash_file(repo_root: Path, problem_id: str, room_id: str) -> Path:
    return repo_root / "documents" / "pdf" / f"meet_{problem_id}_{room_id}.hash"


def compile_meet_pdf(repo_root: Path, room: dict, force: bool = False) -> dict:
    """Compile a meeting room to PDF. Returns {ok, pdf_url, log}."""
    problem_id = room.get("problem_id", "")
    room_id = room.get("id", "")
    if not problem_id or not room_id:
        return {"ok": False, "pdf_url": None, "log": "Missing problem_id or room id"}

    if not room_is_substantive(room):
        return {"ok": False, "pdf_url": None, "log": "empty meeting — no discussion or plan to render"}

    dest = _pdf_cache_path(repo_root, problem_id, room_id)
    hash_file = _hash_file(repo_root, problem_id, room_id)
    cur_hash = _room_hash(room)
    name = f"meet_{problem_id}_{room_id}"

    if not force and dest.is_file() and hash_file.is_file():
        if hash_file.read_text().strip() == cur_hash:
            return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "cached"}

    tectonic = _TECTONIC if os.path.isfile(_TECTONIC) and os.access(_TECTONIC, os.X_OK) else shutil.which("tectonic") or shutil.which("pdflatex")
    if not tectonic:
        return {"ok": False, "pdf_url": None, "log": "No LaTeX toolchain available"}

    tex = _build_meet_tex(room)

    with tempfile.TemporaryDirectory(prefix="rma_meet_") as tmp:
        build = Path(tmp)
        (build / "main.tex").write_text(tex, encoding="utf-8")

        def _try_compile(cmd: list[str]) -> tuple[int, str]:
            try:
                proc = subprocess.run(cmd, cwd=build, capture_output=True, timeout=120)
                log = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
                return proc.returncode, log
            except subprocess.TimeoutExpired:
                return 1, "Compilation timed out"

        if "tectonic" in tectonic:
            rc, log = _try_compile([tectonic, "main.tex"])
            if rc != 0:
                rc2, log2 = _try_compile([tectonic, "-Z", "continue-on-errors", "main.tex"])
                if (build / "main.pdf").is_file():
                    rc, log = 0, log2
        else:
            rc, log = _try_compile(["pdflatex", "-interaction=nonstopmode", "main.tex"])

        out_pdf = build / "main.pdf"
        if out_pdf.is_file():
            shutil.copyfile(out_pdf, dest)
            hash_file.write_text(cur_hash)
            return {"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "OK"}
        return {"ok": False, "pdf_url": None, "log": f"Build failed (exit {rc})\n{log[-3000:]}"}
