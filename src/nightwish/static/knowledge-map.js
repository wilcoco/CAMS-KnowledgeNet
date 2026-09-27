/* Joint Q&A maps: textContent/SVG nodes only; model output is never HTML. */
let knowledgeMode = 'auto', knowledgeNodeId = null, selectedMapTarget = null;
const participationNames={question:'후속 질문',evidence:'근거',condition:'적용 조건',counterexample:'다른 경험·반례'};
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
const selectedReferences = new Map();
let referenceQuery = '', referenceSpace = '';
function syncReferenceSelection(){
  const query = document.getElementById('search').value.trim();
  if(query !== referenceQuery || space() !== referenceSpace) selectedReferences.clear();
  referenceQuery = query; referenceSpace = space(); renderReferenceSelection();
}
function renderReferenceSelection(){
  const box = document.getElementById('selected-sources'); if(!box) return;
  box.replaceChildren(mapEl('p',selectedReferences.size
    ? `다음 답변에 참고할 내부 지식 ${selectedReferences.size}건`
    : '선택한 내부 자료 없음 · 기존 문서를 자동으로 넣지 않습니다.','prov'));
  selectedReferences.forEach((title,id)=>box.append(mapButton(title+' ×',()=>{
    selectedReferences.delete(id);renderReferenceSelection();
  })));
  document.querySelectorAll('.reference-check').forEach(c=>{c.checked=selectedReferences.has(c.dataset.sourceId);});
}
function referencePicker(n){
  const label=mapEl('label',undefined,'reference-picker'),input=mapEl('input');
  input.type='checkbox';input.className='reference-check';input.dataset.sourceId=n.id;
  input.checked=selectedReferences.has(n.id);
  label.onclick=e=>e.stopPropagation();
  input.onchange=()=>{
    if(input.checked){
      if(selectedReferences.size>=5){input.checked=false;toast('참고 자료는 최대 5건까지 선택할 수 있습니다.');return;}
      selectedReferences.set(n.id,n.title);
    } else selectedReferences.delete(n.id);
    renderReferenceSelection();
  };
  label.append(input,document.createTextNode(' 답변에 참고'));return label;
}
function updateResearchScope(){
  const input=document.getElementById('research-web'), publicSpace=space()==='public';
  input.disabled=!publicSpace;
  if(!publicSpace) input.checked=false;
  document.getElementById('research-hint').textContent=publicSpace
    ? '질문을 웹 검색에 사용합니다. 선택한 내부 자료와 아래 배경은 검색어로 보내지 않습니다.'
    : '그룹 질문은 외부 웹 검색을 사용하지 않습니다. 선택한 지식과 대화 맥락으로 답변합니다.';
}
function mapContributions(n,kind,id){
  const matches=[];
  function visit(rows){(rows||[]).forEach(c=>{
    const t=c.knowledge_target;
    if(t && t.node_id===n.id && t.revision===n.knowledge_revision && t.kind===kind && t.id===id) matches.push(c);
    visit(c.replies);
  });}
  visit(n.thread);return matches;
}
function beginMapContribution(n,item,kind,id,purpose){
  const pane=[...document.querySelectorAll('.pane')].find(p=>p.dataset.nodeId===n.id);
  if(!pane || !n.knowledge_revision)return;
  showReply(n.id,purpose==='question'?'followup':'comment',pane);
  const box=[...pane.querySelectorAll('.reply')].find(r=>r.dataset.rid===n.id);
  box._mapTarget={kind,id,revision:n.knowledge_revision,purpose};
  const label=kind==='concept' ? item.label : relationLabel(n.knowledge,item);
  box.prepend(mapEl('div',`${participationNames[purpose]} · ${label}`,'map-target-draft'));
  const area=box.querySelector('textarea');
  const prompts={question:`“${label}”의 적용 조건과 예외는 무엇인가요?`,
    evidence:'이 내용을 뒷받침하는 자료나 직접 관찰한 사실을 적어 주세요. 출처와 관찰 시점도 함께 남기면 도움이 됩니다.',
    condition:'어떤 상황에서 적용되나요? 적용하기 어려운 조건도 함께 적어 주세요.',
    counterexample:'어떤 상황에서 다른 결과를 경험했나요? 직접 경험한 내용과 그때의 조건을 적어 주세요.'};
  if(purpose==='question') area.value=prompts.question;
  else area.placeholder=prompts[purpose];
  box.querySelector('[data-go]').textContent=purpose==='question'?'이 부분을 AI에게 묻기':'선택한 부분에 남기기';
  setMobileSection('answer');area.focus();box.scrollIntoView({block:'center',behavior:'smooth'});
}
function relationLabel(k,r){
  return `${k.concepts.find(c=>c.id===r.source)?.label||r.source} → ${relationNames[r.type]} → ${k.concepts.find(c=>c.id===r.target)?.label||r.target}`;
}
function targetBadge(t){
  return t ? `<div class="map-target-badge">${esc(participationNames[t.purpose]||'참여')} · ${esc(t.label)}</div>` : '';
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
  const needle=quote.replace(/\[\[([^\]]+)\]\]/g,'$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/[*`]/g,'');
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
  if (!n || !n.knowledge || !n.knowledge.version) return;
  const k=n.knowledge;
  if(k.background){
    const details=mapEl('details',undefined,'map-source');
    details.append(mapEl('summary','이 답변에 전달한 배경·목표'),mapEl('p',k.background));box.append(details);
  }
  if(k.research_status){
    box.append(mapEl('h2','웹 원문 확인','sec'));
    const status={searched:'웹 검색에서 찾은 출처입니다. 원문의 설명과 AI의 적용 제안을 구별해 읽어 주세요.',
      off:'이 답변에서는 웹 검색을 사용하지 않았습니다.',
      no_evidence:'웹 검색에서 인용 가능한 근거를 확보하지 못했습니다. 답변을 웹으로 검증한 것은 아닙니다.',
      unavailable:'웹 검색을 완료하지 못했습니다. 아래 답변은 웹 검증 없이 작성되었습니다.'};
    box.append(mapEl('p',status[k.research_status]||'웹 확인 상태를 알 수 없습니다.','prov'));
    (k.web_sources||[]).forEach(s=>{
      let url;try{url=new URL(s.url);}catch{return;}
      if(!['https:','http:'].includes(url.protocol))return;
      const item=mapEl('div',undefined,'map-source web-source'),a=mapEl('a',`[${s.id}] ${s.title}`);
      a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';item.append(a);box.append(item);
    });
  }
  if (!sources.length){
    // Publishing can hide private excerpts; absence is not proof of non-use.
    box.append(mapEl('p',n.knowledge.source_mode==='none'
      ? '이 답변은 별도의 내부 자료를 참고하지 않았습니다.'
      : '이 답변에서 공개된 참고 자료가 없습니다.','prov'));return;
  }
  const mode = n.knowledge.source_mode || (n.parent ? 'conversation' : 'legacy_auto');
  box.append(mapEl('h2',mode==='user_selected' ? '선택해서 참고한 내부 지식' : mode==='conversation' ? '맥락으로 참고한 이전 대화' : '서비스가 자동 검색으로 참고한 자료','sec'),
    mapEl('p',mode==='legacy_auto'
      ? '이전 버전이 자동으로 전달한 내부 문서입니다. 사용자가 첨부한 자료가 아닙니다.'
      : '생성 당시의 발췌입니다. 자료의 서술도 직접 확인해 주세요.','prov'));
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
  if (knowledgeNodeId !== (n && n.id)) { knowledgeNodeId = n && n.id; knowledgeMode = 'auto'; selectedMapTarget=null; clearMapHighlights(); }
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
  panel.append(meaning,mapEl('p','개념·관계를 선택해 근거와 조건을 확인하고, 질문이나 경험을 보태세요.','prov'));
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
    group.setAttribute('role','button');group.setAttribute('tabindex','0');
    group.setAttribute('aria-label',relationLabel(k,r));
    group.onclick=()=>showEvidence(r,relationLabel(k,r));
    group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();group.onclick();}};
    group.append(svgEl('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'edge-hit'}));
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
    const targetKind=item.id?'concept':'relation',targetId=item.id||String(k.relations.indexOf(item));
    selectedMapTarget={kind:targetKind,id:targetId,revision:n.knowledge_revision};
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
      detail.append(mapButton('이 개념 검색',()=>{document.getElementById('search').value=item.label;showTab('search');doSearch();setMobileSection('search');}));
    }
    const actions=mapEl('div',undefined,'map-participate');
    [['question','이어 묻기'],['evidence','근거 보태기'],['condition','조건 보태기'],['counterexample','다른 경험·반례']].forEach(([purpose,title])=>{
      const b=mapButton(title,()=>beginMapContribution(n,item,targetKind,targetId,purpose));
      b.dataset.purpose=purpose;actions.append(b);
    });detail.append(actions);
    const contributions=mapContributions(n,targetKind,targetId);
    detail.append(mapEl('h4',`이 부분에 쌓인 참여 ${contributions.length}건`));
    detail.append(mapEl('p','사람이 남긴 내용도 검토 대상입니다. 참여 수가 사실 확정을 뜻하지는 않습니다.','prov'));
    if(!contributions.length)detail.append(mapEl('p','아직 경험이나 근거가 없습니다. 첫 질문이나 의견을 남겨 주세요.','prov'));
    contributions.forEach(c=>{
      const card=mapEl('div',undefined,'map-contribution');card.dataset.contributionId=c.id;
      card.append(mapEl('strong',`${participationNames[c.knowledge_target.purpose]} · ${c.author}`),
        mapEl('p',c.title||c.body));
      if(c.title && c.replies?.some(r=>r.frozen))card.append(mapEl('p','AI 후속 답변 있음','prov'));
      card.append(mapButton('대화에서 보기',()=>{
        setMobileSection('answer');
        const row=[...document.querySelectorAll('.pane .c')].find(el=>el.dataset.nodeId===c.id);
        if(row){row.scrollIntoView({block:'center',behavior:'smooth'});row.classList.add('map-contribution-focus');setTimeout(()=>row.classList.remove('map-contribution-focus'),2500);}
      }));detail.append(card);
    });
  }
  k.concepts.forEach(c=>{
    const p=pos.get(c.id),g=svgEl('g',{class:'semantic-node '+c.kind,role:'button',tabindex:'0','aria-label':c.label+' · '+conceptKinds[c.kind],'aria-pressed':'false'});
    g.append(svgEl('circle',{cx:p.x,cy:p.y,r:19}),svgEl('text',{x:p.x,y:p.y+4,'text-anchor':'middle'},conceptKinds[c.kind]),svgEl('title',{},c.label));
    const label=svgEl('text',{x:p.x,y:p.y+33,'text-anchor':'middle',class:'concept-label'});
    const chars=Array.from(c.label);label.textContent=chars.slice(0,11).join('')+(chars.length>11?'…':'');g.append(label);
    const count=mapContributions(n,'concept',c.id).length;
    if(count)g.append(svgEl('text',{x:p.x+20,y:p.y-18,class:'participation-count'},'+'+count));
    const select=()=>showEvidence(c,c.label);g.onclick=select;
    g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
    conceptButtons.push([c.id,g]);svg.append(g);
  });
  panel.append(svg);
  const labels=mapEl('div',undefined,'map-concepts');
  k.concepts.forEach(c=>{const count=mapContributions(n,'concept',c.id).length;
    const b=mapButton(c.label+(count?` · 참여 ${count}`:''),()=>showEvidence(c,c.label));conceptButtons.push([c.id,b]);labels.append(b);});
  panel.append(labels,detail);
  detail.append(mapEl('p','선택한 개념의 원문과 관계가 여기에 나타납니다.','prov'));
  if(k.relations.length){
    panel.append(mapEl('h4','관계 · 방향과 근거'));
    k.relations.forEach((r,i)=>{
      const a=k.concepts.find(c=>c.id===r.source),b=k.concepts.find(c=>c.id===r.target);
      if(a&&b){const label=a.label+' → '+relationNames[r.type]+' → '+b.label;
        const count=mapContributions(n,'relation',String(i)).length;
        const btn=mapButton(label+(count?` · 참여 ${count}`:''),()=>showEvidence(r,label));btn.classList.add('map-relation');panel.append(btn);}
    });
  }
  if(selectedMapTarget?.revision===n.knowledge_revision){
    const item=selectedMapTarget.kind==='concept' ? k.concepts.find(c=>c.id===selectedMapTarget.id) : k.relations[Number(selectedMapTarget.id)];
    if(item)showEvidence(item,item.id?item.label:relationLabel(k,item));
  }
  return true;
}
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('search').addEventListener('input',syncReferenceSelection);
  renderReferenceSelection();
  updateResearchScope();
  document.querySelectorAll('[data-map-mode]').forEach(b=>b.onclick=()=>{knowledgeMode=b.dataset.mapMode;renderEgo(EGO.data);});
  document.querySelectorAll('[data-section-tab]').forEach(b=>b.onclick=()=>setMobileSection(b.dataset.sectionTab));
  setMobileSection('search');
});
