"""List accessible Gemini model names without exposing the credential."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dau_archive.secrets import gemini_key


def list_models():
    key = gemini_key()
    if not key:
        raise SystemExit("Set GEMINI_API_KEY or enter it in Cài đặt API first")
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            models = json.load(response).get("models", [])
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Gemini returned HTTP {error.code}") from None
    print("\n".join(model["name"] for model in models))


if __name__ == "__main__":
    list_models()
