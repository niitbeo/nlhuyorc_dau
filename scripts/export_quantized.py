import torch
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from vietocr.tool.config import Cfg
from vietocr.tool.translate import build_model

def export_quantized():
    print("🚀 BẮT ĐẦU QUÁ TRÌNH ÉP CÂN (QUANTIZATION) MÔ HÌNH...")
    
    # Load config
    config = Cfg.load_config_from_file('configs/vgg_transformer_base.yml')
    config['dataset']['image_max_width'] = 2048
    config['device'] = 'cpu' # Quantization dynamic thường hỗ trợ tốt nhất trên CPU
    
    # Build model architecture
    print("[1/3] Đang tải kiến trúc mô hình gốc...")
    model, vocab = build_model(config)
    
    # Load weights
    print("[2/3] Đang nạp tạ 450MB vào mô hình...")
    weights_path = r'd:\orc\weights\handwriting_pro.pth'
    model.load_state_dict(torch.load(weights_path, map_location='cpu'))
    model.eval()
    
    # Apply Dynamic Quantization (ép kiểu float32 xuống int8 cho các lớp Linear)
    print("[3/3] Đang thi triển phép thuật Lượng tử hóa (Int8 Dynamic Quantization)...")
    quantized_model = torch.quantization.quantize_dynamic(
        model, {torch.nn.Linear}, dtype=torch.qint8
    )
    
    # Lưu mô hình ép cân
    output_path = r'd:\orc\weights\handwriting_pro_quantized.pth'
    torch.save(quantized_model.state_dict(), output_path)
    
    # So sánh dung lượng
    orig_size = os.path.getsize(weights_path) / (1024 * 1024)
    quant_size = os.path.getsize(output_path) / (1024 * 1024)
    
    print("\n✅ ÉP CÂN THÀNH CÔNG!")
    print(f"📉 Dung lượng gốc: {orig_size:.2f} MB")
    print(f"📉 Dung lượng sau ép cân: {quant_size:.2f} MB")
    print(f"⚡ Tốc độ dự kiến trên CPU: Nhanh hơn 2-3 lần!")

if __name__ == "__main__":
    export_quantized()
