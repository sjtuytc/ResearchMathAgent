"""Librarian Package A — parametric-recall literature search.

Single CLI driver. Runs the 3-stage chain (gauntlet → narrower → chapter
picker) against the inputs in a problem directory, producing one
consolidated findings markdown file.

Inputs (in <problem-dir>/inputs/):
  - notebook.md         — the stuck-state notebook (any stage)
  - near_miss_proof.txt — best solver output that scored below threshold
  - gap_report.txt      — grader feedback identifying the gaps

Output:
  <problem-dir>/librarian_findings.md

All three stages use pure parametric recall conditioned on the inputs.
No web fetch, no SerpAPI, no PDF read. Books / monographs / lecture
notes are first-class citizens alongside papers (the 5/24 design — see
docs/retrieval_agent_design.md and README "Experimental: librarian-books
lit-search chain").

Companion driver Package B (separate, TBD) will take this findings file
and attempt to fetch the PDFs + distill them into compact .md summaries
suitable for --additional-materials.

Usage:
  python -m scripts.librarian run path/to/problem-dir
or:
  python scripts/librarian.py run path/to/problem-dir
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from math_solver.gemini import call_gemini  # noqa: E402


# ─── Configuration ─────────────────────────────────────────────────────────

N_DRAWS_GAUNTLET = 3
N_DRAWS_NARROWER = 3
MAX_CHAPTER_PICKER_REFS = 4  # cap parallel chapter-picker calls

# FP v2 (2026-05-30): no publication-date restriction. The 2026 cutoff was a
# FP-v1-only guard to keep runs clean of 2026 commentary/writeups ABOUT the v1
# challenge; v2 explicitly wants recent relevant literature (some problems are
# based on papers only a few months old).
CONTEST_DATE_RULE = ""


# ─── Prompts ───────────────────────────────────────────────────────────────

LIBRARIAN_PROMPT = """\
## RESEARCH LIBRARIAN (v3 — papers + books + monographs)

You are a research librarian helping a working mathematician trace prior
literature for an attempted proof that is *stuck*. Inputs: the
investigator's notebook, the near-miss proof, and the grader's
characterization of the gaps that blocked confirmation. Surface the
prior works you genuinely remember whose results or techniques bear on
either the proof itself or — preferably — on closing the specific gaps
the grader identified.

**What counts as a "prior work" (first-class — not just footnoted).**
Anything a working mathematician would cite in this area, including:

- Research papers (journal, conference, arxiv preprint)
- **Books and monographs** (research monographs, advanced textbooks,
  reference volumes — e.g., a Cambridge / Springer / AMS monograph that
  develops the relevant theory; treat these as primary citations, not
  as folklore backstops)
- **Lecture notes / course notes / book drafts** (including authors'
  personal-webpage manuscripts that the community treats as canonical
  references — these often live at `<institution>/~<author>/...` and
  may not have a DOI)
- Surveys and handbook chapters
- PhD theses

Recall the work as the form you actually remember it in. If you remember
a result as living in Chapter 4 of someone's book, say so — do not
substitute a paper that almost-says-the-same-thing.

**Topic-keyed substitutes** (replaces older "substitute for the whole work"
framing). The proof does NOT need the entire book — it needs a specific
result, technique, or chapter-level idea. Decouple the substitute search
from the canonical reference: for each entry, articulate the *specific
topic* the proof needs, then ask whether an openly-hosted source covers
**that topic** — the substitute may be an entirely different work.

Many canonical research monographs are publisher-locked (Springer
Ergebnisse / GTM, Cambridge tracts, AMS series, de Gruyter). Topic-level
substitutes for these are often available as:
- TIFR / IHÉS / MSRI / Bonn HIM / Park City lecture-notes volumes
- Summer-school proceedings, survey chapters on authors' homepages
- arxiv survey preprints
- A more recent paper that subsumes the older result (newer material
  is more likely to be open-access — arxiv has near-universal coverage
  for results since ~2000, and many authors post personal-webpage
  drafts of post-2010 books)
- A different book whose relevant chapter happens to be openly excerpted

Recall the canonical reference AND, where you remember one, a topic-keyed
substitute. The substitute does not need to be a version of the same
work.

**Hard rule: no speculation, especially for numeric IDs.**
- Do not invent titles, authors, venues, DOIs, ISBNs, or URLs.
- Do not invent arxiv IDs. Arxiv IDs that *look* plausible are easy to
  fabricate (e.g. "2104.05891"). If you are not certain an arxiv paper
  exists with a specific ID, OMIT THE FIELD entirely.
- "I don't remember the ID" is the correct answer when you don't.
- Empty is always better than confident fabrication.

{date_rule}

---
**Notebook:** {notebook}
---
**Near-miss proof:** {proof}
---
**Grader gap report (what blocked confirmation):** {gap_report}
---

For each work you remember:

- **Authors / Year** — as recalled; mark uncertain initials with [?]
- **Title** — verbatim if known, paraphrase + "(approx.)" if not, omit if unknown
- **Type** — one of: paper / book / monograph / lecture notes / thesis /
  survey / handbook chapter
- **Venue** — depending on type:
    - paper: journal/conference + volume/year (or arxiv)
    - book/monograph: publisher + year
    - lecture notes / book draft: institution + URL stem if you recall it
    - thesis: institution + year
- **External IDs (only if you actually remember them):**
    - `arxiv:XXXX.XXXXX` — modern format YYMM.NNNNN, or old format like "math/0411115"
    - `doi:10.xxxx/yyyy` — only if you remember it precisely
    - `isbn:...` — for books, only if you remember it precisely
    - If you don't remember any, leave this section empty. Do not guess.
- **Main result or relevant chapter/section** — one or two sentences of what
  it contains that bears on this proof. For a book, name the chapter or
  theorem; for a paper, the main theorem.
- **Topic needed for this proof** (one sentence) — the *specific* result,
  technique, lemma, or chapter-level idea the proof would draw from this
  work. Be narrower than the work itself. This is what the substitute
  search keys on.
- **Open-access substitute for that topic** (omit if none recalled) —
  use the form `(open-access for topic: <one-line topic>) — <substitute
  reference: authors / year / title / venue + URL stem if you have it>`.
  The substitute may be a different work entirely (survey, lecture notes,
  more recent paper subsuming the older result, etc.); newer materials
  are more likely to be open-access (arxiv has near-universal post-2000
  coverage; many authors post personal-webpage drafts of post-2010
  books). Leave empty if you do not remember an open-access source for
  the topic — empty is better than fabrication.
- **Connection** — which lemma, technique, or step here draws on or parallels
  it, OR which gap it might help close
- **Web search query** — a short, human-natural Google query that will
  surface an openly-hosted PDF of this work (or its substitute) when typed
  into Google. Aim for what a working mathematician would actually type —
  e.g. `cogdell lecture notes pdf`, `matringe essential whittaker pdf`,
  `taibleson fourier analysis local fields pdf`. Do NOT use the
  `filetype:pdf` operator. Do NOT wrap the title in quotes. Include the
  word `pdf` as a search term. Prefer 4-7 tokens. If you have no idea
  what query would find it, omit this field.
- **Confidence (bibliographic):** HIGH / PARTIAL / VAGUE
- **ID confidence (if you supplied one):** HIGH / PARTIAL — omit unless you supplied an ID.

If a technique is folklore, say so with a source.

If you sense a work exists but can't recall who or when, describe what to
search for rather than inventing names.

Aim for 4-10 works, including at least one book / monograph / lecture-note
object **if any genuinely bears on the gap**. Specific recall beats
comprehensive lists. **Recall without an ID is more valuable than a wrong ID.**
"""


AGGREGATOR_PROMPT = """\
## LIBRARIAN AGGREGATOR (v3 — papers + books + monographs)

Three research librarians independently produced lists of prior works
they remember as related to the proof below. Union, deduplicate, and sort
into four buckets. Preserve any arxiv IDs / DOIs / ISBNs the librarians
supplied, but only when at least one librarian gave HIGH ID-confidence; if
two librarians disagreed on the ID, mark it as DISPUTED and report both.

**Buckets:** VERY RELATED / RELATED / SOMEWHAT RELATED / NOT MUCH
(judged by load-bearing weight on the proof and on closing the grader's
gap.)

**Discipline:**
- Do not invent IDs. If no librarian supplied one with HIGH confidence,
  the entry should have no ID.
- Deduplicate aggressively across the three reports. A book and a paper
  by the same author covering the same theorem are separate entries —
  prefer the book if it's the canonical reference.
- Preserve the Type field.
- Brief one-line connection per entry.

{date_rule}

---
**Notebook:** {notebook}
---
**Near-miss proof:** {proof}
---
**Grader gap report:** {gap_report}
---
**Librarian Report 1:**
{report_1}
---
**Librarian Report 2:**
{report_2}
---
**Librarian Report 3:**
{report_3}
---

Output format:

## VERY RELATED
- [Type] Authors / Year — Title — Venue — IDs: arxiv:XXXX.XXXXX | doi:10.xxxx/yyyy | isbn:... (or "no ID") — (one-line connection) — search: <human-natural Google query that finds an open PDF, e.g. "cogdell lecture notes pdf">
...

When aggregating, preserve any `search:` query from the input librarian
reports verbatim. If the input reports disagree on the query for the same
work, pick the one that looks most likely to return an open PDF (shorter
and more author-name-focused is usually better). If no input report
supplied a query, omit the `— search: ...` suffix.

## RELATED
- ...

## SOMEWHAT RELATED
- ...

## NOT MUCH
- ...
"""


NARROWER_PROMPT = """\
## RESEARCH LIBRARIAN — NARROWER PASS

A previous librarian pass produced a list of works (papers, books,
monographs, lecture notes, surveys, theses) recalled from parametric
memory as potentially related to a stuck proof attempt. The list errs
on the side of breadth.

Your job: triage the list against the specific gaps the grader
identified. For each entry, judge from what you know of that work's
scope whether it plausibly *addresses* one of the named gaps — not
merely "is in the neighborhood".

You are NOT verifying with PDFs. Use parametric memory of each work's
contents. If you don't remember a work well enough to judge, say so —
"unfamiliar" is a valid bucket.

---
**Notebook:** {notebook}
---
**Near-miss proof:** {proof}
---
**Grader gap report (the gaps to address):** {gap_report}
---
**Aggregated list from prior librarian pass:**
{prior_list}
---

For each entry in the list, place it in exactly one of these buckets:

## LOAD-BEARING
Works whose contents you remember well enough to be confident they
contain machinery directly addressing a specific gap. For each:
- The entry (verbatim from the list)
- The specific gap it addresses (cite the gap by name/number)
- One sentence: which chapter/theorem/section is the load-bearing piece

## SUPPORTING
Works likely useful as background or to verify a step, but not
themselves closing a gap. One-line note each.

## REDUNDANT
Works that overlap with a LOAD-BEARING entry. Name the overlap.

## PERIPHERAL
In the neighborhood but no concrete connection to the named gaps.

## UNFAMILIAR
You don't remember the work's contents well enough to judge.

Rules:
- Every entry goes in exactly one bucket.
- LOAD-BEARING should be selective — aim for 2-4 entries.
- Do not invent gap numbers. Cite the grader's actual gap names.
"""


CHAPTER_PICKER_PROMPT = """\
## CHAPTER PICKER (parametric)

You are pointing a working mathematician at the specific chapters and
sections of a reference that would help close named gaps in a stuck
proof. Use your parametric memory of the work's table of contents — you
do NOT have the PDF in hand.

**The reference:**
- Title: {title}
- Author(s): {authors}
- Year / publisher: {venue}
- What it covers (one line from prior recall): {one_line}

**The problem and where it is stuck.**

Notebook:
---
{notebook}
---

Near-miss proof:
---
{proof}
---

Grader gap report:
---
{gap_report}
---

Your task: list the chapters / sections / theorems that would help close
these gaps. For each pick:

- **Chapter or section number + title** (mark "(approx.)" if guessing)
- **Which gap it addresses**
- **Why** — one or two sentences. Name specific theorems / lemmas if you remember.

Rules:
- Pick 2-5 entries. Tight selection beats broad.
- "I cannot recall chapter numbers" is valid — do not fabricate.
- "(beyond grader's named gaps)" is a valid flag for a chapter that
  helps an unstated gap.
- "I do not believe this reference actually addresses any of the named
  gaps" is a valid conclusion.
"""


# ─── ID extraction ────────────────────────────────────────────────────────

ARXIV_RE = re.compile(r"arxiv[:\s]*([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/\d{7})", re.IGNORECASE)
DOI_RE = re.compile(r"doi[:\s]*(10\.\d{4,9}/[\-._;()/:A-Z0-9]+)", re.IGNORECASE)
ISBN_RE = re.compile(r"isbn[:\s]*([\d\-Xx]{10,17})", re.IGNORECASE)


def extract_ids(text: str) -> dict:
    arxiv_raw = sorted(set(m.group(1) for m in ARXIV_RE.finditer(text)))
    arxiv_kept = arxiv_raw  # FP v2: no date restriction (was: drop 2026+ arxiv ids)
    arxiv_dropped_2026: list[str] = []
    doi = sorted(set(m.group(1).rstrip(".,);") for m in DOI_RE.finditer(text)))
    isbn = sorted(set(m.group(1) for m in ISBN_RE.finditer(text)))
    return {
        "arxiv": arxiv_kept, "arxiv_dropped_2026": arxiv_dropped_2026,
        "doi": doi, "isbn": isbn,
    }


# ─── Substitute extraction ────────────────────────────────────────────────

# Entries the chapter picker can productively ask about: books, monographs,
# lecture notes, surveys, handbook chapters, theses. NOT plain papers (those
# don't have chapter structure worth picking from).
BOOK_TYPES = {"book", "monograph", "lecture notes", "handbook chapter",
              "survey", "thesis"}

# Match a bullet entry of the form "- [Type] Authors / Year — Title — Venue — …"
ENTRY_RE = re.compile(
    r"^-\s*\[(?P<type>[^\]]+)\]\s*"
    r"(?P<authors>[^/]+?)\s*/\s*(?P<year>[^—]+?)\s*—\s*"
    r"(?P<title>[^—]+?)\s*—\s*"
    r"(?P<venue>[^—]+?)\s*—\s*"
    r"(?P<rest>.+)$",
    re.MULTILINE,
)


def extract_book_substitutes(narrower_text: str, max_n: int) -> list[dict]:
    """Pull book-like entries from the LOAD-BEARING and SUPPORTING sections
    of the narrower output. Returns up to max_n dicts ready for chapter
    picker.  Entries from LOAD-BEARING come first; SUPPORTING fills the
    rest."""
    out: list[dict] = []
    seen_titles: set[str] = set()

    for bucket in ("LOAD-BEARING", "SUPPORTING"):
        bm = re.search(
            rf"##\s*{bucket}\s*\n(.*?)(?=^##\s|\Z)",
            narrower_text, re.MULTILINE | re.DOTALL,
        )
        if not bm:
            continue
        section = bm.group(1)
        for em in ENTRY_RE.finditer(section):
            type_ = em.group("type").strip().lower()
            if type_ not in BOOK_TYPES:
                continue
            title = em.group("title").strip()
            key = title.lower()[:60]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            one_line = em.group("rest").strip()
            # Strip a leading "no ID" / IDs prefix if present
            one_line = re.sub(r"^(IDs?:[^—]+—\s*)", "", one_line).strip()
            # Drop trailing parenthetical "(one-line connection)" header text
            one_line = one_line.lstrip("—– ").strip()
            out.append({
                "type": type_,
                "title": title,
                "authors": em.group("authors").strip(),
                "venue": em.group("venue").strip() + ", " + em.group("year").strip(),
                "one_line": one_line[:300],
            })
            if len(out) >= max_n:
                return out
    return out


# ─── Stage callers ────────────────────────────────────────────────────────

async def stage1_one_draw(draw_i: int, run_tag: str, inputs: dict) -> str:
    prompt = LIBRARIAN_PROMPT.format(date_rule=CONTEST_DATE_RULE, **inputs)
    call = await call_gemini(
        prompt,
        run_id=run_tag, notebook_id=f"{run_tag}_gauntlet_draw{draw_i}",
        agent="research_librarian_v3",
        inputs={"stage": "gauntlet", "draw": draw_i}, store=None,
    )
    return call.output


async def stage1_aggregate(run_tag: str, inputs: dict, draws: list[str]) -> str:
    prompt = AGGREGATOR_PROMPT.format(
        date_rule=CONTEST_DATE_RULE, **inputs,
        report_1=draws[0], report_2=draws[1], report_3=draws[2],
    )
    call = await call_gemini(
        prompt,
        run_id=run_tag, notebook_id=f"{run_tag}_gauntlet_agg",
        agent="research_librarian_v3_aggregator",
        inputs={"stage": "gauntlet_aggregate"}, store=None,
    )
    return call.output


async def stage2_one_draw(draw_i: int, run_tag: str, inputs: dict, prior_list: str) -> str:
    prompt = NARROWER_PROMPT.format(**inputs, prior_list=prior_list)
    call = await call_gemini(
        prompt,
        run_id=run_tag, notebook_id=f"{run_tag}_narrower_draw{draw_i}",
        agent="research_librarian_narrower_v1",
        inputs={"stage": "narrower", "draw": draw_i}, store=None,
    )
    return call.output


async def stage3_pick(run_tag: str, sub: dict, inputs: dict) -> str:
    prompt = CHAPTER_PICKER_PROMPT.format(
        title=sub["title"], authors=sub["authors"], venue=sub["venue"],
        one_line=sub["one_line"], **inputs,
    )
    surname = sub["authors"].split()[-1].lower() if sub["authors"] else "ref"
    call = await call_gemini(
        prompt,
        run_id=run_tag, notebook_id=f"{run_tag}_chapter_{surname}",
        agent="chapter_picker_v1",
        inputs={"stage": "chapter_picker", "ref": sub["title"]}, store=None,
    )
    return call.output


# ─── Driver ───────────────────────────────────────────────────────────────

def _load_inputs(problem_dir: Path) -> dict:
    inputs_dir = problem_dir / "inputs"
    required = ("notebook.md", "near_miss_proof.txt", "gap_report.txt")
    missing = [n for n in required if not (inputs_dir / n).exists()]
    if missing:
        # Tolerate notebook_post_stageN.md as a notebook.md substitute
        nb_alts = sorted(inputs_dir.glob("notebook*.md"))
        if "notebook.md" in missing and nb_alts:
            missing.remove("notebook.md")
            notebook_path = nb_alts[0]
        else:
            raise click.UsageError(
                f"Missing required inputs in {inputs_dir}: {', '.join(missing)}"
            )
    else:
        notebook_path = inputs_dir / "notebook.md"
    return {
        "notebook": notebook_path.read_text(encoding="utf-8"),
        "proof": (inputs_dir / "near_miss_proof.txt").read_text(encoding="utf-8"),
        "gap_report": (inputs_dir / "gap_report.txt").read_text(encoding="utf-8"),
    }


async def _run(problem_dir: Path, run_tag: str) -> Path:
    inputs = _load_inputs(problem_dir)
    sizes = {k: len(v) for k, v in inputs.items()}
    click.echo(f"[librarian] inputs: {sizes}")

    # Stage 1: gauntlet
    click.echo(f"[librarian] stage 1 — gauntlet ({N_DRAWS_GAUNTLET} draws + aggregator)…")
    draws1 = await asyncio.gather(*(
        stage1_one_draw(i, run_tag, inputs) for i in range(N_DRAWS_GAUNTLET)
    ))
    agg = await stage1_aggregate(run_tag, inputs, draws1)
    agg_ids = extract_ids(agg)
    union_ids = extract_ids(agg + "\n" + "\n".join(draws1))
    click.echo(f"[librarian]   aggregator: {len(agg)} chars, "
               f"arxiv={len(agg_ids['arxiv'])} doi={len(agg_ids['doi'])} isbn={len(agg_ids['isbn'])}")

    # Stage 2: narrower
    click.echo(f"[librarian] stage 2 — narrower ({N_DRAWS_NARROWER} draws)…")
    draws2 = await asyncio.gather(*(
        stage2_one_draw(i, run_tag, inputs, agg) for i in range(N_DRAWS_NARROWER)
    ))
    # Use draw 0 as the canonical narrowing for substitute extraction;
    # other draws are recorded for variance inspection.
    narrowing = draws2[0]
    substitutes = extract_book_substitutes(narrowing, MAX_CHAPTER_PICKER_REFS)
    click.echo(f"[librarian]   narrower draws: {[len(d) for d in draws2]} chars; "
               f"book-like substitutes extracted: {len(substitutes)}")

    # Stage 3: chapter picker (skip if no book-like substitutes)
    chapter_outputs: list[tuple[dict, str]] = []
    if substitutes:
        click.echo(f"[librarian] stage 3 — chapter picker on {len(substitutes)} substitutes…")
        picks = await asyncio.gather(*(
            stage3_pick(run_tag, sub, inputs) for sub in substitutes
        ))
        chapter_outputs = list(zip(substitutes, picks))
    else:
        click.echo("[librarian] stage 3 — skipped (no book-like substitutes in narrower's LOAD-BEARING/SUPPORTING).")

    # Compose consolidated findings
    out_path = problem_dir / "librarian_findings.md"
    lines: list[str] = [
        f"# Librarian Findings — {run_tag}",
        f"**Generated:** {datetime.now().isoformat(timespec='seconds')}  ",
        f"**Inputs:** notebook={sizes['notebook']} chars, "
        f"proof={sizes['proof']} chars, gap_report={sizes['gap_report']} chars  ",
        f"**Date restriction:** none (FP v2 — recent works allowed)  ",
        "",
        "---",
        "",
        "## Citation IDs (aggregator-only)",
        f"```json\n{json.dumps(agg_ids, indent=2)}\n```",
        "",
        "## Citation IDs (union: aggregator + all draws)",
        f"```json\n{json.dumps(union_ids, indent=2)}\n```",
        "",
        "---",
        "",
        "# Stage 1 — Gauntlet (aggregator output)",
        "",
        agg,
        "",
        "---",
        "",
        "# Stage 2 — Narrower (draw 0, canonical)",
        "",
        narrowing,
        "",
    ]
    if chapter_outputs:
        lines += ["---", "", "# Stage 3 — Chapter Picker", ""]
        for sub, out in chapter_outputs:
            lines += [
                f"## {sub['title']} ({sub['authors']}, {sub['venue']})",
                f"_({sub['one_line']})_",
                "",
                out,
                "",
            ]
    lines += ["---", "", "# Stage 2 — Narrower (additional draws, for variance)"]
    for i, d in enumerate(draws2[1:], start=1):
        lines += [f"## Narrower draw {i}", d, ""]
    lines += ["---", "", "# Stage 1 — Gauntlet (raw draws, for variance)"]
    for i, d in enumerate(draws1):
        lines += [f"## Gauntlet draw {i}", d, ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"[librarian] wrote {out_path} ({out_path.stat().st_size} bytes)")
    return out_path


@click.group()
def cli() -> None:
    """Librarian Package A — parametric-recall literature search."""


@cli.command("run")
@click.argument("problem_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--tag", default=None,
              help="Run tag for telemetry (default: derived from dir name + date).")
def run_cmd(problem_dir: Path, tag: str | None) -> None:
    """Run gauntlet → narrower → chapter picker on PROBLEM_DIR.

    PROBLEM_DIR must contain an inputs/ subdirectory with:
      notebook.md (or notebook*.md), near_miss_proof.txt, gap_report.txt

    Output: PROBLEM_DIR/librarian_findings.md
    """
    if tag is None:
        tag = f"librarian_{problem_dir.name}_{datetime.now().strftime('%Y%m%d')}"
    asyncio.run(_run(problem_dir, tag))


if __name__ == "__main__":
    cli()
