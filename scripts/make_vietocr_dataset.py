import os
import glob
import fitz  # PyMuPDF
import cv2
import numpy as np
from pathlib import Path
from tqdm import tqdm
import unicodedata
import random

def normalize_text(text):
    # Normalize unicode strings to handle weird encoding issues
    return unicodedata.normalize('NFC', text.strip())

def make_dataset(pdf_dir, out_dir, split_ratio=0.9):
    # Create directories
    train_dir = os.path.join(out_dir, "train")
    val_dir = os.path.join(out_dir, "val")
    os.makedirs(train_dir, exist_ok=True)
    os.makedirs(val_dir, exist_ok=True)
    
    train_labels = []
    val_labels = []
    
    pdf_files = list(Path(pdf_dir).rglob("*.pdf"))
    
    # We only want to use digital PDFs with valid text.
    # In stage 1 we saw some bad text like "Di~u 8.". We can filter based on weird characters.
    def is_valid_label(text):
        if not text:
            return False
        # If it has weird characters like '~' inside words
        if '~' in text:
            return False
        if len(text) < 2:
            return False
        return True

    sample_id = 0
    for pdf_path in tqdm(pdf_files, desc="Processing PDFs"):
        doc = fitz.open(pdf_path)
        
        # Check if digital by looking at the first page
        if len(doc) == 0:
            continue
        first_page = doc[0]
        text = first_page.get_text("text").strip()
        if not text:
            # Likely scanned, skip for automatic text extraction
            continue
            
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render page to image (scale up for better quality)
            zoom_x = 2.0  # horizontal zoom
            zoom_y = 2.0  # vertical zoom
            mat = fitz.Matrix(zoom_x, zoom_y)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert to numpy array (BGR)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            
            # Get text blocks
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)["blocks"]
            for b in blocks:
                if "lines" in b:
                    for line in b["lines"]:
                        for span in line["spans"]:
                            text = normalize_text(span["text"])
                            if is_valid_label(text):
                                bbox = span["bbox"] # (x0, y0, x1, y1)
                                # Apply zoom
                                x0, y0, x1, y1 = [int(v * zoom_x) for v in bbox]
                                # Add padding
                                pad = 2
                                x0 = max(0, x0 - pad)
                                y0 = max(0, y0 - pad)
                                x1 = min(img.shape[1], x1 + pad)
                                y1 = min(img.shape[0], y1 + pad)
                                
                                if y1 <= y0 or x1 <= x0:
                                    continue
                                
                                crop = img[y0:y1, x0:x1]
                                
                                # Decide train/val split
                                is_train = random.random() < split_ratio
                                split_dir = train_dir if is_train else val_dir
                                labels_list = train_labels if is_train else val_labels
                                
                                filename = f"img_{sample_id:06d}.jpg"
                                filepath = os.path.join(split_dir, filename)
                                
                                cv2.imwrite(filepath, crop)
                                labels_list.append(f"{filename}\t{text}")
                                sample_id += 1

    # Write labels.txt
    with open(os.path.join(train_dir, "labels.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(train_labels))
        
    with open(os.path.join(val_dir, "labels.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(val_labels))
        
    print(f"Dataset created: {len(train_labels)} train, {len(val_labels)} val samples.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf_dir", type=str, default=r"d:\orc\DAU-ISO-20261009T040003Z-1-001")
    parser.add_argument("--out_dir", type=str, default=r"d:\orc\data")
    args = parser.parse_args()
    
    make_dataset(args.pdf_dir, args.out_dir)
