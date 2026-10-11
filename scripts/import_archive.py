"""Register a local archive for the reusable background document importer.

Example:
  python3 scripts/import_archive.py data/iso_source/example.zip --owner admin \
    --department 'Văn thư' --kind-hint iso --derive-department
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dau_archive.batch_import import create_batch
from dau_archive.db import connect, data_dir, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Đưa ZIP/RAR hoặc nhiều tài liệu vào hàng đợi nhập")
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--owner", required=True, help="Tài khoản đang có trong hệ thống")
    parser.add_argument("--department", required=True)
    parser.add_argument("--visibility", default="department", choices=["public", "department", "restricted"])
    parser.add_argument("--kind-hint", default="", choices=["", "iso"])
    parser.add_argument("--derive-department", action="store_true")
    parser.add_argument("--sha256", help="Checksum dự kiến, chỉ dùng khi nhập một tệp")
    args = parser.parse_args()
    init_db()
    with connect() as db:
        owner = db.execute("SELECT id,role,department FROM users WHERE username=? AND active=1",
                           (args.owner,)).fetchone()
    if not owner:
        parser.error("Không tìm thấy tài khoản đang hoạt động")
    if owner["role"] != "admin" and (args.department != owner["department"] or args.derive_department):
        parser.error("Tài khoản này không được chọn đơn vị khác")
    sources = [item.expanduser().resolve() for item in args.sources]
    if any(not item.is_file() for item in sources):
        parser.error("Có nguồn nhập không phải tệp")
    if args.sha256:
        if len(sources) != 1:
            parser.error("--sha256 chỉ dùng với một tệp")
        digest = hashlib.sha256()
        with sources[0].open("rb") as source:
            for piece in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(piece)
        if digest.hexdigest().lower() != args.sha256.lower():
            parser.error("Checksum SHA256 không khớp")
    expected = [str(item) for item in sources]
    with connect() as db:
        previous = db.execute("SELECT id,source_path,status FROM import_batches WHERE owner_id=? "
                              "ORDER BY created_at DESC LIMIT 100", (owner["id"],)).fetchall()
    for row in previous:
        try:
            manifest = json.loads(Path(row["source_path"]).read_text(encoding="utf-8"))
            if [item["path"] for item in manifest["sources"]] == expected:
                print(json.dumps({"id": row["id"], "status": row["status"], "existing": True}))
                return 0
        except (OSError, ValueError, KeyError):
            continue
    batch_id = str(uuid.uuid4())
    directory = data_dir() / "batch_sources" / batch_id
    directory.mkdir(parents=True, exist_ok=True)
    staged = []
    for index, source in enumerate(sources):
        if source.is_relative_to(data_dir()):
            staged.append((source.name, source))
        else:
            destination = directory / f"{index:04d}-{source.name}"
            shutil.copyfile(source, destination)
            staged.append((source.name, destination))
    created = create_batch(owner["id"], ", ".join(item.name for item in sources), staged,
                           args.department, args.visibility, args.kind_hint,
                           args.derive_department, batch_id=batch_id)
    print(json.dumps({"id": created, "status": "queued", "existing": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
