"""Google Cloud Vertex AI (Claude via ADC) helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_REGION = "us-east5"  # primary Anthropic-on-Vertex region
DEFAULT_MODEL = "claude-opus-4-8"

# USD per million tokens (estimates — Vertex list prices, may differ from your contract).
_VERTEX_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.8, 4.0),
    "default": (15.0, 75.0),
}


def estimate_vertex_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Rough USD estimate for a Vertex Claude call from token counts."""
    in_rate, out_rate = _VERTEX_PRICING_PER_MTOK.get(model, _VERTEX_PRICING_PER_MTOK["default"])
    billable_in = (
        int(input_tokens)
        + int(cache_read_input_tokens) * 0.1
        + int(cache_creation_input_tokens) * 1.25
    )
    return round(
        billable_in / 1_000_000 * in_rate + int(output_tokens) / 1_000_000 * out_rate,
        6,
    )


def gcp_console_urls(project_id: str) -> dict[str, str]:
    """Deep links into the GCP console for billing and Vertex usage."""
    pid = (project_id or "").strip()
    if not pid:
        return {}
    return {
        "billing": f"https://console.cloud.google.com/billing/reports?project={pid}",
        "vertex_usage": (
            f"https://console.cloud.google.com/vertex-ai/generative/language/usage?project={pid}"
        ),
        "dashboard": f"https://console.cloud.google.com/home/dashboard?project={pid}",
    }


def adc_credentials_path() -> Path | None:
    env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    default = Path.home() / ".config/gcloud/application_default_credentials.json"
    return default if default.is_file() else None


def vertex_adc_project() -> str:
    """Resolve the GCP project for Vertex billing/quota."""
    env = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if env:
        return env

    path = adc_credentials_path()
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("quota_project_id", "project_id"):
                val = str(data.get(key) or "").strip()
                if val:
                    return val
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    try:
        import google.auth

        _, project = google.auth.default()
        return str(project or "").strip()
    except Exception:
        return ""


def vertex_region() -> str:
    return os.environ.get("GOOGLE_CLOUD_REGION", DEFAULT_REGION).strip() or DEFAULT_REGION


def vertex_status() -> dict:
    """Return whether Vertex AI via ADC is ready, plus project/region metadata."""
    path = adc_credentials_path()
    project = vertex_adc_project()
    region = vertex_region()
    error = ""

    try:
        from anthropic import AnthropicVertex  # noqa: F401
    except ImportError:
        return {
            "available": False,
            "project": project,
            "region": region,
            "model": DEFAULT_MODEL,
            "adc_path": str(path) if path else "",
            "error": "anthropic[vertex] is not installed",
        }

    try:
        import google.auth  # noqa: F401
    except ImportError:
        return {
            "available": False,
            "project": project,
            "region": region,
            "model": DEFAULT_MODEL,
            "adc_path": str(path) if path else "",
            "error": "google-auth is not installed (run start_server.sh to install .deps)",
        }

    if path is None:
        error = "ADC credentials not found (~/.config/gcloud/application_default_credentials.json)"
    elif not project:
        error = "GCP project not resolved; set GOOGLE_CLOUD_PROJECT or run gcloud auth application-default login with a quota project"
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("type") == "service_account" and not data.get("private_key"):
                error = "service account key file is incomplete"
            elif data.get("type") == "authorized_user" and not data.get("refresh_token"):
                error = "ADC authorized_user credentials have no refresh_token"
        except (OSError, json.JSONDecodeError):
            error = "ADC credentials file is unreadable"

    return {
        "available": not error,
        "project": project,
        "region": region,
        "model": DEFAULT_MODEL,
        "adc_path": str(path) if path else "",
        "error": error,
    }
