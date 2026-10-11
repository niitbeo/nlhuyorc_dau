import uvicorn
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
import sys
import os
import torch
import cv2
import numpy as np
from PIL import Image
import io

# Add vietocr path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg
from transformers import PreTrainedTokenizerFast, AutoModelForSeq2SeqLM

app = FastAPI(title="DAU-ERP AI Core API")

# --- 1. Load OCR Model (Quantized Int8 or FP32) ---
print("[INFO] Đang nạp mô hình OCR...")
config = Cfg.load_config_from_file('configs/vgg_transformer_base.yml')
config['device'] = 'cpu' # Deploy trên CPU sau khi ép cân, hoặc 'cuda:0' nếu muốn dùng GPU
config['weights'] = r'd:\orc\weights\handwriting_pro_quantized.pth' # Dùng bản ép cân cho nhẹ
config['dataset']['image_max_width'] = 2048
# Note: Để nạp bản quantized, ta cần định nghĩa lại model structure rồi load weights, 
# nhưng tạm thời Predictor của VietOCR tự build model gốc. 
# Do đó, để an toàn và nhanh nhất, ta cứ dùng bản gốc trên GPU cho API này.
config['device'] = 'cuda:0' if torch.cuda.is_available() else 'cpu'
config['weights'] = r'd:\orc\weights\handwriting_pro.pth'

ocr_predictor = Predictor(config)

# --- 2. Load ProtonX Corrector ---
print("[INFO] Đang nạp máy giặt chính tả ProtonX...")
protonx_tokenizer = PreTrainedTokenizerFast.from_pretrained("protonx-models/protonx-legal-tc")
protonx_model = AutoModelForSeq2SeqLM.from_pretrained("protonx-models/protonx-legal-tc")

def correct_text(text):
    input_ids = protonx_tokenizer(text, return_tensors="pt").input_ids
    outputs = protonx_model.generate(input_ids, max_length=256)
    return protonx_tokenizer.decode(outputs[0], skip_special_tokens=True)

# --- 3. Endpoints ---
class OCRResponse(BaseModel):
    raw_text: str
    corrected_text: str

@app.post("/ocr/image", response_model=OCRResponse)
async def process_image(file: UploadFile = File(...)):
    # Đọc ảnh
    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert('RGB')
    
    # OCR
    raw_text = ocr_predictor.predict(image)
    
    # Hiệu đính
    corrected = raw_text
    try:
        if raw_text.strip():
            corrected = correct_text(raw_text)
    except:
        pass
        
    return OCRResponse(raw_text=raw_text, corrected_text=corrected)

if __name__ == "__main__":
    print("🚀 DAU-ERP AI Core API đang chạy tại http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
