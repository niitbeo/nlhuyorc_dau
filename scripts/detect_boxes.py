import argparse
import json
import os
from paddleocr import PaddleOCR

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=str, required=True)
    parser.add_argument('--output', type=str, required=True)
    args = parser.parse_args()
    
    # Initialize PaddleOCR v3 style (using PP-OCRv5)
    ocr = PaddleOCR(
        text_detection_model_name='PP-OCRv5_mobile_det',
        text_recognition_model_name='PP-OCRv5_mobile_rec', # Just load it, it's small, to avoid errors
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False
    )
    
    # In PaddleOCR v3 with Paddlex, it returns an iterator of results via predict
    res_list = ocr.predict(args.image)
    
    boxes = []
    # Fetch first result
    for res in res_list:
        # res is a dict-like object
        if 'dt_polys' in res:
            boxes = res['dt_polys']
        elif 'rec_polys' in res:
            boxes = res['rec_polys']
        break
            
    # Convert numpy arrays to lists if necessary
    json_boxes = []
    for box in boxes:
        if hasattr(box, 'tolist'):
            json_boxes.append(box.tolist())
        else:
            json_boxes.append(box)
            
    out_dict = {
        "data": [
            {
                "dt_polys": json_boxes,
                "rec_texts": ["dummy text"] * len(json_boxes) # Required for docreconstruct paddleocr parser
            }
        ]
    }
            
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out_dict, f)

if __name__ == '__main__':
    main()
