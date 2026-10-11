"""Evidence-preserving Vietnamese administrative metadata suggestions."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path


COMMON = {
    "document_number": r"(?:^|\n)\s*Số\s*[:：]\s*([\wĐđ/-]{3,60})",
    "signed_date": r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    "signer": r"(?:KT\.|TL\.|TUQ\.)?\s*(?:HIỆU TRƯỞNG|TRƯỞNG PHÒNG|GIÁM ĐỐC)\s*\n\s*([A-ZĐ][^\n]{3,70})",
}
SPECIFIC = {
    "incoming": {"sender": r"(?:Nơi gửi|Cơ quan ban hành)\s*[:：]\s*([^\n]{3,120})"},
    "outgoing": {"recipient": r"(?:Kính gửi|Nơi nhận)\s*[:：]\s*([^\n]{3,120})"},
    "iso": {
        "iso_code": r"(?:Mã tài liệu|Mã hiệu)\s*[:：]\s*([\w./-]{2,60})",
        "effective_date": r"(?:Ngày hiệu lực|Có hiệu lực từ)\s*[:：]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        "revision": r"(?:Lần ban hành|Phiên bản|Lần sửa đổi)\s*[:：]\s*([\w.-]{1,30})",
    },
    "curriculum": {
        "program": r"(?:Chương trình đào tạo|Ngành đào tạo)\s*[:：]\s*([^\n]{3,120})",
        "academic_year": r"(?:Năm học|Khóa học)\s*[:：]\s*(20\d{2}\s*[-–/]\s*20\d{2})",
    },
    "lesson": {
        "course_code": r"(?:Mã học phần|Mã môn học)\s*[:：]\s*([\w.-]{2,30})",
        "course_name": r"(?:Tên học phần|Tên môn học)\s*[:：]\s*([^\n]{3,120})",
        "academic_year": r"(?:Năm học|Khóa học)\s*[:：]\s*(20\d{2}\s*[-–/]\s*20\d{2})",
    },
}


def _line(text: str, start: int, end: int) -> str:
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    if b < 0:
        b = len(text)
    return text[a:b].strip()[:240]


def _ner_model():
    model_path = os.getenv("DAU_NER_MODEL_PATH", "")
    if not model_path or not Path(model_path).is_dir():
        return None
    from transformers import pipeline
    return pipeline("token-classification", model=model_path, tokenizer=model_path,
                    aggregation_strategy="simple", local_files_only=True)


_ner = None


def suggest_fields(pages: list[dict], kind: str, use_ner: bool = True) -> list[dict]:
    """Only suggest values directly supported by OCR/source text."""
    suggestions: list[dict] = []
    patterns = {**COMMON, **SPECIFIC.get(kind, {})}
    seen = set()
    for page in pages:
        text = page["text"]
        for key, pattern in patterns.items():
            if key in seen:
                continue
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if not match:
                continue
            if key == "signed_date":
                try:
                    value = date(int(match[3]), int(match[2]), int(match[1])).isoformat()
                except ValueError:
                    continue
            else:
                value = match[1].strip(" .,:;\t")
            if not value:
                continue
            suggestions.append({"field_key": key, "value": value,
                                "page_no": page["page_no"],
                                "evidence": _line(text, match.start(), match.end())})
            seen.add(key)

    # The locally installed Vietnamese NER model adds person/organization suggestions.
    global _ner
    if use_ner and os.getenv("DAU_NER_MODEL_PATH"):
        if _ner is None:
            _ner = _ner_model()
        if _ner is not None:
            for page in pages:
                for span in _ner(page["text"][:8000]):
                    group = span.get("entity_group", "").upper()
                    key = {"PER": "person", "ORG": "organization"}.get(group)
                    value = span.get("word", "").replace("##", "").strip()
                    if key and len(value) >= 3 and (key, value) not in seen:
                        start = int(span.get("start", 0))
                        end = int(span.get("end", start))
                        suggestions.append({"field_key": key, "value": value,
                                            "page_no": page["page_no"],
                                            "evidence": _line(page["text"], start, end)})
                        seen.add((key, value))
                if len(suggestions) >= 40:
                    break
    return suggestions
