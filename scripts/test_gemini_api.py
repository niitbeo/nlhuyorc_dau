"""Check Gemini access without printing the credential or using it in a URL."""
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dau_archive.secrets import gemini_key


def check_gemini():
    key = gemini_key()
    if not key:
        raise SystemExit("Set GEMINI_API_KEY or enter it in Cài đặt API first")
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash",
        headers={"x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(f"HTTP {response.status}: Gemini 3.8 Flash available")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Gemini returned HTTP {error.code}") from None


if __name__ == "__main__":
    check_gemini()
