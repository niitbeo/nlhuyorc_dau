"""Reproducible OCR check on labeled print pages and UIT-HWDB handwriting lines.

Run after extracting UIT-HWDB test rows to data/benchmark/uit_hwdb_test/labels.json.
Only pass --gemini for public/synthetic samples that may be sent to Google.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import platform
import resource
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dau_archive.ocr_local import classify_line_crops, predictor, recognize_crop, recognize_image
from dau_archive.secrets import gemini_key


ARCHIVE = ROOT / "data/NLHUY_Dataset_fast_repaired.zip"
HANDWRITING = ROOT / "data/benchmark/uit_hwdb_test"
PROMPT = "Đọc chính xác toàn bộ chữ tiếng Việt trong ảnh theo thứ tự đọc. Chỉ trả về văn bản, giữ chữ hoa, dấu câu và xuống dòng. Không thêm giải thích hay Markdown."


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def edit_distance(left, right) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def metrics(reference: str, prediction: str) -> dict:
    expected, actual = normalize(reference), normalize(prediction)
    expected_words, actual_words = expected.split(), actual.split()
    return {
        "cer": round(edit_distance(expected, actual) / max(len(expected), 1), 4),
        "wer": round(edit_distance(expected_words, actual_words) / max(len(expected_words), 1), 4),
        "reference_chars": len(expected), "prediction_chars": len(actual),
    }


def gemini_ocr(image_bytes: bytes, mime_type: str, model: str) -> tuple[str, float]:
    key = gemini_key()
    if not key:
        raise RuntimeError("Chưa có GEMINI_API_KEY hoặc khóa ở Cài đặt API")
    body = {"contents": [{"parts": [
        {"text": PROMPT},
        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
    ]}], "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingLevel": "low"}}}
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    started = time.monotonic()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"Gemini HTTP {error.code}") from None
            time.sleep(2 ** attempt)
    text = "".join(part.get("text", "") for candidate in data.get("candidates", [])[:1]
                   for part in candidate.get("content", {}).get("parts", []))
    if not text:
        raise RuntimeError("Gemini không trả về văn bản")
    return text.strip(), round(time.monotonic() - started, 2)


def examples(printed_limit: int, handwriting_limit: int):
    with zipfile.ZipFile(ARCHIVE) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".gt.txt") and "/synthetic/" in name)
        by_condition = {condition: [name for name in names if f"/synthetic/{condition}/" in name]
                        for condition in ("clean", "scan", "bad_scan")}
        balanced_names = [name for index in range(4) for condition in by_condition
                          for name in by_condition[condition][index:index + 1]]
        for name in balanced_names[:printed_limit]:
            image_name = name.removesuffix(".gt.txt") + ".png"
            content = archive.read(image_name)
            yield {"id": Path(image_name).stem, "kind": "printed_page", "image": Image.open(io.BytesIO(content)).convert("RGB"),
                   "content": content, "mime_type": "image/png", "reference": archive.read(name).decode("utf-8")}
    for item in json.loads((HANDWRITING / "labels.json").read_text(encoding="utf-8"))[:handwriting_limit]:
        content = (HANDWRITING / item["file"]).read_bytes()
        yield {"id": f"uit_hwdb_test_{item['row_index']}", "kind": "handwritten_line",
               "image": Image.open(io.BytesIO(content)).convert("RGB"),
               "content": content, "mime_type": "image/jpeg", "reference": item["text"]}


def run(args):
    report = {"dataset": "NLHUY synthetic printed pages + UIT-HWDB test handwriting lines",
              "gemini_model": args.model if args.gemini else None, "samples": []}
    gemini_counts = {"printed_page": 0, "handwritten_line": 0}
    for sample in examples(args.printed_limit, args.handwriting_limit):
        print(f"Measuring {sample['id']} ({sample['kind']})", flush=True)
        row = {key: sample[key] for key in ("id", "kind")}
        row["local"] = {}
        if sample["kind"] == "printed_page":
            for mode in ("auto", "printed"):
                started = time.monotonic()
                lines, detector, warning = recognize_image(sample["image"], mode, args.detector)
                text = "\n".join(line["text"] for line in lines)
                row["local"][mode] = {**metrics(sample["reference"], text),
                                       "seconds": round(time.monotonic() - started, 2),
                                       "detector": detector, "warning": warning, "lines": len(lines),
                                       "selected_handwritten": sum(line["recognition_mode"] == "handwritten" for line in lines)}
        else:
            crop = [{"crop": sample["image"]}]
            started = time.monotonic()
            selected, score = classify_line_crops(crop)[0]
            text, chosen, recognition_score, method = recognize_crop(sample["image"], selected, score)
            row["classifier"] = {"selected": selected, "score": score,
                                 "final_mode": chosen, "selection_method": method}
            row["local"]["auto"] = {**metrics(sample["reference"], text),
                                     "seconds": round(time.monotonic() - started, 2),
                                     "recognizer": chosen, "recognition_score": recognition_score}
            for mode in ("handwritten", "printed"):
                started = time.monotonic()
                text = predictor(mode).predict(sample["image"]).strip()
                row["local"][mode] = {**metrics(sample["reference"], text),
                                       "seconds": round(time.monotonic() - started, 2),
                                       "recognizer": mode}
        if args.gemini and gemini_counts[sample["kind"]] < args.gemini_limit_per_kind:
            try:
                text, seconds = gemini_ocr(sample["content"], sample["mime_type"], args.model)
                row["gemini"] = {**metrics(sample["reference"], text), "seconds": seconds}
            except Exception as exc:
                row["gemini_error"] = str(exc)
            gemini_counts[sample["kind"]] += 1
        report["samples"].append(row)
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["peak_process_rss_mib"] = round(peak_rss / (1024 * 1024 if platform.system() == "Darwin" else 1024), 1)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)


def print_summary(report):
    for kind in ("printed_page", "handwritten_line"):
        rows = [row for row in report["samples"] if row["kind"] == kind]
        for name in ("auto", "printed", "handwritten", "gemini"):
            values = [row["gemini"] if name == "gemini" else row["local"][name]
                      for row in rows if ("gemini" in row if name == "gemini" else name in row["local"])]
            if values:
                print(f"{kind} {name}: n={len(values)} mean CER={statistics.mean(v['cer'] for v in values):.3f}"
                      f" mean WER={statistics.mean(v['wer'] for v in values):.3f}"
                      f" median seconds={statistics.median(v['seconds'] for v in values):.2f}")
    handwritten = [row for row in report["samples"] if row["kind"] == "handwritten_line"]
    if handwritten:
        initial = sum(row["classifier"]["selected"] == "handwritten" for row in handwritten)
        final = sum(row["classifier"]["final_mode"] == "handwritten" for row in handwritten)
        print(f"Handwriting selection: classifier {initial}/{len(handwritten)}, final {final}/{len(handwritten)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--printed-limit", type=int, default=12)
    parser.add_argument("--handwriting-limit", type=int, default=10)
    parser.add_argument("--detector", choices=("auto", "paddle_server", "paddle_mobile", "simple"), default="auto")
    parser.add_argument("--gemini", action="store_true")
    parser.add_argument("--gemini-limit-per-kind", type=int, default=4)
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmark/stage1_results.json")
    run(parser.parse_args())
