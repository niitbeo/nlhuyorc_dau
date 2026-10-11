"""Sinh trang văn bản tiếng Việt giả lập bản scan (có sẵn nhãn đúng) để đo CER tự động.

Mỗi trang gồm các dòng văn bản theo văn phong "chương trình đào tạo" của Bộ GD&ĐT,
được render bằng font Windows rồi làm bẩn theo 3 mức: clean / scan / bad_scan.

Chạy:  python scripts/make_synthetic_test.py --out data/synthetic --pages 4
"""
import argparse
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LINES = [
    "BỘ GIÁO DỤC VÀ ĐÀO TẠO",
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
    "Độc lập - Tự do - Hạnh phúc",
    "CHƯƠNG TRÌNH ĐÀO TẠO TRÌNH ĐỘ ĐẠI HỌC",
    "Ngành đào tạo: Công nghệ thông tin",
    "Mã ngành: 7480201",
    "Hình thức đào tạo: Chính quy tập trung",
    "Thời gian đào tạo: 4 năm (8 học kỳ)",
    "Khối lượng kiến thức toàn khóa: 130 tín chỉ",
    "1. Mục tiêu đào tạo",
    "Đào tạo cử nhân có phẩm chất chính trị, đạo đức nghề nghiệp và sức khỏe tốt.",
    "Có kiến thức cơ bản về khoa học tự nhiên, xã hội và nhân văn.",
    "Nắm vững kiến thức chuyên môn để giải quyết các vấn đề thực tiễn.",
    "2. Chuẩn đầu ra của chương trình đào tạo",
    "Vận dụng được kiến thức nền tảng về toán học và khoa học máy tính.",
    "Có khả năng làm việc nhóm, giao tiếp hiệu quả và học tập suốt đời.",
    "Đạt chuẩn năng lực ngoại ngữ bậc 3/6 theo Khung năng lực 6 bậc dùng cho Việt Nam.",
    "3. Khối lượng kiến thức và cấu trúc chương trình",
    "Kiến thức giáo dục đại cương: 30 tín chỉ",
    "Kiến thức cơ sở ngành: 45 tín chỉ; kiến thức chuyên ngành: 40 tín chỉ",
    "Thực tập tốt nghiệp và khóa luận tốt nghiệp: 15 tín chỉ",
    "Học phần Triết học Mác - Lênin (3 tín chỉ), mã học phần: LLCT120205",
    "Học phần Kinh tế chính trị Mác - Lênin (2 tín chỉ)",
    "Học phần Tư tưởng Hồ Chí Minh (2 tín chỉ)",
    "Học phần Giáo dục thể chất và Giáo dục quốc phòng - an ninh",
    "Cấu trúc dữ liệu và giải thuật; Cơ sở dữ liệu; Mạng máy tính",
    "Điều kiện tốt nghiệp: tích lũy đủ số tín chỉ, điểm trung bình tích lũy từ 2,00 trở lên.",
    "Căn cứ Thông tư số 17/2021/TT-BGDĐT ngày 22 tháng 6 năm 2021",
    "Quy định về chuẩn chương trình đào tạo; xây dựng, thẩm định và ban hành",
    "Phương pháp kiểm tra, đánh giá: chuyên cần 10%, giữa kỳ 30%, cuối kỳ 60%.",
    "Giảng viên phụ trách học phần chịu trách nhiệm cập nhật đề cương chi tiết.",
    "Hiệu trưởng quyết định ban hành chương trình đào tạo sau khi được Hội đồng thẩm định.",
    "Nơi nhận: Như Điều 3; Lưu: VT, ĐT.",
    "KT. HIỆU TRƯỞNG - PHÓ HIỆU TRƯỞNG",
    "Ngày 15 tháng 8 năm 2024",
    "Quyết định có hiệu lực kể từ ngày ký; các ông (bà) Trưởng phòng Đào tạo chịu trách nhiệm thi hành.",
]

FONTS = [
    r"C:\Windows\Fonts\times.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
]

PAGE_W, PAGE_H = 1654, 2339  # A4 @ 200 dpi


def render_page(lines, font_path, font_size):
    img = Image.new("L", (PAGE_W, PAGE_H), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    y = 150
    kept = []
    for line in lines:
        # Ngắt dòng nếu quá dài
        words, cur, wrapped = line.split(), "", []
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=font) > PAGE_W - 300 and cur:
                wrapped.append(cur)
                cur = w
            else:
                cur = test
        wrapped.append(cur)
        for wl in wrapped:
            if y + font_size * 1.6 > PAGE_H - 150:
                return img, kept
            draw.text((150, y), wl, font=font, fill=0)
            kept.append(wl)
            y += int(font_size * 1.7)
    return img, kept


def degrade(img: Image.Image, level: str, rng: random.Random) -> Image.Image:
    if level == "clean":
        return img
    angle = rng.uniform(-1.0, 1.0) if level == "scan" else rng.uniform(-2.5, 2.5)
    img = img.rotate(angle, expand=False, fillcolor=255, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(0.6 if level == "scan" else 1.1))
    arr = np.asarray(img).astype(np.float32)
    sigma = 8 if level == "scan" else 18
    arr += np.random.default_rng(rng.randint(0, 10**6)).normal(0, sigma, arr.shape)
    if level == "bad_scan":
        arr = arr * 0.85 + 25  # giảm tương phản, nền xám
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if level == "bad_scan":
        # giảm độ phân giải (giả lập scan 100 dpi) rồi phóng lại
        img = img.resize((PAGE_W // 2, PAGE_H // 2), Image.BILINEAR).resize((PAGE_W, PAGE_H), Image.BILINEAR)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--pages", type=int, default=4, help="số trang mỗi mức độ")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    for level in ["clean", "scan", "bad_scan"]:
        d = out / level
        d.mkdir(parents=True, exist_ok=True)
        for i in range(args.pages):
            font = FONTS[i % len(FONTS)]
            lines = rng.sample(LINES, k=min(22, len(LINES)))
            img, kept = render_page(lines, font, rng.choice([30, 34, 38]))
            img = degrade(img, level, rng)
            name = f"{level}_{i:02d}_{Path(font).stem}"
            img.save(d / f"{name}.png")
            (d / f"{name}.gt.txt").write_text("\n".join(kept), encoding="utf-8")
    print(f"Đã sinh {args.pages * 3} trang tại {out.resolve()}")


if __name__ == "__main__":
    main()
