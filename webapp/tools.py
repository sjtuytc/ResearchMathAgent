"""Tool surface for the Research Math Agent web app.

The agent is given a small, focused set of tools — the math-research analog of
the file/bash tools TheAgentCompany's OpenHands agent uses. Every filesystem
access is sandboxed: the agent may read ``problems/`` and ``skills/`` and read
or write inside a per-session scratch workspace, but it may **never** read the
benchmark solution directories listed in ``config/default.yaml``
(``outputs``, ``final_solutions``, ``baselines``, ...). That blocklist
is the STRICT RULE from CLAUDE.md, enforced here in code rather than by trust.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Directories the agent must never read from. Kept in sync with
# config/default.yaml -> project.blocked_input_dirs.
BLOCKED_INPUT_DIRS = (
    "outputs",
    "final_solutions",
    "skill_solutions",
    "baselines",
)

# Roots the agent is allowed to read from (relative to the repo root), in
# addition to its own session workspace.
READABLE_ROOTS = ("problems", "skills", "documents")

_PROBLEM_RE = re.compile(r"^q(?:10|[1-9])$")
_MAX_OUTPUT_CHARS = 16_000


class ToolError(Exception):
    """Raised when a tool call is invalid or hits the sandbox boundary."""


@dataclass
class ToolContext:
    """Per-session paths the tools operate against."""

    repo_root: Path
    workspace: Path

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        self.workspace = self.workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)


# --- Tool schemas (sent to the Claude Messages API) -----------------------

TOOL_DEFINITIONS = [
    {
        "name": "list_problems",
        "description": (
            "List the available benchmark problems (id and title) under "
            "problems/. Call this first if you are unsure which problem ids "
            "exist."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_problem",
        "description": (
            "Read the full LaTeX statement of a benchmark problem. Pass the "
            "problem id such as 'q6'. The shared preamble is included "
            "automatically when relevant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "problem_id": {
                    "type": "string",
                    "description": "Problem id, e.g. 'q6'.",
                }
            },
            "required": ["problem_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_skills",
        "description": (
            "List available math-research skill files under skills/. "
            "Call read_file on a returned path to load guidance."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file. Allowed locations: anything under "
            "problems/ or skills/, and any file you have written into your "
            "scratch workspace (e.g. solution.tex, preamble.tex). Reading "
            "prior benchmark solutions is forbidden and will fail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the repo root or your workspace.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a UTF-8 text file inside your scratch "
            "workspace (e.g. 'solution.tex' or 'check.py'). Use this to draft "
            "your proof and any verification scripts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative filename, e.g. 'solution.tex'.",
                },
                "content": {"type": "string", "description": "Full file contents."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_python",
        "description": (
            "Run a short Python 3 snippet in your workspace to sanity-check "
            "claims numerically (small cases, counterexample search, symbolic "
            "checks with sympy if available). Returns stdout and stderr. "
            "60s timeout, no network."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to execute."}
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "latex_check",
        "description": (
            "Compile a .tex file in your workspace with latexmk/pdflatex to "
            "confirm it builds. Returns success plus the tail of the log. If "
            "no LaTeX toolchain is installed it reports that and is a no-op."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative .tex filename.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
]


# --- Path safety ----------------------------------------------------------

def _logical_repo_path(ctx: ToolContext, raw: str) -> Path | None:
    """Return a repo-relative path when ``raw`` is under allowed read roots.

    Uses the logical path (no symlink follow) so problems/ symlinks outside the
    repo remain readable when they are declared under problems/ or skills/.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        return None
    logical = ctx.repo_root / candidate
    try:
        logical.relative_to(ctx.repo_root)
    except ValueError:
        return None
    top = candidate.parts[0] if candidate.parts else ""
    if top in BLOCKED_INPUT_DIRS or top not in READABLE_ROOTS:
        return None
    return logical


def _resolve_readable(ctx: ToolContext, raw: str) -> Path:
    """Resolve ``raw`` to an absolute path the agent is allowed to read."""
    candidate = Path(raw)
    options: list[Path] = []
    if candidate.is_absolute():
        options.append(candidate)
    else:
        repo_logical = _logical_repo_path(ctx, raw)
        if repo_logical is not None:
            options.append(repo_logical)
        options.append(ctx.workspace / candidate)

    readable: list[Path] = []
    for opt in options:
        if not opt.is_file():
            if _is_readable(ctx, opt):
                readable.append(opt.resolve())
            continue
        resolved = opt.resolve()
        if _is_readable(ctx, opt):
            return resolved
    if readable:
        return readable[0]
    raise ToolError(
        f"Path '{raw}' is outside the readable sandbox (problems/, skills/, "
        f"or your workspace) or points at a blocked benchmark directory."
    )


def _is_readable(ctx: ToolContext, path: Path) -> bool:
    if _within(path, ctx.workspace):
        return True
    # Accept logical paths under problems/ or skills/ even when they symlink outside.
    try:
        rel = path.relative_to(ctx.repo_root)
    except ValueError:
        return False
    top = rel.parts[0] if rel.parts else ""
    if top in BLOCKED_INPUT_DIRS:
        return False
    return top in READABLE_ROOTS


def _resolve_workspace(ctx: ToolContext, raw: str) -> Path:
    """Resolve ``raw`` to a path the agent is allowed to write (workspace only)."""
    candidate = Path(raw)
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (ctx.workspace / candidate).resolve()
    if not _within(target, ctx.workspace):
        raise ToolError(f"Path '{raw}' is outside your writable workspace.")
    return target


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# --- Tool execution -------------------------------------------------------

def execute_tool(ctx: ToolContext, name: str, tool_input: dict) -> str:
    """Dispatch a tool call and return a string result (raises ToolError)."""
    if name == "list_problems":
        return _list_problems(ctx)
    if name == "list_skills":
        return _list_skills(ctx)
    if name == "read_problem":
        return _read_problem(ctx, str(tool_input.get("problem_id", "")).strip())
    if name == "read_file":
        return _read_file(ctx, str(tool_input.get("path", "")))
    if name == "write_file":
        return _write_file(ctx, str(tool_input.get("path", "")), str(tool_input.get("content", "")))
    if name == "run_python":
        return _run_python(ctx, str(tool_input.get("code", "")))
    if name == "latex_check":
        return _latex_check(ctx, str(tool_input.get("path", "")))
    raise ToolError(f"Unknown tool: {name}")


def _list_problems(ctx: ToolContext) -> str:
    problems_dir = ctx.repo_root / "problems"
    if not problems_dir.is_dir():
        raise ToolError("No problems/ directory found.")
    lines = []
    for tex in sorted(problems_dir.glob("q*.tex"), key=_problem_sort_key):
        if not tex.is_file():
            continue
        title = _extract_title(tex)
        lines.append(f"- {tex.stem}: {title}")
    return "Available problems:\n" + "\n".join(lines) if lines else "No problems found."


def _expand_tex_inputs(text: str, repo_root: Path) -> str:
    """Inline \\input{...} directives (currently preamble only)."""

    def _replacer(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name == "preamble":
            pre = repo_root / "problems" / "preamble.tex"
            if pre.is_file():
                return pre.read_text(encoding="utf-8", errors="replace")
        return match.group(0)

    return re.sub(r"\\input\{([^}]+)\}", _replacer, text)


def seed_workspace(repo_root: Path, problem_id: str, workspace: Path) -> None:
    """Copy problem sources and all accumulated context into the agent workspace."""
    workspace.mkdir(parents=True, exist_ok=True)
    prob = repo_root / "problems" / f"{problem_id}.tex"
    if prob.is_file():
        (workspace / "problem.tex").write_text(
            _expand_tex_inputs(prob.read_text(encoding="utf-8", errors="replace"), repo_root),
            encoding="utf-8",
        )
    pre = repo_root / "problems" / "preamble.tex"
    if pre.is_file():
        shutil.copy2(pre, workspace / "preamble.tex")
    skill = repo_root / "skills" / "math-research" / "SKILL.md"
    if skill.is_file():
        shutil.copy2(skill, workspace / "SKILL.md")

    # Copy all accumulated research documents for this problem
    qdir = repo_root / "documents" / "questions" / problem_id
    for doc_name in ("overview.md", "strategies.md", "progress.md", "timeline.md"):
        src = qdir / doc_name
        if src.is_file():
            shutil.copy2(src, workspace / f"ctx_{doc_name}")

    # Seed the best current proof as solution.tex if one exists
    _seed_best_proof(repo_root, problem_id, workspace)


def _seed_best_proof(repo_root: Path, problem_id: str, workspace: Path) -> None:
    """Write the best known proof into solution.tex if one exists."""
    sol = workspace / "solution.tex"
    if sol.is_file():
        return  # caller already provided one
    try:
        # Lazy import to avoid circular dependency
        from .proofs import get_best_proof  # type: ignore[attr-defined]
        bp = get_best_proof(problem_id)
        if bp and bp.get("latex"):
            sol.write_text(bp["latex"], encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _read_problem(ctx: ToolContext, problem_id: str) -> str:
    if not _PROBLEM_RE.match(problem_id):
        raise ToolError(f"Invalid problem id '{problem_id}'. Expected q1..q10.")
    path = ctx.repo_root / "problems" / f"{problem_id}.tex"
    if not path.is_file():
        raise ToolError(f"Problem '{problem_id}' not found.")
    text = path.read_text(encoding="utf-8", errors="replace")
    text = _expand_tex_inputs(text, ctx.repo_root)
    return _clip(text)


def _list_skills(ctx: ToolContext) -> str:
    skills_dir = ctx.repo_root / "skills"
    if not skills_dir.is_dir():
        raise ToolError("No skills/ directory found.")
    lines: list[str] = []
    for path in sorted(skills_dir.rglob("*.md")):
        rel = path.relative_to(ctx.repo_root)
        lines.append(f"- {rel}")
    if not lines:
        return "No skill files found under skills/."
    return (
        "Available skill files (use read_file with the path shown):\n"
        + "\n".join(lines)
    )


def _read_file(ctx: ToolContext, raw: str) -> str:
    if not raw:
        raise ToolError("read_file requires a 'path'.")
    path = _resolve_readable(ctx, raw)
    if not path.is_file():
        raise ToolError(f"File not found: {raw}")
    return _clip(path.read_text(encoding="utf-8", errors="replace"))


def _write_file(ctx: ToolContext, raw: str, content: str) -> str:
    if not raw:
        raise ToolError("write_file requires a 'path'.")
    path = _resolve_workspace(ctx, raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    rel = path.relative_to(ctx.workspace)
    return f"Wrote {len(content)} chars to workspace/{rel}."


def _run_python(ctx: ToolContext, code: str) -> str:
    if not code.strip():
        raise ToolError("run_python requires 'code'.")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=ctx.workspace,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise ToolError("run_python timed out after 60s.")
    out = proc.stdout or ""
    err = proc.stderr or ""
    parts = [f"exit_code: {proc.returncode}"]
    if out:
        parts.append("stdout:\n" + out)
    if err:
        parts.append("stderr:\n" + err)
    return _clip("\n".join(parts))


def _latex_check(ctx: ToolContext, raw: str) -> str:
    if not raw:
        raise ToolError("latex_check requires a 'path'.")
    path = _resolve_workspace(ctx, raw)
    if not path.is_file():
        raise ToolError(f"File not found in workspace: {raw}")

    latexmk = shutil.which("latexmk")
    pdflatex = shutil.which("pdflatex")
    if latexmk:
        cmd = [latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error", path.name]
    elif pdflatex:
        cmd = [pdflatex, "-interaction=nonstopmode", "-halt-on-error", path.name]
    else:
        return "No LaTeX toolchain (latexmk/pdflatex) is installed; skipped compilation."

    try:
        proc = subprocess.run(
            cmd, cwd=ctx.workspace, text=True, capture_output=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        raise ToolError("latex_check timed out after 180s.")
    status = "BUILD OK" if proc.returncode == 0 else "BUILD FAILED"
    log_tail = (proc.stdout or "")[-4000:]
    return _clip(f"{status} (exit {proc.returncode})\n--- log tail ---\n{log_tail}")


# --- helpers --------------------------------------------------------------

def _problem_sort_key(path: Path) -> int:
    m = re.search(r"\d+", path.stem)
    return int(m.group()) if m else 0


def _extract_title(tex: Path) -> str:
    try:
        text = tex.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(unreadable)"
    m = re.search(r"\\title\{([^}]*)\}", text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    # Fall back to the first comment line.
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("%"):
            return line.lstrip("% ").strip()
    return "(untitled)"


def _clip(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    head = text[:_MAX_OUTPUT_CHARS]
    return head + f"\n... [truncated {len(text) - _MAX_OUTPUT_CHARS} chars]"
