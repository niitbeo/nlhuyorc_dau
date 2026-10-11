import re

with open(r'd:\orc\scripts\app.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Add docx export import
if 'from docreconstruct.cli import run_hybrid_job' not in code:
    code = code.replace('import sys\n', 'import sys\nfrom docreconstruct.cli import run_hybrid_job\nfrom pathlib import Path\n')

# Update process_document to generate evidence.json and content.md, then run docreconstruct
process_pattern = r'(    all_full_text = ""\n    total_det_time = 0)'
process_replacement = '''    all_full_text = ""
    all_evidence_pages = []
    total_det_time = 0'''
code = re.sub(process_pattern, process_replacement, code)

# We need to collect boxes and texts into evidence
evidence_pattern = r'(        page_text = group_rows\(boxes, texts\))'
evidence_replacement = '''        
        all_evidence_pages.append({
            "dt_polys": boxes,
            "rec_texts": texts
        })
        
        page_text = group_rows(boxes, texts)'''
code = re.sub(evidence_pattern, evidence_replacement, code)

# At the end of process_document
end_process_pattern = r'(    return all_vis_imgs, all_full_text, stats)'
end_process_replacement = '''    # Write content.md and evidence.json
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
            online_ocr=False
        )
    except Exception as e:
        print(f"DocReconstruct failed: {e}")
        out_docx_path = None
        stats += f"\\nLỗi tạo Word: {e}"
    
    return all_vis_imgs, all_full_text, stats, out_docx_path'''
code = re.sub(end_process_pattern, end_process_replacement, code)

if 'docx_output' not in code:
    code = code.replace('stats_output = gr.Textbox(label="Thông số hiệu năng (Thời gian, Số dòng)")', 'stats_output = gr.Textbox(label="Thông số hiệu năng (Thời gian, Số dòng)")\n            docx_output = gr.File(label="Tải xuống Word (DOCX)")')
    code = code.replace('outputs=[img_output, text_output, stats_output]', 'outputs=[img_output, text_output, stats_output, docx_output]')


with open(r'd:\orc\scripts\app.py', 'w', encoding='utf-8') as f:
    f.write(code)
