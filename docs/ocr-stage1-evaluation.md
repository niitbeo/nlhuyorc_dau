# Đánh giá OCR giai đoạn 1 — 11/10/2026

## Dữ liệu và cách đo

- 6 trang chữ in từ `data/NLHUY_Dataset_fast_repaired.zip`: 2 trang sạch, 2 trang scan, 2 trang scan xấu; mỗi trang có bản chép đúng. Đo toàn pipeline PaddleOCR server + VietOCR.
- 10 dòng chữ viết tay ở tập **test** [UIT-HWDB](https://huggingface.co/datasets/blue7012/UIT_HWDB), giấy phép CC-BY-4.0. Đo riêng lựa chọn model và nhận dạng trên từng dòng.
- Ghép 10 dòng công khai thành một trang để kiểm tra dò dòng và nhận dạng toàn trang; đây là trang dựng để thử tích hợp, không đại diện cho công văn viết tay thật.
- CER/WER dùng khoảng trắng chuẩn hóa và Unicode NFC, giữ nguyên chữ hoa/dấu. Thời gian là wall clock trên máy thử; lần nạp model đầu và tải máy ảnh hưởng kết quả. Gemini 3.8 Flash nhận chính những ảnh công khai/tổng hợp được so sánh.

## Kết quả

| Tập | Cấu hình | Số mẫu | CER trung bình | WER trung bình | Thời gian trung vị |
| --- | --- | ---: | ---: | ---: | ---: |
| Trang in | Tự chọn + Paddle server | 6 | 11,8% | 19,2% | 12,28 s/trang |
| Dòng viết tay | Tự chọn sau kiểm tra lại | 10 | 4,4% | 12,2% | 0,98 s/dòng |
| Dòng viết tay | Buộc model viết tay | 10 | 4,4% | 12,2% | 0,45 s/dòng |

So trên **cùng 4 ảnh in**: OCR nội bộ CER 12,1%, trung vị 13,84 s; Gemini CER 0% và 5,14 s. So trên **cùng 4 dòng viết tay**: OCR tự chọn CER 4,3%, trung vị 0,99 s; Gemini CER 4,0% và 4,30 s. Chỉ 4 mẫu mỗi nhóm, vì vậy không suy rộng kết quả này thành độ chính xác trên hồ sơ trường.

Ban đầu bộ phân loại nhận đúng viết tay 3/10 dòng. Khi điểm phân loại dưới 0,90, thử cả hai recognizer và đổi model nếu điểm nhận dạng tăng ít nhất 0,02; sau sửa chọn đúng model viết tay 10/10 dòng test. Các ngưỡng này cần kiểm tra tiếp trên dữ liệu của trường.

Trang viết tay ghép: Paddle server tìm đủ 10 dòng, OCR tự chọn CER 6,9%, WER 17,8%, 17,07 s; Gemini CER 5,0%, WER 16,4%, 6,20 s. Paddle mobile chỉ tìm 8 dòng, CER tăng lên 24,7%, nên **giữ Paddle server làm mặc định**. Trên một trang in, mobile tìm đủ 22 dòng và nhanh hơn server (9,66 s so với 13,46 s), nhưng một mẫu không đủ để đổi cấu hình chung.

Peak RSS của tiến trình benchmark sau khi nạp model khoảng 7.247 MiB; tiến trình OCR đang phục vụ sau khi nạp hai detector khoảng 1.996 MiB RSS. Số này phụ thuộc máy, thư viện và lịch sử yêu cầu.

## Giới hạn và bước tiếp theo

Ảnh chữ in là dữ liệu tổng hợp và tập viết tay chỉ có dòng độc lập. Chưa có mẫu chữ viết tay của trường kèm bản chép chuẩn; chưa thể nghiệm thu độ chính xác trên công văn, giáo án và biểu mẫu thật. Cần lập tập kiểm tra có ít nhất vài chục trang đại diện, đo CER/WER theo loại và kiểm tra thứ tự đọc trong bảng, nhiều cột, dấu mộc.

Lệnh tái lập: `python scripts/fetch_uit_hwdb_test.py`, rồi `python scripts/benchmark_stage1.py --gemini`. Chỉ dùng `--gemini` khi các ảnh được phép gửi lên Google. Số liệu chi tiết trong `data/benchmark/stage1_local_fallback.json`, `data/benchmark/stage1_results.json` và các tệp `handwritten_page_*_result.json` (thư mục `data/` không đưa vào Git).
