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

# Thêm đường dẫn để import vietocr
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg

# Global predictor
predictor = None

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

def process_document(file_obj, use_finetuned):
    global predictor
    if predictor is None:
        if use_finetuned and os.path.exists('weights/transformerocr_finetuned.pth'):
            load_model('weights/transformerocr_finetuned.pth')
        else:
            load_model('https://vocr.vn/data/vietocr/vgg_transformer.pth')
            
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
            
        for box in boxes:
            crop = get_crop(img, box)
            pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            text = predictor.predict(pil_crop)
            texts.append(text)
            
            # Draw box
            pts = [(int(p[0]), int(p[1])) for p in box]
            pts_closed = pts + [pts[0]]
            draw.line(pts_closed, fill=(255, 0, 0), width=2)
            
            # Draw text
            text_x, text_y = pts[0][0], pts[0][1] - 25
            try:
                bbox = draw.textbbox((text_x, text_y), text, font=font)
                # Expand background slightly
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
    stats += f"Nhận diện chữ (VietOCR): {total_rec_time:.2f}s\n"
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
    
    return all_vis_imgs, all_full_text, stats, out_docx_path

with gr.Blocks(title="Bộ OCR Bộ Giáo Dục - VietOCR Finetuned") as demo:
    gr.Markdown("# Hệ thống OCR phân rã PDF - Đánh giá tốc độ và độ chính xác")
    
    with gr.Row():
        file_input = gr.File(label="Tải lên PDF hoặc Ảnh (JPG/PNG)")
        use_finetuned = gr.Checkbox(label="Sử dụng model Fine-tuned (nếu có)", value=True)
        
    btn = gr.Button("Bắt đầu xử lý OCR")
    
    with gr.Row():
        # Dùng Gallery để hiển thị nhiều ảnh nếu PDF có nhiều trang
        img_output = gr.Gallery(label="Ảnh kết quả (Vẽ khung bouding box)", columns=1)
        with gr.Column():
            text_output = gr.Textbox(label="Văn bản bóc tách", lines=20)
            stats_output = gr.Textbox(label="Thông số hiệu năng (Thời gian, Số dòng)")
            docx_output = gr.File(label="Tải xuống Word (DOCX)")
            
    btn.click(fn=process_document, inputs=[file_input, use_finetuned], outputs=[img_output, text_output, stats_output, docx_output])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
