/* ── State ── */
const state = {
  meta: null,
  tools: [],
  selectedId: null,
  editing: false,
  isNew: false,
  sortKey: 'number',
  sortAsc: true,
  admin: false,
  adminPassword: '',
};

/* ── DOM refs ── */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const els = {
  status: $('#status'),
  dbPath: $('#dbPath'),
  openDbBtn: $('#openDbBtn'),
  createDbBtn: $('#createDbBtn'),
  newToolBtn: $('#newToolBtn'),
  editBtn: $('#editBtn'),
  cancelBtn: $('#cancelBtn'),
  saveBtn: $('#saveBtn'),
  deleteBtn: $('#deleteBtn'),
  detailTitle: $('#detailTitle'),
  tableBody: document.querySelector('#toolsTable tbody'),
  toolImage: $('#toolImage'),
  capList: $('#capList'),
  jobRates: $('#jobRates'),
  imageOverlay: $('#imageOverlay'),
  overlayImg: $('#overlayImg'),
  overlayClose: $('#overlayClose'),
  imageUploadBtn: $('#imageUploadBtn'),
  imageFileInput: $('#imageFileInput'),
  imagePlaceholder: $('#imagePlaceholder'),
  toolImg: $('#toolImg'),
  adminLoginBtn: $('#adminLoginBtn'),
  adminLogoutBtn: $('#adminLogoutBtn'),
  changePwBtn: $('#changePwBtn'),
  dbBar: $('#dbBar'),
};

/* Info fields */
const fields = {
  number: $('#f_number'),
  active: $('#f_active'),
  name: $('#f_name'),
  diameter: $('#f_diameter'),
  color: $('#f_color'),
  comment: $('#f_comment'),
  canPlunge: $('#f_canPlunge'),
  flutesNum: $('#f_flutesNum'),
  flutesLength: $('#f_flutesLength'),
  flutesCoating: $('#f_flutesCoating'),
  aliases: $('#f_aliases'),
  storePos: $('#f_storePos'),
  dCorrector: $('#f_dCorrector'),
  flutesType: $('#f_flutesType'),
  maxDepth: $('#f_maxDepth'),
  maxWorkingDepth: $('#f_maxWorkingDepth'),
  depthPerPass: $('#f_depthPerPass'),
};

/* Default rates */
const rates = {
  speed: $('#r_speed'),
  feed: $('#r_feed'),
  plunge: $('#r_plunge'),
  ramp: $('#r_ramp'),
};

/* ── Auth helpers ── */
function adminHeaders() {
  return { 'Content-Type': 'application/json', 'X-Admin-Password': state.adminPassword };
}

function setAdminMode(isAdmin) {
  state.admin = isAdmin;
  els.adminLoginBtn.classList.toggle('hidden', isAdmin);
  els.adminLogoutBtn.classList.toggle('hidden', !isAdmin);
  els.changePwBtn.classList.toggle('hidden', !isAdmin);
  els.imageUploadBtn.classList.toggle('hidden', !isAdmin);
  els.dbBar.classList.toggle('hidden', !isAdmin);

  // Show/hide admin-only buttons (when not editing)
  if (!state.editing) {
    els.newToolBtn.classList.toggle('hidden', !isAdmin);
    els.editBtn.classList.toggle('hidden', !isAdmin);
    els.deleteBtn.classList.toggle('hidden', !isAdmin);
  }
}

async function adminLogin() {
  const pw = prompt('Admin password:');
  if (pw === null) return;
  try {
    const res = await fetch('/api/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    const body = await res.json();
    if (body.admin) {
      state.adminPassword = pw;
      setAdminMode(true);
      setStatus('Admin mode');
    } else {
      setStatus('Wrong password', true);
    }
  } catch (e) {
    setStatus(String(e), true);
  }
}

function adminLogout() {
  state.adminPassword = '';
  setAdminMode(false);
  if (state.editing) cancelEdit();
  setStatus('Guest mode');
}

async function changePassword() {
  const newPw = prompt('New password (min 4 characters):');
  if (newPw === null) return;
  if (newPw.trim().length < 4) { setStatus('Password must be at least 4 characters', true); return; }
  try {
    const res = await fetch('/api/auth/change-password', {
      method: 'POST', headers: adminHeaders(),
      body: JSON.stringify({ newPassword: newPw.trim() }),
    });
    const body = await res.json();
    if (res.ok) {
      state.adminPassword = newPw.trim();
      setStatus('Password changed');
    } else {
      setStatus(body.error || 'Failed', true);
    }
  } catch (e) {
    setStatus(String(e), true);
  }
}

/* ── Helpers ── */
function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.className = 'status' + (isError ? ' error' : '');
}

function n(v) {
  if (v === '' || v === null || v === undefined) return null;
  const num = Number(v);
  return isNaN(num) ? null : num;
}

/** Format a double to 2 decimals, or empty string if falsy */
function f2(v) {
  if (v === null || v === undefined || v === 0 || v === '') return '';
  return Number(v).toFixed(2);
}

/** List of double input IDs — get formatted on blur */
const doubleFieldIds = ['f_diameter', 'f_flutesLength', 'f_maxDepth', 'f_maxWorkingDepth', 'f_depthPerPass'];

function setupDoubleFormatting() {
  for (const id of doubleFieldIds) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener('blur', () => {
      if (el.value !== '') {
        el.value = Number(el.value).toFixed(2);
      }
    });
  }
}
setupDoubleFormatting();

function setEditing(editing) {
  state.editing = editing;

  const allInputs = [
    ...Object.values(fields),
    ...Object.values(rates),
    ...$$('[data-cap]'),
    ...$$('[data-job]'),
  ];
  allInputs.forEach((el) => { if (el) el.disabled = !editing; });

  const showAdmin = state.admin && !editing;
  els.newToolBtn.classList.toggle('hidden', !showAdmin);
  els.editBtn.classList.toggle('hidden', !showAdmin);
  els.deleteBtn.classList.toggle('hidden', !showAdmin);
  els.cancelBtn.classList.toggle('hidden', !editing);
  els.saveBtn.classList.toggle('hidden', !editing);

  if (!editing) {
    els.editBtn.disabled = !state.selectedId;
    els.deleteBtn.disabled = !state.selectedId;
  }
}

/* ── Sort ── */
function sortTools() {
  const key = state.sortKey;
  const dir = state.sortAsc ? 1 : -1;
  state.tools.sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (typeof va === 'string') return va.localeCompare(vb) * dir;
    return (va - vb) * dir;
  });
}

function onSortClick(e) {
  const th = e.target.closest('th[data-sort]');
  if (!th) return;
  const key = th.dataset.sort;
  if (state.sortKey === key) {
    state.sortAsc = !state.sortAsc;
  } else {
    state.sortKey = key;
    state.sortAsc = true;
  }
  updateSortHeaders();
  sortTools();
  renderTools();
}

function updateSortHeaders() {
  $$('th[data-sort]').forEach((th) => {
    const isActive = th.dataset.sort === state.sortKey;
    th.classList.toggle('sort-active', isActive);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) {
      arrow.textContent = isActive ? (state.sortAsc ? '▲' : '▼') : '';
    }
  });
}

/* ── Build meta widgets ── */
function buildMetaWidgets() {
  els.capList.innerHTML = '';
  els.jobRates.innerHTML = '';
  if (!state.meta) return;

  for (const jt of state.meta.jobTypes) {
    const lbl = document.createElement('label');
    lbl.innerHTML = `<input type="checkbox" data-cap="${jt.code}" disabled /> ${jt.name}`;
    lbl.querySelector('input').addEventListener('change', () => updateJobRateVisibility());
    els.capList.appendChild(lbl);

    const sec = document.createElement('div');
    sec.className = 'rates-section hidden-job';
    sec.dataset.jobSection = jt.code;
    sec.innerHTML = `
      <h3>${jt.name}</h3>
      <div class="rates-row">
        <label>Speed <input type="number" min="0" step="100" data-job="${jt.code}" data-k="speed" disabled /></label>
        <label>Feed <input type="number" min="0" step="100" data-job="${jt.code}" data-k="feed" disabled /></label>
        <label>Plunge <input type="number" min="0" step="100" data-job="${jt.code}" data-k="plunge" disabled /></label>
        <label>Ramp <input type="number" min="0" step="100" data-job="${jt.code}" data-k="ramp" disabled /></label>
      </div>
    `;
    els.jobRates.appendChild(sec);
  }
}

function updateJobRateVisibility() {
  if (!state.meta) return;
  for (const jt of state.meta.jobTypes) {
    const cb = $(`[data-cap="${jt.code}"]`);
    const sec = $(`[data-job-section="${jt.code}"]`);
    if (cb && sec) {
      sec.classList.toggle('hidden-job', !cb.checked);
    }
  }
}

/* ── Render tool list ── */
function renderTools() {
  els.tableBody.innerHTML = '';
  for (const t of state.tools) {
    const tr = document.createElement('tr');
    if (t.id === state.selectedId) tr.classList.add('selected');
    tr.dataset.id = String(t.id);
    tr.innerHTML = `
      <td>${t.number}</td>
      <td>${t.name}</td>
      <td>${Number(t.diameter).toFixed(2)}</td>
      <td><span class="color-dot" style="background:${t.color}"></span></td>
      <td><span class="active-dot${t.active ? ' on' : ''}"></span></td>
    `;
    tr.addEventListener('click', () => {
      if (state.editing) return;
      loadTool(t.id);
    });
    els.tableBody.appendChild(tr);
  }
}

/* ── Clear / populate form ── */
function clearForm() {
  state.selectedId = null;
  state.isNew = false;
  els.detailTitle.textContent = '—';

  fields.number.value = '';
  fields.active.checked = false;
  fields.name.value = '';
  fields.diameter.value = '';
  fields.color.value = '#6ba4ff';
  fields.aliases.value = '';
  fields.storePos.value = '';
  fields.dCorrector.value = '';
  fields.comment.value = '';
  fields.canPlunge.checked = false;
  fields.flutesNum.value = '';
  fields.flutesLength.value = '';
  fields.flutesCoating.value = '';
  fields.flutesType.value = '';
  fields.maxDepth.value = '';
  fields.maxWorkingDepth.value = '';
  fields.depthPerPass.value = '';

  rates.speed.value = '';
  rates.feed.value = '';
  rates.plunge.value = '';
  rates.ramp.value = '';

  $$('[data-cap]').forEach((el) => { el.checked = false; });
  $$('[data-job]').forEach((el) => { el.value = ''; });
  updateJobRateVisibility();

  showToolImage(null);
  setEditing(false);
  renderTools();
}

function populateForm(t) {
  state.selectedId = t.id;
  state.isNew = false;
  els.detailTitle.textContent = `#${t.number} | ${t.name}`;

  fields.number.value = t.number;                   // int
  fields.active.checked = !!t.active;
  fields.name.value = t.name;
  fields.diameter.value = f2(t.diameter);             // double
  fields.color.value = t.color || '#6ba4ff';
  fields.aliases.value = t.aliases || '';
  fields.storePos.value = t.storePos || '';           // int
  fields.dCorrector.value = t.dCorrector || '';       // int
  fields.comment.value = t.comment || '';
  fields.canPlunge.checked = !!t.canPlunge;
  fields.flutesNum.value = t.flutesNum || '';         // int
  fields.flutesLength.value = f2(t.flutesLength);    // double
  fields.flutesCoating.value = t.flutesCoating || '';
  fields.flutesType.value = t.flutesType || '';
  fields.maxDepth.value = f2(t.maxDepth);             // double
  fields.maxWorkingDepth.value = f2(t.maxWorkingDepth); // double
  fields.depthPerPass.value = f2(t.depthPerPass);     // double

  const g = t.defaultsGlobal || {};
  rates.speed.value = g.speed ?? '';
  rates.feed.value = g.feed ?? '';
  rates.plunge.value = g.plunge ?? '';
  rates.ramp.value = g.ramp ?? '';

  const capSet = new Set(t.capabilities || []);
  $$('[data-cap]').forEach((el) => { el.checked = capSet.has(el.dataset.cap); });

  const byJob = t.defaultsByJob || {};
  $$('[data-job]').forEach((el) => {
    const v = byJob?.[el.dataset.job]?.[el.dataset.k];
    el.value = (v === null || v === undefined) ? '' : v;
  });

  updateJobRateVisibility();
  showToolImage(t.id);
  setEditing(false);
  renderTools();
}

/* ── API calls ── */
async function loadTool(id) {
  try {
    const res = await fetch(`/api/tools/${id}`);
    if (!res.ok) { setStatus('Failed to load tool', true); return; }
    populateForm(await res.json());
    setStatus('');
  } catch (e) {
    setStatus(String(e), true);
  }
}

async function refreshTools() {
  const res = await fetch('/api/tools');
  const data = await res.json();
  state.tools = data.tools || [];
  sortTools();
  renderTools();
}

async function refreshMeta() {
  const res = await fetch('/api/meta');
  if (!res.ok) throw new Error('Failed to load metadata');
  state.meta = await res.json();
  if (els.dbPath) els.dbPath.value = state.meta.dbPath || '';
  buildMetaWidgets();
}

function collectPayload() {
  const capabilities = Array.from($$('[data-cap]:checked')).map((x) => x.dataset.cap);
  const defaultsByJob = {};
  if (state.meta) {
    for (const jt of state.meta.jobTypes) {
      const code = jt.code;
      const get = (k) => { const el = $(`[data-job="${code}"][data-k="${k}"]`); return el ? el.value : ''; };
      const item = { speed: n(get('speed')), feed: n(get('feed')), plunge: n(get('plunge')), ramp: n(get('ramp')) };
      if (Object.values(item).some((v) => v !== null)) defaultsByJob[code] = item;
    }
  }
  return {
    number: Number(fields.number.value),
    name: fields.name.value.trim(),
    diameter: Number(fields.diameter.value),
    color: fields.color.value,
    canPlunge: fields.canPlunge.checked,
    active: fields.active.checked,
    aliases: fields.aliases.value.trim(),
    storePos: Number(fields.storePos.value) || 0,
    dCorrector: Number(fields.dCorrector.value) || 0,
    comment: fields.comment.value.trim(),
    flutesNum: Number(fields.flutesNum.value) || 0,
    flutesLength: Number(fields.flutesLength.value) || 0,
    flutesCoating: fields.flutesCoating.value,
    flutesType: fields.flutesType.value,
    maxDepth: Number(fields.maxDepth.value) || 0,
    maxWorkingDepth: Number(fields.maxWorkingDepth.value) || 0,
    depthPerPass: Number(fields.depthPerPass.value) || 0,
    capabilities,
    defaultsGlobal: { speed: n(rates.speed.value), feed: n(rates.feed.value), plunge: n(rates.plunge.value), ramp: n(rates.ramp.value) },
    defaultsByJob,
  };
}

async function saveTool() {
  let payload;
  try { payload = collectPayload(); } catch (err) { setStatus(err.message, true); return; }
  if (!payload.number || payload.number < 100 || payload.number > 999) { setStatus('Tool Number is required (100-999)', true); return; }
  if (!payload.diameter || payload.diameter <= 0) { setStatus('Diameter is required', true); return; }
  if (!payload.storePos || payload.storePos <= 0) { setStatus('Store Pos is required', true); return; }
  if (!payload.dCorrector || payload.dCorrector <= 0) { setStatus('D Corrector is required', true); return; }
  if (!payload.capabilities || payload.capabilities.length === 0) { setStatus('At least 1 capability is required', true); return; }
  const gd = payload.defaultsGlobal;
  if (gd.speed === null || gd.speed <= 0) { setStatus('Default Speed is required', true); return; }
  if (gd.feed === null || gd.feed <= 0) { setStatus('Default Feed is required', true); return; }
  if (payload.canPlunge && (gd.plunge === null || gd.plunge <= 0)) { setStatus('Default Plunge is required (Can Plunge is on)', true); return; }
  if (gd.ramp === null || gd.ramp <= 0) { setStatus('Default Ramp is required', true); return; }

  const url = state.isNew ? '/api/tools' : `/api/tools/${state.selectedId}`;
  const method = state.isNew ? 'POST' : 'PUT';
  try {
    const res = await fetch(url, { method, headers: adminHeaders(), body: JSON.stringify(payload) });
    const body = await res.json();
    if (!res.ok) { setStatus(body.error || 'Save failed', true); return; }
    setStatus('Saved');
    await refreshTools();
    await loadTool(body.id);
  } catch (e) {
    setStatus(String(e), true);
  }
}

async function openDbPath() {
  const dbPath = (els.dbPath.value || '').trim();
  if (!dbPath) { setStatus('DB path is required', true); return; }
  els.openDbBtn.disabled = true;
  setStatus('Opening DB...');
  try {
    const res = await fetch('/api/settings/db-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dbPath }) });
    const body = await res.json();
    if (!res.ok) { setStatus(body.error || 'Failed to open DB', true); return; }
    await refreshMeta();
    await refreshTools();
    clearForm();
    setStatus('DB opened');
  } catch (e) {
    setStatus(String(e), true);
  } finally {
    els.openDbBtn.disabled = false;
  }
}

function startNewTool() {
  clearForm();
  state.isNew = true;
  state.selectedId = null;
  els.detailTitle.textContent = 'New Tool';
  setEditing(true);
  fields.number.focus();
}

function startEdit() {
  if (!state.selectedId) return;
  setEditing(true);
}

function cancelEdit() {
  if (state.isNew) { clearForm(); return; }
  if (state.selectedId) loadTool(state.selectedId);
  else clearForm();
}

/* ── Image ── */
function showToolImage(toolId) {
  if (!toolId) {
    els.toolImg.classList.add('hidden');
    els.imagePlaceholder.classList.remove('hidden');
    return;
  }
  const src = `/api/tools/${toolId}/image?t=${Date.now()}`;
  const img = new Image();
  img.onload = () => {
    els.toolImg.src = src;
    els.toolImg.classList.remove('hidden');
    els.imagePlaceholder.classList.add('hidden');
  };
  img.onerror = () => {
    els.toolImg.classList.add('hidden');
    els.imagePlaceholder.classList.remove('hidden');
  };
  img.src = src;
}

async function uploadImage(file) {
  if (!state.selectedId) { setStatus('Select a tool first', true); return; }
  const form = new FormData();
  form.append('image', file);
  try {
    const res = await fetch(`/api/tools/${state.selectedId}/image`, {
      method: 'POST', headers: { 'X-Admin-Password': state.adminPassword }, body: form,
    });
    if (!res.ok) { const b = await res.json(); setStatus(b.error || 'Upload failed', true); return; }
    showToolImage(state.selectedId);
    setStatus('Image uploaded');
  } catch (e) {
    setStatus(String(e), true);
  }
}

async function deleteTool() {
  if (!state.selectedId) return;
  if (!confirm('Delete this tool?')) return;
  try {
    const res = await fetch(`/api/tools/${state.selectedId}`, { method: 'DELETE', headers: adminHeaders() });
    if (!res.ok) { const b = await res.json(); setStatus(b.error || 'Delete failed', true); return; }
    setStatus('Deleted');
    await refreshTools();
    clearForm();
  } catch (e) {
    setStatus(String(e), true);
  }
}

async function createNewDb() {
  const dbPath = (els.dbPath.value || '').trim();
  if (!dbPath) { setStatus('Enter a path for the new database', true); return; }
  if (!dbPath.endsWith('.db')) { setStatus('Path must end with .db', true); return; }
  els.createDbBtn.disabled = true;
  setStatus('Creating database...');
  try {
    const res = await fetch('/api/settings/create-db', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dbPath }),
    });
    const body = await res.json();
    if (!res.ok) { setStatus(body.error || 'Failed to create DB', true); return; }
    await refreshMeta();
    await refreshTools();
    clearForm();
    setStatus('Database created');
  } catch (e) {
    setStatus(String(e), true);
  } finally {
    els.createDbBtn.disabled = false;
  }
}

/* ── Events ── */
els.adminLoginBtn.addEventListener('click', adminLogin);
els.adminLogoutBtn.addEventListener('click', adminLogout);
els.changePwBtn.addEventListener('click', changePassword);
els.openDbBtn.addEventListener('click', openDbPath);
els.createDbBtn.addEventListener('click', createNewDb);
els.newToolBtn.addEventListener('click', startNewTool);
els.editBtn.addEventListener('click', startEdit);
els.cancelBtn.addEventListener('click', cancelEdit);
els.deleteBtn.addEventListener('click', deleteTool);
els.saveBtn.addEventListener('click', saveTool);
els.imageUploadBtn.addEventListener('click', () => els.imageFileInput.click());
els.imageFileInput.addEventListener('change', () => {
  if (els.imageFileInput.files.length) uploadImage(els.imageFileInput.files[0]);
  els.imageFileInput.value = '';
});
els.toolImg.addEventListener('dblclick', () => {
  els.overlayImg.src = els.toolImg.src;
  els.imageOverlay.classList.remove('hidden');
});
els.overlayClose.addEventListener('click', () => els.imageOverlay.classList.add('hidden'));
els.imageOverlay.addEventListener('click', (e) => { if (e.target === els.imageOverlay) els.imageOverlay.classList.add('hidden'); });
document.querySelector('#toolsTable thead').addEventListener('click', onSortClick);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && state.editing) cancelEdit(); });

/* ── Init ── */
(async () => {
  setStatus('Loading...');
  try {
    await refreshMeta();
    if (state.meta && state.meta.noDatabase) {
      setStatus('No database — Open DB or Create New', true);
    } else {
      await refreshTools();
      clearForm();
      setStatus('Ready');
    }
  } catch (e) {
    setStatus(String(e), true);
  }
})();
