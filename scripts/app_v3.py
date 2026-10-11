import gradio as gr
import cv2
import numpy as np
import time
import os
import subprocess
import json
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import sys
from docreconstruct.reconstruction.hybrid_job import run_hybrid_job
from pathlib import Path
import torch
import torch.nn as nn
from torchvision import models, transforms

# Thêm đường dẫn tới thư viện nhận dạng OCR.
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg
from transformers import PreTrainedTokenizerFast, AutoModelForSeq2SeqLM

# Global predictor & corrector
predictor = None
protonx_tokenizer = None
protonx_model = None

def get_corrector():
    global protonx_tokenizer, protonx_model
    if protonx_model is None:
        print("[INFO] Đang tải mô hình ProtonX Legal TC...")
        protonx_tokenizer = PreTrainedTokenizerFast.from_pretrained("protonx-models/protonx-legal-tc")
        protonx_model = AutoModelForSeq2SeqLM.from_pretrained("protonx-models/protonx-legal-tc")
    return protonx_tokenizer, protonx_model

def correct_text(text):
    tokenizer, model = get_corrector()
    input_ids = tokenizer(text, return_tensors="pt").input_ids
    outputs = model.generate(input_ids, max_length=256)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


# --- 2-STREAM ROUTING ARCHITECTURE ---
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def get_classifier():
    model = models.resnet18(weights=None)
    num_ftrs = model.fc.in_features
    # 2 classes: handwritten, printed
    model.fc = nn.Linear(num_ftrs, 2)
    model.load_state_dict(torch.load(r'd:\orc\weights\text_classifier.pth', map_location=device))
    model = model.to(device)
    model.eval()
    
    transform = transforms.Compose([
        transforms.Resize((64, 256)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    return model, transform

def get_ocr_model(model_type="printed"):
    config = Cfg.load_config_from_file('configs/vgg_transformer_base.yml')
    config['device'] = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    
    if model_type == "printed":
        config['weights'] = r'd:\orc\weights\transformerocr_finetuned.pth'
    else:
        config['weights'] = r'd:\orc\weights\handwriting_pro.pth'
        config['dataset']['image_max_width'] = 2048
        
    predictor = Predictor(config)
    return predictor

def load_model(weight_path):
    global predictor
    config = Cfg.load_config_from_name('vgg_transformer')
    config['weights'] = weight_path
    config['cnn']['pretrained'] = False
    config['device'] = 'cuda:0'
    config['predictor']['beamsearch'] = False
    predictor = Predictor(config)

def get_boxes_from_paddle(img_path):
    cmd = [
        r"d:\orc\.venv\Scripts\python.exe",
        r"d:\orc\scripts\detect_boxes.py",
        "--image", img_path,
        "--output", img_path + ".json"
    ]
    subprocess.run(cmd, check=True)
    with open(img_path + ".json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data:
        return data["data"][0].get("dt_polys", [])
    return data

def get_crop(img, box):
    pts = np.array(box, dtype="float32")
    rect = cv2.boundingRect(pts)
    x, y, w, h = rect
    crop = img[y:y+h, x:x+w].copy()
    pts = pts - pts.min(axis=0)
    mask = np.zeros(crop.shape[:2], np.uint8)
    cv2.drawContours(mask, [pts.astype(int)], -1, (255, 255, 255), -1, cv2.LINE_AA)
    dst = cv2.bitwise_and(crop, crop, mask=mask)
    bg = np.ones_like(crop, np.uint8) * 255
    cv2.bitwise_not(bg, bg, mask=mask)
    dst2 = bg + dst
    
    # Perspective transform if rotated (simple approach)
    width = int(max(np.linalg.norm(pts[0]-pts[1]), np.linalg.norm(pts[2]-pts[3])))
    height = int(max(np.linalg.norm(pts[0]-pts[3]), np.linalg.norm(pts[1]-pts[2])))
    src_pts = pts.astype("float32")
    dst_pts = np.array([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]], dtype="float32")
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(dst2, M, (width, height))
    return warped

def group_rows(boxes, texts):
    # Dựa theo y_center để gom dòng
    lines = []
    threshold = 10
    
    for box, text in zip(boxes, texts):
        pts = np.array(box)
        y_center = np.mean(pts[:, 1])
        x_min = np.min(pts[:, 0])
        
        added = False
        for line in lines:
            if abs(line['y'] - y_center) < threshold:
                line['items'].append({'x': x_min, 'text': text})
                # Cập nhật lại y_center trung bình
                line['y'] = (line['y'] * line['count'] + y_center) / (line['count'] + 1)
                line['count'] += 1
                added = True
                break
        if not added:
            lines.append({'y': y_center, 'count': 1, 'items': [{'x': x_min, 'text': text}]})
    
    lines.sort(key=lambda x: x['y'])
    full_text = ""
    for line in lines:
        line['items'].sort(key=lambda x: x['x'])
        full_text += "  ".join([item['text'] for item in line['items']]) + "\n"
    return full_text

import difflib

import math
from collections import Counter

def calculate_similarity(text1, text2):
    import re
    t1 = re.sub(r'--- TRANG \d+ ---', '', text1)
    t2 = re.sub(r'--- TRANG \d+ ---', '', text2)
    
    words1 = re.findall(r'\w+', t1.lower())
    words2 = re.findall(r'\w+', t2.lower())
    
    vec1 = Counter(words1)
    vec2 = Counter(words2)
    
    intersection = set(vec1.keys()) & set(vec2.keys())
    numerator = sum([vec1[x] * vec2[x] for x in intersection])
    
    sum1 = sum([vec1[x]**2 for x in vec1.keys()])
    sum2 = sum([vec2[x]**2 for x in vec2.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)
    
    if not denominator: return 0.0
    return (float(numerator) / denominator) * 100

def process_document(file_obj, use_finetuned, compare_gemini, api_key):
    path = file_obj.name
    images = []
    
    if path.lower().endswith('.pdf'):
        doc = fitz.open(path)
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            images.append(img)
    else:
        images.append(cv2.imread(path))
        
    all_vis_imgs = []
    all_full_text = ""
    all_evidence_pages = []
    total_det_time = 0
    total_rec_time = 0
    total_boxes = 0
    
    for page_idx, img in enumerate(images):
        temp_path = f"temp_ocr_{page_idx}.jpg"
        cv2.imwrite(temp_path, img)
        
        t0 = time.time()
        boxes = get_boxes_from_paddle(temp_path)
        t_det = time.time() - t0
        total_det_time += t_det
        
        t1 = time.time()
        texts = []
        vis_img = img.copy()
        
        vis_img_pil = Image.fromarray(cv2.cvtColor(vis_img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(vis_img_pil)
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()
            
        pil_crops = []
        for box in boxes:
            crop = get_crop(img, box)
            pil_crops.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            
        print("Classifying crops...")
        classifier, clf_transform = get_classifier()
        labels = []
        with torch.no_grad():
            for pil_crop in pil_crops:
                tensor_crop = clf_transform(pil_crop).unsqueeze(0).to(device)
                outputs = classifier(tensor_crop)
                _, preds = torch.max(outputs, 1)
                labels.append("printed" if preds.item() == 1 else "handwritten")
                
        del classifier
        torch.cuda.empty_cache()
        
        print("Reading printed text...")
        printed_predictor = get_ocr_model("printed")
        texts = [""] * len(boxes)
        for i, (pil_crop, label) in enumerate(zip(pil_crops, labels)):
            if label == "printed":
                texts[i] = printed_predictor.predict(pil_crop)
        del printed_predictor
        torch.cuda.empty_cache()
        
        print("Reading handwritten text...")
        hw_predictor = get_ocr_model("handwritten")
        for i, (pil_crop, label) in enumerate(zip(pil_crops, labels)):
            if label == "handwritten":
                texts[i] = hw_predictor.predict(pil_crop)
        del hw_predictor
        torch.cuda.empty_cache()
        
        print("Bắt đầu hiệu đính chính tả (ProtonX)...")
        for i in range(len(texts)):
            if texts[i].strip():
                try:
                    texts[i] = correct_text(texts[i])
                except:
                    pass
        
        for i, box in enumerate(boxes):
            text = texts[i]
            label = labels[i]
            pts = [(int(p[0]), int(p[1])) for p in box]
            pts_closed = pts + [pts[0]]
            
            color = (255, 0, 0) if label == "printed" else (0, 255, 0)
            draw.line(pts_closed, fill=color, width=2)
            
            text_x, text_y = pts[0][0], pts[0][1] - 25
            try:
                bbox = draw.textbbox((text_x, text_y), text, font=font)
                draw.rectangle([bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2], fill=(255, 255, 255, 180))
            except:
                pass
            draw.text((text_x, text_y), text, font=font, fill=(0, 0, 255))
            
        t_rec = time.time() - t1
        total_rec_time += t_rec
        total_boxes += len(boxes)
        
        vis_img = np.array(vis_img_pil)
        all_vis_imgs.append(vis_img)
        
        
        all_evidence_pages.append({
            "dt_polys": boxes,
            "rec_texts": texts
        })
        
        page_text = group_rows(boxes, texts)
        if len(images) > 1:
            all_full_text += f"--- TRANG {page_idx+1} ---\n"
        all_full_text += f"{page_text}\n\n"
        
    stats = f"Tổng số trang xử lý: {len(images)}\n"
    stats += f"Phát hiện chữ (PaddleOCR): {total_det_time:.2f}s\n"
    stats += f"Nhận diện chữ (NLHUYOCR): {total_rec_time:.2f}s\n"
    stats += f"Tổng thời gian: {total_det_time + total_rec_time:.2f}s\n"
    stats += f"Tổng số dòng phát hiện: {total_boxes}"
    
    # Write content.md and evidence.json
    with open('content.md', 'w', encoding='utf-8') as f:
        f.write(all_full_text)
    
    evidence_json = {"data": all_evidence_pages}
    with open('evidence.json', 'w', encoding='utf-8') as f:
        json.dump(evidence_json, f)
        
    out_docx_path = "output.docx"
    try:
        job = run_hybrid_job(
            Path("content.md"),
            Path(path),
            evidence=Path("evidence.json"),
            evidence_provider_hints="paddleocr",
            strict_evidence=False,
            output=Path(out_docx_path),
            allow_remote_assets=False,
            online_ocr=None
        )
    except Exception as e:
        print(f"DocReconstruct failed: {e}")
        out_docx_path = None
        stats += f"\\nLỗi tạo Word: {e}"
    
    gemini_text = "Chưa bật chế độ So sánh với Google Gemini."
    
    if compare_gemini and api_key:
        import google.generativeai as genai
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name="gemini-3.8-flash")
            
            # Send all pages to Gemini
            content_payload = ["Extract all the text from this document (which may have multiple pages) exactly as it is written. Do not add any markdown formatting, explanations, or comments. Just the raw text. Keep the order of the pages."]
            
            for idx, img_arr in enumerate(images):
                temp_path = f"temp_gemini_upload_{idx}.jpg"
                cv2.imwrite(temp_path, img_arr)
                pil_img = Image.open(temp_path)
                content_payload.append(pil_img)
            
            t0 = time.time()
            response = model.generate_content(content_payload)
            t1 = time.time()
            
            gemini_text = response.text.strip()
            similarity = calculate_similarity(all_full_text, gemini_text)
            
            stats += f"\n\n--- BENCHMARK ---"
            stats += f"\nThời gian API Gemini: {t1-t0:.2f}s"
            stats += f"\nĐộ tương đồng (Local vs Gemini): {similarity:.2f}%"
        except Exception as e:
            gemini_text = f"Lỗi gọi Gemini API: {str(e)}"
    
    return all_vis_imgs, all_full_text, gemini_text, stats, out_docx_path

import os

saved_api_key = os.getenv("GEMINI_API_KEY", "")

with gr.Blocks(title="NLHUYOCR · Nhận dạng tiếng Việt") as demo:
    gr.Markdown("# NLHUYOCR · Đánh giá tốc độ và độ chính xác")
    
    with gr.Row():
        file_input = gr.File(label="Tải lên PDF hoặc Ảnh (JPG/PNG)")
        use_finetuned = gr.Checkbox(label="Sử dụng model Fine-tuned (nếu có)", value=True)
        
    with gr.Row():
        compare_gemini = gr.Checkbox(label="So sánh với Google Gemini API (Tốn phí, lưu ý)", value=False)
        api_key_input = gr.Textbox(label="Gemini API Key (Chỉ dùng khi bật So sánh)", type="password", value=saved_api_key)

    btn = gr.Button("Bắt đầu xử lý OCR")
    
    with gr.Row():
        img_output = gr.Gallery(label="Ảnh kết quả (Vẽ khung bouding box)", columns=1)
        with gr.Column():
            text_output = gr.Textbox(label="Văn bản bóc tách", lines=15)
            gemini_output = gr.Textbox(label="Văn bản từ Google Gemini", lines=15)
            stats_output = gr.Textbox(label="Thông số hiệu năng (Thời gian, Số dòng, Metric)")
            docx_output = gr.File(label="Tải xuống Word (DOCX)")
            
    btn.click(fn=process_document, inputs=[file_input, use_finetuned, compare_gemini, api_key_input], outputs=[img_output, text_output, gemini_output, stats_output, docx_output])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7862, inbrowser=True)
