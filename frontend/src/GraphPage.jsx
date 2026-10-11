import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Check, ChevronRight, FileSearch, GitBranch, Link2, Maximize2, Minimize2, Plus, RefreshCw, Search, X } from 'lucide-react';
import './graph.css';

const KINDS = { incoming: 'Công văn đến', outgoing: 'Công văn đi', iso: 'ISO',
  curriculum: 'Chương trình đào tạo', lesson: 'Học liệu', other: 'Khác' };
const RELATIONS = { cites: 'Viện dẫn', replaces: 'Thay thế', in_file: 'Thuộc hồ sơ',
  in_course: 'Thuộc học phần', related: 'Liên quan' };
const COLORS = { incoming: '#3a82bf', outgoing: '#6b6dc2', iso: '#088d80',
  curriculum: '#a77c2d', lesson: '#bd6d59', other: '#738a99' };
const EDGE_COLORS = { cites: '#5790bb', replaces: '#b97267', in_file: '#238a78',
  in_course: '#aa8438', related: '#80939c' };

function positions(nodes) {
  const result = {};
  const rings = [nodes.filter(node => node.level === 1), nodes.filter(node => node.level >= 2)];
  const root = nodes.find(node => node.level === 0);
  if (root) result[root.id] = { x: 500, y: 330 };
  rings.forEach((ring, index) => {
    const radius = index ? 285 : 170;
    ring.forEach((node, position) => {
      const angle = -Math.PI / 2 + position * Math.PI * 2 / Math.max(1, ring.length);
      result[node.id] = { x: 500 + Math.cos(angle) * radius,
                          y: 330 + Math.sin(angle) * radius };
    });
  });
  return result;
}

function DocumentPicker({ token, request, notify, onChoose, exclude = '', label }) {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState([]);
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q: query.trim(), limit: '12' });
      request(`/api/documents/page?${params}`, {}, token).then(response => response.json())
        .then(data => { if (live) setItems(data.items.filter(item => item.id !== exclude)); })
        .catch(error => { if (live) notify(error.message, true); });
    }, 180);
    return () => { live = false; clearTimeout(timer); };
  }, [token, request, notify, query, exclude]);
  return <div className="graph-picker"><label>{label}<span><Search size={16} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Tìm theo tên, mã hoặc đơn vị…" /></span></label>
    <div className="graph-picker-results">{items.map(item => <button type="button" key={item.id} onClick={() => onChoose(item)}><strong>{item.title}</strong><small>{KINDS[item.kind]} · {item.department}</small><ChevronRight size={16} /></button>)}</div></div>;
}

export default function GraphPage({ token, request, notify, onOpen, initialDocumentId = '' }) {
  const [rootId, setRootId] = useState(initialDocumentId);
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [depth, setDepth] = useState(2);
  const [includeProposed, setIncludeProposed] = useState(true);
  const [typeFilter, setTypeFilter] = useState('all');
  const [selectedId, setSelectedId] = useState(initialDocumentId);
  const [target, setTarget] = useState(null);
  const [relationType, setRelationType] = useState('related');
  const [evidence, setEvidence] = useState('');
  const [pageNo, setPageNo] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [suggestions, setSuggestions] = useState(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => { if (initialDocumentId) { setRootId(initialDocumentId); setSelectedId(initialDocumentId); } }, [initialDocumentId]);
  useEffect(() => {
    if (!rootId) { setGraph(null); return; }
    let live = true;
    setLoading(true);
    const params = new URLSearchParams({ depth: String(depth), limit: '80', include_proposed: String(includeProposed) });
    request(`/api/graph/${rootId}?${params}`, {}, token).then(response => response.json())
      .then(data => { if (live) setGraph(data); })
      .catch(error => { if (live) notify(error.message, true); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [token, request, notify, rootId, depth, includeProposed, revision]);
  useEffect(() => {
    if (!rootId) { setSuggestions(null); return; }
    let live = true;
    request(`/api/documents/${rootId}/similar?limit=6`, {}, token)
      .then(response => response.json()).then(value => { if (live) setSuggestions(value); })
      .catch(error => { if (live) notify(error.message, true); });
    return () => { live = false; };
  }, [rootId, token, request, notify, revision]);

  const visibleEdges = useMemo(() => (graph?.edges || []).filter(edge => typeFilter === 'all' || edge.relation_type === typeFilter), [graph, typeFilter]);
  const connected = new Set([rootId, ...visibleEdges.flatMap(edge => [edge.source_id, edge.target_id])]);
  const visibleNodes = (graph?.nodes || []).filter(node => connected.has(node.id));
  const points = useMemo(() => positions(visibleNodes), [graph, typeFilter, rootId]);
  const lookup = Object.fromEntries((graph?.nodes || []).map(node => [node.id, node]));
  const root = lookup[rootId];
  const selected = lookup[selectedId] || root;
  const relevant = visibleEdges.filter(edge => edge.source_id === selected?.id || edge.target_id === selected?.id);

  async function createRelation(event) {
    event.preventDefault();
    if (!rootId || !target) return;
    setBusy(true);
    try {
      await request(`/api/documents/${rootId}/relations`, { method: 'POST', body: JSON.stringify({
        target_id: target.id, relation_type: relationType, evidence: evidence.trim(),
        page_no: pageNo ? Number(pageNo) : null,
      }) }, token);
      setTarget(null); setEvidence(''); setPageNo(''); setRevision(value => value + 1);
      notify('Đã tạo quan hệ tài liệu.');
    } catch (error) { notify(error.message, true); }
    finally { setBusy(false); }
  }
  async function review(edge, status) {
    setBusy(true);
    try {
      await request(`/api/relations/${edge.id}`, { method: 'PATCH', body: JSON.stringify({ status }) }, token);
      setRevision(value => value + 1); notify(status === 'confirmed' ? 'Đã xác nhận quan hệ.' : 'Đã bỏ đề xuất.');
    } catch (error) { notify(error.message, true); }
    finally { setBusy(false); }
  }

  return <div className="page-flow graph-page"><div className="page-title-row"><div><span className="eyebrow">MẠNG LƯỚI HỒ SƠ</span><h1>Sơ đồ quan hệ</h1><p>Xem công văn, quy trình ISO và học liệu liên kết với nhau; chọn một nút để lần theo hồ sơ.</p></div>{root && <button className="button button-outline" onClick={() => setRevision(value => value + 1)}><RefreshCw size={17} /> Làm mới</button>}</div>
    <div className="graph-workspace"><aside className="surface graph-controls"><div className="surface-head"><div><span className="eyebrow">HỒ SƠ GỐC</span><h2>{root ? 'Đang khám phá' : 'Chọn tài liệu'}</h2></div><GitBranch size={21} /></div>
      {root ? <div className="graph-root"><strong>{root.title}</strong><small>{KINDS[root.kind]} · {root.department}</small><button className="text-button" onClick={() => { setRootId(''); setGraph(null); }}>Đổi hồ sơ <ArrowRight size={15} /></button></div> : <DocumentPicker token={token} request={request} notify={notify} label="Tìm hồ sơ" onChoose={item => { setRootId(item.id); setSelectedId(item.id); }} />}
      {root && <><div className="graph-options"><label>Số lớp quan hệ<select value={depth} onChange={event => setDepth(Number(event.target.value))}><option value="1">1 lớp</option><option value="2">2 lớp</option><option value="3">3 lớp</option></select></label><label>Loại quan hệ<select value={typeFilter} onChange={event => setTypeFilter(event.target.value)}><option value="all">Tất cả</option>{Object.entries(RELATIONS).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label><label className="graph-check"><input type="checkbox" checked={includeProposed} onChange={event => setIncludeProposed(event.target.checked)} /> Gồm đề xuất chưa duyệt</label></div>
        <div className="graph-legend">{Object.entries(COLORS).map(([key, color]) => <span key={key}><i style={{ background: color }} />{KINDS[key]}</span>)}</div></>}
    </aside>
      <section className={`surface graph-canvas-card ${expanded ? 'graph-expanded' : ''}`}><div className="graph-canvas-head"><strong>{root ? `${visibleNodes.length} tài liệu · ${visibleEdges.length} quan hệ` : 'Chọn hồ sơ để xem sơ đồ'}</strong>{loading && <span>Đang tải…</span>}{root && <button type="button" className="graph-expand-button" onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}{expanded ? 'Thu nhỏ' : 'Phóng to'}</button>}</div>{root && <svg className="graph-canvas" viewBox="0 0 1000 660" role="img" aria-label="Sơ đồ quan hệ tài liệu"><defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9cafb6" /></marker></defs>
          {visibleEdges.map(edge => { const from = points[edge.source_id], to = points[edge.target_id]; if (!from || !to) return null; return <g key={edge.id}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={EDGE_COLORS[edge.relation_type]} strokeWidth="2" strokeDasharray={edge.status === 'proposed' ? '6 5' : undefined} opacity=".65" markerEnd="url(#graph-arrow)" /><title>{RELATIONS[edge.relation_type]} · {edge.status === 'proposed' ? 'chờ duyệt' : 'đã xác nhận'}</title></g>; })}
          {visibleNodes.map(node => { const point = points[node.id], main = node.id === rootId, chosen = node.id === selected?.id; return <g key={node.id} className="graph-node" onClick={() => setSelectedId(node.id)} role="button" tabIndex="0" onKeyDown={event => { if (event.key === 'Enter') setSelectedId(node.id); }}><circle cx={point.x} cy={point.y} r={main ? 26 : chosen ? 21 : node.level === 1 ? 17 : 12} fill={COLORS[node.kind]} stroke={chosen ? '#1b3540' : '#fff'} strokeWidth={chosen ? 4 : 3} /><text x={point.x} y={point.y + (main ? 45 : 33)} textAnchor="middle">{node.title.length > 30 ? `${node.title.slice(0, 29)}…` : node.title}</text><title>{node.title} · {node.department}</title></g>; })}</svg>}{root && visibleEdges.length === 0 && <div className="graph-empty"><FileSearch size={21} />Chưa có quan hệ phù hợp. Có thể tạo liên kết ở bảng bên dưới.</div>}{!root && <div className="graph-placeholder"><GitBranch size={48} /><strong>Khám phá hồ sơ theo sơ đồ</strong><span>Tìm tài liệu ở cột bên trái để bắt đầu.</span></div>}</section></div>
    {root && <div className="graph-bottom"><section className="surface graph-inspector"><div className="surface-head"><div><span className="eyebrow">NÚT ĐANG CHỌN</span><h2>{selected?.title}</h2></div><button className="button button-outline button-small" onClick={() => onOpen(selected.id)}>Mở hồ sơ <ArrowRight size={15} /></button></div><p>{KINDS[selected?.kind]} · {selected?.department}</p>{selected?.id !== rootId && <button className="text-button" onClick={() => { setRootId(selected.id); setSelectedId(selected.id); }}>Lấy làm tâm sơ đồ <ArrowRight size={15} /></button>}
        <div className="graph-edge-list">{relevant.map(edge => { const other = lookup[edge.source_id === selected.id ? edge.target_id : edge.source_id]; return <div className="graph-edge-row" key={edge.id}><span className="graph-edge-icon" style={{ color: EDGE_COLORS[edge.relation_type] }}><Link2 size={16} /></span><div><strong>{RELATIONS[edge.relation_type]} · {other?.title}</strong><small>{edge.status === 'proposed' ? 'Chờ xác nhận' : 'Đã xác nhận'}{edge.page_no ? ` · Trang ${edge.page_no}` : ''}</small>{edge.evidence && <p>{edge.evidence}</p>}</div>{edge.status === 'proposed' && lookup[edge.source_id]?.can_write && <div className="graph-edge-actions"><button title="Xác nhận" onClick={() => review(edge, 'confirmed')} disabled={busy}><Check size={16} /></button><button title="Bỏ đề xuất" onClick={() => review(edge, 'rejected')} disabled={busy}><X size={16} /></button></div>}</div>; })}{!relevant.length && <p>Không có quan hệ trong bộ lọc này.</p>}</div></section>
      {root.can_write && <section className="surface graph-create"><div className="surface-head"><div><span className="eyebrow">LIÊN KẾT THỦ CÔNG</span><h2>Tạo quan hệ mới</h2></div><Plus size={21} /></div>{suggestions?.indexed && <div className="graph-suggestions"><strong>Gợi ý theo nội dung</strong><p>Model tìm tài liệu gần nhau; chỉ tạo quan hệ sau khi bạn kiểm tra.</p>{suggestions.results.filter(item => !lookup[item.id]).slice(0, 4).map(item => <button key={item.id} type="button" onClick={() => { setTarget(item); setRelationType('related'); setEvidence(''); }}><span>{item.title}<small>{item.department}</small></span><em>{Math.round(item.score * 100)}%</em><Plus size={15} /></button>)}</div>}<form onSubmit={createRelation}>{target ? <div className="graph-target"><strong>{target.title}</strong><small>{target.department}</small><button type="button" onClick={() => setTarget(null)} aria-label="Chọn lại tài liệu"><X size={17} /></button></div> : <DocumentPicker token={token} request={request} notify={notify} exclude={rootId} label="Tài liệu đích" onChoose={setTarget} />}<div className="graph-create-grid"><label>Kiểu liên kết<select value={relationType} onChange={event => setRelationType(event.target.value)}>{Object.entries(RELATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Trang bằng chứng<input type="number" min="1" value={pageNo} onChange={event => setPageNo(event.target.value)} placeholder="Nếu có" /></label></div><label>Bằng chứng / lý do<textarea rows="3" maxLength="500" value={evidence} onChange={event => setEvidence(event.target.value)} placeholder="Ví dụ: Quy trình này viện dẫn Quyết định số…" /></label><button className="button button-primary" disabled={!target || busy}><Plus size={16} /> Tạo quan hệ</button></form></section>}</div>}
  </div>;
}
