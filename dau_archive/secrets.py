"""Local admin-managed credentials; never return the credential from an API."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .db import data_dir


def settings_path() -> Path:
    return data_dir() / "secret_settings.json"


def gemini_key() -> str:
    environment_key = os.getenv("GEMINI_API_KEY", "").strip()
    if environment_key:
        return environment_key
    try:
        return str(json.loads(settings_path().read_text(encoding="utf-8")).get("gemini_api_key", "")).strip()
    except (OSError, ValueError, TypeError):
        return ""


def gemini_key_source() -> str:
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "environment"
    return "local" if gemini_key() else "none"


def save_gemini_key(value: str) -> None:
    target = settings_path()
    temporary = target.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"gemini_api_key": value}, output)
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def delete_gemini_key() -> None:
    settings_path().unlink(missing_ok=True)
