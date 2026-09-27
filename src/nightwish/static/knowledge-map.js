/* Joint Q&A maps: textContent/SVG nodes only; model output is never HTML. */
let knowledgeMode = 'auto', knowledgeNodeId = null;
const relationNames = {is_a:'일종이다',part_of:'일부이다',requires:'필요하다',
  influences:'영향을 준다',contradicts:'상충한다',related_to:'관련된다'};
const conceptKinds = {concept:'개념',actor:'주체',condition:'조건',outcome:'결과'};
const originNames = {question:'질문에 담긴 표현 · 사실 여부 미확인',
  answer:'AI 답변의 제안 · 사람의 검토 전',source:'참고 자료의 서술 · 사실 여부는 별도 검토'};
function mapEl(tag, text, cls){
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function mapButton(text, action){
  const el = mapEl('button', text, 'sec'); el.type = 'button'; el.onclick = action; return el;
}
function setMobileSection(name){
  document.body.dataset.section = name;
  document.querySelectorAll('[data-section-tab]').forEach(b=>{
    const active = b.dataset.sectionTab === name;
    b.classList.toggle('active', active); b.setAttribute('aria-pressed', String(active));
  });
}
function clearMapHighlights(){
  document.querySelectorAll('mark.map-match').forEach(m=>m.replaceWith(document.createTextNode(m.textContent)));
  document.querySelectorAll('.map-source.selected').forEach(s=>s.classList.remove('selected'));
}
function highlightMapQuote(n, quote, origin){
  clearMapHighlights();
  const pane = [...document.querySelectorAll('.pane')].find(p=>p.dataset.nodeId === n.id);
  const root = pane && pane.querySelector(origin === 'question' ? '.node-head h3' : '.answer');
  if (!root || !quote) return;
  root.normalize();
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts = []; while(walk.nextNode()) texts.push(walk.currentNode);
  const needle=quote.replace(/\[\[([^\]]+)\]\]/g,'$1');
  const start=texts.map(t=>t.textContent).join('').indexOf(needle);
  if(start<0) return;
  let offset=0;
  for (const t of texts){
    const length=t.textContent.length,from=Math.max(0,start-offset),to=Math.min(length,start+needle.length-offset);
    if(to>from){
      const tail=t.splitText(from);tail.splitText(to-from);
      const mark=mapEl('mark',tail.textContent,'map-match');tail.replaceWith(mark);
    }
    offset+=length;
  }
}
function renderMapSources(n){
  const box = document.getElementById('map-sources'); if (!box) return;
  box.replaceChildren();
  const sources = n && n.knowledge && n.knowledge.sources || [];
  if (!sources.length) return;
  box.append(mapEl('h2','이 답변에 제공한 참고 자료','sec'),
    mapEl('p','생성 당시의 발췌입니다. 자료의 서술도 직접 확인해 주세요.','prov'));
  sources.forEach(s=>{
    const item = mapEl('div',undefined,'map-source'); item.dataset.sourceId = s.id;
    item.append(mapButton(s.title || '이전 대화',()=>{openNode(s.id);setMobileSection('answer');}));
    const details = mapEl('details'); details.append(mapEl('summary',s.model ? 'AI 자료 · 당시 발췌 보기' : '작성자의 자료 · 당시 발췌 보기'));
    details.append(mapEl('p',s.excerpt)); item.append(details); box.append(item);
  });
}
function renderKnowledge(n){
  const panel = document.getElementById('knowledge-map');
  if (!panel) return false;
  if (knowledgeNodeId !== (n && n.id)) { knowledgeNodeId = n && n.id; knowledgeMode = 'auto'; clearMapHighlights(); }
  const k = n && n.knowledge, hasMap = k && k.version === 1;
  const semantic = knowledgeMode === 'semantic' || (knowledgeMode === 'auto' && hasMap);
  document.getElementById('document-map').hidden = !!semantic;
  panel.hidden = !semantic;
  document.querySelectorAll('[data-map-mode]').forEach(b=>{
    const active = (b.dataset.mapMode === 'semantic') === !!semantic;
    b.classList.toggle('active',active); b.setAttribute('aria-pressed',String(active));
  });
  renderMapSources(n);
  if (!semantic) return false;
  panel.replaceChildren();
  if (!hasMap){ panel.append(mapEl('p','이 답에는 함께 생성된 개념 지도가 없습니다. 새 질문이나 후속 질문을 하면 답변과 지도가 함께 남습니다.','prov')); return true; }
  panel.append(mapEl('div','AI가 제안한 개념·관계','map-kicker'),mapEl('h3',k.question.intent));
  const meaning = mapEl('div',undefined,'map-meaning');
  if(k.question.conditions.length) meaning.append(mapEl('p','질문의 조건 · '+k.question.conditions.join(' / ')));
  if(k.question.unknowns.length) meaning.append(mapEl('p','확인할 점 · '+k.question.unknowns.join(' / ')));
  panel.append(meaning,mapEl('p','개념이나 관계를 누르면 원문 구절을 확인할 수 있습니다.','prov'));
  if(k.notice) panel.append(mapEl('p',k.notice,'map-notice'));
  if(!k.concepts.length){
    panel.append(mapEl('p','이 답에서는 근거가 확인된 개념을 만들지 못했습니다. 답변을 읽고 보강하거나 후속 질문으로 구체화해 주세요.','prov'));
    return true;
  }
  const NS = 'http://www.w3.org/2000/svg';
  function svgEl(tag, attrs, text){
    const e = document.createElementNS(NS,tag);
    Object.entries(attrs||{}).forEach(([a,v])=>e.setAttribute(a,v));
    if(text !== undefined) e.textContent = text; return e;
  }
  const svg = svgEl('svg',{viewBox:'0 0 320 350',role:'group','aria-label':'질문과 답변의 개념 관계 지도',class:'semantic-svg'});
  const pos = new Map();
  k.concepts.forEach((c,i)=>{const a = -Math.PI/2 + i*2*Math.PI/k.concepts.length;pos.set(c.id,{x:160+111*Math.cos(a),y:173+122*Math.sin(a)});});
  const edges = [];
  k.relations.forEach(r=>{
    const a=pos.get(r.source),b=pos.get(r.target); if(!a||!b) return;
    const length=Math.hypot(b.x-a.x,b.y-a.y),dx=(b.x-a.x)/length,dy=(b.y-a.y)/length;
    const group=svgEl('g',{'data-from':r.source,'data-to':r.target,class:'semantic-edge'});
    group.append(svgEl('line',{x1:a.x+dx*20,y1:a.y+dy*20,x2:b.x-dx*24,y2:b.y-dy*24}));
    const x=b.x-dx*24,y=b.y-dy*24;
    group.append(svgEl('path',{d:`M ${x-dx*7-dy*4} ${y-dy*7+dx*4} L ${x} ${y} L ${x-dx*7+dy*4} ${y-dy*7-dx*4}`}));
    group.append(svgEl('title',{},relationNames[r.type]));svg.append(group);edges.push(group);
  });
  const center=svgEl('g',{class:'semantic-center'});
  center.append(svgEl('circle',{cx:160,cy:173,r:29}),svgEl('text',{x:160,y:170,'text-anchor':'middle'},'질문'),svgEl('text',{x:160,y:187,'text-anchor':'middle'},'↔ 답변'));
  svg.append(center);
  const detail=mapEl('div',undefined,'map-detail');detail.setAttribute('aria-live','polite');
  const conceptButtons=[];
  function showEvidence(item,label){
    highlightMapQuote(n,item.quote,item.origin);
    edges.forEach(e=>e.classList.toggle('selected',item.id ? e.dataset.from===item.id||e.dataset.to===item.id : e.dataset.from===item.source&&e.dataset.to===item.target));
    conceptButtons.forEach(([id,el])=>el.setAttribute('aria-pressed',String(id===item.id)));
    detail.replaceChildren(mapEl('strong',label),mapEl('p',originNames[item.origin],'prov'),mapEl('blockquote',item.quote));
    if(item.origin==='source'){
      const s=(k.sources||[]).find(s=>s.id===item.source_id);
      if(s) detail.append(mapEl('p','참고 자료: '+(s.title||'이전 대화')));
      document.querySelectorAll('.map-source').forEach(el=>{
        if(el.dataset.sourceId===item.source_id){el.classList.add('selected');el.querySelector('details').open=true;}
      });
    }
    if(item.id){
      detail.append(mapButton('이 개념 검색',()=>{document.getElementById('search').value=item.label;showTab('search');doSearch();setMobileSection('search');}),
        mapButton('이어 묻기',()=>{
          const pane=[...document.querySelectorAll('.pane')].find(p=>p.dataset.nodeId===n.id);
          if(!pane) return;
          const btn=pane.querySelector('.actbar.main [data-act="followup"]'); if(btn) btn.click();
          const area=[...pane.querySelectorAll('.reply')].find(r=>r.dataset.rid===n.id)?.querySelector('textarea');
          if(area){area.value=item.label+'에 대해 더 알고 싶습니다.';setMobileSection('answer');area.focus();}
        }));
    }
    detail.append(mapEl('p','경험이나 다른 의견은 가운데 답변의 ‘보강’ 또는 ‘정정/다른 답’으로 남길 수 있습니다.','prov'));
  }
  k.concepts.forEach(c=>{
    const p=pos.get(c.id),g=svgEl('g',{class:'semantic-node '+c.kind,role:'button',tabindex:'0','aria-label':c.label+' · '+conceptKinds[c.kind],'aria-pressed':'false'});
    g.append(svgEl('circle',{cx:p.x,cy:p.y,r:19}),svgEl('text',{x:p.x,y:p.y+4,'text-anchor':'middle'},conceptKinds[c.kind]),svgEl('title',{},c.label));
    const label=svgEl('text',{x:p.x,y:p.y+33,'text-anchor':'middle',class:'concept-label'});
    const chars=Array.from(c.label);label.textContent=chars.slice(0,11).join('')+(chars.length>11?'…':'');g.append(label);
    const select=()=>showEvidence(c,c.label);g.onclick=select;
    g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
    conceptButtons.push([c.id,g]);svg.append(g);
  });
  panel.append(svg);
  const labels=mapEl('div',undefined,'map-concepts');
  k.concepts.forEach(c=>{const b=mapButton(c.label,()=>showEvidence(c,c.label));conceptButtons.push([c.id,b]);labels.append(b);});
  panel.append(labels,detail);
  detail.append(mapEl('p','선택한 개념의 원문과 관계가 여기에 나타납니다.','prov'));
  if(k.relations.length){
    panel.append(mapEl('h4','관계 · 방향과 근거'));
    k.relations.forEach(r=>{
      const a=k.concepts.find(c=>c.id===r.source),b=k.concepts.find(c=>c.id===r.target);
      if(a&&b){const label=a.label+' → '+relationNames[r.type]+' → '+b.label;
        const btn=mapButton(label,()=>showEvidence(r,label));btn.classList.add('map-relation');panel.append(btn);}
    });
  }
  return true;
}
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-map-mode]').forEach(b=>b.onclick=()=>{knowledgeMode=b.dataset.mapMode;renderEgo(EGO.data);});
  document.querySelectorAll('[data-section-tab]').forEach(b=>b.onclick=()=>setMobileSection(b.dataset.sectionTab));
  setMobileSection('search');
});
