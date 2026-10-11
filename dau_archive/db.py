from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def data_dir() -> Path:
    path = Path(os.environ.get("DAU_DATA_DIR", "data")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    (path / "blobs").mkdir(exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "archive.sqlite3"


@contextmanager
def connect():
    db = sqlite3.connect(db_path(), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','staff')),
 department TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('incoming','outgoing','iso','curriculum','lesson','other')),
 title TEXT NOT NULL, department TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('public','department','restricted')),
 owner_id TEXT NOT NULL REFERENCES users(id), current_version_id TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS grants (
 document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 PRIMARY KEY(document_id,user_id)
);
CREATE TABLE IF NOT EXISTS versions (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 version_no INTEGER NOT NULL, filename TEXT NOT NULL, mime_type TEXT NOT NULL,
 sha256 TEXT NOT NULL, blob_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued'
  CHECK(status IN ('queued','processing','ready','failed')),
 error TEXT, created_by TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(document_id,version_no)
);
CREATE TABLE IF NOT EXISTS pages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
 page_no INTEGER NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
 UNIQUE(version_id,page_no)
);
CREATE TABLE IF NOT EXISTS fields (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
 field_key TEXT NOT NULL, value TEXT NOT NULL, page_no INTEGER NOT NULL,
 evidence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed'
  CHECK(status IN ('proposed','confirmed','rejected')),
 updated_by TEXT REFERENCES users(id), updated_at TEXT,
 UNIQUE(version_id,field_key,value,page_no)
);
CREATE TABLE IF NOT EXISTS relations (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 target_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 relation_type TEXT NOT NULL CHECK(relation_type IN ('replaces','cites','in_file','in_course','related')),
 evidence TEXT NOT NULL DEFAULT '', page_no INTEGER,
 status TEXT NOT NULL DEFAULT 'confirmed' CHECK(status IN ('proposed','confirmed','rejected')),
 created_by TEXT REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK(source_id != target_id)
);
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
 page_no INTEGER NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL,
 embedding BLOB, model_id TEXT,
 UNIQUE(version_id,page_no,ordinal)
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
 text, chunk_id UNINDEXED, tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing','ready','failed')),
 error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT REFERENCES users(id),
 action TEXT NOT NULL, document_id TEXT, detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_documents_department ON documents(department,visibility);
CREATE INDEX IF NOT EXISTS idx_versions_document ON versions(document_id,version_no);
CREATE INDEX IF NOT EXISTS idx_pages_version ON pages(version_id,page_no);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(version_id,page_no);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status,created_at);
"""


def init_db() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)


def audit(db: sqlite3.Connection, actor_id: str | None, action: str,
          document_id: str | None = None, detail: str = "") -> None:
    db.execute(
        "INSERT INTO audit(actor_id,action,document_id,detail) VALUES (?,?,?,?)",
        (actor_id, action, document_id, detail),
    )
