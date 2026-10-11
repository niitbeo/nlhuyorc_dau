import io
import concurrent.futures
import threading
import time

import fitz
from fastapi.testclient import TestClient
from PIL import Image

from dau_archive import ocr_local


def _pdf_with_text_and_scan() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Van ban goc co du noi dung de duoc lay truc tiep tu PDF tren trang mot.")
    scanned = document.new_page()
    scanned.insert_text((72, 72), "SCAN PAGE TWO")
    png = scanned.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    document.delete_page(1)
    page = document.new_page()
    page.insert_image(page.rect, stream=png)
    content = document.tobytes()
    document.close()
    return content


def _ready_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"ready", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("OCR job did not finish")


def test_pdf_pages_correction_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_local, "jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(ocr_local, "recognize_image", lambda image, mode, detector="auto": ([
        {"box": [0, 0, 20, 20], "text": "SCAN PAGE TWO"}
    ], "paddle_server", None))
    with TestClient(ocr_local.app) as client:
        created = client.post("/api/jobs", files={"file": ("sample.pdf", _pdf_with_text_and_scan(), "application/pdf")})
        assert created.status_code == 202, created.text
        assert created.json()["page_count"] == 2
        job_id = created.json()["id"]
        job = _ready_job(client, job_id)
        assert job["status"] == "ready", job["error"]
        assert [page["source"] for page in job["results"]] == ["native-pdf", "ocr"]
        assert "SCAN PAGE TWO" in job["results"][1]["text"]

        preview = client.get(f"/api/jobs/{job_id}/pages/2/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/jpeg"

        saved = client.patch(f"/api/jobs/{job_id}/pages/2", json={"text": "Trang hai đã sửa"})
        assert saved.status_code == 200
        exported = client.get(f"/api/jobs/{job_id}/export/txt")
        assert exported.status_code == 200
        assert "Trang hai đã sửa" in exported.text
        assert "Trang 1" in exported.text
        assert client.get(f"/api/jobs/{job_id}/export/json").json()["pages"][1]["corrected_text"] == "Trang hai đã sửa"


def test_image_and_invalid_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_local, "jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(ocr_local, "recognize_image", lambda image, mode, detector="auto": ([
        {"box": [0, 0, image.width, image.height], "text": mode}
    ], "paddle_server", None))
    image = Image.new("RGB", (80, 40), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with TestClient(ocr_local.app) as client:
        created = client.post("/api/jobs", data={"mode": "handwritten"},
                              files={"file": ("note.png", buffer.getvalue(), "image/png")})
        assert created.status_code == 202, created.text
        job = _ready_job(client, created.json()["id"])
        assert job["status"] == "ready", job["error"]
        assert job["results"][0]["text"] == "handwritten"
        invalid = client.post("/api/jobs", files={"file": ("wrong.pdf", b"not a document", "application/pdf")})
        assert invalid.status_code == 422


def test_ocr_request_does_not_block_homepage(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_local, "jobs_dir", lambda: tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_recognize(image, mode, detector="auto"):
        started.set()
        assert release.wait(3)
        return ([{"box": [0, 0, image.width, image.height], "text": "OK"}],
                "simple", None)

    monkeypatch.setattr(ocr_local, "recognize_image", slow_recognize)
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(buffer, format="PNG")
    with TestClient(ocr_local.app) as client, concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        task = pool.submit(client.post, "/ocr/image", files={"file": ("test.png", buffer.getvalue(), "image/png")})
        assert started.wait(2)
        homepage = pool.submit(client.get, "/")
        try:
            assert homepage.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert task.result(timeout=3).status_code == 200


def test_paddle_boxes_are_rectified_and_read_in_page_order(monkeypatch):
    class Detection:
        json = {"res": {"dt_polys": [
            [[45, 55], [145, 45], [148, 68], [48, 78]],
            [[20, 12], [120, 12], [120, 32], [20, 32]],
        ], "dt_scores": [0.9, 0.95]}}

    class Detector:
        def predict(self, input):
            return iter([Detection()])

    class Recognizer:
        def predict(self, crop):
            assert crop.width >= 100 and crop.height >= 20
            return "dòng chữ"

    monkeypatch.setattr(ocr_local, "paddle_detector", lambda model_name: Detector())
    monkeypatch.setattr(ocr_local, "predictor", lambda mode: Recognizer())
    image = Image.new("RGB", (180, 100), "white")
    lines, detector, warning = ocr_local.recognize_image(image, "printed", "paddle")
    assert detector == "paddle_server" and warning is None
    assert [line["box"][1] for line in lines] == [12, 45]
    assert lines[0]["detection_score"] == 0.95
    assert len(lines[1]["polygon"]) == 4


def test_auto_selects_recognizer_for_each_detected_line(monkeypatch):
    crops = [
        {"box": [0, 0, 100, 20], "polygon": [[0, 0], [100, 0], [100, 20], [0, 20]],
         "score": .9, "crop": Image.new("RGB", (100, 20), "white")},
        {"box": [0, 30, 100, 50], "polygon": [[0, 30], [100, 30], [100, 50], [0, 50]],
         "score": .8, "crop": Image.new("RGB", (100, 20), "white")},
    ]

    class Recognizer:
        def __init__(self, name):
            self.name = name

        def predict(self, crop, return_prob=False):
            return (self.name, .95) if return_prob else self.name

    monkeypatch.setattr(ocr_local, "detected_crops", lambda image, detector: (crops, "paddle_server", None))
    monkeypatch.setattr(ocr_local, "classify_line_crops", lambda items: [("printed", .97), ("handwritten", .92)])
    monkeypatch.setattr(ocr_local, "predictor", lambda name: Recognizer(name))
    lines, detector, warning = ocr_local.recognize_image(Image.new("RGB", (100, 60)), "auto")
    assert detector == "paddle_server" and warning is None
    assert [line["text"] for line in lines] == ["printed", "handwritten"]
    assert [line["recognition_mode"] for line in lines] == ["printed", "handwritten"]
    assert [line["classification_score"] for line in lines] == [.97, .92]


def test_auto_rechecks_uncertain_handwriting(monkeypatch):
    crops = [{"box": [0, 0, 100, 20], "polygon": [], "score": .9,
              "crop": Image.new("RGB", (100, 20), "white")}]

    class Recognizer:
        def __init__(self, mode):
            self.mode = mode

        def predict(self, crop, return_prob=False):
            return (self.mode, .92 if self.mode == "handwritten" else .82)

    monkeypatch.setattr(ocr_local, "detected_crops", lambda image, detector: (crops, "paddle_server", None))
    monkeypatch.setattr(ocr_local, "classify_line_crops", lambda items: [("printed", .74)])
    monkeypatch.setattr(ocr_local, "predictor", lambda mode: Recognizer(mode))
    lines, _, _ = ocr_local.recognize_image(Image.new("RGB", (100, 20)), "auto")
    assert lines[0]["recognition_mode"] == "handwritten"
    assert lines[0]["selection_method"] == "recognition_score"
