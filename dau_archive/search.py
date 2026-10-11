from __future__ import annotations

import heapq
import re

from .db import connect
from .embeddings import available, cosine, embed_query, model_id


def _acl(user) -> tuple[str, tuple]:
    if user["role"] == "admin":
        return "1=1", ()
    return (
        "(d.visibility='public' OR d.owner_id=? OR "
        "(d.visibility='department' AND d.department=?) OR "
        "EXISTS(SELECT 1 FROM grants g WHERE g.document_id=d.id AND g.user_id=?))",
        (user["id"], user["department"], user["id"]),
    )


def _filters(kind: str, department: str, collection: str) -> tuple[str, tuple]:
    clauses = []
    params = []
    if kind:
        clauses.append("d.kind=?")
        params.append(kind)
    if department:
        clauses.append("d.department=?")
        params.append(department)
    if collection:
        clauses.append("EXISTS (SELECT 1 FROM import_batch_entries e "
                       "WHERE e.document_id=d.id AND e.collection_key=?)")
        params.append(collection)
    return (" AND " + " AND ".join(clauses) if clauses else ""), tuple(params)


def search(user, query: str, limit: int = 10, mode: str = "hybrid",
           kind: str = "", department: str = "", collection: str = "") -> dict:
    tokens = re.findall(r"\w+", query.lower(), re.UNICODE)[:16]
    if not tokens:
        return {"results": [], "effective_mode": "keyword", "semantic_ready": False}
    match = " OR ".join('"' + token.replace('"', '') + '"' for token in tokens)
    acl_sql, acl_params = _acl(user)
    filter_sql, filter_params = _filters(kind, department, collection)
    current_model = model_id()
    with connect() as db:
        total_chunks = db.execute(
            "SELECT COUNT(*) FROM chunks c JOIN documents d ON d.current_version_id=c.version_id"
        ).fetchone()[0]
        indexed_chunks = db.execute(
            "SELECT COUNT(*) FROM chunk_embeddings e JOIN chunks c ON c.id=e.chunk_id "
            "JOIN documents d ON d.current_version_id=c.version_id WHERE e.model_id=?",
            (current_model,),
        ).fetchone()[0]
    has_index = indexed_chunks > 0
    semantic_ready = bool(has_index and available())
    effective_mode = mode if mode == "keyword" or semantic_ready else (
        "keyword" if mode == "hybrid" else "unavailable")
    lexical = []
    if effective_mode in {"keyword", "hybrid"}:
        with connect() as db:
            lexical = db.execute(
                "SELECT c.id FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.chunk_id "
                "JOIN versions v ON v.id=c.version_id JOIN documents d ON d.current_version_id=v.id "
                f"WHERE chunks_fts MATCH ? AND {acl_sql}{filter_sql} "
                "ORDER BY bm25(chunks_fts) LIMIT 150",
                (match, *acl_params, *filter_params),
            ).fetchall()
    scores = {row["id"]: 1.0 / (60 + index) for index, row in enumerate(lexical, 1)}
    lexical_ids = set(scores)
    if effective_mode in {"semantic", "hybrid"}:
        query_vector = embed_query(query)
        if query_vector is None:
            return {"results": [], "effective_mode": "unavailable", "semantic_ready": False,
                    "indexed_chunks": indexed_chunks, "total_chunks": total_chunks}
        with connect() as db:
            cursor = db.execute(
                "SELECT c.id,e.embedding FROM chunk_embeddings e JOIN chunks c ON c.id=e.chunk_id "
                "JOIN versions v ON v.id=c.version_id "
                "JOIN documents d ON d.current_version_id=v.id "
                f"WHERE e.model_id=? AND {acl_sql}{filter_sql}",
                (current_model, *acl_params, *filter_params),
            )
            top = []
            for row in cursor:
                value = cosine(query_vector, row["embedding"])
                if len(top) < 150:
                    heapq.heappush(top, (value, row["id"]))
                elif value > top[0][0]:
                    heapq.heapreplace(top, (value, row["id"]))
        semantic_ids = set()
        for index, (similarity, chunk_id) in enumerate(sorted(top, reverse=True), 1):
            if similarity <= 0:
                continue
            semantic_ids.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (60 + index)
    else:
        semantic_ids = set()
    if not scores:
        return {"results": [], "effective_mode": effective_mode,
                "semantic_ready": semantic_ready, "indexed_chunks": indexed_chunks,
                "total_chunks": total_chunks}
    winners = sorted(scores, key=scores.get, reverse=True)
    output = []
    seen_documents = set()
    with connect() as db:
        for chunk_id in winners:
            row = db.execute(
                "SELECT c.id,c.page_no,c.text,d.id AS document_id,d.title,d.kind,d.visibility,"
                "v.id AS version_id FROM chunks c JOIN versions v ON v.id=c.version_id "
                "JOIN documents d ON d.current_version_id=v.id WHERE c.id=?",
                (chunk_id,),
            ).fetchone()
            if row and row["document_id"] not in seen_documents:
                seen_documents.add(row["document_id"])
                output.append({**dict(row), "score": round(scores[chunk_id], 6),
                               "match_type": "hybrid" if chunk_id in lexical_ids and
                               chunk_id in semantic_ids else (
                                   "semantic" if chunk_id in semantic_ids else "keyword")})
            if len(output) >= max(1, min(limit, 50)):
                break
    return {"results": output, "effective_mode": effective_mode,
            "semantic_ready": semantic_ready, "indexed_chunks": indexed_chunks,
            "total_chunks": total_chunks}
