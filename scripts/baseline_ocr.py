"""Giai đoạn 1 - Đo mốc (baseline) PaddleOCR trên tài liệu tiếng Việt.

- Đầu vào: thư mục chứa ảnh (png/jpg/tif/bmp) và/hoặc PDF (quét đệ quy).
- Nếu cạnh file ảnh có file `<tên>.gt.txt` (nhãn đúng) -> tính CER/WER.
- Đầu ra (mỗi trang): text.txt, lines.json, vis.jpg (khung xanh = tin cậy cao, đỏ = thấp)
  và file tổng hợp summary.csv + summary.md.

Ví dụ:
  python scripts/baseline_ocr.py --input data/synthetic --out results/synthetic
  python scripts/baseline_ocr.py --input samples --out results/samples
  python scripts/baseline_ocr.py --input samples --rec latin_PP-OCRv5_mobile_rec,PP-OCRv5_server_rec
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
sys.stdout.reconfigure(encoding="utf-8")

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from metrics import report  # noqa: E402

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
LOW_CONF = 0.80


def iter_pages(input_dir: Path, dpi: int):
    """Sinh (tên trang, ảnh BGR, đường dẫn nhãn đúng hoặc None)."""
    for p in sorted(input_dir.rglob("*")):
        ext = p.suffix.lower()
        rel = p.relative_to(input_dir).with_suffix("")
        if ext in IMG_EXT:
            img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                print(f"[!] Không đọc được ảnh: {p}")
                continue
            gt = p.with_name(p.stem + ".gt.txt")
            yield str(rel), img, gt if gt.exists() else None
        elif ext == ".pdf":
            import fitz  # PyMuPDF

            doc = fitz.open(str(p))
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=dpi)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                img = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                gt = p.with_name(f"{p.stem}_p{i + 1:03d}.gt.txt")
                yield f"{rel}_p{i + 1:03d}", img, gt if gt.exists() else None


def estimate_skew(polys) -> float:
    """Góc nghiêng trang (radian) = trung vị góc cạnh trên của các box đủ dài."""
    angles = []
    for poly in polys:
        p = np.asarray(poly, dtype=np.float64)
        if len(p) < 2:
            continue
        (x0, y0), (x1, y1) = p[0], p[1]
        if x1 - x0 > 3 * max(1.0, float(p[:, 1].max() - p[:, 1].min()) / 2):
            angles.append(np.arctan2(y1 - y0, x1 - x0))
    return float(np.median(angles)) if angles else 0.0


def group_rows(polys, texts, scores):
    """Gom các box thành dòng theo thứ tự đọc (trên->dưới, trái->phải), có bù góc nghiêng."""
    theta = estimate_skew(polys)
    c, s_ = np.cos(-theta), np.sin(-theta)
    rot = np.array([[c, -s_], [s_, c]])
    items = []
    for poly, t, s in zip(polys, texts, scores):
        poly = np.asarray(poly)
        q = poly.astype(np.float64) @ rot.T  # toạ độ sau khi "duỗi thẳng" trang
        ys, xs = q[:, 1], q[:, 0]
        items.append({"text": t, "score": float(s), "x": float(xs.min()),
                      "yc": float(ys.mean()), "h": float(ys.max() - ys.min()), "poly": poly.tolist()})

    items.sort(key=lambda d: d["yc"])
    rows = []
    for it in items:
        if rows and abs(it["yc"] - rows[-1]["yc"]) < 0.5 * max(it["h"], rows[-1]["h"]):
            rows[-1]["items"].append(it)
        else:
            rows.append({"yc": it["yc"], "h": it["h"], "items": [it]})
    lines = []
    for r in rows:
        r["items"].sort(key=lambda d: d["x"])
        lines.append(" ".join(i["text"] for i in r["items"]))
    return lines, items


def draw_vis(img, items, path):
    vis = img.copy()
    for it in items:
        color = (0, 170, 0) if it["score"] >= LOW_CONF else (0, 0, 255)
        cv2.polylines(vis, [np.asarray(it["poly"], dtype=np.int32)], True, color, 2)
    cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(path))


def build_ocr(det, rec, device):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=det,
        text_recognition_model_name=rec,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
    )


def run(args, rec_name):
    out_root = Path(args.out) / rec_name
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== Det: {args.det} | Rec: {rec_name} | Device: {args.device} ===")
    ocr = build_ocr(args.det, rec_name, args.device)

    rows = []
    for name, img, gt_path in iter_pages(Path(args.input), args.dpi):
        t0 = time.perf_counter()
        res = ocr.predict(img)[0]
        dt = time.perf_counter() - t0

        lines, items = group_rows(res["rec_polys"], res["rec_texts"], res["rec_scores"])
        hyp = "\n".join(lines)
        page_dir = out_root / name
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "text.txt").write_text(hyp, encoding="utf-8")
        (page_dir / "lines.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        draw_vis(img, items, page_dir / "vis.jpg")

        scores = [i["score"] for i in items]
        row = {
            "trang": name,
            "so_box": len(items),
            "tin_cay_TB": round(float(np.mean(scores)), 4) if scores else 0,
            "box_tin_cay_thap": sum(s < LOW_CONF for s in scores),
            "giay": round(dt, 2),
        }
        if gt_path:
            ref = gt_path.read_text(encoding="utf-8")
            row.update(report(ref, hyp))
        rows.append(row)
        extra = f" | CER {row['CER']}% WER {row['WER']}% CER_khong_dau {row['CER_khong_dau']}%" if gt_path else ""
        print(f"  {name}: {len(items)} box, {dt:.2f}s{extra}")

    if not rows:
        print("[!] Không tìm thấy ảnh/PDF nào trong", args.input)
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(out_root / "summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    md = [f"# Baseline: det={args.det}, rec={rec_name}\n", "| " + " | ".join(keys) + " |",
          "|" + "---|" * len(keys)]
    md += ["| " + " | ".join(str(r.get(k, "")) for k in keys) + " |" for r in rows]
    if any("CER" in r for r in rows):
        # Trung bình theo nhóm (thư mục cha) - ví dụ clean / scan / bad_scan
        groups = {}
        for r in rows:
            if "CER" in r:
                groups.setdefault(Path(r["trang"]).parts[0], []).append(r)
        md += ["\n## Trung bình theo nhóm\n", "| Nhóm | Số trang | CER % | WER % | CER không dấu % | Giây/trang |",
               "|---|---|---|---|---|---|"]
        for g, rs in groups.items():
            avg = lambda k: round(float(np.mean([x[k] for x in rs])), 2)  # noqa: E731
            md.append(f"| {g} | {len(rs)} | {avg('CER')} | {avg('WER')} | {avg('CER_khong_dau')} | {avg('giay')} |")
    (out_root / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print(f"-> Kết quả: {out_root.resolve()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="samples")
    ap.add_argument("--out", default="results/baseline")
    ap.add_argument("--det", default="PP-OCRv5_server_det")
    ap.add_argument("--rec", default="latin_PP-OCRv5_mobile_rec",
                    help="một hoặc nhiều model nhận dạng, cách nhau dấu phẩy")
    ap.add_argument("--device", default="gpu:0")
    ap.add_argument("--dpi", type=int, default=200, help="độ phân giải khi render PDF")
    args = ap.parse_args()
    for rec in args.rec.split(","):
        run(args, rec.strip())


if __name__ == "__main__":
    main()
