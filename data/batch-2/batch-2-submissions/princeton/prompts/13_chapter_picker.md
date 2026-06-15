# Chapter Picker — parametric chapter selection per substitute

**Source of truth:** `scratch/2026-05-24_librarian_books/chapter_picker_q7.py`
**Status:** experimental (scratch). Not loaded by the live pipeline.
**Stage 3 of 3** in the new lit-search chain. See `00_README.md`.

For each open-access substitute the librarian named (stage 1), a separate
Gemini call asks which chapters/sections of that work address the
grader's named gaps. Pure parametric — does not read the PDF.

---

## CHAPTER_PICKER_PROMPT

```
## CHAPTER PICKER (parametric)

You are pointing a working mathematician at the specific chapters and
sections of an open-access reference that would help close named gaps
in a stuck proof. Use your parametric memory of the work's table of
contents and structure — you do NOT have the PDF in hand.

**The reference:**
- Title: {title}
- Author(s): {authors}
- Year / publisher: {venue}
- What it covers (one line from prior recall): {one_line}

**The problem and where it is stuck.**

Notebook (post-stage-4 state of the pipeline's investigation):
---
{notebook}
---

Near-miss proof:
---
{proof}
---

Grader gap report (the specific gaps to address):
---
{gap_report}
---

Your task: list the chapters / sections / theorems of the named reference
that would help close these gaps. Be specific. For each pick:

- **Chapter or section number + title** (as you remember it; mark
  "(approx.)" if you're guessing the exact section number)
- **Which gap it addresses** (cite the grader's gap by name/number)
- **Why** — one or two sentences on what that chapter contains that
  closes (or helps close) the gap. Name specific theorems, lemmas, or
  constructions if you remember them.

Rules:
- Pick 2-5 entries. Tight selection beats broad.
- If you don't remember the work's structure well enough to make
  chapter-level picks, say so explicitly — "I remember the book covers
  X at a high level, but cannot recall chapter numbers" is a valid
  output. Do not fabricate chapter numbers.
- If a chapter helps an *unnamed* gap (one the grader didn't list but
  the proof clearly has), flag it as "(beyond grader's named gaps)".
- "I do not believe this reference actually addresses any of the named
  gaps" is a valid conclusion if you've reconsidered.

```
