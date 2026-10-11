"""Manual, incremental embedding jobs and document-level similarity."""
from __future__ import annotations

import threading
import uuid

import numpy as np

from . import auth
from .db import audit, connect
from .embeddings import (available, cosine, embed_texts, model_catalog,
                         model_id, selected_model_key)
from .search import _acl


_job_lock = threading.Lock()


def recover_interrupted_jobs() -> None:
    with connect() as db:
        db.execute("UPDATE embedding_jobs SET status='failed',error='Máy chủ khởi động lại; "
                   "chạy lượt tiếp theo để tiếp tục',updated_at=CURRENT_TIMESTAMP "
                   "WHERE status IN ('queued','running')")


def status() -> dict:
    current_model = model_id()
    with connect() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM chunks c JOIN documents d ON d.current_version_id=c.version_id"
        ).fetchone()[0]
        indexed = db.execute(
            "SELECT COUNT(*) FROM chunk_embeddings e JOIN chunks c ON c.id=e.chunk_id "
            "JOIN documents d ON d.current_version_id=c.version_id "
            "WHERE e.model_id=?", (current_model,)
        ).fetchone()[0]
        documents = db.execute(
            "SELECT COUNT(*) FROM document_embeddings e JOIN documents d ON d.id=e.document_id "
            "WHERE e.model_id=? AND e.version_id=d.current_version_id", (current_model,)
        ).fetchone()[0]
        latest = db.execute("SELECT * FROM embedding_jobs ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
    return {"model_id": current_model, "selected_model": selected_model_key(),
            "model_ready": available(), "models": model_catalog(),
            "total_chunks": total, "indexed_chunks": indexed,
            "indexed_documents": documents, "latest_job": dict(latest) if latest else None}


def start_job(actor_id: str, limit: int = 100) -> dict:
    if not available():
        raise ValueError("Chưa có trọng số model embedding tại máy")
    limit = max(1, min(limit, 5000))
    with _job_lock:
        current_model = model_id()
        with connect() as db:
            running = db.execute("SELECT 1 FROM embedding_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone()
            if running:
                raise RuntimeError("Đã có lượt lập chỉ mục đang chạy")
            rows = db.execute(
                "SELECT c.id FROM chunks c JOIN documents d ON d.current_version_id=c.version_id "
                "JOIN (SELECT version_id,COUNT(*) AS count FROM chunks GROUP BY version_id) size "
                "ON size.version_id=c.version_id "
                "WHERE NOT EXISTS(SELECT 1 FROM chunk_embeddings e "
                "WHERE e.chunk_id=c.id AND e.model_id=?) "
                "ORDER BY size.count,c.version_id,c.page_no,c.ordinal LIMIT ?",
                (current_model, limit),
            ).fetchall()
            ids = [row["id"] for row in rows]
            job_id = str(uuid.uuid4())
            db.execute("INSERT INTO embedding_jobs(id,model_id,status,total,created_by) "
                       "VALUES (?,?,'queued',?,?)", (job_id, current_model, len(ids), actor_id))
            audit(db, actor_id, "embedding.start", detail=job_id)
        thread = threading.Thread(target=_run_job, args=(job_id, current_model, ids), daemon=True)
        thread.start()
    return {"id": job_id, "total": len(ids), "status": "queued"}


def _run_job(job_id: str, current_model: str, ids: list[str]) -> None:
    try:
        with connect() as db:
            db.execute("UPDATE embedding_jobs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        affected = set()
        for start in range(0, len(ids), 4):
            if model_id() != current_model:
                raise RuntimeError("Model đã thay đổi trong lúc lập chỉ mục")
            batch_ids = ids[start:start + 4]
            with connect() as db:
                rows = [db.execute(
                    "SELECT c.id,c.text,v.document_id FROM chunks c "
                    "JOIN versions v ON v.id=c.version_id WHERE c.id=?", (chunk_id,)
                ).fetchone() for chunk_id in batch_ids]
            rows = [row for row in rows if row]
            vectors = embed_texts([row["text"] for row in rows])
            if vectors is None:
                raise RuntimeError("Model embedding chưa sẵn sàng")
            with connect() as db:
                db.executemany("INSERT INTO chunk_embeddings(chunk_id,model_id,embedding) VALUES (?,?,?) "
                               "ON CONFLICT(chunk_id,model_id) DO UPDATE SET embedding=excluded.embedding",
                               [(row["id"], current_model, vector)
                                for row, vector in zip(rows, vectors)])
                db.execute("UPDATE embedding_jobs SET completed=completed+?,"
                           "updated_at=CURRENT_TIMESTAMP WHERE id=?", (len(rows), job_id))
            affected.update(row["document_id"] for row in rows)
        for document_id in affected:
            _refresh_document_embedding(document_id, current_model)
        with connect() as db:
            db.execute("UPDATE embedding_jobs SET status='ready',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE embedding_jobs SET status='failed',error=?,"
                       "updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(exc)[:500], job_id))


def _refresh_document_embedding(document_id: str, current_model: str) -> None:
    with connect() as db:
        doc = db.execute("SELECT current_version_id FROM documents WHERE id=?", (document_id,)).fetchone()
        version_id = doc["current_version_id"] if doc else None
        if not version_id:
            return
        rows = db.execute("SELECT e.embedding FROM chunks c LEFT JOIN chunk_embeddings e "
                          "ON e.chunk_id=c.id AND e.model_id=? WHERE c.version_id=?",
                          (current_model, version_id)).fetchall()
        if not rows or any(row["embedding"] is None for row in rows):
            db.execute("DELETE FROM document_embeddings WHERE document_id=? AND model_id=?",
                       (document_id, current_model))
            return
        vectors = [np.frombuffer(row["embedding"], dtype="<f4") for row in rows]
        if len({vector.shape for vector in vectors}) != 1:
            raise ValueError("Kích thước vector không nhất quán")
        mean = np.mean(vectors, axis=0)
        norm = np.linalg.norm(mean)
        if norm == 0:
            return
        vector = np.asarray(mean / norm, dtype="<f4").tobytes()
        db.execute("INSERT INTO document_embeddings(document_id,version_id,model_id,embedding) "
                   "VALUES (?,?,?,?) ON CONFLICT(document_id,model_id) DO UPDATE SET "
                   "version_id=excluded.version_id,model_id=excluded.model_id,"
                   "embedding=excluded.embedding,updated_at=CURRENT_TIMESTAMP",
                   (document_id, version_id, current_model, vector))


def similar_documents(user, document_id: str, limit: int = 10) -> dict | None:
    limit = max(1, min(limit, 30))
    current_model = model_id()
    acl_sql, acl_params = _acl(user)
    with connect() as db:
        doc = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not doc or not auth.can_read(db, user, doc):
            return None
        root = db.execute("SELECT embedding FROM document_embeddings WHERE document_id=? "
                          "AND version_id=? AND model_id=?",
                          (document_id, doc["current_version_id"], current_model)).fetchone()
        if not root:
            return {"indexed": False, "model_id": current_model, "results": []}
        query = np.frombuffer(root["embedding"], dtype="<f4")
        rows = db.execute(
            "SELECT d.id,d.title,d.kind,d.department,e.embedding FROM document_embeddings e "
            "JOIN documents d ON d.id=e.document_id "
            f"WHERE e.model_id=? AND e.version_id=d.current_version_id AND d.id!=? AND {acl_sql}",
            (current_model, document_id, *acl_params),
        ).fetchall()
    ranked = sorted((({"id": row["id"], "title": row["title"],
                      "kind": row["kind"], "department": row["department"],
                      "score": round(cosine(query, row["embedding"]), 4)}) for row in rows),
                    key=lambda item: item["score"], reverse=True)
    return {"indexed": True, "model_id": current_model, "results": ranked[:limit]}
