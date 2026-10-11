const $ = id => document.getElementById(id);
const statusNames = {queued:'Đang chờ',processing:'Đang xử lý',ready:'Hoàn tất',failed:'Có lỗi'};
let currentJob = null;
let currentPageNo = null;
let renderedPageKey = '';
let previewUrl = null;
let pollTimer = null;

function notice(message='') { $('notice').textContent = message; }
function fileSize(bytes) { return bytes >= 1024*1024 ? `${(bytes/1024/1024).toFixed(1)} MiB` : `${Math.ceil(bytes/1024)} KiB`; }
function clearPreviewUrl() { if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null; }
function preview(node, label) { $('preview-frame').replaceChildren(node); $('preview-label').textContent = label; }
function showSelectedFile() {
  const file = $('source-file').files[0];
  clearPreviewUrl();
  $('boxes-toggle').hidden=true;
  if (!file) { $('file-summary').hidden=true; return; }
  $('file-summary').hidden=false;
  $('file-name').textContent=file.name;
  $('file-size').textContent=fileSize(file.size);
  previewUrl=URL.createObjectURL(file);
  const isPdf=file.type==='application/pdf' || file.name.toLowerCase().endsWith('.pdf');
  if (isPdf) {
    const frame=document.createElement('iframe');frame.title=`Xem trước ${file.name}`;frame.src=previewUrl+'#page=1&view=FitH';
    preview(frame,'Xem trước PDF');
  } else {
    const image=document.createElement('img');image.alt=`Xem trước ${file.name}`;image.src=previewUrl;
    preview(image,'Xem trước ảnh');
  }
}

$('source-file').addEventListener('change', showSelectedFile);
const dropzone=$('dropzone');
dropzone.addEventListener('dragover', event=>{event.preventDefault();dropzone.classList.add('dragging')});
dropzone.addEventListener('dragleave', ()=>dropzone.classList.remove('dragging'));
dropzone.addEventListener('drop', event=>{event.preventDefault();dropzone.classList.remove('dragging');
  if(event.dataTransfer.files.length){$('source-file').files=event.dataTransfer.files;showSelectedFile()}
});

function resetView() {
  if(pollTimer)clearTimeout(pollTimer);
  pollTimer=null;currentJob=null;currentPageNo=null;renderedPageKey='';
  history.replaceState(null,'',location.pathname);
  $('ocr-form').reset();$('source-file').value='';$('file-summary').hidden=true;
  $('empty-result').hidden=false;$('job-result').hidden=true;
  $('result-status').textContent='Sẵn sàng';$('result-status').className='pill';
  $('preview-frame').replaceChildren();
  $('preview-frame').dataset.page='';$('edit-status').textContent='';
  $('boxes-toggle').hidden=true;
  const box=document.createElement('div');box.className='preview-empty';
  const icon=document.createElement('span');icon.textContent='▣';
  const text=document.createElement('p');text.textContent='Bản xem trước sẽ xuất hiện tại đây';
  box.append(icon,text);preview(box,'Chưa chọn tài liệu');clearPreviewUrl();notice();
}
$('new-job').onclick=resetView;

async function request(path,options={}) {
  const response=await fetch(path,options);
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||`Lỗi ${response.status}`)}
  return response.json();
}

function renderJob(job) {
  const previousId=currentJob?.id;
  currentJob=job;
  $('empty-result').hidden=true;$('job-result').hidden=false;
  $('result-status').textContent=statusNames[job.status]||job.status;
  $('result-status').className='pill '+job.status;
  $('progress-title').textContent=job.status==='ready'?'Đã xử lý xong':job.status==='failed'?'Xử lý bị gián đoạn':'Đang xử lý tài liệu';
  $('progress-count').textContent=`${job.processed_pages}/${job.total_pages} trang`;
  $('progress-bar').style.width=`${job.total_pages?Math.round(100*job.processed_pages/job.total_pages):0}%`;
  $('progress-detail').textContent=job.status==='processing' ? `Đang đọc trang ${Math.min(job.end_page,job.start_page+job.processed_pages)}…` :
    job.status==='queued'?'Tác vụ đã vào hàng chờ.':job.status==='ready'?'Có thể sửa kết quả và tải về.':'';
  $('result-file-name').textContent=job.filename;
  $('result-summary').textContent=`${job.type==='pdf'?'PDF':'Ảnh'} · ${job.mode==='auto'?'Tự chọn chữ in/viết tay':job.mode==='printed'?'Chữ in':'Chữ viết tay'} · ${job.total_pages} trang`;
  $('download-txt').href=`/api/jobs/${job.id}/export/txt`;
  $('download-json').href=`/api/jobs/${job.id}/export/json`;
  $('job-error').hidden=job.status!=='failed';$('job-error').textContent=job.error||'';

  if(previousId!==job.id || !job.results.some(page=>page.page_no===currentPageNo)){
    currentPageNo=job.results[0]?.page_no??null;renderedPageKey='';
  }
  const tabs=$('page-tabs');tabs.replaceChildren();
  job.results.forEach(page=>{
    const button=document.createElement('button');button.type='button';button.textContent=`Trang ${page.page_no}`;
    button.className=page.page_no===currentPageNo?'active':'';
    button.setAttribute('role','tab');button.setAttribute('aria-selected',String(page.page_no===currentPageNo));
    button.onclick=()=>{currentPageNo=page.page_no;renderedPageKey='';renderJob(currentJob)};
    tabs.append(button);
  });
  const page=job.results.find(item=>item.page_no===currentPageNo);
  $('page-content').hidden=!page;
  if(!page){$('boxes-toggle').hidden=true;return}
  $('page-title').textContent=`Trang ${page.page_no}`;
  const printedLines=page.lines?.filter(line=>line.recognition_mode==='printed').length||0;
  const handwrittenLines=page.lines?.filter(line=>line.recognition_mode==='handwritten').length||0;
  $('page-source').textContent=page.source==='native-pdf'?'Text có sẵn trong PDF':
    `${page.detector==='paddle_server'?'PaddleOCR server tìm dòng · VietOCR đọc':page.detector==='paddle_mobile'?'PaddleOCR mobile tìm dòng · VietOCR đọc':page.detector==='simple'?'Dò dòng đơn giản · VietOCR đọc':'OCR'} · ${printedLines} dòng in, ${handwrittenLines} dòng viết tay · ${page.seconds} giây`;
  $('detection-warning').hidden=!page.detection_warning;
  $('detection-warning').textContent=page.detection_warning||'';
  const key=`${job.id}:${page.page_no}`;
  if(key!==renderedPageKey || document.activeElement!==$('page-text')){
    $('page-text').value=page.corrected_text;
    if(key!==renderedPageKey)$('edit-status').textContent='';
    renderedPageKey=key;
  }
  if(previousId!==job.id || $('preview-frame').dataset.page!==key){
    clearPreviewUrl();
    const image=document.createElement('img');image.alt=`Bản gốc trang ${page.page_no}`;
    image.src=`/api/jobs/${job.id}/pages/${page.page_no}/preview`;
    const annotated=annotatedPreview(image,page);
    preview(annotated,`Trang ${page.page_no} / ${job.page_count}`);
    $('preview-frame').dataset.page=key;
  }
  $('boxes-toggle').hidden=!(page.lines?.length&&page.image_size);
  $('preview-frame').classList.toggle('boxes-off',!$('show-boxes').checked);
}

function annotatedPreview(image,page){
  if(!page.image_size||!page.lines?.length)return image;
  const [width,height]=page.image_size;
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)return image;
  const wrapper=document.createElement('div');wrapper.className='annotated-preview';wrapper.append(image);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('aria-hidden','true');
  page.lines.forEach((line,index)=>{
    if(!Array.isArray(line.polygon)||line.polygon.length!==4)return;
    const points=line.polygon.map(point=>Array.isArray(point)&&point.length===2&&point.every(Number.isFinite)?point.join(','):null);
    if(points.includes(null))return;
    const polygon=document.createElementNS('http://www.w3.org/2000/svg','polygon');
    polygon.setAttribute('points',points.join(' '));
    const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`Dòng ${index+1}: ${line.text}`;
    polygon.append(title);svg.append(polygon);
  });
  wrapper.append(svg);return wrapper;
}
$('show-boxes').onchange=()=>$('preview-frame').classList.toggle('boxes-off',!$('show-boxes').checked);

async function loadJob(id) {
  const job=await request(`/api/jobs/${id}`);
  renderJob(job);
  history.replaceState(null,'',`?job=${id}`);
  if(pollTimer)clearTimeout(pollTimer);
  if(job.status==='queued'||job.status==='processing'){
    pollTimer=setTimeout(()=>loadJob(id).catch(error=>notice(error.message)),1000);
  } else {
    pollTimer=null;refreshHistory().catch(()=>{});
  }
}

$('ocr-form').onsubmit=async event=>{
  event.preventDefault();notice();
  const file=$('source-file').files[0];
  if(!file){notice('Hãy chọn PDF hoặc ảnh trước.');return}
  const isPdf=file.type==='application/pdf'||file.name.toLowerCase().endsWith('.pdf');
  if(file.size>(isPdf?200:50)*1024*1024){notice(isPdf?'PDF vượt quá 200 MiB.':'Ảnh vượt quá 50 MiB.');return}
  $('submit').disabled=true;
  try{
    const form=new FormData(event.target);
    if(!form.get('end_page'))form.delete('end_page');
    const created=await request('/api/jobs',{method:'POST',body:form});
    $('preview-frame').dataset.page='';
    await loadJob(created.id);
    refreshHistory().catch(()=>{});
  }catch(error){notice(error.message)}finally{$('submit').disabled=false}
};

$('save-page').onclick=async()=>{
  if(!currentJob||currentPageNo===null)return;
  try{
    await request(`/api/jobs/${currentJob.id}/pages/${currentPageNo}`,{
      method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:$('page-text').value})
    });
    const page=currentJob.results.find(item=>item.page_no===currentPageNo);
    page.corrected_text=$('page-text').value;
    $('edit-status').textContent='Đã lưu';
  }catch(error){$('edit-status').textContent=error.message}
};
$('page-text').addEventListener('input',()=>$('edit-status').textContent='Chưa lưu');
$('copy-page').onclick=async()=>{
  try{await navigator.clipboard.writeText($('page-text').value);$('edit-status').textContent='Đã sao chép'}
  catch(error){$('edit-status').textContent='Không thể sao chép: '+error.message}
};

async function refreshHistory(){
  const data=await request('/api/jobs');const root=$('history-list');root.replaceChildren();
  if(!data.jobs.length){const empty=document.createElement('p');empty.className='history-empty';empty.textContent='Chưa có lượt xử lý nào.';root.append(empty);return}
  data.jobs.forEach(job=>{
    const button=document.createElement('button');button.type='button';button.className='history-item';
    const left=document.createElement('span');const title=document.createElement('strong');title.textContent=job.filename;
    const date=document.createElement('small');date.textContent=new Date(job.created_at).toLocaleString('vi-VN');left.append(title,date);
    const right=document.createElement('span');right.textContent=`${statusNames[job.status]||job.status} · ${job.processed_pages}/${job.total_pages}`;
    button.append(left,right);button.onclick=()=>loadJob(job.id).catch(error=>notice(error.message));root.append(button);
  });
}
$('refresh-history').onclick=()=>refreshHistory().catch(error=>notice(error.message));
refreshHistory().catch(error=>notice(error.message));
const initialJob=new URLSearchParams(location.search).get('job');
if(initialJob)loadJob(initialJob).catch(error=>notice(error.message));
