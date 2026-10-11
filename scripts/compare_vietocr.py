"""So sánh tham chiếu: PaddleOCR phát hiện dòng + VietOCR nhận dạng (model tiếng Việt có sẵn).

Dùng lại box đã lưu trong lines.json của baseline_ocr.py (cùng phát hiện -> chỉ khác bộ nhận dạng),
nên kết quả phản ánh đúng chênh lệch giữa 2 model nhận dạng.

Chạy (trong venv riêng .venv-vietocr):
  .venv-vietocr\\Scripts\\python scripts/compare_vietocr.py ^
      --input data/synthetic --paddle-results results/synthetic/latin_PP-OCRv5_mobile_rec ^
      --out results/synthetic/vietocr_vgg_transformer
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from baseline_ocr import IMG_EXT, group_rows  # noqa: E402
from metrics import report  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def crop_quad(img, poly, pad=3):
    """Cắt và nắn thẳng vùng chữ theo 4 điểm."""
    p = np.asarray(poly, dtype=np.float32)
    w = int(max(np.linalg.norm(p[0] - p[1]), np.linalg.norm(p[2] - p[3]))) + 2 * pad
    h = int(max(np.linalg.norm(p[0] - p[3]), np.linalg.norm(p[1] - p[2]))) + 2 * pad
    dst = np.array([[pad, pad], [w - pad, pad], [w - pad, h - pad], [pad, h - pad]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(p, dst)
    crop = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--paddle-results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default="vgg_transformer", help="vgg_transformer | vgg_seq2seq")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    from vietocr.tool.config import Cfg
    from vietocr.tool.predictor import Predictor

    cfg = Cfg.load_config_from_name(args.config)
    cfg["device"] = args.device
    cfg["predictor"]["beamsearch"] = False
    predictor = Predictor(cfg)

    inp, pres, out = Path(args.input), Path(args.paddle_results), Path(args.out)
    rows = []
    for img_path in sorted(p for p in inp.rglob("*") if p.suffix.lower() in IMG_EXT):
        rel = img_path.relative_to(inp).with_suffix("")
        lj = pres / rel / "lines.json"
        if not lj.exists():
            continue
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        boxes = json.loads(lj.read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        crops = [crop_quad(img, b["poly"]) for b in boxes]
        texts = predictor.predict_batch(crops) if crops else []
        dt = time.perf_counter() - t0
        lines, _ = group_rows([b["poly"] for b in boxes], texts, [1.0] * len(texts))
        hyp = "\n".join(lines)
        (out / rel).mkdir(parents=True, exist_ok=True)
        (out / rel / "text.txt").write_text(hyp, encoding="utf-8")
        row = {"trang": str(rel), "so_box": len(boxes), "giay": round(dt, 2)}
        gt = img_path.with_name(img_path.stem + ".gt.txt")
        if gt.exists():
            row.update(report(gt.read_text(encoding="utf-8"), hyp))
        rows.append(row)
        print(f"  {rel}: {dt:.2f}s" + (f" | CER {row['CER']}% WER {row['WER']}% CER_khong_dau {row['CER_khong_dau']}%" if "CER" in row else ""))

    if rows:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with open(out / "summary.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        groups = {}
        for r in rows:
            if "CER" in r:
                groups.setdefault(Path(r["trang"]).parts[0], []).append(r)
        md = [f"# VietOCR ({args.config}, {args.device}) trên box của PaddleOCR\n",
              "| Nhóm | Số trang | CER % | WER % | CER không dấu % | Giây/trang |", "|---|---|---|---|---|---|"]
        for g, rs in groups.items():
            avg = lambda k: round(float(np.mean([x[k] for x in rs])), 2)  # noqa: E731
            md.append(f"| {g} | {len(rs)} | {avg('CER')} | {avg('WER')} | {avg('CER_khong_dau')} | {avg('giay')} |")
        (out / "summary.md").write_text("\n".join(md), encoding="utf-8")
        print(f"-> Kết quả: {out.resolve()}")


if __name__ == "__main__":
    main()
