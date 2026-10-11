"""Conservative, explainable document classification for repeated archive imports."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path


KINDS = {"incoming", "outgoing", "iso", "curriculum", "lesson", "other"}
ISO_ROLES = {"procedure", "form", "reference", "guide", "regulation", "other"}


def plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]+", " ", "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )).strip()


def classify(filename: str, archive_path: str = "", text: str = "", kind_hint: str = "") -> dict:
    """Return a suggested kind/role with inspectable evidence; no ML dependency."""
    source = plain(archive_path or filename)
    name = plain(Path(filename).stem)
    body = plain(text[:6000])
    parts = [plain(part) for part in archive_path.split("/") if part]

    if kind_hint == "iso" or (parts and any(part in {"dau iso", "iso"} for part in parts[:2])):
        kind, confidence, reason = "iso", 0.98, "Thư mục nguồn ISO"
    elif "quy trinh" in source or re.search(r"\biso\b", source):
        kind, confidence, reason = "iso", 0.85, "Tên tệp/thư mục có quy trình hoặc ISO"
    elif any(token in source for token in ("chuong trinh dao tao", "khung chuong trinh", "nganh dao tao")):
        kind, confidence, reason = "curriculum", 0.85, "Tên tệp/thư mục về chương trình đào tạo"
    elif any(token in source for token in ("giao an", "de cuong hoc phan", "bai giang")):
        kind, confidence, reason = "lesson", 0.85, "Tên tệp/thư mục về học liệu"
    elif "cong van den" in source or "cong van den" in body:
        kind, confidence, reason = "incoming", 0.72, "Cụm từ công văn đến"
    elif "cong van di" in source or "cong van di" in body:
        kind, confidence, reason = "outgoing", 0.72, "Cụm từ công văn đi"
    else:
        kind, confidence, reason = "other", 0.35, "Chưa có dấu hiệu đủ rõ; cần xác nhận"

    role = "other"
    if kind == "iso":
        # Folder names are stronger than filename keywords: a form can mention
        # the procedure it belongs to without itself being a procedure.
        folder_tail = parts[3:] if len(parts) > 3 else []
        if any("bieu mau" in part or "mau bieu" in part for part in folder_tail):
            role, reason = "form", reason + "; nằm trong thư mục Biểu mẫu"
        elif any(part in {"van ban", "van ban phap ly", "tai lieu vien dan"} for part in folder_tail):
            role, reason = "reference", reason + "; nằm trong thư mục Văn bản"
        elif "huong dan" in name:
            role, reason = "guide", reason + "; tên tệp là hướng dẫn"
        elif "quy dinh" in name:
            role, reason = "regulation", reason + "; tên tệp là quy định"
        elif "quy trinh" in name or len(parts) <= 4:
            role, reason = "procedure", reason + "; tài liệu ở cấp quy trình"
    return {"kind": kind, "subtype": role if kind == "iso" else "",
            "confidence": confidence, "evidence": reason}
