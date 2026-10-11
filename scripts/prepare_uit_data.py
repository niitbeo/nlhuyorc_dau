import os
import json
import shutil
import random

def convert_uit_dataset():
    base_dir = r"d:\orc\UIT-HWDB-line\UIT_HWDB_line\UIT_HWDB_line"
    out_img_dir = r"d:\orc\uit_images"
    os.makedirs(out_img_dir, exist_ok=True)
    
    all_lines = []
    
    # Process both train_data and test_data
    for split in ["train_data", "test_data"]:
        split_dir = os.path.join(base_dir, split)
        if not os.path.exists(split_dir):
            continue
            
        for folder in os.listdir(split_dir):
            folder_path = os.path.join(split_dir, folder)
            if not os.path.isdir(folder_path):
                continue
                
            label_file = os.path.join(folder_path, "label.json")
            if not os.path.exists(label_file):
                continue
                
            with open(label_file, 'r', encoding='utf-8') as f:
                try:
                    labels = json.load(f)
                except:
                    continue
                    
            for img_name, text in labels.items():
                src_img = os.path.join(folder_path, img_name)
                if not os.path.exists(src_img):
                    continue
                
                # New unique name
                new_img_name = f"uit_{split}_{folder}_{img_name}"
                dst_img = os.path.join(out_img_dir, new_img_name)
                
                # Copy image
                shutil.copy(src_img, dst_img)
                
                # Add to dataset lines
                all_lines.append(f"{dst_img}\t{text}")

    print(f"Extracted {len(all_lines)} images from UIT-HWDB-line.")
    
    # Read cinnamon labels
    print("Reading Cinnamon labels...")
    cinnamon_train = []
    with open(r"D:\orc\vn_handwritten_images\vn_handwritten_images\train_labels.txt", "r", encoding="utf-8") as f:
        cinnamon_train = f.read().splitlines()
        
    cinnamon_val = []
    with open(r"D:\orc\vn_handwritten_images\vn_handwritten_images\val_labels.txt", "r", encoding="utf-8") as f:
        cinnamon_val = f.read().splitlines()
        
    print(f"Loaded {len(cinnamon_train) + len(cinnamon_val)} from Cinnamon.")
    
    # Combine everything
    combined = all_lines + cinnamon_train + cinnamon_val
    random.shuffle(combined)
    
    # Split 90/10 for train/val
    split_idx = int(len(combined) * 0.9)
    train_combined = combined[:split_idx]
    val_combined = combined[split_idx:]
    
    with open(r"d:\orc\train_combined.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(train_combined))
        
    with open(r"d:\orc\val_combined.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(val_combined))
        
    print(f"Saved combined train ({len(train_combined)}) and val ({len(val_combined)})")

if __name__ == "__main__":
    convert_uit_dataset()
