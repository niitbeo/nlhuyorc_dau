import io
import time

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dau_archive import model_eval
from dau_archive.app import app
from dau_archive.auth import create_user


def _login(client, username):
    result = client.post("/api/auth/login", json={
        "username": username, "password": "password-for-tests"})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json()["token"]}


def test_model_check_is_admin_only_and_bounds_work(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    monkeypatch.setattr(model_eval, "availability", lambda: {
        "printed": True, "handwritten": True, "gemini": False})
    monkeypatch.setattr(model_eval, "latest", lambda: None)
    calls = []

    def record(*args):
        calls.append(args)
        return {"id": "test", "status": "running"}

    monkeypatch.setattr(model_eval, "start", record)
    with TestClient(app) as client:
        create_user("model-admin", "password-for-tests", "admin", "Văn thư")
        create_user("model-staff", "password-for-tests", "staff", "Văn thư")
        admin, staff = _login(client, "model-admin"), _login(client, "model-staff")
        assert client.get("/api/admin/model-check", headers=staff).status_code == 403
        assert client.post("/api/admin/model-check", headers=staff, json={}).status_code == 403
        assert client.get("/api/admin/model-check", headers=admin).status_code == 200
        assert client.post("/api/admin/model-check", headers=admin,
                           json={"printed_count": 100}).status_code == 422
        started = client.post("/api/admin/model-check", headers=admin,
                              json={"printed_count": 2, "handwritten_count": 3})
        assert started.status_code == 202
        assert calls == [(2, 3, False)]


def test_metrics_count_vietnamese_diacritics():
    perfect = model_eval.score("CỘNG HÒA", "CỘNG HÒA", 1.25)
    changed = model_eval.score("CỘNG HÒA", "CỘNG HOA", 1.25)
    assert perfect["cer"] == perfect["wer"] == 0
    assert changed["cer"] > 0 and changed["wer"] > 0


def _png():
    output = io.BytesIO()
    Image.new("RGB", (120, 50), "white").save(output, format="PNG")
    return output.getvalue()


def test_uploaded_model_check_is_admin_only_and_validates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    calls = []
    monkeypatch.setattr(model_eval, "start_upload", lambda *args: calls.append(args) or {"status": "running"})
    with TestClient(app) as client:
        create_user("upload-admin", "password-for-tests", "admin", "Văn thư")
        create_user("upload-staff", "password-for-tests", "staff", "Văn thư")
        admin, staff = _login(client, "upload-admin"), _login(client, "upload-staff")
        files = {"file": ("test.png", _png(), "image/png")}
        assert client.post("/api/admin/model-check/upload", headers=staff, files=files).status_code == 403
        started = client.post("/api/admin/model-check/upload", headers=admin, files=files,
                              data={"first_page": "1", "page_count": "1", "reference_text": "Xin chào",
                                    "compare_gemini": "false"})
        assert started.status_code == 202
        assert calls[0][1:] == ("test.png", 1, 1, "Xin chào", False)
        assert client.post("/api/admin/model-check/upload", headers=admin, files={
            "file": ("huge.png", b"x" * (model_eval.MAX_UPLOAD_BYTES + 1), "image/png")
        }).status_code == 422


def test_uploaded_pages_and_optional_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(model_eval, "gemini_key", lambda: "configured")
    monkeypatch.setattr(model_eval, "_ocr", lambda sample, mode: (
        "Xin chào" if mode != "handwritten" else "Xin chao", 0.5,
        {"detector": "paddle", "line_count": 1, "selected_handwritten": 0, "warning": None}))
    monkeypatch.setattr(model_eval, "_gemini", lambda sample: ("Xin chào", 0.25))
    with model_eval._lock:
        model_eval._job = None
    job = model_eval.start_upload(_png(), "test.png", 1, 1, "Xin chào", True)
    for _ in range(100):
        result = model_eval.latest()
        if result["status"] != "running":
            break
        time.sleep(0.02)
    assert result["status"] == "ready"
    assert result["id"] == job["id"]
    assert result["samples"][0]["local"]["auto"]["text"] == "Xin chào"
    assert {row["model"]: row["cer"] for row in result["summary"]}["auto"] == 0
    assert {row["model"]: row["cer"] for row in result["summary"]}["handwritten"] > 0
    assert result["samples"][0]["gemini"]["text"] == "Xin chào"
    with model_eval._lock:
        model_eval._job = None

    pdf = fitz.open()
    pdf.new_page()
    pdf.new_page()
    pages = model_eval._upload_pages(pdf.tobytes(), "scan.pdf", 2, 1)
    assert len(pages) == 1 and pages[0]["page_no"] == 2
    with pytest.raises(ValueError, match="Chỉ nhận PDF"):
        model_eval._upload_pages(b"plain text", "notes.txt", 1, 1)


def test_upload_without_reference_never_calls_gemini(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(model_eval, "_ocr", lambda sample, mode: (
        "Xin chào", 0.1, {"detector": "paddle", "line_count": 1}))
    monkeypatch.setattr(model_eval, "_gemini", lambda sample: pytest.fail("Gemini called without opt-in"))
    with model_eval._lock:
        model_eval._job = None
    model_eval.start_upload(_png(), "test.png", 1, 1, "", False)
    for _ in range(100):
        result = model_eval.latest()
        if result["status"] != "running":
            break
        time.sleep(0.02)
    assert result["status"] == "ready"
    assert all(row["cer"] is None and row["wer"] is None for row in result["summary"])
    with model_eval._lock:
        model_eval._job = None
