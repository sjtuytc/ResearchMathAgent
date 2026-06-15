"""Web search backend — Gemini Google Search grounding (default) or Tavily."""
from __future__ import annotations

import os
from typing import Literal

WebBackend = Literal["gemini_grounding", "tavily", "none"]

_BACKEND: WebBackend = os.environ.get("WEB_SEARCH_BACKEND", "gemini_grounding")  # type: ignore


async def web_search(query: str, *, recency: str = "any") -> list[dict]:
    """
    Run a web search. Returns list of {title, url, snippet} dicts.
    For Gemini grounding, the actual web retrieval happens inside the
    Gemini call (pass use_google_search=True to gemini.call_gemini).
    This function is used when we want standalone web results pre-call.
    """
    if _BACKEND == "tavily":
        return await _tavily_search(query, recency=recency)
    # gemini_grounding: handled inline during the agent call; return empty
    return []


async def _tavily_search(query: str, *, recency: str = "any") -> list[dict]:
    try:
        from tavily import AsyncTavilyClient  # type: ignore
    except ImportError:
        raise RuntimeError("Install tavily-python: pip install tavily-python")

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set TAVILY_API_KEY environment variable")

    client = AsyncTavilyClient(api_key=api_key)
    days = 548 if recency == "recent" else None  # ~18 months
    result = await client.search(query, max_results=10, days=days,
                                  include_raw_content=False)
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": r.get("content", "")}
        for r in result.get("results", [])
    ]
