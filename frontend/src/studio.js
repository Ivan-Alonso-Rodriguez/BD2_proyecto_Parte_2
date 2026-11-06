import {createStoreMap} from './store-map.js';

const $ = id => document.getElementById(id);
const state = { category: '', rows: [], reference: null, file: null, objectUrl: null, center: [-12.10, -77.04], view: 'explore', resultView: 'grid', busy: false, serial: 0 };
const names = {Apparel:'Ropa', Footwear:'Calzado', Accessories:'Accesorios', 'Personal Care':'Cuidado personal'};
const money = new Intl.NumberFormat('es-PE', {style:'currency', currency:'PEN'});
const number = new Intl.NumberFormat('es-PE');
const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let map, mapLoading;

async function api(path, options={}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw Error(typeof body.detail === 'string' ? body.detail : 'Revisa los valores de la consulta.');
  return body;
}
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
function clearMetrics() {
  ['latency','reads','writes','index-reads','table-reads','blob-reads','approximate'].forEach(id => $(id).textContent='—');
  $('pipeline').replaceChildren();
}
function metrics(result) {
  $('latency').textContent = result.exec_time_ms.toFixed(1);
  $('reads').textContent = number.format(result.disk_reads);
  $('writes').textContent = number.format(result.disk_writes);
  const io = result.io_breakdown || {};
  ['index','table','blob'].forEach(kind => $(kind+'-reads').textContent=number.format(io[kind]?.disk_reads || 0));
  const plan = result.execution_plan || {};
  $('approximate').textContent = plan.approximate ? 'APROXIMADA' : 'EXACTA';
  const steps = plan.steps || [result.access_path];
  $('pipeline').innerHTML = steps.map(step=>`<li>${escape(step)}</li>`).join('');
}
function renderProducts(result) {
  state.rows = result.rows;
  $('result-count').textContent = `${result.rows.length} resultados mostrados · ${state.reference || state.file ? 'similitud visual' : $('search').value.trim() ? 'relevancia textual' : 'selección del catálogo'}`;
  $('results-title').textContent = state.reference || state.file ? 'Una imagen, nuevas posibilidades' : $('search').value.trim() ? 'Lo que encontramos para ti' : 'El catálogo, a tu alcance';
  $('empty').hidden = !!result.rows.length || state.resultView === 'map';
  const visualDistance = ['ivf','exact','spatial_knn'].includes($('mode').value);
  $('product-grid').innerHTML = result.rows.map(row => `<article class="product-card">
    <div class="product-image"><span class="product-number">${escape(row.id)}</span><img src="${escape(row.imagen_url)}" alt="${escape(row.titulo)}" loading="lazy"><button class="similar-button" data-similar="${row.id}" aria-label="Buscar similares a ${escape(row.titulo)}" title="Buscar productos similares">↗</button></div>
    <div class="product-info"><span class="product-category">${escape(names[row.categoria] || row.categoria)}</span><h3 class="product-name" title="${escape(row.titulo)}">${escape(row.titulo)}</h3><div class="product-meta"><span class="product-price">${money.format(row.precio)}</span><span class="product-distance">${row.distancia_km !== undefined ? row.distancia_km.toFixed(1)+' km' : '◎ Lima'}</span></div>${row.score ? `<div class="score">${visualDistance ? 'Distancia' : 'Relevancia'} · ${row.score.toFixed(4)}</div>` : ''}</div></article>`).join('');
  metrics(result);
  if (state.resultView === 'map') renderMap();
}
function spec() {
  let mode = $('mode').value;
  if (['ivf','exact','bovw'].includes(mode) && !state.reference && !state.file) throw Error('Sube una imagen o pulsa ↗ en un producto para buscar similares.');
  if (mode === 'spatial_knn') $('nearby').checked=true;
  const body = {mode, text:$('search').value.trim(), k:12, probes:Number($('probes').value)};
  if (state.category) body.category = state.category;
  if ($('max-price').value !== '') body.max_price = Number($('max-price').value);
  if ($('nearby').checked) Object.assign(body, {lon:state.center[1], lat:state.center[0], radius:Number($('radius').value)});
  if (state.reference) body.reference_id = state.reference.id;
  return body;
}
async function search() {
  const serial = ++state.serial;
  error('');
  state.busy = true;
  document.body.classList.add('loading');
  $('search-button').disabled = true;
  $('result-count').textContent = 'Consultando páginas en disco…';
  try {
    const body = spec();
    let result;
    if (state.file && ['ivf','exact','bovw'].includes(body.mode)) {
      const params = new URLSearchParams();
      for (const key of ['mode','k','probes','category','max_price','lon','lat','radius','text']) if (body[key] !== undefined) params.set(key, body[key]);
      result = await api('/api/multimodal/image-search?'+params, {method:'POST', body:state.file, headers:{'Content-Type':state.file.type}});
    } else result = await api('/api/multimodal/search', {method:'POST', body:JSON.stringify(body), headers:{'Content-Type':'application/json'}});
    if (serial === state.serial) renderProducts(result);
  } catch (exception) {
    if (serial === state.serial) {
      error(exception.message);
      clearMetrics();
      state.rows=[];
      $('product-grid').replaceChildren();
      $('result-count').textContent='Consulta no completada';
      if (map) map.clear();
    }
  } finally {
    if (serial === state.serial) {
      state.busy = false;
      document.body.classList.remove('loading');
      $('search-button').disabled=false;
    }
  }
}
function showReference(name, url) {
  $('reference-name').textContent=name;
  $('reference-preview').src=url;
  $('reference').hidden=false;
  $('search').value='';
  $('mode').value='ivf';
}
function clearReference() {
  state.reference=null;
  state.file=null;
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl=null;
  $('image-upload').value='';
  $('reference').hidden=true;
  $('mode').value='text';
  search();
}
function setResultsView(view) {
  state.resultView=view;
  $('product-grid').hidden=view==='map';
  $('map-panel').hidden=view!=='map';
  $('empty').hidden=!!state.rows.length || view==='map';
  document.querySelectorAll('[data-results-view]').forEach(button=>button.classList.toggle('active',button.dataset.resultsView===view));
  if (view==='map') renderMap();
}
async function renderMap() {
  try {
    if (!map) {
      if (!mapLoading) mapLoading=api('/api/maps/config').then(config=>createStoreMap(
        $('map'),config,state.center,center=>{
          state.center=center;
          $('nearby').checked=true;
          search();
        },message=>{
          $('map-status').textContent=message;
          $('map-status').hidden=!message;
        }
      )).catch(exception=>{mapLoading=null;throw exception;});
      map=await mapLoading;
    }
  } catch(exception) {
    $('map-status').textContent='No se pudo configurar el mapa: '+exception.message;
    $('map-status').hidden=false;
    return;
  }
  if (state.resultView!=='map') return;
  map.render(state.rows,state.center,$('nearby').checked?Number($('radius').value)*1000:null);
  $('map-center').textContent=`${state.center[1].toFixed(4)}, ${state.center[0].toFixed(4)}`;
}
const headings={explore:['DESCUBRIMIENTO MULTIMODAL','Encuentra lo que tienes<br>en mente<span class="purple">.</span>','Una idea, una imagen o un lugar. Tres formas de explorar el mismo catálogo.'],map:['BÚSQUEDA ESPACIAL','Más cerca de lo<br>que buscas<span class="purple">.</span>','Explora tiendas y filtra por radio. Cada punto se recupera desde un R-Tree en disco.'],sql:['CONSULTAS DECLARATIVAS','Del SQL a las<br>páginas en disco<span class="purple">.</span>','Consulta texto, precios y ubicaciones con el plan de ejecución a la vista.'],benchmarks:['EXPERIMENTACIÓN Y RENDIMIENTO','La evidencia detrás<br>de cada índice<span class="purple">.</span>','Datos medidos, consultas separadas y comparaciones reproducibles.' ]};
function view(name) {
  state.view=name;error('');
  document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===name));
  const h=headings[name];$('section-kicker').textContent=h[0];$('page-title').innerHTML=h[1];$('page-intro').textContent=h[2];
  $('search-section').hidden=!['explore','map'].includes(name);
  $('results-layout').hidden=!['explore','map'].includes(name);
  $('sql-panel').hidden=name!=='sql';$('benchmarks-panel').hidden=name!=='benchmarks';
  if (name==='explore'||name==='map') setResultsView(name==='map'?'map':'grid');
  if (name==='benchmarks') benchmarks();
}
const examples={
 text:"SELECT id, titulo, COSINE_SCORE() AS relevancia\nFROM productos\nWHERE cuerpo MATCH 'blue shirt'\nORDER BY relevancia DESC LIMIT 10;",
 boolean:"SELECT id, titulo, precio, COSINE_SCORE() AS relevancia\nFROM productos\nWHERE cuerpo MATCH 'black AND shoes AND NOT women'\nAND precio <= 250\nORDER BY relevancia DESC LIMIT 10;",
 spatial:"SELECT id, titulo, precio, ubicacion\nFROM productos\nWHERE ubicacion WITHIN_RADIUS ((-77.04, -12.10), 2.5)\nLIMIT 20;",
 probes:"SET ivf.probes = 10;",
 relational:"SELECT id, titulo, precio FROM productos\nWHERE precio >= 100 AND precio <= 150;"
};
function tableHtml(rows, columns) {
  return `<thead><tr>${columns.map(c=>`<th>${escape(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(c=>`<td>${escape(typeof row[c]==='object'?JSON.stringify(row[c]):row[c]??'')}</td>`).join('')}</tr>`).join('')}</tbody>`;
}
async function executeSQL() {
  error('');$('run-sql').disabled=true;$('sql-message').textContent='Ejecutando…';
  try {
    const result=await api('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sql:$('sql-input').value,limit:100})});
    $('sql-table').innerHTML=tableHtml(result.rows,result.columns);
    $('sql-message').textContent=`${result.message} · ${result.exec_time_ms.toFixed(2)} ms · ${result.disk_reads} lecturas · ${result.disk_writes} escrituras`;
    $('sql-plan').textContent=JSON.stringify(result.execution_plan || {access_path:result.access_path},null,2);
  } catch(e) {error(e.message);$('sql-table').replaceChildren();$('sql-plan').textContent='';$('sql-message').textContent='Consulta no completada';}
  finally{$('run-sql').disabled=false;}
}
async function benchmarks() {
  try {
    const data=await api('/api/multimodal/benchmarks');
    const cards=[
      ['05','Escalabilidad espacial','10000, 50000 y 100000 puntos. Radios, k-NN y efecto de 2 a 128 dimensiones.','exp5_spatial',['exp5_spatial.png','exp5_dimensions.png']],
      ['06','Recuperación textual','Corpus de hasta 20000 documentos. TF-IDF frente a Full Scan y PostgreSQL GIN. Los buffers de PostgreSQL usan 8 KB; el motor propio usa 4 KB.','exp6_build',['exp6_build.png','exp6_query.png']],
      ['07','SIFT frente a ResNet-18','Precision@5 y @10 con 100 imágenes fuera del índice. Relevancia definida por articleType del dataset.','exp7_quality',['exp7_quality.png']],
      ['08','Calidad frente a costo','Recall@10 de IVF contra k-NN exacto, variando probes de 1 a 100.','exp8_ann',['exp8_recall_latency.png','exp8_reads.png']]
    ];
    $('benchmark-content').innerHTML=cards.map(([no,title,description,key,images])=>{
      const rows=data[key] || [];
      return `<article class="benchmark-card"><p class="eyebrow">EXPERIMENTO ${no}</p><h2>${title}</h2><p>${description}</p>${rows.length?`<div class="benchmark-charts">${images.map(img=>`<img loading="lazy" src="/experiments/${img}" alt="Gráfica del experimento ${no}">`).join('')}</div><table>${tableHtml(rows.slice(0,16),Object.keys(rows[0]).slice(0,8))}</table><p><a href="/experiments/${key}.csv" download>Descargar CSV completo ↗</a></p>`:'<p>Este experimento aún no tiene resultados. Ejecuta el benchmark correspondiente.</p>'}</article>`;
    }).join('');
  } catch(e){error(e.message);}
}
$('search-form').addEventListener('submit',event=>{event.preventDefault();search();});
$('categories').addEventListener('click',event=>{const button=event.target.closest('[data-category]');if(!button)return;state.category=button.dataset.category;document.querySelectorAll('[data-category]').forEach(b=>b.classList.toggle('active',b===button));search();});
$('product-grid').addEventListener('click',event=>{const button=event.target.closest('[data-similar]');if(!button)return;state.reference=state.rows.find(r=>r.id===Number(button.dataset.similar));state.file=null;if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);showReference(state.reference.titulo,state.reference.imagen_url);search();});
$('image-upload').addEventListener('change',event=>{const file=event.target.files[0];if(!file)return;if(file.size>10*1024*1024){error('La imagen debe pesar menos de 10 MB.');return;}state.reference=null;state.file=file;if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);state.objectUrl=URL.createObjectURL(file);showReference(file.name,state.objectUrl);search();});
$('clear-reference').addEventListener('click',clearReference);
['mode','probes','nearby','radius'].forEach(id=>$(id).addEventListener('change',()=>search()));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>view(button.dataset.view)));
document.querySelectorAll('[data-results-view]').forEach(button=>button.addEventListener('click',()=>setResultsView(button.dataset.resultsView)));
$('sql-example').addEventListener('change',()=>$('sql-input').value=examples[$('sql-example').value]);
$('sql-input').value=examples.text;
const nearestOption=document.createElement('option');nearestOption.value='spatial_knn';nearestOption.textContent='Ubicación · k-NN';$('mode').append(nearestOption);
$('run-sql').addEventListener('click',executeSQL);
$('sql-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();executeSQL();}});
try {
  const info=await api('/api/multimodal/status');
  if(!info.ready)throw Error('El motor está disponible, pero falta cargar el catálogo. Ejecuta: python setup.py --full');
  $('connection').textContent='Motor conectado';$('product-count').textContent=number.format(info.n);
  await search();
} catch(e){$('connection').textContent='Catálogo pendiente';error(e.message);$('result-count').textContent='Sin datos cargados';}
