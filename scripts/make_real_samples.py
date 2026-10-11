"""Lấy mẫu trang thật từ kho tài liệu để đo baseline.

- PDF số (có lớp chữ): render ảnh + trích chữ làm nhãn đúng (.gt.txt) -> tính được CER.
- PDF scan: chỉ render ảnh (chưa có nhãn) -> xem kết quả bằng mắt / gán nhãn sau.

Chạy:  python scripts/make_real_samples.py --src "DAU-ISO-..." --out samples --n-digital 6 --n-scan 10
"""
import argparse
import random
import sys
from pathlib import Path

import pymupdf

sys.stdout.reconfigure(encoding="utf-8")


def classify(doc) -> str:
    n = len(doc)
    chars = sum(len(p.get_text().strip()) for p in doc)
    return "digital" if chars / max(n, 1) > 200 else "scan"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="samples")
    ap.add_argument("--n-digital", type=int, default=6)
    ap.add_argument("--n-scan", type=int, default=10)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pdfs = sorted(Path(args.src).rglob("*.pdf"))
    rng.shuffle(pdfs)
    want = {"digital": args.n_digital, "scan": args.n_scan}
    got = {"digital": 0, "scan": 0}
    for p in pdfs:
        if all(got[k] >= want[k] for k in want):
            break
        try:
            doc = pymupdf.open(str(p))
        except Exception:
            continue
        kind = classify(doc)
        if got[kind] >= want[kind] or len(doc) == 0:
            continue
        i = rng.randrange(min(len(doc), 5))  # 1 trang ngẫu nhiên trong 5 trang đầu
        page = doc[i]
        out = Path(args.out) / f"real_{kind}"
        out.mkdir(parents=True, exist_ok=True)
        name = f"{kind}_{got[kind]:02d}"
        page.get_pixmap(dpi=args.dpi).save(str(out / f"{name}.png"))
        if kind == "digital":
            (out / f"{name}.gt.txt").write_text(page.get_text("text", sort=True), encoding="utf-8")
        (out / f"{name}.source.txt").write_text(f"{p}\ntrang {i + 1}", encoding="utf-8")
        got[kind] += 1
        print(f"[{kind}] {name} <- {p.name} (trang {i + 1})")
    print("Xong:", got)


if __name__ == "__main__":
    main()
