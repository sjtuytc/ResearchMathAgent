"""Shared OpenAI API helper for verifier_v2."""
from __future__ import annotations
import os, json
from time import sleep, monotonic
from pathlib import Path
import openai

QUEUED_TIMEOUT      = int(os.getenv("QUEUED_TIMEOUT_SECONDS",      str(30 * 60)))
IN_PROGRESS_TIMEOUT = int(os.getenv("IN_PROGRESS_TIMEOUT_SECONDS", str(60 * 60)))

_COST_LOG: list[dict] = []

# gpt-5.5-pro pricing per 1M tokens (approximate)
_INPUT_PRICE  = float(os.getenv("INPUT_TOKEN_PRICE_PER_1M",  "15.0"))
_OUTPUT_PRICE = float(os.getenv("OUTPUT_TOKEN_PRICE_PER_1M", "60.0"))

def get_client() -> openai.OpenAI:
    return openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def _compute_cost(usage) -> float:
    if usage is None:
        return 0.0
    inp  = getattr(usage, "input_tokens", 0) or 0
    out  = getattr(usage, "output_tokens", 0) or 0
    return (inp * _INPUT_PRICE + out * _OUTPUT_PRICE) / 1_000_000

def get_total_cost() -> float:
    return sum(e["cost_usd"] for e in _COST_LOG)

def get_cost_log() -> list[dict]:
    return list(_COST_LOG)

def save_cost_log(path: str | Path) -> None:
    with open(path, "w") as f:
        for entry in _COST_LOG:
            f.write(json.dumps(entry) + "\n")
        f.write(json.dumps({"total_cost_usd": get_total_cost(), "calls": len(_COST_LOG)}) + "\n")

def call_api(
    prompt: str,
    stage: str,
    reasoning: str = "medium",
    max_tokens: int = 32_000,
    web_search: bool = False,
    max_retries: int | None = None,
) -> str:
    """Submit a background API call.

    Mirrors `harness.run_response` retry semantics:
      - network / SDK exceptions → log, sleep 10s, resubmit
      - job stuck in `queued` beyond QUEUED_TIMEOUT → cancel + resubmit
      - non-`completed` terminal status (failed/cancelled/incomplete) →
        log, sleep 10s, resubmit
      - no `in_progress` timeout (a running job is allowed to take as long
        as it needs)

    `max_retries`:
        None (default) — retry forever until status == "completed".
            Use for any call whose empty output would be silently treated
            as success (verifier scorers, polish, typeset, etc.).
        int — bounded retry; returns "" on exhaustion. Use only for
            best-effort calls whose caller tolerates an empty response
            (e.g. opportunistic numerical-code rewrite in prechecker).
    """
    client = get_client()
    print(f"[{stage}] reasoning={reasoning} max_tokens={max_tokens} "
          f"web_search={web_search} max_retries={max_retries or 'inf'}")
    attempt = 0
    while max_retries is None or attempt < max_retries:
        attempt += 1
        response = None
        try:
            kwargs: dict = dict(
                model=os.getenv("MODEL", "gpt-5.5-pro"),
                input=[{"role": "user", "content": prompt}],
                reasoning={"effort": reasoning},
                max_output_tokens=max_tokens,
                background=True,
                service_tier="priority",
            )
            if web_search:
                kwargs["tools"] = [{"type": "web_search"}]
                kwargs["tool_choice"] = "auto"
                kwargs["include"] = ["web_search_call.action.sources"]
            response = client.responses.create(**kwargs)
            print(f"[{stage}] submitted {response.id}")

            poll = 0
            queued_since = None
            cancelled = False
            while response.status in {"queued", "in_progress"}:
                sleep(2)
                poll += 1
                if poll % 50 == 0:
                    print(f"[{stage}] {response.status} after {poll * 2}s")
                response = client.responses.retrieve(response.id)
                if response.status == "queued":
                    if queued_since is None:
                        queued_since = monotonic()
                    elif monotonic() - queued_since > QUEUED_TIMEOUT:
                        print(
                            f"[{stage}] job {response.id} stuck in 'queued' for "
                            f">{QUEUED_TIMEOUT//60} min — cancelling and resubmitting"
                        )
                        try:
                            client.responses.cancel(response.id)
                        except Exception as cancel_exc:
                            print(f"[{stage}] cancel error (ignoring): {cancel_exc}")
                        cancelled = True
                        break
                else:
                    queued_since = None  # running; reset so a re-queue would be caught

            if cancelled:
                continue

            if response.status == "completed":
                cost = _compute_cost(response.usage)
                inp  = getattr(response.usage, "input_tokens", 0) if response.usage else 0
                out  = getattr(response.usage, "output_tokens", 0) if response.usage else 0
                _COST_LOG.append({"stage": stage, "cost_usd": cost,
                                   "input_tokens": inp, "output_tokens": out,
                                   "response_id": response.id})
                print(f"[{stage}] done  cost=${cost:.4f}  tokens(in={inp} out={out})")
                return response.output_text or ""

            print(f"[{stage}] non-completed status: {response.status} | {response}")
            sleep(10)

        except Exception as e:
            print(f"[{stage}] error: {e}")
            if response is not None:
                try: client.responses.cancel(response.id)
                except: pass
            sleep(10)
    print(f"[{stage}] max_retries={max_retries} exhausted — returning empty string")
    return ""
