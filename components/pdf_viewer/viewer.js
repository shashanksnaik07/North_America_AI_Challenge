/* Page navigation is local: scrolling never reruns the Python app. */
'use strict';
const viewport = document.getElementById('viewport');
const pagesRoot = document.getElementById('pages');
const pageInput = document.getElementById('page-number');
const buttons = Object.fromEntries(['first', 'previous', 'next', 'last'].map(id => [id, document.getElementById(id)]));
const svgNS = 'http://www.w3.org/2000/svg';
let args = {}, pageElements = [], currentPage = 0, contentId = null, command = null, drag = null, scrollFrame = null, editingPage = false;
let redlineElements = [];
const changeDialog = document.getElementById('change-dialog');
document.getElementById('close-change').onclick = () => changeDialog.close();

function send(type, extra = {}) { parent.postMessage({isStreamlitMessage: true, type, ...extra}, '*'); }
function emit(value) { send('streamlit:setComponentValue', {value: {...value, event: crypto.randomUUID()}, dataType: 'json'}); }
function frameHeight() { send('streamlit:setFrameHeight', {height: document.body.scrollHeight + 2}); }
function storageKey() { return 'iep-pdf-position:' + args.document_key; }
function readPosition() { try { return JSON.parse(sessionStorage.getItem(storageKey())) || null; } catch { return null; } }
function remember() {
  const element = pageElements[currentPage];
  if (!element) return;
  const position = {page: currentPage, fraction: (viewport.scrollTop - element.offsetTop) / element.offsetHeight, left: viewport.scrollLeft, command};
  try { sessionStorage.setItem(storageKey(), JSON.stringify(position)); } catch { /* Navigation also works without storage. */ }
}
function clampPage(page) { return Math.max(0, Math.min(pageElements.length - 1, Number.isFinite(page) ? Math.trunc(page) : currentPage)); }
function updateControls(announce = false) {
  if (!editingPage) pageInput.value = currentPage + 1;
  buttons.first.disabled = buttons.previous.disabled = currentPage === 0;
  buttons.last.disabled = buttons.next.disabled = currentPage === pageElements.length - 1;
  if (announce) document.getElementById('announcement').textContent = `Page ${currentPage + 1} of ${pageElements.length}`;
}
function goToPage(page, announce = true) {
  if (!pageElements.length) return;
  currentPage = clampPage(page);
  editingPage = false;
  viewport.scrollTop = Math.max(0, pageElements[currentPage].offsetTop - 12);
  pageInput.value = currentPage + 1;
  updateControls(announce); remember();
}
function followScroll() {
  scrollFrame = null;
  // The page crossing the top reading line wins; gaps belong to the next page.
  const readingLine = viewport.scrollTop + Math.min(100, viewport.clientHeight * .2);
  let index = pageElements.findIndex(el => el.offsetTop + el.offsetHeight > readingLine);
  if (viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 2) index = pageElements.length - 1;
  currentPage = clampPage(index < 0 ? pageElements.length - 1 : index);
  updateControls(); remember();
}
viewport.addEventListener('scroll', () => { if (!scrollFrame) scrollFrame = requestAnimationFrame(followScroll); }, {passive: true});
buttons.first.onclick = () => goToPage(0);
buttons.previous.onclick = () => goToPage(currentPage - 1);
buttons.next.onclick = () => goToPage(currentPage + 1);
buttons.last.onclick = () => goToPage(pageElements.length - 1);
function submitPage() {
  const value = pageInput.value.trim();
  goToPage(value && Number.isFinite(Number(value)) ? Number(value) - 1 : currentPage);
}
pageInput.addEventListener('change', submitPage);
pageInput.addEventListener('input', () => { editingPage = true; });
pageInput.addEventListener('blur', () => { editingPage = false; updateControls(); });
pageInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); submitPage(); }
  if (event.key === 'Escape') { editingPage = false; pageInput.value = currentPage + 1; pageInput.blur(); }
});
document.getElementById('viewer').addEventListener('keydown', event => {
  if (event.target === pageInput || event.ctrlKey || event.altKey || event.metaKey) return;
  const targets = {PageDown: currentPage + 1, PageUp: currentPage - 1, Home: 0, End: pageElements.length - 1};
  if (event.key in targets) { event.preventDefault(); goToPage(targets[event.key]); }
});

function rectangle(svg, bounds, stroke, fill, width = 1) {
  const [x, y, right, bottom] = bounds, rect = document.createElementNS(svgNS, 'rect');
  for (const [key, value] of Object.entries({x, y, width: right - x, height: bottom - y, stroke, fill, 'stroke-width': width, 'vector-effect': 'non-scaling-stroke'})) rect.setAttribute(key, value);
  svg.appendChild(rect); return rect;
}
function tokenText(element, tokens) {
  element.replaceChildren();
  for (const [index, token] of tokens.entries()) {
    if (index) element.appendChild(document.createTextNode(' '));
    const part = document.createElement(token.kind === 'delete' ? 'del' : token.kind === 'insert' ? 'ins' : 'span');
    part.textContent = token.text; // Record values must never become HTML.
    if (token.kind !== 'equal') part.title = token.kind === 'delete' ? 'Removed' : 'Added';
    element.appendChild(part);
  }
}
function expandChange(change) {
  document.getElementById('change-title').textContent = change.label;
  document.getElementById('change-location').textContent = `Page ${change.page + 1} · Full change in this field`;
  tokenText(document.getElementById('change-content'), change.tokens);
  const link = document.getElementById('continuation-link');
  link.hidden = !change.continuation_page;
  link.textContent = `Go to full field on continuation page ${change.continuation_page}`;
  link.onclick = () => { changeDialog.close(); goToPage(change.continuation_page - 1); };
  changeDialog.showModal();
}
function fitRedlines() {
  const marginPositions = new Map();
  for (const {box, text, button, connector, change, sheet, page} of [...redlineElements].sort((a, b) => a.change.page - b.change.page || a.change.rect[1] - b.change.rect[1])) {
    const scale = sheet.clientWidth / page.width;
    if (!scale) continue;
    let display = 'full';
    function fits(tokens) {
      tokenText(text, tokens);
      for (let size = 10; size >= 7; size -= .5) {
        text.style.fontSize = `${size * scale}px`;
        if (text.scrollHeight <= text.clientHeight + 1 && text.scrollWidth <= text.clientWidth + 1) return true;
      }
      return false;
    }
    if (!fits(change.tokens)) {
      display = 'changes-only';
      const changed = change.tokens.filter(token => token.kind !== 'equal');
      if (!fits(changed)) {
        display = 'excerpt';
        let fitted = false;
        for (let count = 5; count >= 1; count--) {
          const excerpt = changed.map(token => ({...token, text: token.text.split(/\s+/).slice(0, count).join(' ') + (token.text.split(/\s+/).length > count ? '…' : '')}));
          if (fits(excerpt)) { fitted = true; break; }
        }
        if (!fitted) { display = 'summary'; fits(changed.map(token => ({kind: token.kind, text: token.kind === 'delete' ? '−' : '+'}))); }
      }
    }
    box.dataset.display = display;
    button.textContent = display === 'full' ? '↗' : '…';
    button.classList.toggle('abridged', display !== 'full');
    button.title = display === 'full' ? 'Expand full change' : 'Preview shortened to fit this box. Expand to read the full change.';
    button.setAttribute('aria-label', `${display === 'full' ? 'Expand change' : 'Expand full change (shortened preview)'}: ${change.label}`);
    // Put controls in the right page margin, away from neighboring form labels.
    const marginTop = Math.min(sheet.clientHeight - 24, Math.max(change.rect[1] * scale, (marginPositions.get(sheet) ?? -28) + 28));
    marginPositions.set(sheet, marginTop);
    button.style.left = `${sheet.clientWidth - change.rect[0] * scale - 26}px`;
    button.style.top = `${marginTop - change.rect[1] * scale}px`;
    connector.style.width = `${Math.max(0, sheet.clientWidth - change.rect[2] * scale - 26)}px`;
  }
}
function paintRedlines() {
  redlineElements = [];
  for (const element of pageElements) element.querySelectorAll('.redline-box').forEach(box => box.remove());
  for (const change of args.redlines || []) {
    const page = args.pages[change.page], sheet = pageElements[change.page]?.querySelector('.sheet');
    if (!sheet) continue;
    const [x, y, right, bottom] = change.rect;
    const box = document.createElement('div'); box.className = 'redline-box'; box.setAttribute('aria-label', `Change: ${change.label}`);
    Object.assign(box.style, {left: `${x / page.width * 100}%`, top: `${y / page.height * 100}%`, width: `${(right - x) / page.width * 100}%`, height: `${(bottom - y) / page.height * 100}%`});
    const text = document.createElement('div'); text.className = 'redline-content';
    const connector = document.createElement('span'); connector.className = 'redline-connector'; connector.setAttribute('aria-hidden', 'true');
    const button = document.createElement('button'); button.type = 'button'; button.className = 'expand-change'; button.onclick = () => expandChange(change);
    box.append(text, connector, button); sheet.appendChild(box); redlineElements.push({box, text, button, connector, change, sheet, page});
  }
  fitRedlines();
}
function paintOverlays() {
  const highlighted = new Set(args.highlighted_fields || []);
  pageElements.forEach((element, index) => {
    const page = args.pages[index], sheet = element.querySelector('.sheet'), svg = sheet.querySelector('svg');
    sheet.dataset.mode = args.mode || 'read'; svg.replaceChildren();
    for (const field of page.fields || []) {
      if (highlighted.has(field.path)) rectangle(svg, field.rect, args.color === 'red' ? '#cc2020' : '#0d8c38', args.color === 'red' ? '#cc202021' : '#0d8c3821', 2);
      if (args.show_fields || field.path === args.active_field) rectangle(svg, field.rect, field.path === args.active_field ? '#2563eb' : '#3b82f677', 'none', field.path === args.active_field ? 3 : 1);
    }
    if (args.selection && args.selection.page === index && args.mode === 'map') rectangle(svg, args.selection.rect, '#15803d', '#16a34a22', 2);
  });
  paintRedlines();
}
function point(event, sheet, page) {
  const bounds = sheet.getBoundingClientRect();
  return [Math.max(0, Math.min(page.width, (event.clientX - bounds.left) * page.width / bounds.width)),
    Math.max(0, Math.min(page.height, (event.clientY - bounds.top) * page.height / bounds.height))];
}
function bindSheet(sheet, index) {
  sheet.addEventListener('pointerdown', event => {
    if (args.mode === 'read' || event.button !== 0) return;
    drag = {index, start: point(event, sheet, args.pages[index]), client: [event.clientX, event.clientY]};
    if (args.mode === 'map') { sheet.setPointerCapture(event.pointerId); event.preventDefault(); }
  });
  sheet.addEventListener('pointermove', event => {
    if (!drag || drag.index !== index || args.mode !== 'map') return;
    const end = point(event, sheet, args.pages[index]), start = drag.start;
    drag.rect = [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])];
    sheet.querySelector('[data-drag]')?.remove();
    rectangle(sheet.querySelector('svg'), drag.rect, '#15803d', '#16a34a22', 2).setAttribute('data-drag', 'true');
  });
  sheet.addEventListener('pointerup', event => {
    if (!drag || drag.index !== index) return;
    const gesture = drag; drag = null;
    const page = args.pages[index], end = point(event, sheet, page);
    const distance = Math.hypot(event.clientX - gesture.client[0], event.clientY - gesture.client[1]);
    remember();
    if (args.mode === 'map' && distance >= 5 && gesture.rect) {
      const [x, y, right, bottom] = gesture.rect;
      if (right - x >= 5 && bottom - y >= 5) emit({rect: gesture.rect, page: index});
    } else if (distance < 5) {
      const match = (page.fields || []).filter(f => end[0] >= f.rect[0] && end[0] <= f.rect[2] && end[1] >= f.rect[1] && end[1] <= f.rect[3])
        .sort((a, b) => (a.rect[2] - a.rect[0]) * (a.rect[3] - a.rect[1]) - (b.rect[2] - b.rect[0]) * (b.rect[3] - b.rect[1]))[0];
      if (match) emit({field: match.path, page: index});
    }
  });
  sheet.addEventListener('pointercancel', () => { drag = null; sheet.querySelector('[data-drag]')?.remove(); });
}
function rebuild() {
  pagesRoot.replaceChildren();
  pageElements = args.pages.map((page, index) => {
    const element = document.createElement('section'); element.className = 'pdf-page'; element.setAttribute('aria-label', `Page ${index + 1} of ${args.pages.length}`);
    const label = document.createElement('p'); label.className = 'page-label'; label.textContent = `Page ${index + 1} · ${(page.label || 'IEP').replace('Continuation / additional plan details', 'App-added continuation / additional plan details')}`;
    const sheet = document.createElement('div'); sheet.className = 'sheet'; sheet.style.aspectRatio = `${page.width} / ${page.height}`;
    const img = document.createElement('img'); img.alt = `IEP PDF page ${index + 1}. Field text is also available in Form view.`;
    img.loading = 'lazy'; img.decoding = 'async'; img.width = Math.round(page.width); img.height = Math.round(page.height); img.src = 'data:image/png;base64,' + page.image;
    const svg = document.createElementNS(svgNS, 'svg'); svg.setAttribute('viewBox', `0 0 ${page.width} ${page.height}`); svg.setAttribute('aria-hidden', 'true');
    sheet.append(img, svg); element.append(label, sheet); pagesRoot.appendChild(element); bindSheet(sheet, index); return element;
  });
  pageInput.max = args.pages.length; document.getElementById('page-total').textContent = `of ${args.pages.length}`;
}
function restore(position) {
  currentPage = clampPage(position?.page ?? args.initial_page ?? 0);
  const element = pageElements[currentPage];
  viewport.scrollTop = Math.max(0, element.offsetTop + (position?.fraction || 0) * element.offsetHeight);
  viewport.scrollLeft = position?.left || 0;
  updateControls();
}
window.addEventListener('message', event => {
  if (event.source !== parent || event.data.type !== 'streamlit:render') return;
  const next = event.data.args;
  if (!next.pages?.length) return;
  if (changeDialog.open) changeDialog.close();
  const switchedDocument = args.document_key !== next.document_key;
  if (contentId) remember();
  args = next;
  const saved = readPosition();
  if (!contentId || switchedDocument) command = saved?.command ?? null;
  const nextId = args.content_id + ':' + args.document_key;
  if (nextId !== contentId) { rebuild(); contentId = nextId; }
  pagesRoot.style.width = (args.zoom || 100) + '%';
  viewport.style.height = (args.viewport_height || 710) + 'px';
  document.getElementById('instructions').textContent = args.mode === 'map'
    ? 'Drag an area on any page, then save its field binding in Edit draft.'
    : args.mode === 'select' ? 'Click a highlighted field to edit. Scroll or use Page Up / Page Down to move through pages.'
    : 'Scroll to read. Use Page Up / Page Down or enter a page number to jump.';
  paintOverlays();
  if (args.navigation && args.navigation.token !== command) {
    command = args.navigation.token; goToPage(args.navigation.page);
  } else restore(saved);
  frameHeight();
});
let resizeFrame;
new ResizeObserver(() => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => { if (pageElements.length) restore(readPosition()); fitRedlines(); frameHeight(); });
}).observe(viewport);
send('streamlit:componentReady', {apiVersion: 1}); frameHeight();
