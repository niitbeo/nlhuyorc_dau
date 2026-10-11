import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, BrainCircuit, CheckCircle2, Database, HardDriveDownload, RefreshCw, Sparkles } from 'lucide-react';
import './embedding.css';

const MODEL_NAMES = { 'vietnamese-v2': 'Vietnamese Embedding v2', 'bge-m3': 'BGE-M3' };

export default function EmbeddingPage({ token, request, notify }) {
  const [data, setData] = useState(null);
  const [limit, setLimit] = useState(100);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setData(await (await request('/api/admin/embeddings', {}, token)).json()); }
    catch (error) { notify(error.message, true); }
  }, [token, request, notify]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!data?.latest_job || !['queued', 'running'].includes(data.latest_job.status)) return;
    const timer = setInterval(load, 2200);
    return () => clearInterval(timer);
  }, [data?.latest_job?.status, load]);
  async function choose(key) {
    setBusy(true);
    try { setData(await (await request('/api/admin/embeddings/model', { method: 'POST', body: JSON.stringify({ key }) }, token)).json()); notify('Đã đổi model. Chỉ mục của model cũ được giữ để có thể chọn lại.'); }
    catch (error) { notify(error.message, true); }
    finally { setBusy(false); }
  }
  async function start(event) {
    event.preventDefault(); setBusy(true);
    try { await request('/api/admin/embeddings/reindex', { method: 'POST', body: JSON.stringify({ limit: Number(limit) }) }, token); notify('Đã bắt đầu lập chỉ mục.'); await load(); }
    catch (error) { notify(error.message, true); }
    finally { setBusy(false); }
  }
  const job = data?.latest_job;
  const percentage = data?.total_chunks ? Math.round(data.indexed_chunks / data.total_chunks * 100) : 0;
  const jobPercent = job?.total ? Math.round(job.completed / job.total * 100) : 0;
  return <div className="page-flow embedding-page"><div className="page-title-row"><div><span className="eyebrow">TÌM KIẾM TẠI MÁY</span><h1>Embedding & chỉ mục</h1><p>Chọn model tiếng Việt, lập vector từng lượt và theo dõi tài liệu đã sẵn sàng để tra cứu ngữ nghĩa.</p></div><button className="button button-outline" onClick={load}><RefreshCw size={16} /> Làm mới</button></div>
    <div className="embedding-metrics"><div className="surface"><BrainCircuit size={20} /><span>Model đang chọn</span><strong>{MODEL_NAMES[data?.selected_model] || data?.selected_model || 'Đang tải…'}</strong></div><div className="surface"><Database size={20} /><span>Đoạn đã lập chỉ mục</span><strong>{data ? `${data.indexed_chunks.toLocaleString('vi-VN')} / ${data.total_chunks.toLocaleString('vi-VN')}` : '—'}</strong></div><div className="surface"><CheckCircle2 size={20} /><span>Tài liệu hoàn chỉnh</span><strong>{data?.indexed_documents?.toLocaleString('vi-VN') ?? '—'}</strong></div></div>
    <section className="surface embedding-models"><div className="surface-head"><div><span className="eyebrow">CHẠY NỘI BỘ</span><h2>Chọn model</h2></div><Sparkles size={22} /></div><p>Vector của mỗi model được lưu kèm định danh. Đổi model không ghi đè nhầm chỉ mục đã tạo.</p><div className="embedding-model-grid">{data?.models?.map(model => <div className={`embedding-model ${model.active ? 'active' : ''}`} key={model.key}><div><strong>{MODEL_NAMES[model.key] || model.key}</strong><span>{model.model_id}</span></div><div className="embedding-model-foot"><small className={model.installed ? 'installed' : ''}>{model.installed ? 'Đã có trọng số tại máy' : 'Chưa có trọng số tại máy'}</small><button className="button button-outline button-small" disabled={model.active || busy || ['queued', 'running'].includes(job?.status)} onClick={() => choose(model.key)}>{model.active ? 'Đang chọn' : 'Chọn model'}</button></div></div>)}</div>{!data?.model_ready && <div className="embedding-setup"><HardDriveDownload size={19} /><div><strong>Model chưa sẵn sàng trên máy chủ</strong><p>Chạy <code>python3 scripts/fetch_embedding_model.py --model {data?.selected_model || 'vietnamese-v2'}</code> trong thư mục dự án. Tệp trọng số nằm tại <code>data/models/</code> và không được đưa lên GitHub.</p></div></div>}</section>
    <section className="surface embedding-index"><div className="surface-head"><div><span className="eyebrow">LẬP CHỈ MỤC THEO LƯỢT</span><h2>Tiến độ dữ liệu</h2></div><span className="count-pill">{percentage}%</span></div><div className="embedding-track"><span style={{ width: `${percentage}%` }} /></div><p>Chỉ xử lý các đoạn của phiên bản hiện hành còn thiếu vector từ model đang chọn.</p><form onSubmit={start}><label>Số đoạn trong lượt<select value={limit} onChange={event => setLimit(event.target.value)}><option value="20">20 đoạn · kiểm tra nhanh</option><option value="100">100 đoạn</option><option value="500">500 đoạn</option><option value="2000">2.000 đoạn</option></select></label><button className="button button-primary" disabled={!data?.model_ready || busy || ['queued', 'running'].includes(job?.status)}><ArrowRight size={17} /> Lập chỉ mục</button></form>{job && <div className="embedding-job"><div><strong>Lượt gần nhất · {job.status === 'ready' ? 'Hoàn tất' : job.status === 'failed' ? 'Có lỗi' : 'Đang chạy'}</strong><small>{job.completed} / {job.total} đoạn</small></div><div className="embedding-track"><span style={{ width: `${jobPercent}%` }} /></div>{job.error && <p className="form-error">{job.error}</p>}</div>}</section>
  </div>;
}
