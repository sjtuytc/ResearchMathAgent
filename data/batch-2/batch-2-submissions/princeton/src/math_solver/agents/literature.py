"""Literature Agent — answers specific concrete questions about papers."""
from __future__ import annotations

from pathlib import Path

from ..gemini import call_gemini


# ── Prompt ───────────────────────────────────────────────────────────────────
# Deliberately simple — just answers specific, concrete questions.
_PROMPT_TEMPLATE = """\
# PASTE YOUR LITERATURE AGENT PROMPT HERE
#
# Placeholders:
#   {question}      — the specific question to answer
#   {paper_summary} — text or excerpt from the paper

[Question]
{question}

[Paper Content]
{paper_summary}
"""


async def answer_literature_question(
    *,
    question: str,
    paper_summary: str,
    notebook_id: str,
    run_id: str,
    pdf_paths: list[Path] | None = None,
    store=None,
) -> str:
    prompt = _PROMPT_TEMPLATE.format(question=question, paper_summary=paper_summary)
    call = await call_gemini(
        prompt,
        run_id=run_id,
        notebook_id=notebook_id,
        agent="literature",
        inputs={"question": question[:200]},
        pdf_paths=pdf_paths,
        store=store,
    )
    return call.output
