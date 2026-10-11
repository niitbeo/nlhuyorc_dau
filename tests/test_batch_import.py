import io
import zipfile

from fastapi.testclient import TestClient

from dau_archive.app import app
from dau_archive.auth import create_user
from dau_archive.backup import create_backup, restore_backup, verify_backup
from dau_archive.batch_import import run_once as import_once
from dau_archive.db import connect
from dau_archive.worker import run_once as ocr_once


def _archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("DAU-ISO/Phòng A/QT Lưu trữ/Quy trình lưu trữ.txt",
                         "Mã tài liệu: QT.01\nQuy trình lưu trữ hồ sơ nội bộ.")
        archive.writestr("DAU-ISO/Phòng A/QT Lưu trữ/Biểu mẫu/Mẫu lưu trữ.txt",
                         "Biểu mẫu lưu trữ hồ sơ nội bộ.")
        archive.writestr("DAU-ISO/Phòng A/QT Lưu trữ/Biểu mẫu/Bản sao mẫu.txt",
                         "Biểu mẫu lưu trữ hồ sơ nội bộ.")
        archive.writestr("DAU-ISO/Phòng A/QT Lưu trữ/Văn bản/Quy định.txt",
                         "Văn bản viện dẫn của quy trình.")
        archive.writestr("../ngoai-thu-muc.txt", "Không hợp lệ")
    return output.getvalue()


def test_reusable_batch_import_classification_sources_acl_and_export(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    with TestClient(app) as client:
        create_user("admin-batch", "password-for-tests", "admin", "Văn thư")
        create_user("outside", "password-for-tests", "staff", "Phòng B")
        admin_token = client.post("/api/auth/login", json={
            "username": "admin-batch", "password": "password-for-tests"}).json()["token"]
        outside_token = client.post("/api/auth/login", json={
            "username": "outside", "password": "password-for-tests"}).json()["token"]
        admin = {"Authorization": "Bearer " + admin_token}
        outside = {"Authorization": "Bearer " + outside_token}
        response = client.post("/api/import-batches", headers=admin,
                               data={"department": "Văn thư", "visibility": "department",
                                     "kind_hint": "iso", "derive_department": "true"},
                               files=[("files", ("demo.zip", io.BytesIO(_archive()), "application/zip"))])
        assert response.status_code == 202, response.text
        batch_id = response.json()["id"]
        assert client.get("/api/import-batches/" + batch_id, headers=outside).status_code == 404
        assert import_once()
        batch = client.get("/api/import-batches/" + batch_id, headers=admin).json()
        assert batch["status"] == "ready"
        assert batch["total_entries"] == 5
        assert batch["imported_entries"] == 4
        assert batch["skipped_entries"] == 1
        assert "Đường dẫn" in batch["recent_errors"][0]["error"]

        with connect() as db:
            rows = db.execute("SELECT d.*,e.archive_path,v.blob_name FROM documents d "
                              "JOIN import_batch_entries e ON e.document_id=d.id "
                              "JOIN versions v ON v.document_id=d.id "
                              "WHERE e.batch_id=?", (batch_id,)).fetchall()
            assert len(rows) == 4
            assert len({row["blob_name"] for row in rows}) == 3
            procedure = next(row for row in rows if row["subtype"] == "procedure")
            forms = [row for row in rows if row["subtype"] == "form"]
            assert len(forms) == 2
            assert all(row["kind"] == "iso" and row["department"] == "Phòng A" for row in rows)
            assert db.execute("SELECT COUNT(*) FROM relations WHERE relation_type='in_file' "
                              "AND status='proposed'").fetchone()[0] == 3
        assert ocr_once(fast_only=True)
        while ocr_once():
            pass
        detail = client.get("/api/documents/" + procedure["id"], headers=admin).json()
        assert detail["sources"][0]["archive_path"].startswith("DAU-ISO/")
        assert detail["pages"][0]["source"] == "native-text"
        assert client.get("/api/documents/" + procedure["id"] + "/export?format=txt",
                          headers=admin).text.startswith("--- Trang 1 ---")
        structured = client.get("/api/documents/" + procedure["id"] + "/export?format=json",
                                headers=admin).json()
        assert structured["pages"][0]["text"].startswith("Mã tài liệu")
        assert structured["sources"][0]["source_role"] == "procedure"
        assert client.get("/api/documents/" + procedure["id"], headers=outside).status_code == 404
        assert client.patch("/api/documents/" + procedure["id"], headers=admin,
                            json={"title": "QT lưu trữ chuẩn", "visibility": "department",
                                  "kind": "iso", "subtype": "procedure"}).status_code == 200
        confirmed = client.get("/api/documents/" + procedure["id"], headers=admin).json()
        assert confirmed["document"]["classification_status"] == "confirmed"
    backup = tmp_path / "bulk-backup.tar.gz"
    create_backup(backup)
    assert verify_backup(backup)["valid"]
    restore_backup(backup, tmp_path / "restored")
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path / "restored"))
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM import_batch_entries WHERE batch_id=?",
                          (batch_id,)).fetchone()[0] == 5
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 4
