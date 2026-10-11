from __future__ import annotations

import logging
import threading
import time

from .db import connect, init_db
from .processing import process_version

log = logging.getLogger(__name__)
_lock = threading.Lock()


FAST_SUFFIXES = (".txt", ".md", ".docx", ".doc")
FAST_FILTER = " OR ".join("lower(v.filename) LIKE ?" for _ in FAST_SUFFIXES)


def run_once(fast_only: bool = False) -> bool:
    with _lock:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            where = f"AND ({FAST_FILTER})" if fast_only else ""
            job = db.execute(
                "SELECT j.id,j.version_id FROM jobs j JOIN versions v ON v.id=j.version_id "
                f"WHERE j.status='queued' {where} ORDER BY j.created_at,j.rowid LIMIT 1",
                tuple("%" + suffix for suffix in FAST_SUFFIXES) if fast_only else (),
            ).fetchone()
            if not job:
                return False
            db.execute("UPDATE jobs SET status='processing',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job["id"],))
    try:
        process_version(job["version_id"])
    except Exception:
        log.exception("Failed to process OCR/document version %s", job["version_id"])
    return True


def serve(stop: threading.Event) -> None:
    init_db()
    with connect() as db:
        db.execute("UPDATE jobs SET status='queued' WHERE status='processing'")
    fast_lane = threading.Thread(target=_serve_fast, args=(stop,), daemon=True)
    fast_lane.start()
    while not stop.is_set():
        if not run_once():
            stop.wait(1.0)
    fast_lane.join(timeout=3)


def _serve_fast(stop: threading.Event) -> None:
    while not stop.is_set():
        if not run_once(fast_only=True):
            stop.wait(1.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        serve(threading.Event())
    except KeyboardInterrupt:
        pass
