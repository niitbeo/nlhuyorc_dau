import os
import sys
import torch
import cv2
import numpy as np
from PIL import Image
import io
import uvicorn
from fastapi import FastAPI, UploadFile, File
from bs4 import BeautifulSoup
from paddleocr import PPStructureV3

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg

app = FastAPI(title="DAU-ERP Table OCR API")

print('[INFO] Init VietOCR (Handwriting/Printed)...')
config = Cfg.load_config_from_file('configs/vgg_transformer_base.yml')
config['device'] = 'cuda:0' if torch.cuda.is_available() else 'cpu'
config['weights'] = r'd:\orc\weights\handwriting_pro.pth'
config['dataset']['image_max_width'] = 2048
vietocr_model = Predictor(config)

print('[INFO] Init PPStructureV3 (PaddleX)...')
# We only need table recognition and basic OCR
table_engine = PPStructureV3(
    use_table_recognition=True,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False
)

@app.post("/ocr/table")
async def process_table(file: UploadFile = File(...)):
    contents = await file.read()
    # Read image via cv2
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # 1. Run PPStructureV3 to get layout and tables
    res_list = list(table_engine.predict(img))
    
    final_htmls = []
    
    # Iterate through regions (tables, text blocks)
    for res in res_list:
        # PaddleX returns objects that have .keys() if cast to dict
        res_dict = dict(res)
        
        # In PaddleX, table results usually have 'html' or 'table_html'
        # Let's search for HTML field
        html_str = res_dict.get('html', res_dict.get('table_html', ''))
        cell_bboxes = res_dict.get('cell_bboxes', res_dict.get('table_cell_bboxes', []))
        
        if html_str and len(cell_bboxes) > 0:
            print(f"[INFO] Found table with {len(cell_bboxes)} cells.")
            # Crop cells and run VietOCR
            cell_texts = []
            for box in cell_bboxes:
                if len(box) == 4:
                    x1, y1, x2, y2 = [int(v) for v in box]
                else:
                    x1 = int(min([p[0] for p in box]))
                    y1 = int(min([p[1] for p in box]))
                    x2 = int(max([p[0] for p in box]))
                    y2 = int(max([p[1] for p in box]))
                
                cell_img = img[y1:y2, x1:x2]
                if cell_img.size == 0 or cell_img.shape[0] < 5 or cell_img.shape[1] < 5:
                    cell_texts.append("")
                    continue
                    
                cell_pil = Image.fromarray(cv2.cvtColor(cell_img, cv2.COLOR_BGR2RGB))
                text = vietocr_model.predict(cell_pil)
                cell_texts.append(text)
                
            # Substitute texts back into HTML
            soup = BeautifulSoup(html_str, 'html.parser')
            tds = soup.find_all(['td', 'th'])
            for idx, td in enumerate(tds):
                if idx < len(cell_texts):
                    td.string = cell_texts[idx]
                    
            final_htmls.append(str(soup))
            
    if not final_htmls:
        return {"status": "success", "message": "No tables detected", "htmls": []}
        
    return {"status": "success", "message": "Tables extracted", "htmls": final_htmls}

if __name__ == "__main__":
    print("[INFO] Table OCR API running on http://0.0.0.0:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
