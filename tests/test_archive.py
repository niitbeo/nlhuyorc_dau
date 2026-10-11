import io
import json

from fastapi.testclient import TestClient

from dau_archive.auth import create_user
from dau_archive.backup import create_backup, restore_backup, verify_backup
from dau_archive.db import connect
from dau_archive.worker import run_once
from dau_archive.app import app


def login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": "password-for-tests"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def upload(client, headers, kind, title, text, *, visibility="department", department="Văn thư"):
    response = client.post(
        "/api/documents", headers=headers,
        data={"kind": kind, "title": title, "visibility": visibility, "department": department},
        files={"file": ("sample.txt", io.BytesIO(text.encode()), "text/plain")},
    )
    assert response.status_code == 202, response.text
    assert run_once()
    assert client.get("/api/jobs/" + response.json()["job_id"], headers=headers).json()["status"] == "ready"
    return response.json()["document_id"]


def test_document_management_acl_evidence_versions_and_backup(monkeypatch, tmp_path):
    data = tmp_path / "live"
    monkeypatch.setenv("DAU_DATA_DIR", str(data))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    monkeypatch.delenv("DAU_ENABLE_SEMANTIC", raising=False)
    with TestClient(app) as client:
        create_user("clerk", "password-for-tests", "staff", "Văn thư")
        create_user("teacher", "password-for-tests", "staff", "Khoa Xây dựng")
        clerk = login(client, "clerk")
        teacher = login(client, "teacher")
        doc_id = upload(client, clerk, "incoming", "Quyết định nhập học",
                        "Số: 12/QĐ-DAU\nĐà Nẵng, ngày 10 tháng 9 năm 2026\nNơi gửi: Sở Giáo dục\nNội dung tuyển sinh ngành Kiến trúc.",
                        visibility="restricted")

        detail = client.get("/api/documents/" + doc_id, headers=clerk).json()
        assert detail["pages"][0]["source"] == "native-text"
        number = next(field for field in detail["fields"] if field["field_key"] == "document_number")
        assert number["value"] == "12/QĐ-DAU"
        assert number["page_no"] == 1 and "Số:" in number["evidence"]
        assert client.patch("/api/fields/" + number["id"], headers=clerk,
                            json={"value": "12/QĐ-DAU", "status": "confirmed"}).status_code == 200
        assert client.get("/api/search", headers=clerk, params={"q": "tuyển sinh"}).json()["results"][0]["document_id"] == doc_id
        assert client.get("/api/search", headers=clerk, params={"q": "tuyen sinh"}).json()["results"][0]["document_id"] == doc_id
        assert client.get("/api/documents/" + doc_id, headers=teacher).status_code == 404
        assert client.get("/api/search", headers=teacher, params={"q": "tuyển sinh"}).json()["results"] == []
        assert client.get("/api/documents", headers=teacher).json() == []
        assert client.post("/api/documents/" + doc_id + "/grants", headers=clerk,
                           json={"username": "teacher"}).status_code == 200
        assert client.get("/api/documents/" + doc_id, headers=teacher).status_code == 200
        assert client.get("/api/search", headers=teacher, params={"q": "tuyển sinh"}).json()["results"]
        assert client.patch("/api/documents/" + doc_id, headers=clerk,
                            json={"title": "Quyết định nhập học 2026", "visibility": "restricted"}).status_code == 200
        assert client.get("/api/documents/" + doc_id, headers=clerk).json()["document"]["title"] == "Quyết định nhập học 2026"
        assert client.patch("/api/fields/" + number["id"], headers=teacher,
                            json={"value": "bad", "status": "confirmed"}).status_code == 403
        grant = client.get("/api/documents/" + doc_id, headers=clerk).json()["grants"][0]
        assert client.delete("/api/documents/" + doc_id + "/grants/" + grant["id"], headers=clerk).status_code == 200
        assert client.get("/api/documents/" + doc_id, headers=teacher).status_code == 404

        newer = client.post("/api/documents/" + doc_id + "/versions", headers=clerk,
                            files={"file": ("v2.txt", io.BytesIO(b"Ban sua doi lan 2"), "text/plain")})
        assert newer.status_code == 202, newer.text
        assert run_once()
        revised = client.get("/api/documents/" + doc_id, headers=clerk).json()
        assert len(revised["versions"]) == 2
        assert revised["versions"][0]["version_no"] == 2
        assert revised["pages"][0]["text"] == "Ban sua doi lan 2"
        old_version = revised["versions"][1]["id"]
        assert client.get("/api/documents/" + doc_id, headers=clerk,
                          params={"version_id": old_version}).json()["pages"][0]["text"].startswith("Số: 12")
        assert client.get("/api/documents/" + doc_id + "/download", headers=clerk,
                          params={"version_id": old_version}).content.startswith(b"S\xe1\xbb\x91:")
        assert client.get("/api/search", headers=clerk, params={"q": "tuyển sinh"}).json()["results"] == []
        assert client.get("/api/documents/" + doc_id + "/download", headers=clerk).content == b"Ban sua doi lan 2"

        second = upload(client, clerk, "iso", "Quy trình lưu trữ",
                        "Mã tài liệu: QT.01\nNgày hiệu lực: 01/10/2026\nQuy trình lưu trữ hồ sơ ISO.")
        relation = client.post("/api/documents/" + doc_id + "/relations", headers=clerk,
                               json={"target_id": second, "relation_type": "related", "evidence": "Hồ sơ cùng đợt"})
        assert relation.status_code == 200, relation.text
        assert any(item["target_id"] == second for item in client.get("/api/documents/" + doc_id, headers=clerk).json()["relations"])

    archive = tmp_path / "backup.tar.gz"
    create_backup(archive)
    assert verify_backup(archive)["valid"]
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    monkeypatch.setenv("DAU_DATA_DIR", str(restored))
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 1
    assert (restored / "blobs").exists()


def test_existing_ocr_pages_and_list_limit_after_acl(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    with TestClient(app) as client:
        create_user("alpha", "password-for-tests", "staff", "Khoa A")
        create_user("beta", "password-for-tests", "staff", "Khoa B")
        alpha = login(client, "alpha")
        beta = login(client, "beta")
        response = client.post(
            "/api/documents", headers=alpha,
            data={"kind": "lesson", "title": "Giáo án Bê tông", "visibility": "department", "department": "Khoa A",
                  "ocr_pages_json": json.dumps([{"text": "Mã học phần: XD101\nTên học phần: Kết cấu bê tông"},
                                                {"text": "Năm học: 2026-2027\nBài giảng kết cấu."}])},
            files={"file": ("scan.png", io.BytesIO(b"placeholder-image"), "image/png")},
        )
        assert response.status_code == 202, response.text
        assert run_once()
        doc_id = response.json()["document_id"]
        detail = client.get("/api/documents/" + doc_id, headers=alpha).json()
        assert [p["source"] for p in detail["pages"]] == ["existing-ocr", "existing-ocr"]
        assert any(f["field_key"] == "academic_year" and f["page_no"] == 2 for f in detail["fields"])
        upload(client, beta, "other", "Hidden", "Van ban rieng", department="Khoa B")
        assert [d["id"] for d in client.get("/api/documents?limit=1", headers=alpha).json()] == [doc_id]


def test_failed_ocr_can_retry_after_importing_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    monkeypatch.delenv("DAU_OCR_URL", raising=False)
    with TestClient(app) as client:
        create_user("clerk", "password-for-tests", "staff", "Văn thư")
        headers = login(client, "clerk")
        result = client.post("/api/documents", headers=headers,
                             data={"kind": "incoming", "title": "Ảnh quét", "department": "Văn thư"},
                             files={"file": ("scan.png", io.BytesIO(b"image-placeholder"), "image/png")})
        assert result.status_code == 202
        assert run_once()
        document_id = result.json()["document_id"]
        version_id = result.json()["version_id"]
        assert client.get("/api/jobs/" + result.json()["job_id"], headers=headers).json()["status"] == "failed"
        with connect() as db:
            blob = db.execute("SELECT blob_name FROM versions WHERE id=?", (version_id,)).fetchone()[0]
        (tmp_path / "archive" / "blobs" / (blob + ".ocr.json")).write_text(
            json.dumps([{"text": "Số: 22/CV-DAU\nNội dung OCR sau khi sửa"}]), encoding="utf-8")
        response = client.post(f"/api/documents/{document_id}/versions/{version_id}/retry", headers=headers)
        assert response.status_code == 202
        assert run_once()
        assert client.get("/api/jobs/" + result.json()["job_id"], headers=headers).json()["status"] == "ready"
        assert client.get("/api/documents/" + document_id, headers=headers).json()["pages"][0]["source"] == "existing-ocr"
