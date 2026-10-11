"""Restartable bulk import of document files and ZIP archives into the OCR queue."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
import os
import stat
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

from .classify import classify, plain
from .db import audit, connect, data_dir, init_db
from .processing import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES


log = logging.getLogger(__name__)
_lock = threading.Lock()
MAX_BATCH_BYTES = 1536 * 1024 * 1024
MAX_BATCH_FILES = 200
MAX_ARCHIVE_ENTRIES = 5000
MAX_EXTRACTED_BYTES = 3 * 1024 * 1024 * 1024


def _safe_name(name: str) -> str:
    value = name.replace("\\", "/")
    if value.startswith("/"):
        raise ValueError("Đường dẫn không hợp lệ trong archive")
    while value.startswith("./"):
        value = value[2:]
    parts = value.split("/")
    if not value or len(value) > 1200 or value.startswith("/") or any(
        part in {"", ".", ".."} or "\x00" in part for part in parts
    ):
        raise ValueError("Đường dẫn không hợp lệ trong archive")
    return "/".join(parts)


def _rar_members(content: bytes):
    with tempfile.TemporaryDirectory(dir=data_dir()) as directory:
        source = Path(directory) / "nested.rar"
        source.write_bytes(content)
        listing = subprocess.run(["bsdtar", "-tf", str(source)], capture_output=True,
                                 text=True, timeout=60, check=True)
        details = subprocess.run(["bsdtar", "-tvf", str(source)], capture_output=True,
                                 text=True, timeout=60, check=True)
        names = listing.stdout.splitlines()
        verbose = details.stdout.splitlines()
        if len(names) != len(verbose):
            raise ValueError("Không đọc được danh sách tệp trong RAR")
        for name, detail in zip(names, verbose):
            if name.endswith("/") or detail.startswith("d"):
                continue
            result = subprocess.run(["bsdtar", "-xOf", str(source), name],
                                    capture_output=True, timeout=90, check=True)
            yield name, result.stdout


def _zip_members(archive: zipfile.ZipFile, prefix: str = "", depth: int = 0,
                 budget: list[int] | None = None):
    budget = budget if budget is not None else [0]
    entries = [item for item in archive.infolist() if not item.is_dir()
               and not item.filename.startswith("__MACOSX/")]
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("Archive có quá 5.000 tệp")
    for item in entries:
        path = prefix + item.filename
        mode = item.external_attr >> 16
        if stat.S_ISLNK(mode):
            yield path, None, "Liên kết mềm trong ZIP không được nhập"
            continue
        if item.file_size > MAX_UPLOAD_BYTES:
            yield path, None, "Tệp vượt quá 50 MiB"
            continue
        budget[0] += item.file_size
        if budget[0] > MAX_EXTRACTED_BYTES:
            yield path, None, "Archive vượt quá 3 GiB dữ liệu giải nén"
            continue
        try:
            content = archive.read(item)
            extension = Path(item.filename).suffix.lower()
            if extension == ".zip" and depth < 2:
                with zipfile.ZipFile(io.BytesIO(content)) as nested:
                    yield from _zip_members(nested, path + "!/", depth + 1, budget)
            elif extension == ".rar" and depth < 2:
                for name, raw in _rar_members(content):
                    yield path + "!/" + name, raw, None
            else:
                yield path, content, None
        except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
            yield path, None, f"Không đọc được archive: {str(error)[:120]}"


def _entries(manifest: dict):
    many = len(manifest["sources"]) > 1
    for index, source in enumerate(manifest["sources"]):
        path = Path(source["path"])
        if not path.resolve().is_relative_to(data_dir()):
            raise ValueError("Nguồn nhập phải nằm trong thư mục dữ liệu")
        prefix = f"{index + 1}-{source['name']}!/" if many and path.suffix.lower() in {".zip", ".rar"} else ""
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                yield from _zip_members(archive, prefix)
        elif path.suffix.lower() == ".rar":
            for name, raw in _rar_members(path.read_bytes()):
                yield prefix + name, raw, None
        else:
            name = f"{index + 1}-{source['name']}" if many else source["name"]
            yield name, path.read_bytes() if path.stat().st_size <= MAX_UPLOAD_BYTES else None, (
                None if path.stat().st_size <= MAX_UPLOAD_BYTES else "Tệp vượt quá 50 MiB")


def create_batch(owner_id: str, source_name: str, sources: list[tuple[str, Path]],
                 department: str, visibility: str = "department", kind_hint: str = "",
                 derive_department: bool = False, batch_id: str | None = None) -> str:
    if not sources or len(sources) > MAX_BATCH_FILES:
        raise ValueError("Chọn từ 1 đến 200 tệp hoặc ZIP")
    if visibility not in {"public", "department", "restricted"}:
        raise ValueError("Quyền truy cập không hợp lệ")
    if kind_hint not in {"", "iso"}:
        raise ValueError("Gợi ý loại tài liệu không hợp lệ")
    batch_id = batch_id or str(uuid.uuid4())
    directory = data_dir() / "batch_sources" / batch_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"sources": [{"name": name, "path": str(path.resolve())} for name, path in sources],
                "derive_department": bool(derive_department)}
    for source in manifest["sources"]:
        if not Path(source["path"]).is_file() or not Path(source["path"]).is_relative_to(data_dir()):
            raise ValueError("Nguồn nhập không hợp lệ")
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with connect() as db:
        db.execute("INSERT INTO import_batches(id,source_name,source_path,owner_id,department,"
                   "visibility,kind_hint) VALUES (?,?,?,?,?,?,?)",
                   (batch_id, source_name[:300], str(manifest_path), owner_id,
                    department.strip(), visibility, kind_hint))
        audit(db, owner_id, "batch.create", detail=batch_id)
    return batch_id


def _logical_parts(path: str) -> list[str]:
    parts = path.replace("!/", "/").split("/")
    if parts[0].endswith((".zip", ".rar", ".zip!", ".rar!")):
        parts = parts[1:]
    return parts


def _collection(path: str) -> str:
    parts = _logical_parts(path)
    if len(parts) >= 4 and plain(parts[0]) == "dau iso":
        return "/".join(parts[:3])
    return "/".join(parts[:-1])


def _department(batch, path: str, derive: bool) -> str:
    parts = _logical_parts(path)
    if derive and len(parts) > 2 and plain(parts[0]) == "dau iso":
        return parts[1][:120]
    return batch["department"]


def _record(batch, path: str, content: bytes | None, error: str | None, derive: bool) -> None:
    try:
        path = _safe_name(path)
    except ValueError as exc:
        # Bad paths are recorded without writing them to the filesystem.
        error = str(exc)
        path = path[:1200]
    with connect() as db:
        if db.execute("SELECT 1 FROM import_batch_entries WHERE batch_id=? AND archive_path=?",
                      (batch["id"], path)).fetchone():
            return
    filename = Path(path).name[:300]
    extension = Path(filename).suffix.lower()
    if filename.startswith("~$") or filename in {".DS_Store", "Thumbs.db"}:
        error = error or "Tệp tạm của hệ điều hành/Office"
    if extension not in ALLOWED_EXTENSIONS:
        error = error or f"Chưa hỗ trợ định dạng {extension or '(không có đuôi)'}"
    if not content:
        error = error or "Tệp trống"
    if content and len(content) > MAX_UPLOAD_BYTES:
        error = "Tệp vượt quá 50 MiB"
    suggestion = classify(filename, path, kind_hint=batch["kind_hint"])
    collection = _collection(path)
    if error:
        with connect() as db:
            db.execute("INSERT INTO import_batch_entries(id,batch_id,archive_path,collection_key,"
                       "source_role,status,error) VALUES (?,?,?,?,?,'skipped',?)",
                       (str(uuid.uuid4()), batch["id"], path, collection,
                        suggestion["subtype"], error[:240]))
            db.execute("UPDATE import_batches SET skipped_entries=skipped_entries+1,"
                       "updated_at=CURRENT_TIMESTAMP WHERE id=?", (batch["id"],))
        return

    digest = hashlib.sha256(content).hexdigest()
    blob = data_dir() / "blobs" / digest
    temporary_blob = blob.with_name(f".{digest}.{uuid.uuid4().hex}.part")
    try:
        temporary_blob.write_bytes(content)
        try:
            os.link(temporary_blob, blob)
        except FileExistsError:
            pass  # Same bytes are already stored, possibly under another archive path.
    finally:
        temporary_blob.unlink(missing_ok=True)
    document_id, version_id, job_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with connect() as db:
        db.execute("INSERT INTO documents(id,kind,title,department,visibility,owner_id,subtype,"
                   "classification_status,classification_confidence,classification_evidence) "
                   "VALUES (?,?,?,?,?,?,?,'proposed',?,?)",
                   (document_id, suggestion["kind"], Path(filename).stem[:300],
                    _department(batch, path, derive), batch["visibility"], batch["owner_id"],
                    suggestion["subtype"], suggestion["confidence"], suggestion["evidence"]))
        db.execute("INSERT INTO versions(id,document_id,version_no,filename,mime_type,sha256,blob_name,"
                   "created_by) VALUES (?,?,1,?,?,?,?,?)",
                   (version_id, document_id, filename,
                    mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    digest, digest, batch["owner_id"]))
        db.execute("INSERT INTO jobs(id,version_id) VALUES (?,?)", (job_id, version_id))
        db.execute("INSERT INTO import_batch_entries(id,document_id,batch_id,archive_path,"
                   "collection_key,source_role,status) VALUES (?,?,?,?,?,?,'imported')",
                   (str(uuid.uuid4()), document_id, batch["id"], path, collection,
                    suggestion["subtype"]))
        db.execute("UPDATE import_batches SET imported_entries=imported_entries+1,"
                   "updated_at=CURRENT_TIMESTAMP WHERE id=?", (batch["id"],))
        audit(db, batch["owner_id"], "document.import", document_id, path[:500])


def _propose_folder_relations(batch_id: str, owner_id: str) -> None:
    with connect() as db:
        rows = db.execute("SELECT document_id,collection_key,source_role,archive_path "
                          "FROM import_batch_entries WHERE batch_id=? AND status='imported'",
                          (batch_id,)).fetchall()
        parents = {}
        for row in rows:
            if row["source_role"] == "procedure" and row["collection_key"] not in parents:
                parents[row["collection_key"]] = row["document_id"]
        for row in rows:
            parent = parents.get(row["collection_key"])
            if parent and parent != row["document_id"] and row["source_role"] != "procedure" and not db.execute(
                "SELECT 1 FROM relations WHERE source_id=? AND target_id=? AND relation_type='in_file'",
                (row["document_id"], parent),
            ).fetchone():
                db.execute("INSERT INTO relations(id,source_id,target_id,relation_type,evidence,"
                           "status,created_by) VALUES (?,?,?,'in_file',?,'proposed',?)",
                           (str(uuid.uuid4()), row["document_id"], parent,
                            ("Cùng thư mục: " + row["collection_key"])[:500], owner_id))


def _run_batch(batch) -> None:
    manifest = json.loads(Path(batch["source_path"]).read_text(encoding="utf-8"))
    total = sum(1 for _ in _entries(manifest))
    with connect() as db:
        db.execute("UPDATE import_batches SET total_entries=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (total, batch["id"]))
    for path, content, error in _entries(manifest):
        _record(batch, path, content, error, manifest["derive_department"])
    _propose_folder_relations(batch["id"], batch["owner_id"])
    with connect() as db:
        db.execute("UPDATE import_batches SET status='ready',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (batch["id"],))
        audit(db, batch["owner_id"], "batch.ready", detail=batch["id"])
    # Browser uploads are staging data. Each imported leaf is already stored in
    # a content-addressed blob, so retaining the transport ZIP duplicates space.
    stage = (data_dir() / "batch_sources" / batch["id"]).resolve()
    for source in manifest["sources"]:
        path = Path(source["path"]).resolve()
        if path.is_relative_to(stage):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove staged archive %s", path)


def run_once() -> bool:
    with _lock:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            batch = db.execute("SELECT * FROM import_batches WHERE status='queued' "
                               "ORDER BY created_at LIMIT 1").fetchone()
            if not batch:
                return False
            db.execute("UPDATE import_batches SET status='importing',updated_at=CURRENT_TIMESTAMP "
                       "WHERE id=?", (batch["id"],))
        try:
            _run_batch(batch)
        except Exception as error:
            log.exception("Failed bulk import %s", batch["id"])
            with connect() as db:
                db.execute("UPDATE import_batches SET status='failed',error=?,"
                           "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (str(error)[:500], batch["id"]))
        return True


def serve(stop: threading.Event) -> None:
    init_db()
    with connect() as db:
        db.execute("UPDATE import_batches SET status='queued' WHERE status='importing'")
    while not stop.is_set():
        if not run_once():
            stop.wait(1.0)


def batch_status(batch_id: str, user) -> dict | None:
    with connect() as db:
        batch = db.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch or (user["role"] != "admin" and batch["owner_id"] != user["id"]):
            return None
        result = dict(batch)
        result.pop("source_path", None)
        result["ocr"] = {row["status"]: row["n"] for row in db.execute(
            "SELECT j.status,COUNT(*) AS n FROM import_batch_entries e "
            "JOIN versions v ON v.document_id=e.document_id "
            "JOIN jobs j ON j.version_id=v.id WHERE e.batch_id=? GROUP BY j.status",
            (batch_id,))}
        result["recent_errors"] = [dict(row) for row in db.execute(
            "SELECT archive_path,error FROM import_batch_entries WHERE batch_id=? "
            "AND status='skipped' ORDER BY rowid DESC LIMIT 10", (batch_id,))]
        return result
