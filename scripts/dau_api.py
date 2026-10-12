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
from bs4 import BeautifulSoup

# Fix Paddle oneDNN CPU issues on Windows
os.environ["FLAGS_use_mkldnn"] = "False"

# Add vietocr path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg
from transformers import PreTrainedTokenizerFast, AutoModelForSeq2SeqLM

app = FastAPI(title="DAU-ERP AI Core API (Text & Table)")

# --- 1. Load OCR Model (VietOCR) ---
print("[INFO] Đang nạp mô hình VietOCR (Handwriting/Printed)...")
config = Cfg.load_config_from_file('configs/vgg_transformer_base.yml')
config['device'] = 'cuda:0' if torch.cuda.is_available() else 'cpu'
config['weights'] = r'd:\orc\weights\handwriting_pro.pth'
config['dataset']['image_max_width'] = 2048
ocr_predictor = Predictor(config)

# --- 2. Load Table Engine (PP-Structure) ---
print("[INFO] Đang nạp mô hình Table OCR (PaddleX)...")
try:
    from paddleocr import PPStructureV3
    table_engine = PPStructureV3(
        use_table_recognition=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False
    )
except ImportError:
    print("[WARN] Chưa cài đặt paddlex[ocr]. Endpoint /ocr/table sẽ không hoạt động.")
    table_engine = None

# --- 3. Load ProtonX Corrector ---
print("[INFO] Đang nạp máy sửa lỗi chính tả ProtonX...")
try:
    protonx_tokenizer = PreTrainedTokenizerFast.from_pretrained("protonx-models/protonx-legal-tc")
    protonx_model = AutoModelForSeq2SeqLM.from_pretrained("protonx-models/protonx-legal-tc")
except Exception as e:
    print(f"[WARN] Lỗi nạp mô hình chính tả: {e}")
    protonx_tokenizer = None
    protonx_model = None

def correct_text(text):
    if not protonx_model or not text.strip():
        return text
    input_ids = protonx_tokenizer(text, return_tensors="pt").input_ids
    outputs = protonx_model.generate(input_ids, max_length=256)
    return protonx_tokenizer.decode(outputs[0], skip_special_tokens=True)

# --- 4. Endpoints ---
class OCRResponse(BaseModel):
    raw_text: str
    corrected_text: str

@app.post("/ocr/image", response_model=OCRResponse)
async def process_image(file: UploadFile = File(...)):
    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert('RGB')
    
    # Text OCR
    raw_text = ocr_predictor.predict(image)
    corrected = raw_text
    
    try:
        corrected = correct_text(raw_text)
    except:
        pass
        
    return OCRResponse(raw_text=raw_text, corrected_text=corrected)


@app.post("/ocr/table")
async def process_table(file: UploadFile = File(...)):
    if not table_engine:
        return {"status": "error", "message": "Table Engine chưa được cài đặt (cần paddlex[ocr])"}
        
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Chạy PPStructure để lấy lưới (layout)
    res_list = list(table_engine.predict(img))
    final_htmls = []
    
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
                
                cell_img = img[max(0, y1):y2, max(0, x1):x2]
                if cell_img.size == 0 or cell_img.shape[0] < 5 or cell_img.shape[1] < 5:
                    cell_texts.append("")
                    continue
                    
                # Chuyển từng ô nhỏ cho VietOCR đọc
                cell_pil = Image.fromarray(cv2.cvtColor(cell_img, cv2.COLOR_BGR2RGB))
                text = ocr_predictor.predict(cell_pil)
                cell_texts.append(text)
                
            # Gắn chữ vào thẻ HTML
            soup = BeautifulSoup(html_str, 'html.parser')
            tds = soup.find_all(['td', 'th'])
            for idx, td in enumerate(tds):
                if idx < len(cell_texts):
                    td.string = cell_texts[idx]
                    
            final_htmls.append(str(soup))
            
    if not final_htmls:
        return {"status": "success", "message": "Không tìm thấy bảng nào", "htmls": []}
        
    return {"status": "success", "message": "Đã bóc bảng thành công", "htmls": final_htmls}

if __name__ == "__main__":
    print("🚀 DAU-ERP AI Core API đang chạy tại http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
