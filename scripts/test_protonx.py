import sys

def test_correction():
    print("==================================================")
    print("🚀 DEMO LÕI HIỆU ĐÍNH - PROTONX LEGAL TC")
    print("==================================================")
    
    from transformers import PreTrainedTokenizerFast, AutoModelForSeq2SeqLM
    
    try:
        # Mô hình này không có file spiece.model mà dùng tokenizer.json, nên ta phải gọi Fast Tokenizer
        tokenizer = PreTrainedTokenizerFast.from_pretrained("protonx-models/protonx-legal-tc")
        # T5 Model
        model = AutoModelForSeq2SeqLM.from_pretrained("protonx-models/protonx-legal-tc")
    except Exception as e:
        print(f"Lỗi tải mô hình: {e}")
        return

    # Giả lập kết quả OCR bị sai dấu, sai chính tả do ảnh mờ
    bad_ocr = "Théo quyét đinh số 123 cùa Giám đõc sở Gíao dục, bổ nhlệm ông Nguễn Vặn A làq trưỡng pgòng."
    print(f"\n[❌] KẾT QUẢ OCR BỊ LỖI (Input):")
    print(f"    '{bad_ocr}'")
    
    # Chạy mô hình sửa lỗi
    print("\n[INFO] Đang đưa vào máy giặt (ProtonX TC) để sửa chính tả...")
    # T5 thường cần thêm prefix tùy cách huấn luyện, nhưng ta cứ thử raw text trước
    input_ids = tokenizer(bad_ocr, return_tensors="pt").input_ids
    outputs = model.generate(input_ids, max_length=128)
    good_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    print(f"\n[✅] KẾT QUẢ ĐÃ SỬA LỖI (Output):")
    print(f"    '{good_text}'\n")

if __name__ == "__main__":
    test_correction()
