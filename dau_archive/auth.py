from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from .db import audit, connect


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(rounds) < 100_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def create_user(username: str, password: str, role: str, department: str) -> str:
    if role not in {"admin", "staff"} or len(password) < 12:
        raise ValueError("Role must be admin/staff and password must contain at least 12 characters")
    if not username.strip() or not department.strip():
        raise ValueError("Username and department are required")
    user_id = str(uuid.uuid4())
    with connect() as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,department) VALUES (?,?,?,?,?)",
            (user_id, username.strip(), hash_password(password), role, department.strip()),
        )
        audit(db, user_id, "user.create", detail=username.strip())
    return user_id


def login(username: str, password: str) -> str | None:
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user["id"], expires),
        )
        audit(db, user["id"], "auth.login")
        return token


def session_user(token: str):
    if not token:
        return None
    key = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        return db.execute(
            "SELECT u.id,u.username,u.role,u.department FROM sessions s "
            "JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
            (key, datetime.now(timezone.utc).isoformat()),
        ).fetchone()


def logout(token: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def can_read(db, user, doc) -> bool:
    if user["role"] == "admin" or doc["owner_id"] == user["id"]:
        return True
    if doc["visibility"] == "public":
        return True
    if doc["visibility"] == "department" and doc["department"] == user["department"]:
        return True
    return db.execute(
        "SELECT 1 FROM grants WHERE document_id=? AND user_id=?", (doc["id"], user["id"])
    ).fetchone() is not None


def can_write(user, doc) -> bool:
    return user["role"] == "admin" or doc["owner_id"] == user["id"]
