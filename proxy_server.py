"""Lightweight reverse proxy that routes /rmac/solve → solve app and
/rmac/filter → filter app.

Run on the public-facing port (8001 dev / 8000 prod). The two backend apps
run on internal ports and are entirely independent — if one crashes the other
keeps running and this proxy returns 502 only for that path.

Handles:
  - Regular JSON/HTML responses
  - Server-Sent Events (SSE) streams — forwarded chunk by chunk
  - Static file responses
  - Arbitrary request bodies (POST/PATCH/etc.)
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

SOLVE_ORIGIN = os.environ.get("RMAC_SOLVE_ORIGIN", "http://127.0.0.1:8011")
FILTER_ORIGIN = os.environ.get("RMAC_FILTER_ORIGIN", "http://127.0.0.1:8012")

_SKIP_HEADERS = {"host", "transfer-encoding", "content-length"}

app = FastAPI(title="rmac proxy", docs_url=None, redoc_url=None)

_client = httpx.AsyncClient(timeout=600.0, follow_redirects=False)


def _forward_headers(request: Request) -> dict:
    return {
        k: v for k, v in request.headers.items()
        if k.lower() not in _SKIP_HEADERS
    }


async def _proxy(request: Request, origin: str, path: str) -> Response:
    url = f"{origin}/{path.lstrip('/')}"
    if request.url.query:
        url += f"?{request.url.query}"

    body = await request.body()
    headers = _forward_headers(request)

    is_sse = "text/event-stream" in request.headers.get("accept", "")

    try:
        if is_sse:
            # Stream SSE chunk by chunk
            async def _stream():
                async with _client.stream(
                    request.method, url,
                    headers=headers,
                    content=body or None,
                ) as resp:
                    async for chunk in resp.aiter_bytes(chunk_size=512):
                        yield chunk

            return StreamingResponse(
                _stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        else:
            resp = await _client.request(
                request.method, url,
                headers=headers,
                content=body or None,
            )
            # Forward all response headers except hop-by-hop ones
            out_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in {"transfer-encoding", "content-encoding",
                                     "connection", "keep-alive"}
            }
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=out_headers,
                media_type=resp.headers.get("content-type"),
            )
    except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
        service = "solve" if origin == SOLVE_ORIGIN else "filter"
        return Response(
            content=f"Service '{service}' is unavailable: {exc}",
            status_code=502,
            media_type="text/plain",
        )


# ── Root redirects ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return RedirectResponse("/rmac/solve/", status_code=302)


@app.get("/rmac")
async def rmac_root():
    return RedirectResponse("/rmac/solve/", status_code=302)


@app.get("/rmac/")
async def rmac_slash():
    return RedirectResponse("/rmac/solve/", status_code=302)


@app.get("/rmac/solve")
async def solve_root():
    return RedirectResponse("/rmac/solve/", status_code=302)


@app.get("/rmac/filter")
async def filter_root():
    return RedirectResponse("/rmac/filter/", status_code=302)


# ── Solve routes ──────────────────────────────────────────────────────────────

@app.api_route("/rmac/solve/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_solve(request: Request, path: str = ""):
    return await _proxy(request, SOLVE_ORIGIN, path)


# ── Filter routes ─────────────────────────────────────────────────────────────

@app.api_route("/rmac/filter/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_filter(request: Request, path: str = ""):
    return await _proxy(request, FILTER_ORIGIN, path)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "solve": SOLVE_ORIGIN, "filter": FILTER_ORIGIN}
