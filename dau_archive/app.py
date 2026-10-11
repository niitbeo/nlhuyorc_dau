from __future__ import annotations

import json
import os
import socket
import threading
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from . import model_eval
from .db import audit, connect, data_dir, init_db
from .embeddings import available as embeddings_available, model_id
from .processing import reindex_embeddings, save_blob
from .search import _acl, search
from .secrets import delete_gemini_key, gemini_key, gemini_key_source, save_gemini_key
from .worker import serve


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = threading.Event()
    thread = None
    if os.getenv("DAU_RUN_WORKER", "1") == "1":
        thread = threading.Thread(target=serve, args=(stop,), daemon=True)
        thread.start()
    yield
    stop.set()
    if thread:
        thread.join(timeout=3)


app = FastAPI(title="NLHUYOCR Document Archive", lifespan=lifespan)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_model_check_ocr_status: dict | None = None


def current_user(authorization: Optional[str] = Header(None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    user = auth.session_user(token)
    if not user:
        raise HTTPException(401, "Đăng nhập để tiếp tục")
    return user


def document_for(db, document_id: str, user, write: bool = False):
    doc = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not doc or not auth.can_read(db, user, doc):
        raise HTTPException(404, "Không tìm thấy tài liệu")
    if write and not auth.can_write(user, doc):
        raise HTTPException(403, "Không có quyền sửa tài liệu")
    return doc


class LoginBody(BaseModel):
    username: str
    password: str


class FieldBody(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    status: str = Field(pattern="^(confirmed|rejected)$")


class RelationBody(BaseModel):
    target_id: str
    relation_type: str = Field(pattern="^(replaces|cites|in_file|in_course|related)$")
    evidence: str = Field(default="", max_length=500)
    page_no: Optional[int] = Field(default=None, ge=1)


class RelationReviewBody(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected)$")


class GrantBody(BaseModel):
    username: str


class DocumentUpdateBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    visibility: str = Field(pattern="^(public|department|restricted)$")


class GeminiKeyBody(BaseModel):
    api_key: str = Field(min_length=10, max_length=500)


class ModelCheckBody(BaseModel):
    printed_count: int = Field(default=2, ge=1, le=3)
    handwritten_count: int = Field(default=3, ge=1, le=5)
    compare_gemini: bool = False


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được cấu hình API")
    return user


@app.get("/api/admin/settings/gemini")
def gemini_settings(user=Depends(require_admin)):
    return {"configured": bool(gemini_key()), "source": gemini_key_source(),
            "model": "gemini-3.8-flash"}


@app.put("/api/admin/settings/gemini")
def set_gemini_key(body: GeminiKeyBody, user=Depends(require_admin)):
    value = body.api_key.strip()
    if not value or any(character.isspace() for character in value):
        raise HTTPException(422, "API key không hợp lệ")
    save_gemini_key(value)
    with connect() as db:
        audit(db, user["id"], "gemini_key_updated", detail="gemini")
    return gemini_settings(user)


@app.delete("/api/admin/settings/gemini")
def remove_gemini_key(user=Depends(require_admin)):
    delete_gemini_key()
    with connect() as db:
        audit(db, user["id"], "gemini_key_deleted", detail="gemini")
    return gemini_settings(user)


@app.post("/api/admin/settings/gemini/test")
def test_gemini_key(user=Depends(require_admin)):
    key = gemini_key()
    if not key:
        raise HTTPException(422, "Chưa cấu hình Gemini API key")
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash",
        headers={"x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise HTTPException(502, "Không thể xác minh Gemini API key")
    except urllib.error.HTTPError as exc:
        if exc.code in {400, 401, 403}:
            raise HTTPException(422, "Google từ chối API key; hãy tạo khóa mới trong Google AI Studio") from None
        raise HTTPException(502, f"Google Gemini trả lỗi HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(503, "Không kết nối được tới Google Gemini từ máy chủ") from None
    return {"ok": True, "model": "gemini-3.8-flash"}


@app.get("/api/admin/model-check")
def model_check(user=Depends(require_admin)):
    global _model_check_ocr_status
    status = {"availability": model_eval.availability(), "latest": model_eval.latest()}
    if status["latest"] and status["latest"]["status"] == "running" and _model_check_ocr_status:
        status["ocr_service"] = _model_check_ocr_status
        return status
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
            raw = json.load(response)
        status["ocr_service"] = {"online": True,
                                 "recognizers": {name: bool(item["weights_present"])
                                                 for name, item in raw.get("recognizers", {}).items()},
                                 "classifier": bool(raw.get("classifier", {}).get("weights_present")),
                                 "detectors": {name: bool(item["ready"])
                                               for name, item in raw.get("detectors", {}).items()}}
        _model_check_ocr_status = status["ocr_service"]
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError):
        status["ocr_service"] = {"online": False}
    return status


@app.post("/api/admin/model-check", status_code=202)
def start_model_check(body: ModelCheckBody, user=Depends(require_admin)):
    try:
        return model_eval.start(body.printed_count, body.handwritten_count, body.compare_gemini)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from None


@app.post("/api/admin/model-check/upload", status_code=202)
async def start_uploaded_model_check(
    file: UploadFile = File(...), first_page: int = Form(1), page_count: int = Form(1),
    reference_text: str = Form(""), compare_gemini: bool = Form(False),
    user=Depends(require_admin),
):
    content = await file.read(model_eval.MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > model_eval.MAX_UPLOAD_BYTES:
        raise HTTPException(422, "Tệp trống hoặc vượt quá 30 MiB")
    try:
        return model_eval.start_upload(content, file.filename or "", first_page, page_count,
                                       reference_text, compare_gemini)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from None


@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"status": "ok", "embedding_model": model_id(),
            "embedding_local_ready": embeddings_available(),
            "semantic_search_enabled": os.getenv("DAU_ENABLE_SEMANTIC", "0") == "1",
            "ocr_endpoint_configured": bool(os.getenv("DAU_OCR_URL"))}


@app.post("/api/auth/login")
def login(body: LoginBody):
    token = auth.login(body.username, body.password)
    if not token:
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu")
    return {"token": token}


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None), user=Depends(current_user)):
    auth.logout(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return dict(user)


def _queue_version(db, doc_id: str, user, blob_name: str, sha256: str,
                   filename: str, mime_type: str, ocr_pages_json: Optional[str]) -> tuple[str, str]:
    if ocr_pages_json:
        try:
            payload = json.loads(ocr_pages_json)
            if not isinstance(payload, list) or not payload or len(payload) > 1000 or any(
                not isinstance(p, dict) or not isinstance(p.get("text"), str) for p in payload
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "ocr_pages_json phải là mảng trang có trường text")
        (data_dir() / "blobs" / f"{blob_name}.ocr.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    row = db.execute("SELECT COALESCE(MAX(version_no),0)+1 AS n FROM versions WHERE document_id=?", (doc_id,)).fetchone()
    version_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.execute(
        "INSERT INTO versions(id,document_id,version_no,filename,mime_type,sha256,blob_name,created_by) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (version_id, doc_id, row["n"], filename, mime_type, sha256, blob_name, user["id"]),
    )
    db.execute("INSERT INTO jobs(id,version_id) VALUES (?,?)", (job_id, version_id))
    audit(db, user["id"], "version.upload", doc_id, version_id)
    return version_id, job_id


@app.post("/api/documents", status_code=202)
def create_document(file: UploadFile = File(...), kind: str = Form(...), title: str = Form(...),
                    department: str = Form(...), visibility: str = Form("department"),
                    ocr_pages_json: Optional[str] = Form(None), user=Depends(current_user)):
    if kind not in {"incoming", "outgoing", "iso", "curriculum", "lesson", "other"}:
        raise HTTPException(422, "Loại tài liệu không hợp lệ")
    if visibility not in {"public", "department", "restricted"}:
        raise HTTPException(422, "Mức truy cập không hợp lệ")
    if not title.strip() or len(title) > 300:
        raise HTTPException(422, "Tiêu đề không hợp lệ")
    if user["role"] != "admin" and department != user["department"]:
        raise HTTPException(403, "Chỉ được tạo tài liệu trong đơn vị của mình")
    try:
        blob_name, sha256 = save_blob(file.file, file.filename or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    doc_id = str(uuid.uuid4())
    try:
        with connect() as db:
            db.execute(
                "INSERT INTO documents(id,kind,title,department,visibility,owner_id) VALUES (?,?,?,?,?,?)",
                (doc_id, kind, title.strip(), department.strip(), visibility, user["id"]),
            )
            version_id, job_id = _queue_version(db, doc_id, user, blob_name, sha256,
                                                 file.filename or "upload", file.content_type or "application/octet-stream",
                                                 ocr_pages_json)
            audit(db, user["id"], "document.create", doc_id)
    except Exception:
        (data_dir() / "blobs" / blob_name).unlink(missing_ok=True)
        (data_dir() / "blobs" / f"{blob_name}.ocr.json").unlink(missing_ok=True)
        raise
    return {"document_id": doc_id, "version_id": version_id, "job_id": job_id}


@app.post("/api/documents/{document_id}/versions", status_code=202)
def add_version(document_id: str, file: UploadFile = File(...),
                ocr_pages_json: Optional[str] = Form(None), user=Depends(current_user)):
    with connect() as db:
        document_for(db, document_id, user, write=True)
    try:
        blob_name, sha256 = save_blob(file.file, file.filename or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        with connect() as db:
            existing = db.execute("SELECT 1 FROM versions WHERE document_id=? AND sha256=?", (document_id, sha256)).fetchone()
            if existing:
                raise HTTPException(409, "Phiên bản trùng tệp đã lưu")
            version_id, job_id = _queue_version(db, document_id, user, blob_name, sha256,
                                                 file.filename or "upload", file.content_type or "application/octet-stream",
                                                 ocr_pages_json)
    except Exception:
        (data_dir() / "blobs" / blob_name).unlink(missing_ok=True)
        (data_dir() / "blobs" / f"{blob_name}.ocr.json").unlink(missing_ok=True)
        raise
    return {"document_id": document_id, "version_id": version_id, "job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, user=Depends(current_user)):
    with connect() as db:
        row = db.execute(
            "SELECT j.*,v.document_id FROM jobs j JOIN versions v ON v.id=j.version_id WHERE j.id=?", (job_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Không tìm thấy tác vụ")
        document_for(db, row["document_id"], user)
        return dict(row)


@app.get("/api/documents")
def list_documents(user=Depends(current_user), limit: int = 100):
    limit = max(1, min(limit, 500))
    acl_sql, acl_params = _acl(user)
    with connect() as db:
        rows = db.execute(
            f"SELECT d.* FROM documents d WHERE {acl_sql} ORDER BY d.created_at DESC,d.rowid DESC LIMIT ?",
            (*acl_params, limit),
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/documents/{document_id}")
def get_document(document_id: str, version_id: Optional[str] = None, user=Depends(current_user)):
    with connect() as db:
        doc = document_for(db, document_id, user)
        selected_version = version_id or doc["current_version_id"]
        if selected_version and not db.execute(
            "SELECT 1 FROM versions WHERE id=? AND document_id=?", (selected_version, document_id)
        ).fetchone():
            raise HTTPException(404, "Không tìm thấy phiên bản")
        versions = [dict(row) for row in db.execute(
            "SELECT id,version_no,filename,mime_type,sha256,status,error,created_at FROM versions "
            "WHERE document_id=? ORDER BY version_no DESC", (document_id,)
        )]
        pages = [dict(row) for row in db.execute(
            "SELECT page_no,text,source FROM pages WHERE version_id=? ORDER BY page_no", (selected_version,)
        )] if selected_version else []
        fields = [dict(row) for row in db.execute(
            "SELECT * FROM fields WHERE version_id=? ORDER BY page_no,field_key", (selected_version,)
        )] if selected_version else []
        relations = [dict(row) for row in db.execute(
            "SELECT r.*,a.title AS source_title,b.title AS target_title FROM relations r "
            "JOIN documents a ON a.id=r.source_id JOIN documents b ON b.id=r.target_id "
            "WHERE r.source_id=? OR r.target_id=?", (document_id, document_id)
        ) if auth.can_read(db, user, db.execute(
            "SELECT * FROM documents WHERE id=?", (row["target_id"] if row["source_id"] == document_id else row["source_id"],)
        ).fetchone())]
        grants = [dict(row) for row in db.execute(
            "SELECT u.id,u.username,u.department FROM grants g JOIN users u ON u.id=g.user_id "
            "WHERE g.document_id=? ORDER BY u.username", (document_id,)
        )] if auth.can_write(user, doc) else []
        return {"document": dict(doc), "selected_version_id": selected_version,
                "versions": versions, "pages": pages,
                "fields": fields, "relations": relations, "grants": grants}


@app.patch("/api/documents/{document_id}")
def update_document(document_id: str, body: DocumentUpdateBody, user=Depends(current_user)):
    if not body.title.strip():
        raise HTTPException(422, "Tiêu đề không hợp lệ")
    with connect() as db:
        document_for(db, document_id, user, write=True)
        db.execute("UPDATE documents SET title=?,visibility=? WHERE id=?",
                   (body.title.strip(), body.visibility, document_id))
        audit(db, user["id"], "document.update", document_id,
              json.dumps({"title": body.title.strip(), "visibility": body.visibility}, ensure_ascii=False))
    return {"ok": True}


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: str, version_id: Optional[str] = None, user=Depends(current_user)):
    with connect() as db:
        doc = document_for(db, document_id, user)
        selected_version = version_id or doc["current_version_id"]
        if not selected_version:
            raise HTTPException(409, "Tài liệu chưa xử lý xong")
        version = db.execute("SELECT * FROM versions WHERE id=? AND document_id=?",
                             (selected_version, document_id)).fetchone()
        if not version:
            raise HTTPException(404, "Không tìm thấy phiên bản")
        audit(db, user["id"], "document.download", document_id)
    return FileResponse(data_dir() / "blobs" / version["blob_name"],
                        media_type=version["mime_type"], filename=version["filename"])


@app.post("/api/documents/{document_id}/versions/{version_id}/retry", status_code=202)
def retry_version(document_id: str, version_id: str, user=Depends(current_user)):
    with connect() as db:
        document_for(db, document_id, user, write=True)
        version = db.execute("SELECT status FROM versions WHERE id=? AND document_id=?",
                             (version_id, document_id)).fetchone()
        if not version:
            raise HTTPException(404, "Không tìm thấy phiên bản")
        if version["status"] != "failed":
            raise HTTPException(409, "Chỉ chạy lại phiên bản xử lý lỗi")
        db.execute("UPDATE versions SET status='queued',error=NULL WHERE id=?", (version_id,))
        db.execute("UPDATE jobs SET status='queued',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE version_id=?",
                   (version_id,))
        job = db.execute("SELECT id FROM jobs WHERE version_id=?", (version_id,)).fetchone()
        audit(db, user["id"], "version.retry", document_id, version_id)
    return {"job_id": job["id"], "version_id": version_id}


@app.patch("/api/fields/{field_id}")
def review_field(field_id: str, body: FieldBody, user=Depends(current_user)):
    if not body.value.strip():
        raise HTTPException(422, "Giá trị không hợp lệ")
    with connect() as db:
        field = db.execute(
            "SELECT f.*,v.document_id FROM fields f JOIN versions v ON v.id=f.version_id WHERE f.id=?", (field_id,)
        ).fetchone()
        if not field:
            raise HTTPException(404, "Không tìm thấy trường dữ liệu")
        document_for(db, field["document_id"], user, write=True)
        db.execute(
            "UPDATE fields SET value=?,status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (body.value.strip(), body.status, user["id"], field_id),
        )
        audit(db, user["id"], "field.review", field["document_id"], field_id)
    return {"ok": True}


@app.post("/api/documents/{document_id}/relations")
def add_relation(document_id: str, body: RelationBody, user=Depends(current_user)):
    with connect() as db:
        document_for(db, document_id, user, write=True)
        document_for(db, body.target_id, user)
        if document_id == body.target_id:
            raise HTTPException(422, "Không thể tự liên kết")
        relation_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO relations(id,source_id,target_id,relation_type,evidence,page_no,status,created_by) "
            "VALUES (?,?,?,?,?,?,'confirmed',?)",
            (relation_id, document_id, body.target_id, body.relation_type, body.evidence, body.page_no, user["id"]),
        )
        audit(db, user["id"], "relation.create", document_id, relation_id)
    return {"id": relation_id}


@app.patch("/api/relations/{relation_id}")
def review_relation(relation_id: str, body: RelationReviewBody, user=Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT * FROM relations WHERE id=?", (relation_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Không tìm thấy quan hệ")
        document_for(db, row["source_id"], user, write=True)
        document_for(db, row["target_id"], user)
        db.execute("UPDATE relations SET status=?,created_by=? WHERE id=?", (body.status, user["id"], relation_id))
        audit(db, user["id"], "relation.review", row["source_id"], relation_id)
    return {"ok": True}


@app.post("/api/documents/{document_id}/grants")
def grant_access(document_id: str, body: GrantBody, user=Depends(current_user)):
    with connect() as db:
        document_for(db, document_id, user, write=True)
        target = db.execute("SELECT id FROM users WHERE username=? AND active=1", (body.username,)).fetchone()
        if not target:
            raise HTTPException(404, "Không tìm thấy người dùng")
        db.execute("INSERT OR IGNORE INTO grants(document_id,user_id) VALUES (?,?)", (document_id, target["id"]))
        audit(db, user["id"], "access.grant", document_id, target["id"])
    return {"ok": True}


@app.delete("/api/documents/{document_id}/grants/{user_id}")
def revoke_access(document_id: str, user_id: str, user=Depends(current_user)):
    with connect() as db:
        document_for(db, document_id, user, write=True)
        db.execute("DELETE FROM grants WHERE document_id=? AND user_id=?", (document_id, user_id))
        audit(db, user["id"], "access.revoke", document_id, user_id)
    return {"ok": True}


@app.get("/api/search")
def search_api(q: str, user=Depends(current_user), limit: int = 10):
    return {"results": search(user, q, limit)}


@app.post("/api/admin/reindex")
def reindex(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Chỉ quản trị viên")
    from .processing import ProcessingUnavailable
    try:
        count = reindex_embeddings()
    except ProcessingUnavailable as exc:
        raise HTTPException(503, str(exc))
    with connect() as db:
        audit(db, user["id"], "embedding.reindex", detail=str(count))
    return {"chunks_reindexed": count}
