'use strict';
const reportState={current:null,drafts:[],dirty:false,busy:false};
const reportKinds={monthly:'Theo tháng',category:'Ngành hàng',state:'Bang',seller:'Người bán'};
const reportMetrics={product_gmv:'GMV hàng hóa (BRL)',orders:'Số đơn',late_rate:'Tỷ lệ giao trễ'};
const reportDimensions={monthly:'month',category:'category',state:'state',seller:'seller_id'};
const reportColumns={month:'Tháng',category:'Ngành hàng',state:'Bang',seller_id:'Người bán',orders:'Số đơn',product_gmv:'GMV (BRL)',late_rate:'Tỷ lệ trễ',late_orders:'Đơn trễ',late_eligible:'Đủ ngày giao'};

function reportValue(value,metric){return value==null?'Chưa đủ dữ liệu':metric.includes('rate')?percent(value):['product_gmv','product_aov','freight'].includes(metric)?money(value):typeof value==='number'?number(value):String(value);}
function reportOptions(options,selected){return Object.entries(options).map(([key,label])=>`<option value="${key}" ${key===selected?'selected':''}>${esc(label)}</option>`).join('');}
function reportDirty(){reportState.dirty=true;const label=$('#report-save-state');if(label)label.textContent='Có thay đổi chưa lưu';}
function reportLock(){document.querySelectorAll('#report-workspace input,#report-workspace textarea,#report-workspace select,#report-workspace button,#report-new,.report-draft,.report-from-chat').forEach(el=>{if(reportState.busy){if(el.dataset.reportWasDisabled===undefined)el.dataset.reportWasDisabled=el.disabled?'1':'0';el.disabled=true;}else if(el.dataset.reportWasDisabled!==undefined){el.disabled=el.dataset.reportWasDisabled==='1';delete el.dataset.reportWasDisabled;}});}
function reportPayload(){const r=reportState.current;return Object.fromEntries(['title','filters','notes','charts','include_tables','version'].map(key=>[key,r[key]]));}

async function reportPage(){
 reportState.drafts=await api('/report-drafts');
 return `<div class="page-enter"><div class="report-toolbar"><p class="muted">Bản nháp và số liệu được lưu trên máy.</p><button class="button" id="report-new">${icon('chart')}Tạo báo cáo</button></div><div id="report-notice" role="status"></div><div class="report-layout"><aside class="panel report-library" aria-label="Báo cáo đã lưu"><h2>Bản nháp đã lưu</h2><div id="report-list">${reportList()}</div></aside><section id="report-workspace">${reportWorkspace()}</section></div></div>`;
}
function reportList(){return reportState.drafts.map(r=>`<button class="report-draft ${r.id===reportState.current?.id?'selected':''}" data-report-open="${r.id}"><strong>${esc(r.title)}</strong><small>${esc(scopeText(r.filters))}</small><small>${esc(new Date(r.updated_at).toLocaleString('vi-VN'))}</small></button>`).join('')||'<p class="muted">Chưa có báo cáo. Tạo mới hoặc đưa một kết quả BI từ chat vào đây.</p>';}
function reportWorkspace(){
 const r=reportState.current;
 if(!r)return empty('Một báo cáo, đủ số liệu và nguồn','Chọn ngày, bang, biểu đồ và sửa nhận xét trước khi tải PDF hoặc Excel.');
 const snapshot=r.snapshot,values=snapshot.kpis.values;
 const stale=JSON.stringify(r.filters)!==JSON.stringify(snapshot.kpis.filters);
 const original=r.source;
 const sourceChanged=original&&JSON.stringify(original.filters)!==JSON.stringify(r.filters);
 return `<div class="panel report-editor"><div class="report-toolbar"><span class="tag neutral" id="report-save-state">${reportState.dirty?'Có thay đổi chưa lưu':'Đã lưu · bản '+r.version}</span><div class="report-actions"><button class="button secondary small" id="report-save">Lưu bản nháp</button><button class="button small" data-report-download="pdf">${icon('download')}PDF</button><button class="button secondary small" data-report-download="xlsx">${icon('download')}Excel</button></div></div>
 <label class="field"><span>Tiêu đề báo cáo</span><input id="report-title" maxlength="160" value="${esc(r.title)}" required></label>
 <div class="report-scope"><label class="field"><span>Từ ngày</span><input id="report-start" type="date" value="${esc(r.filters.start)}" required></label><label class="field"><span>Đến ngày</span><input id="report-end" type="date" value="${esc(r.filters.end)}" required></label><label class="field"><span>Bang khách hàng</span><select id="report-state"><option value="">Tất cả</option>${['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'].map(s=>`<option ${r.filters.state===s?'selected':''}>${s}</option>`).join('')}</select></label></div>
 <div id="report-stale" class="notice" ${stale?'':'hidden'}>Bộ lọc đã thay đổi. Lưu bản nháp để lấy số liệu mới; phần xem trước vẫn là số liệu đã lưu.</div>
 <p class="small-text muted">Số liệu đã lưu: ${esc(scopeText(snapshot.kpis.filters))} · ${esc(new Date(snapshot.generated_at).toLocaleString('vi-VN'))}</p>
 ${values.orders===0?'<div class="notice">Không có đơn hàng trong phạm vi đã chọn. Các số không không phản ánh doanh thu hiện tại.</div>':''}
 ${original?`<div class="notice"><strong>Từ cuộc chat:</strong> ${esc(original.question)}<br>Phạm vi chat: ${esc(scopeText(original.filters))} · ${original.status==='complete'?'Đã hoàn tất':'Chưa hoàn tất; cần rà soát nhận xét'}. Số liệu báo cáo được truy vấn lại từ BI.${sourceChanged?'<br><strong>Bộ lọc khác chat nguồn; hãy rà soát lại nhận xét.</strong>':''}</div>`:''}
 <div class="report-kpis">${[['GMV hàng hóa',money(values.product_gmv)],['Số đơn',number(values.orders)],['AOV hàng hóa',money(values.product_aov)],['Tỷ lệ giao trễ',percent(values.late_delivery_rate)]].map(([label,value])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('')}</div>
 <label class="field"><span>Nhận xét · bạn có thể chỉnh trước khi tải</span><textarea id="report-notes" rows="7" maxlength="8000" placeholder="Nhận xét, điểm cần đối chiếu và giới hạn…">${esc(r.notes)}</textarea></label>
 <div class="report-toolbar"><h2>Biểu đồ</h2><button class="button secondary small" id="report-add-chart" ${r.charts.length>=6?'disabled':''}>+ Thêm biểu đồ</button></div>
 <label class="report-table-toggle"><input id="report-tables" type="checkbox" ${r.include_tables?'checked':''}> Kèm bảng chi tiết trong báo cáo</label>
 <div id="report-charts">${r.charts.map(reportChartCard).join('')||'<p class="muted">Báo cáo hiện chỉ gồm KPI và nhận xét.</p>'}</div>
 <details class="evidence"><summary>Nguồn và giới hạn</summary><div class="evidence-content"><ul>${r.limits.map(text=>`<li>${esc(text)}</li>`).join('')}</ul><p>${esc(snapshot.kpis.definition)}</p><details><summary>Truy vấn và bộ lọc đã dùng</summary><pre>${esc(JSON.stringify({filters:snapshot.kpis.filters,kpis:snapshot.kpis.sql,datasets:Object.fromEntries(Object.entries(snapshot.datasets).map(([k,v])=>[k,v.sql]))},null,2))}</pre></details>${original?.documents.map(d=>`<p><strong>${esc(d.source)} · ${esc(d.section)} · ${esc(d.id)}</strong><br>${esc(d.text)}</p>`).join('')||''}</div></details></div>`;
}
function reportChartCard(spec,index){
 const dataset=reportState.current.snapshot.datasets[spec.kind];
 const metrics={...reportMetrics};if(spec.kind==='category')delete metrics.late_rate;
 return `<article class="report-chart-card" data-report-card="${index}"><div class="report-chart-controls"><label class="field"><span>Tên biểu đồ</span><input data-report-chart="${index}" data-report-field="title" maxlength="120" value="${esc(spec.title)}"></label><div class="report-chart-buttons"><button class="button secondary small" data-report-move="${index}" data-direction="-1" ${index===0?'disabled':''} aria-label="Đưa biểu đồ lên">↑</button><button class="button secondary small" data-report-move="${index}" data-direction="1" ${index===reportState.current.charts.length-1?'disabled':''} aria-label="Đưa biểu đồ xuống">↓</button><button class="button secondary small" data-report-remove="${index}">Bỏ</button></div></div>
 <div class="report-scope"><label class="field"><span>Dữ liệu</span><select data-report-chart="${index}" data-report-field="kind">${reportOptions(reportKinds,spec.kind)}</select></label><label class="field"><span>Chỉ tiêu</span><select data-report-chart="${index}" data-report-field="metric">${reportOptions(metrics,spec.metric)}</select></label><label class="field"><span>Dạng biểu đồ</span><select data-report-chart="${index}" data-report-field="chart_type">${reportOptions(spec.kind==='monthly'?{line:'Đường',bar:'Cột'}:{bar:'Cột'},spec.chart_type)}</select></label></div>
 <h3 data-report-heading="${index}">${esc(spec.title)}</h3><div data-report-plot="${index}">${dataset?reportChartSVG(spec,dataset.rows):'<div class="notice">Lưu bản nháp để lấy dữ liệu cho biểu đồ này.</div>'}</div>
 ${dataset&&reportState.current.include_tables?reportDataTable(dataset.rows):''}</article>`;
}
function reportChartSVG(spec,rows){
 const dimension=reportDimensions[spec.kind],points=rows.map(row=>({label:String(row[dimension]),value:row[spec.metric]}));
 const numeric=points.filter(p=>p.value!=null&&Number.isFinite(p.value));
 if(!numeric.length)return '<div class="empty-state">Chưa đủ dữ liệu để vẽ biểu đồ.</div>';
 const narrow=window.innerWidth<=760;
 const width=narrow?320:720,height=270,left=narrow?65:85,right=20,top=20,bottom=45,plotW=width-left-right,plotH=height-top-bottom;
 const maximum=Math.max(...numeric.map(p=>p.value),1e-9)*1.12;
 const x=i=>left+(i+.5)/points.length*plotW,y=v=>top+plotH-v/maximum*plotH;
 const ticks=Array.from({length:5},(_,i)=>{const value=maximum*i/4;return `<line x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}" stroke="#e5ece2"/><text x="${left-8}" y="${y(value)+4}" text-anchor="end">${esc(spec.metric==='late_rate'?percent(value):number(value))}</text>`;}).join('');
 let previous=null;
 const marks=points.map((point,i)=>{
  if(point.value==null){previous=null;return '';}
  const label=`${point.label}: ${reportValue(point.value,spec.metric)}`,xx=x(i),yy=y(point.value);
  let shape='';
  if(spec.chart_type==='bar'){const bw=plotW/points.length*.7;shape=`<rect x="${xx-bw/2}" y="${yy}" width="${bw}" height="${top+plotH-yy}" fill="#427759"><title>${esc(label)}</title></rect>`;}
  else{if(previous)shape=`<line x1="${previous[0]}" y1="${previous[1]}" x2="${xx}" y2="${yy}" stroke="#427759" stroke-width="2.5"/>`;shape+=`<circle cx="${xx}" cy="${yy}" r="4" fill="#427759"><title>${esc(label)}</title></circle>`;previous=[xx,yy];}
  if(i%Math.max(1,Math.ceil(points.length/(narrow?3:6)))===0)shape+=`<text x="${xx}" y="${height-15}" text-anchor="middle">${esc(point.label.length>15?point.label.slice(0,13)+'…':point.label)}</text>`;
  return shape;
 }).join('');
 return `<svg class="report-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(spec.title+' · '+reportMetrics[spec.metric])}">${ticks}${marks}</svg><p class="small-text muted">${esc(reportKinds[spec.kind])} · ${esc(reportMetrics[spec.metric])}. Giá trị thiếu được để trống. Nhãn dài được rút gọn; xem bảng để đối chiếu.</p>`;
}
function reportDataTable(rows){
 if(!rows.length)return '<p class="muted">Không có dòng dữ liệu trong phạm vi này.</p>';
 const keys=Object.keys(rows[0]);
 return `<details class="evidence"><summary>Bảng số liệu · ${rows.length} dòng</summary><div class="table-scroll"><table class="data-table"><thead><tr>${keys.map(k=>`<th>${esc(reportColumns[k]||k)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${keys.map(k=>`<td>${esc(reportValue(row[k],k))}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
}
function reportPaint(){if(state.page!=='reports')return;$('#report-workspace').innerHTML=reportWorkspace();$('#report-list').innerHTML=reportList();reportLock();}
window.addEventListener('resize',()=>{if(state.page!=='reports'||!reportState.current)return;reportState.current.charts.forEach((spec,i)=>{const target=$(`[data-report-plot="${i}"]`),data=reportState.current.snapshot.datasets[spec.kind];if(target&&data)target.innerHTML=reportChartSVG(spec,data.rows);});});
async function reportSave(){
 if(!reportState.current||!reportState.dirty)return;
 const saved=await api('/report-drafts/'+reportState.current.id,{method:'PUT',body:reportPayload()});
 reportState.current=saved;reportState.dirty=false;
 reportState.drafts=await api('/report-drafts');reportPaint();
}
async function reportCreate(sourceRun=null){
 await reportSave();
 const body=sourceRun?{source_run_id:sourceRun,title:'Báo cáo từ cuộc chat'}:{filters:{...state.filters}};
 const report=await api('/report-drafts',{method:'POST',body});
 reportState.current=report;reportState.dirty=false;
 await navigate('reports');toast('Đã tạo bản nháp báo cáo.');
}
async function reportDownload(format){
 await reportSave();
 const r=reportState.current;
 const response=await fetch(`/report-drafts/${r.id}/export/${format}`,{credentials:'same-origin'});
 if(!response.ok){if(response.status===401)showConnect();const error=await response.json();throw new Error(readableError(error.detail));}
 const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
 link.href=url;link.download=`olist_report_${r.id.slice(0,8)}.${format}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 toast('Đã tải báo cáo '+format.toUpperCase()+'.');
}
document.addEventListener('input',e=>{
 if(!reportState.current||reportState.busy)return;
 const el=e.target,r=reportState.current;
 if(el.id==='report-title'){r.title=el.value;reportDirty();}
 if(el.id==='report-notes'){r.notes=el.value;reportDirty();}
 if(el.dataset.reportField==='title'){r.charts[Number(el.dataset.reportChart)].title=el.value;reportDirty();const title=$(`[data-report-heading="${el.dataset.reportChart}"]`);if(title)title.textContent=el.value;}
});
document.addEventListener('change',e=>{
 if(!reportState.current||reportState.busy)return;
 const el=e.target,r=reportState.current;
 if(['report-start','report-end','report-state'].includes(el.id)){
  r.filters={start:$('#report-start').value,end:$('#report-end').value,state:$('#report-state').value||null};reportDirty();$('#report-stale').hidden=false;
 }
 if(el.id==='report-tables'){r.include_tables=el.checked;reportDirty();reportPaint();}
 if(el.dataset.reportField&&el.dataset.reportField!=='title'){
  const spec=r.charts[Number(el.dataset.reportChart)];spec[el.dataset.reportField]=el.value;
  if(spec.kind!=='monthly')spec.chart_type='bar';
  if(spec.kind==='category'&&spec.metric==='late_rate')spec.metric='product_gmv';
  reportDirty();reportPaint();
 }
});
document.addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 const isAction=b.id?.startsWith('report-')||['reportChat','reportOpen','reportDownload','reportRemove','reportMove'].some(k=>b.dataset[k]!==undefined);
 if(!isAction||reportState.busy)return;
 e.preventDefault();reportState.busy=true;reportLock();
 try{
  if(b.dataset.reportChat){await reportCreate(b.dataset.reportChat);return;}
  if(b.id==='report-reload'){reportState.current=await api('/report-drafts/'+reportState.current.id);reportState.dirty=false;$('#report-notice').innerHTML='';reportPaint();return;}
  if(b.id==='report-new'){await reportCreate();return;}
  if(b.dataset.reportOpen){await reportSave();reportState.current=await api('/report-drafts/'+b.dataset.reportOpen);reportState.dirty=false;reportPaint();return;}
  if(b.id==='report-save'){await reportSave();toast('Đã lưu bản nháp.');return;}
  if(b.dataset.reportDownload){await reportDownload(b.dataset.reportDownload);return;}
  const r=reportState.current;if(!r)return;
  if(b.id==='report-add-chart'&&r.charts.length<6){r.charts.push({kind:'monthly',metric:'orders',chart_type:'line',title:'Số đơn theo tháng'});reportDirty();reportPaint();}
  if(b.dataset.reportRemove!==undefined){r.charts.splice(Number(b.dataset.reportRemove),1);reportDirty();reportPaint();}
  if(b.dataset.reportMove!==undefined){const i=Number(b.dataset.reportMove),j=i+Number(b.dataset.direction);if(j>=0&&j<r.charts.length){[r.charts[i],r.charts[j]]=[r.charts[j],r.charts[i]];reportDirty();reportPaint();}}
 }catch(error){const target=$('#report-notice');if(target)target.innerHTML=`<div class="notice error">${esc(error.message)}${error.status===409?'<p><button id="report-reload" class="button secondary small">Bỏ sửa và mở lại bản đã lưu</button></p>':''}</div>`;else toast(error.message);}
 finally{reportState.busy=false;reportLock();}
});
