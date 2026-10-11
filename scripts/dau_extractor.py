import re
import json

class DAUDocumentExtractor:
    """
    Bộ bóc tách thông tin (Extractor) chuyên dụng cho văn bản hành chính 
    và tài liệu nội bộ của Đại học Kiến Trúc Đà Nẵng (DAU).
    Chiến thuật 3 Lớp: Regex -> PhoBERT -> LLM
    """
    
    def __init__(self, use_phobert=False):
        self.use_phobert = use_phobert
        self.nlp = None
        
        # Chỉ load PhoBERT (Transformers) nếu được yêu cầu để tránh nặng máy
        if self.use_phobert:
            print("[INFO] Đang tải mô hình NER Tiếng Việt (PhoBERT/Electra)...")
            try:
                from transformers import pipeline
                # Dùng mô hình NER Tiếng Việt đã được train sẵn
                self.nlp = pipeline("ner", model="NlpHUST/ner-vietnamese-electra-base", aggregation_strategy="simple")
            except ImportError:
                print("[WARN] Chưa cài đặt transformers. Chạy: pip install transformers torch")
                self.nlp = None

    def layer1_regex_extract(self, text: str):
        """LỚP 1: Bóc tách bằng Regex (Tốc độ ánh sáng, chính xác 100%)"""
        result = {
            "so_van_ban": None,
            "ngay_ky": None,
            "loai_van_ban": None
        }
        
        # 1. Tìm Số văn bản (VD: Số: 123/QĐ-ĐHKT, Số: 45/TB-BGDĐT)
        so_match = re.search(r'Số:\s*([0-9]+/[A-ZĐ]+-[A-ZĐ]+)', text)
        if so_match:
            result["so_van_ban"] = so_match.group(1)
            
        # 2. Tìm Ngày tháng năm (VD: Đà Nẵng, ngày 15 tháng 08 năm 2026)
        ngay_match = re.search(r'ngày\s+([0-9]{1,2})\s+tháng\s+([0-9]{1,2})\s+năm\s+([0-9]{4})', text)
        if ngay_match:
            result["ngay_ky"] = f"{ngay_match.group(1)}/{ngay_match.group(2)}/{ngay_match.group(3)}"
            
        # 3. Phân loại cơ bản qua Tiêu đề (Quyết định, Thông báo, Tờ trình)
        if "QUYẾT ĐỊNH" in text.upper():
            result["loai_van_ban"] = "Quyết Định"
        elif "THÔNG BÁO" in text.upper():
            result["loai_van_ban"] = "Thông Báo"
        elif "TỜ TRÌNH" in text.upper():
            result["loai_van_ban"] = "Tờ Trình"
            
        return result

    def layer2_phobert_ner(self, text: str):
        """LỚP 2: Bóc tách Tên người, Địa điểm, Tổ chức bằng PhoBERT (Zero-cost NLP)"""
        if not self.nlp:
            return "PhoBERT NER chưa được bật hoặc chưa cài thư viện."
            
        # Chạy NER pipeline
        ner_results = self.nlp(text[:2000]) # Giới hạn độ dài để chạy nhanh
        
        entities = {"PERSON": [], "ORGANIZATION": [], "LOCATION": []}
        for ent in ner_results:
            group = ent['entity_group']
            word = ent['word']
            if group == 'PER':
                entities["PERSON"].append(word)
            elif group == 'ORG':
                entities["ORGANIZATION"].append(word)
            elif group == 'LOC':
                entities["LOCATION"].append(word)
                
        # Lọc trùng lặp
        for k in entities:
            entities[k] = list(set(entities[k]))
            
        return entities

    def layer3_llm_json_prompt(self, text: str):
        """LỚP 3: Tạo Prompt ép khuôn JSON cho Qwen-2.5-3B (Ollama)"""
        
        prompt = f"""Bạn là một Trợ lý AI chuyên phân tích văn bản hành chính của Đại học Kiến Trúc Đà Nẵng.
Nhiệm vụ của bạn là đọc văn bản dưới đây và trích xuất thông tin dưới dạng JSON bắt buộc.

VĂN BẢN:
---
{text[:1500]}... (đã cắt ngắn)
---

YÊU CẦU ĐẦU RA BẮT BUỘC (Chỉ xuất JSON, không giải thích):
{{
  "tom_tat_noi_dung": "Tóm tắt văn bản trong 2 câu",
  "ten_sinh_vien_lien_quan": ["Tên 1", "Tên 2"],
  "han_hanh_dong": "Hạn chót nếu có, không có thì ghi null",
  "phong_ban_chiu_trach_nhiem": "Tên phòng ban"
}}"""
        return prompt

if __name__ == "__main__":
    # Test thử với một đoạn OCR giả lập
    sample_ocr_text = '''
    BỘ GIÁO DỤC VÀ ĐÀO TẠO
    TRƯỜNG ĐẠI HỌC KIẾN TRÚC ĐÀ NẴNG
    Số: 1950/QĐ-ĐHKT
    
    CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
    Độc lập - Tự do - Hạnh phúc
    
    Đà Nẵng, ngày 08 tháng 10 năm 2026
    
    QUYẾT ĐỊNH
    Về việc khen thưởng sinh viên Nguyễn Văn A, mã SV 123456 thuộc khoa Công nghệ Thông tin
    đã có thành tích xuất sắc trong kỳ thi Olympic Tin học toàn quốc.
    
    HIỆU TRƯỞNG TRƯỜNG ĐẠI HỌC KIẾN TRÚC ĐÀ NẴNG
    Giao cho Phòng Công tác Sinh viên chịu trách nhiệm thi hành quyết định này.
    '''
    
    extractor = DAUDocumentExtractor(use_phobert=False)
    
    print("="*50)
    print("🚀 TEST BỘ BÓC TÁCH VĂN BẢN ĐẠI HỌC (DAU-ERP)")
    print("="*50)
    
    print("\n[LAYER 1] KẾT QUẢ REGEX (Tốc độ < 0.01s):")
    regex_res = extractor.layer1_regex_extract(sample_ocr_text)
    print(json.dumps(regex_res, ensure_ascii=False, indent=2))
    
    print("\n[LAYER 2] KẾT QUẢ PhoBERT NER:")
    print("Đang tắt để tiết kiệm RAM. Sẽ bật khi tích hợp vào ArkhamMirror.")
    
    print("\n[LAYER 3] LỆNH GỬI CHO QWEN-2.5-3B (Ollama):")
    print(extractor.layer3_llm_json_prompt(sample_ocr_text))
