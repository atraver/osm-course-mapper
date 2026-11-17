'use strict';

async function openReview() {
  const response = await fetch('review.json');
  if (!response.ok) throw Error('The review data could not be loaded');
  const data = await response.json();
  const byId = id => document.getElementById(id);
  const svg = byId('map');
  const colors = {bunker:'#ffd56a',water:'#73deff',green:'#57f3ac',tee:'#ffacf4',fairway:'#c7ee77'};
  const {z,x0,y0,x1,y1} = data.grid;
  const width = 256*(x1-x0+1), height = 256*(y1-y0+1), scale = 256*2**z;
  const frame = {x:0,y:0,w:width,h:height};
  const paths = new Map(), features = data.candidates.features;
  const key = 'course-imagery-review:'+data.revision;
  let decisions = {}, selected = null, drag = null, moved = false;
  try { decisions = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch {}
  function pixel([lon,lat]) {
    return [(lon+180)/360*scale-256*x0,(1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)*scale/2-256*y0];
  }
  function draw(feature, layer) {
    const geometry = feature.geometry;
    const line = geometry.type === 'LineString';
    const rings = line ? [geometry.coordinates] : geometry.coordinates;
    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    const d = rings.map(ring => 'M'+ring.map(p => pixel(p).map(n=>n.toFixed(2)).join(' ')).join('L')+(line?'':'Z')).join('');
    path.setAttribute('d', d);
    path.setAttribute('fill-rule','evenodd');
    if (line) path.classList.add('line');
    byId(layer).append(path);
    return path;
  }
  function view() { svg.setAttribute('viewBox',[frame.x,frame.y,frame.w,frame.h].join(' ')); }
  function fit() { Object.assign(frame,{x:0,y:0,w:width,h:height}); view(); }
  function pointer(event) {
    const pt = new DOMPoint(event.clientX,event.clientY);
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }
  function zoom(factor, cx=frame.x+frame.w/2, cy=frame.y+frame.h/2) {
    const ratio = Math.max(0.018,Math.min(1.5,frame.w/width*factor))/(frame.w/width);
    Object.assign(frame,{x:cx-(cx-frame.x)*ratio,y:cy-(cy-frame.y)*ratio,w:frame.w*ratio,h:frame.h*ratio});
    view();
  }
  function select(feature, focus=false) {
    selected = feature;
    if (focus && feature) {
      const b = paths.get(feature.id).getBBox();
      const aspect = width/height;
      frame.w = Math.min(width,Math.max(160,b.width*2,b.height*aspect*2));
      frame.h = frame.w/aspect;
      frame.x = b.x+(b.width-frame.w)/2; frame.y = b.y+(b.height-frame.h)/2;
      view();
    }
    update();
  }
  function update() {
    const kept = features.filter(f=>decisions[f.id]==='keep').length;
    const pending = features.filter(f=>!decisions[f.id]).length;
    byId('totals').textContent = pending+' pending · '+kept+' kept · '+(features.length-pending-kept)+' skipped';
    for (const f of features) {
      const path = paths.get(f.id);
      path.style.display = byId('filter').value && byId('filter').value!==f.properties.kind ? 'none' : '';
      path.classList.toggle('selected',selected===f);
      path.classList.toggle('kept',decisions[f.id]==='keep');
      path.classList.toggle('skipped',decisions[f.id]==='skip');
    }
    const p = selected?.properties;
    byId('selection').textContent = selected ? [p.kind,p.hole?'hole '+p.hole:'unassigned',p.capture_month,decisions[selected.id] || 'pending'].filter(Boolean).join(' · ') : 'Select an outline';
    byId('keep').disabled = byId('skip').disabled = !selected;
    byId('undo').disabled = !selected || !decisions[selected.id];
    byId('export').disabled = !kept;
    byId('next').disabled = !features.some(f=>!decisions[f.id] && (!byId('filter').value || f.properties.kind===byId('filter').value));
  }
  function next() {
    const start = features.indexOf(selected)+1;
    const ordered = features.slice(start).concat(features.slice(0,start));
    const feature = ordered.find(f=>!decisions[f.id] && (!byId('filter').value || f.properties.kind===byId('filter').value));
    if (feature) select(feature,true);
  }
  function decide(outcome) {
    if (!selected) return;
    if (outcome) decisions[selected.id] = outcome;
    else delete decisions[selected.id];
    try { localStorage.setItem(key,JSON.stringify(decisions)); }
    catch { byId('title').textContent = data.title+' (session only)'; }
    update();
  }
  byId('title').textContent = data.title;
  byId('photo').setAttribute('width',width); byId('photo').setAttribute('height',height);
  for (const f of data.reference.features) draw(f,'reference');
  for (const f of features) {
    const path = draw(f,'shapes');
    path.classList.add('candidate'); path.dataset.key=f.id;
    path.setAttribute('fill',colors[f.properties.kind]); path.setAttribute('stroke',colors[f.properties.kind]);
    paths.set(f.id,path);
  }
  for (const kind of Object.keys(colors)) byId('filter').add(new Option(kind,kind));
  byId('filter').onchange = () => select(null);
  byId('refs').onchange = () => { byId('reference').style.display = byId('refs').checked?'':'none'; };
  byId('next').onclick=next; byId('keep').onclick=()=>decide('keep'); byId('skip').onclick=()=>decide('skip'); byId('undo').onclick=()=>decide(null);
  byId('fit').onclick=fit; byId('in').onclick=()=>zoom(.65); byId('out').onclick=()=>zoom(1.5);
  svg.addEventListener('wheel',e=>{ e.preventDefault(); const p=pointer(e); zoom(Math.exp(Math.max(-1,Math.min(1,e.deltaY*.003))),p.x,p.y); },{passive:false});
  svg.onpointerdown=e=>{ if (e.button!==0) return; moved=false; drag={p:pointer(e), key:e.target.dataset.key}; svg.setPointerCapture(e.pointerId); };
  svg.onpointermove=e=>{ if (!drag) return; const p=pointer(e); const dx=drag.p.x-p.x, dy=drag.p.y-p.y;
    if (!moved && Math.hypot(dx,dy)*svg.getScreenCTM().a<4) return;
    moved=true; frame.x+=dx;frame.y+=dy;view(); };
  svg.onpointerup=()=>{ if (drag && !moved && drag.key) select(features.find(f=>f.id===drag.key)); drag=null; };
  svg.onpointercancel=()=>{drag=null;};
  byId('export').onclick=()=>{
    const kept = features.filter(f=>decisions[f.id]==='keep').map(f=>({...f,properties:{...f.properties,status:'kept_for_review'}}));
    const url=URL.createObjectURL(new Blob([JSON.stringify({type:'FeatureCollection',features:kept})],{type:'application/geo+json'}));
    const a=document.createElement('a');a.href=url;a.download='kept-course-outlines.geojson';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  fit(); update();
}
openReview().catch(error=>{document.getElementById('totals').textContent=error.message;});
