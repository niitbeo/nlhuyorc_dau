from __future__ import annotations

import logging
import threading
import time

from .db import connect, init_db
from .processing import process_version

log = logging.getLogger(__name__)
_lock = threading.Lock()


def run_once() -> bool:
    with _lock:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT id,version_id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
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
    while not stop.is_set():
        if not run_once():
            stop.wait(1.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        serve(threading.Event())
    except KeyboardInterrupt:
        pass
