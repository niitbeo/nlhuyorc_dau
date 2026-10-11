# NLHUYOCR — nhận dạng và kho hồ sơ tài liệu

Mã OCR chữ in và chữ viết tay hiện có nằm trong `scripts/`. Phần `dau_archive/` là ứng dụng quản lý văn bản tiếng Việt mới, dùng kết quả OCR đó hoặc văn bản gốc để lưu hồ sơ. Giai đoạn này tập trung quản lý tài liệu và tra cứu từ khóa; chatbot được để cho giai đoạn sau.

## Chạy OCR và kho hồ sơ

Yêu cầu Python 3.9 trở lên và SQLite có FTS5. Từ thư mục dự án:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-paddle.txt
python scripts/setup_paddle_detector.py
export DAU_DATA_DIR="$PWD/data"
python -m dau_archive.admin create-user admin --role admin --department "Văn thư"
uvicorn dau_archive.ocr_local:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000` để nhận dạng PDF nhiều trang hoặc ảnh. PaddleOCR dò vùng chữ rồi **NLHUYOCR**, gồm hai model do dự án huấn luyện cho chữ in và chữ viết tay, đọc từng vùng. Chọn trang cần xem, sửa text rồi tải TXT hoặc JSON. PDF có lớp chữ được đọc trực tiếp theo mặc định; trang scan được đưa qua OCR. Trong terminal thứ hai, chạy kho hồ sơ:

Model mặc định là bản lớn `PP-OCRv5_server_det`; chữ `server` chỉ tên biến thể model do PaddleOCR đặt, không phải máy chủ trên Internet. Model nằm trong `weights/paddle/` và nhận dạng offline sau khi tải một lần bằng script cài đặt. Nếu muốn bản gọn, tải thêm bằng `python scripts/setup_paddle_detector.py --model mobile` rồi chọn **PaddleOCR bản gọn** trên giao diện. Trên một ảnh scan mẫu xoay 12°, cả hai bản đều tìm được một dòng; bản lớn giữ đúng chữ hoa và text mẫu, nhưng mất khoảng 5 giây so với khoảng 0,5 giây của bản gọn trên máy thử. Đây chỉ là kiểm tra tích hợp một ảnh, chưa phải benchmark tài liệu thực tế.

```bash
source .venv/bin/activate
export DAU_DATA_DIR="$PWD/data"
export DAU_OCR_URL=http://127.0.0.1:8000/ocr/image
uvicorn dau_archive.app:app --host 127.0.0.1 --port 8001
```

Mở `http://127.0.0.1:8001` để nhập và tra cứu hồ sơ. Lệnh tạo tài khoản yêu cầu mật khẩu tối thiểu 12 ký tự. Tạo tài khoản nhân sự bằng `python -m dau_archive.admin create-user ten_dang_nhap --department "Tên đơn vị"`. Tệp gốc và SQLite nằm trong `DAU_DATA_DIR`; thư mục `data/` được bỏ qua bởi Git.

Giao diện kho hồ sơ dùng React và Lucide, mã nguồn nằm trong `frontend/`. Bản biên dịch được phục vụ trực tiếp bởi FastAPI tại cổng 8001. Sau khi sửa giao diện, chạy `cd frontend && npm ci && npm run build` rồi tải lại trang; khi phát triển có thể chạy `npm run dev` với API được proxy sang cổng 8001. Giao diện chạy với phông hệ thống, không cần tải tài nguyên từ CDN.

Quản trị viên dùng biểu tượng **Cài đặt API** ở góc phải để nhập, kiểm tra hoặc xóa Gemini API key. Khóa nằm trong `DAU_DATA_DIR/secret_settings.json` (quyền 0600, thư mục `data/` được Git bỏ qua); biến môi trường `GEMINI_API_KEY` được ưu tiên nếu có. API không trả lại khóa. Không đưa khóa vào mã nguồn, tệp theo dõi bởi Git hoặc hội thoại. Trước khi đẩy mã, chạy `python scripts/check_no_secrets.py`; GitHub Actions cũng chạy phép quét này. Khóa đã từng bị công khai cần được xóa và tạo lại trong Google AI Studio, kể cả sau khi làm sạch lịch sử Git.

Quản trị viên chọn **Kiểm tra model** trong menu trái để tải PDF/ảnh của mình (PNG, JPG, WebP, TIFF; tối đa 30 MiB), chọn trang bắt đầu và kiểm tra tối đa 3 trang mỗi lần. Trang đó được chạy qua NLHUYOCR tự chọn, chữ in và viết tay; văn bản và thời gian từng cách đọc hiển thị cạnh nhau. Dán bản chép đúng của các trang đã chọn theo đúng thứ tự để tính CER/WER; không có bản chép thì chỉ so văn bản và thời gian, không có số đo độ chính xác. Mặc định chỉ xử lý nội bộ. **So với Gemini** là tùy chọn riêng cho từng lần chạy và gửi đúng các trang đã chọn lên Google, có thể dùng quota API. Kết quả gần nhất được lưu trong thư mục dữ liệu và chỉ quản trị viên xem được. Hồ sơ trong kho không tự động được dùng cho phép đo này.

Trang này vẫn có bộ mẫu có đáp án để đo nhanh. Chạy `python scripts/fetch_uit_hwdb_test.py` để lấy 10 dòng chữ viết tay test có nhãn. Có thể chạy bằng CLI qua `python scripts/benchmark_stage1.py --gemini` để lưu chi tiết vào `data/benchmark/stage1_results.json`. Kết quả tập công khai chỉ dùng làm phép kiểm tra ban đầu, không thay cho bộ tài liệu thật của trường.

Kết quả phép đo hiện tại và giới hạn của bộ mẫu: [docs/ocr-stage1-evaluation.md](docs/ocr-stage1-evaluation.md).

Ứng dụng hỗ trợ công văn đến, công văn đi, ISO, chương trình đào tạo, giáo án/học liệu và loại khác. Người tạo có thể sửa tiêu đề và mức truy cập, tải phiên bản mới, xác nhận hoặc bỏ metadata, thêm quan hệ và cấp/thu hồi quyền xem. Quản trị viên có thể quản lý mọi hồ sơ. Nhân sự xem tài liệu công khai, tài liệu của đơn vị mình, tài liệu do mình tạo, hoặc tài liệu được cấp quyền. Tra cứu chỉ trả tài liệu người dùng được phép xem.

## Nguồn văn bản và OCR

- PDF có lớp text đọc được, DOCX, TXT và Markdown được lấy chữ trực tiếp. Trang PDF chỉ chứa ảnh hoặc có lớp chữ lỗi mã tiếng Việt được gửi tới dịch vụ OCR nội bộ; hệ thống giữ số trang và ghi nguồn `ocr`.
- Khi đã chạy OCR bằng pipeline hiện có, tải bản gốc cùng `ocr_pages_json` dạng `[{"text":"Nội dung trang 1"},{"text":"Nội dung trang 2"}]`. Mỗi trang được lưu với nguồn `existing-ocr`; kết quả metadata ghi kèm số trang và câu chứa bằng chứng.
- Dịch vụ `dau_archive.ocr_local` dùng trọng số NLHUYOCR tại `weights/transformerocr_finetuned.pth` (chữ in) và `weights/handwriting_pro.pth` (chữ viết tay); có thể đổi bằng `DAU_PRINTED_WEIGHTS` và `DAU_HANDWRITTEN_WEIGHTS`. Hai checkpoint dùng thư viện nhận dạng nền để suy luận; tên gói kỹ thuật trong dependency không phải tên sản phẩm. Bước dò dòng dùng model chính thức `PP-OCRv5_server_det` tại `weights/paddle/PP-OCRv5_server_det_infer`, hoặc đường dẫn `DAU_PADDLE_DET_MODEL_DIR`. Bản gọn dùng `DAU_PADDLE_MOBILE_DET_MODEL_DIR` nếu muốn đổi đường dẫn. Model được tải một lần bằng script trên, kiểm SHA-256 và dùng offline lúc nhận dạng. `auto` ưu tiên bản lớn, rồi bản gọn; nếu không có model hoặc model lỗi sẽ chuyển sang dò dòng đơn giản và hiện cảnh báo. Có thể chọn riêng bản lớn, bản gọn hoặc cách dò đơn giản để so sánh. PaddleOCR chỉ trả các đa giác vùng chữ, NLHUYOCR đọc nội dung. Giao diện hiện khung chữ trên trang gốc và cho bật/tắt lớp này. Trang có hai cột chữ tách biệt được đọc hết cột trái rồi đến cột phải; bố cục bảng phức tạp vẫn cần kiểm tra thủ công.
- Giao diện OCR xử lý PDF hoặc ảnh, báo tiến độ theo trang, cho xem trang gốc, sửa kết quả và xuất TXT/JSON. Lượt xử lý cùng tệp gốc nằm tại `DAU_DATA_DIR/ocr_jobs/`, nên vẫn xem lại được sau khi khởi động lại. Mỗi lượt cho chọn tối đa 500 trang, PDF tối đa 200 MiB, ảnh tối đa 50 MiB. Mặc định hệ thống phân loại **từng dòng** là chữ in hoặc viết tay bằng `weights/text_classifier.pth` rồi chọn model NLHUYOCR tương ứng. Dòng có điểm phân loại dưới 0,90 được thử thêm bằng model còn lại; chỉ đổi model khi điểm nhận dạng cao hơn tối thiểu 0,02. Có thể buộc một loại chữ trên giao diện hoặc qua `DAU_OCR_MODE`. Nếu OCR thiếu hoặc lỗi, tác vụ được đánh dấu thất bại và giữ bản gốc để xử lý lại.
- Kho hồ sơ nhận bản tải lên tối đa 50 MiB và OCR JSON tối đa 1.000 trang. Các đề xuất metadata dùng quy tắc tiếng Việt cho số văn bản, ngày ký, người ký, nơi gửi/nhận, mã ISO, ngày hiệu lực, học phần và năm học. Có thể gắn thêm model NER **đã tải tại máy** qua `DAU_NER_MODEL_PATH`.

## Nhập loạt tài liệu và phân loại

Màn hình **Nhập tài liệu → Nhập hàng loạt** nhận nhiều tệp PDF, Word, Excel, ảnh, TXT/Markdown hoặc ZIP/RAR (tối đa 200 tệp, 1,5 GiB mỗi đợt). Một tệp rời hoặc tệp bên trong archive tối đa 50 MiB. Sau khi tải lên, đợt nhập chạy nền, giữ đường dẫn gốc, phân loại sơ bộ và tạo hàng đợi trích chữ/OCR. Tệp tạm của Office bị bỏ qua; lỗi từng tệp được liệt kê ngay trong đợt nhập. Hệ thống lưu tệp theo SHA-256 nên các bản trùng byte dùng chung một blob; ZIP/RAR tải qua trình duyệt chỉ là tệp trung chuyển và được xóa sau khi nhập thành công. Mỗi hồ sơ vẫn có nguồn nhập riêng, đơn vị, quyền xem và phiên bản riêng.

Phân loại ban đầu dựa vào đường dẫn, tên tệp và nội dung đã trích: công văn đến/đi, ISO, chương trình đào tạo, học liệu hoặc tài liệu khác. Trong bộ ISO, hệ thống đề xuất quy trình, biểu mẫu, văn bản viện dẫn, hướng dẫn và quy định. Các tài liệu trong cùng thư mục quy trình có thể được đề xuất quan hệ **Thuộc hồ sơ**; mọi đề xuất cần người phụ trách xác nhận. Có thể sửa loại, vai trò ISO và đơn vị trong hồ sơ. Tab **Nội dung OCR** cho tải TXT hoặc JSON gồm trang, nguồn trích, metadata và đường dẫn trong archive. DOC/XLS/XLSX dùng LibreOffice nội bộ để chuyển sang PDF trước khi lấy text; trang quét dùng dịch vụ OCR tại `DAU_OCR_URL`.

Kho tài liệu phân trang 50 hồ sơ mỗi lần và lọc trên SQLite theo tên, đường dẫn nguồn, loại, đơn vị hoặc bộ hồ sơ. Bộ lọc và tổng số hồ sơ được tính trên toàn bộ dữ liệu người dùng được phép xem, không bị giới hạn bởi số tài liệu đã tải vào trình duyệt.

Menu **Cần xác nhận** gom các hồ sơ có phân loại, trường dữ liệu hoặc quan hệ còn ở trạng thái đề xuất; chỉ chủ hồ sơ và quản trị viên thấy các mục mình có quyền sửa. Tab **Nguồn gốc** trong từng hồ sơ nối đường dẫn trong archive với phiên bản SHA-256, nguồn text/OCR theo trang, các bản trùng byte mà người xem được phép truy cập và lịch sử thao tác của người có quyền sửa. Nút **Kiểm tra toàn vẹn** tính lại SHA-256 của tệp đã lưu để phát hiện tệp thiếu hoặc bị thay đổi. Cách trình bày theo nguồn gốc và luồng xác nhận được tham khảo từ [ArkhamMirror](https://github.com/mantisfury/ArkhamMirror); không dùng các module điều tra hoặc dịch vụ đám mây của dự án đó.

Để nhập archive đã có sẵn trên máy mà không tải qua trình duyệt:

```bash
python3 scripts/import_archive.py data/iso_source/example.zip --owner admin \
  --department "Văn thư" --kind-hint iso --derive-department
```

Lệnh sẽ xác minh SHA-256 nếu thêm `--sha256 <digest>` và không tạo lại đợt nhập cho cùng đường dẫn đã đăng ký. Một archive ISO thực tế có thể mất lâu để OCR xong; trang đợt nhập tách số **đã đưa vào kho** khỏi trạng thái OCR. Tìm kiếm từ khóa chạy trên trang đã trích. Embedding localhost vẫn tắt theo mặc định (`DAU_ENABLE_SEMANTIC=0`) để chỉ lập chỉ mục ngữ nghĩa sau khi rà chất lượng OCR và so model trên câu hỏi thật. Sao lưu hiện lưu SQLite cùng các blob tài liệu đã nhập; archive nguồn bên ngoài kho không nằm trong bản sao lưu.

Hai archive do người dùng cung cấp: [trọng số OCR](https://drive.google.com/file/d/1z9gD4o4faiJSaK2JpbPWc0Gogmv70o3O/view) và [dữ liệu OCR](https://drive.google.com/file/d/1D4PE7BFRN1ZqWvTNeNlxWjj_IiW_Mic7/view). Archive trọng số có SHA-256 `13b49ff4fe95ea9e2c1ef83228f26d58f26c1cd8d855b8a7828c81b4f9c99bec`, 5 tệp và CRC ZIP hợp lệ. Archive dữ liệu có SHA-256 `9f56abe07875a190e02c5a63d072ef475579c0a7585c835173661f818c0f6ad9`, chứa 46.256 mục nhưng **thiếu mục lục cuối ZIP**; bản sửa riêng tại `data/NLHUY_Dataset_fast_repaired.zip` đã qua kiểm tra CRC. Mẫu ảnh kiểm tra trong archive là chữ in và không có cặp câu hỏi–tài liệu để đánh giá embedding. Trọng số và dữ liệu đều nằm ngoài Git.

## Sao lưu và khôi phục

```bash
python -m dau_archive.admin backup /duong/dan/backup.tar.gz
python -m dau_archive.admin verify-backup /duong/dan/backup.tar.gz
python -m dau_archive.admin restore /duong/dan/backup.tar.gz /duong/dan/thu_muc_trong
```

Bản sao lưu gồm ảnh chụp SQLite nhất quán, tệp gốc và OCR JSON; manifest SHA-256 được kiểm tra khi khôi phục. Nên lưu backup ở thiết bị khác và thử khôi phục định kỳ. Đặt `DAU_DATA_DIR` trỏ tới thư mục đã khôi phục để mở lại hệ thống.

## Sơ đồ quan hệ và tra cứu bằng embedding

Menu **Sơ đồ quan hệ** cho chọn một hồ sơ, xem 1–3 lớp liên kết, lọc theo loại và trạng thái đề xuất, mở hồ sơ liên quan, tạo quan hệ thủ công có trang/bằng chứng và xác nhận hoặc bỏ đề xuất. Mỗi nút/quan hệ đều được kiểm tra quyền xem ở API; không hiển thị hồ sơ kín cho người không được cấp quyền. Từ tab **Quan hệ** của một hồ sơ có thể mở sơ đồ lấy hồ sơ đó làm tâm.

Tìm kiếm có ba chế độ: **Từ khóa** (SQLite FTS5/BM25), **Ngữ nghĩa** (vector tại máy), và **Kết hợp** (xếp hạng trộn hai nguồn). Khi model chưa có hoặc chưa lập vector, chế độ Kết hợp tự dùng từ khóa và báo rõ trạng thái; chế độ Ngữ nghĩa không tạo kết quả giả. API hỗ trợ lọc loại tài liệu, đơn vị và bộ sưu tập. Tab **Tương tự** trong hồ sơ dùng vector tài liệu để gợi ý các hồ sơ gần nhau theo quyền truy cập.

Quản trị viên vào menu **Embedding** để chọn `AITeamVN/Vietnamese_Embedding_v2` hoặc `BAAI/bge-m3`, xem số đoạn/tài liệu đã lập chỉ mục và chạy từng lượt 20–2.000 đoạn. Trọng số chạy nội bộ; không gọi API embedding. Tải model đầu tiên bằng:

```bash
python3 -m pip install -r requirements-embedding.txt
python3 scripts/fetch_embedding_model.py --model vietnamese-v2
```

Tệp lớn nằm tại `data/models/` và được bỏ qua bởi Git. Sau khi tải, bấm **Làm mới** rồi chạy thử một lượt 20 đoạn. Chỉ mục lưu riêng theo model và phiên bản tài liệu; khi đổi model phải lập vector cho model mới. `sentence-transformers` được dùng nếu đã cài; nếu không, hệ thống dùng `transformers` với mean pooling tại CPU. Có thể đặt `DAU_EMBED_MODEL_PATH` để dùng thư mục trọng số riêng. Không nên lập toàn bộ 19.000+ đoạn trên CPU trước khi đo chất lượng/tốc độ bằng câu hỏi thật của trường. Chưa có chatbot hoặc API trả lời tự động trong giai đoạn này.

## Kiểm thử

```bash
pip install pytest httpx
python -m pytest -q tests
```

Bộ kiểm thử dùng dữ liệu mẫu, bao gồm phân quyền, OCR JSON, metadata có bằng chứng, tìm kiếm, phiên bản, quan hệ, khôi phục backup, PDF hai trang, sửa kết quả, xuất tệp và cắt đa giác PaddleOCR. OCR chữ in đã được chạy bằng trọng số thật cùng detector PaddleOCR trên trang PDF scan và ảnh nghiêng. Đây là kiểm tra tích hợp, chưa phải phép đo tăng độ chính xác trên bộ tài liệu thật. Model viết tay đã nạp và trả kết quả qua API, nhưng độ chính xác trên ảnh viết tay thật cần thử bằng ảnh người dùng cung cấp.
