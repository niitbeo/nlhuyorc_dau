from __future__ import annotations

import heapq
import os
import re

from .db import connect
from .embeddings import cosine, embed_query, model_id


def _acl(user) -> tuple[str, tuple]:
    if user["role"] == "admin":
        return "1=1", ()
    return (
        "(d.visibility='public' OR d.owner_id=? OR "
        "(d.visibility='department' AND d.department=?) OR "
        "EXISTS(SELECT 1 FROM grants g WHERE g.document_id=d.id AND g.user_id=?))",
        (user["id"], user["department"], user["id"]),
    )


def search(user, query: str, limit: int = 10) -> list[dict]:
    tokens = re.findall(r"\w+", query.lower(), re.UNICODE)[:16]
    if not tokens:
        return []
    match = " OR ".join('"' + token.replace('"', '') + '"' for token in tokens)
    acl_sql, acl_params = _acl(user)
    with connect() as db:
        lexical = db.execute(
            "SELECT c.id FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.chunk_id "
            "JOIN versions v ON v.id=c.version_id JOIN documents d ON d.current_version_id=v.id "
            f"WHERE chunks_fts MATCH ? AND {acl_sql} ORDER BY bm25(chunks_fts) LIMIT 100",
            (match, *acl_params),
        ).fetchall()
    scores = {row["id"]: 1.0 / (60 + index) for index, row in enumerate(lexical, 1)}
    query_vector = embed_query(query) if os.getenv("DAU_ENABLE_SEMANTIC", "0") == "1" else None
    if query_vector is not None:
        with connect() as db:
            cursor = db.execute(
                "SELECT c.id,c.embedding FROM chunks c JOIN versions v ON v.id=c.version_id "
                "JOIN documents d ON d.current_version_id=v.id "
                f"WHERE c.embedding IS NOT NULL AND c.model_id=? AND {acl_sql}",
                (model_id(), *acl_params),
            )
            top = []
            for row in cursor:
                value = cosine(query_vector, row["embedding"])
                if len(top) < 100:
                    heapq.heappush(top, (value, row["id"]))
                elif value > top[0][0]:
                    heapq.heapreplace(top, (value, row["id"]))
        for index, (_, chunk_id) in enumerate(sorted(top, reverse=True), 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (60 + index)
    if not scores:
        return []
    winners = sorted(scores, key=scores.get, reverse=True)[:max(1, min(limit, 50))]
    output = []
    with connect() as db:
        for chunk_id in winners:
            row = db.execute(
                "SELECT c.id,c.page_no,c.text,d.id AS document_id,d.title,d.kind,d.visibility,"
                "v.id AS version_id FROM chunks c JOIN versions v ON v.id=c.version_id "
                "JOIN documents d ON d.current_version_id=v.id WHERE c.id=?",
                (chunk_id,),
            ).fetchone()
            if row:
                output.append({**dict(row), "score": round(scores[chunk_id], 6)})
    return output
