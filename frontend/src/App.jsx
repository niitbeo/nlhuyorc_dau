import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle, ArrowLeft, ArrowRight, BookOpen, Building2, CalendarDays,
  Check, CheckCircle2, ChevronDown, ChevronRight, Database,
  Download, FilePlus2, Files, FileSearch, FileText, FolderOpen, History,
  LayoutDashboard, Link2, LockKeyhole, LogOut, Menu, Plus, RefreshCw,
  ScanText, Search, Settings2, KeyRound, ShieldCheck, SlidersHorizontal, Sparkles, Trash2,
  FlaskConical, Timer, BarChart3,
  Upload, UsersRound, X,
} from 'lucide-react';

const KINDS = {
  incoming: 'Công văn đến', outgoing: 'Công văn đi', iso: 'Tài liệu ISO',
  curriculum: 'Chương trình đào tạo', lesson: 'Giáo án / học liệu', other: 'Tài liệu khác',
};
const KIND_ICONS = {
  incoming: FileText, outgoing: FilePlus2, iso: ShieldCheck,
  curriculum: BookOpen, lesson: BookOpen, other: Files,
};
const VISIBILITIES = { public: 'Công khai', department: 'Trong đơn vị', restricted: 'Hạn chế' };
const ISO_ROLES = { procedure: 'Quy trình', form: 'Biểu mẫu', reference: 'Văn bản viện dẫn', guide: 'Hướng dẫn', regulation: 'Quy định', other: 'Khác' };
const STATUSES = {
  queued: 'Chờ xử lý', importing: 'Đang nhập', processing: 'Đang xử lý', ready: 'Sẵn sàng', failed: 'Có lỗi',
  proposed: 'Chờ xác nhận', confirmed: 'Đã xác nhận', rejected: 'Đã bỏ',
};
const FIELDS = {
  document_number: 'Số văn bản', signed_date: 'Ngày ký', signer: 'Người ký',
  sender: 'Nơi gửi', recipient: 'Nơi nhận', iso_code: 'Mã ISO',
  effective_date: 'Ngày hiệu lực', revision: 'Lần sửa đổi', program: 'Chương trình',
  academic_year: 'Năm học', course_code: 'Mã học phần', course_name: 'Tên học phần',
  person: 'Người', organization: 'Đơn vị',
};
const RELATIONS = {
  cites: 'Viện dẫn', replaces: 'Thay thế', in_file: 'Thuộc hồ sơ',
  in_course: 'Thuộc học phần', related: 'Liên quan',
};
const ACCEPTED_FILES = '.pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff';

async function request(path, options = {}, token = '') {
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(typeof detail === 'string' ? detail : `Không thể hoàn tất yêu cầu (${response.status})`);
  }
  return response;
}

function dateLabel(value) {
  if (!value) return '—';
  const date = new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z'));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('vi-VN');
}

function Status({ value }) {
  return <span className={`status status-${value || 'queued'}`}><span className="status-dot" />{STATUSES[value] || value || 'Đang xử lý'}</span>;
}

function EmptyState({ icon: Icon = FolderOpen, title, description, action }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={25} /></div>
    <h3>{title}</h3><p>{description}</p>{action}</div>;
}

function DocumentCard({ doc, onOpen, compact = false }) {
  const Icon = KIND_ICONS[doc.kind] || Files;
  return <button className={`document-card ${compact ? 'document-card-compact' : ''}`} type="button" onClick={() => onOpen(doc.id)}>
    <span className={`file-icon file-icon-${doc.kind}`}><Icon size={21} strokeWidth={1.8} /></span>
    <span className="document-card-body"><strong>{doc.title}</strong><span className="document-subtitle">{KINDS[doc.kind] || doc.kind} <span className="separator">·</span> {doc.department}</span>{!compact && doc.collection_key && <span className="document-source">{doc.collection_key}</span>}</span>
    {!compact && <span className="document-date"><CalendarDays size={14} />{dateLabel(doc.created_at)}</span>}
    <Status value={doc.current_version_id ? 'ready' : 'queued'} />
    <ChevronRight className="row-arrow" size={18} />
  </button>;
}

function Login({ onLogin }) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    setWorking(true); setError('');
    try {
      const form = new FormData(event.currentTarget);
      await onLogin(Object.fromEntries(form));
    } catch (exc) { setError(exc.message); }
    finally { setWorking(false); }
  }
  return <div className="login-layout">
    <div className="login-panel"><div className="login-main">
      <div className="brand brand-login"><div className="brand-mark"><Files size={22} /></div><div><strong>NLHUYOCR</strong><small>DOCUMENT WORKSPACE</small></div></div>
      <div className="login-copy"><span className="eyebrow"><span className="eyebrow-line" />NỀN TẢNG QUẢN LÝ TÀI LIỆU</span>
        <h1>Chào mừng<br />trở lại<span className="accent-dot">.</span></h1>
        <p>Đăng nhập để quản lý hồ sơ, kiểm tra kết quả OCR và tra cứu tài liệu của đơn vị.</p></div>
      <form className="login-form" onSubmit={submit}>
        <label>Tên đăng nhập<input name="username" autoComplete="username" placeholder="Nhập tài khoản" required /></label>
        <label>Mật khẩu<input name="password" type="password" autoComplete="current-password" placeholder="Nhập mật khẩu" required /></label>
        {error && <p className="form-error"><AlertCircle size={16} />{error}</p>}
        <button className="button button-primary login-submit" type="submit" disabled={working}>{working ? 'Đang đăng nhập…' : 'Đăng nhập'}<ArrowRight size={18} /></button>
      </form>
      <p className="login-foot">Chỉ nhân sự được phân quyền mới có thể truy cập kho hồ sơ.</p>
    </div></div>
    <div className="login-showcase"><div className="showcase-glow" /><div className="showcase-content">
      <div className="showcase-top"><span className="showcase-badge"><ShieldCheck size={15} /> Không gian làm việc nội bộ</span><span>01 / 03</span></div>
      <div className="showcase-visual"><div className="visual-sheet visual-sheet-back" /><div className="visual-sheet visual-sheet-front"><div className="visual-sheet-icon"><ScanText size={30} /></div><span className="visual-line wide" /><span className="visual-line" /><span className="visual-line short" /><div className="visual-stamp"><Check size={22} /></div></div><div className="visual-float"><Sparkles size={18} /><span>OCR tiếng Việt</span></div></div>
      <div className="showcase-bottom"><span className="showcase-overline">MỌI TÀI LIỆU, MỘT NƠI QUẢN LÝ</span><h2>Lưu trữ rõ ràng.<br />Tra cứu nhanh hơn.</h2><p>Từ công văn đến học liệu, mỗi hồ sơ đều có nguồn, phiên bản và quyền truy cập cụ thể.</p></div>
    </div></div>
  </div>;
}

function Sidebar({ screen, setScreen, me, onLogout, mobileOpen, setMobileOpen }) {
  const items = [
    { id: 'dashboard', label: 'Tổng quan', icon: LayoutDashboard },
    { id: 'documents', label: 'Kho tài liệu', icon: Files },
    { id: 'search', label: 'Tra cứu', icon: Search },
    { id: 'upload', label: 'Nhập tài liệu', icon: FilePlus2 },
    ...(me?.role === 'admin' ? [{ id: 'models', label: 'Kiểm tra model', icon: FlaskConical }] : []),
  ];
  return <><div className={`sidebar-backdrop ${mobileOpen ? 'visible' : ''}`} onClick={() => setMobileOpen(false)} />
    <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
      <div className="sidebar-head"><div className="brand"><div className="brand-mark"><Files size={21} /></div><div><strong>NLHUYOCR</strong><small>DOCUMENT WORKSPACE</small></div></div><button className="icon-button mobile-close" onClick={() => setMobileOpen(false)} aria-label="Đóng menu"><X size={20} /></button></div>
      <div className="sidebar-section-label">KHÔNG GIAN LÀM VIỆC</div>
      <nav className="sidebar-nav" aria-label="Điều hướng chính">{items.map(({ id, label, icon: Icon }) => <button key={id} type="button" className={`nav-item ${(screen === id || (screen === 'detail' && id === 'documents')) ? 'active' : ''}`} aria-current={(screen === id || (screen === 'detail' && id === 'documents')) ? 'page' : undefined} onClick={() => { setScreen(id); setMobileOpen(false); }}><Icon size={19} strokeWidth={1.9} />{label}{id === 'upload' && <Plus size={16} className="nav-end" />}</button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-help"><div className="help-icon"><ScanText size={20} /></div><strong>Nhận dạng tài liệu</strong><p>PDF và ảnh được xử lý bằng OCR tiếng Việt ngay tại máy chủ.</p><a href="http://127.0.0.1:8000/" target="_blank" rel="noreferrer">Mở công cụ OCR <ArrowRight size={15} /></a></div>
        <button className="sidebar-user" onClick={onLogout} title="Đăng xuất"><span className="avatar">{me?.username?.slice(0, 1).toUpperCase() || 'U'}</span><span><strong>{me?.username}</strong><small>{me?.department}</small></span><LogOut size={18} /></button></div>
    </aside></>;
}

function Dashboard({ documents, me, health, stats, openDocument, setScreen }) {
  const counts = useMemo(() => ({
    total: stats?.total ?? documents.length,
    incoming: stats?.kinds?.incoming ?? documents.filter(d => d.kind === 'incoming').length,
    outgoing: stats?.kinds?.outgoing ?? documents.filter(d => d.kind === 'outgoing').length,
    learning: stats ? (stats.kinds?.curriculum || 0) + (stats.kinds?.lesson || 0) : documents.filter(d => ['curriculum', 'lesson'].includes(d.kind)).length,
  }), [documents, stats]);
  const cards = [
    { label: 'Tổng hồ sơ', value: counts.total, icon: Files, tint: 'teal' },
    { label: 'Công văn đến', value: counts.incoming, icon: Download, tint: 'blue' },
    { label: 'Công văn đi', value: counts.outgoing, icon: Upload, tint: 'purple' },
    { label: 'Học liệu', value: counts.learning, icon: BookOpen, tint: 'amber' },
  ];
  return <div className="page-flow">
    <section className="welcome-banner"><div className="welcome-text"><span className="eyebrow light">KHO HỒ SƠ ĐIỆN TỬ</span><h1>Xin chào, {me?.username}<span className="welcome-wave"> ✦</span></h1><p>Mọi văn bản và tài liệu của đơn vị, được sắp xếp để bạn tìm thấy nhanh hơn.</p><button className="button button-white" onClick={() => setScreen('upload')}><Plus size={18} /> Nhập tài liệu mới</button></div><div className="welcome-art" aria-hidden="true"><div className="art-ring art-ring-one" /><div className="art-ring art-ring-two" /><div className="art-document"><FileText size={52} strokeWidth={1.1} /><span /><span /><span /></div><div className="art-check"><Check size={23} /></div></div></section>
    <div className="section-heading"><div><span className="eyebrow">TỔNG QUAN</span><h2>Tình hình tài liệu</h2></div><span className="section-note"><span className="online-dot" /> Dữ liệu nội bộ</span></div>
    <div className="metric-grid">{cards.map(({ label, value, icon: Icon, tint }) => <div className="metric-card" key={label}><div className={`metric-icon tint-${tint}`}><Icon size={22} /></div><div className="metric-value">{value.toLocaleString('vi-VN')}</div><div className="metric-label">{label}</div></div>)}</div>
    <div className="dashboard-grid"><section className="surface recent-section"><div className="surface-head"><div><span className="eyebrow">GẦN ĐÂY</span><h2>Hồ sơ mới cập nhật</h2></div><button className="text-button" onClick={() => setScreen('documents')}>Xem tất cả <ArrowRight size={17} /></button></div>
      {documents.length ? <div className="document-list">{documents.slice(0, 6).map(doc => <DocumentCard key={doc.id} doc={doc} onOpen={openDocument} compact />)}</div> : <EmptyState title="Chưa có tài liệu" description="Bắt đầu bằng cách nhập tài liệu đầu tiên vào kho hồ sơ." action={<button className="button button-primary" onClick={() => setScreen('upload')}><Plus size={17} /> Nhập tài liệu</button>} />}</section>
      <aside className="workspace-panel"><div className="workspace-panel-icon"><Database size={24} /></div><span className="eyebrow">HỆ THỐNG</span><h3>Tra cứu luôn sẵn sàng</h3><p>{health?.semantic_search_enabled && health?.embedding_local_ready ? 'Tìm kiếm ngữ nghĩa nội bộ đang hoạt động.' : 'Tìm kiếm từ khóa trên nội dung OCR và hồ sơ đang hoạt động.'}</p><div className="workspace-divider" /><div className="workspace-feature"><CheckCircle2 size={18} /><span>Phân quyền theo đơn vị</span></div><div className="workspace-feature"><CheckCircle2 size={18} /><span>Lưu lịch sử phiên bản</span></div><div className="workspace-feature"><CheckCircle2 size={18} /><span>Dẫn chứng theo trang</span></div><button className="button button-outline full" onClick={() => setScreen('search')}>Bắt đầu tra cứu <ArrowRight size={17} /></button></aside></div>
  </div>;
}

function Documents({ token, notify, openDocument, setScreen }) {
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [department, setDepartment] = useState('all');
  const [collection, setCollection] = useState('all');
  const [facets, setFacets] = useState({ departments: [], collections: [] });
  const [page, setPage] = useState(0);
  const [result, setResult] = useState({ items: [], total: 0 });
  const [refreshKey, setRefreshKey] = useState(0);
  const collections = useMemo(() => facets.collections.filter(item => department === 'all' || item.department === department).map(item => item.collection_key), [facets, department]);
  useEffect(() => {
    request('/api/documents/facets', {}, token).then(response => response.json()).then(setFacets)
      .catch(error => notify(error.message, true));
  }, [token, notify, refreshKey]);
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ limit: '50', offset: String(page * 50) });
      if (query.trim()) params.set('q', query.trim());
      if (kind !== 'all') params.set('kind', kind);
      if (department !== 'all') params.set('department', department);
      if (collection !== 'all') params.set('collection', collection);
      request(`/api/documents/page?${params}`, {}, token).then(response => response.json())
        .then(value => { if (live) setResult(value); })
        .catch(error => { if (live) notify(error.message, true); });
    }, 220);
    return () => { live = false; clearTimeout(timer); };
  }, [token, notify, page, query, kind, department, collection, refreshKey]);
  const shown = result.items;
  return <div className="page-flow"><div className="page-title-row"><div><span className="eyebrow">THƯ VIỆN TÀI LIỆU</span><h1>Kho tài liệu</h1><p>Quản lý, theo dõi và mở lại mọi hồ sơ bạn có quyền truy cập.</p></div><button className="button button-primary" onClick={() => setScreen('upload')}><Plus size={18} /> Nhập tài liệu</button></div>
    <section className="surface documents-surface"><div className="toolbar"><div className="toolbar-search"><Search size={19} /><input value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} placeholder="Lọc theo tên, đường dẫn hoặc đơn vị…" aria-label="Lọc tài liệu" /></div><div className="toolbar-actions"><label className="select-wrap"><SlidersHorizontal size={17} /><select value={kind} onChange={event => { setKind(event.target.value); setPage(0); }} aria-label="Lọc loại tài liệu"><option value="all">Tất cả loại</option>{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={15} /></label><button className="icon-button refresh-button" onClick={() => setRefreshKey(value => value + 1)} title="Làm mới danh sách" aria-label="Làm mới danh sách"><RefreshCw size={18} /></button></div></div>
      <div className="folder-filters"><label>Đơn vị<select value={department} onChange={event => { setDepartment(event.target.value); setCollection('all'); setPage(0); }}><option value="all">Tất cả đơn vị</option>{facets.departments.map(value => <option value={value} key={value}>{value}</option>)}</select></label><label>Bộ hồ sơ / quy trình<select value={collection} onChange={event => { setCollection(event.target.value); setPage(0); }}><option value="all">Tất cả bộ hồ sơ</option>{collections.map(value => <option value={value} key={value}>{value}</option>)}</select></label></div>
      <div className="table-caption"><strong>Danh sách hồ sơ</strong><span>{result.total.toLocaleString('vi-VN')} tài liệu</span></div>
      {shown.length ? <div className="document-list">{shown.map(doc => <DocumentCard key={doc.id} doc={doc} onOpen={openDocument} />)}</div> : <EmptyState icon={FileSearch} title="Không có hồ sơ phù hợp" description={result.total ? 'Thử từ khóa hoặc bộ lọc khác.' : 'Kho tài liệu của bạn chưa có hồ sơ nào.'} />}
      {result.total > 50 && <div className="document-pagination"><button className="button button-outline button-small" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Trang trước</button><span>Trang {page + 1} / {Math.ceil(result.total / 50)}</span><button className="button button-outline button-small" disabled={(page + 1) * 50 >= result.total} onClick={() => setPage(value => value + 1)}>Trang sau</button></div>}
    </section></div>;
}

function BatchUpload({ me, token, notify, onImported }) {
  const [batches, setBatches] = useState([]);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    const list = await (await request('/api/import-batches?limit=10', {}, token)).json();
    setBatches(list);
    if (list.some(item => item.status === 'importing' || item.status === 'queued')) onImported();
  }, [token, onImported]);
  useEffect(() => {
    refresh().catch(error => notify(error.message, true));
    const timer = setInterval(() => refresh().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [refresh, notify]);
  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const body = new FormData(form);
    if (!body.getAll('files').some(file => file instanceof File && file.size)) return;
    setBusy(true);
    try {
      const result = await (await request('/api/import-batches', { method: 'POST', body }, token)).json();
      form.reset(); await refresh();
      notify(`Đã nhận đợt nhập ${result.source_name}. Hệ thống đang xếp hồ sơ vào hàng đợi OCR.`);
    } catch (error) { notify(error.message, true); }
    finally { setBusy(false); }
  }
  async function retry(id) {
    try { await request(`/api/import-batches/${id}/retry`, { method: 'POST' }, token); await refresh(); }
    catch (error) { notify(error.message, true); }
  }
  return <section className="surface form-surface batch-section"><div className="surface-head"><div><span className="eyebrow">NHẬP HÀNG LOẠT</span><h2>Nhiều tài liệu, nhiều đợt</h2></div><Files size={24} /></div>
    <p className="section-intro">Chọn nhiều tệp hoặc ZIP/RAR. Hệ thống giữ cấu trúc thư mục, tự đề xuất loại tài liệu và xử lý OCR trong nền. Bạn có thể tiếp tục nhập các đợt khác.</p>
    <form className="form-stack" onSubmit={submit}>
      <label className="upload-drop"><div className="upload-drop-icon"><FolderOpen size={23} /></div><strong>Chọn tệp hoặc archive</strong><span>PDF, Word, Excel, ảnh, TXT, ZIP, RAR · tối đa 1,5 GiB mỗi đợt</span><input name="files" type="file" accept={`${ACCEPTED_FILES},.zip,.rar`} multiple required /></label>
      <div className="form-grid"><label>Gợi ý phân loại<select name="kind_hint" defaultValue=""><option value="">Tự nhận diện</option><option value="iso">Bộ tài liệu ISO</option></select></label><label>Đơn vị mặc định<input name="department" defaultValue={me.department} required /></label></div>
      <div className="form-grid"><label>Quyền xem<select name="visibility" defaultValue="department"><option value="department">Trong đơn vị</option><option value="restricted">Hạn chế</option><option value="public">Nhân sự toàn trường</option></select></label>{me.role === 'admin' && <label className="batch-check"><input type="checkbox" name="derive_department" value="true" /> Lấy đơn vị từ thư mục ISO</label>}</div>
      <div className="form-footer"><span><LockKeyhole size={16} /> Bản gốc lưu nội bộ; tệp trùng chỉ lưu một lần</span><button className="button button-primary" disabled={busy}>{busy ? 'Đang tải lên…' : 'Nhập loạt và xử lý'} <ArrowRight size={18} /></button></div>
    </form>
    <div className="batch-history"><div className="surface-head"><h3>Đợt nhập gần đây</h3><button className="button button-outline button-small" onClick={() => refresh().catch(error => notify(error.message, true))}><RefreshCw size={15} /> Làm mới</button></div>
      {batches.length ? batches.map(item => <div className="batch-row" key={item.id}><div className="batch-row-title"><strong>{item.source_name}</strong><span className={`status status-${item.status}`}><span className="status-dot" />{item.status === "ready" ? "Đã nhập vào kho" : STATUSES[item.status]}</span></div><small>{dateLabel(item.created_at)} · {item.imported_entries}/{item.total_entries || '…'} tệp đã đưa vào kho · {item.skipped_entries} tệp bỏ qua</small><div className="batch-progress"><span style={{ width: `${item.total_entries ? Math.min(100, Math.round((item.imported_entries + item.skipped_entries) * 100 / item.total_entries)) : 0}%` }} /></div><small>OCR: {Object.entries(item.ocr || {}).map(([status, count]) => `${STATUSES[status] || status} ${count}`).join(' · ') || 'Chưa xếp hàng'}</small>{item.error && <p className="form-error">{item.error}</p>}{item.recent_errors?.length > 0 && <details className="batch-errors"><summary>{item.recent_errors.length} lỗi gần đây</summary>{item.recent_errors.map((entry, index) => <p key={index}>{entry.archive_path}: {entry.error}</p>)}</details>}{item.status === 'failed' && <button className="button button-outline button-small" onClick={() => retry(item.id)}>Thử lại đợt nhập</button>}</div>) : <p className="section-intro">Chưa có đợt nhập loạt.</p>}
    </div>
  </section>;
}

function UploadPage({ me, token, notify, onImported, onSubmit, working }) {
  return <div className="page-flow"><div className="page-title-row"><div><span className="eyebrow">BỔ SUNG HỒ SƠ</span><h1>Nhập tài liệu</h1><p>Tải bản gốc lên để lưu trữ, nhận dạng chữ và tạo nội dung tra cứu.</p></div></div>
    <div className="form-layout"><section className="surface form-surface"><div className="surface-head"><div><span className="eyebrow">THÔNG TIN TÀI LIỆU</span><h2>Tạo hồ sơ mới</h2></div><span className="step-pill">Bước 1 / 1</span></div>
      <form className="form-stack" onSubmit={onSubmit}><div className="form-grid"><label>Loại tài liệu<select name="kind" defaultValue="incoming">{Object.entries(KINDS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>Đơn vị quản lý<input name="department" defaultValue={me?.department || ''} required /></label></div>
        <label>Tiêu đề hồ sơ<input name="title" placeholder="Ví dụ: Quyết định về công tác đào tạo năm 2026" maxLength="300" required /></label>
        <label>Quyền truy cập<select name="visibility" defaultValue="department"><option value="department">Người trong cùng đơn vị</option><option value="restricted">Chỉ người được cấp quyền</option><option value="public">Nhân sự toàn trường</option></select></label>
        <label className="upload-drop"><div className="upload-drop-icon"><Upload size={23} /></div><strong>Chọn tệp tài liệu</strong><span>PDF, Word, Excel, TXT, Markdown hoặc ảnh · tối đa 50 MiB</span><input name="file" type="file" accept={ACCEPTED_FILES} required /></label>
        <details className="advanced-box"><summary><Database size={17} /> Đã có kết quả OCR? Nhập nội dung theo trang <ChevronDown size={16} /></summary><label>JSON các trang OCR<textarea name="ocr_pages_json" rows="4" placeholder='[{"text":"Nội dung trang 1"}, {"text":"Nội dung trang 2"}]' /></label></details>
        <div className="form-footer"><span><LockKeyhole size={16} /> Tài liệu được lưu trên máy chủ nội bộ</span><button className="button button-primary" type="submit" disabled={working}>{working ? 'Đang tải lên…' : 'Tải lên và xử lý'} <ArrowRight size={18} /></button></div>
      </form></section><aside className="upload-aside"><div className="aside-number">01</div><ScanText size={29} /><h3>Từ tệp gốc đến hồ sơ có thể tra cứu</h3><p>Hệ thống trích nội dung PDF hoặc dùng PaddleOCR dò dòng và NLHUYOCR đọc chữ in, chữ viết tay trên trang ảnh. Mỗi trường dữ liệu đề xuất đều kèm trang nguồn để bạn kiểm tra.</p><div className="aside-steps"><div><span>1</span>Tải tệp và chọn quyền xem</div><div><span>2</span>Hệ thống đọc chữ, tách dữ liệu</div><div><span>3</span>Kiểm tra và xác nhận hồ sơ</div></div></aside></div>
    <BatchUpload me={me} token={token} notify={notify} onImported={onImported} />
  </div>;
}

function SearchPage({ query, setQuery, results, onSearch, working, searched, openDocument }) {
  return <div className="page-flow"><div className="page-title-row"><div><span className="eyebrow">TRA CỨU NỘI BỘ</span><h1>Tìm trong kho hồ sơ</h1><p>Tìm theo số công văn, học phần hoặc bất kỳ nội dung nào đã được OCR.</p></div></div>
    <section className="search-hero"><div className="search-hero-icon"><FileSearch size={25} /></div><h2>Bạn cần tìm tài liệu gì?</h2><p>Kết quả chỉ gồm những hồ sơ bạn có quyền truy cập.</p><form className="search-large" onSubmit={onSearch}><Search size={21} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Nhập từ khóa, số văn bản, tên học phần…" required autoFocus /><button className="button button-primary" type="submit" disabled={working}>{working ? 'Đang tìm…' : 'Tìm kiếm'} <ArrowRight size={17} /></button></form></section>
    {searched && <section className="surface search-results"><div className="surface-head"><div><span className="eyebrow">KẾT QUẢ TRA CỨU</span><h2>{results.length ? `${results.length} kết quả phù hợp` : 'Không tìm thấy kết quả'}</h2></div></div>{results.length ? <div className="result-list">{results.map((result, index) => <button className="result-card" key={`${result.document_id}-${result.page_no}-${index}`} onClick={() => openDocument(result.document_id)}><span className="result-icon"><FileText size={21} /></span><span><strong>{result.title}</strong><small>Trang {result.page_no} · {KINDS[result.kind] || 'Tài liệu'}</small><p>{result.text?.slice(0, 300)}</p></span><ArrowRight size={18} /></button>)}</div> : <EmptyState icon={Search} title="Chưa có kết quả" description="Hãy thử cụm từ ngắn hơn hoặc kiểm tra cách viết của từ khóa." />}</section>}
  </div>;
}

function FieldItem({ field, canWrite, onReview }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(field.value);
  return <div className="field-item"><div className="field-item-top"><div><span className="field-name">{FIELDS[field.field_key] || field.field_key}</span><Status value={field.status} /></div><span className="page-tag">Trang {field.page_no}</span></div>
    {editing ? <form className="field-edit" onSubmit={async event => { event.preventDefault(); await onReview(field, value, 'confirmed'); setEditing(false); }}><input value={value} onChange={event => setValue(event.target.value)} maxLength="500" required autoFocus /><button className="button button-primary button-small" type="submit"><Check size={16} /> Xác nhận</button><button className="button button-quiet button-small" type="button" onClick={() => { setValue(field.value); setEditing(false); }}>Hủy</button></form> : <strong className="field-value">{field.value}</strong>}
    <p className="field-evidence">“{field.evidence}”</p>
    {canWrite && field.status !== 'rejected' && !editing && <div className="field-actions"><button onClick={() => setEditing(true)}>Sửa / xác nhận</button><button onClick={() => onReview(field, field.value, 'rejected')}>Bỏ đề xuất</button></div>}
  </div>;
}

function Detail({ data, documents, me, tab, setTab, onBack, onVersion, onDownload, onExport, onEdit, onNewVersion, onRetry, onFieldReview, onRelation, onRelationReview, onGrant, onRevoke, working }) {
  const { document: doc, versions, pages, fields, relations, grants, sources = [] } = data;
  const canWrite = me?.role === 'admin' || doc.owner_id === me?.id;
  const selected = versions.find(version => version.id === data.selected_version_id);
  const tabs = [{ id: 'overview', label: 'Tổng quan', icon: LayoutDashboard }, { id: 'pages', label: 'Nội dung OCR', icon: ScanText }, { id: 'fields', label: 'Trường dữ liệu', icon: Database }, { id: 'relations', label: 'Quan hệ', icon: Link2 }, { id: 'versions', label: 'Phiên bản', icon: History }, ...(canWrite ? [{ id: 'access', label: 'Phân quyền', icon: UsersRound }] : [])];
  const targets = documents.filter(item => item.id !== doc.id);
  return <div className="page-flow detail-page"><button className="back-link" onClick={onBack}><ArrowLeft size={17} /> Quay lại kho tài liệu</button>
    <div className="detail-hero"><div className={`file-icon file-icon-${doc.kind} detail-hero-icon`}>{(() => { const Icon = KIND_ICONS[doc.kind] || Files; return <Icon size={29} />; })()}</div><div className="detail-hero-text"><span className="eyebrow">CHI TIẾT HỒ SƠ <span className="separator">/</span> {KINDS[doc.kind] || doc.kind}</span><h1>{doc.title}</h1><div className="detail-chips"><span><Building2 size={15} />{doc.department}</span><span><LockKeyhole size={15} />{VISIBILITIES[doc.visibility]}</span><span><History size={15} />{versions.length} phiên bản</span></div></div><button className="button button-primary" onClick={onDownload} disabled={!selected}><Download size={18} /> Tải bản gốc</button></div>
    <div className="detail-tabs" role="tablist" aria-label="Các phần hồ sơ">{tabs.map(({ id, label, icon: Icon }) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}><Icon size={17} />{label}</button>)}</div>
    {tab === 'overview' && <div className="detail-columns"><section className="surface detail-main"><div className="surface-head"><div><span className="eyebrow">THÔNG TIN CHUNG</span><h2>Hồ sơ tài liệu</h2></div><Status value={selected?.status || 'queued'} /></div><div className="info-grid"><div><small>Loại tài liệu</small><strong>{KINDS[doc.kind]}</strong></div><div><small>Vai trò</small><strong>{ISO_ROLES[doc.subtype] || '—'}</strong></div><div><small>Đơn vị quản lý</small><strong>{doc.department}</strong></div><div><small>Quyền xem</small><strong>{VISIBILITIES[doc.visibility]}</strong></div><div><small>Ngày tạo</small><strong>{dateLabel(doc.created_at)}</strong></div><div><small>Tệp gốc</small><strong>{selected?.filename || 'Đang xử lý'}</strong></div><div><small>Số trang</small><strong>{pages.length} trang</strong></div><div><small>Phân loại</small><strong>{STATUSES[doc.classification_status] || '—'}</strong></div></div>
      {doc.classification_evidence && <p className="classification-evidence">Gợi ý từ hệ thống: {doc.classification_evidence}</p>}
      {sources.length > 0 && <div className="source-paths"><h3>Nguồn nhập</h3>{sources.map((source, index) => <p key={index}><FolderOpen size={16} />{source.archive_path}</p>)}</div>}
      {canWrite && <form className="detail-edit" key={doc.id} onSubmit={onEdit}><div className="surface-head"><h3>Chỉnh sửa và xác nhận hồ sơ</h3></div><div className="form-grid"><label>Tiêu đề<input name="title" defaultValue={doc.title} maxLength="300" required /></label><label>Quyền xem<select name="visibility" defaultValue={doc.visibility}><option value="department">Trong đơn vị</option><option value="restricted">Hạn chế</option><option value="public">Công khai</option></select></label><label>Loại tài liệu<select name="kind" defaultValue={doc.kind}>{Object.entries(KINDS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label><label>Vai trò ISO<select name="subtype" defaultValue={doc.subtype || ''}><option value="">Không áp dụng</option>{Object.entries(ISO_ROLES).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>{me.role === 'admin' && <label>Đơn vị quản lý<input name="department" defaultValue={doc.department} required /></label>}</div><button className="button button-outline" type="submit" disabled={working}>Lưu và xác nhận</button></form>}</section><aside className="detail-side"><div className="surface side-card"><span className="eyebrow">NỘI DUNG ĐÃ XỬ LÝ</span><h3>{pages.length} trang tài liệu</h3><p>Xem nội dung theo từng trang, đối chiếu các trường dữ liệu và dẫn chứng nguồn.</p><button className="text-button" onClick={() => setTab('pages')}>Xem nội dung OCR <ArrowRight size={17} /></button></div><div className="surface side-card"><span className="eyebrow">TRẠNG THÁI</span><div className="status-line"><CheckCircle2 size={20} />Bản gốc được lưu trữ</div><div className="status-line"><CheckCircle2 size={20} />{fields.length} trường dữ liệu gợi ý</div><div className="status-line"><CheckCircle2 size={20} />{relations.length} quan hệ tài liệu</div></div></aside></div>}
    {tab === 'pages' && <section className="surface detail-section"><div className="surface-head"><div><span className="eyebrow">VĂN BẢN THEO TRANG</span><h2>Nội dung OCR</h2></div><div className="export-actions"><span className="count-pill">{pages.length} trang</span><button className="button button-outline button-small" onClick={() => onExport('txt')} disabled={!pages.length}><Download size={15} /> TXT</button><button className="button button-outline button-small" onClick={() => onExport('json')} disabled={!pages.length}><Download size={15} /> JSON</button></div></div>{pages.length ? <div className="pages-list">{pages.map(page => <details className="page-accordion" key={page.page_no}><summary><span className="page-number">{String(page.page_no).padStart(2, '0')}</span><span><strong>Trang {page.page_no}</strong><small>{page.source === 'native-pdf' ? 'Lớp chữ PDF' : page.source === 'ocr' ? 'Đọc bằng OCR' : 'Văn bản đã nhập'}</small></span><ChevronDown size={18} /></summary><div className="page-text">{page.text || 'Trang này chưa có nội dung nhận dạng.'}</div></details>)}</div> : <EmptyState icon={ScanText} title="Chưa có nội dung" description="Tài liệu đang được xử lý hoặc chưa có văn bản theo trang." />}</section>}
    {tab === 'fields' && <section className="surface detail-section"><div className="surface-head"><div><span className="eyebrow">TRÍCH XUẤT DỮ LIỆU</span><h2>Trường dữ liệu</h2></div><span className="count-pill">{fields.length} trường</span></div><p className="section-intro">Mỗi đề xuất kèm đoạn văn bản và số trang nguồn để người phụ trách kiểm tra.</p>{fields.length ? <div className="field-grid">{fields.map(field => <FieldItem key={field.id} field={field} canWrite={canWrite} onReview={onFieldReview} />)}</div> : <EmptyState icon={Database} title="Chưa có trường dữ liệu" description="Hệ thống chưa trích được metadata từ phiên bản này." />}</section>}
    {tab === 'relations' && <section className="surface detail-section"><div className="surface-head"><div><span className="eyebrow">LIÊN KẾT HỒ SƠ</span><h2>Quan hệ tài liệu</h2></div><span className="count-pill">{relations.length} quan hệ</span></div>{relations.length ? <div className="relation-list">{relations.map(relation => <div className="relation-card" key={relation.id}><span className="relation-icon"><Link2 size={19} /></span><div><strong>{relation.source_title} <ArrowRight size={14} /> {relation.target_title}</strong><small>{RELATIONS[relation.relation_type] || relation.relation_type} · {STATUSES[relation.status] || relation.status}</small>{relation.evidence && <p>{relation.evidence}</p>}</div>{canWrite && relation.status === 'proposed' && <button className="button button-outline button-small" onClick={() => onRelationReview(relation.id)}>Xác nhận</button>}</div>)}</div> : <EmptyState icon={Link2} title="Chưa có quan hệ" description="Kết nối hồ sơ này với tài liệu khác để theo dõi nguồn viện dẫn và liên quan." />}
      {canWrite && <form className="secondary-form" onSubmit={onRelation}><h3><Plus size={18} /> Thêm quan hệ</h3><div className="form-grid"><label>Tài liệu liên kết<select name="target_id" required><option value="">Chọn tài liệu</option>{targets.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><label>Loại quan hệ<select name="relation_type">{Object.entries(RELATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div><label>Ghi chú / bằng chứng<input name="evidence" maxLength="500" placeholder="Mô tả lý do liên kết (nếu có)" /></label><button className="button button-primary" disabled={!targets.length || working}><Plus size={17} /> Thêm quan hệ</button></form>}</section>}
    {tab === 'versions' && <section className="surface detail-section"><div className="surface-head"><div><span className="eyebrow">LỊCH SỬ TÀI LIỆU</span><h2>Phiên bản</h2></div><span className="count-pill">{versions.length} phiên bản</span></div><div className="version-list">{versions.map(version => <div className={`version-card ${version.id === data.selected_version_id ? 'selected' : ''}`} key={version.id}><span className="version-icon"><History size={19} /></span><div><strong>Phiên bản {version.version_no}</strong><small>{version.filename} · {dateLabel(version.created_at)}</small>{version.error && <p className="form-error"><AlertCircle size={16} />{version.error}</p>}</div><Status value={version.status} /><div className="version-actions">{version.id !== data.selected_version_id && <button className="button button-quiet button-small" onClick={() => onVersion(version.id)}>Xem</button>}{canWrite && version.status === 'failed' && <button className="button button-outline button-small" onClick={() => onRetry(version.id)}>Xử lý lại</button>}</div></div>)}</div>
      {canWrite && <form className="secondary-form" onSubmit={onNewVersion}><h3><Plus size={18} /> Tải phiên bản mới</h3><div className="form-grid"><label>Tệp mới<input type="file" name="file" accept={ACCEPTED_FILES} required /></label><label>JSON OCR có sẵn (không bắt buộc)<textarea name="ocr_pages_json" rows="2" placeholder='[{"text":"Nội dung trang 1"}]' /></label></div><button className="button button-primary" disabled={working}><Upload size={17} /> Tải phiên bản</button></form>}</section>}
    {tab === 'access' && canWrite && <section className="surface detail-section"><div className="surface-head"><div><span className="eyebrow">AN TOÀN DỮ LIỆU</span><h2>Quyền truy cập</h2></div><span className="count-pill">{grants.length} người được cấp</span></div><p className="section-intro">Quyền xem riêng được áp dụng cùng với phạm vi truy cập của hồ sơ.</p>{grants.length ? <div className="grant-list">{grants.map(grant => <div className="grant-card" key={grant.id}><span className="avatar small">{grant.username.slice(0, 1).toUpperCase()}</span><div><strong>{grant.username}</strong><small>{grant.department}</small></div><button className="icon-button danger" title={`Thu hồi quyền ${grant.username}`} aria-label={`Thu hồi quyền ${grant.username}`} onClick={() => onRevoke(grant.id)}><Trash2 size={18} /></button></div>)}</div> : <EmptyState icon={UsersRound} title="Chưa cấp riêng cho ai" description="Bạn có thể cấp quyền xem hồ sơ này cho một tài khoản cụ thể." />}
      <form className="secondary-form" onSubmit={onGrant}><h3><Plus size={18} /> Cấp quyền xem</h3><div className="grant-form-row"><label>Tên đăng nhập<input name="username" placeholder="Nhập tài khoản nhân sự" required /></label><button className="button button-primary" disabled={working}><Plus size={17} /> Cấp quyền</button></div></form></section>}
  </div>;
}

function ApiSettings({ token, notify }) {
  const [status, setStatus] = useState(null);
  const [apiKey, setApiKey] = useState('');
  const [working, setWorking] = useState(false);
  useEffect(() => {
    let live = true;
    request('/api/admin/settings/gemini', {}, token).then(response => response.json())
      .then(value => { if (live) setStatus(value); })
      .catch(error => { if (live) notify(error.message, true); });
    return () => { live = false; };
  }, [token, notify]);
  async function save(event) {
    event.preventDefault();
    if (!apiKey.trim()) return;
    setWorking(true);
    try {
      const response = await request('/api/admin/settings/gemini', {
        method: 'PUT', body: JSON.stringify({ api_key: apiKey.trim() }),
      }, token);
      setStatus(await response.json());
      setApiKey('');
      notify('Đã lưu Gemini API key trên máy chủ.');
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  async function remove() {
    setWorking(true);
    try {
      const response = await request('/api/admin/settings/gemini', { method: 'DELETE' }, token);
      setStatus(await response.json());
      setApiKey('');
      notify('Đã xóa Gemini API key lưu trên máy chủ.');
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  async function testConnection() {
    setWorking(true);
    try {
      await request('/api/admin/settings/gemini/test', { method: 'POST' }, token);
      notify('Kết nối Google Gemini thành công.');
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  return <div className="page-flow"><div className="page-title-row"><div><span className="eyebrow">QUẢN TRỊ HỆ THỐNG</span><h1>Cài đặt API</h1><p>Cấu hình khóa để so sánh chất lượng OCR với Google Gemini.</p></div></div>
    <section className="surface api-settings-card"><div className="api-settings-head"><div className="api-settings-icon"><KeyRound size={24} /></div><div><h2>Google Gemini API</h2><p>Chỉ quản trị viên có quyền thay đổi khóa.</p></div><span className={`api-settings-state ${status?.configured ? 'configured' : ''}`}>{status?.configured ? 'Đã cấu hình' : 'Chưa cấu hình'}</span></div>
      <div className="api-settings-body"><div className="api-settings-note"><ShieldCheck size={18} /><span>Khóa được lưu trong thư mục dữ liệu của máy chủ, không hiển thị lại trên giao diện. Tài liệu chỉ gửi tới Gemini khi bạn chủ động chạy phép so sánh.</span></div>
        <form onSubmit={save} className="api-settings-form"><label htmlFor="gemini-api-key">API key mới</label><div className="api-settings-input"><LockKeyhole size={18} /><input id="gemini-api-key" type="password" autoComplete="off" spellCheck="false" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={status?.configured ? 'Nhập khóa mới để thay thế' : 'Nhập Gemini API key'} /></div><div className="api-settings-actions"><button className="button button-primary" type="submit" disabled={working || !apiKey.trim()}><Check size={17} /> Lưu khóa</button>{status?.configured && <button className="button button-outline" type="button" onClick={testConnection} disabled={working}><RefreshCw size={16} /> Kiểm tra kết nối</button>}{status?.configured && status.source === 'local' && <button className="button button-outline" type="button" onClick={remove} disabled={working}><Trash2 size={16} /> Xóa khóa</button>}</div></form>
        <p className="api-settings-meta">Model so sánh: <strong>{status?.model || 'gemini-3.8-flash'}</strong>{status?.source === 'environment' && ' · Khóa đang được cấp qua biến môi trường máy chủ.'}</p></div>
    </section></div>;
}

function ModelCheck({ token, notify }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [printedCount, setPrintedCount] = useState(2);
  const [handwrittenCount, setHandwrittenCount] = useState(3);
  const [compareGemini, setCompareGemini] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [firstPage, setFirstPage] = useState(1);
  const [pageCount, setPageCount] = useState(1);
  const [referenceText, setReferenceText] = useState('');
  const [uploadGemini, setUploadGemini] = useState(false);
  const refresh = useCallback(async () => {
    const result = await (await request('/api/admin/model-check', {}, token)).json();
    setData(result);
    setLoading(false);
  }, [token]);
  useEffect(() => {
    refresh().catch(error => { setLoading(false); notify(error.message, true); });
  }, [refresh, notify]);
  useEffect(() => {
    if (data?.latest?.status !== 'running') return undefined;
    const timer = setInterval(() => refresh().catch(error => notify(error.message, true)), 2500);
    return () => clearInterval(timer);
  }, [data?.latest?.status, refresh, notify]);
  async function run() {
    setWorking(true);
    try {
      await request('/api/admin/model-check', { method: 'POST', body: JSON.stringify({
        printed_count: Number(printedCount), handwritten_count: Number(handwrittenCount), compare_gemini: compareGemini,
      }) }, token);
      await refresh();
      notify('Đã bắt đầu kiểm tra model trên mẫu có đáp án.');
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  async function runUpload(event) {
    event.preventDefault();
    if (!uploadFile) return;
    if (uploadFile.size > 30 * 1024 * 1024) { notify('Tệp vượt quá 30 MiB.', true); return; }
    const form = new FormData();
    form.append('file', uploadFile);
    form.append('first_page', String(firstPage));
    form.append('page_count', String(pageCount));
    form.append('reference_text', referenceText);
    form.append('compare_gemini', String(uploadGemini));
    setWorking(true);
    try {
      await request('/api/admin/model-check/upload', { method: 'POST', body: form }, token);
      await refresh();
      notify('Đã bắt đầu kiểm tra tệp của bạn.');
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  const latest = data?.latest;
  const ready = data?.availability;
  const ocr = data?.ocr_service;
  const labels = { auto: 'NLHUYOCR tự chọn', printed: 'NLHUYOCR chữ in', handwritten: 'NLHUYOCR viết tay', gemini: 'Gemini', printed_page: 'Trang chữ in', handwritten_line: 'Dòng viết tay', uploaded_page: 'Tệp của bạn' };
  const percent = value => value == null ? '—' : `${(value * 100).toFixed(1).replace('.', ',')}%`;
  return <div className="page-flow model-check-page">
    <div className="page-title-row"><div><span className="eyebrow">PHÒNG KIỂM THỬ OCR</span><h1>Kiểm tra model</h1><p>Tải PDF hoặc ảnh của bạn để so sánh kết quả OCR theo từng model.</p></div><button className="button button-outline" type="button" onClick={() => refresh().catch(error => notify(error.message, true))}><RefreshCw size={17} /> Làm mới</button></div>
    <div className="model-status-grid"><div className="surface model-status"><span className="model-status-icon"><ScanText size={20} /></span><span>Dịch vụ OCR<strong>{ocr?.online ? 'Đang hoạt động' : 'Chưa kết nối'}</strong></span></div><div className="surface model-status"><span className="model-status-icon"><Files size={20} /></span><span>Bộ mẫu có đáp án<strong>{ready?.printed && ready?.handwritten ? 'Đã sẵn sàng' : 'Thiếu dữ liệu'}</strong></span></div><div className="surface model-status"><span className="model-status-icon"><FlaskConical size={20} /></span><span>Bộ phân loại chữ<strong>{ocr?.classifier ? 'Đã nạp trọng số' : 'Chưa có trọng số'}</strong></span></div></div>
    <section className="surface model-run-card model-upload-card"><div className="surface-head"><div><span className="eyebrow">TỆP CỦA BẠN</span><h2>Tải tệp để so sánh</h2></div><Upload size={22} /></div><p className="model-muted">Chạy cùng một trang qua chế độ tự chọn, chữ in và chữ viết tay. Chọn Gemini nếu muốn so sánh với dịch vụ Google.</p>
      <form onSubmit={runUpload} className="model-upload-form"><label className="model-file-pick"><Upload size={20} /><span><strong>{uploadFile ? uploadFile.name : 'Chọn PDF hoặc ảnh'}</strong><small>{uploadFile ? `${(uploadFile.size / 1024 / 1024).toFixed(2)} MiB` : 'PDF, PNG, JPG, WebP, TIFF · tối đa 30 MiB'}</small></span><input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff" required onChange={event => setUploadFile(event.target.files?.[0] || null)} /></label>
        <div className="model-form-grid"><label>Trang bắt đầu<input type="number" min="1" max="9999" value={firstPage} onChange={event => setFirstPage(event.target.value)} required /></label><label>Số trang kiểm tra<select value={pageCount} onChange={event => setPageCount(event.target.value)}>{[1, 2, 3].map(count => <option key={count} value={count}>{count} trang</option>)}</select></label></div>
        <label className="model-reference">Bản chép đúng <span>(không bắt buộc)</span><textarea value={referenceText} onChange={event => setReferenceText(event.target.value)} maxLength={50000} rows="4" placeholder="Dán văn bản đúng của các trang đã chọn theo đúng thứ tự. Có bản chép này hệ thống mới tính CER/WER." /></label>
        <label className="model-gemini"><input type="checkbox" checked={uploadGemini} onChange={event => setUploadGemini(event.target.checked)} disabled={!ready?.gemini} /><span><strong>So với Gemini</strong><small>Chỉ khi bạn bật mục này, trang trong tệp đã chọn mới được gửi tới Google. Có thể dùng quota API.</small></span></label>
        <button className="button button-primary model-run-button" type="submit" disabled={working || loading || latest?.status === 'running' || !ocr?.online || !uploadFile}><ScanText size={17} />{latest?.status === 'running' ? 'Đang kiểm tra…' : 'Kiểm tra tệp này'}</button></form></section>
    <div className="model-check-layout"><section className="surface model-run-card"><div className="surface-head"><div><span className="eyebrow">PHÉP ĐO MỚI</span><h2>Chọn số mẫu kiểm tra</h2></div><BarChart3 size={22} /></div><p className="model-muted">Trang in lấy từ dữ liệu tổng hợp của dự án; dòng viết tay lấy từ tập test UIT-HWDB. Cả hai có bản chép đúng để tính sai số.</p><div className="model-form-grid"><label>Trang chữ in<select value={printedCount} onChange={event => setPrintedCount(event.target.value)}>{[1, 2, 3].map(count => <option key={count} value={count}>{count} trang</option>)}</select></label><label>Dòng viết tay<select value={handwrittenCount} onChange={event => setHandwrittenCount(event.target.value)}>{[1, 2, 3, 4, 5].map(count => <option key={count} value={count}>{count} dòng</option>)}</select></label></div><label className="model-gemini"><input type="checkbox" checked={compareGemini} onChange={event => setCompareGemini(event.target.checked)} disabled={!ready?.gemini} /><span><strong>So với Gemini</strong><small>Gửi đúng các ảnh kiểm thử công khai / tổng hợp lên Google. Có thể dùng quota API.</small></span></label><button className="button button-primary model-run-button" type="button" onClick={run} disabled={working || loading || latest?.status === 'running' || !ocr?.online || !ready?.printed || !ready?.handwritten}><FlaskConical size={17} />{latest?.status === 'running' ? 'Đang kiểm tra…' : 'Chạy kiểm tra model'}</button></section>
      <aside className="surface model-info-card"><span className="eyebrow">CẤU HÌNH ĐANG CHẠY</span><h2>Pipeline OCR</h2><div><span>Dò dòng</span><strong>{ocr?.detectors?.paddle_server ? 'PaddleOCR bản lớn · offline' : 'Chưa sẵn sàng'}</strong></div><div><span>Đọc chữ in</span><strong>{ocr?.recognizers?.printed ? 'NLHUYOCR chữ in' : 'Thiếu trọng số'}</strong></div><div><span>Đọc viết tay</span><strong>{ocr?.recognizers?.handwritten ? 'NLHUYOCR viết tay' : 'Thiếu trọng số'}</strong></div><div><span>Tự chọn model</span><strong>{ocr?.classifier ? 'Bật' : 'Chưa sẵn sàng'}</strong></div><p>Các model OCR xử lý ảnh tại máy. Sai số CER/WER càng thấp càng tốt; thời gian là trung vị mỗi ảnh trên máy này. Dòng viết tay được đo theo dòng, không đại diện cho cả trang A4.</p></aside></div>
    {latest && <section className="surface model-results"><div className="surface-head"><div><span className="eyebrow">KẾT QUẢ GẦN NHẤT</span><h2>{latest.status === 'running' ? 'Đang đo model' : latest.status === 'ready' ? 'Kết quả kiểm tra' : 'Phép đo chưa hoàn tất'}</h2></div><span className="model-run-date">{latest.started_at ? new Date(latest.started_at).toLocaleString('vi-VN') : ''}</span></div><div className="model-progress"><div style={{ width: `${latest.total ? latest.completed / latest.total * 100 : 0}%` }} /></div><p className="model-muted">{latest.source === 'upload' ? `${latest.filename} · ` : ''}{latest.completed}/{latest.total} {latest.source === 'upload' ? 'trang' : 'mẫu'} đã xử lý{latest.settings?.compare_gemini ? ' · Có so sánh Gemini' : ' · Chỉ chạy nội bộ'}{latest.source === 'upload' && !latest.settings?.has_reference ? ' · Chưa có bản chép đúng nên không tính CER/WER' : ''}</p>{latest.error && <p className="form-error"><AlertCircle size={16} />{latest.error}</p>}{latest.summary?.length > 0 && <div className="model-table-wrap"><table className="model-table"><thead><tr><th>Nhóm mẫu</th><th>Model / cách chạy</th><th>Số mẫu</th><th>CER</th><th>WER</th><th>Trung vị</th></tr></thead><tbody>{latest.summary.map(row => <tr key={`${row.kind}-${row.model}`}><td>{labels[row.kind]}</td><td><strong>{labels[row.model]}</strong></td><td>{row.count}</td><td>{percent(row.cer)}</td><td>{percent(row.wer)}</td><td>{row.seconds.toFixed(2)} s</td></tr>)}</tbody></table></div>}{latest.samples?.some(row => row.gemini_error) && <p className="model-warning">Gemini trả lỗi ở một số trang; chỉ hiện kết quả so sánh thành công.</p>}</section>}
    {latest?.source === 'upload' && latest.samples?.length > 0 && <section className="surface model-results model-page-results"><div className="surface-head"><div><span className="eyebrow">VĂN BẢN NHẬN DẠNG</span><h2>So sánh từng trang</h2></div></div><p className="model-muted">Mở một trang để xem toàn bộ kết quả và thời gian của từng cách đọc.</p>{latest.samples.map(row => <details className="model-page-detail" key={row.id}><summary>Trang {row.page_no}<span>{row.gemini_error ? `Gemini: ${row.gemini_error}` : 'Xem kết quả'}</span></summary><div className="model-text-grid">{['auto', 'printed', 'handwritten', 'gemini'].map(mode => { const result = mode === 'gemini' ? row.gemini : row.local?.[mode]; return result && <article className="model-text-card" key={mode}><div><strong>{labels[mode]}</strong><span>{result.error ? 'Có lỗi' : `${Number(result.seconds).toFixed(2)} s`}</span></div><pre>{result.error ? `Lỗi: ${result.error}` : result.text || '(Không nhận được chữ)'}</pre></article>; })}</div></details>)}</section>}
    {!latest && !loading && <section className="surface model-empty"><Timer size={22} /><span>Chưa có lần kiểm tra nào. Chọn số mẫu và chạy phép đo đầu tiên.</span></section>}
  </div>;
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('dau_token') || '');
  const [me, setMe] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [health, setHealth] = useState(null);
  const [stats, setStats] = useState(null);
  const [screen, setScreen] = useState('dashboard');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailTab, setDetailTab] = useState('overview');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searched, setSearched] = useState(false);
  const [working, setWorking] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = useCallback((message, error = false) => setToast({ message, error, id: Date.now() }), []);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(null), 5000); return () => clearTimeout(timer); }, [toast]);
  const loadDocuments = useCallback(async (accessToken = token) => {
    const list = await (await request('/api/documents?limit=2000', {}, accessToken)).json();
    setDocuments(list);
    setStats(await (await request('/api/documents/facets', {}, accessToken)).json());
    return list;
  }, [token]);
  const loadStats = useCallback(async (accessToken = token) => {
    const value = await (await request('/api/documents/facets', {}, accessToken)).json();
    setStats(value);
    return value;
  }, [token]);
  useEffect(() => {
    if (!token) return;
    let live = true;
    Promise.all([
      request('/api/me', {}, token).then(response => response.json()),
      request('/api/documents?limit=2000', {}, token).then(response => response.json()),
      request('/api/health').then(response => response.json()),
      request('/api/documents/facets', {}, token).then(response => response.json()),
    ]).then(([account, list, status, summary]) => {
      if (!live) return;
      setMe(account); setDocuments(list); setHealth(status); setStats(summary);
    }).catch(error => {
      if (!live) return;
      if (/401|đăng nhập|hết hạn/i.test(error.message)) { sessionStorage.removeItem('dau_token'); setToken(''); }
      else notify(error.message, true);
    });
    return () => { live = false; };
  }, [token, notify]);

  async function login(credentials) {
    const result = await (await request('/api/auth/login', { method: 'POST', body: JSON.stringify(credentials) })).json();
    sessionStorage.setItem('dau_token', result.token);
    setToken(result.token);
  }
  async function logout() {
    try { await request('/api/auth/logout', { method: 'POST' }, token); } catch (_) { /* Clear local session anyway. */ }
    sessionStorage.removeItem('dau_token'); setToken(''); setMe(null); setDetail(null); setScreen('dashboard');
  }
  async function openDocument(id, versionId = '', keepTab = false) {
    try {
      const suffix = versionId ? `?version_id=${encodeURIComponent(versionId)}` : '';
      const record = await (await request(`/api/documents/${id}${suffix}`, {}, token)).json();
      setDetail(record); setScreen('detail'); if (!keepTab) setDetailTab('overview');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) { notify(error.message, true); }
  }
  async function refreshDetail() {
    if (detail) await openDocument(detail.document.id, detail.selected_version_id || '', true);
  }
  async function act(work, success) {
    setWorking(true);
    try { await work(); if (success) notify(success); }
    catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  async function pollJob(jobId, documentId) {
    for (let attempt = 0; attempt < 300; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      try {
        const job = await (await request(`/api/jobs/${jobId}`, {}, token)).json();
        if (job.status === 'ready' || job.status === 'failed') {
          await loadDocuments(); await openDocument(documentId);
          notify(job.status === 'ready' ? 'Tài liệu đã xử lý xong.' : (job.error || 'Xử lý tài liệu thất bại.'), job.status === 'failed');
          return;
        }
      } catch (error) { notify(error.message, true); return; }
    }
    notify('Tài liệu vẫn đang xử lý. Bấm làm mới để xem trạng thái.');
  }
  async function upload(event) {
    event.preventDefault(); const form = event.currentTarget;
    await act(async () => {
      const body = new FormData(form);
      if (!body.get('ocr_pages_json')) body.delete('ocr_pages_json');
      const result = await (await request('/api/documents', { method: 'POST', body }, token)).json();
      form.reset(); await loadDocuments(); setScreen('documents');
      notify('Đã nhận tài liệu. Hệ thống đang xử lý OCR.');
      pollJob(result.job_id, result.document_id);
    });
  }
  async function newVersion(event) {
    event.preventDefault(); const form = event.currentTarget; const id = detail.document.id;
    await act(async () => {
      const body = new FormData(form); if (!body.get('ocr_pages_json')) body.delete('ocr_pages_json');
      const result = await (await request(`/api/documents/${id}/versions`, { method: 'POST', body }, token)).json();
      form.reset(); await openDocument(id, '', true); notify('Đã nhận phiên bản mới.');
      pollJob(result.job_id, id);
    });
  }
  async function retry(versionId) {
    const id = detail.document.id;
    await act(async () => {
      const result = await (await request(`/api/documents/${id}/versions/${versionId}/retry`, { method: 'POST' }, token)).json();
      await refreshDetail(); pollJob(result.job_id, id);
    }, 'Đang xử lý lại phiên bản.');
  }
  async function editDocument(event) {
    event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget)); const id = detail.document.id;
    await act(async () => {
      await request(`/api/documents/${id}`, { method: 'PATCH', body: JSON.stringify(body) }, token);
      await loadDocuments(); await refreshDetail();
    }, 'Đã lưu thông tin hồ sơ.');
  }
  async function reviewField(field, value, status) {
    await act(async () => {
      await request(`/api/fields/${field.id}`, { method: 'PATCH', body: JSON.stringify({ value, status }) }, token);
      await refreshDetail();
    }, status === 'confirmed' ? 'Đã xác nhận dữ liệu.' : 'Đã bỏ đề xuất.');
  }
  async function addRelation(event) {
    event.preventDefault(); const form = event.currentTarget; const id = detail.document.id;
    await act(async () => {
      const body = Object.fromEntries(new FormData(form));
      await request(`/api/documents/${id}/relations`, { method: 'POST', body: JSON.stringify(body) }, token);
      form.reset(); await refreshDetail();
    }, 'Đã thêm quan hệ tài liệu.');
  }
  async function reviewRelation(id) {
    await act(async () => {
      await request(`/api/relations/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'confirmed' }) }, token);
      await refreshDetail();
    }, 'Đã xác nhận quan hệ.');
  }
  async function grant(event) {
    event.preventDefault(); const form = event.currentTarget;
    await act(async () => {
      const body = Object.fromEntries(new FormData(form));
      await request(`/api/documents/${detail.document.id}/grants`, { method: 'POST', body: JSON.stringify(body) }, token);
      form.reset(); await refreshDetail();
    }, 'Đã cấp quyền xem.');
  }
  async function revoke(userId) {
    await act(async () => {
      await request(`/api/documents/${detail.document.id}/grants/${userId}`, { method: 'DELETE' }, token);
      await refreshDetail();
    }, 'Đã thu hồi quyền xem.');
  }
  async function download() {
    if (!detail) return;
    try {
      const version = detail.versions.find(item => item.id === detail.selected_version_id);
      const suffix = version ? `?version_id=${encodeURIComponent(version.id)}` : '';
      const response = await request(`/api/documents/${detail.document.id}/download${suffix}`, {}, token);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = version?.filename || 'document'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (error) { notify(error.message, true); }
  }
  async function exportText(format) {
    if (!detail) return;
    try {
      const response = await request(`/api/documents/${detail.document.id}/export?format=${format}`, {}, token);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url;
      anchor.download = `${detail.document.id}.${format}`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (error) { notify(error.message, true); }
  }
  async function search(event) {
    event?.preventDefault();
    if (!searchQuery.trim()) return;
    setWorking(true); setScreen('search'); setSearched(true);
    try { setSearchResults((await (await request(`/api/search?q=${encodeURIComponent(searchQuery.trim())}&limit=30`, {}, token)).json()).results); }
    catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }

  if (!token) return <Login onLogin={login} />;
  if (!me) return <div className="loading-screen"><div className="brand-mark"><Files size={24} /></div><span>Đang mở không gian làm việc…</span></div>;
  return <div className="app-shell"><Sidebar screen={screen} setScreen={setScreen} me={me} onLogout={logout} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
    <div className="app-main"><header className="topbar"><button className="icon-button mobile-menu" aria-label="Mở menu" onClick={() => setMobileOpen(true)}><Menu size={22} /></button><div className="topbar-path">Không gian làm việc <ChevronRight size={15} /><strong>{screen === 'dashboard' ? 'Tổng quan' : screen === 'documents' || screen === 'detail' ? 'Kho tài liệu' : screen === 'upload' ? 'Nhập tài liệu' : screen === 'settings' ? 'Cài đặt API' : screen === 'models' ? 'Kiểm tra model' : 'Tra cứu'}</strong></div><form className="topbar-search" onSubmit={search}><Search size={17} /><input value={searchQuery} onChange={event => setSearchQuery(event.target.value)} placeholder="Tìm trong tài liệu…" aria-label="Tìm trong tài liệu" /><span>↵</span></form><div className="topbar-user"><span className="topbar-status"><span className="online-dot" /> Hệ thống hoạt động</span>{me.role === 'admin' && <button className={`icon-button settings-button ${screen === 'settings' ? 'active' : ''}`} type="button" aria-label="Cài đặt API" title="Cài đặt API" onClick={() => setScreen('settings')}><Settings2 size={19} /></button>}<span className="avatar">{me.username.slice(0, 1).toUpperCase()}</span></div></header>
      <main className="content-wrap">
        {screen === 'dashboard' && <Dashboard documents={documents} me={me} health={health} stats={stats} openDocument={openDocument} setScreen={setScreen} />}
        {screen === 'documents' && <Documents token={token} notify={notify} openDocument={openDocument} setScreen={setScreen} />}
        {screen === 'upload' && <UploadPage me={me} token={token} notify={notify} onImported={loadStats} onSubmit={upload} working={working} />}
        {screen === 'search' && <SearchPage query={searchQuery} setQuery={setSearchQuery} results={searchResults} onSearch={search} working={working} searched={searched} openDocument={openDocument} />}
        {screen === 'settings' && me.role === 'admin' && <ApiSettings token={token} notify={notify} />}
        {screen === 'models' && me.role === 'admin' && <ModelCheck token={token} notify={notify} />}
        {screen === 'detail' && detail && <Detail data={detail} documents={documents} me={me} tab={detailTab} setTab={setDetailTab} onBack={() => setScreen('documents')} onVersion={versionId => openDocument(detail.document.id, versionId, true)} onDownload={download} onExport={exportText} onEdit={editDocument} onNewVersion={newVersion} onRetry={retry} onFieldReview={reviewField} onRelation={addRelation} onRelationReview={reviewRelation} onGrant={grant} onRevoke={revoke} working={working} />}
      </main><footer className="app-footer">NLHUYOCR <span>·</span> Kho hồ sơ tài liệu nội bộ</footer></div>
    {toast && <div className={`toast ${toast.error ? 'toast-error' : ''}`} role="status">{toast.error ? <AlertCircle size={19} /> : <CheckCircle2 size={19} />}<span>{toast.message}</span><button onClick={() => setToast(null)} aria-label="Đóng thông báo"><X size={17} /></button></div>}
  </div>;
}
