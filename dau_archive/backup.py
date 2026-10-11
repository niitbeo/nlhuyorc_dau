"""Consistent, checksum-verified backups of the archive database and blobs."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from .db import data_dir, db_path


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def create_backup(target: Path) -> dict:
    target = target.expanduser().resolve()
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "archive.sqlite3"
        with sqlite3.connect(db_path()) as live, sqlite3.connect(snapshot) as copy:
            live.backup(copy)
        files = [(snapshot, "archive.sqlite3")]
        files.extend((path, f"blobs/{path.name}") for path in sorted((data_dir() / "blobs").iterdir()) if path.is_file())
        manifest = {name: {"sha256": _digest(path), "size": path.stat().st_size} for path, name in files}
        with tarfile.open(target, "w:gz") as archive:
            for path, name in files:
                archive.add(path, arcname=name, recursive=False)
            content = json.dumps({"format": 1, "files": manifest}, sort_keys=True).encode()
            entry = tarfile.TarInfo("manifest.json")
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    return {"archive": str(target), "files": len(files)}


def verify_backup(path: Path) -> dict:
    with tarfile.open(path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        if "manifest.json" not in members:
            raise ValueError("Missing backup manifest")
        manifest = json.load(archive.extractfile(members["manifest.json"]))
        if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
            raise ValueError("Unsupported backup format")
        for name, expected in manifest["files"].items():
            if name != "archive.sqlite3" and not (name.startswith("blobs/") and "/" not in name[6:]):
                raise ValueError("Unexpected backup path")
            member = members.get(name)
            if not member or not member.isfile() or member.size != expected["size"]:
                raise ValueError(f"Missing or wrong size: {name}")
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != expected["sha256"]:
                raise ValueError(f"Checksum mismatch: {name}")
        if set(members) != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("Unexpected entries in backup")
        return {"valid": True, "files": len(manifest["files"])}


def restore_backup(path: Path, destination: Path) -> dict:
    verify_backup(path)
    destination = destination.expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Restore destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "blobs").mkdir(exist_ok=True)
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.name == "manifest.json":
                continue
            target = destination / member.name
            with target.open("wb") as output:
                source = archive.extractfile(member)
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(block)
    return {"restored_to": str(destination)}
