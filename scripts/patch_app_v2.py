import re
import os

with open(r'd:\orc\scripts\app.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add classifier imports
new_imports = '''import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import sys
import torch
from torchvision import transforms, models
import torch.nn as nn
from docreconstruct.reconstruction.hybrid_job import run_hybrid_job
from pathlib import Path
'''
code = re.sub(r'import fitz.*from pathlib import Path\n', new_imports, code, flags=re.DOTALL)

# 2. Add model loading functions
routing_code = '''
# --- 2-STREAM ROUTING ARCHITECTURE ---
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def get_classifier():
    model = models.resnet18(weights=None)
    num_ftrs = model.fc.in_features
    # 2 classes: handwritten, printed
    model.fc = nn.Linear(num_ftrs, 2)
    model.load_state_dict(torch.load(r'd:\\orc\\weights\\text_classifier.pth', map_location=device))
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
        config['weights'] = r'd:\\orc\\weights\\transformerocr_finetuned.pth'
    else:
        config['weights'] = r'd:\\orc\\weights\\handwriting_finetuned.pth'
        
    predictor = Predictor(config)
    return predictor
'''
# Insert after predictor = None
code = code.replace('predictor = None', 'predictor = None\n' + routing_code)


# 3. Update process_document logic
# Find where crops are made and text is predicted
old_loop = r'''        for box in boxes:
            crop = get_crop(img, box)
            pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            text = predictor.predict(pil_crop)
            texts.append(text)
            
            # Draw box
            pts = \[\(int\(p\[0\]\), int\(p\[1\]\)\) for p in box\]
            pts_closed = pts \+ \[pts\[0\]\]
            draw.line\(pts_closed, fill=\(255, 0, 0\), width=2\)
            
            # Draw text
            draw.text\(\(pts\[0\]\[0\], max\(0, pts\[0\]\[1\] - 25\)\), text, font=font, fill=\(0, 0, 255\)\)
'''

new_loop = '''        
        # Crop all boxes
        pil_crops = []
        for box in boxes:
            crop = get_crop(img, box)
            pil_crops.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            
        # Classify all crops
        print("Classifying crops...")
        classifier, clf_transform = get_classifier()
        labels = []
        
        with torch.no_grad():
            for pil_crop in pil_crops:
                tensor_crop = clf_transform(pil_crop).unsqueeze(0).to(device)
                outputs = classifier(tensor_crop)
                _, preds = torch.max(outputs, 1)
                # 0: handwritten, 1: printed (alphabetical order of ImageFolder)
                labels.append("printed" if preds.item() == 1 else "handwritten")
                
        # Free classifier
        del classifier
        torch.cuda.empty_cache()
        
        # Read Printed
        print("Reading printed text...")
        printed_predictor = get_ocr_model("printed")
        texts = [""] * len(boxes)
        for i, (pil_crop, label) in enumerate(zip(pil_crops, labels)):
            if label == "printed":
                texts[i] = printed_predictor.predict(pil_crop)
        del printed_predictor
        torch.cuda.empty_cache()
        
        # Read Handwritten
        print("Reading handwritten text...")
        hw_predictor = get_ocr_model("handwritten")
        for i, (pil_crop, label) in enumerate(zip(pil_crops, labels)):
            if label == "handwritten":
                texts[i] = hw_predictor.predict(pil_crop)
        del hw_predictor
        torch.cuda.empty_cache()
        
        # Draw on image
        for i, box in enumerate(boxes):
            text = texts[i]
            label = labels[i]
            pts = [(int(p[0]), int(p[1])) for p in box]
            pts_closed = pts + [pts[0]]
            # Red box for printed, Green box for handwritten
            color = (255, 0, 0) if label == "printed" else (0, 255, 0)
            draw.line(pts_closed, fill=color, width=2)
            draw.text((pts[0][0], max(0, pts[0][1] - 25)), text, font=font, fill=(0, 0, 255))
'''

code = re.sub(old_loop, new_loop, code, flags=re.DOTALL)

# We need to remove the global predictor initialization at the top of process_document since we load dynamically
code = re.sub(r'    global predictor\n    if predictor is None and use_finetuned:\n.*?else:\n.*?    t0 = time.time\(\)\n', '    t0 = time.time()\n', code, flags=re.DOTALL)

with open(r'd:\orc\scripts\app_v2.py', 'w', encoding='utf-8') as f:
    f.write(code)
