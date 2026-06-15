#!/usr/bin/env python3
"""
Test submitter: reads each LaTeX problem from the input file,
sends it to an LLM via OpenRouter, and wraps the response
in a verbatim block so the output always compiles.
"""
import json
import os
import signal
import time
import requests

INPUT_PATH = "/data/input/input.json"
OUTPUT_DIR = "/data/output"

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
MODEL = "openrouter/free"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

SYSTEM_PROMPT = "You are a mathematician. Provide a clear, concise proof for the given problem."


class LLMTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise LLMTimeout(f"LLM call exceeded {TIMEOUT_SECONDS}s")


def call_llm(problem_latex: str) -> str:
    """Send the problem to the LLM and return the response text."""
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)
    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": problem_latex},
                ],
            },
        )
        signal.alarm(0)
    except LLMTimeout:
        raise
    finally:
        signal.signal(signal.SIGALRM, old_handler)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    if not content:
        raise ValueError("LLM returned empty response")
    return content


def call_llm_with_retries(problem_latex: str) -> str:
    """Call the LLM, retrying on rate limits and timeouts."""
    for attempt in range(MAX_RETRIES):
        try:
            return call_llm(problem_latex)
        except (requests.exceptions.HTTPError, LLMTimeout, ValueError) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 10 * (attempt + 1)
            print(f"    retry {attempt + 1}/{MAX_RETRIES} after {e}, waiting {wait}s...")
            time.sleep(wait)


with open(INPUT_PATH) as f:
    data = json.load(f)

os.makedirs(OUTPUT_DIR, exist_ok=True)

for problem in data["problems"]:
    pid = problem["id"]
    latex = problem["latex"]

    print(f"  {pid}: calling LLM...")
    answer = call_llm_with_retries(latex)
    print(f"  {pid}: got response ({len(answer)} chars)")

    # Wrap the LLM response in a verbatim block so the .tex always compiles
    proof_block = (
        "\n\\bigskip\n"
        "\\textbf{LLM Response:}\n\n"
        "\\begin{verbatim}\n"
        f"{answer}\n"
        "\\end{verbatim}\n"
    )

    if r"\end{document}" in latex:
        output = latex.replace(r"\end{document}", proof_block + r"\end{document}")
    else:
        output = latex + "\n" + proof_block

    output_path = os.path.join(OUTPUT_DIR, f"{pid}.tex")
    with open(output_path, "w") as f:
        f.write(output)

    print(f"  {pid}.tex written")
    time.sleep(10)  # wait 10s between problems

print(f"\nDone. Wrote {len(data['problems'])} files to {OUTPUT_DIR}")
