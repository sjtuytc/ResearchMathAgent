"""literature_research.py — Stage 0 literature research.

Standalone module. Runs BEFORE Stage 1 (advisor directions). Replaces the
previous "literature survey + direction-writing in one Stage-1 call" pattern,
which relied on the web_search tool to fetch full paper text — unreliable, in
practice it only returned title/abstract level material.

Pipeline:
  A. Search   — one web_search-enabled API call asking the LLM to enumerate
                every paper likely to contain theorems, lemmas, or proof
                techniques useful for the target problem. Output: a JSON array
                of {url, title, why_relevant}.
  B. Fetch    — download each paper's PDF and extract full text. PDF infra is
                reused from deep_read.py (_fetch_paper_text, _arxiv_id_from_url,
                _sanitize_id), which already handles arXiv URL rewriting,
                on-disk cache, pymupdf/pdftotext fallback, and HTML
                landing-page guards. Cache directory is shared with Stage 1.5
                so the same arXiv ID is downloaded at most once per machine.
  C. Read     — for each successfully downloaded paper, a dedicated reader
                agent (parallel across papers, web_search disabled) extracts:
                  • overall_summary       — 3-6 sentence paper-level summary
                  • key_theorems_lemmas   — every useful labelled statement,
                                            with self-contained restatements
                                            and detailed proof sketches (the
                                            agent decides how many)
                  • proof_techniques      — every technique portable to the
                                            problem, with applicability notes
                                            (the agent decides how many)
                  • other_useful_info     — anything else that could matter
  D. Save     — write one JSON object per paper to literature_research.jsonl.

The output of this module feeds the Stage 1 direction-writing prompt ONLY; it
does NOT enter the shared KB. (The optional Stage 1.5 deep_read still runs
afterwards and DOES inject its own extractions into the KB, on a subset of
papers triaged from the resulting directions.)
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deep_read import (
    _arxiv_id_from_url,
    _extract_json_array,
    _extract_json_object,
    _fetch_paper_text,
    _sanitize_id,
)
from rate_limiter import acquire_slot

LIT_SEARCH_MIN_INTERVAL_SEC = float(os.environ.get("LIT_SEARCH_MIN_INTERVAL_SEC", "60"))
LIT_SEARCH_RATE_LOCK_PATH   = os.environ.get("LIT_SEARCH_RATE_LOCK_PATH", "/tmp/lit_search.rate.lock")
LIT_READ_MIN_INTERVAL_SEC   = float(os.environ.get("LIT_READ_MIN_INTERVAL_SEC", "30"))
LIT_READ_RATE_LOCK_PATH     = os.environ.get("LIT_READ_RATE_LOCK_PATH", "/tmp/lit_read.rate.lock")


# ─── Prompts ──────────────────────────────────────────────────────────────────

SEARCH_PROMPT = """\
You are a research assistant with access to web search. Your task is to find \
every paper in the literature likely to contain theorems, lemmas, proof \
techniques, or other content useful for proving the mathematical problem below.

# Problem
{problem}

# Past Attempts on This Problem (from previous runs, if any)
{past_notes_section}

# Instructions
- Search broadly. Cover the major lines of attack and the standard tool-box for \
this kind of problem; do NOT restrict yourself to one sub-area.
- For every paper you cite, provide an exact, verifiable URL. **Prefer arXiv \
links** (https://arxiv.org/abs/XXXX.XXXXX) since they are freely downloadable. \
Other publisher URLs are acceptable ONLY if the paper is freely downloadable \
from there (i.e., a direct PDF link works).
- Do NOT fabricate or approximate URLs — if you cannot confirm the exact URL, \
omit the paper rather than guess.
- Be thorough but discerning: include every paper that genuinely contributes, \
and do NOT pad with marginally related work. There is no minimum or maximum \
count — return exactly the papers you find genuinely useful, however many \
that turns out to be.

# Output
Return ONLY a JSON array, one entry per paper. No prose before or after the \
array. No code fences.

[
  {{"url": "https://arxiv.org/abs/XXXX.XXXXX", "title": "...", "why_relevant": "1-2 sentences on what specifically in this paper would help solve the problem"}}
]
""".strip()


READ_PROMPT = """\
You are reading a research paper to extract content useful for proving the \
mathematical problem below. Your output is consumed by a strategic advisor \
that synthesises these extractions into directions for solver agents — your \
extraction quality directly affects downstream proof quality.

# Original Problem
{problem}

# Why this paper was picked
{why_relevant}

# Full text of the paper (may be long)
{paper_text}

# Your task
Read the paper carefully and produce a structured extraction. Two priorities: \
**fidelity** (extract only what is actually in the paper; do not hallucinate) \
and **usefulness for the original problem** (do not transcribe unrelated \
content — focus on what could plausibly help).

1. **overall_summary** — 3-6 sentences describing what the paper proves, the \
core technique used, and the most important way (or ways) the paper might \
serve a proof of the original problem.

2. **key_theorems_lemmas** — every theorem, lemma, proposition, or key \
estimate from this paper that is potentially useful for the original problem. \
Include as many or as few as the paper actually contributes; no minimum or \
maximum count. For each:
   • label — e.g. "Theorem 1.2", "Lemma 3.4", "Main Result"
   • statement — self-contained restatement. Define every symbol, quantifier, \
hypothesis, and notational convention inline so the statement stands alone. \
Paraphrasing is allowed and often necessary; do NOT silently weaken hypotheses. \
No length cap.
   • proof_sketch — detailed enough that a mathematician could reconstruct or \
port the argument. Identify every key construction, inequality, identity, \
hypothesis use, and non-obvious choice. Use as much length as the proof \
actually demands; do not pad and do not abbreviate.

3. **proof_techniques** — every technique, strategy, or idea from this paper \
that might transfer to the original problem. Include as many or as few as the \
paper actually contributes; no minimum or maximum count. For each:
   • name — short descriptive name
   • description — 1-2 paragraph explanation of the technique itself, in the \
paper's own setting
   • applicability_to_problem — 1-2 sentences on how this could attach to the \
original problem (a specific hypothesis to try, an obstacle it might bypass, \
an analogue to set up, etc.)

4. **other_useful_info** — any other observation, conjecture, related-work \
pointer, open problem, or implicit insight that could matter for the original \
problem. One-line cross-references to other papers the paper itself cites are \
allowed (do NOT auto-fetch them). Leave empty if nothing fits.

# Output (single JSON object, no fences, no surrounding prose)
{{
  "arxiv_id": "{arxiv_id}",
  "url": "{url}",
  "title": "...",
  "overall_summary": "...",
  "key_theorems_lemmas": [
    {{"label": "...", "statement": "...", "proof_sketch": "..."}}
  ],
  "proof_techniques": [
    {{"name": "...", "description": "...", "applicability_to_problem": "..."}}
  ],
  "other_useful_info": "..."
}}

Constraints:
- If a section has nothing useful, return [] (lists) or "" (strings) — do not pad.
- Do NOT translate statements into the original problem's setting; leave them \
in the paper's own language. Cross-setting translation can live inside \
`proof_techniques[].applicability_to_problem`.
- Do NOT include "what to avoid" or failed approaches — only proven, citable \
content.
""".strip()


# ─── Parsing ──────────────────────────────────────────────────────────────────

def _parse_search(text):
    arr = _extract_json_array(text) or []
    out = []
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        out.append({
            "url":          url,
            "title":        (entry.get("title") or "").strip(),
            "why_relevant": (entry.get("why_relevant") or "").strip(),
        })
    return out


def _parse_extraction(text, arxiv_id, url, fallback_title):
    obj = _extract_json_object(text) or {}
    obj.setdefault("arxiv_id", arxiv_id)
    obj.setdefault("url", url)
    if not (obj.get("title") or "").strip():
        obj["title"] = fallback_title

    raw_lemmas = obj.get("key_theorems_lemmas") or []
    cleaned_lemmas = []
    for lem in raw_lemmas:
        if not isinstance(lem, dict):
            continue
        stmt = (lem.get("statement") or "").strip()
        if not stmt:
            continue
        cleaned_lemmas.append({
            "label":        (lem.get("label") or "").strip(),
            "statement":    stmt,
            "proof_sketch": (lem.get("proof_sketch") or "").strip(),
        })
    obj["key_theorems_lemmas"] = cleaned_lemmas

    raw_techs = obj.get("proof_techniques") or []
    cleaned_techs = []
    for t in raw_techs:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        desc = (t.get("description") or "").strip()
        if not name and not desc:
            continue
        cleaned_techs.append({
            "name":                     name,
            "description":              desc,
            "applicability_to_problem": (t.get("applicability_to_problem") or "").strip(),
        })
    obj["proof_techniques"] = cleaned_techs

    obj["overall_summary"]   = (obj.get("overall_summary")   or "").strip()
    obj["other_useful_info"] = (obj.get("other_useful_info") or "").strip()
    return obj


# ─── Public entrypoint ────────────────────────────────────────────────────────

def run_literature_research(
    *,
    problem,
    past_notes_section,
    run_response,                   # harness's run_response(...)
    output_file: Path,              # OUTPUT_DIR / "literature_research.jsonl"
    cache_dir: Path,                # PROBLEM_DATA_DIR / "papers" (shared with deep_read)
    max_parallel: int = 5,
    search_reasoning: str = "medium",
    search_max_tokens: int = 16000,
    read_reasoning: str = "xhigh",
    read_max_tokens: int = 32000,
):
    """Stage 0 literature research: search → download → parallel deep-read.

    Three layers of resume:

    1. ``output_file`` (literature_research.jsonl) — when this final combined
       file exists, Stage 0 is fully done and we just replay it.
    2. ``search_picks_file`` (literature_search_picks.json) — caches the
       LLM-driven search step so we don't re-pay the search call.
    3. ``extracts_dir/<sid>.json`` (literature_extracts/) — per-paper cache.
       Each successful extraction is persisted **before** the reader worker
       returns, so a mid-Stage-0 crash leaves behind a per-paper sidecar that
       the next run reuses without re-calling the reader LLM. Only successful
       extractions are cached; errored entries (fetch_failed, LLM error) are
       retried on resume.

    The final combined ``output_file`` is written atomically (tmp + rename)
    so a half-written jsonl never masquerades as complete.

    Returns the list of paper-extraction dicts (also persisted on disk).
    """
    output_file       = Path(output_file)
    progress_root     = output_file.parent
    search_picks_file = progress_root / "literature_search_picks.json"
    extracts_dir      = progress_root / "literature_extracts"
    extracts_dir.mkdir(parents=True, exist_ok=True)

    if output_file.exists():
        existing = []
        for line in output_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing.append(json.loads(line))
            except Exception:
                continue
        print(f"[lit_research] [RESUME] {output_file.name} exists "
              f"({len(existing)} paper(s)) — skipping Stage 0")
        return existing

    # ── A. Search (cached at search_picks_file) ──────────────────────────
    picks = _load_cached_picks(search_picks_file)
    if picks is not None:
        print(f"[lit_research] [RESUME] reusing cached search picks "
              f"({len(picks)} paper(s)) from {search_picks_file.name}")
    else:
        search_prompt = SEARCH_PROMPT.format(
            problem=problem,
            past_notes_section=past_notes_section or "(no prior runs)",
        )
        print(f"\n{'='*80}\n[Stage 0] literature search (agent decides paper count)\n{'='*80}")

        if LIT_SEARCH_MIN_INTERVAL_SEC > 0:
            print(f"[lit_search] waiting for global injection slot "
                  f"(min_interval={LIT_SEARCH_MIN_INTERVAL_SEC}s, lock={LIT_SEARCH_RATE_LOCK_PATH})",
                  flush=True)
            waited = acquire_slot(LIT_SEARCH_MIN_INTERVAL_SEC, LIT_SEARCH_RATE_LOCK_PATH)
            print(f"[lit_search] slot acquired (waited {waited:.1f}s)", flush=True)

        search_text, _ = run_response(
            search_prompt,
            stage_name="lit_search",
            reasoning_effort=search_reasoning,
            verbosity="medium",
            max_output_tokens=search_max_tokens,
            web_search=True,
        )
        picks = _parse_search(search_text)
        if not picks:
            print("[lit_research] search returned no usable picks; Stage 0 produces no output.")
            # Persist the empty picks so resume doesn't re-pay the search call,
            # then write the (empty) final jsonl.
            _atomic_write_json(search_picks_file, [])
            _atomic_write_jsonl(output_file, [])
            return []
        _atomic_write_json(search_picks_file, picks)

    print(f"[lit_research] {len(picks)} paper(s) to process:")
    for p in picks:
        print(f"  • {p['title'] or '?'} — {p['url']}")

    # ── B+C. Fetch + Read (parallel per paper, per-paper resume cache) ───
    def _read_one(pick):
        url   = pick["url"]
        title = pick.get("title", "")
        why   = pick.get("why_relevant", "")
        sid   = _sanitize_id(url)
        cache_file = extracts_dir / f"{sid}.json"

        # Per-paper resume: a successful prior extraction is on disk.
        if cache_file.exists():
            try:
                cached_entry = json.loads(cache_file.read_text(encoding="utf-8"))
                print(f"[lit_research] [RESUME] reusing cached extraction for {url}")
                # Keep the original pick's metadata in case the cache is older
                # than the current pick (e.g., title got cleaned up).
                cached_entry["url"]          = url
                cached_entry.setdefault("title", title)
                cached_entry["why_relevant"] = why
                return cached_entry
            except Exception as exc:
                print(f"[lit_research] cached extraction unreadable for {url} "
                      f"({exc}); re-extracting")

        text, cached = _fetch_paper_text(url, cache_dir)
        aid = _arxiv_id_from_url(url) or sid
        base = {
            "url":                 url,
            "arxiv_id":            aid,
            "title":               title,
            "why_relevant":        why,
            "overall_summary":     "",
            "key_theorems_lemmas": [],
            "proof_techniques":    [],
            "other_useful_info":   "",
        }
        if not text:
            return {**base, "error": "fetch_failed"}

        prompt = READ_PROMPT.format(
            problem=problem,
            why_relevant=why or "(no rationale provided)",
            paper_text=text,
            arxiv_id=aid,
            url=url,
        )
        print(f"[lit_research] reading {url} "
              f"({'cached' if cached else 'fetched'}, paper={len(text)} chars)")

        if LIT_READ_MIN_INTERVAL_SEC > 0:
            waited = acquire_slot(LIT_READ_MIN_INTERVAL_SEC, LIT_READ_RATE_LOCK_PATH)
            print(f"[lit_read {aid}] slot acquired (waited {waited:.1f}s)", flush=True)

        try:
            txt, _ = run_response(
                prompt,
                stage_name=f"lit_read_{aid}",
                reasoning_effort=read_reasoning,
                verbosity="high",
                max_output_tokens=read_max_tokens,
                web_search=False,
            )
        except Exception as e:
            print(f"[lit_research] read error for {url}: {e}")
            return {**base, "error": str(e)[:300]}

        parsed = _parse_extraction(txt, aid, url, title)
        parsed["why_relevant"] = why
        # Persist the successful extraction BEFORE returning so a crash before
        # the main thread finishes draining the futures still leaves behind a
        # sidecar for the next run.
        _atomic_write_json(cache_file, parsed)
        return parsed

    results = []
    with ThreadPoolExecutor(max_workers=max_parallel) as ex:
        futures = {ex.submit(_read_one, p): p for p in picks}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futures[fut]
                print(f"[lit_research] worker error for {p.get('url','?')}: {e}")
                results.append({
                    "url":                 p.get("url", "?"),
                    "arxiv_id":            "",
                    "title":               p.get("title", ""),
                    "why_relevant":        p.get("why_relevant", ""),
                    "overall_summary":     "",
                    "key_theorems_lemmas": [],
                    "proof_techniques":    [],
                    "other_useful_info":   "",
                    "error":               str(e)[:300],
                })

    results.sort(key=lambda r: (r.get("arxiv_id") or "", r.get("url") or ""))

    # ── D. Save ──────────────────────────────────────────────────────────
    _atomic_write_jsonl(output_file, results)
    n_ok       = sum(1 for r in results if not r.get("error"))
    n_lemmas   = sum(len(r.get("key_theorems_lemmas") or []) for r in results)
    n_techs    = sum(len(r.get("proof_techniques")    or []) for r in results)
    print(f"[lit_research] saved {len(results)} paper(s) ({n_ok} successful) "
          f"with {n_lemmas} lemma(s) and {n_techs} technique(s) "
          f"to {output_file.name}")
    return results


def _atomic_write_jsonl(path: Path, records):
    """Write JSONL atomically: write to .tmp, then rename. Avoids leaving a
    half-written file that the resume check would mis-detect as complete."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
    tmp.replace(path)


def _atomic_write_json(path: Path, obj):
    """Single-object JSON variant of the atomic write helper. Used for the
    per-paper sidecar cache and the search-picks cache."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
    tmp.replace(path)


def _load_cached_picks(path: Path):
    """Return the parsed search picks list if the cache file exists and is
    valid, else None (caller re-runs the search)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[lit_research] cached search picks unreadable ({exc}); re-searching")
        return None
    if not isinstance(data, list):
        return None
    return data


# ─── Renderer used by Stage 1 to inject into the direction-writing prompt ─────

def format_literature_for_directions(records):
    """Render the Stage 0 paper extractions into a markdown section that gets
    inserted into the Stage 1 direction-writing prompt. Returns "" when there
    are no usable records."""
    if not records:
        return ""
    blocks = []
    for i, r in enumerate(records, 1):
        title = (r.get("title") or "(unknown title)").strip()
        url   = (r.get("url") or "").strip()
        aid   = (r.get("arxiv_id") or "").strip()
        head  = f"## Paper {i}. {title}"
        if r.get("error"):
            blocks.append(f"{head}\nURL: {url}\n*Extraction failed: {r.get('error')}*")
            continue

        lines = [head]
        if url:
            url_note = url
            if aid and aid not in url:
                url_note += f"  (arXiv:{aid})"
            lines.append(f"URL: {url_note}")
        why = (r.get("why_relevant") or "").strip()
        if why:
            lines.append(f"Why picked: {why}")

        summary = (r.get("overall_summary") or "").strip()
        if summary:
            lines.append(f"\n### Overall Summary\n{summary}")

        lemmas = r.get("key_theorems_lemmas") or []
        if lemmas:
            lines.append("\n### Key Theorems / Lemmas")
            for lem in lemmas:
                label  = (lem.get("label")        or "").strip()
                stmt   = (lem.get("statement")    or "").strip()
                sketch = (lem.get("proof_sketch") or "").strip()
                head_l = f"- **{label}.**" if label else "-"
                lines.append(f"{head_l} {stmt}")
                if sketch:
                    lines.append(f"  *Proof sketch:* {sketch}")

        techs = r.get("proof_techniques") or []
        if techs:
            lines.append("\n### Proof Techniques")
            for t in techs:
                name = (t.get("name")                     or "").strip()
                desc = (t.get("description")              or "").strip()
                appl = (t.get("applicability_to_problem") or "").strip()
                head_t = f"- **{name}.**" if name else "-"
                lines.append(f"{head_t} {desc}")
                if appl:
                    lines.append(f"  *Applicability:* {appl}")

        other = (r.get("other_useful_info") or "").strip()
        if other:
            lines.append(f"\n### Other Useful Info\n{other}")

        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
