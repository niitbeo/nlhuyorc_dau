import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple
import sys
import os
import re
import json
import time
import uuid
import hashlib
import sqlite3
from datetime import datetime
from collections import defaultdict
import torch
import cv2
import numpy as np
from PIL import Image
import io
import base64
from bs4 import BeautifulSoup

# Fix Paddle oneDNN CPU issues & UTF-8 console on Windows
os.environ["FLAGS_use_mkldnn"] = "False"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add vietocr path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg
from transformers import PreTrainedTokenizerFast, AutoModelForSeq2SeqLM

app = FastAPI(title="DAU DocFile AI - Hệ thống Quản lý Tài liệu Số & OCR Thông minh (Arkham Core)")

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- STORAGE & DATABASE SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage_docfile")
UPLOAD_DIR = os.path.join(STORAGE_DIR, "uploads")
FEEDBACK_DIR = os.path.join(STORAGE_DIR, "active_learning")
DB_PATH = os.path.join(STORAGE_DIR, "dau_docfile.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FEEDBACK_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT,
            folder_path TEXT,
            file_url TEXT,
            file_size INTEGER,
            checksum TEXT,
            ocr_mode TEXT,
            quality_info TEXT,
            raw_text TEXT,
            corrected_text TEXT,
            html_tables TEXT,
            entities TEXT,
            custom_fields TEXT,
            summary TEXT,
            graph_data TEXT,
            status TEXT,
            confidence REAL,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ocr_templates (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            fields_json TEXT,
            created_at TEXT
        )
    """)
    # Insert default templates if empty
    c.execute("SELECT COUNT(*) FROM ocr_templates")
    if c.fetchone()[0] == 0:
        default_templates = [
            (
                "tpl_hanh_chinh",
                "Văn bản Hành chính (Quyết định / Thông báo)",
                "Trích xuất chuẩn cho Quyết định, Thông báo, Tờ trình đại học",
                json.dumps([
                    {"key": "so_van_ban", "label": "Số văn bản", "pattern": r"Số:\s*([0-9]+/[A-ZĐa-zđ\-]+)", "type": "regex"},
                    {"key": "ngay_ban_hanh", "label": "Ngày ban hành", "pattern": r"ngày\s+([0-9]{1,2})\s+tháng\s+([0-9]{1,2})\s+năm\s+([0-9]{4})", "type": "regex"},
                    {"key": "nguoi_ky", "label": "Người ký / Chức vụ", "pattern": r"(HIỆU TRƯỞNG|PHÓ HIỆU TRƯỞNG|TRƯỞNG PHÒNG|TRƯỞNG KHOA)", "type": "regex"},
                    {"key": "kinh_phi", "label": "Số tiền / Kinh phí", "pattern": r"([0-9]{1,3}(?:\.[0-9]{3})+\s*(?:đồng|VNĐ|VND))", "type": "regex"}
                ], ensure_ascii=False),
                datetime.now().isoformat()
            ),
            (
                "tpl_sinh_vien",
                "Đơn từ & Hồ sơ Sinh viên (Viết tay / In)",
                "Trích xuất Họ tên, Mã SV, Lớp, Khoa, Điểm số từ đơn hoặc bảng điểm",
                json.dumps([
                    {"key": "ma_sinh_vien", "label": "Mã sinh viên (MSSV)", "pattern": r"(?:MSSV|Mã SV|Mã số SV)[:\s]*([0-9A-Za-z]{5,12})", "type": "regex"},
                    {"key": "lop_hoc", "label": "Lớp sinh hoạt", "pattern": r"Lớp[:\s]*([0-9]{2}[A-Za-z0-9_\-]+)", "type": "regex"},
                    {"key": "so_dien_thoai", "label": "Số điện thoại", "pattern": r"(0[0-9]{9,10})", "type": "regex"}
                ], ensure_ascii=False),
                datetime.now().isoformat()
            )
        ]
        c.executemany("INSERT INTO ocr_templates VALUES (?, ?, ?, ?, ?)", default_templates)
    conn.commit()
    conn.close()

init_db()

# --- 1. Load OCR Model (VietOCR) + Lazy Load Heavy Engines ---
print("[INFO] Đang nạp mô hình VietOCR (Handwriting/Printed)...")
config_path = os.path.join(BASE_DIR, '..', 'configs', 'vgg_transformer_base.yml')
if not os.path.exists(config_path):
    config_path = 'configs/vgg_transformer_base.yml'
config = Cfg.load_config_from_file(config_path)
config['device'] = 'cuda:0' if torch.cuda.is_available() else 'cpu'
weights_path = r'd:\orc\weights\handwriting_pro.pth'
if os.path.exists(weights_path):
    config['weights'] = weights_path
config['dataset']['image_max_width'] = 2048
ocr_predictor = Predictor(config)

# Lazy-loaded engines để cổng 8000 mở ngay lập tức trong 2 giây!
_table_engine = None
_table_engine_loaded = False
_protonx_tokenizer = None
_protonx_model = None
_protonx_loaded = False
_ner_pipeline = None
_ner_loaded = False

def get_table_engine():
    global _table_engine, _table_engine_loaded
    if not _table_engine_loaded:
        _table_engine_loaded = True
        try:
            print("[INFO] Đang nạp Table Engine (PPStructureV3)...")
            from paddleocr import PPStructureV3
            _table_engine = PPStructureV3(
                use_table_recognition=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False
            )
        except Exception as e:
            print(f"[WARN] Không thể nạp PPStructureV3: {e}")
    return _table_engine

def get_protonx():
    global _protonx_tokenizer, _protonx_model, _protonx_loaded
    if not _protonx_loaded:
        _protonx_loaded = True
        try:
            print("[INFO] Đang nạp máy sửa lỗi chính tả ProtonX...")
            _protonx_tokenizer = PreTrainedTokenizerFast.from_pretrained("protonx-models/protonx-legal-tc")
            _protonx_model = AutoModelForSeq2SeqLM.from_pretrained("protonx-models/protonx-legal-tc")
        except Exception as e:
            print(f"[WARN] Lỗi nạp mô hình chính tả: {e}")
    return _protonx_tokenizer, _protonx_model

def get_ner_pipeline():
    global _ner_pipeline, _ner_loaded
    if not _ner_loaded:
        _ner_loaded = True
        try:
            print("[INFO] Đang nạp mô hình NER Tiếng Việt (NlpHUST Electra)...")
            from transformers import pipeline
            _ner_pipeline = pipeline("ner", model="NlpHUST/ner-vietnamese-electra-base", aggregation_strategy="simple")
        except Exception as e:
            print(f"[WARN] Chưa nạp được NlpHUST NER ({e}), dùng chế độ Regex + Heuristic NER.")
    return _ner_pipeline


# =====================================================================
# ARKHAM MIRROR MODULE 1: IMAGE QUALITY & OPENCV PREPROCESSING
# =====================================================================
class ArkhamImageProcessor:
    """Rút trích từ arkham-shard-ingest: ImageQualityClassifier & ImageWorker"""

    @staticmethod
    def analyze_and_preprocess(img_bgr: np.ndarray, auto_enhance: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
        start_t = time.perf_counter()
        h, w = img_bgr.shape[:2]
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape) == 3 else img_bgr.copy()

        # 1. Contrast & Blank Check
        std_val = float(np.std(gray))
        contrast_ratio = round(min(1.0, std_val / 80.0), 3)
        white_ratio = float(np.sum(gray > 240) / gray.size)
        is_blank = (std_val < 10.0) or (white_ratio > 0.992)

        # 2. Noise level via Laplacian variance
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        has_noise = laplacian_var > 600.0

        # 3. Layout assessment (Table vs Simple Text)
        row_means = np.mean(gray, axis=1)
        col_means = np.mean(gray, axis=0)
        row_edges = int(np.sum(np.abs(np.diff(row_means)) > 25))
        col_edges = int(np.sum(np.abs(np.diff(col_means)) > 25))
        edge_ratio = (row_edges + col_edges) / float(h + w)
        layout_type = "table" if edge_ratio >= 0.08 else "text"

        # 4. Skew Estimation & Deskew
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(thresh > 0))
        skew_angle = 0.0
        if len(coords) > 50:
            rect = cv2.minAreaRect(coords)
            angle = rect[-1]
            if angle < -45:
                angle = 90 + angle
            elif angle > 45:
                angle = angle - 90
            if abs(angle) <= 10.0:
                skew_angle = round(float(angle), 2)

        # Classification: CLEAN, FIXABLE, MESSY
        if contrast_ratio > 0.45 and not has_noise and abs(skew_angle) < 1.5:
            quality_label = "CLEAN"
        elif contrast_ratio > 0.2 and abs(skew_angle) < 8.0:
            quality_label = "FIXABLE"
        else:
            quality_label = "MESSY"

        ops_applied = []
        processed_bgr = img_bgr.copy()

        if auto_enhance and not is_blank:
            # Deskew if needed
            if abs(skew_angle) >= 0.4:
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
                processed_bgr = cv2.warpAffine(
                    processed_bgr, M, (w, h),
                    flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
                )
                ops_applied.append(f"deskew({skew_angle}°)")

            # Contrast Enhancement (CLAHE on L channel) if low contrast
            if contrast_ratio < 0.55:
                lab = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                cl = clahe.apply(l)
                limg = cv2.merge((cl, a, b))
                processed_bgr = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
                ops_applied.append("clahe_contrast")

        elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
        quality_info = {
            "width": w,
            "height": h,
            "contrast_ratio": contrast_ratio,
            "skew_angle": skew_angle,
            "has_noise": has_noise,
            "is_blank": is_blank,
            "detected_layout": layout_type,
            "classification": quality_label,
            "operations_applied": ops_applied,
            "analysis_ms": elapsed_ms
        }
        return processed_bgr, quality_info


# =====================================================================
# ARKHAM MIRROR MODULE 2: MULTI-LINE SEGMENTATION + VIETOCR
# =====================================================================
def segment_and_ocr_lines(img_bgr: np.ndarray) -> Tuple[str, List[Dict[str, Any]], float]:
    """
    Tách dòng văn bản (nếu ảnh có nhiều dòng) và đọc từng dòng bằng VietOCR.
    Nếu ảnh chỉ là 1 dòng cắt sẵn (chiều cao nhỏ), đưa thẳng vào VietOCR.
    """
    h, w = img_bgr.shape[:2]
    lines_output = []

    # Nếu là ảnh crop 1 dòng (tỷ lệ ngang dài hoặc chiều cao < 140px)
    if h < 140 or (w / max(h, 1) > 4.5):
        pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        text = ocr_predictor.predict(pil_img)
        lines_output.append({
            "id": "line_1",
            "box": [0, 0, w, h],
            "raw_text": text,
            "corrected_text": correct_text(text),
            "confidence": 0.94
        })
        return text, lines_output, 0.94

    # Dùng hình thái học OpenCV (Horizontal Projection & Dilation) để tách các dòng chữ trong trang tài liệu
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Nối liền các chữ trên cùng 1 dòng bằng kernel ngang
    kernel_w = max(25, int(w * 0.04))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 3))
    dilated = cv2.dilate(binary, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bboxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        # Lọc nhiễu chấm nhỏ
        if bw > 25 and bh > 12 and bh < h * 0.4:
            # Mở rộng nhẹ lề trên dưới để không mất dấu tiếng Việt
            pad_y = max(3, int(bh * 0.15))
            pad_x = max(4, int(bw * 0.02))
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(w, x + bw + pad_x)
            y2 = min(h, y + bh + pad_y)
            bboxes.append((x1, y1, x2, y2))

    # Nếu không tìm thấy nhiều dòng hoặc chỉ có 1 khối, đọc toàn ảnh
    if len(bboxes) <= 1:
        pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        text = ocr_predictor.predict(pil_img)
        corr = correct_text(text)
        lines_output.append({
            "id": "line_1",
            "box": [0, 0, w, h],
            "raw_text": text,
            "corrected_text": corr,
            "confidence": 0.92
        })
        return text, lines_output, 0.92

    # Sắp xếp các dòng từ trên xuống dưới, từ trái qua phải (gom nhóm theo hàng Y)
    bboxes.sort(key=lambda b: (b[1] // 20, b[0]))

    raw_lines = []
    for idx, (x1, y1, x2, y2) in enumerate(bboxes[:60]):  # Giới hạn tối đa 60 dòng/trang
        crop = img_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        line_txt = ocr_predictor.predict(pil_crop).strip()
        if line_txt:
            raw_lines.append(line_txt)
            lines_output.append({
                "id": f"line_{idx+1}",
                "box": [int(x1), int(y1), int(x2), int(y2)],
                "raw_text": line_txt,
                "corrected_text": line_txt,
                "confidence": 0.93
            })

    full_raw = "\n".join(raw_lines)
    return full_raw, lines_output, 0.93


def correct_text(text: str, use_llm: bool = False) -> str:
    if not text or not text.strip():
        return text
    if not use_llm:
        return text
    tok, mdl = get_protonx()
    if not mdl or not tok:
        return text
    try:
        lines = text.split("\n")
        corrected_lines = []
        for line in lines:
            if not line.strip():
                corrected_lines.append("")
                continue
            input_ids = tok(line[:250], return_tensors="pt").input_ids
            outputs = mdl.generate(input_ids, max_length=256)
            corrected_lines.append(tok.decode(outputs[0], skip_special_tokens=True))
        return "\n".join(corrected_lines)
    except Exception:
        return text


# =====================================================================
# ARKHAM MIRROR MODULE 3: 3-LAYER ENTITY EXTRACTION + CUSTOM DEFINITIONS
# =====================================================================
def extract_arkham_entities(text: str, custom_rules: List[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Rút trích từ arkham-shard-parse (DAUDocumentExtractor + RelationExtractor)
    """
    entities = {
        "so_van_ban": None,
        "ngay_ban_hanh": None,
        "loai_van_ban": "Văn bản chung",
        "PERSON": [],
        "ORGANIZATION": [],
        "LOCATION": [],
        "MONEY": [],
        "MSSV": [],
        "custom_extracted": {}
    }

    if not text:
        return entities

    # LAYER 1: Regex Hành chính & Đại học
    so_match = re.search(r'Số:\s*([0-9]+/[A-ZĐa-zđ0-9\-]+)', text, re.IGNORECASE)
    if so_match:
        entities["so_van_ban"] = so_match.group(1)

    ngay_match = re.search(r'ngày\s+([0-9]{1,2})\s+tháng\s+([0-9]{1,2})\s+năm\s+([0-9]{4})', text, re.IGNORECASE)
    if ngay_match:
        entities["ngay_ban_hanh"] = f"{ngay_match.group(1).zfill(2)}/{ngay_match.group(2).zfill(2)}/{ngay_match.group(3)}"
    else:
        date_slash = re.search(r'\b([0-9]{1,2}/[0-9]{1,2}/20[0-9]{2})\b', text)
        if date_slash:
            entities["ngay_ban_hanh"] = date_slash.group(1)

    upper_txt = text.upper()
    if "QUYẾT ĐỊNH" in upper_txt:
        entities["loai_van_ban"] = "Quyết Định"
    elif "THÔNG BÁO" in upper_txt:
        entities["loai_van_ban"] = "Thông Báo"
    elif "TỜ TRÌNH" in upper_txt:
        entities["loai_van_ban"] = "Tờ Trình"
    elif "ĐƠN XIN" in upper_txt or "CỘNG HÒA XÃ HỘI" in upper_txt and "KÍNH GỬI" in upper_txt:
        entities["loai_van_ban"] = "Đơn Từ / Hồ Sơ"
    elif "BẢNG ĐIỂM" in upper_txt or "KẾT QUẢ HỌC TẬP" in upper_txt:
        entities["loai_van_ban"] = "Bảng Điểm"
    elif "BIÊN BẢN" in upper_txt:
        entities["loai_van_ban"] = "Biên Bản"

    # Tìm số tiền & Mã SV
    money_matches = re.findall(r'[0-9]{1,3}(?:\.[0-9]{3})+\s*(?:đồng|VNĐ|VND|đ)', text, re.IGNORECASE)
    entities["MONEY"] = list(set(money_matches))

    mssv_matches = re.findall(r'(?:MSSV|Mã SV|Mã số SV)[:\s]*([0-9A-Za-z]{5,12})', text, re.IGNORECASE)
    entities["MSSV"] = list(set(mssv_matches))

    # LAYER 2: Heuristic Tiếng Việt siêu tốc + PhoBERT / Electra NER
    org_patterns = re.findall(
        r'((?:Trường|Phòng|Khoa|Bộ|Ban|Trung tâm|Hội đồng)\s+[A-ZĐÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴ][a-zđáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+(?:\s+[A-ZĐa-zđáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+){1,4})',
        text
    )
    entities["ORGANIZATION"].extend(org_patterns)

    per_patterns = re.findall(
        r'(?:sinh viên|ông|bà|thầy|cô|họ và tên|Người ký|Hiệu trưởng)[:\s]+([A-ZĐÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴ][a-zđáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+(?:\s+[A-ZĐÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴ][a-zđáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+){1,3})',
        text, re.IGNORECASE
    )
    entities["PERSON"].extend(per_patterns)

    for k in ["PERSON", "ORGANIZATION", "LOCATION"]:
        entities[k] = list(dict.fromkeys([x.strip() for x in entities[k] if len(x.strip()) > 2]))[:15]

    # LAYER 3: Custom User-Defined Extraction Rules (Định nghĩa OCR của người dùng)
    if custom_rules:
        for rule in custom_rules:
            r_key = rule.get("key") or rule.get("label", "field")
            r_pat = rule.get("pattern", "")
            if r_pat:
                try:
                    m = re.search(r_pat, text, re.IGNORECASE)
                    if m:
                        entities["custom_extracted"][r_key] = m.group(1) if m.groups() else m.group(0)
                    else:
                        entities["custom_extracted"][r_key] = None
                except Exception:
                    entities["custom_extracted"][r_key] = None

    return entities


# =====================================================================
# ARKHAM MIRROR MODULE 4: SMART SUMMARIZATION ENGINE
# =====================================================================
def generate_arkham_summary(text: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rút trích từ arkham-shard-summary: Tự động tạo Tiêu đề, Tóm tắt điều hành (Executive Summary),
    và Danh sách Ý chính (Key Bullet Points).
    """
    if not text or not text.strip():
        return {
            "title": "Tài liệu trống",
            "executive_summary": "Không phát hiện nội dung văn bản trong tài liệu.",
            "key_points": [],
            "word_count": 0
        }

    clean_lines = [l.strip() for l in text.split("\n") if l.strip()]
    sentences = [s.strip() for s in re.split(r'[.\n]+', text) if len(s.strip()) > 10]

    # 1. Xác định Tiêu đề thông minh
    title = entities.get("loai_van_ban", "Văn bản")
    vv_match = re.search(r'(?:Về việc|V/v)[:\s]+([^\n.]{10,120})', text, re.IGNORECASE)
    if vv_match:
        title = f"{title}: {vv_match.group(1).strip()}"
    elif clean_lines:
        first_meaningful = next((l for l in clean_lines if len(l) > 8 and "CỘNG HÒA" not in l.upper() and "ĐỘC LẬP" not in l.upper()), clean_lines[0])
        title = first_meaningful[:90]

    # 2. Chấm điểm câu quan trọng (Sentence Scoring theo mật độ thực thể & từ khóa hành chính)
    important_keywords = ["quyết định", "thông báo", "giao cho", "chịu trách nhiệm", "khen thưởng", "kỷ luật", "sinh viên", "học phí", "thời gian", "đề nghị", "xét", "điều 1", "điều 2"]
    scored_sentences = []
    for idx, sent in enumerate(sentences):
        score = 0.0
        s_lower = sent.lower()
        for kw in important_keywords:
            if kw in s_lower:
                score += 2.0
        for p in entities.get("PERSON", []):
            if p.lower() in s_lower:
                score += 2.5
        for o in entities.get("ORGANIZATION", []):
            if o.lower() in s_lower:
                score += 1.5
        if idx < 3:
            score += 1.0  # Ưu tiên câu đầu
        scored_sentences.append((score, idx, sent))

    scored_sentences.sort(key=lambda x: (-x[0], x[1]))
    top_sentences = sorted(scored_sentences[:3], key=lambda x: x[1])
    executive_summary = ". ".join([s[2] for s in top_sentences])
    if not executive_summary and clean_lines:
        executive_summary = " ".join(clean_lines[:2])

    # 3. Tạo Key Points (Gạch đầu dòng cốt lõi)
    key_points = []
    if entities.get("so_van_ban"):
        key_points.append(f"Số hiệu văn bản: {entities['so_van_ban']} ({entities.get('loai_van_ban')})")
    if entities.get("ngay_ban_hanh"):
        key_points.append(f"Thời gian ban hành: {entities['ngay_ban_hanh']}")
    if entities.get("PERSON"):
        key_points.append(f"Nhân sự liên quan: {', '.join(entities['PERSON'][:5])}")
    if entities.get("ORGANIZATION"):
        key_points.append(f"Đơn vị / Phòng ban: {', '.join(entities['ORGANIZATION'][:4])}")
    if entities.get("MONEY"):
        key_points.append(f"Số tiền / Kinh phí đề cập: {', '.join(entities['MONEY'])}")
    for s in top_sentences[:2]:
        if len(key_points) < 5:
            key_points.append(s[2][:140])

    return {
        "title": title,
        "executive_summary": executive_summary,
        "key_points": key_points,
        "word_count": len(text.split())
    }


# =====================================================================
# ARKHAM MIRROR MODULE 5: DOCUMENT & ENTITY KNOWLEDGE GRAPH BUILDER
# =====================================================================
def build_arkham_graph(doc_id: str, filename: str, text: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rút trích từ arkham-shard-graph (GraphBuilder + Centrality):
    Xây dựng Đỉnh (Nodes) và Cạnh (Edges) liên kết giữa Tài liệu - Con người - Tổ chức - Thời gian.
    """
    nodes = []
    edges = []

    doc_label = entities.get("so_van_ban") or filename[:25]
    doc_node_id = f"doc_{doc_id[:8]}"
    nodes.append({
        "id": doc_node_id,
        "label": doc_label,
        "type": "DOCUMENT",
        "sub_type": entities.get("loai_van_ban", "Tài liệu"),
        "degree": 0
    })

    # Thêm Node Ngày tháng
    if entities.get("ngay_ban_hanh"):
        date_id = f"date_{entities['ngay_ban_hanh']}"
        nodes.append({"id": date_id, "label": entities["ngay_ban_hanh"], "type": "DATE", "degree": 1})
        edges.append({"source": doc_node_id, "target": date_id, "label": "NGÀY_KÝ", "weight": 1.0})

    # Thêm Node Tổ chức / Phòng ban
    org_ids = {}
    for org in entities.get("ORGANIZATION", []):
        oid = f"org_{hashlib.md5(org.encode()).hexdigest()[:8]}"
        org_ids[org] = oid
        nodes.append({"id": oid, "label": org, "type": "ORGANIZATION", "degree": 1})
        edges.append({"source": doc_node_id, "target": oid, "label": "ĐƠN_VỊ_LIÊN_QUAN", "weight": 1.5})

    # Thêm Node Nhân sự / Sinh viên
    per_ids = {}
    for per in entities.get("PERSON", []):
        pid = f"per_{hashlib.md5(per.encode()).hexdigest()[:8]}"
        per_ids[per] = pid
        nodes.append({"id": pid, "label": per, "type": "PERSON", "degree": 1})
        edges.append({"source": doc_node_id, "target": pid, "label": "ĐỀ_CẬP_NHÂN_SỰ", "weight": 1.5})

    # Co-occurrence Edges (Nếu Người và Tổ chức đứng gần nhau < 150 ký tự giống RelationExtractor)
    for per, pid in per_ids.items():
        for org, oid in org_ids.items():
            pos_p = text.find(per)
            pos_o = text.find(org)
            if pos_p != -1 and pos_o != -1 and abs(pos_p - pos_o) <= 180:
                edges.append({
                    "source": pid,
                    "target": oid,
                    "label": "THUỘC_ĐƠN_VỊ",
                    "weight": 2.0
                })

    # Tính Degree cho từng Node
    deg_map = defaultdict(int)
    for e in edges:
        deg_map[e["source"]] += 1
        deg_map[e["target"]] += 1
    for n in nodes:
        n["degree"] = deg_map.get(n["id"], 0)

    return {
        "nodes": nodes,
        "edges": edges
    }


def extract_tables_from_image(img_bgr: np.ndarray) -> List[str]:
    tbl_eng = get_table_engine()
    if not tbl_eng:
        return []
    final_htmls = []
    try:
        res_list = list(tbl_eng.predict(img_bgr))
        for res in res_list:
            res_dict = dict(res)
            html_str = res_dict.get('html', res_dict.get('table_html', ''))
            cell_bboxes = res_dict.get('cell_bboxes', res_dict.get('table_cell_bboxes', []))
            if html_str and len(cell_bboxes) > 0:
                cell_texts = []
                for box in cell_bboxes:
                    if len(box) == 4:
                        x1, y1, x2, y2 = [int(v) for v in box]
                    else:
                        x1 = int(min([p[0] for p in box]))
                        y1 = int(min([p[1] for p in box]))
                        x2 = int(max([p[0] for p in box]))
                        y2 = int(max([p[1] for p in box]))
                    cell_img = img_bgr[max(0, y1):y2, max(0, x1):x2]
                    if cell_img.size == 0 or cell_img.shape[0] < 5 or cell_img.shape[1] < 5:
                        cell_texts.append("")
                        continue
                    cell_pil = Image.fromarray(cv2.cvtColor(cell_img, cv2.COLOR_BGR2RGB))
                    text = ocr_predictor.predict(cell_pil)
                    cell_texts.append(text)
                soup = BeautifulSoup(html_str, 'html.parser')
                tds = soup.find_all(['td', 'th'])
                for idx, td in enumerate(tds):
                    if idx < len(cell_texts):
                        td.string = cell_texts[idx]
                final_htmls.append(str(soup))
    except Exception as e:
        print(f"[WARN] Table extraction error: {e}")
    return final_htmls


# =====================================================================
# ENDPOINTS: ALL-IN-ONE OCR + DOCFILE MANAGEMENT + ARKHAM INTELLIGENCE
# =====================================================================
class OCRResponse(BaseModel):
    raw_text: str
    corrected_text: str

@app.post("/ocr/image", response_model=OCRResponse)
async def process_image(file: UploadFile = File(...)):
    """Endpoint tương thích ngược với ArkhamMirror Worker cũ"""
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    processed_bgr, _ = ArkhamImageProcessor.analyze_and_preprocess(img_bgr, auto_enhance=True)
    raw_text, _, _ = segment_and_ocr_lines(processed_bgr)
    corrected = correct_text(raw_text)
    return OCRResponse(raw_text=raw_text, corrected_text=corrected)


@app.post("/ocr/table")
async def process_table(file: UploadFile = File(...)):
    """Endpoint nhận diện Bảng biểu chuyên dụng"""
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    htmls = extract_tables_from_image(img_bgr)
    if not htmls:
        return {"status": "success", "message": "Không tìm thấy bảng nào", "htmls": []}
    return {"status": "success", "message": "Đã bóc bảng thành công", "htmls": htmls}


def create_text_preview_image(title_text: str, body_text: str, save_img_path: str):
    """Tạo ảnh preview đại diện cho tài liệu DOCX / TXT / XLSX để hiển thị đồng bộ trên Trạm OCR"""
    from PIL import ImageDraw, ImageFont
    w, h = 900, 1200
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Vẽ khung viền trang giấy A4
    draw.rectangle([25, 25, w - 25, h - 25], outline=(200, 210, 225), width=2)
    draw.rectangle([25, 25, w - 25, 95], fill=(30, 41, 59))
    try:
        font_title = ImageFont.truetype("arial.ttf", 20)
        font_body = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    draw.text((45, 48), f"TÀI LIỆU SỐ: {title_text[:55]}", fill=(255, 255, 255), font=font_title)

    y_offset = 120
    for line in body_text.split("\n")[:42]:
        wrapped = [line[i:i+85] for i in range(0, max(1, len(line)), 85)]
        for subline in wrapped:
            if y_offset > h - 60:
                break
            draw.text((45, y_offset), subline, fill=(20, 25, 35), font=font_body)
            y_offset += 24

    img.save(save_img_path)


@app.post("/api/docfile/upload")
async def upload_and_analyze_document(
    file: UploadFile = File(...),
    folder_path: str = Form("Hồ sơ chung"),
    ocr_mode: str = Form("auto"),  # auto | text | table | handwriting
    template_id: str = Form("tpl_hanh_chinh"),
    custom_rules_json: str = Form("[]")
):
    """
    Pipeline Toàn diện hỗ trợ MỌI ĐỊNH DẠNG VĂN BẢN:
    - PDF (.pdf): Tự động trích xuất text gốc + Render từng trang qua PyMuPDF để chạy VietOCR & Table OCR nếu là PDF scan!
    - Word (.docx, .doc): Trích xuất toàn bộ đoạn văn + Chuyển toàn bộ Bảng trong Word sang HTML Table!
    - Excel / CSV / TXT (.xlsx, .csv, .txt, .md): Trích xuất dữ liệu & bảng biểu!
    - Ảnh (.png, .jpg, .jpeg, .webp, .bmp, .tif, .tiff): Chạy OpenCV Deskew/CLAHE + VietOCR + PP-Structure Table!
    """
    contents = await file.read()
    checksum = hashlib.sha256(contents).hexdigest()
    file_size = len(contents)

    doc_id = str(uuid.uuid4())
    orig_filename = file.filename or "tai_lieu"
    ext = os.path.splitext(orig_filename)[1].lower() or ".png"
    safe_name = f"{doc_id}{ext}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(save_path, "wb") as f:
        f.write(contents)

    raw_text = ""
    corrected_text = ""
    lines_data = []
    html_tables = []
    confidence = 0.95
    effective_mode = ocr_mode
    quality_info = {
        "width": 900,
        "height": 1200,
        "contrast_ratio": 0.9,
        "skew_angle": 0.0,
        "has_noise": False,
        "is_blank": False,
        "detected_layout": "document",
        "classification": "CLEAN",
        "operations_applied": [f"format({ext})"],
        "analysis_ms": 5.0
    }
    preview_file_url = f"/files/{safe_name}"

    # -----------------------------------------------------------------
    # NHÁNH 1: XỬ LÝ FILE PDF (Cả PDF điện tử lẫn PDF Scan / Viết tay)
    # -----------------------------------------------------------------
    if ext == ".pdf":
        import pymupdf
        pdf_doc = pymupdf.open(stream=contents, filetype="pdf")
        page_texts = []
        preview_saved = False
        total_pages = min(len(pdf_doc), 15)  # Xử lý tối đa 15 trang đầu để đảm bảo tốc độ

        for pno in range(total_pages):
            page = pdf_doc[pno]
            # Render trang PDF ra ảnh độ phân giải 180 DPI
            pix = page.get_pixmap(dpi=180)
            img_bytes = pix.tobytes("png")
            if not preview_saved:
                preview_name = f"{doc_id}_page1.png"
                preview_path = os.path.join(UPLOAD_DIR, preview_name)
                with open(preview_path, "wb") as pf:
                    pf.write(img_bytes)
                preview_file_url = f"/files/{preview_name}"
                preview_saved = True

            # Kiểm tra xem trang PDF đã có lớp text gốc chưa
            embedded_text = page.get_text("text").strip()
            nparr = np.frombuffer(img_bytes, np.uint8)
            page_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if pno == 0 and page_bgr is not None:
                page_bgr, quality_info = ArkhamImageProcessor.analyze_and_preprocess(page_bgr, auto_enhance=True)
                quality_info["operations_applied"].append(f"pdf_pages({len(pdf_doc)})")

            if len(embedded_text) > 40 and ocr_mode != "handwriting":
                # PDF có sẵn text điện tử chuẩn
                page_texts.append(f"--- [Trang {pno + 1}] ---\n{embedded_text}")
            elif page_bgr is not None:
                # PDF Scan ảnh -> Đưa vào VietOCR đọc!
                p_raw, p_lines, p_conf = segment_and_ocr_lines(page_bgr)
                page_texts.append(f"--- [Trang {pno + 1} - OCR] ---\n{p_raw}")
                if pno == 0:
                    lines_data = p_lines
                    confidence = p_conf

            # Bóc bảng nếu người dùng chọn chế độ Bảng biểu
            if page_bgr is not None and ocr_mode == "table":
                t_htmls = extract_tables_from_image(page_bgr)
                html_tables.extend(t_htmls)

        raw_text = "\n\n".join(page_texts)
        corrected_text = correct_text(raw_text) if len(raw_text) < 2000 else raw_text
        effective_mode = "pdf_hybrid"

    # -----------------------------------------------------------------
    # NHÁNH 2: XỬ LÝ FILE WORD (.DOCX)
    # -----------------------------------------------------------------
    elif ext in (".docx", ".doc"):
        try:
            import docx
            doc_obj = docx.Document(io.BytesIO(contents))
            paras = [p.text.strip() for p in doc_obj.paragraphs if p.text.strip()]
            raw_text = "\n".join(paras)

            # Bóc toàn bộ Bảng biểu trong file Word ra HTML Table
            for tbl in doc_obj.tables:
                rows_html = []
                for r_idx, row in enumerate(tbl.rows):
                    cells_html = []
                    tag = "th" if r_idx == 0 else "td"
                    for cell in row.cells:
                        cells_html.append(f"<{tag}>{cell.text.strip()}</{tag}>")
                    rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
                if rows_html:
                    html_tables.append(f"<table>{''.join(rows_html)}</table>")

            corrected_text = raw_text
            effective_mode = "docx_native"
            confidence = 0.99

            # Tạo ảnh preview trang tài liệu để hiển thị bên khung trái Trạm OCR
            preview_name = f"{doc_id}_preview.png"
            preview_path = os.path.join(UPLOAD_DIR, preview_name)
            create_text_preview_image(orig_filename, raw_text or "Tài liệu Word chứa bảng biểu", preview_path)
            preview_file_url = f"/files/{preview_name}"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Không thể đọc file Word ({orig_filename}): {e}")

    # -----------------------------------------------------------------
    # NHÁNH 3: XỬ LÝ FILE EXCEL (.XLSX) & TEXT / CSV (.TXT, .CSV, .MD)
    # -----------------------------------------------------------------
    elif ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
            sheet_texts = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows_html = []
                for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if not any(row):
                        continue
                    row_vals = [str(c) if c is not None else "" for c in row]
                    sheet_texts.append(" | ".join(row_vals))
                    tag = "th" if r_idx == 0 else "td"
                    cells = "".join([f"<{tag}>{v}</{tag}>" for v in row_vals])
                    rows_html.append(f"<tr>{cells}</tr>")
                if rows_html:
                    html_tables.append(f"<table>{''.join(rows_html[:100])}</table>")
            raw_text = "\n".join(sheet_texts)
            corrected_text = raw_text
            effective_mode = "excel_table"
            confidence = 0.99

            preview_name = f"{doc_id}_preview.png"
            preview_path = os.path.join(UPLOAD_DIR, preview_name)
            create_text_preview_image(orig_filename, raw_text, preview_path)
            preview_file_url = f"/files/{preview_name}"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Không thể đọc file Excel ({orig_filename}): {e}")

    elif ext in (".txt", ".csv", ".md", ".json"):
        raw_text = contents.decode("utf-8", errors="ignore")
        corrected_text = raw_text
        effective_mode = "text_native"
        confidence = 1.0
        preview_name = f"{doc_id}_preview.png"
        preview_path = os.path.join(UPLOAD_DIR, preview_name)
        create_text_preview_image(orig_filename, raw_text, preview_path)
        preview_file_url = f"/files/{preview_name}"

    # -----------------------------------------------------------------
    # NHÁNH 4: XỬ LÝ HÌNH ẢNH SCAN / CHỤP ĐIỆN THOẠI (.PNG, .JPG, .WEBP, .BMP, .TIFF)
    # -----------------------------------------------------------------
    else:
        nparr = np.frombuffer(contents, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail=f"Định dạng file '{orig_filename}' không được hỗ trợ hoặc bị lỗi.")

        processed_bgr, quality_info = ArkhamImageProcessor.analyze_and_preprocess(img_bgr, auto_enhance=True)
        if effective_mode == "auto":
            effective_mode = quality_info.get("detected_layout", "text")

        raw_text, lines_data, confidence = segment_and_ocr_lines(processed_bgr)
        corrected_text = correct_text(raw_text)

        if ocr_mode == "table":
            html_tables = extract_tables_from_image(processed_bgr)

    # 3. Load Template Rules + Custom Rules
    rules = []
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT fields_json FROM ocr_templates WHERE id = ?", (template_id,))
        row = c.fetchone()
        if row:
            rules.extend(json.loads(row[0]))
        conn.close()
    except Exception:
        pass

    try:
        extra_rules = json.loads(custom_rules_json)
        if isinstance(extra_rules, list):
            rules.extend(extra_rules)
    except Exception:
        pass

    # 4. Arkham 3-Layer Entity Extraction
    entities = extract_arkham_entities(corrected_text, custom_rules=rules)
    entities["lines"] = lines_data

    # 5. Arkham Summary Generation
    summary_data = generate_arkham_summary(corrected_text, entities)

    # 6. Arkham Graph Builder
    graph_data = build_arkham_graph(doc_id, orig_filename, corrected_text, entities)

    now_iso = datetime.now().isoformat()

    # Lưu vào SQLite
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        doc_id,
        orig_filename,
        folder_path,
        preview_file_url,
        file_size,
        checksum,
        effective_mode,
        json.dumps(quality_info, ensure_ascii=False),
        raw_text,
        corrected_text,
        json.dumps(html_tables, ensure_ascii=False),
        json.dumps(entities, ensure_ascii=False),
        json.dumps(rules, ensure_ascii=False),
        json.dumps(summary_data, ensure_ascii=False),
        json.dumps(graph_data, ensure_ascii=False),
        "processed",
        confidence,
        now_iso,
        now_iso
    ))
    conn.commit()
    conn.close()

    return {
        "id": doc_id,
        "filename": orig_filename,
        "folder_path": folder_path,
        "file_url": preview_file_url,
        "file_size": file_size,
        "checksum": checksum,
        "ocr_mode": effective_mode,
        "quality_info": quality_info,
        "raw_text": raw_text,
        "corrected_text": corrected_text,
        "html_tables": html_tables,
        "entities": entities,
        "summary": summary_data,
        "graph_data": graph_data,
        "confidence": confidence,
        "created_at": now_iso
    }


class CropOCRRequest(BaseModel):
    doc_id: str
    box: List[int]  # [x1, y1, x2, y2] trên ảnh gốc
    field_name: Optional[str] = None

@app.post("/api/docfile/ocr-region")
async def ocr_cropped_region(req: CropOCRRequest):
    """
    Định nghĩa vùng OCR (Zone OCR): Người dùng kẻ khung trên ảnh -> Cắt đúng tọa độ đó đưa vào VietOCR đọc!
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT file_url, entities, custom_fields FROM documents WHERE id = ?", (req.doc_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")

    safe_name = row[0].replace("/files/", "")
    img_path = os.path.join(UPLOAD_DIR, safe_name)
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        raise HTTPException(status_code=400, detail="Không đọc được file ảnh gốc")

    h, w = img_bgr.shape[:2]
    x1, y1, x2, y2 = req.box
    x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
    y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))

    if x2 - x1 < 5 or y2 - y1 < 5:
        return {"text": "", "corrected_text": ""}

    crop = img_bgr[y1:y2, x1:x2]
    pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    raw_txt = ocr_predictor.predict(pil_crop)
    corr_txt = correct_text(raw_txt)

    # Nếu có tên trường (field_name), lưu luôn vào custom_extracted của tài liệu
    if req.field_name:
        entities = json.loads(row[1]) if row[1] else {}
        if "custom_extracted" not in entities:
            entities["custom_extracted"] = {}
        entities["custom_extracted"][req.field_name] = corr_txt
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE documents SET entities = ?, updated_at = ? WHERE id = ?",
                  (json.dumps(entities, ensure_ascii=False), datetime.now().isoformat(), req.doc_id))
        conn.commit()
        conn.close()

    return {
        "field_name": req.field_name,
        "box": [x1, y1, x2, y2],
        "raw_text": raw_txt,
        "corrected_text": corr_txt
    }


class UpdateDocRequest(BaseModel):
    corrected_text: str
    custom_extracted: Optional[Dict[str, Any]] = None
    folder_path: Optional[str] = None

@app.put("/api/docfile/documents/{doc_id}")
async def update_document_ocr(doc_id: str, req: UpdateDocRequest):
    """
    Sửa OCR trực tiếp (Human-in-the-loop) -> Tự động cập nhật lại Thực thể, Tóm tắt, Sơ đồ Graph
    và lưu mẫu vào kho Active Learning để train lại model sau này!
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT filename, entities, custom_fields, folder_path FROM documents WHERE id = ?", (doc_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")

    filename, entities_str, rules_str, current_folder = row
    rules = json.loads(rules_str) if rules_str else []
    old_entities = json.loads(entities_str) if entities_str else {}

    # Chạy lại bộ trích xuất & tóm tắt & đồ thị trên văn bản đã hiệu đính
    new_entities = extract_arkham_entities(req.corrected_text, custom_rules=rules)
    new_entities["lines"] = old_entities.get("lines", [])
    if req.custom_extracted:
        new_entities["custom_extracted"].update(req.custom_extracted)

    new_summary = generate_arkham_summary(req.corrected_text, new_entities)
    new_graph = build_arkham_graph(doc_id, filename, req.corrected_text, new_entities)
    new_folder = req.folder_path or current_folder

    c.execute("""
        UPDATE documents
        SET corrected_text = ?, entities = ?, summary = ?, graph_data = ?, folder_path = ?, updated_at = ?
        WHERE id = ?
    """, (
        req.corrected_text,
        json.dumps(new_entities, ensure_ascii=False),
        json.dumps(new_summary, ensure_ascii=False),
        json.dumps(new_graph, ensure_ascii=False),
        new_folder,
        datetime.now().isoformat(),
        doc_id
    ))
    conn.commit()
    conn.close()

    # Lưu log Active Learning
    feedback_log = os.path.join(FEEDBACK_DIR, "corrections_log.jsonl")
    with open(feedback_log, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "doc_id": doc_id,
            "filename": filename,
            "corrected_text": req.corrected_text,
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False) + "\n")

    return {
        "status": "updated",
        "entities": new_entities,
        "summary": new_summary,
        "graph_data": new_graph,
        "folder_path": new_folder
    }


@app.get("/api/docfile/documents")
async def list_documents(search: str = "", folder: str = ""):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM documents ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()

    docs = []
    for r in rows:
        d = dict(r)
        for json_col in ["quality_info", "html_tables", "entities", "custom_fields", "summary", "graph_data"]:
            try:
                d[json_col] = json.loads(d[json_col]) if d[json_col] else {}
            except Exception:
                d[json_col] = {}

        if folder and folder != "ALL" and d["folder_path"] != folder:
            continue
        if search:
            q = search.lower()
            haystack = f"{d['filename']} {d['corrected_text']} {json.dumps(d['entities'], ensure_ascii=False)}".lower()
            if q not in haystack:
                continue
        docs.append(d)

    return {"documents": docs, "total": len(docs)}


@app.delete("/api/docfile/documents/{doc_id}")
async def delete_document(doc_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "id": doc_id}


@app.get("/api/docfile/global-graph")
async def get_global_knowledge_graph():
    """
    Gộp toàn bộ Sơ đồ của tất cả văn bản trong hệ thống thành một Mạng lưới Tri thức Tổng thể (Global Arkham Graph)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, filename, graph_data, entities, summary FROM documents")
    rows = c.fetchall()
    conn.close()

    merged_nodes = {}
    merged_edges = []
    contradictions = []

    # Theo dõi số liệu/ngày tháng theo Số văn bản để phát hiện mâu thuẫn (Arkham Contradictions)
    doc_records = []

    for r in rows:
        g = json.loads(r["graph_data"]) if r["graph_data"] else {"nodes": [], "edges": []}
        ent = json.loads(r["entities"]) if r["entities"] else {}
        summ = json.loads(r["summary"]) if r["summary"] else {}

        doc_records.append({
            "id": r["id"],
            "filename": r["filename"],
            "so_van_ban": ent.get("so_van_ban"),
            "ngay_ban_hanh": ent.get("ngay_ban_hanh"),
            "money": ent.get("MONEY", []),
            "persons": ent.get("PERSON", []),
            "title": summ.get("title", r["filename"])
        })

        for n in g.get("nodes", []):
            nid = n["id"]
            if nid not in merged_nodes:
                merged_nodes[nid] = {**n, "doc_count": 1}
            else:
                merged_nodes[nid]["doc_count"] += 1
                merged_nodes[nid]["degree"] += n.get("degree", 1)

        for e in g.get("edges", []):
            merged_edges.append(e)

    # Kiểm tra mâu thuẫn cơ bản giữa các tài liệu cùng nhắc tới 1 Nhân sự hoặc trùng Số văn bản
    for i in range(len(doc_records)):
        for j in range(i + 1, len(doc_records)):
            d1, d2 = doc_records[i], doc_records[j]
            if d1["so_van_ban"] and d1["so_van_ban"] == d2["so_van_ban"]:
                if d1["ngay_ban_hanh"] != d2["ngay_ban_hanh"] or d1["money"] != d2["money"]:
                    contradictions.append({
                        "type": "Mâu thuẫn Số liệu / Ngày ký trên cùng Số văn bản",
                        "doc_a": d1["filename"],
                        "doc_b": d2["filename"],
                        "detail": f"Cùng số {d1['so_van_ban']} nhưng ngày/số tiền khác nhau ({d1['ngay_ban_hanh']} vs {d2['ngay_ban_hanh']})"
                    })

    return {
        "nodes": list(merged_nodes.values()),
        "edges": merged_edges,
        "contradictions": contradictions,
        "total_documents": len(rows)
    }


@app.get("/api/docfile/templates")
async def get_ocr_templates():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM ocr_templates ORDER BY created_at ASC")
    rows = c.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["fields"] = json.loads(d["fields_json"]) if d["fields_json"] else []
        res.append(d)
    return {"templates": res}


class CreateTemplateRequest(BaseModel):
    name: str
    description: str = ""
    fields: List[Dict[str, str]]

@app.post("/api/docfile/templates")
async def create_ocr_template(req: CreateTemplateRequest):
    tpl_id = f"tpl_{uuid.uuid4().hex[:8]}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO ocr_templates VALUES (?, ?, ?, ?, ?)", (
        tpl_id,
        req.name,
        req.description,
        json.dumps(req.fields, ensure_ascii=False),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()
    return {"id": tpl_id, "name": req.name, "fields": req.fields}


if __name__ == "__main__":
    print("🚀 DAU DocFile AI & Arkham Core Server đang chạy tại http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
