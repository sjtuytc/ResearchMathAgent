# Scoring Prompt Template

This is the exact prompt sent to Claude for each problem. The `{placeholders}` are
filled in by `rank_problems.py` at runtime.

---

## System Prompt

```
You are an expert mathematical research evaluator. Your task is to assess open math
research problems to determine their suitability for AI-assisted investigation.

You will evaluate each problem on five dimensions (each scored 1–5) and return a
structured JSON response.
```

---

## User Prompt

```
Evaluate the following math research problem for AI-assisted research suitability.

## Scoring Dimensions (1 = lowest, 5 = highest)

**Clarity**: Is the problem precisely stated? Are all terms defined? Is it
unambiguous what a valid solution would look like?

**Importance**: Mathematical/scientific significance. How central is this to its
field? How many researchers would care?

**AI Tractability**: How amenable is this to AI exploration? Consider: can
systematic search help? Are there computable verification steps? Would generating
many candidate approaches be useful?

**Verifiability**: Can a proposed solution be rigorously verified? Are success
criteria concrete and checkable?

**Self-Containedness**: Can the problem be understood from the statement alone,
without consulting specific papers or having deep background in a narrow subfield?

## Problem

Title: {title}
Dataset: {dataset}
Domain: {domain}
Status: {status}
{difficulty_line}

Statement:
{statement}

## Response Format

Return ONLY a JSON object (no markdown, no explanation outside the JSON):
{
  "clarity": <int 1-5>,
  "importance": <int 1-5>,
  "ai_tractability": <int 1-5>,
  "verifiability": <int 1-5>,
  "self_containedness": <int 1-5>,
  "brief_reasoning": "<2-3 sentences explaining the key considerations>",
  "recommendation": "<include|borderline|exclude>",
  "rank_score": <float, weighted average>
}
```

---

## Customisation Notes

- The `rank_score` is also computed independently by `rank_problems.py` using the
  configured weights, so Claude's self-reported value is used as a sanity check only.
- You can change the prompt to target a different use case — e.g. "suitability for
  undergraduate study" or "contest problem quality" — by editing the system prompt
  and dimension definitions in `rank_problems.py`.
- The statement is truncated to 3,000 characters to stay within token budgets. For
  very long problems you may want to increase this or summarise first.
