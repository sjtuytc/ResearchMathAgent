"""Google Cloud Vertex AI (Claude via ADC) helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_REGION = "global"
DEFAULT_MODEL = "claude-opus-4-8"


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
