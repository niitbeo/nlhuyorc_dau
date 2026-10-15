import React, { useState, useEffect, useRef } from 'react';
import {
  FileText,
  FolderUp,
  Upload,
  ScanText,
  Sparkles,
  Network,
  FolderOpen,
  Search,
  CheckCircle2,
  AlertTriangle,
  Sliders,
  Crop,
  Save,
  Trash2,
  Plus,
  Table,
  Tags,
  BookOpen,
  Layers,
  Eye,
  RefreshCw,
  Download,
  ChevronRight,
  Cpu,
  ShieldCheck,
  Calendar,
  Building2,
  UserCheck,
  Hash,
  Wand2
} from 'lucide-react';

const API_BASE = 'http://localhost:8000';

export interface DocumentRecord {
  id: string;
  filename: string;
  folder_path: string;
  file_url: string;
  file_size: number;
  checksum: string;
  ocr_mode: string;
  quality_info: {
    width?: number;
    height?: number;
    contrast_ratio?: number;
    skew_angle?: number;
    has_noise?: boolean;
    is_blank?: boolean;
    detected_layout?: string;
    classification?: string;
    operations_applied?: string[];
    analysis_ms?: number;
  };
  raw_text: string;
  corrected_text: string;
  html_tables: string[];
  entities: {
    so_van_ban?: string | null;
    ngay_ban_hanh?: string | null;
    loai_van_ban?: string;
    PERSON?: string[];
    ORGANIZATION?: string[];
    LOCATION?: string[];
    MONEY?: string[];
    MSSV?: string[];
    custom_extracted?: Record<string, string | null>;
    lines?: Array<{
      id: string;
      box: number[];
      raw_text: string;
      corrected_text: string;
      confidence: number;
    }>;
  };
  summary: {
    title?: string;
    executive_summary?: string;
    key_points?: string[];
    word_count?: number;
  };
  graph_data: {
    nodes: Array<{ id: string; label: string; type: string; sub_type?: string; degree: number; doc_count?: number }>;
    edges: Array<{ source: string; target: string; label: string; weight: number }>;
  };
  confidence: number;
  created_at: string;
}

export interface OCRTemplate {
  id: string;
  name: string;
  description: string;
  fields: Array<{ key: string; label: string; pattern: string; type: string }>;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dms' | 'studio' | 'rules' | 'graph'>('dms');
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<DocumentRecord | null>(null);
  const [templates, setTemplates] = useState<OCRTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('tpl_hanh_chinh');
  const [ocrMode, setOcrMode] = useState<string>('auto');
  const [targetFolder, setTargetFolder] = useState<string>('Hồ sơ Hành chính');
  const [filterFolder, setFilterFolder] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Upload states
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number; currentFile: string }>({
    current: 0,
    total: 0,
    currentFile: ''
  });

  // OCR Studio states (Edit, Zone Crop, Tabs)
  const [studioSubTab, setStudioSubTab] = useState<'text' | 'table' | 'entities' | 'summary'>('text');
  const [editedText, setEditedText] = useState<string>('');
  const [customFieldsEdit, setCustomFieldsEdit] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveMessage, setSaveMessage] = useState<string>('');

  // Interactive Zone Crop OCR on Image
  const [isCropping, setIsCropping] = useState<boolean>(false);
  const [cropFieldLabel, setCropFieldLabel] = useState<string>('Trường_Mới');
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragCurrent, setDragCurrent] = useState<{ x: number; y: number } | null>(null);
  const [isRunningZoneOcr, setIsRunningZoneOcr] = useState<boolean>(false);
  const imgRef = useRef<HTMLImageElement | null>(null);

  // Custom Template Creation states
  const [newTplName, setNewTplName] = useState<string>('');
  const [newTplDesc, setNewTplDesc] = useState<string>('');
  const [newTplFields, setNewTplFields] = useState<Array<{ key: string; label: string; pattern: string; type: string }>>([
    { key: 'so_quyet_dinh', label: 'Số Quyết định', pattern: 'Số:\\s*([0-9]+/[A-ZĐ\\-]+)', type: 'regex' }
  ]);

  // Global Graph state
  const [globalGraph, setGlobalGraph] = useState<{
    nodes: Array<{ id: string; label: string; type: string; degree: number; doc_count?: number }>;
    edges: Array<{ source: string; target: string; label: string; weight: number }>;
    contradictions: Array<{ type: string; doc_a: string; doc_b: string; detail: string }>;
    total_documents: number;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  const fetchDocuments = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/docfile/documents?search=${encodeURIComponent(searchQuery)}&folder=${encodeURIComponent(filterFolder)}`
      );
      const data = await res.json();
      setDocuments(data.documents || []);
      if (data.documents?.length > 0 && !selectedDoc) {
        selectDocumentForStudio(data.documents[0]);
      }
    } catch (e) {
      console.error('Lỗi tải danh sách tài liệu:', e);
    }
  };

  const fetchTemplates = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/docfile/templates`);
      const data = await res.json();
      setTemplates(data.templates || []);
    } catch (e) {
      console.error('Lỗi tải mẫu định nghĩa OCR:', e);
    }
  };

  const fetchGlobalGraph = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/docfile/global-graph`);
      const data = await res.json();
      setGlobalGraph(data);
    } catch (e) {
      console.error('Lỗi tải sơ đồ mạng lưới:', e);
    }
  };

  useEffect(() => {
    fetchDocuments();
    fetchTemplates();
    fetchGlobalGraph();
  }, [searchQuery, filterFolder]);

  const selectDocumentForStudio = (doc: DocumentRecord) => {
    setSelectedDoc(doc);
    setEditedText(doc.corrected_text || doc.raw_text || '');
    const customExt = doc.entities?.custom_extracted || {};
    const normalized: Record<string, string> = {};
    Object.entries(customExt).forEach(([k, v]) => {
      normalized[k] = v || '';
    });
    setCustomFieldsEdit(normalized);
  };

  // Xử lý Upload 1 hoặc Nhiều File / Cả Thư Mục
  const handleFilesUpload = async (fileList: FileList | null, isFolderUpload = false) => {
    if (!fileList || fileList.length === 0) return;
    const filesArray = Array.from(fileList).filter((f) =>
      /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(f.name)
    );
    if (filesArray.length === 0) {
      alert('Vui lòng chọn các tệp hình ảnh tài liệu (.png, .jpg, .jpeg, .webp, .bmp)!');
      return;
    }

    setIsUploading(true);
    setUploadProgress({ current: 0, total: filesArray.length, currentFile: '' });

    let lastUploadedDoc: DocumentRecord | null = null;

    for (let i = 0; i < filesArray.length; i++) {
      const file = filesArray[i];
      setUploadProgress({ current: i + 1, total: filesArray.length, currentFile: file.name });

      // Lấy tên thư mục con nếu người dùng upload cả Folder
      const relPath = (file as any).webkitRelativePath || '';
      const folderFromPath = isFolderUpload && relPath.includes('/')
        ? relPath.split('/')[0]
        : targetFolder;

      const formData = new FormData();
      formData.append('file', file);
      formData.append('folder_path', folderFromPath);
      formData.append('ocr_mode', ocrMode);
      formData.append('template_id', selectedTemplateId);

      try {
        const res = await fetch(`${API_BASE}/api/docfile/upload`, {
          method: 'POST',
          body: formData
        });
        if (res.ok) {
          lastUploadedDoc = await res.json();
        }
      } catch (err) {
        console.error('Upload error:', err);
      }
    }

    setIsUploading(false);
    await fetchDocuments();
    await fetchGlobalGraph();

    if (lastUploadedDoc) {
      selectDocumentForStudio(lastUploadedDoc);
      setActiveTab('studio');
    }
  };

  // Lưu chỉnh sửa OCR (Human-in-the-loop) & cập nhật lại Thực thể + Tóm tắt + Sơ đồ
  const handleSaveEditedOCR = async () => {
    if (!selectedDoc) return;
    setIsSaving(true);
    setSaveMessage('');
    try {
      const res = await fetch(`${API_BASE}/api/docfile/documents/${selectedDoc.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          corrected_text: editedText,
          custom_extracted: customFieldsEdit,
          folder_path: selectedDoc.folder_path
        })
      });
      if (res.ok) {
        const updated = await res.json();
        const updatedDoc: DocumentRecord = {
          ...selectedDoc,
          corrected_text: editedText,
          entities: updated.entities,
          summary: updated.summary,
          graph_data: updated.graph_data
        };
        setSelectedDoc(updatedDoc);
        setSaveMessage('Đã lưu hiệu chỉnh OCR & cập nhật lại Thực thể / Tóm tắt / Sơ đồ!');
        fetchDocuments();
        fetchGlobalGraph();
        setTimeout(() => setSaveMessage(''), 4000);
      }
    } catch (e) {
      console.error('Lỗi lưu OCR:', e);
    } finally {
      setIsSaving(false);
    }
  };

  // Xử lý Kẻ khung định nghĩa vùng OCR trực tiếp trên ảnh
  const handleImageMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isCropping || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    setDragStart({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    });
    setDragCurrent({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    });
  };

  const handleImageMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isCropping || !dragStart || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    setDragCurrent({
      x: Math.max(0, Math.min(e.clientX - rect.left, rect.width)),
      y: Math.max(0, Math.min(e.clientY - rect.top, rect.height))
    });
  };

  const handleImageMouseUp = async () => {
    if (!isCropping || !dragStart || !dragCurrent || !imgRef.current || !selectedDoc) return;
    const imgEl = imgRef.current;
    const scaleX = imgEl.naturalWidth / imgEl.clientWidth;
    const scaleY = imgEl.naturalHeight / imgEl.clientHeight;

    const x1 = Math.round(Math.min(dragStart.x, dragCurrent.x) * scaleX);
    const y1 = Math.round(Math.min(dragStart.y, dragCurrent.y) * scaleY);
    const x2 = Math.round(Math.max(dragStart.x, dragCurrent.x) * scaleX);
    const y2 = Math.round(Math.max(dragStart.y, dragCurrent.y) * scaleY);

    setDragStart(null);
    setDragCurrent(null);

    if (x2 - x1 < 10 || y2 - y1 < 10) return;

    setIsRunningZoneOcr(true);
    try {
      const res = await fetch(`${API_BASE}/api/docfile/ocr-region`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doc_id: selectedDoc.id,
          box: [x1, y1, x2, y2],
          field_name: cropFieldLabel || 'Vùng_Chọn'
        })
      });
      if (res.ok) {
        const data = await res.json();
        setCustomFieldsEdit((prev) => ({
          ...prev,
          [cropFieldLabel || 'Vùng_Chọn']: data.corrected_text
        }));
        setSaveMessage(`Đã bóc vùng [${cropFieldLabel}]: "${data.corrected_text}"`);
        setIsCropping(false);
        fetchDocuments();
      }
    } catch (err) {
      console.error('Lỗi Zone OCR:', err);
    } finally {
      setIsRunningZoneOcr(false);
    }
  };

  const handleDeleteDoc = async (docId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`${API_BASE}/api/docfile/documents/${docId}`, { method: 'DELETE' });
    if (selectedDoc?.id === docId) setSelectedDoc(null);
    fetchDocuments();
    fetchGlobalGraph();
  };

  const handleCreateTemplate = async () => {
    if (!newTplName.trim()) return;
    const res = await fetch(`${API_BASE}/api/docfile/templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newTplName,
        description: newTplDesc,
        fields: newTplFields
      })
    });
    if (res.ok) {
      const created = await res.json();
      await fetchTemplates();
      setSelectedTemplateId(created.id);
      setNewTplName('');
      setNewTplDesc('');
    }
  };

  const uniqueFolders = Array.from(
    new Set(['Hồ sơ Hành chính', 'Hồ sơ Sinh viên', 'Bảng điểm & Học bạ', ...documents.map((d) => d.folder_path)])
  );

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* TOP HEADER BAR */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
            <ScanText className="w-6 h-6 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold text-lg tracking-tight text-white">DAU DocFile AI</h1>
              <span className="text-[11px] font-semibold uppercase px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                ArkhamMirror Core v2.0
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Quản lý Tài liệu Số • VietOCR In & Viết tay • PP-Structure Table • Trích xuất 3 Lớp & Sơ đồ Tri thức
            </p>
          </div>
        </div>

        {/* NAVIGATION PILLS */}
        <nav className="flex items-center gap-1.5 bg-slate-950/90 p-1.5 rounded-xl border border-slate-800">
          <button
            onClick={() => setActiveTab('dms')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition ${
              activeTab === 'dms'
                ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <FolderOpen className="w-4 h-4" />
            <span>Kho Tài liệu & Upload</span>
            <span className="px-1.5 py-0.2 bg-slate-900/60 rounded text-[10px]">{documents.length}</span>
          </button>

          <button
            onClick={() => setActiveTab('studio')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition ${
              activeTab === 'studio'
                ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <Sliders className="w-4 h-4" />
            <span>Trạm Sửa & Trích xuất OCR</span>
          </button>

          <button
            onClick={() => setActiveTab('rules')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition ${
              activeTab === 'rules'
                ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <Tags className="w-4 h-4" />
            <span>Định nghĩa Mẫu OCR</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('graph');
              fetchGlobalGraph();
            }}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition ${
              activeTab === 'graph'
                ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <Network className="w-4 h-4" />
            <span>Sơ đồ Văn bản (Arkham Graph)</span>
          </button>
        </nav>

        {/* QUICK UPLOAD ACTIONS */}
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*"
            className="hidden"
            onChange={(e) => handleFilesUpload(e.target.files, false)}
          />
          <input
            ref={folderInputRef}
            type="file"
            // @ts-ignore - webkitdirectory for folder upload
            webkitdirectory=""
            directory=""
            multiple
            className="hidden"
            onChange={(e) => handleFilesUpload(e.target.files, true)}
          />

          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-600/25 transition disabled:opacity-50"
          >
            <Upload className="w-4 h-4" />
            <span>Tải Tài liệu</span>
          </button>

          <button
            onClick={() => folderInputRef.current?.click()}
            disabled={isUploading}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-lg shadow-emerald-600/25 transition disabled:opacity-50"
          >
            <FolderUp className="w-4 h-4" />
            <span>Tải cả Thư mục</span>
          </button>
        </div>
      </header>

      {/* UPLOAD PROGRESS BANNER */}
      {isUploading && (
        <div className="bg-indigo-950/90 border-b border-indigo-500/40 px-6 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />
            <span className="text-xs font-medium text-indigo-200">
              Đang chạy Pipeline ArkhamMirror (OpenCV Deskew → VietOCR → ProtonX → NER → Summary → Graph):{' '}
              <strong className="text-white">{uploadProgress.currentFile}</strong>
            </span>
          </div>
          <span className="text-xs font-bold text-indigo-300">
            {uploadProgress.current} / {uploadProgress.total} tệp
          </span>
        </div>
      )}

      {/* ================================================================= */}
      {/* TAB 1: KHO TÀI LIỆU SỐ (DMS) & TRẠM INGEST HÀNG LOẠT              */}
      {/* ================================================================= */}
      {activeTab === 'dms' && (
        <div className="flex-1 grid grid-cols-12 gap-6 p-6">
          {/* LEFT SIDEBAR: CẤU HÌNH INGEST & CÂY THƯ MỤC */}
          <div className="col-span-3 space-y-5">
            {/* UPLOAD & ROUTING BOX */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-4">
              <div className="flex items-center gap-2 text-indigo-400 font-semibold text-sm">
                <Cpu className="w-4 h-4" />
                <span>Cấu hình Trạm Ingest & OCR</span>
              </div>

              <div className="space-y-2">
                <label className="text-xs text-slate-400 block">Thư mục lưu trữ mặc định</label>
                <input
                  type="text"
                  value={targetFolder}
                  onChange={(e) => setTargetFolder(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                  placeholder="VD: Hồ sơ Hành chính 2026"
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs text-slate-400 block">Chế độ Định tuyến OCR (Smart Routing)</label>
                <select
                  value={ocrMode}
                  onChange={(e) => setOcrMode(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="auto">⚡ Tự động nhận diện (Văn bản + Bảng biểu)</option>
                  <option value="text">📝 Chuyên Văn bản In & Viết tay (VietOCR)</option>
                  <option value="table">📊 Chuyên Bảng biểu (PP-Structure + VietOCR)</option>
                </select>
              </div>

              <div className="space-y-2">
                <label className="text-xs text-slate-400 block">Mẫu Định nghĩa Trích xuất (OCR Schema)</label>
                <select
                  value={selectedTemplateId}
                  onChange={(e) => setSelectedTemplateId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                >
                  {templates.map((tpl) => (
                    <option key={tpl.id} value={tpl.id}>
                      {tpl.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* DRAG & DROP ZONE */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-slate-700 hover:border-indigo-500 bg-slate-950/60 hover:bg-indigo-950/20 rounded-xl p-5 text-center cursor-pointer transition group"
              >
                <Upload className="w-8 h-8 text-slate-500 group-hover:text-indigo-400 mx-auto mb-2 transition" />
                <p className="text-xs font-semibold text-slate-200">
                  Nhấn để chọn Ảnh hoặc kéo thả vào đây
                </p>
                <p className="text-[11px] text-slate-500 mt-1">
                  Tự động xoay ảnh nghiêng, làm nét CLAHE, đọc chữ viết tay & bóc bảng HTML
                </p>
              </div>
            </div>

            {/* FOLDER TREE */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                <FolderOpen className="w-4 h-4 text-amber-400" />
                <span>Cây Thư mục Hồ sơ Số</span>
              </h3>

              <button
                onClick={() => setFilterFolder('ALL')}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition ${
                  filterFolder === 'ALL'
                    ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
                    : 'text-slate-400 hover:bg-slate-800/60'
                }`}
              >
                <span>📁 Tất cả hồ sơ tài liệu</span>
                <span className="text-[11px] opacity-75">{documents.length}</span>
              </button>

              {uniqueFolders.map((folder) => (
                <button
                  key={folder}
                  onClick={() => setFilterFolder(folder)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition ${
                    filterFolder === folder
                      ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
                      : 'text-slate-400 hover:bg-slate-800/60'
                  }`}
                >
                  <span className="truncate">📂 {folder}</span>
                </button>
              ))}
            </div>
          </div>

          {/* RIGHT AREA: DANH SÁCH HỒ SƠ SỐ & KẾT QUẢ PHÂN TÍCH NHANH */}
          <div className="col-span-9 space-y-4">
            {/* SEARCH & STATS BAR */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex items-center justify-between gap-4">
              <div className="relative flex-1">
                <Search className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Tìm kiếm toàn văn nội dung OCR, Số quyết định, Tên sinh viên, Phòng ban..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-400">
                <span className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800">
                  Tổng số: <strong className="text-white">{documents.length}</strong> văn bản
                </span>
              </div>
            </div>

            {/* DOCUMENT CARDS GRID */}
            {documents.length === 0 ? (
              <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-12 text-center space-y-3">
                <FileText className="w-12 h-12 text-slate-600 mx-auto" />
                <h3 className="text-sm font-semibold text-slate-300">
                  Chưa có tài liệu nào trong kho lưu trữ
                </h3>
                <p className="text-xs text-slate-500 max-w-md mx-auto">
                  Hãy nhấn nút <strong>"Tải Tài liệu"</strong> hoặc <strong>"Tải cả Thư mục"</strong> ở góc phải phía trên để hệ thống tự động nhận diện chữ viết tay, chữ in, bảng biểu và vẽ sơ đồ tri thức.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                {documents.map((doc) => {
                  const qClass = doc.quality_info?.classification || 'CLEAN';
                  return (
                    <div
                      key={doc.id}
                      onClick={() => {
                        selectDocumentForStudio(doc);
                        setActiveTab('studio');
                      }}
                      className="bg-slate-900 hover:bg-slate-900/80 border border-slate-800 hover:border-indigo-500/60 rounded-2xl p-4 cursor-pointer transition group flex gap-4"
                    >
                      {/* THUMBNAIL PREVIEW */}
                      <div className="w-28 h-36 rounded-xl bg-slate-950 border border-slate-800 overflow-hidden flex-shrink-0 relative">
                        <img
                          src={`${API_BASE}${doc.file_url}`}
                          alt={doc.filename}
                          className="w-full h-full object-cover group-hover:scale-105 transition"
                        />
                        <span
                          className={`absolute bottom-1.5 left-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            qClass === 'CLEAN'
                              ? 'bg-emerald-500/90 text-slate-950'
                              : qClass === 'FIXABLE'
                              ? 'bg-amber-500/90 text-slate-950'
                              : 'bg-rose-500/90 text-white'
                          }`}
                        >
                          {qClass}
                        </span>
                      </div>

                      {/* CONTENT DETAILS */}
                      <div className="flex-1 min-w-0 flex flex-col justify-between">
                        <div>
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                              {doc.entities?.loai_van_ban || 'Tài liệu'}
                            </span>
                            <button
                              onClick={(e) => handleDeleteDoc(doc.id, e)}
                              className="text-slate-500 hover:text-rose-400 p-1"
                              title="Xóa tài liệu"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>

                          <h4 className="font-semibold text-sm text-white truncate mt-1.5" title={doc.summary?.title || doc.filename}>
                            {doc.summary?.title || doc.filename}
                          </h4>
                          <p className="text-[11px] text-slate-400 line-clamp-2 mt-1">
                            {doc.summary?.executive_summary || doc.corrected_text || 'Đang phân tích...'}
                          </p>
                        </div>

                        {/* EXTRACTED BADGES */}
                        <div className="pt-2 border-t border-slate-800/80 flex flex-wrap items-center gap-1.5 mt-2">
                          {doc.entities?.so_van_ban && (
                            <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-amber-300 flex items-center gap-1">
                              <Hash className="w-3 h-3" /> {doc.entities.so_van_ban}
                            </span>
                          )}
                          {doc.entities?.ngay_ban_hanh && (
                            <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-emerald-300 flex items-center gap-1">
                              <Calendar className="w-3 h-3" /> {doc.entities.ngay_ban_hanh}
                            </span>
                          )}
                          {doc.html_tables?.length > 0 && (
                            <span className="text-[10px] px-2 py-0.5 rounded bg-violet-500/20 text-violet-300 flex items-center gap-1">
                              <Table className="w-3 h-3" /> {doc.html_tables.length} Bảng
                            </span>
                          )}
                          <span className="ml-auto text-[11px] text-indigo-400 font-medium flex items-center gap-0.5 group-hover:translate-x-0.5 transition">
                            Mở Trạm OCR <ChevronRight className="w-3.5 h-3.5" />
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* TAB 2: TRẠM HIỆU CHỈNH, ĐỊNH NGHĨA VÙNG & TRÍCH XUẤT OCR          */}
      {/* ================================================================= */}
      {activeTab === 'studio' && (
        <div className="flex-1 p-6">
          {!selectedDoc ? (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center">
              <p className="text-sm text-slate-400">
                Vui lòng chọn một tài liệu từ Kho Tài liệu hoặc tải lên tài liệu mới để mở Trạm OCR.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-12 gap-6 h-[calc(100vh-125px)]">
              {/* LEFT PANEL: IMAGE VIEWER & INTERACTIVE ZONE CROP OCR */}
              <div className="col-span-6 bg-slate-900 border border-slate-800 rounded-2xl flex flex-col overflow-hidden">
                {/* IMAGE TOOLBAR */}
                <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
                  <div className="flex items-center gap-2 min-w-0">
                    <Eye className="w-4 h-4 text-indigo-400 flex-shrink-0" />
                    <span className="text-xs font-semibold text-white truncate">{selectedDoc.filename}</span>
                    {selectedDoc.quality_info?.operations_applied &&
                      selectedDoc.quality_info.operations_applied.length > 0 && (
                        <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                          Đã tối ưu: {selectedDoc.quality_info.operations_applied.join(', ')}
                        </span>
                      )}
                  </div>

                  {/* ZONE CROP OCR CONTROLS */}
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={cropFieldLabel}
                      onChange={(e) => setCropFieldLabel(e.target.value)}
                      placeholder="Tên trường cần quét..."
                      className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white w-36 focus:outline-none focus:border-indigo-500"
                    />
                    <button
                      onClick={() => setIsCropping(!isCropping)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                        isCropping
                          ? 'bg-amber-500 text-slate-950 shadow-lg shadow-amber-500/30'
                          : 'bg-slate-800 hover:bg-slate-700 text-slate-200'
                      }`}
                    >
                      <Crop className="w-3.5 h-3.5" />
                      <span>{isCropping ? 'Kéo chuột trên ảnh...' : 'Khoanh vùng đọc OCR'}</span>
                    </button>
                  </div>
                </div>

                {/* IMAGE CANVAS */}
                <div className="flex-1 overflow-auto p-4 flex items-start justify-center bg-slate-950/80 relative select-none">
                  <div
                    className={`relative inline-block ${isCropping ? 'cursor-crosshair' : ''}`}
                    onMouseDown={handleImageMouseDown}
                    onMouseMove={handleImageMouseMove}
                    onMouseUp={handleImageMouseUp}
                  >
                    <img
                      ref={imgRef}
                      src={`${API_BASE}${selectedDoc.file_url}`}
                      alt={selectedDoc.filename}
                      draggable={false}
                      className="max-w-full rounded-lg border border-slate-800 shadow-xl"
                    />

                    {/* SELECTION BOX OVERLAY */}
                    {isCropping && dragStart && dragCurrent && (
                      <div
                        style={{
                          left: Math.min(dragStart.x, dragCurrent.x),
                          top: Math.min(dragStart.y, dragCurrent.y),
                          width: Math.abs(dragCurrent.x - dragStart.x),
                          height: Math.abs(dragCurrent.y - dragStart.y)
                        }}
                        className="absolute border-2 border-amber-400 bg-amber-400/20 pointer-events-none"
                      />
                    )}
                  </div>
                </div>

                {/* FOOTER METRICS */}
                <div className="px-4 py-2.5 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between text-[11px] text-slate-400">
                  <span>
                    Kích thước: {selectedDoc.quality_info?.width}×{selectedDoc.quality_info?.height}px • Góc nghiêng:{' '}
                    {selectedDoc.quality_info?.skew_angle}°
                  </span>
                  <span>
                    Layout phát hiện: <strong className="text-indigo-300 uppercase">{selectedDoc.ocr_mode}</strong>
                  </span>
                </div>
              </div>

              {/* RIGHT PANEL: MULTI-TAB OCR EDITOR, TABLE HTML, ENTITIES & ARKHAM SUMMARY */}
              <div className="col-span-6 bg-slate-900 border border-slate-800 rounded-2xl flex flex-col overflow-hidden">
                {/* SUB-NAVIGATION TABS */}
                <div className="px-4 py-2.5 border-b border-slate-800 bg-slate-950/50 flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setStudioSubTab('text')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                        studioSubTab === 'text' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <FileText className="w-3.5 h-3.5" />
                      <span>Sửa Văn bản OCR</span>
                    </button>

                    <button
                      onClick={() => setStudioSubTab('entities')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                        studioSubTab === 'entities' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <Tags className="w-3.5 h-3.5" />
                      <span>Trích xuất Thực thể</span>
                    </button>

                    <button
                      onClick={() => setStudioSubTab('summary')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                        studioSubTab === 'summary' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Tóm tắt & Sơ đồ</span>
                    </button>

                    <button
                      onClick={() => setStudioSubTab('table')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                        studioSubTab === 'table' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <Table className="w-3.5 h-3.5" />
                      <span>Bảng biểu ({selectedDoc.html_tables?.length || 0})</span>
                    </button>
                  </div>

                  <button
                    onClick={handleSaveEditedOCR}
                    disabled={isSaving}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow transition"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>{isSaving ? 'Đang lưu...' : 'Lưu & Phân tích lại'}</span>
                  </button>
                </div>

                {saveMessage && (
                  <div className="bg-emerald-950/90 border-b border-emerald-500/40 px-4 py-2 text-xs text-emerald-300 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>{saveMessage}</span>
                  </div>
                )}

                {/* SUB-TAB 1: SỬA VĂN BẢN OCR (HUMAN-IN-THE-LOOP) */}
                {studioSubTab === 'text' && (
                  <div className="flex-1 flex flex-col p-4 space-y-3 overflow-auto">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                        <Wand2 className="w-3.5 h-3.5 text-indigo-400" />
                        Văn bản đã qua VietOCR & Hiệu đính chính tả ProtonX (Có thể sửa trực tiếp):
                      </span>
                      <span className="text-[11px] text-slate-400">
                        Độ tin cậy: <strong className="text-emerald-400">{Math.round((selectedDoc.confidence || 0.93) * 100)}%</strong>
                      </span>
                    </div>

                    <textarea
                      value={editedText}
                      onChange={(e) => setEditedText(e.target.value)}
                      className="flex-1 w-full bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-100 font-mono leading-relaxed focus:outline-none focus:border-indigo-500 resize-none"
                      placeholder="Nội dung văn bản OCR..."
                    />

                    <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3">
                      <p className="text-[11px] font-semibold text-slate-400 mb-1">
                        Bản OCR gốc trước khi sửa chính tả (Raw VietOCR):
                      </p>
                      <p className="text-xs text-slate-400 whitespace-pre-wrap font-mono">
                        {selectedDoc.raw_text || '(Trống)'}
                      </p>
                    </div>
                  </div>
                )}

                {/* SUB-TAB 2: TRÍCH XUẤT THỰC THỂ 3 LỚP & ĐỊNH NGHĨA TRƯỜNG */}
                {studioSubTab === 'entities' && (
                  <div className="flex-1 p-4 space-y-4 overflow-auto">
                    {/* LỚP 1: HÀNH CHÍNH CHUẨN */}
                    <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                        Lớp 1: Định danh Văn bản Hành chính (Regex 100%)
                      </h4>
                      <div className="grid grid-cols-3 gap-3">
                        <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                          <span className="text-[11px] text-slate-400 block">Loại văn bản</span>
                          <strong className="text-sm text-white">{selectedDoc.entities?.loai_van_ban || 'Chưa rõ'}</strong>
                        </div>
                        <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                          <span className="text-[11px] text-slate-400 block">Số hiệu văn bản</span>
                          <strong className="text-sm text-amber-300">{selectedDoc.entities?.so_van_ban || 'Không có'}</strong>
                        </div>
                        <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                          <span className="text-[11px] text-slate-400 block">Ngày ban hành</span>
                          <strong className="text-sm text-emerald-300">{selectedDoc.entities?.ngay_ban_hanh || 'Không có'}</strong>
                        </div>
                      </div>
                    </div>

                    {/* LỚP 2: PHOBERT NER */}
                    <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-violet-400">
                        Lớp 2: Thực thể AI (PhoBERT / Electra NER)
                      </h4>

                      <div className="space-y-2">
                        <div>
                          <span className="text-xs text-slate-400 flex items-center gap-1.5 mb-1">
                            <UserCheck className="w-3.5 h-3.5 text-sky-400" /> Nhân sự / Sinh viên (PERSON):
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {(selectedDoc.entities?.PERSON || []).length === 0 ? (
                              <span className="text-xs text-slate-600">Chưa phát hiện</span>
                            ) : (
                              selectedDoc.entities?.PERSON?.map((p, idx) => (
                                <span key={idx} className="px-2.5 py-1 rounded-lg bg-sky-500/15 text-sky-300 border border-sky-500/30 text-xs">
                                  {p}
                                </span>
                              ))
                            )}
                          </div>
                        </div>

                        <div>
                          <span className="text-xs text-slate-400 flex items-center gap-1.5 mb-1">
                            <Building2 className="w-3.5 h-3.5 text-amber-400" /> Đơn vị / Phòng ban / Khoa (ORGANIZATION):
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {(selectedDoc.entities?.ORGANIZATION || []).length === 0 ? (
                              <span className="text-xs text-slate-600">Chưa phát hiện</span>
                            ) : (
                              selectedDoc.entities?.ORGANIZATION?.map((o, idx) => (
                                <span key={idx} className="px-2.5 py-1 rounded-lg bg-amber-500/15 text-amber-300 border border-amber-500/30 text-xs">
                                  {o}
                                </span>
                              ))
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* LỚP 3: CÁC TRƯỜNG ĐỊNH NGHĨA CUSTOM & VÙNG KHOANH */}
                    <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                          Lớp 3: Trường Trích xuất theo Định nghĩa & Khoanh vùng
                        </h4>
                        <button
                          onClick={() => {
                            const key = prompt('Nhập tên trường mới cần thêm:');
                            if (key) setCustomFieldsEdit((prev) => ({ ...prev, [key]: '' }));
                          }}
                          className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
                        >
                          <Plus className="w-3.5 h-3.5" /> Thêm trường
                        </button>
                      </div>

                      <div className="space-y-2">
                        {Object.entries(customFieldsEdit).map(([k, val]) => (
                          <div key={k} className="flex items-center gap-2">
                            <span className="w-40 text-xs font-medium text-slate-300 truncate" title={k}>
                              {k}:
                            </span>
                            <input
                              type="text"
                              value={val}
                              onChange={(e) =>
                                setCustomFieldsEdit((prev) => ({ ...prev, [k]: e.target.value }))
                              }
                              className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* SUB-TAB 3: TÓM TẮT VĂN BẢN & SƠ ĐỒ TRI THỨC CỤC BỘ */}
                {studioSubTab === 'summary' && (
                  <div className="flex-1 p-4 space-y-4 overflow-auto">
                    <div className="bg-gradient-to-br from-indigo-950/60 to-slate-950 border border-indigo-500/30 rounded-xl p-4 space-y-3">
                      <div className="flex items-center gap-2 text-indigo-300 text-xs font-bold uppercase">
                        <BookOpen className="w-4 h-4" />
                        <span>Bản Tóm tắt Điều hành (Arkham Executive Summary)</span>
                      </div>
                      <h3 className="text-sm font-bold text-white">{selectedDoc.summary?.title}</h3>
                      <p className="text-xs text-slate-300 leading-relaxed">
                        {selectedDoc.summary?.executive_summary}
                      </p>

                      {selectedDoc.summary?.key_points && selectedDoc.summary.key_points.length > 0 && (
                        <div className="pt-2 border-t border-indigo-500/20 space-y-1.5">
                          <span className="text-[11px] font-semibold text-indigo-300 block">
                            Các điểm cốt lõi (Key Points):
                          </span>
                          <ul className="space-y-1">
                            {selectedDoc.summary.key_points.map((pt, i) => (
                              <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                                <span className="text-indigo-400 font-bold">•</span>
                                <span>{pt}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>

                    {/* DOCUMENT KNOWLEDGE GRAPH */}
                    <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-2">
                        <Network className="w-4 h-4" />
                        <span>Sơ đồ Liên kết Thực thể trong Văn bản ({selectedDoc.graph_data?.nodes?.length || 0} thực thể)</span>
                      </h4>

                      <div className="space-y-2">
                        {(selectedDoc.graph_data?.edges || []).map((edge, idx) => {
                          const srcNode = selectedDoc.graph_data.nodes.find((n) => n.id === edge.source);
                          const tgtNode = selectedDoc.graph_data.nodes.find((n) => n.id === edge.target);
                          return (
                            <div
                              key={idx}
                              className="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs"
                            >
                              <span className="font-semibold text-indigo-300">{srcNode?.label || edge.source}</span>
                              <span className="px-2 py-0.5 rounded bg-slate-800 text-[10px] text-amber-300 font-mono">
                                ──[ {edge.label} ]──►
                              </span>
                              <span className="font-semibold text-emerald-300">{tgtNode?.label || edge.target}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}

                {/* SUB-TAB 4: BẢNG BIỂU HTML (TABLE OCR) */}
                {studioSubTab === 'table' && (
                  <div className="flex-1 p-4 space-y-4 overflow-auto">
                    {(!selectedDoc.html_tables || selectedDoc.html_tables.length === 0) ? (
                      <div className="text-center py-12 space-y-3">
                        <Table className="w-10 h-10 text-slate-600 mx-auto" />
                        <p className="text-xs text-slate-400">
                          Tài liệu này chưa bóc bảng hoặc không có cấu trúc kẻ bảng.
                        </p>
                      </div>
                    ) : (
                      selectedDoc.html_tables.map((html, idx) => (
                        <div key={idx} className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-violet-300">Bảng #{idx + 1} (PP-StructureV3 + VietOCR)</span>
                          </div>
                          <div
                            className="ocr-table-preview overflow-x-auto text-slate-200"
                            dangerouslySetInnerHTML={{ __html: html }}
                          />
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ================================================================= */}
      {/* TAB 3: ĐỊNH NGHĨA MẪU TRÍCH XUẤT OCR (OCR SCHEMA BUILDER)          */}
      {/* ================================================================= */}
      {activeTab === 'rules' && (
        <div className="flex-1 p-6 grid grid-cols-12 gap-6">
          <div className="col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Plus className="w-4 h-4 text-indigo-400" />
              <span>Tạo Mẫu Định nghĩa Trích xuất OCR Mới</span>
            </h3>
            <p className="text-xs text-slate-400">
              Định nghĩa trước các trường thông tin cần lấy cho từng loại hồ sơ (VD: Học bạ, Quyết định, Đơn xin học, Hóa đơn).
            </p>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-400 block mb-1">Tên mẫu hồ sơ</label>
                <input
                  type="text"
                  value={newTplName}
                  onChange={(e) => setNewTplName(e.target.value)}
                  placeholder="VD: Hồ sơ Xét duyệt Học bổng DAU"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 block mb-1">Mô tả</label>
                <input
                  type="text"
                  value={newTplDesc}
                  onChange={(e) => setNewTplDesc(e.target.value)}
                  placeholder="Mô tả ngắn gọn..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-300">Danh sách trường cần bóc tách (Regex / Từ khóa)</label>
                  <button
                    onClick={() =>
                      setNewTplFields([
                        ...newTplFields,
                        { key: `truong_${newTplFields.length + 1}`, label: 'Trường mới', pattern: 'Từ_khóa:\\s*([^\\n]+)', type: 'regex' }
                      ])
                    }
                    className="text-xs text-indigo-400 hover:underline"
                  >
                    + Thêm dòng
                  </button>
                </div>

                {newTplFields.map((f, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                    <input
                      type="text"
                      value={f.key}
                      onChange={(e) => {
                        const copy = [...newTplFields];
                        copy[i].key = e.target.value;
                        copy[i].label = e.target.value;
                        setNewTplFields(copy);
                      }}
                      placeholder="Tên trường"
                      className="col-span-5 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white"
                    />
                    <input
                      type="text"
                      value={f.pattern}
                      onChange={(e) => {
                        const copy = [...newTplFields];
                        copy[i].pattern = e.target.value;
                        setNewTplFields(copy);
                      }}
                      placeholder="Biểu thức Regex"
                      className="col-span-7 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-amber-300 font-mono"
                    />
                  </div>
                ))}
              </div>

              <button
                onClick={handleCreateTemplate}
                className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg transition"
              >
                Lưu Mẫu Định Nghĩa OCR
              </button>
            </div>
          </div>

          <div className="col-span-7 space-y-4">
            <h3 className="text-sm font-bold text-white">Các Mẫu Định nghĩa OCR Đang Hoạt động</h3>
            <div className="space-y-3">
              {templates.map((tpl) => (
                <div key={tpl.id} className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-indigo-300">{tpl.name}</h4>
                    <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                      {tpl.fields?.length || 0} quy tắc trích xuất
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{tpl.description}</p>
                  <div className="grid grid-cols-2 gap-2 pt-2">
                    {tpl.fields?.map((f, idx) => (
                      <div key={idx} className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
                        <span className="text-slate-300 font-semibold">{f.label || f.key}: </span>
                        <code className="text-amber-300 text-[11px]">{f.pattern}</code>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* TAB 4: SƠ ĐỒ MẠNG LƯỚI VĂN BẢN & PHÁT HIỆN MÂU THUẪN (ARKHAM GRAPH) */}
      {/* ================================================================= */}
      {activeTab === 'graph' && (
        <div className="flex-1 p-6 grid grid-cols-12 gap-6">
          {/* LEFT: INTERACTIVE SVG FORCE GRAPH VISUALIZER */}
          <div className="col-span-8 bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Network className="w-4 h-4 text-indigo-400" />
                  <span>Sơ đồ Mạng lưới Văn bản & Thực thể Toàn trường (Arkham Knowledge Graph)</span>
                </h3>
                <p className="text-xs text-slate-400">
                  Tự động liên kết các Quyết định, Thông báo, Sinh viên, Phòng ban và Thời gian từ tất cả văn bản OCR.
                </p>
              </div>
              <div className="flex items-center gap-3 text-[11px]">
                <span className="flex items-center gap-1 text-indigo-300">● Văn bản</span>
                <span className="flex items-center gap-1 text-sky-300">● Nhân sự / SV</span>
                <span className="flex items-center gap-1 text-amber-300">● Phòng ban / Khoa</span>
                <span className="flex items-center gap-1 text-emerald-300">● Ngày ký</span>
              </div>
            </div>

            <div className="flex-1 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-center overflow-hidden relative min-h-[460px]">
              {(!globalGraph || globalGraph.nodes.length === 0) ? (
                <p className="text-xs text-slate-500">Chưa có dữ liệu sơ đồ. Hãy tải lên ít nhất 1 văn bản.</p>
              ) : (
                <svg viewBox="0 0 800 500" className="w-full h-full">
                  {(() => {
                    const nodes = globalGraph.nodes.slice(0, 32);
                    const coords: Record<string, { x: number; y: number }> = {};
                    const cx = 400;
                    const cy = 250;

                    nodes.forEach((n, idx) => {
                      const angle = (2 * Math.PI * idx) / nodes.length;
                      const radius = n.type === 'DOCUMENT' ? 95 : 195;
                      coords[n.id] = {
                        x: cx + radius * Math.cos(angle),
                        y: cy + radius * Math.sin(angle)
                      };
                    });

                    return (
                      <>
                        {/* EDGES */}
                        {globalGraph.edges.map((e, idx) => {
                          const s = coords[e.source];
                          const t = coords[e.target];
                          if (!s || !t) return null;
                          return (
                            <g key={idx}>
                              <line
                                x1={s.x}
                                y1={s.y}
                                x2={t.x}
                                y2={t.y}
                                stroke="#334155"
                                strokeWidth={Math.min(3, e.weight || 1.2)}
                              />
                            </g>
                          );
                        })}

                        {/* NODES */}
                        {nodes.map((n) => {
                          const pt = coords[n.id];
                          const color =
                            n.type === 'DOCUMENT'
                              ? '#6366f1'
                              : n.type === 'PERSON'
                              ? '#38bdf8'
                              : n.type === 'ORGANIZATION'
                              ? '#f59e0b'
                              : '#10b981';
                          return (
                            <g key={n.id} transform={`translate(${pt.x}, ${pt.y})`}>
                              <circle r={n.type === 'DOCUMENT' ? 18 : 13} fill={color} fillOpacity={0.25} stroke={color} strokeWidth={2} />
                              <text
                                y={n.type === 'DOCUMENT' ? 28 : 24}
                                textAnchor="middle"
                                fill="#e2e8f0"
                                fontSize="10"
                                fontWeight="600"
                              >
                                {n.label.length > 22 ? n.label.slice(0, 22) + '…' : n.label}
                              </text>
                            </g>
                          );
                        })}
                      </>
                    );
                  })()}
                </svg>
              )}
            </div>
          </div>

          {/* RIGHT: CENTRALITY RANKING & CONTRADICTION DETECTOR */}
          <div className="col-span-4 space-y-4">
            {/* CONTRADICTIONS CHECK */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-rose-400 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                <span>Kiểm tra Mâu thuẫn Văn bản (Arkham Contradictions)</span>
              </h4>
              {(!globalGraph?.contradictions || globalGraph.contradictions.length === 0) ? (
                <div className="bg-emerald-950/30 border border-emerald-500/30 rounded-xl p-3 text-xs text-emerald-300 flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 flex-shrink-0" />
                  <span>Không phát hiện mâu thuẫn số hiệu hoặc ngày ký giữa các hồ sơ hiện tại.</span>
                </div>
              ) : (
                <div className="space-y-2">
                  {globalGraph.contradictions.map((c, i) => (
                    <div key={i} className="bg-rose-950/40 border border-rose-500/40 rounded-xl p-3 text-xs space-y-1">
                      <strong className="text-rose-300 block">{c.type}</strong>
                      <p className="text-slate-300">{c.detail}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* TOP ENTITIES BY DEGREE CENTRALITY */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                <Layers className="w-4 h-4" />
                <span>Thực thể Trung tâm (PageRank / Centrality)</span>
              </h4>
              <div className="space-y-2 max-h-80 overflow-auto">
                {(globalGraph?.nodes || [])
                  .slice()
                  .sort((a, b) => (b.degree || 0) - (a.degree || 0))
                  .slice(0, 12)
                  .map((n, i) => (
                    <div key={n.id} className="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs">
                      <div className="truncate pr-2">
                        <span className="text-slate-500 mr-2">#{i + 1}</span>
                        <span className="font-medium text-white">{n.label}</span>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] flex-shrink-0">
                        {n.degree} liên kết
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
