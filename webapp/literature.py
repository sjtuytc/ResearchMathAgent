"""Per-question literature tracking: paper index + inline notes."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .agent import AgentEvent


def _lit_dir(repo_root: Path, qid: str) -> Path:
    d = repo_root / "documents" / "questions" / qid / "literature"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(repo_root: Path, qid: str) -> Path:
    return _lit_dir(repo_root, qid) / "index.json"


def load_index(repo_root: Path, qid: str) -> list[dict]:
    p = _index_path(repo_root, qid)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(repo_root: Path, qid: str, papers: list[dict]) -> None:
    _index_path(repo_root, qid).write_text(
        json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _paper_id(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()[:10]


def add_paper(
    repo_root: Path,
    qid: str,
    *,
    url: str,
    title: str,
    authors: list[str] | None = None,
    year: int | None = None,
    abstract: str = "",
    tags: list[str] | None = None,
    relevance: str = "medium",
    notes: str = "",
    added_by: str = "human",
) -> dict:
    papers = load_index(repo_root, qid)
    pid = _paper_id(url)
    existing = next((p for p in papers if p["id"] == pid), None)
    if existing:
        return existing
    entry: dict = {
        "id": pid,
        "url": url,
        "title": title,
        "authors": authors or [],
        "year": year,
        "abstract": abstract,
        "tags": tags or [],
        "relevance": relevance,
        "notes": notes,
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    papers.append(entry)
    _save_index(repo_root, qid, papers)
    return entry


def update_paper(repo_root: Path, qid: str, paper_id: str, **kwargs) -> dict | None:
    papers = load_index(repo_root, qid)
    for p in papers:
        if p["id"] == paper_id:
            allowed = {"title", "authors", "year", "abstract", "tags", "relevance", "notes", "url"}
            for k, v in kwargs.items():
                if k in allowed:
                    p[k] = v
            if "notes" in kwargs:
                p["notes_updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_index(repo_root, qid, papers)
            return p
    return None


def delete_paper(repo_root: Path, qid: str, paper_id: str) -> bool:
    papers = load_index(repo_root, qid)
    new = [p for p in papers if p["id"] != paper_id]
    if len(new) == len(papers):
        return False
    _save_index(repo_root, qid, new)
    return True


# ── Agent-driven discovery ──────────────────────────────────────────────────

_DISCOVER_SYSTEM = (
    "You are a mathematical literature researcher. Given a research-level math problem, "
    "identify the most important papers a researcher would need to read to tackle it. "
    "Focus on papers that contain key techniques, foundational results, or recent progress "
    "directly relevant to the specific mathematical objects in the problem. "
    "Be precise and mathematically informed."
)

_DISCOVER_PROMPT = """\
Problem ID: {qid}
Title: {title}

Problem statement (LaTeX):
{problem_tex}

Identify 6-10 papers essential for tackling this problem. Include: seminal foundational works, \
papers introducing key techniques used in the solution area, and any recent progress papers.

Return ONLY valid JSON — no markdown fences, no explanation outside the JSON array:
[
  {{
    "url": "https://arxiv.org/abs/XXXX.XXXXX",
    "title": "Full paper title",
    "authors": ["Surname, Firstname", "..."],
    "year": YYYY,
    "abstract": "2-3 sentence summary of what this paper proves/introduces",
    "tags": ["key technique", "foundational", "recent progress"],
    "relevance": "high",
    "notes": "2-3 sentences explaining exactly how this paper is useful for our specific problem — which lemma/technique/result we would borrow"
  }}
]
Relevance must be one of: high, medium, low. Order papers by relevance descending.
"""


def _call_vertex_json(prompt: str, system: str, model: str = "claude-opus-4-8") -> str | None:
    from .llm import complete
    return complete(prompt, system=system, model=model, max_tokens=8192)


def ensure_all_lit(repo_root: Path, q_titles: dict | None = None) -> None:
    """Background: discover literature for any question missing a paper index."""
    for i in range(1, 11):
        qid = f"q{i}"
        if load_index(repo_root, qid):
            continue
        title = (q_titles or {}).get(qid, qid)
        for _ in discover_literature(repo_root, qid, title):
            pass


def discover_literature(repo_root: Path, qid: str, title: str) -> Iterator[AgentEvent]:
    """Call Claude to discover relevant papers, save them, yield AgentEvents."""
    problem_path = repo_root / "problems" / f"{qid}.tex"
    if not problem_path.is_file():
        yield AgentEvent("error", {"message": f"Problem file not found: {qid}.tex"})
        yield AgentEvent("done", {"reason": "error"})
        return

    yield AgentEvent("status", {"state": "running", "message": "Asking Claude to identify relevant literature…"})

    problem_tex = problem_path.read_text(encoding="utf-8", errors="replace")[:5000]
    prompt = _DISCOVER_PROMPT.format(qid=qid, title=title, problem_tex=problem_tex)
    raw = _call_vertex_json(prompt, _DISCOVER_SYSTEM)

    if not raw:
        yield AgentEvent("error", {"message": "Claude returned no response."})
        yield AgentEvent("done", {"reason": "error"})
        return

    # Extract JSON array from response
    import re
    raw = raw.strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)

    try:
        papers = json.loads(raw)
    except Exception:
        yield AgentEvent("error", {"message": f"Could not parse JSON response: {raw[:300]}"})
        yield AgentEvent("done", {"reason": "error"})
        return

    added = []
    for p in papers:
        if not isinstance(p, dict) or not p.get("url") or not p.get("title"):
            continue
        entry = add_paper(
            repo_root, qid,
            url=p.get("url", ""),
            title=p.get("title", ""),
            authors=p.get("authors", []),
            year=p.get("year"),
            abstract=p.get("abstract", ""),
            tags=p.get("tags", []),
            relevance=p.get("relevance", "medium"),
            notes=p.get("notes", ""),
            added_by="discovery-agent",
        )
        added.append(entry)
        # Also add to global shared library
        try:
            add_to_global(repo_root, entry)
        except Exception:
            pass
        yield AgentEvent("text_delta", {"text": f"+ {entry['title']} ({entry.get('year','')})\n"})

    yield AgentEvent("done", {"reason": "end_turn", "added": len(added), "papers": added})


# ── Global shared library ───────────────────────────────────────────────────

def _global_index_path(repo_root: Path) -> Path:
    d = repo_root / "documents" / "literature"
    d.mkdir(parents=True, exist_ok=True)
    return d / "global_index.json"


def _pdf_dir(repo_root: Path) -> Path:
    d = repo_root / "documents" / "literature" / "pdfs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_global(repo_root: Path) -> list[dict]:
    p = _global_index_path(repo_root)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def add_to_global(repo_root: Path, paper: dict) -> dict:
    """Add a paper to the global shared library (deduplicates by id or url)."""
    papers = list_global(repo_root)
    pid = paper.get("id") or _paper_id(paper.get("url", ""))
    if any(p.get("id") == pid or p.get("url") == paper.get("url") for p in papers):
        return next(p for p in papers if p.get("id") == pid or p.get("url") == paper.get("url"))
    entry = {**paper, "id": pid}
    entry.setdefault("added_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    papers.append(entry)
    _global_index_path(repo_root).write_text(
        json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return entry


def update_global(repo_root: Path, paper_id: str, **kwargs) -> dict | None:
    papers = list_global(repo_root)
    allowed = {"title", "authors", "year", "abstract", "tags", "relevance", "notes", "url"}
    for p in papers:
        if p.get("id") == paper_id:
            for k, v in kwargs.items():
                if k in allowed:
                    p[k] = v
            _global_index_path(repo_root).write_text(
                json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return p
    return None


def delete_from_global(repo_root: Path, paper_id: str) -> bool:
    papers = list_global(repo_root)
    new = [p for p in papers if p.get("id") != paper_id]
    if len(new) == len(papers):
        return False
    _global_index_path(repo_root).write_text(
        json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return True


def pdf_path_for(repo_root: Path, paper_id: str) -> Path:
    return _pdf_dir(repo_root) / f"{paper_id}.pdf"


def get_pdf_status(repo_root: Path, paper_id: str) -> str:
    """Return 'available', 'downloading', or 'none'."""
    lock = _pdf_dir(repo_root) / f"{paper_id}.lock"
    if lock.is_file():
        return "downloading"
    pdf = pdf_path_for(repo_root, paper_id)
    if pdf.is_file() and pdf.stat().st_size > 1000:
        return "available"
    return "none"


def download_paper_pdf(repo_root: Path, paper_id: str, url: str) -> str:
    """Download PDF from arXiv/URL. Returns 'ok', 'error:...', or 'exists'."""
    pdf_file = pdf_path_for(repo_root, paper_id)
    if pdf_file.is_file() and pdf_file.stat().st_size > 1000:
        return "exists"

    lock = _pdf_dir(repo_root) / f"{paper_id}.lock"
    if lock.is_file():
        return "downloading"

    # Resolve arXiv abstract URL → PDF URL
    pdf_url = _resolve_pdf_url(url)
    if not pdf_url:
        return "error:cannot resolve PDF URL"

    lock.write_text(pdf_url, encoding="utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(
            pdf_url,
            headers={"User-Agent": "ResearchMathAgent/1.0 (educational use)"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 1000:
            return "error:downloaded file too small"
        pdf_file.write_bytes(data)
        return "ok"
    except Exception as exc:
        return f"error:{exc}"
    finally:
        if lock.is_file():
            lock.unlink(missing_ok=True)


def _resolve_pdf_url(url: str) -> str | None:
    """Convert arXiv abstract URL to PDF URL."""
    url = url.strip()
    # arXiv abs → pdf
    m = re.search(r"arxiv\.org/abs/([0-9]{4}\.[0-9]+|[a-z]+/[0-9]+)", url, re.I)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    # Already a PDF URL
    if url.lower().endswith(".pdf"):
        return url
    # DOI or other — can't auto-resolve
    return None


# ── System-level literature (agent/AI research) ────────────────────────────

_SYSTEM_LIT_QID = "_system_"

_SYSTEM_SURVEY_SYSTEM = (
    "You are a research systems engineer surveying the academic literature relevant to "
    "building AI research agents for advanced mathematics. "
    "Your goal is to identify key papers that would help engineers improve the RMAC system: "
    "its agents, pipelines, evaluation methodology, and tool use. "
    "Be precise: cite real papers with real arXiv IDs where available."
)

_SYSTEM_SURVEY_PROMPT = """\
Survey the most important recent academic literature in the following areas relevant to
building and improving RMAC (Research Math Agent Cluster), an AI system that uses LLM agents
to make progress on research-level mathematics problems.

Identify 5-7 papers per area from the following areas:

1. Multi-agent LLM systems and collaboration (e.g. debate, reflection, critic-solver patterns)
2. LLM reasoning and mathematical problem solving (e.g. chain-of-thought, process reward models)
3. AI-assisted theorem proving and formal verification (e.g. Lean, Isabelle assistants)
4. Retrieval-augmented generation for scientific literature
5. Agent evaluation and benchmark design for complex reasoning tasks
6. Tool-augmented agents (code execution, search, APIs in reasoning loops)

For each paper return:
- Real arXiv URL if available (or a credible source URL)
- Full title exactly as published
- Authors (surname, firstname format)
- Year
- 2-3 sentence abstract summary
- Tags matching the area name above (use consistent short tags)
- Relevance to RMAC: high / medium
- Notes: 1-2 sentences on specifically how this paper could improve the RMAC system

Return ONLY valid JSON array — no markdown fences, no explanation:
[
  {{
    "url": "https://arxiv.org/abs/XXXX.XXXXX",
    "title": "Full paper title",
    "authors": ["Surname, Firstname"],
    "year": YYYY,
    "abstract": "2-3 sentence summary",
    "tags": ["multi-agent", "LLM"],
    "relevance": "high",
    "notes": "How this specifically helps RMAC"
  }}
]
"""


def discover_system_literature(repo_root: Path) -> Iterator[AgentEvent]:
    """Survey agent/AI research literature for the RMAC system via the Claude subscription."""
    yield AgentEvent("status", {"state": "running", "message": "Surveying agent research literature…"})
    raw = _call_vertex_json(_SYSTEM_SURVEY_PROMPT, _SYSTEM_SURVEY_SYSTEM)
    if not raw:
        yield AgentEvent("error", {"message": "Vertex returned no response."})
        yield AgentEvent("done", {"reason": "error"})
        return

    import re as _re
    raw = raw.strip()
    m = _re.search(r"\[.*\]", raw, _re.DOTALL)
    if m:
        raw = m.group(0)

    try:
        papers = json.loads(raw)
    except Exception:
        yield AgentEvent("error", {"message": f"Could not parse JSON: {raw[:300]}"})
        yield AgentEvent("done", {"reason": "error"})
        return

    added = []
    for p in papers:
        if not isinstance(p, dict) or not p.get("title"):
            continue
        # Store using per-question storage with special _system_ qid
        entry = add_paper(
            repo_root, _SYSTEM_LIT_QID,
            url=p.get("url", ""),
            title=p.get("title", ""),
            authors=p.get("authors", []),
            year=p.get("year"),
            abstract=p.get("abstract", ""),
            tags=p.get("tags", []),
            relevance=p.get("relevance", "medium"),
            notes=p.get("notes", ""),
            added_by="system-survey-agent",
        )
        added.append(entry)
        yield AgentEvent("text_delta", {"text": f"+ {entry['title']} ({entry.get('year','')})\n"})

    yield AgentEvent("done", {"reason": "end_turn", "added": len(added), "papers": added})


def pin_paper_to_prefix(
    repo_root: Path,
    problem_id: str,
    paper: dict,
) -> dict:
    """Download paper PDF and add it as a prefix entry for the given problem.

    Returns {"ok": bool, "prefix_id": str|None, "pdf_status": str, "message": str}
    """
    from .prefix import add_entry as prefix_add_entry

    paper_id = paper.get("id") or _paper_id(paper.get("url", ""))
    url = paper.get("url", "")

    # Download PDF in-process (blocking; call from a thread for the endpoint)
    pdf_status = "none"
    if url:
        try:
            result = download_paper_pdf(repo_root, paper_id, url)
            pdf_status = "available" if result in ("ok", "exists") else f"error:{result}"
        except Exception as exc:
            pdf_status = f"error:{exc}"

    # Build prefix content from paper metadata
    authors_str = ", ".join(paper.get("authors") or [])
    year = paper.get("year", "")
    tags_str = ", ".join(paper.get("tags") or [])
    abstract = (paper.get("abstract") or "").strip()
    notes = (paper.get("notes") or "").strip()

    content_lines = [
        f"**{paper.get('title', 'Untitled')}**",
        f"{authors_str} ({year})" if (authors_str or year) else "",
        f"Tags: {tags_str}" if tags_str else "",
        "",
        abstract,
    ]
    if notes:
        content_lines += ["", f"*Relevance to this problem:* {notes}"]
    if url:
        content_lines += ["", f"Source: {url}"]
    content = "\n".join(l for l in content_lines if l is not None).strip()

    # Add as prefix entry
    try:
        entry = prefix_add_entry(
            repo_root, problem_id,
            type="background",
            title=f"Literature: {paper.get('title', '')[:60]}",
            content=content,
        )
        prefix_id = entry["id"]
    except Exception as exc:
        return {"ok": False, "prefix_id": None, "pdf_status": pdf_status,
                "message": f"Prefix add failed: {exc}"}

    return {"ok": True, "prefix_id": prefix_id, "pdf_status": pdf_status,
            "message": "Pinned to prefix."}


# ── Seed global library with foundational references ───────────────────────

_SEED_PAPERS = [
    {
        "url": "https://arxiv.org/abs/1301.1995",
        "title": "Interlacing Families I: Bipartite Ramanujan Graphs of All Degrees",
        "authors": ["Marcus, Adam W.", "Spielman, Daniel A.", "Srivastava, Nikhil"],
        "year": 2015,
        "abstract": "Proves existence of bipartite Ramanujan graphs of every degree via interlacing polynomials.",
        "tags": ["spectral graph theory", "interlacing polynomials", "Ramanujan graphs"],
        "relevance": "high",
        "notes": "Core technique for finite free convolution (q4) and spectral sparsification (q6).",
    },
    {
        "url": "https://arxiv.org/abs/0803.0929",
        "title": "Graph Sparsification by Effective Resistances",
        "authors": ["Spielman, Daniel A.", "Srivastava, Nikhil"],
        "year": 2011,
        "abstract": "Constructs spectral sparsifiers of size O(n log n / ε²) via random sampling by effective resistances.",
        "tags": ["spectral graph theory", "graph sparsification", "effective resistance"],
        "relevance": "high",
        "notes": "Foundational for ε-light subset constructions (q6) and spectral graph theory (q4).",
    },
    {
        "url": "https://arxiv.org/abs/1109.2903",
        "title": "Solving the KPZ Equation",
        "authors": ["Hairer, Martin"],
        "year": 2013,
        "abstract": "Introduces regularity structures to give meaning to and solve the KPZ equation.",
        "tags": ["stochastic PDE", "regularity structures", "KPZ", "Phi^4"],
        "relevance": "high",
        "notes": "Hairer's regularity structures are the key framework for Φ⁴₃ measure equivalence (q1).",
    },
    {
        "url": "https://arxiv.org/abs/1303.5082",
        "title": "A Theory of Regularity Structures",
        "authors": ["Hairer, Martin"],
        "year": 2014,
        "abstract": "General theory of regularity structures for singular SPDEs.",
        "tags": ["regularity structures", "singular SPDE", "renormalization"],
        "relevance": "high",
        "notes": "General framework underlying the Φ⁴₃ measure shift question (q1).",
    },
    {
        "url": "https://arxiv.org/abs/1402.4143",
        "title": "Interlacing Families II: Mixed Characteristic Polynomials and the Kadison–Singer Problem",
        "authors": ["Marcus, Adam W.", "Spielman, Daniel A.", "Srivastava, Nikhil"],
        "year": 2015,
        "abstract": "Resolves the Kadison–Singer conjecture using interlacing polynomial methods.",
        "tags": ["Kadison-Singer", "interlacing polynomials", "spectral theory"],
        "relevance": "high",
        "notes": "Key reference for finite free convolution and spectral graph theory questions (q4, q6).",
    },
    {
        "url": "https://arxiv.org/abs/1202.3533",
        "title": "Symplectic Homology, Autonomous Hamiltonians, and Morse–Bott Moduli Spaces",
        "authors": ["Bourgeois, Frédéric", "Oancea, Alexandru"],
        "year": 2017,
        "abstract": "Studies Morse–Bott methods in symplectic homology.",
        "tags": ["symplectic geometry", "Floer theory", "Morse-Bott"],
        "relevance": "high",
        "notes": "Background for Lagrangian smoothings question (q8).",
    },
    {
        "url": "https://arxiv.org/abs/math/0606200",
        "title": "A geometric criterion for generating the Fukaya category",
        "authors": ["Abouzaid, Mohammed"],
        "year": 2010,
        "abstract": "Gives a geometric criterion for when a Lagrangian generates the Fukaya category.",
        "tags": ["Fukaya category", "Lagrangian", "symplectic geometry"],
        "relevance": "high",
        "notes": "Direct reference for Lagrangian smoothings problem (q8).",
    },
    {
        "url": "https://arxiv.org/abs/2110.03038",
        "title": "On symmetric functions and Hall–Littlewood polynomials",
        "authors": ["Williams, Lauren K."],
        "year": 2022,
        "abstract": "Studies Markov chains with stationary distribution given by Macdonald polynomials.",
        "tags": ["Macdonald polynomials", "Markov chains", "algebraic combinatorics"],
        "relevance": "high",
        "notes": "Directly relevant to the Macdonald stationary distribution Markov chain (q3).",
    },
]


def seed_global_library(repo_root: Path) -> int:
    """Seed the global library with foundational references. Returns count added."""
    count = 0
    for paper in _SEED_PAPERS:
        papers = list_global(repo_root)
        exists = any(p.get("url") == paper["url"] for p in papers)
        if not exists:
            add_to_global(repo_root, {**paper, "added_by": "seed"})
            count += 1
    return count
