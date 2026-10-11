"""Local document OCR service using the project's trained NLHUYOCR weights."""
from __future__ import annotations

import io
import importlib.util
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import fitz
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from .text_quality import looks_garbled_vietnamese


app = FastAPI(title="NLHUYOCR tài liệu")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_FILES = {
    "printed": "transformerocr_finetuned.pth",
    "handwritten": "handwriting_pro.pth",
}
DETECTION_MODELS = {
    "paddle_server": "PP-OCRv5_server_det",
    "paddle_mobile": "PP-OCRv5_mobile_det",
}
DETECTOR_CHOICES = {"auto", "paddle", "paddle_server", "paddle_mobile", "simple"}
RECOGNITION_MODES = {"auto", *MODEL_FILES}
AUTO_RECHECK_BELOW = 0.90
AUTO_SWITCH_MARGIN = 0.02
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_DOCUMENT_BYTES = 200 * 1024 * 1024
MAX_PAGES_PER_JOB = 500
STATIC = Path(__file__).parent / "static"
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dau-ocr")
_jobs_lock = threading.RLock()
logger = logging.getLogger(__name__)


def weight_path(mode: str) -> Path:
    variable = "DAU_PRINTED_WEIGHTS" if mode == "printed" else "DAU_HANDWRITTEN_WEIGHTS"
    return Path(os.getenv(variable, str(PROJECT_ROOT / "weights" / MODEL_FILES[mode]))).expanduser().resolve()


@lru_cache(maxsize=2)
def predictor(mode: str):
    path = weight_path(mode)
    if not path.is_file():
        raise FileNotFoundError(f"Thiếu trọng số {mode}: {path}")
    import yaml
    from vietocr.tool.config import Cfg
    from vietocr.tool.predictor import Predictor

    with (PROJECT_ROOT / "configs" / "base.yml").open(encoding="utf-8") as source:
        values = yaml.safe_load(source)
    with (PROJECT_ROOT / "configs" / "vgg-transformer.yml").open(encoding="utf-8") as source:
        values.update(yaml.safe_load(source))
    config = Cfg(values)
    config["weights"] = str(path)
    config["device"] = "cpu"
    config["cnn"]["pretrained"] = False
    config["predictor"]["beamsearch"] = False
    config["dataset"]["image_max_width"] = 2048
    return Predictor(config)


def classifier_path() -> Path:
    return Path(os.getenv("DAU_CLASSIFIER_WEIGHTS", str(PROJECT_ROOT / "weights" / "text_classifier.pth"))).expanduser().resolve()


@lru_cache(maxsize=1)
def text_classifier():
    path = classifier_path()
    if not path.is_file():
        raise FileNotFoundError(f"Thiếu trọng số phân loại chữ in/viết tay: {path}")
    import torch
    from torch import nn
    from torchvision import models, transforms

    model = models.resnet18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 2)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.eval()
    transform = transforms.Compose([
        transforms.Resize((64, 256)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    return model, transform


def classify_line_crops(crops: list[dict]) -> list[tuple[str, float]]:
    """Class 0 is handwriting and class 1 is print in the trained ResNet18."""
    import torch

    model, transform = text_classifier()
    labels = []
    with torch.inference_mode():
        for start in range(0, len(crops), 32):
            batch = torch.stack([transform(item["crop"].convert("RGB")) for item in crops[start:start + 32]])
            scores = torch.softmax(model(batch), dim=1)
            for score in scores:
                index = int(score.argmax())
                labels.append(("handwritten" if index == 0 else "printed", round(float(score[index]), 4)))
    return labels


def line_crops(image: Image.Image) -> list[tuple[tuple[int, int, int, int], Image.Image]]:
    """Split an ordinary one-column page into text lines; keep coordinates."""
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    row_counts = (ink > 0).sum(axis=1)
    active = row_counts > max(3, image.width * 0.008)
    groups = []
    start = None
    last = None
    for y, on in enumerate(active):
        if on:
            if start is None:
                start = y
            elif last is not None and y - last > 4:
                groups.append((start, last + 1))
                start = y
            last = y
    if start is not None and last is not None:
        groups.append((start, last + 1))
    output = []
    for top, bottom in groups:
        if bottom - top < 7:
            continue
        band = ink[top:bottom]
        columns = np.flatnonzero((band > 0).sum(axis=0) > 1)
        if not len(columns):
            continue
        left = max(0, int(columns[0]) - 8)
        right = min(image.width, int(columns[-1]) + 9)
        top = max(0, top - 6)
        bottom = min(image.height, bottom + 6)
        if right - left < 20:
            continue
        box = (left, top, right, bottom)
        output.append((box, image.crop(box)))
    return output or [((0, 0, image.width, image.height), image)]


def paddle_model_dir(model_name: str = "PP-OCRv5_server_det") -> Path:
    variable = ("DAU_PADDLE_MOBILE_DET_MODEL_DIR" if model_name == "PP-OCRv5_mobile_det"
                else "DAU_PADDLE_DET_MODEL_DIR")
    return Path(os.getenv(variable, str(
        PROJECT_ROOT / "weights" / "paddle" / f"{model_name}_infer"
    ))).expanduser().resolve()


def paddle_available(model_name: str = "PP-OCRv5_server_det") -> bool:
    return (paddle_model_dir(model_name) / "inference.yml").is_file() and importlib.util.find_spec("paddleocr") is not None


@lru_cache(maxsize=2)
def paddle_detector(model_name: str):
    model_dir = paddle_model_dir(model_name)
    if not (model_dir / "inference.yml").is_file():
        raise FileNotFoundError(f"Thiếu model dò chữ PaddleOCR: {model_dir}")
    cache_root = Path(os.getenv("DAU_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_root / "paddlex"))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "cache"))
    from paddleocr import TextDetection

    return TextDetection(model_name=model_name, model_dir=str(model_dir),
                         device="cpu", cpu_threads=4)


def paddle_line_crops(image: Image.Image, model_name: str) -> list[dict]:
    rgb = np.asarray(image.convert("RGB"))
    result = next(iter(paddle_detector(model_name).predict(input=rgb)), None)
    if result is None:
        return []
    data = result.json.get("res", {})
    polygons = data.get("dt_polys", [])
    scores = data.get("dt_scores", [])
    crops = []
    for index, raw_polygon in enumerate(polygons[:1000]):
        polygon = np.asarray(raw_polygon, dtype=np.float32)
        if polygon.shape != (4, 2) or not np.isfinite(polygon).all():
            continue
        polygon[:, 0] = np.clip(polygon[:, 0], 0, image.width - 1)
        polygon[:, 1] = np.clip(polygon[:, 1], 0, image.height - 1)
        width = int(round(max(np.linalg.norm(polygon[1] - polygon[0]),
                              np.linalg.norm(polygon[2] - polygon[3]))))
        height = int(round(max(np.linalg.norm(polygon[3] - polygon[0]),
                               np.linalg.norm(polygon[2] - polygon[1]))))
        if width < 12 or height < 5:
            continue
        target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                          dtype=np.float32)
        transform = cv2.getPerspectiveTransform(polygon, target)
        crop = cv2.warpPerspective(rgb, transform, (width, height), borderValue=(255, 255, 255))
        crop = cv2.copyMakeBorder(crop, 5, 5, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        box = [int(np.floor(polygon[:, 0].min())), int(np.floor(polygon[:, 1].min())),
               int(np.ceil(polygon[:, 0].max())), int(np.ceil(polygon[:, 1].max()))]
        crops.append({"box": box, "polygon": polygon.astype(int).tolist(),
                      "score": round(float(scores[index]), 4) if index < len(scores) else None,
                      "crop": Image.fromarray(crop)})
    sort_reading_order(crops, image.width)
    return crops


def sort_reading_order(crops: list[dict], image_width: int) -> None:
    """Read two distinct text columns from top to bottom, left first."""
    crops.sort(key=lambda item: (item["box"][1], item["box"][0]))
    if len(crops) < 12 or image_width <= 0:
        return
    low, high = int(image_width * .35), int(image_width * .65)
    if high <= low:
        return
    occupied = np.zeros(high - low, dtype=bool)
    for item in crops:
        left, _, right, _ = item["box"]
        start = max(0, min(high - low, left - low))
        end = max(0, min(high - low, right - low))
        if end > start:
            occupied[start:end] = True
    gaps = np.flatnonzero(~occupied)
    if len(gaps) == 0:
        return
    runs = np.split(gaps, np.where(np.diff(gaps) > 1)[0] + 1)
    gap = max(runs, key=len)
    if len(gap) < image_width * .04:
        return
    boundary = low + int((gap[0] + gap[-1]) / 2)
    left = [item for item in crops if item["box"][2] <= boundary]
    right = [item for item in crops if item["box"][0] >= boundary]
    if len(left) < 5 or len(right) < 5 or len(left) + len(right) != len(crops):
        return
    left_top = min(item["box"][1] for item in left)
    left_bottom = max(item["box"][3] for item in left)
    right_top = min(item["box"][1] for item in right)
    right_bottom = max(item["box"][3] for item in right)
    overlap = min(left_bottom, right_bottom) - max(left_top, right_top)
    if overlap < min(left_bottom - left_top, right_bottom - right_top) * .35:
        return
    crops[:] = left + right


def detected_crops(image: Image.Image, detector: str) -> tuple[list[dict], str, Optional[str]]:
    if detector not in DETECTOR_CHOICES:
        raise ValueError("detector không hợp lệ")
    selected = "paddle_server" if detector == "paddle" else detector
    if selected == "auto":
        selected = next((name for name, model in DETECTION_MODELS.items()
                         if paddle_available(model)), "simple")
    if selected in DETECTION_MODELS:
        try:
            crops = paddle_line_crops(image, DETECTION_MODELS[selected])
            if crops:
                return crops, selected, None
            if detector != "auto":
                return [], selected, "PaddleOCR không tìm thấy dòng chữ"
            warning = "PaddleOCR không tìm thấy dòng chữ; đã thử cách dò đơn giản"
        except Exception as exc:
            if detector != "auto":
                raise
            logger.warning("PaddleOCR detection failed; using simple detection", exc_info=True)
            warning = f"PaddleOCR lỗi; đã dùng cách dò đơn giản: {exc}"
    else:
        warning = None
    crops = []
    for box, crop in line_crops(image):
        left, top, right, bottom = box
        crops.append({"box": list(box), "polygon": [[left, top], [right, top],
                                                       [right, bottom], [left, bottom]],
                      "score": None, "crop": crop})
    return crops, "simple", warning


@app.get("/api/health")
def health():
    return {"recognizers": {mode: {"weights_present": weight_path(mode).is_file(),
                                    "weights": str(weight_path(mode))} for mode in MODEL_FILES},
            "classifier": {"weights_present": classifier_path().is_file(),
                           "weights": str(classifier_path())},
            "detectors": {name: {"model": model, "ready": paddle_available(model),
                                 "model_dir": str(paddle_model_dir(model))}
                          for name, model in DETECTION_MODELS.items()}}


def recognize_crop(crop: Image.Image, mode: str, classification_score: Optional[float] = None):
    """Read one detected line; double-check uncertain automatic classification."""
    recognition_score = None
    selection_method = "manual" if classification_score is None else "classifier"
    if classification_score is None:
        recognized = predictor(mode).predict(crop)
    else:
        recognized, recognition_score = predictor(mode).predict(crop, return_prob=True)
        recognition_score = float(recognition_score)
        if classification_score < AUTO_RECHECK_BELOW:
            alternative = "handwritten" if mode == "printed" else "printed"
            other_text, other_score = predictor(alternative).predict(crop, return_prob=True)
            if float(other_score) > recognition_score + AUTO_SWITCH_MARGIN:
                mode, recognized, recognition_score = alternative, other_text, float(other_score)
                selection_method = "recognition_score"
            else:
                selection_method = "classifier_rechecked"
    return recognized.strip(), mode, recognition_score, selection_method


def recognize_image(image: Image.Image, mode: str, detector: str = "auto") -> tuple[list[dict], str, Optional[str]]:
    if mode not in RECOGNITION_MODES:
        raise ValueError("mode phải là auto, printed hoặc handwritten")
    crops, detector_used, warning = detected_crops(image, detector)
    if mode == "auto" and crops:
        decisions = classify_line_crops(crops)
    else:
        decisions = [(mode, None) for _ in crops]
    lines = []
    for item, (line_mode, classification_score) in zip(crops, decisions):
        recognized, line_mode, recognition_score, selection_method = recognize_crop(
            item["crop"], line_mode, classification_score)
        if recognized:
            lines.append({"box": item["box"], "polygon": item["polygon"],
                          "detection_score": item["score"], "text": recognized,
                          "recognition_mode": line_mode,
                          "classification_score": classification_score,
                          "recognition_score": round(recognition_score, 4) if recognition_score is not None else None,
                          "selection_method": selection_method})
    return lines, detector_used, warning


@app.post("/ocr/image")
async def ocr_image(file: UploadFile = File(...), mode: str = Form("auto"),
                    detector: str = Form("auto")):
    if mode not in RECOGNITION_MODES or detector not in DETECTOR_CHOICES:
        raise HTTPException(422, "mode phải là auto, printed hoặc handwritten")
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(422, "Ảnh trống hoặc quá 50 MiB")
    try:
        image = Image.open(io.BytesIO(content)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, "Tệp không phải ảnh hợp lệ")
    if image.width * image.height > 25_000_000:
        raise HTTPException(422, "Ảnh quá lớn")
    try:
        lines, detector_used, warning = await run_in_threadpool(
            recognize_image, image, mode, detector)
    except (FileNotFoundError, ImportError) as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"NLHUYOCR không đọc được ảnh: {exc}")
    text = "\n".join(line["text"] for line in lines)
    return {"mode": mode, "detector": detector_used, "detection_warning": warning,
            "image_size": [image.width, image.height],
            "raw_text": text, "corrected_text": text, "lines": lines}


def jobs_dir() -> Path:
    base = Path(os.getenv("DAU_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
    path = base / "ocr_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "Không tìm thấy tác vụ")
    path = jobs_dir() / job_id
    if not (path / "job.json").is_file():
        raise HTTPException(404, "Không tìm thấy tác vụ")
    return path


def _read_job(job_id: str) -> dict:
    return json.loads((_job_dir(job_id) / "job.json").read_text(encoding="utf-8"))


def _write_job(job: dict) -> None:
    path = jobs_dir() / job["id"] / "job.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _source_path(job: dict) -> Path:
    return jobs_dir() / job["id"] / ("source.pdf" if job["type"] == "pdf" else "source.img")


def _render_page(page, max_side: int) -> Image.Image:
    scale = min(2.4, max_side / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _process_job(job_id: str) -> None:
    try:
        with _jobs_lock:
            job = _read_job(job_id)
            job["status"] = "processing"
            job["error"] = None
            _write_job(job)
        source = _source_path(job)
        completed = {item["page_no"] for item in job["results"]}
        if job["type"] == "pdf":
            with fitz.open(source) as pdf:
                for page_no in range(job["start_page"], job["end_page"] + 1):
                    if page_no in completed:
                        continue
                    started = time.monotonic()
                    page = pdf[page_no - 1]
                    native = page.get_text("text").strip()
                    if (job["text_mode"] == "auto" and len(native) >= 30
                            and not looks_garbled_vietnamese(native)):
                        text, lines, origin, image_size = native, [], "native-pdf", None
                    else:
                        image = _render_page(page, 2600)
                        lines, detector_used, warning = recognize_image(
                            image, job["mode"], job.get("detector", "auto"))
                        text = "\n".join(item["text"] for item in lines)
                        origin = "ocr"
                        image_size = [image.width, image.height]
                    if origin == "native-pdf":
                        detector_used, warning = None, None
                    result = {"page_no": page_no, "text": text, "corrected_text": text,
                              "source": origin, "lines": lines, "image_size": image_size,
                              "detector": detector_used,
                              "detection_warning": warning,
                              "seconds": round(time.monotonic() - started, 2)}
                    with _jobs_lock:
                        current = _read_job(job_id)
                        current["results"].append(result)
                        current["results"].sort(key=lambda item: item["page_no"])
                        current["processed_pages"] = len(current["results"])
                        _write_job(current)
        else:
            with Image.open(source) as opened:
                image = opened.convert("RGB")
            started = time.monotonic()
            lines, detector_used, warning = recognize_image(image, job["mode"], job.get("detector", "auto"))
            text = "\n".join(item["text"] for item in lines)
            with _jobs_lock:
                current = _read_job(job_id)
                current["results"] = [{"page_no": 1, "text": text, "corrected_text": text,
                                       "source": "ocr", "lines": lines,
                                       "image_size": [image.width, image.height],
                                       "detector": detector_used,
                                       "detection_warning": warning,
                                       "seconds": round(time.monotonic() - started, 2)}]
                current["processed_pages"] = 1
                _write_job(current)
        with _jobs_lock:
            current = _read_job(job_id)
            current["status"] = "ready"
            _write_job(current)
    except Exception as exc:
        with _jobs_lock:
            current = _read_job(job_id)
            current["status"] = "failed"
            current["error"] = str(exc)[:500]
            _write_job(current)


@app.on_event("startup")
def resume_jobs() -> None:
    for folder in jobs_dir().iterdir():
        if not folder.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", folder.name):
            continue
        try:
            job = _read_job(folder.name)
        except (ValueError, OSError, HTTPException):
            continue
        if job["status"] in {"queued", "processing"}:
            _pool.submit(_process_job, folder.name)


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile = File(...), mode: str = Form("auto"),
                     text_mode: str = Form("auto"), detector: str = Form("auto"),
                     start_page: int = Form(1),
                     end_page: Optional[int] = Form(None)):
    if mode not in RECOGNITION_MODES or text_mode not in {"auto", "force_ocr"} or detector not in DETECTOR_CHOICES:
        raise HTTPException(422, "Tùy chọn OCR không hợp lệ")
    job_id = uuid.uuid4().hex
    folder = jobs_dir() / job_id
    folder.mkdir()
    temporary = folder / "upload.tmp"
    total_bytes = 0
    first_bytes = b""
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                if not first_bytes:
                    first_bytes = chunk[:16]
                total_bytes += len(chunk)
                if total_bytes > MAX_DOCUMENT_BYTES:
                    raise HTTPException(413, "Tệp vượt quá 200 MiB")
                output.write(chunk)
        if not total_bytes:
            raise HTTPException(422, "Tệp trống")
        is_pdf = first_bytes.startswith(b"%PDF-")
        source_type = "pdf" if is_pdf else "image"
        if is_pdf:
            try:
                with fitz.open(temporary) as pdf:
                    if pdf.needs_pass:
                        raise HTTPException(422, "PDF có mật khẩu; hãy mở khóa trước khi tải lên")
                    page_count = len(pdf)
            except fitz.FileDataError:
                raise HTTPException(422, "PDF không hợp lệ")
            if page_count < 1:
                raise HTTPException(422, "PDF không có trang")
        else:
            if total_bytes > MAX_IMAGE_BYTES:
                raise HTTPException(413, "Ảnh vượt quá 50 MiB")
            try:
                with Image.open(temporary) as image:
                    if image.width * image.height > 25_000_000:
                        raise HTTPException(422, "Ảnh quá lớn")
                    image.verify()
            except (UnidentifiedImageError, OSError):
                raise HTTPException(422, "Chỉ hỗ trợ PDF, PNG, JPG hoặc TIFF hợp lệ")
            page_count = 1
        last_page = end_page if end_page is not None else page_count
        if start_page < 1 or last_page < start_page or last_page > page_count:
            raise HTTPException(422, f"Khoảng trang phải nằm trong 1–{page_count}")
        if last_page - start_page + 1 > MAX_PAGES_PER_JOB:
            raise HTTPException(422, "Mỗi lượt xử lý tối đa 500 trang")
        temporary.rename(folder / ("source.pdf" if is_pdf else "source.img"))
        job = {"id": job_id, "filename": Path((file.filename or "tai-lieu").replace("\\", "/")).name[:200],
               "type": source_type, "mode": mode, "text_mode": text_mode, "detector": detector,
               "page_count": page_count, "start_page": start_page, "end_page": last_page,
               "total_pages": last_page - start_page + 1, "processed_pages": 0,
               "status": "queued", "error": None, "results": [],
               "created_at": datetime.now(timezone.utc).isoformat()}
        with _jobs_lock:
            _write_job(job)
        _pool.submit(_process_job, job_id)
        return {"id": job_id, "status": "queued", "page_count": page_count,
                "total_pages": job["total_pages"]}
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.get("/api/jobs")
def recent_jobs():
    jobs = []
    for folder in sorted(jobs_dir().iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
        if not folder.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", folder.name):
            continue
        try:
            job = _read_job(folder.name)
        except (ValueError, OSError, HTTPException):
            continue
        jobs.append({key: job[key] for key in ("id", "filename", "status", "created_at", "processed_pages", "total_pages")})
        if len(jobs) >= 20:
            break
    return {"jobs": jobs}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        return _read_job(job_id)


class Correction(BaseModel):
    text: str = Field(max_length=500_000)


@app.patch("/api/jobs/{job_id}/pages/{page_no}")
def correct_page(job_id: str, page_no: int, body: Correction):
    with _jobs_lock:
        job = _read_job(job_id)
        page = next((item for item in job["results"] if item["page_no"] == page_no), None)
        if page is None:
            raise HTTPException(404, "Trang chưa được xử lý")
        page["corrected_text"] = body.text
        page["edited_at"] = datetime.now(timezone.utc).isoformat()
        _write_job(job)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/pages/{page_no}/preview")
def page_preview(job_id: str, page_no: int):
    job = _read_job(job_id)
    if page_no < 1 or page_no > job["page_count"]:
        raise HTTPException(404, "Không tìm thấy trang")
    if job["type"] == "pdf":
        with fitz.open(_source_path(job)) as pdf:
            image = _render_page(pdf[page_no - 1], 1500)
    else:
        with Image.open(_source_path(job)) as opened:
            image = opened.convert("RGB")
            image.thumbnail((1500, 1500))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=86)
    return Response(output.getvalue(), media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/export/{format_name}")
def export_job(job_id: str, format_name: str):
    job = _read_job(job_id)
    if format_name not in {"txt", "json"}:
        raise HTTPException(404, "Định dạng không hỗ trợ")
    if format_name == "json":
        content = json.dumps({"filename": job["filename"], "mode": job["mode"],
                              "pages": job["results"]}, ensure_ascii=False, indent=2).encode("utf-8")
        mime = "application/json; charset=utf-8"
    else:
        content = "\n\n".join(f"--- Trang {page['page_no']} ---\n{page['corrected_text']}"
                              for page in job["results"]).encode("utf-8")
        mime = "text/plain; charset=utf-8"
    return Response(content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="ocr-{job_id}.{format_name}"'})


@app.get("/", response_class=HTMLResponse)
def tester():
    return (STATIC / "ocr.html").read_text(encoding="utf-8")


@app.get("/ocr.css")
def ocr_css():
    return FileResponse(STATIC / "ocr.css", media_type="text/css")


@app.get("/ocr.js")
def ocr_js():
    return FileResponse(STATIC / "ocr.js", media_type="text/javascript")
