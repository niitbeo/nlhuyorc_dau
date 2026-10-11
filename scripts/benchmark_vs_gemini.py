"""Compare one user-selected image locally and with Gemini; no ground truth metric."""
from __future__ import annotations

import argparse
import mimetypes
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dau_archive.ocr_local import recognize_image
from benchmark_stage1 import gemini_ocr


def main():
    parser = argparse.ArgumentParser(description="Compare OCR text and speed on one image")
    parser.add_argument("image", type=Path)
    parser.add_argument("--mode", choices=("auto", "printed", "handwritten"), default="auto")
    parser.add_argument("--model", default="gemini-3.8-flash")
    args = parser.parse_args()
    content = args.image.read_bytes()
    image = Image.open(args.image).convert("RGB")
    started = time.monotonic()
    lines, detector, warning = recognize_image(image, args.mode)
    local_seconds = time.monotonic() - started
    print(f"LOCAL | {local_seconds:.2f}s | {detector} | {len(lines)} lines")
    if warning:
        print(f"Detector warning: {warning}")
    print("\n".join(line["text"] for line in lines))
    print("\nGEMINI")
    mime_type = mimetypes.guess_type(args.image.name)[0] or "image/jpeg"
    text, seconds = gemini_ocr(content, mime_type, args.model)
    print(f"{seconds:.2f}s | {args.model}")
    print(text)
    print("No CER/WER: provide a verified transcription and use benchmark_stage1.py for quality metrics.")


if __name__ == "__main__":
    main()
