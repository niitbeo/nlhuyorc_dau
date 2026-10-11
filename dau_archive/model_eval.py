"""OCR evaluations for bundled samples and administrator-selected PDF/image files.

Uploaded pages are sent to Gemini only after an explicit opt-in. Archive documents
are never selected implicitly for the external comparison.
"""
from __future__ import annotations

import base64
import io
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

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from .db import data_dir
from .secrets import gemini_key


ROOT = Path(__file__).resolve().parent.parent
PRINT_ARCHIVE = ROOT / "data/NLHUY_Dataset_fast_repaired.zip"
HAND_DIR = ROOT / "data/benchmark/uit_hwdb_test"
PROMPT = ("Đọc chính xác toàn bộ chữ tiếng Việt trong ảnh theo thứ tự đọc. "
          "Chỉ trả về văn bản, giữ chữ hoa, dấu câu và xuống dòng. Không thêm giải thích hay Markdown.")
_lock = threading.Lock()
_job: dict | None = None
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_UPLOAD_PAGES = 3
UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


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
        _job = {"id": uuid.uuid4().hex, "source": "bundled", "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "settings": {"printed_count": printed_count, "handwritten_count": handwritten_count,
                             "compare_gemini": compare_gemini},
                "completed": 0, "total": printed_count + handwritten_count,
                "samples": [], "summary": []}
        _persist(_job)
        snapshot = json.loads(json.dumps(_job))
        threading.Thread(target=_run, args=(_job["id"],), daemon=True).start()
        return snapshot


def _upload_pages(content: bytes, filename: str, first_page: int, page_count: int) -> list[dict]:
    """Render only the selected pages as bounded PNGs for both OCR backends."""
    suffix = Path(filename).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise ValueError("Chỉ nhận PDF hoặc ảnh PNG, JPG, WebP, TIFF")
    pages: list[dict] = []
    try:
        if suffix == ".pdf":
            with fitz.open(stream=content, filetype="pdf") as document:
                if document.is_encrypted:
                    raise ValueError("PDF có mật khẩu; hãy mở khóa trước khi kiểm tra")
                total = len(document)
                if first_page > total:
                    raise ValueError(f"Tệp chỉ có {total} trang")
                for index in range(first_page - 1, min(total, first_page - 1 + page_count)):
                    page = document[index]
                    scale = min(2.0, 2400 / max(page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    pages.append({"id": f"trang_{index + 1}", "page_no": index + 1,
                                  "kind": "uploaded_page", "content": pix.tobytes("png"),
                                  "mime": "image/png"})
        else:
            with Image.open(io.BytesIO(content)) as image:
                total = getattr(image, "n_frames", 1)
                if first_page > total:
                    raise ValueError(f"Tệp chỉ có {total} trang")
                for index in range(first_page - 1, min(total, first_page - 1 + page_count)):
                    image.seek(index)
                    if image.width * image.height > 25_000_000:
                        raise ValueError("Ảnh vượt quá 25 triệu điểm ảnh")
                    frame = ImageOps.exif_transpose(image).convert("RGB")
                    frame.thumbnail((2400, 2400))
                    output = io.BytesIO()
                    frame.save(output, format="PNG")
                    pages.append({"id": f"trang_{index + 1}", "page_no": index + 1,
                                  "kind": "uploaded_page", "content": output.getvalue(),
                                  "mime": "image/png"})
    except (fitz.FileDataError, UnidentifiedImageError, Image.DecompressionBombError,
            OSError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith(("PDF có", "Tệp chỉ", "Ảnh vượt")):
            raise
        raise ValueError("Không đọc được PDF hoặc ảnh đã chọn") from error
    return pages


def start_upload(content: bytes, filename: str, first_page: int, page_count: int,
                 reference_text: str, compare_gemini: bool) -> dict:
    global _job
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Tệp trống hoặc vượt quá 30 MiB")
    if first_page < 1 or page_count < 1 or page_count > MAX_UPLOAD_PAGES:
        raise ValueError("Chọn trang bắt đầu và 1–3 trang để kiểm tra")
    if len(reference_text) > 50000:
        raise ValueError("Bản chép đúng vượt quá 50.000 ký tự")
    if compare_gemini and not gemini_key():
        raise ValueError("Chưa cấu hình Gemini API key")
    pages = _upload_pages(content, filename, first_page, page_count)
    with _lock:
        if _job and _job["status"] == "running":
            raise RuntimeError("Đã có phép kiểm tra model đang chạy")
        _job = {"id": uuid.uuid4().hex, "source": "upload", "status": "running",
                "filename": Path(filename).name[:180],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "settings": {"first_page": first_page, "page_count": len(pages),
                             "compare_gemini": compare_gemini,
                             "has_reference": bool(reference_text.strip())},
                "completed": 0, "total": len(pages), "samples": [], "summary": []}
        _persist(_job)
        snapshot = json.loads(json.dumps(_job))
        threading.Thread(target=_run_upload, args=(_job["id"], pages, reference_text.strip(),
                                                  compare_gemini), daemon=True).start()
        return snapshot


def _run_upload(job_id: str, pages: list[dict], reference: str, compare_gemini: bool) -> None:
    try:
        for sample in pages:
            row = {"id": sample["id"], "page_no": sample["page_no"],
                   "kind": "uploaded_page", "local": {}}
            for mode in ("auto", "printed", "handwritten"):
                try:
                    prediction, seconds, details = _ocr(sample, mode)
                    row["local"][mode] = {"text": prediction, "seconds": round(seconds, 2), **details}
                except Exception as error:
                    row["local"][mode] = {"error": str(error)[:160]}
            if compare_gemini:
                try:
                    prediction, seconds = _gemini(sample)
                    row["gemini"] = {"text": prediction, "seconds": round(seconds, 2)}
                except Exception as error:
                    row["gemini_error"] = str(error)[:160]
            with _lock:
                if _job["id"] != job_id:
                    return
                _job["samples"].append(row)
                _job["completed"] += 1
                _persist(_job)
        with _lock:
            rows = _job["samples"]
            summary = []
            for mode in ("auto", "printed", "handwritten", "gemini"):
                values = [row.get("gemini") if mode == "gemini" else row["local"].get(mode)
                          for row in rows]
                if any(value is None or "error" in value for value in values):
                    continue
                result = {"kind": "uploaded_page", "model": mode, "count": len(values),
                          "seconds": round(statistics.median(value["seconds"] for value in values), 2),
                          "cer": None, "wer": None}
                if reference:
                    metric = score(reference, "\n".join(value["text"] for value in values), 0)
                    result.update(cer=metric["cer"], wer=metric["wer"])
                summary.append(result)
            if not summary:
                _job["status"] = "failed"
                _job["error"] = "Không model nào xử lý được các trang đã chọn"
                _persist(_job)
                return
            _job["summary"] = summary
            _job["status"] = "ready"
            _job["finished_at"] = datetime.now(timezone.utc).isoformat()
            _persist(_job)
    except Exception as error:
        with _lock:
            _job["status"] = "failed"
            _job["error"] = str(error)[:240]
            _persist(_job)


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
