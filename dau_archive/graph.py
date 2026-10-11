"""Bounded document relationship graph with per-node access checks."""
from __future__ import annotations

from . import auth
from .db import connect


def neighborhood(user, document_id: str, depth: int = 2, limit: int = 80,
                 include_proposed: bool = True) -> dict | None:
    depth = max(1, min(depth, 3))
    limit = max(2, min(limit, 120))
    with connect() as db:
        root = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not root or not auth.can_read(db, user, root):
            return None
        nodes = {document_id: _node(root, 0, auth.can_write(user, root))}
        edges = {}
        frontier = {document_id}
        for level in range(1, depth + 1):
            if not frontier or len(nodes) >= limit:
                break
            placeholders = ",".join("?" for _ in frontier)
            condition = "" if include_proposed else " AND r.status='confirmed'"
            rows = db.execute(
                f"SELECT r.* FROM relations r WHERE (r.source_id IN ({placeholders}) "
                f"OR r.target_id IN ({placeholders})){condition} "
                "AND r.status!='rejected' ORDER BY r.created_at DESC,r.id",
                (*frontier, *frontier),
            ).fetchall()
            next_frontier = set()
            for row in rows:
                source_id, target_id = row["source_id"], row["target_id"]
                candidate_id = target_id if source_id in frontier else source_id
                if candidate_id not in nodes:
                    if len(nodes) >= limit:
                        continue
                    candidate = db.execute("SELECT * FROM documents WHERE id=?",
                                           (candidate_id,)).fetchone()
                    if not candidate or not auth.can_read(db, user, candidate):
                        continue
                    nodes[candidate_id] = _node(candidate, level,
                                                auth.can_write(user, candidate))
                    next_frontier.add(candidate_id)
                if source_id in nodes and target_id in nodes:
                    edges[row["id"]] = {
                        "id": row["id"], "source_id": source_id,
                        "target_id": target_id, "relation_type": row["relation_type"],
                        "status": row["status"], "evidence": row["evidence"],
                        "page_no": row["page_no"],
                    }
            frontier = next_frontier
        return {"root_id": document_id, "nodes": list(nodes.values()),
                "edges": list(edges.values()), "depth": depth, "limit": limit}


def _node(doc, level: int, can_write: bool) -> dict:
    return {"id": doc["id"], "title": doc["title"], "kind": doc["kind"],
            "subtype": doc["subtype"], "department": doc["department"],
            "classification_status": doc["classification_status"],
            "level": level, "can_write": can_write}
