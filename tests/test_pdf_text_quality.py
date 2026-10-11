from dau_archive import processing
from dau_archive.ocr_local import sort_reading_order
from dau_archive.text_quality import looks_garbled_vietnamese


def test_legacy_font_text_falls_back_to_ocr(monkeypatch, tmp_path):
    bad = "s¬ líc mét sè nÐt vÒ gia ®×nh «ng NguyÔn §×nh" * 3
    assert looks_garbled_vietnamese(bad)
    assert not looks_garbled_vietnamese(
        "Hồi ký của ông Nguyễn Đình Chu, con trai trưởng của Liệt sĩ Nguyễn Đình Liễn."
    )
    assert not looks_garbled_vietnamese("Nhãn hiệu ® đã đăng ký.")

    class Page:
        def get_text(self, kind):
            assert kind == "text"
            return bad

        def get_pixmap(self, matrix):
            return self

        def tobytes(self, format):
            assert format == "png"
            return b"page-image"

    class Pdf:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __len__(self):
            return 1

        def __iter__(self):
            return iter([Page()])

    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("fitz.open", lambda _: Pdf())
    monkeypatch.setattr(processing, "_ocr_image", lambda image, filename: "Hồi ký của ông Nguyễn Đình Chu")
    pages = processing.extract_pages("garbled.pdf", "garbled.pdf")
    assert pages == [{"page_no": 1, "text": "Hồi ký của ông Nguyễn Đình Chu", "source": "ocr"}]


def test_two_column_page_reads_left_column_before_right():
    crops = []
    for row in range(8):
        crops.extend([
            {"box": [90, row * 40, 430, row * 40 + 22], "text": f"L{row}"},
            {"box": [570, row * 40, 900, row * 40 + 22], "text": f"R{row}"},
        ])
    sort_reading_order(crops, 1000)
    assert [item["text"] for item in crops] == [
        *(f"L{row}" for row in range(8)), *(f"R{row}" for row in range(8))
    ]
