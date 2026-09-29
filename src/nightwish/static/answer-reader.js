/* Read existing answers in smaller pieces. Original rendered nodes are moved,
   never rewritten: citations, wiki links and source quotes stay attached. */
(() => {
  let readerSequence = 0;
  const headingLevel = element => /^H[1-6]$/.test(element?.tagName || '')
    ? Number(element.tagName.slice(1)) : 0;
  const make = (tag, className, text) => {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };

  function conceptButtons(pane, node) {
    const knowledge = node.knowledge;
    if (!knowledge || !(knowledge.concepts || []).length) return null;
    const degree = new Map();
    (knowledge.relations || []).forEach(relation => {
      degree.set(relation.source, (degree.get(relation.source) || 0) + 1);
      degree.set(relation.target, (degree.get(relation.target) || 0) + 1);
    });
    const concepts = [...knowledge.concepts].sort((a, b) =>
      (degree.get(b.id) || 0) - (degree.get(a.id) || 0)).slice(0, 5);
    const group = make('div', 'answer-concept-nav');
    group.append(make('span', 'answer-concept-label', '개념으로 보기'));
    const buttons = make('div', 'answer-concept-buttons');
    concepts.forEach(concept => {
      const button = make('button', 'sec answer-concept-button', concept.label);
      button.type = 'button';
      button.dataset.conceptId = concept.id;
      button.setAttribute('aria-label', `${concept.label} 개념과 연결 보기`);
      button.addEventListener('click', () => {
        if (typeof window.focusPane === 'function') window.focusPane(pane);
        const mode = document.querySelector('[data-map-mode="semantic"]');
        if (mode?.getAttribute('aria-pressed') !== 'true') mode?.click();
        const tab = document.querySelector('[data-rtab="map"]');
        if (tab && !tab.classList.contains('active')) tab.click();
        if (typeof window.focusKnowledgeConcept === 'function') {
          window.focusKnowledgeConcept(concept.id, node.id);
        }
      });
      buttons.append(button);
    });
    group.append(buttons);
    return group;
  }

  function sectionsFrom(blocks) {
    const headings = blocks.filter(block => headingLevel(block));
    // A single document title belongs to the opening; its subheadings divide
    // the answer. Nested headings remain inside their parent section.
    const levels = headings.map(headingLevel);
    let level = Math.min(...levels);
    if (levels.filter(value => value === level).length === 1 && levels.some(value => value > level)) {
      level = Math.min(...levels.filter(value => value > level));
    }
    const starts = blocks.filter(block => headingLevel(block) === level);
    if (starts.length >= 2) {
      const opening = [];
      const sections = [];
      let current;
      blocks.forEach(block => {
        if (headingLevel(block) === level) {
          current = {heading: block, blocks: []};
          sections.push(current);
        } else if (current) current.blocks.push(block);
        else opening.push(block);
      });
      return {opening, sections};
    }
    // Answers without headings can still be read a few original paragraphs
    // at a time. Generic labels do not claim to summarize their meaning.
    const opening = [];
    let rest = [...blocks];
    while (rest.length && (headingLevel(rest[0])
      || (rest[0].nodeType === Node.TEXT_NODE && !rest[0].textContent.trim()))) {
      opening.push(rest.shift());
    }
    if (rest[0]?.tagName === 'P' && rest[0].textContent.length <= 650) opening.push(rest.shift());
    const sections = [];
    let current = {heading: null, blocks: []};
    let length = 0;
    rest.forEach(block => {
      if (length >= 650 && sections.length < 5) {
        sections.push(current);
        current = {heading: null, blocks: []};
        length = 0;
      }
      current.blocks.push(block);
      length += block.textContent.length;
    });
    if (current.blocks.length) sections.push(current);
    return {opening, sections};
  }

  window.mountAnswerReader = (pane, node) => {
    const answer = pane.querySelector('.answer.markdown-answer');
    if (!answer || answer.dataset.readerMounted || node.is_query || node.is_stub
      || (!node.frozen && !node.model)) return;
    answer.dataset.readerMounted = 'true';
    const concepts = conceptButtons(pane, node);
    const blocks = Array.from(answer.childNodes);
    const meaningful = blocks.filter(block => block.nodeType === Node.ELEMENT_NODE);
    const long = answer.textContent.trim().length > 1200;
    if (!long) {
      if (concepts) answer.after(concepts);
      return;
    }
    const {opening, sections} = sectionsFrom(blocks);
    if (!sections.length || meaningful.length < 2) {
      if (concepts) answer.after(concepts);
      return;
    }
    const identifier = `answer-reader-${++readerSequence}`;
    answer.id = identifier;
    answer.classList.add('answer-reader');
    const toolbar = make('div', 'answer-reader-toolbar');
    const description = make('div', 'answer-reader-description');
    description.append(make('strong', '', opening.some(block => block.textContent.trim()) ? '먼저 읽기' : '나눠 읽기'));
    description.append(make('span', '', `${sections.length}개 부분 · 제목을 누르면 내용이 열려요`));
    const toggle = make('button', 'sec answer-reader-toggle', '전체 펼치기');
    toggle.type = 'button';
    toggle.setAttribute('aria-controls', identifier);
    toggle.setAttribute('aria-expanded', 'false');
    toolbar.append(description, toggle);
    answer.before(toolbar);
    if (concepts) answer.before(concepts);
    const openingBox = make('div', 'answer-opening');
    if (opening.some(block => block.textContent.trim())) {
      openingBox.setAttribute('aria-label', '답변의 도입');
      openingBox.append(...opening);
      answer.append(openingBox);
    }
    const sectionElements = [];
    sections.forEach((section, index) => {
      const details = make('details', 'answer-section');
      details.id = `${identifier}-section-${index + 1}`;
      const summary = make('summary', 'answer-section-heading');
      if (!section.heading || !/^\s*\d+[.)]/.test(section.heading.textContent)) {
        summary.dataset.index = String(index + 1).padStart(2, '0');
      }
      if (section.heading) summary.append(section.heading);
      else {
        const label = sections.length === 1 ? '답변 이어 읽기' : `이어서 읽기 ${index + 1}`;
        const generic = make('span', 'answer-section-generic');
        generic.dataset.label = label;
        summary.setAttribute('aria-label', label);
        summary.append(generic);
      }
      const content = make('div', 'answer-section-content');
      content.append(...section.blocks);
      details.append(summary, content);
      answer.append(details);
      sectionElements.push(details);
    });
    const sync = () => {
      const allOpen = sectionElements.every(section => section.open);
      toggle.textContent = allOpen ? '전체 접기' : '전체 펼치기';
      toggle.setAttribute('aria-expanded', String(allOpen));
    };
    sectionElements.forEach(section => section.addEventListener('toggle', sync));
    toggle.addEventListener('click', () => {
      const expand = !sectionElements.every(section => section.open);
      sectionElements.forEach(section => { section.open = expand; });
      sync();
    });
  };

  // Call before scrolling to a graph's verbatim quote: the quote may live in a
  // collapsed section. Only its ancestors are opened, preserving reading focus.
  window.revealAnswerEvidence = element => {
    let current = element?.nodeType === Node.TEXT_NODE ? element.parentElement : element;
    while (current) {
      if (current.tagName === 'DETAILS') current.open = true;
      current = current.parentElement;
    }
  };
})();
