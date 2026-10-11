"""Các chỉ số đánh giá OCR: CER (Character Error Rate) và WER (Word Error Rate)."""
import re
import unicodedata

from rapidfuzz.distance import Levenshtein


def normalize(text: str) -> str:
    """Chuẩn hóa Unicode NFC (tránh lỗi dấu dựng sẵn vs. tổ hợp) và gộp khoảng trắng."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt để tách riêng lỗi 'mặt chữ' và lỗi 'dấu'."""
    text = text.replace("đ", "d").replace("Đ", "D")
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def cer(ref: str, hyp: str) -> float:
    ref, hyp = normalize(ref), normalize(hyp)
    if not ref:
        return 0.0 if not hyp else 1.0
    return Levenshtein.distance(ref, hyp) / len(ref)


def wer(ref: str, hyp: str) -> float:
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    return Levenshtein.distance(r, h) / len(r)


def cer_no_diacritics(ref: str, hyp: str) -> float:
    return cer(strip_diacritics(ref), strip_diacritics(hyp))


def report(ref: str, hyp: str) -> dict:
    return {
        "CER": round(cer(ref, hyp) * 100, 2),
        "WER": round(wer(ref, hyp) * 100, 2),
        "CER_khong_dau": round(cer_no_diacritics(ref, hyp) * 100, 2),
    }
