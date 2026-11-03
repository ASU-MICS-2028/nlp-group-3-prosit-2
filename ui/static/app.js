// Prosit Builder UI. Plain JS, no build step. Talks to ui/server.py.

// ---------- icons (lucide-style, 24x24 stroke) ----------
const ICONS = {
  logo: '<svg viewBox="0 0 48 48"><rect width="48" height="48" rx="13" fill="currentColor"/><path d="M17 36V13h8.5a6.5 6.5 0 0 1 0 13H17" fill="none" stroke="var(--logo-ink, #fff)" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="33" cy="34" r="3.4" fill="var(--logo-ink, #fff)"/></svg>',
  network: '<rect x="9" y="2" width="6" height="6" rx="1.5"/><rect x="2" y="16" width="6" height="6" rx="1.5"/><rect x="16" y="16" width="6" height="6" rx="1.5"/><path d="M12 8v4M5 16v-2a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2"/>',
  home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
  folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  play: '<path d="M6 3l14 9-14 9V3z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  panel: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  arrowUp: '<path d="m5 12 7-7 7 7M12 19V5"/>',
  code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" fill="currentColor"/>',
  sparkle: '<path d="M12 2c.8 5.7 4.3 9.2 10 10-5.7.8-9.2 4.3-10 10-.8-5.7-4.3-9.2-10-10 5.7-.8 9.2-4.3 10-10z" fill="currentColor" stroke="none"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  file: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><path d="M14 2v6h6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
  external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7l10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  send: '<path d="m22 2-7 20-4-9-9-4 20-7z"/>',
  flask: '<path d="M10 2v7.31M14 9.3V2M8.5 2h7"/><path d="M14 9.3a6.5 6.5 0 1 1-4 0"/><path d="M5.52 16h12.96"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
};
const icon = (name, cls = '') => {
  const body = ICONS[name] || '';
  const svg = body.startsWith('<svg') ? body
    : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
  return `<i class="${cls}">${svg}</i>`;
};
function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach(el => {
    const n = el.dataset.icon; el.removeAttribute('data-icon');
    el.innerHTML = icon(n).replace(/^<i class="">|<\/i>$/g, '');
  });
}

// ---------- helpers ----------
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const DESKTOP = new URLSearchParams(location.search).has('desktop');

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.body !== undefined || opts.method === 'POST' ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : (opts.method === 'POST' ? '{}' : undefined),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 3500);
}

// light markdown for assistant text: **bold**, `code`, "- " bullets, newlines
function md(text) {
  const lines = esc(text).split('\n');
  let html = '', inList = false;
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
    if (/^\s*[-•*]\s+/.test(line)) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${line.replace(/^\s*[-•*]\s+/, '')}</li>`;
    } else {
      if (inList) { html += '</ul>'; inList = false; }
      html += line ? `${line}<br>` : '<br>';
    }
  }
  if (inList) html += '</ul>';
  return html.replace(/(<br>)+$/, '');
}

// ---------- syntax highlighting ----------
const PY_RE = /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|[rbfu]{0,2}"(?:\\.|[^"\\\n])*"|[rbfu]{0,2}'(?:\\.|[^'\\\n])*')|(@[\w.]+)|\b(\d+(?:\.\d+)?)\b|\b(def|class|return|if|elif|else|for|while|in|not|and|or|is|import|from|as|with|try|except|finally|raise|pass|break|continue|lambda|yield|async|await|global|nonlocal|del|assert)\b|\b(True|False|None|self)\b|\b(int|str|float|bool|dict|list|set|tuple|len|range|print|isinstance|super|Optional|Exception)\b|([A-Za-z_]\w*)(?=\s*\()/g;
const PY_CLS = [null, 'com', 'str', 'dec', 'num', 'kw', 'const', 'builtin', 'fn'];
const JSON_RE = /("(?:\\.|[^"\\])*")(\s*:)?|\b(-?\d+(?:\.\d+)?)\b|\b(true|false|null)\b/g;

function tokenize(text, lang) {
  const out = []; let last = 0, m;
  const re = lang === 'python' ? PY_RE : lang === 'json' ? JSON_RE : null;
  if (!re) return [[null, text]];
  re.lastIndex = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push([null, text.slice(last, m.index)]);
    if (lang === 'python') {
      const g = m.findIndex((v, i) => i > 0 && v !== undefined);
      out.push([PY_CLS[g], m[0]]);
    } else if (m[1]) {
      out.push([m[2] ? 'key' : 'str', m[1]]);
      if (m[2]) out.push([null, m[2]]);
    } else out.push([m[3] ? 'num' : 'const', m[0]]);
    last = re.lastIndex;
    if (m[0] === '') re.lastIndex++;
  }
  if (last < text.length) out.push([null, text.slice(last)]);
  return out;
}

function highlightLines(text, lang) {
  const lines = ['']; // html per line
  for (const [cls, chunk] of tokenize(text, lang)) {
    chunk.split('\n').forEach((part, i) => {
      if (i > 0) lines.push('');
      if (part) lines[lines.length - 1] += cls ? `<span class="tok-${cls}">${esc(part)}</span>` : esc(part);
    });
  }
  return lines;
}

const langOf = p => p.endsWith('.py') ? 'python' : p.endsWith('.json') ? 'json' : p.endsWith('.md') ? 'markdown' : 'text';
const LANG_NAME = { python: 'Python', json: 'JSON', markdown: 'Markdown', text: 'Plain Text' };
const badge = (p, sm = '') => {
  const l = langOf(p);
  return l === 'python' ? `<span class="badge ${sm}">PY</span>` : l === 'json' ? `<span class="badge json ${sm}">{}</span>`
    : `<span class="badge md ${sm}">TXT</span>`;
};

// ---------- app state ----------
let S = null;                 // last /api/state snapshot
let view = 'home';
let tabs = [];                // open file paths
let active = null;            // active tab path
const files = {};             // path -> content
let cursor = { ln: 1, col: 1 };
let highlightLine = null;
let pollTimer = null, busySince = null, lastChatKey = '';
let settings = null;
let tryState = { ep: 0, role: 'user', uid: '1', resp: null, sending: false };

// ---------- polling ----------
async function refresh() {
  const prev = S;
  try { S = await api('/api/state'); } catch (e) { toast(e.message); return; }
  if (S.busy && !busySince) busySince = Date.now();
  if (!S.busy) busySince = null;
  const justBuilt = prev && prev.busy && !S.busy && S.state.build_ok;
  if (justBuilt || (S.state.workspace && !prev)) await loadFiles(justBuilt);
  render();
  clearTimeout(pollTimer);
  if (S.busy) pollTimer = setTimeout(refresh, 800);
}

async function act(path, body) {
  try { S = await api(path, { method: 'POST', body }); busySince = S.busy ? Date.now() : null; render(); }
  catch (e) { toast(e.message); }
  refresh();
}

async function loadFiles(openMain) {
  try {
    const { files: list } = await api('/api/files');
    S && (S._files = list);
    for (const p of list) delete files[p];
    tabs = tabs.filter(t => list.includes(t));
    if (openMain && list.includes('app/main.py')) await openFile('app/main.py', null, false);
    else if (!tabs.length && list.includes('app/main.py')) await openFile('app/main.py', null, false);
  } catch { /* no project yet */ }
}

async function openFile(path, line = null, switchView = true) {
  if (!(path in files)) {
    try { files[path] = (await api(`/api/file?path=${encodeURIComponent(path)}`)).content; }
    catch (e) { toast(e.message); return; }
  }
  if (!tabs.includes(path)) tabs.push(path);
  active = path; highlightLine = line; cursor = { ln: line || 1, col: 1 };
  if (switchView) setView('home'); else renderEditor();
  if (line) requestAnimationFrame(() => {  // vertical only: scrollIntoView would also scroll long lines sideways past the gutter
    const ed = $('#editor'), row = document.querySelector(`.lines div:nth-child(${line})`);
    if (row) { ed.scrollTop = row.offsetTop - ed.clientHeight / 2; ed.scrollLeft = 0; }
  });
}

function setView(v) {
  view = v;
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  document.querySelectorAll('.view').forEach(el => (el.hidden = el.id !== `view-${v}`));
  renderCenter();
}

// ---------- render ----------
function render() {
  if (!S) return;
  const st = S.state;
  $('#project-name').textContent = st.spec?.project_name || 'New project';
  $('#export-btn').hidden = !st.build_ok;
  renderChat();
  renderComposer();
  renderCenter();
}

function renderCenter() {
  if (!S) return;
  ({ home: renderEditor, files: renderFiles, map: renderMap, tests: renderTests, search: renderSearch, activity: renderActivity, run: renderRun, settings: renderSettings })[view]();
}

// editor
function renderEditor() {
  const tabsEl = $('#tabs');
  const name = p => p.split('/').pop();
  const dup = p => tabs.filter(t => name(t) === name(p)).length > 1;  // same file name in two folders
  tabsEl.innerHTML = tabs.map(p => `
    <div class="tab ${p === active ? 'active' : ''}" data-path="${esc(p)}" title="${esc(p)}">${badge(p)}<span>${esc(name(p))}</span>${dup(p) ? `<span class="tab-dir">${esc(p.split('/').slice(-2, -1)[0] || '')}</span>` : ''}
      <button class="close" data-close="${esc(p)}" title="Close">${icon('x')}</button></div>`).join('')
    + `<button class="tab-add" id="tab-add" title="Open a file">${icon('plus')}</button>`;
  const ed = $('#editor');
  if (!active || !(active in files)) {
    const built = S?.state.build_ok;
    ed.innerHTML = `<div class="empty-editor"><div>
      <div class="ghost-logo">${icon('logo')}</div>
      <h3>${built ? 'Pick a file' : 'Nothing built yet'}</h3>
      <p>${built ? 'Open a file with + or from Files.' : "Describe the app you want in the Assistant. I'll design it with you, then write and test the backend here."}</p>
    </div></div>`;
    $('#statusbar').innerHTML = '<span class="lang">Ready</span><span>UTF-8</span><span>LF</span>';
    return;
  }
  const lang = langOf(active);
  const lines = highlightLines(files[active], lang);
  ed.innerHTML = `<div class="code"><div class="gutter">${lines.map((_, i) =>
    `<div class="${i + 1 === highlightLine ? 'hl' : ''}">${i + 1}</div>`).join('')}</div>
    <div class="lines">${lines.map((l, i) => `<div class="${i + 1 === highlightLine ? 'hl' : ''}">${l || ' '}</div>`).join('')}</div></div>`;
  renderStatus();
}

function renderStatus() {
  if (!active) return;
  const lang = langOf(active);
  $('#statusbar').innerHTML = `<span class="lang">${badge(active, 'sm')} ${LANG_NAME[lang]}</span>
    <span>Ln ${cursor.ln}, Col ${cursor.col}</span><span>Spaces: ${lang === 'python' ? 4 : 1}</span><span>UTF-8</span><span>LF</span>`;
}

// files
function renderFiles() {
  const list = (S._files || []).filter(p => !p.endsWith('__init__.py'));
  const groups = {};
  for (const p of list) (groups[p.includes('/') ? p.split('/').slice(0, -1).join('/') : ''] ||= []).push(p);
  $('#view-files').innerHTML = `
    <div class="panel-head">Files <span class="sub">${list.length ? esc(S.state.workspace?.split('/').slice(-2).join('/')) : ''}</span>
      <div class="right"><button class="btn" id="files-refresh">${icon('refresh')}Refresh</button>
        ${list.length ? `<a class="btn" href="/api/export" download>${icon('download')}Download .zip</a>` : ''}</div></div>
    <div class="panel-body">${!list.length ? '<div class="empty">No files yet. They appear here once the coder builds your API.</div>' :
      Object.entries(groups).sort().map(([dir, ps]) => `
        ${dir ? `<div class="dir">${esc(dir)}/</div>` : '<div class="dir">project</div>'}
        ${ps.map(p => `<button class="file-row" data-open="${esc(p)}">${badge(p, 'sm')}${esc(p.split('/').pop())}</button>`).join('')}`).join('')}
    </div>`;
}

// map: how the generated modules import each other, drawn as layered columns
const LAYERS = [
  ['client', 'Client', 'Calls the API'],
  ['entry', 'Entry', 'Creates the app'],
  ['routers', 'Routers', 'HTTP endpoints'],
  ['services', 'Services', 'Business rules'],
  ['schemas', 'Schemas', 'Data shapes'],
  ['core', 'Core', 'Auth & storage'],
];
let mapData = null, mapKey = '';

async function renderMap() {
  const el = $('#view-map');
  const key = `${S.state.workspace}|${S.state.build_ok}|${S.state.logs.length}`;
  if (key !== mapKey) {
    mapKey = key;
    mapData = await api('/api/map').catch(() => ({ nodes: [], edges: [] }));
    if (view !== 'map') return;
  }
  const { nodes, edges } = mapData;
  const routes = nodes.reduce((n, m) => n + m.routes.length, 0);
  const head = `<div class="panel-head">Map <span class="sub">How your API's modules connect</span>
    ${nodes.length ? `<div class="right map-stats"><span><b>${nodes.length}</b> modules</span><span><b>${edges.length}</b> links</span><span><b>${routes}</b> endpoints</span></div>` : ''}</div>`;
  if (!nodes.length) {
    el.innerHTML = head + `<div class="panel-body"><div class="empty">The map appears once the coder builds your API.</div></div>`;
    return;
  }
  // a synthetic client calls the entry point
  const all = [{ id: 'client', name: 'HTTP client', layer: 'client', doc: 'Browser, app or curl', routes: [] }, ...nodes];
  const links = [...nodes.filter(n => n.layer === 'entry').map(n => ({ from: 'client', to: n.id })), ...edges];
  // order each column by the average position of what points at it (fewer crossings)
  const pos = {};
  const cols = LAYERS.map(([id]) => {
    const col = all.filter(n => n.layer === id);
    const score = n => {
      const src = links.filter(l => l.to === n.id && l.from in pos).map(l => pos[l.from]);
      return src.length ? src.reduce((a, b) => a + b, 0) / src.length : 1e9;
    };
    col.sort((a, b) => score(a) - score(b) || a.name.localeCompare(b.name));
    col.forEach((n, i) => (pos[n.id] = i));
    return col;
  });
  el.innerHTML = head + `<div class="panel-body map-body" id="map-body"><div class="map" id="map">
    <svg class="map-edges" id="map-edges"></svg>
    ${LAYERS.map(([id, title, sub], c) => !cols[c].length ? '' : `
      <div class="map-col">
        <div class="map-col-head"><span class="ldot l-${id}"></span>${title}<small>${sub}</small></div>
        ${cols[c].map(n => `
          <div class="mnode l-${n.layer}" data-node="${esc(n.id)}">
            ${n.file ? `<button class="mnode-name" data-open="${esc(n.file)}" title="Open ${esc(n.file)}">${esc(n.name)}<span>.py</span></button>`
              : `<div class="mnode-name">${esc(n.name)}</div>`}
            ${n.doc ? `<div class="mnode-doc">${esc(n.doc)}</div>` : ''}
            ${n.routes.length ? `<div class="mnode-routes">${n.routes.map(r => `
              <button class="route" data-open="${esc(n.file)}" data-line="${r.line}" title="${r.method} ${esc(r.path)}"><b class="m-${r.method.toLowerCase()}">${r.method}</b>${esc(r.path)}</button>`).join('')}</div>` : ''}
          </div>`).join('')}
      </div>`).join('')}
  </div></div>`;
  drawEdges(links);
}

function drawEdges(links) {
  const map = $('#map'), svg = $('#map-edges');
  if (!map) return;
  const box = map.getBoundingClientRect();
  const r = id => map.querySelector(`[data-node="${CSS.escape(id)}"]`)?.getBoundingClientRect();
  svg.setAttribute('width', map.scrollWidth); svg.setAttribute('height', map.scrollHeight);
  svg.innerHTML = links.map(l => {
    const a = r(l.from), b = r(l.to);
    if (!a || !b) return '';
    const y1 = a.top - box.top + Math.min(a.height / 2, 26), y2 = b.top - box.top + Math.min(b.height / 2, 26);
    let x1 = a.right - box.left, x2 = b.left - box.left, d;
    if (x2 > x1 + 4) {
      const k = Math.max(40, (x2 - x1) / 2);
      d = `M${x1} ${y1} C${x1 + k} ${y1} ${x2 - k} ${y2} ${x2} ${y2}`;
    } else {  // same column: loop out to the right
      x2 = b.right - box.left;
      d = `M${x1} ${y1} C${x1 + 46} ${y1} ${x2 + 46} ${y2} ${x2} ${y2}`;
    }
    const layer = layerOf(l.to);
    return `<path class="edge l-${layer}" data-from="${esc(l.from)}" data-to="${esc(l.to)}" d="${d}"/>
      <circle class="edge-end l-${layer}" data-from="${esc(l.from)}" data-to="${esc(l.to)}" cx="${x2}" cy="${y2}" r="3"/>`;
  }).join('');
  map._links = links;
}
const layerOf = id => id === 'client' ? 'client' : mapData.nodes.find(n => n.id === id)?.layer || 'core';

function focusNode(id) {
  const map = $('#map');
  if (!map) return;
  map.classList.toggle('focus', !!id);
  const near = new Set(id ? [id] : []);
  map.querySelectorAll('.edge, .edge-end').forEach(e => {
    const on = !!id && (e.dataset.from === id || e.dataset.to === id);
    e.classList.toggle('on', on);
    if (on) { near.add(e.dataset.from); near.add(e.dataset.to); }
  });
  map.querySelectorAll('.mnode').forEach(n => n.classList.toggle('on', near.has(n.dataset.node)));
}
document.addEventListener('mouseover', e => {
  const n = e.target.closest?.('.mnode');
  if (n?.dataset.node !== focusNode.cur) focusNode(focusNode.cur = n?.dataset.node);
});
addEventListener('resize', () => view === 'map' && $('#map')?._links && drawEdges($('#map')._links));

// tests: every test the tester ran, grouped by file, click to open
const TEST_GROUPS = {
  'tests/test_contract.py': ['Contract tests', 'Generated from your design: login rules, unknown records and invalid input'],
  'tests/test_behaviour.py': ['Behaviour tests', 'Written by the tester agent from your design: each endpoint and business rule'],
};
const testCounts = res => ({ total: res.length, passed: res.filter(r => r.outcome === 'passed').length,
  failed: res.filter(r => r.outcome === 'failed' || r.outcome === 'error').length });

function renderTests() {
  const st = S.state, res = st.test_results || [], c = testCounts(res);
  const groups = {};
  for (const r of res) (groups[r.file] ||= []).push(r);
  const pill = !res.length ? '' : c.failed ? `<span class="pill bad">${c.failed} failing</span>` : `<span class="pill ok">All passing</span>`;
  $('#view-tests').innerHTML = `
    <div class="panel-head">Tests <span class="sub">${res.length ? `${c.passed} of ${c.total} passed` : ''}</span>
      <div class="right">${pill}</div></div>
    <div class="panel-body">${!res.length ? `<div class="empty">${st.build_ok
        ? 'This build has no test results yet. Rebuild to run the tester.' : 'The tester checks your API right after the coder builds it.'}</div>` : `
      ${st.tests_ok === false ? `<div class="known-issues">${icon('alert')}<div><b>Known problems</b>
        <p>The tester found these and the coder couldn't fix them.</p><pre>${esc(st.test_report || '')}</pre></div></div>` : ''}
      ${Object.entries(groups).map(([file, rows]) => {
        const [title, desc] = TEST_GROUPS[file] || [file.split('/').pop(), ''];
        const g = testCounts(rows);
        return `<div class="test-group">
          <div class="test-group-head"><div><b>${esc(title)}</b><span>${esc(desc)}</span></div>
            <span class="count ${g.failed ? 'bad' : 'ok'}">${g.passed}/${g.total}</span></div>
          ${rows.map(r => {
            const [, base, param] = r.name.match(/^([^[]+)(?:\[(.*)\])?$/) || [, r.name];
            return `<button class="test-row" data-test-file="${esc(file)}" data-test-fn="${esc(base)}" title="Open ${esc(file)}">
              <span class="tdot ${r.outcome}"></span><span class="tname">${esc(base.replace(/^test_/, '').replace(/_/g, ' '))}</span>
              ${param ? `<code>${esc(param)}</code>` : ''}<span class="toutcome ${r.outcome}">${r.outcome}</span></button>`;
          }).join('')}</div>`;
      }).join('')}`}
    </div>`;
}

async function openTest(file, fn) {
  if (!(file in files)) {
    try { files[file] = (await api(`/api/file?path=${encodeURIComponent(file)}`)).content; }
    catch (e) { return toast(e.message); }
  }
  const line = files[file].split('\n').findIndex(l => l.startsWith(`def ${fn}(`)) + 1;
  openFile(file, line || null);
}

// search
let searchQ = '', searchResults = [];
function renderSearch() {
  const el = $('#view-search');
  if (!el.innerHTML) {
    el.innerHTML = `<div class="panel-head">Search <span class="sub">in generated code</span></div>
      <div class="panel-body"><label class="search-box">${icon('search')}<input id="search-input" placeholder="Search files..." autocomplete="off"></label>
      <div id="search-results"></div></div>`;
  }
  const res = $('#search-results');
  if (!searchQ) { res.innerHTML = '<div class="empty">Type to search across your project files.</div>'; return; }
  if (!searchResults.length) { res.innerHTML = `<div class="empty">No matches for “${esc(searchQ)}”.</div>`; return; }
  const by = {};
  for (const r of searchResults) (by[r.path] ||= []).push(r);
  const re = new RegExp(searchQ.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  res.innerHTML = Object.entries(by).map(([p, rs]) => `
    <div class="result-file">${badge(p, 'sm')}${esc(p)} <span class="sub" style="color:var(--faint);font-weight:400">${rs.length}</span></div>
    ${rs.map(r => `<button class="result" data-open="${esc(p)}" data-line="${r.line}"><span class="ln">${r.line}</span>
      <span>${esc(r.text).replace(re, m => `<mark>${m}</mark>`)}</span></button>`).join('')}`).join('');
}
let searchTimer;
async function doSearch(q) {
  searchQ = q.trim();
  if (!searchQ) { searchResults = []; renderSearch(); return; }
  try { searchResults = (await api(`/api/search?q=${encodeURIComponent(searchQ)}`)).results; } catch (e) { toast(e.message); }
  renderSearch();
}

// activity
function renderActivity() {
  const logs = S.state.logs;
  const total = logs.reduce((a, l) => a + (l.tokens || 0), 0);
  $('#view-activity').innerHTML = `
    <div class="panel-head">Activity <span class="sub">every agent step, newest first</span>
      <div class="right"><span class="sub">${logs.length} steps · ${total.toLocaleString()} tokens</span></div></div>
    <div class="panel-body">${!logs.length ? '<div class="empty">No agent activity yet.</div>' :
      `<div class="timeline">${[...logs].reverse().map(l => `
        <div class="event"><span class="agent ${esc(l.agent)}">${esc(l.agent)}</span>
          <div class="what"><b>${esc(l.action)}</b>${l.detail ? `<div>${esc(l.detail)}</div>` : ''}</div>
          <div class="meta">${l.tokens ? `${l.tokens.toLocaleString()} tok<br>` : ''}${l.seconds ? `${l.seconds.toFixed(1)}s` : ''}</div></div>`).join('')}</div>`}
    </div>`;
}

// run / try it
const SAMPLE = { str: 'example', int: 1, float: 1.5, bool: true, email: 'user@example.com' };
function sampleBody(ep) {
  const ent = S.state.spec?.entities.find(e => e.name === ep.entity);
  if (!ent || !ep.request_fields.length) return '';
  const now = new Date();
  const obj = {};
  for (const name of ep.request_fields) {
    const f = ent.fields.find(x => x.name === name);
    const t = f?.type || 'str';
    obj[name] = t === 'date' ? now.toISOString().slice(0, 10) : t === 'datetime' ? new Date(now.getTime() + 864e5).toISOString().slice(0, 19)
      : name.endsWith('_id') ? 1 : SAMPLE[t];
  }
  return JSON.stringify(obj, null, 2);
}

function renderRun() {
  const st = S.state, srv = S.server, eps = st.spec?.endpoints || [];
  const ep = eps[tryState.ep];
  const params = ep ? [...ep.path.matchAll(/\{(\w+)\}/g)].map(m => m[1]) : [];
  $('#view-run').innerHTML = `
    <div class="panel-head">Run <span class="sub">start your API and try it</span></div>
    <div class="panel-body">
      <div class="card"><div class="row">
        <span class="dot ${srv ? 'on' : ''}"></span>
        <div style="flex:1;min-width:200px"><h4>${srv ? 'Your API is running' : st.build_ok ? 'Ready to start' : 'Not built yet'}</h4>
          <p>${srv ? `<a href="${srv.url}/docs" target="_blank">${srv.url}/docs</a> · inside the Docker sandbox, only reachable from this computer`
            : st.build_ok ? 'Starts in the sandbox with memory and CPU limits.' : 'Finish the chat and approve the design first.'}</p></div>
        ${srv ? `<a class="btn" href="${srv.url}/docs" target="_blank">${icon('external')}Open docs</a><button class="btn" id="run-stop">${icon('stop')}Stop</button>`
          : `<button class="btn primary" id="run-start" ${st.build_ok ? '' : 'disabled'}>${icon('play')}Start API</button>`}
      </div></div>
      ${eps.length ? `
      <div class="try">
        <div class="ep-list">${eps.map((e, i) => `<button class="ep ${i === tryState.ep ? 'sel' : ''}" data-ep="${i}">
          <span class="method m-${e.method}">${e.method}</span><span>${esc(e.path)}</span></button>`).join('')}</div>
        <div class="form">
          <div><b>${esc(ep.summary)}</b> <span class="sub" style="color:var(--muted);font-size:13px">· access: ${ep.access}</span></div>
          ${params.length ? `<div class="grid2">${params.map(p => `<div class="field"><label>${esc(p)}</label><input data-param="${esc(p)}" value="1"></div>`).join('')}</div>` : ''}
          <div class="grid2">
            <div class="field"><label>X-Role</label><select id="try-role">
              ${['public', 'user', 'admin'].map(r => `<option ${r === tryState.role ? 'selected' : ''}>${r}</option>`).join('')}</select></div>
            <div class="field"><label>X-User-Id</label><input id="try-uid" value="${esc(tryState.uid)}"></div>
          </div>
          ${['POST', 'PUT', 'PATCH'].includes(ep.method) ? `<div class="field"><label>Body (JSON)</label><textarea id="try-body">${esc(sampleBody(ep))}</textarea></div>` : ''}
          <div class="row"><button class="btn primary" id="try-send" ${srv && !tryState.sending ? '' : 'disabled'}>${icon('send')}${tryState.sending ? 'Sending...' : 'Send request'}</button>
            ${!srv ? '<span class="hint">Start the API to send requests.</span>' : ''}</div>
          ${tryState.resp ? `<div class="response"><div class="head"><span class="status ${tryState.resp.status < 400 ? 'ok' : 'bad'}">${tryState.resp.status}</span>
            <span style="color:var(--muted)">${tryState.resp.ms} ms</span></div><pre>${esc(pretty(tryState.resp.body))}</pre></div>` : ''}
        </div>
      </div>` : ''}
    </div>`;
}
const pretty = s => { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } };

async function sendTry() {
  const ep = S.state.spec.endpoints[tryState.ep];
  let path = ep.path;
  document.querySelectorAll('[data-param]').forEach(i => (path = path.replace(`{${i.dataset.param}}`, encodeURIComponent(i.value))));
  tryState.role = $('#try-role').value; tryState.uid = $('#try-uid').value;
  const headers = tryState.role === 'public' ? {} : { 'X-Role': tryState.role, 'X-User-Id': tryState.uid };
  const body = $('#try-body')?.value;
  tryState.sending = true; renderRun();
  try { tryState.resp = await api('/api/try', { body: { method: ep.method, path, headers, body } }); }
  catch (e) { toast(e.message); }
  tryState.sending = false; renderRun();
}

// settings
async function renderSettings() {
  if (!settings) settings = await api('/api/settings').catch(() => null);
  if (!settings) return;
  const defaults = { gemini: 'gemini-3.8-flash', 'claude-code': 'sonnet', claude: 'claude-sonnet-5-5' };
  $('#view-settings').innerHTML = `
    <div class="panel-head">Settings</div>
    <div class="panel-body"><div class="settings">
      <div class="card"><h4>Model</h4><p>Which LLM the agents use. Applies from the next message.</p>
        <div class="grid2" style="margin-top:14px">
          <div class="field"><label>Provider</label><select id="set-provider">${settings.providers.map(p =>
            `<option ${p === settings.provider ? 'selected' : ''}>${p}</option>`).join('')}</select></div>
          <div class="field"><label>Model</label><input id="set-model" value="${esc(settings.model)}" placeholder="${defaults[settings.provider] || ''}"></div>
        </div>
        <div class="hint">gemini needs GEMINI_API_KEY · claude-code uses your Claude Code login · claude needs ANTHROPIC_API_KEY.</div>
      </div>
      <div class="card"><h4>Sandbox</h4><p>Where generated code is checked and run.</p>
        <div class="field" style="margin-top:14px"><select id="set-sandbox">${['docker', 'local'].map(s =>
          `<option ${s === settings.sandbox ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
        <div class="hint">docker: isolated container, no network. local: plain process, not isolated.</div>
      </div>
      <div class="card"><h4>Profile</h4>
        <div class="field" style="margin-top:12px"><label>Your name</label><input id="set-name" value="${esc(settings.user_name)}"></div>
      </div>
      <div class="row"><button class="btn primary" id="set-save">${icon('check')}Save settings</button>
        <span class="hint">This session: ${S.tokens.toLocaleString()} tokens${S.model ? ` on ${esc(S.model)}` : ''}.</span></div>
    </div></div>`;
}

async function saveSettings() {
  try {
    settings = await api('/api/settings', { body: {
      provider: $('#set-provider').value, model: $('#set-model').value,
      sandbox: $('#set-sandbox').value, user_name: $('#set-name').value } });
    renderUser(); toast('Settings saved'); renderSettings();
  } catch (e) { toast(e.message); }
}

function renderUser() {
  const name = settings?.user_name || 'You';
  $('#user-name').textContent = name;
  $('#avatar').textContent = name.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
}

// ---------- assistant ----------
const CHIPS = [
  ['sparkle', 'A clinic appointment booking system', "I want an app where patients can book appointments with doctors at my clinic."],
  ['code', 'A personal meal & calorie tracker', 'I want a simple app to log my meals and track calories each day.'],
  ['zap', 'A library book lending app', 'I run a small library and want to track books, members and who borrowed what.'],
  ['list', 'Describe something else...', null],
];
const STEP_LABEL = { write_file: 'Wrote code', write_files: 'Wrote the project files', read_file: 'Read code', list_files: 'Looked at files', run_checks: 'Tested in the sandbox',
  finish: 'Wrapped up', invalid: 'Retried a garbled reply', gave_up: 'Stopped', done: 'Done',
  contract: 'Generated contract tests', write_test: 'Wrote tests', read_test: 'Read tests', run_tests: 'Ran the tests',
  verdict: 'Test result', restored: 'Kept the last working code' };

function coderSteps() {
  // build logs (coder, tester, orchestrator) since the most recent architect entry
  const logs = S.state.logs;
  let start = 0;
  logs.forEach((l, i) => { if (l.agent === 'architect' || (l.agent === 'orchestrator' && l.action === 'build')) start = i + 1; });
  return logs.slice(start).filter(l => l.agent !== 'architect' && l.agent !== 'requirements');
}

function renderChat() {
  const st = S.state;
  const key = JSON.stringify([st.chat.length, st.spec, st.spec_approved, st.build_ok, st.logs.length, S.busy, S.error, S.revisions, S.server]);
  const el = $('#messages');
  if (key === lastChatKey) { updateElapsed(); return; }
  lastChatKey = key;

  if (!st.chat.length && !S.busy) {
    el.innerHTML = `<div class="welcome"><div class="big-logo">${icon('logo')}</div>
      <h2>How can I help?</h2><p>Describe the app you want, and I'll design, build and run its backend.</p>
      <div class="chips">${CHIPS.map(([ic, label], i) => `<button class="chip" data-chip="${i}">${icon(ic, ic === 'list' || ic === 'code' ? 'plain' : '')}${esc(label)}</button>`).join('')}</div></div>`;
    return;
  }

  let html = '', prevRole = null;
  for (const m of st.chat) {
    if (m.role === 'assistant' && prevRole !== 'assistant') html += `<div class="who">${icon('logo')}Assistant</div>`;
    html += `<div class="msg ${m.role}">${m.role === 'assistant' ? md(m.content) : esc(m.content)}</div>`;
    prevRole = m.role;
  }
  for (const r of S.revisions) html += `<div class="msg user">${esc(r)}</div>`;
  if (st.spec) html += specCard();
  if (st.spec_approved) html += buildCard();
  if (S.busy && !(st.spec_approved && S.busy.startsWith('Building'))) {
    html += `<div class="typing"><div class="dots"><span></span><span></span><span></span></div>${esc(S.busy)} <span class="elapsed"></span></div>`;
  }
  if (S.error) html += `<div class="msg error">${icon('alert')}<div><b>Something went wrong.</b><br>${esc(S.error)}</div></div>`;
  el.innerHTML = html;
  updateElapsed();
  el.scrollTop = el.scrollHeight;
}

function updateElapsed() {
  const s = busySince ? Math.floor((Date.now() - busySince) / 1000) : 0;
  document.querySelectorAll('.elapsed').forEach(e => (e.textContent = busySince ? `${s}s` : ''));
}
setInterval(updateElapsed, 1000);

function specCard() {
  const sp = S.state.spec, review = S.state.spec_approved === false;
  const pill = review ? '<span class="pill run">Needs your OK</span>' : '<span class="pill ok">Approved</span>';
  return `<div class="acard"><div class="acard-head">${icon('layers')}${esc(sp.project_name)} · design ${pill}</div>
    <div class="acard-body">
      <p class="desc">${esc(sp.description)}</p>
      <h5>What it stores</h5>
      ${sp.entities.map(e => `<div class="entity"><b>${esc(e.name)}</b> <span>${e.fields.map(f => esc(f.name)).join(', ')}</span></div>`).join('')}
      <h5>What it can do · ${sp.endpoints.length} endpoints</h5>
      <div class="eps">${sp.endpoints.map(e => `<div class="e"><span class="method m-${e.method}">${e.method}</span>
        <code>${esc(e.path)}</code><span class="s">${esc(e.summary)}</span><span class="acc">${e.access}</span></div>`).join('')}</div>
      ${sp.rules.length ? `<h5>Rules</h5><ul class="rules">${sp.rules.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
    </div>
    ${review && !S.busy ? `<div class="acard-foot"><button class="btn primary" id="approve">${icon('check')}Approve & build</button>
      <button class="btn" id="request-change">Request a change</button></div>` : ''}</div>`;
}

function buildCard() {
  const st = S.state, steps = coderSteps();
  const building = S.busy && S.busy.startsWith('Building');
  const failed = !building && !st.build_ok && steps.some(l => l.action === 'gave_up');
  const pill = building ? '<span class="pill run">Building</span>' : st.build_ok ? '<span class="pill ok">Built</span>'
    : failed ? '<span class="pill bad">Failed</span>' : '<span class="pill">Queued</span>';
  const rows = steps.filter(l => l.action !== 'done').map(l => {
    const warn = l.action === 'invalid' || l.action === 'gave_up' || l.action === 'restored'
      || (l.action === 'verdict' && /failed|bugs|error|did not run/.test(l.detail));
    return `<div class="step ${warn ? 'warn' : ''}"><span class="ic">${icon(warn ? 'alert' : 'check')}</span>
      <div><b>${l.agent === 'tester' ? '<em class="agent-tag">Tester</em>' : ''}${STEP_LABEL[l.action] || esc(l.action)}</b>${l.detail ? `<span>${esc(l.detail.slice(0, 160))}</span>` : ''}</div></div>`;
  }).join('');
  const tc = testCounts(st.test_results || []);
  const strip = st.build_ok && !building && tc.total ? `<div class="test-strip ${tc.failed ? 'bad' : 'ok'}">${icon(tc.failed ? 'alert' : 'check')}
    <div><b>${tc.passed} of ${tc.total} tests passed</b><span>${(st.test_results || []).filter(r => r.file === 'tests/test_contract.py').length} contract · ${
      (st.test_results || []).filter(r => r.file !== 'tests/test_contract.py').length} behaviour</span></div>
    <button class="btn" data-go="tests">${icon('flask')}View tests</button></div>` : '';
  const live = building ? `<div class="step live"><span class="ic"><span class="spin"></span></span>
    <div><b>Working...</b><span class="elapsed"></span></div></div>` : '';
  let foot = '';
  if (st.build_ok && !building) {
    foot = `<div class="acard-foot">
      <button class="btn" data-open="app/main.py">${icon('code')}View code</button>
      ${st.tests_ok === false ? `<button class="btn" id="rebuild">${icon('refresh')}Rebuild</button>` : ''}
      <a class="btn" href="/api/export" download>${icon('download')}Download code</a>
      ${S.server ? `<button class="btn primary" id="goto-run">${icon('play')}Try it</button>`
        : `<button class="btn primary" id="start-api">${icon('play')}Start API</button>`}</div>`;
  } else if (failed) {
    foot = `<div class="acard-foot"><button class="btn primary" id="rebuild">${icon('refresh')}Try again</button></div>`;
  }
  const running = S.server ? ` It's running at <a href="${S.server.url}/docs" target="_blank">${S.server.url}/docs</a>.` : '';
  const tests = st.tests_ok ? ' The tester checked it against your design.'
    : st.tests_ok === false ? '' : ' Not tested yet.';
  const summary = st.build_ok && !building
    ? `<p class="desc" style="margin-bottom:10px">Your API is built: ${st.spec.endpoints.length} endpoints.${tests}${running}</p>
      ${st.tests_ok === false ? `<div class="known-issues">${icon('alert')}<div><b>Known problems (${esc(st.test_summary)})</b>
        <p>The tester found these and the coder couldn't fix them. Ask for a change or try building again.</p>
        <pre>${esc(st.test_report || '')}</pre></div></div>` : ''}` : '';
  return `<div class="acard"><div class="acard-head">${icon('code')}Build ${pill}</div>
    <div class="acard-body">${summary}<div class="steps">${rows}${live}${!rows && !live && !st.build_ok ? '<span class="desc">Waiting to start...</span>' : ''}</div>${strip}</div>${foot}</div>`;
}

function renderComposer() {
  const phase = S.phase, busy = !!S.busy;
  const input = $('#input');
  input.placeholder = busy ? 'Working on it...' : phase === 'chat' ? 'Ask a question or describe what you want...'
    : phase === 'review' ? 'Describe a change to the design, or approve it above...' : 'Describe a new feature or change...';
  input.disabled = busy;
  $('#send').disabled = busy;
}

async function send(text) {
  text = text.trim();
  if (!text || S?.busy) return;
  $('#input').value = ''; autoGrow();
  // optimistic bubble
  if (S.phase === 'chat') S.state.chat.push({ role: 'user', content: text });
  else S.revisions.push(text);
  S.busy = 'Thinking...'; busySince = Date.now(); lastChatKey = ''; render();
  await act('/api/chat', { text });
}

function autoGrow() {
  const t = $('#input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 180) + 'px';
}

// ---------- project menu ----------
async function toggleProjectMenu() {
  const menu = $('#project-menu');
  if (!menu.hidden) { menu.hidden = true; return; }
  let data = { projects: [], current: null };
  try { data = await api('/api/projects'); } catch (e) { toast(e.message); }
  menu.innerHTML = `${data.projects.length ? '<div class="label">Projects</div>' : ''}
    ${data.projects.map(p => `<button data-project="${esc(p.slug)}">${icon(p.slug === data.current ? 'check' : 'folder')}${esc(p.name)}
      <span class="tag">${p.built ? 'built' : 'draft'}</span></button>`).join('')}
    ${data.projects.length ? '<div class="sep"></div>' : ''}
    <button data-project="__new">${icon('plus')}New project</button>`;
  menu.hidden = false;
}

async function switchProject(slug) {
  $('#project-menu').hidden = true;
  try {
    S = await api(slug === '__new' ? '/api/projects/new' : '/api/projects/open', slug === '__new' ? { method: 'POST' } : { body: { slug } });
  } catch (e) { toast(e.message); return; }
  tabs = []; active = null; for (const k in files) delete files[k];
  lastChatKey = ''; tryState = { ...tryState, ep: 0, resp: null };
  S._files = [];
  await loadFiles(false);
  render();
}

// ---------- theme / layout ----------
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem('theme', t);
  $('#theme-btn').innerHTML = icon(t === 'dark' ? 'moon' : 'sun');
}
function toggleAssistant(show) {
  const body = document.querySelector('.body');
  body.classList.toggle('no-assistant', show === undefined ? !body.classList.contains('no-assistant') : !show);
}

// ---------- events ----------
document.addEventListener('click', async e => {
  const t = e.target.closest('button, a, .tab, .gutter div, .lines div');
  if (!t) { $('#project-menu').hidden = true; return; }
  if (!t.closest('.project-picker')) $('#project-menu').hidden = true;

  if (t.matches('.nav-item')) return setView(t.dataset.view);
  if (t.id === 'user') return setView('settings');
  if (t.id === 'project-btn') return toggleProjectMenu();
  if (t.dataset.project) return switchProject(t.dataset.project);
  if (t.id === 'theme-btn') return applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  if (t.id === 'panel-btn') return toggleAssistant();
  if (t.id === 'close-assistant') return toggleAssistant(false);
  if (t.dataset.close) {
    e.stopPropagation();
    tabs = tabs.filter(p => p !== t.dataset.close);
    if (active === t.dataset.close) active = tabs[tabs.length - 1] || null;
    return renderEditor();
  }
  if (t.matches('.tab')) { active = t.dataset.path; highlightLine = null; cursor = { ln: 1, col: 1 }; return renderEditor(); }
  if (t.id === 'tab-add' || t.id === 'files-refresh') { if (t.id === 'files-refresh') await loadFiles(false); return setView('files'); }
  if (t.dataset.open) return openFile(t.dataset.open, t.dataset.line ? +t.dataset.line : null);
  if (t.matches('.gutter div, .lines div')) {
    const idx = [...t.parentElement.children].indexOf(t) + 1;
    const sel = window.getSelection();
    cursor = { ln: idx, col: t.matches('.lines div') && sel.anchorNode && t.contains(sel.anchorNode) ? caretCol(t, sel) : 1 };
    return renderStatus();
  }
  if (t.dataset.chip !== undefined) {
    const [, , text] = CHIPS[+t.dataset.chip];
    if (text) return send(text);
    return $('#input').focus();
  }
  if (t.id === 'approve') return act('/api/spec/approve');
  if (t.id === 'request-change') { $('#input').focus(); return toast('Type the change you want below and press Enter.'); }
  if (t.id === 'rebuild') return act('/api/build');
  if (t.id === 'start-api' || t.id === 'run-start') {
    t.disabled = true; t.textContent = 'Starting...';
    try { S = await api('/api/run', { method: 'POST' }); lastChatKey = ''; render(); setView('run'); }
    catch (err) { toast(err.message); render(); }
    return;
  }
  if (t.id === 'goto-run') return setView('run');
  if (t.dataset.go) return setView(t.dataset.go);
  if (t.dataset.testFile) return openTest(t.dataset.testFile, t.dataset.testFn);
  if (t.id === 'run-stop') { S = await api('/api/run/stop', { method: 'POST' }); lastChatKey = ''; return render(); }
  if (t.dataset.ep !== undefined) { tryState.ep = +t.dataset.ep; tryState.resp = null; return renderRun(); }
  if (t.id === 'try-send') return sendTry();
  if (t.id === 'set-save') return saveSettings();
  if (t.id === 'attach-btn') return $('#attach').click();
});

function caretCol(lineEl, sel) {
  const r = document.createRange(); r.setStart(lineEl, 0);
  try { r.setEnd(sel.anchorNode, sel.anchorOffset); } catch { return 1; }
  return r.toString().length + 1;
}

document.addEventListener('change', e => {
  if (e.target.id === 'set-provider') { $('#set-model').placeholder = { gemini: 'gemini-3.8-flash', 'claude-code': 'sonnet', claude: 'claude-sonnet-5-5' }[e.target.value] || ''; }
  if (e.target.id === 'try-role') tryState.role = e.target.value;
});
document.addEventListener('input', e => {
  if (e.target.id === 'search-input') { clearTimeout(searchTimer); searchTimer = setTimeout(() => doSearch(e.target.value), 200); }
  if (e.target.id === 'try-uid') tryState.uid = e.target.value;
});

$('#composer').addEventListener('submit', e => { e.preventDefault(); send($('#input').value); });
$('#input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send($('#input').value); }
});
$('#input').addEventListener('input', autoGrow);
$('#attach').addEventListener('change', async e => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  if (f.size > 50_000) return toast('File too large (max 50 KB).');
  const text = await f.text();
  const input = $('#input');
  input.value = `${input.value ? input.value + '\n\n' : ''}Here is ${f.name}:\n${text}`;
  autoGrow(); input.focus();
});
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setView('search'); $('#search-input')?.focus(); }
});

// ---------- boot ----------
(async function boot() {
  hydrateIcons();
  if (DESKTOP) document.documentElement.classList.add('desktop');
  applyTheme(localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  settings = await api('/api/settings').catch(() => null);
  renderUser();
  setView('home');
  await refresh();
})();
