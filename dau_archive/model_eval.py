"""Small, labeled OCR evaluations launched from the administration UI.

Only bundled synthetic/public samples can be evaluated. Documents in the archive
are never sent to the optional external comparator.
"""
from __future__ import annotations

import base64
import json
import os
import statistics
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .db import data_dir
from .secrets import gemini_key


ROOT = Path(__file__).resolve().parent.parent
PRINT_ARCHIVE = ROOT / "data/NLHUY_Dataset_fast_repaired.zip"
HAND_DIR = ROOT / "data/benchmark/uit_hwdb_test"
PROMPT = ("Đọc chính xác toàn bộ chữ tiếng Việt trong ảnh theo thứ tự đọc. "
          "Chỉ trả về văn bản, giữ chữ hoa, dấu câu và xuống dòng. Không thêm giải thích hay Markdown.")
_lock = threading.Lock()
_job: dict | None = None


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _distance(left, right) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for index, item in enumerate(left, 1):
        current = [index]
        for column, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (item != other)))
        previous = current
    return previous[-1]


def score(reference: str, prediction: str, seconds: float) -> dict:
    expected, actual = _normalize(reference), _normalize(prediction)
    return {"cer": round(_distance(expected, actual) / max(len(expected), 1), 4),
            "wer": round(_distance(expected.split(), actual.split()) / max(len(expected.split()), 1), 4),
            "seconds": round(seconds, 2)}


def availability() -> dict:
    hand_labels = HAND_DIR / "labels.json"
    return {"printed": PRINT_ARCHIVE.is_file(), "handwritten": hand_labels.is_file(),
            "gemini": bool(gemini_key())}


def _samples(printed_count: int, handwritten_count: int):
    with zipfile.ZipFile(PRINT_ARCHIVE) as archive:
        names = sorted(name for name in archive.namelist()
                       if name.endswith(".gt.txt") and "/synthetic/" in name)
        groups = {condition: [name for name in names if f"/synthetic/{condition}/" in name]
                  for condition in ("clean", "scan", "bad_scan")}
        balanced = [name for index in range(4) for group in groups.values()
                    for name in group[index:index + 1]]
        for name in balanced[:printed_count]:
            image_name = name.removesuffix(".gt.txt") + ".png"
            yield {"id": Path(image_name).stem, "kind": "printed_page",
                   "content": archive.read(image_name), "mime": "image/png",
                   "reference": archive.read(name).decode("utf-8")}
    labels = json.loads((HAND_DIR / "labels.json").read_text(encoding="utf-8"))
    for item in labels[:handwritten_count]:
        yield {"id": f"uit_hwdb_test_{item['row_index']}", "kind": "handwritten_line",
               "content": (HAND_DIR / item["file"]).read_bytes(), "mime": "image/jpeg",
               "reference": item["text"]}


def _ocr(sample: dict, mode: str) -> tuple[str, float, dict]:
    import requests

    # The URL is fixed to loopback: this endpoint cannot be used as a proxy.
    endpoint = "http://127.0.0.1:8000/ocr/image"
    boundary = os.getenv("DAU_OCR_EVAL_URL", "").strip()
    if boundary:
        from urllib.parse import urlparse
        parsed = urlparse(boundary)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("DAU_OCR_EVAL_URL phải trỏ đến OCR nội bộ")
        endpoint = boundary
    start = time.monotonic()
    response = requests.post(endpoint, data={"mode": mode, "detector": "auto"},
                             files={"file": (sample["id"] + (".png" if sample["mime"] == "image/png" else ".jpg"),
                                             sample["content"], sample["mime"])}, timeout=180)
    response.raise_for_status()
    payload = response.json()
    return payload.get("raw_text", ""), time.monotonic() - start, {
        "detector": payload.get("detector"), "line_count": len(payload.get("lines", [])),
        "selected_handwritten": sum(row.get("recognition_mode") == "handwritten"
                                    for row in payload.get("lines", [])),
        "warning": payload.get("detection_warning"),
    }


def _gemini(sample: dict) -> tuple[str, float]:
    key = gemini_key()
    if not key:
        raise RuntimeError("Chưa cấu hình Gemini API key")
    body = {"contents": [{"parts": [{"text": PROMPT}, {"inline_data": {
        "mime_type": sample["mime"], "data": base64.b64encode(sample["content"]).decode("ascii")}}]}],
        "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingLevel": "low"}}}
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Gemini HTTP {error.code}") from None
    text = "".join(part.get("text", "") for candidate in payload.get("candidates", [])[:1]
                   for part in candidate.get("content", {}).get("parts", []))
    if not text.strip():
        raise RuntimeError("Gemini không trả về văn bản")
    return text.strip(), time.monotonic() - start


def _summary(rows: list[dict]) -> list[dict]:
    groups = []
    for kind in ("printed_page", "handwritten_line"):
        selected = [row for row in rows if row["kind"] == kind]
        for mode in ("auto", "printed", "handwritten", "gemini"):
            values = [row.get("gemini") if mode == "gemini" else row["local"].get(mode)
                      for row in selected]
            values = [value for value in values if value]
            if values:
                groups.append({"kind": kind, "model": mode, "count": len(values),
                               "cer": round(statistics.mean(value["cer"] for value in values), 4),
                               "wer": round(statistics.mean(value["wer"] for value in values), 4),
                               "seconds": round(statistics.median(value["seconds"] for value in values), 2)})
    return groups


def _persist(job: dict) -> None:
    directory = data_dir() / "model_evaluations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "latest.json"
    temporary = directory / "latest.tmp"
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def latest() -> dict | None:
    with _lock:
        if _job is not None:
            return json.loads(json.dumps(_job))
    path = data_dir() / "model_evaluations/latest.json"
    if not path.is_file():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") == "running":
        result["status"] = "interrupted"
    return result


def start(printed_count: int, handwritten_count: int, compare_gemini: bool) -> dict:
    global _job
    ready = availability()
    if not ready["printed"] or not ready["handwritten"]:
        raise ValueError("Thiếu archive trang in hoặc tập kiểm tra chữ viết tay")
    if compare_gemini and not ready["gemini"]:
        raise ValueError("Chưa cấu hình Gemini API key")
    with _lock:
        if _job and _job["status"] == "running":
            raise RuntimeError("Đã có phép kiểm tra model đang chạy")
        _job = {"id": uuid.uuid4().hex, "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "settings": {"printed_count": printed_count, "handwritten_count": handwritten_count,
                             "compare_gemini": compare_gemini},
                "completed": 0, "total": printed_count + handwritten_count,
                "samples": [], "summary": []}
        _persist(_job)
        snapshot = json.loads(json.dumps(_job))
        threading.Thread(target=_run, args=(_job["id"],), daemon=True).start()
        return snapshot


def _run(job_id: str) -> None:
    with _lock:
        settings = _job["settings"].copy()
    try:
        for sample in _samples(settings["printed_count"], settings["handwritten_count"]):
            row = {"id": sample["id"], "kind": sample["kind"], "local": {}}
            modes = ("auto", "printed") if sample["kind"] == "printed_page" else ("auto", "handwritten", "printed")
            for mode in modes:
                prediction, seconds, details = _ocr(sample, mode)
                row["local"][mode] = {**score(sample["reference"], prediction, seconds), **details}
            if settings["compare_gemini"]:
                try:
                    prediction, seconds = _gemini(sample)
                    row["gemini"] = score(sample["reference"], prediction, seconds)
                except Exception as error:
                    row["gemini_error"] = str(error)[:160]
            with _lock:
                if _job["id"] != job_id:
                    return
                _job["samples"].append(row)
                _job["completed"] += 1
                _job["summary"] = _summary(_job["samples"])
                _persist(_job)
        with _lock:
            _job["status"] = "ready"
            _job["finished_at"] = datetime.now(timezone.utc).isoformat()
            _persist(_job)
    except Exception as error:
        with _lock:
            _job["status"] = "failed"
            _job["error"] = str(error)[:240]
            _persist(_job)
