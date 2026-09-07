import 'mathlive';

// small shims to stay compatible across mathlive minor-version API differences
function setFieldLatex(field, latex) {
  try {
    field.setValue(latex || '', { format: 'latex' });
  } catch {
    field.value = latex || '';
  }
}
function getFieldLatex(field) {
  try {
    return field.getValue('latex');
  } catch {
    return field.value || '';
  }
}
function getFieldAscii(field) {
  try {
    return field.getValue('ascii-math') || '';
  } catch {
    return getFieldLatex(field);
  }
}

// ---------- modal (replaces window.prompt/confirm, which don't render
// reliably/consistently styled across browser contexts) ----------
const modalOverlay = document.getElementById('modal-overlay');
const modalMessage = document.getElementById('modal-message');
const modalInput = document.getElementById('modal-input');
const modalCancel = document.getElementById('modal-cancel');
const modalOk = document.getElementById('modal-ok');

function askModal({ message, defaultValue = '', showInput = true }) {
  return new Promise((resolve) => {
    modalMessage.textContent = message;
    modalInput.hidden = !showInput;
    modalInput.value = defaultValue;
    modalOverlay.hidden = false;
    if (showInput) modalInput.focus();

    const cleanup = () => {
      modalOverlay.hidden = true;
      modalOk.removeEventListener('click', onOk);
      modalCancel.removeEventListener('click', onCancel);
      modalInput.removeEventListener('keydown', onKeydown);
    };
    const onOk = () => {
      cleanup();
      resolve(showInput ? modalInput.value.trim() || null : true);
    };
    const onCancel = () => {
      cleanup();
      resolve(showInput ? null : false);
    };
    const onKeydown = (e) => {
      if (e.key === 'Enter') onOk();
      if (e.key === 'Escape') onCancel();
    };
    modalOk.addEventListener('click', onOk);
    modalCancel.addEventListener('click', onCancel);
    modalInput.addEventListener('keydown', onKeydown);
  });
}
const askPrompt = (message, defaultValue = '') => askModal({ message, defaultValue, showInput: true });
const askConfirm = (message) => askModal({ message, showInput: false });

// ---------- tiny fetch helpers ----------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (res.status === 401) {
    showLogin();
    throw new Error('Not authenticated');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}
const apiGet = (p) => api(p);
const apiPost = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body) });
const apiPatch = (p, body) => api(p, { method: 'PATCH', body: JSON.stringify(body) });
const apiDelete = (p) => api(p, { method: 'DELETE' });

// ---------- latex <-> plain math bridge (via a hidden math-field) ----------
let bridgeField = null;
function ensureBridge() {
  if (bridgeField) return bridgeField;
  bridgeField = document.createElement('math-field');
  bridgeField.style.position = 'absolute';
  bridgeField.style.left = '-9999px';
  bridgeField.style.top = '0';
  document.body.appendChild(bridgeField);
  return bridgeField;
}
function latexToAscii(latex) {
  if (!latex) return '';
  const f = ensureBridge();
  f.setValue(latex, { format: 'latex' });
  return f.getValue('ascii-math') || '';
}

function formatResult(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') {
    if (!isFinite(value)) return String(value);
    return math.format(value, { precision: 8 });
  }
  try {
    return math.format(value, { precision: 8 });
  } catch {
    return String(value);
  }
}

// ---------- state ----------
let treeData = { folders: [], calculators: [] };
let selected = null; // { id, kind }
let currentCalc = null; // full calculator object being edited
let saveTimer = null;

// ---------- auth ----------
const loginOverlay = document.getElementById('login-overlay');
const appRoot = document.getElementById('app');

function showLogin() {
  loginOverlay.hidden = false;
  appRoot.hidden = true;
}
function showApp() {
  loginOverlay.hidden = true;
  appRoot.hidden = false;
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.textContent = '';
  try {
    await apiPost('/api/login', { password: pw });
    showApp();
    await loadTree();
  } catch (err) {
    errEl.textContent = err.message;
  }
});

document.getElementById('btn-logout').addEventListener('click', async () => {
  await apiPost('/api/logout', {});
  selected = null;
  currentCalc = null;
  showLogin();
});

async function init() {
  try {
    const status = await apiGet('/api/session');
    if (status.authed) {
      showApp();
      await loadTree();
    } else {
      showLogin();
    }
  } catch {
    showLogin();
  }
}

// ---------- tree ----------
async function loadTree() {
  treeData = await apiGet('/api/tree');
  renderTree();
  populateFolderSelects();
}

function childFolders(parentId) {
  return treeData.folders.filter((f) => f.parent_id === parentId);
}
function calcsInFolder(folderId) {
  return treeData.calculators.filter((c) => c.folder_id === folderId);
}

function renderTree() {
  const root = document.getElementById('tree');
  root.innerHTML = '';
  root.appendChild(renderFolderLevel(null));
}

function renderFolderLevel(parentId) {
  const frag = document.createDocumentFragment();
  for (const folder of childFolders(parentId)) {
    frag.appendChild(renderFolder(folder));
  }
  for (const calc of calcsInFolder(parentId)) {
    frag.appendChild(renderCalcItem(calc));
  }
  return frag;
}

function renderFolder(folder) {
  const wrap = document.createElement('div');
  wrap.className = 'tree-folder';

  const header = document.createElement('div');
  header.className = 'tree-folder-header';
  header.innerHTML = `<span>&#128193; ${escapeHtml(folder.name)}</span>`;

  const actions = document.createElement('span');
  actions.className = 'tree-row-actions';
  actions.innerHTML = `<button data-act="rename" title="Rename">&#9998;</button><button data-act="delete" title="Delete">&#10005;</button>`;
  header.appendChild(actions);

  const children = document.createElement('div');
  children.className = 'tree-folder-children';
  children.appendChild(renderFolderLevel(folder.id));

  header.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    children.style.display = children.style.display === 'none' ? '' : 'none';
  });

  actions.querySelector('[data-act="rename"]').addEventListener('click', async (e) => {
    e.stopPropagation();
    const name = await askPrompt('Rename folder', folder.name);
    if (name) {
      await apiPatch(`/api/folders/${folder.id}`, { name });
      await loadTree();
    }
  });
  actions.querySelector('[data-act="delete"]').addEventListener('click', async (e) => {
    e.stopPropagation();
    if (await askConfirm(`Delete folder "${folder.name}" and everything inside it?`)) {
      await apiDelete(`/api/folders/${folder.id}`);
      if (selected) clearSelection();
      await loadTree();
    }
  });

  wrap.appendChild(header);
  wrap.appendChild(children);
  return wrap;
}

function renderCalcItem(calc) {
  const item = document.createElement('div');
  item.className = 'tree-item' + (selected && selected.id === calc.id ? ' active' : '');
  item.innerHTML = `<span>${escapeHtml(calc.name)}</span>`;

  const actions = document.createElement('span');
  actions.className = 'tree-row-actions';
  actions.innerHTML = `<button data-act="delete" title="Delete">&#10005;</button>`;
  item.appendChild(actions);

  item.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    selectCalculator(calc.id);
  });
  actions.querySelector('[data-act="delete"]').addEventListener('click', async (e) => {
    e.stopPropagation();
    if (await askConfirm(`Delete "${calc.name}"?`)) {
      await apiDelete(`/api/calculators/${calc.id}`);
      if (selected && selected.id === calc.id) clearSelection();
      await loadTree();
    }
  });

  return item;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function folderOptionsList() {
  const options = [{ id: '', label: '(no folder)' }];
  const walk = (parentId, depth) => {
    for (const f of childFolders(parentId)) {
      options.push({ id: String(f.id), label: '  '.repeat(depth) + f.name });
      walk(f.id, depth + 1);
    }
  };
  walk(null, 0);
  return options;
}

function populateFolderSelects() {
  const sel = document.getElementById('calc-move');
  sel.innerHTML = '';
  for (const opt of folderOptionsList()) {
    const o = document.createElement('option');
    o.value = opt.id;
    o.innerHTML = opt.label;
    sel.appendChild(o);
  }
}

// ---------- sidebar actions ----------
document.getElementById('btn-new-folder').addEventListener('click', async () => {
  const name = await askPrompt('Folder name');
  if (!name) return;
  await apiPost('/api/folders', { name, parent_id: null });
  await loadTree();
});

document.getElementById('btn-new-calc').addEventListener('click', async () => {
  const name = await askPrompt('Calculator name', 'New calculator');
  if (!name) return;
  const calc = await apiPost('/api/calculators', { name, folder_id: null });
  await loadTree();
  selectCalculator(calc.id);
});

// ---------- selection / views ----------
const views = {
  empty: document.getElementById('empty-state'),
  calculator: document.getElementById('calc-view'),
};

function clearSelection() {
  selected = null;
  currentCalc = null;
  views.empty.hidden = false;
  views.calculator.hidden = true;
  renderTree();
}

async function selectCalculator(id) {
  currentCalc = await apiGet(`/api/calculators/${id}`);
  // older data created before inputs/outputs/lock existed
  if (currentCalc.data.locked === undefined) currentCalc.data.locked = false;
  selected = { id };
  views.empty.hidden = true;
  views.calculator.hidden = false;
  renderCalcView();
  renderTree();
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    if (!currentCalc) return;
    await apiPatch(`/api/calculators/${currentCalc.id}`, {
      name: currentCalc.name,
      data: currentCalc.data,
    });
    const idx = treeData.calculators.findIndex((c) => c.id === currentCalc.id);
    if (idx >= 0) treeData.calculators[idx].name = currentCalc.name;
    renderTree();
  }, 400);
}

// ---------- calculator view ----------
// A line has one of three roles:
//   'none'   - a plain equation, editable as a math-field. Can be marked
//              `hidden`, which only takes visual effect while the
//              calculator is locked.
//   'input'  - a labeled, always-editable value (e.g. "Voltage") bound to
//              a variable name, independent of that display label.
//   'output' - a labeled, read-only computed result (e.g. "Power"),
//              driven by an expression independent of its display label.
// Locking a calculator switches from the full editable view (every line,
// every control) to a clean view: hidden 'none' lines disappear, and
// input/output lines show only their label + value, never the underlying
// variable name or expression.
function newLine(role = 'none') {
  return { id: crypto.randomUUID(), role, hidden: false, latex: '', varName: '', label: '', value: '', expr: '' };
}

const calcNameInput = document.getElementById('calc-name');
const calcMoveSelect = document.getElementById('calc-move');
const calcLinesEl = document.getElementById('calc-lines');
const calcLockToggle = document.getElementById('calc-lock-toggle');

calcNameInput.addEventListener('input', () => {
  currentCalc.name = calcNameInput.value;
  scheduleSave();
});
calcMoveSelect.addEventListener('change', async () => {
  const folder_id = calcMoveSelect.value ? Number(calcMoveSelect.value) : null;
  await apiPatch(`/api/calculators/${currentCalc.id}`, { folder_id });
  await loadTree();
});
document.getElementById('calc-delete').addEventListener('click', async () => {
  if (!(await askConfirm(`Delete "${currentCalc.name}"?`))) return;
  await apiDelete(`/api/calculators/${currentCalc.id}`);
  clearSelection();
  await loadTree();
});
document.getElementById('calc-add-line').addEventListener('click', () => {
  currentCalc.data.lines.push(newLine('none'));
  scheduleSave();
  renderCalcView();
});
calcLockToggle.addEventListener('click', () => {
  currentCalc.data.locked = !currentCalc.data.locked;
  scheduleSave();
  renderCalcView();
});

// Rows are rebuilt only on structural changes (add/delete/role change/lock
// toggle/switch calculator). Typing inside a math-field only recomputes
// results in place, so the field element is never recreated and
// focus/cursor stays put.
let calcLineRows = []; // [{ line, field|null, resultEl|null }]
let pendingFocusLineId = null;

function renderCalcView() {
  calcNameInput.value = currentCalc.name;
  calcMoveSelect.value = currentCalc.folder_id ? String(currentCalc.folder_id) : '';
  const locked = !!currentCalc.data.locked;
  calcLockToggle.textContent = locked ? 'Locked' : 'Unlocked';
  calcLockToggle.classList.toggle('locked', locked);
  calcLinesEl.innerHTML = '';
  calcLineRows = locked
    ? currentCalc.data.lines.map(renderLockedLine)
    : currentCalc.data.lines.map(renderEditLine);
  computeAll();

  if (pendingFocusLineId) {
    const target = calcLineRows.find((r) => r.line.id === pendingFocusLineId);
    pendingFocusLineId = null;
    if (target && target.field) {
      requestAnimationFrame(() => target.field.focus());
    }
  }
}

// Pressing Enter in any field of a line inserts a fresh line of the same
// role right after it and moves focus into it, so typing a column of
// equations (or inputs, or outputs) never requires reaching for the mouse.
function insertLineAfter(line) {
  const idx = currentCalc.data.lines.findIndex((l) => l.id === line.id);
  const created = newLine(line.role);
  currentCalc.data.lines.splice(idx + 1, 0, created);
  pendingFocusLineId = created.id;
  scheduleSave();
  renderCalcView();
}

function onEnterInsertsLine(el, line) {
  // Capture phase: math-field handles Enter internally (and stops
  // propagation) before it would ever reach a bubble-phase listener, so we
  // have to intercept it on the way down instead.
  el.addEventListener(
    'keydown',
    (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        e.stopPropagation();
        insertLineAfter(line);
      }
    },
    { capture: true }
  );
}

function makeDeleteButton(line) {
  const delBtn = document.createElement('button');
  delBtn.textContent = '✕';
  delBtn.title = 'Delete line';
  delBtn.addEventListener('click', () => {
    currentCalc.data.lines = currentCalc.data.lines.filter((l) => l.id !== line.id);
    scheduleSave();
    renderCalcView();
  });
  return delBtn;
}

function makeLabelInput(line, placeholder) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'role-label-input';
  input.placeholder = placeholder;
  input.value = line.label || '';
  input.addEventListener('input', () => {
    line.label = input.value;
    scheduleSave();
  });
  return input;
}

// Drag-and-drop reordering of lines, in the unlocked/edit view only.
// Only the small handle is draggable, so dragging never fights with
// clicking into a math-field or text input elsewhere in the row.
let draggingLineId = null;

function makeDragHandle(line) {
  const handle = document.createElement('span');
  handle.className = 'drag-handle';
  handle.textContent = '⠿'; // braille-pattern dots, reads as a grip icon
  handle.title = 'Drag to reorder';
  handle.draggable = true;
  handle.addEventListener('dragstart', (e) => {
    draggingLineId = line.id;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', line.id);
    requestAnimationFrame(() => handle.closest('.calc-line')?.classList.add('dragging'));
  });
  handle.addEventListener('dragend', () => {
    draggingLineId = null;
    document.querySelectorAll('.calc-line.dragging, .calc-line.drag-over').forEach((el) => {
      el.classList.remove('dragging', 'drag-over');
    });
  });
  return handle;
}

function attachDropTarget(row, line) {
  row.addEventListener('dragover', (e) => {
    if (draggingLineId === null || draggingLineId === line.id) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    row.classList.add('drag-over');
  });
  row.addEventListener('dragleave', () => {
    row.classList.remove('drag-over');
  });
  row.addEventListener('drop', (e) => {
    e.preventDefault();
    row.classList.remove('drag-over');
    const sourceId = e.dataTransfer.getData('text/plain') || draggingLineId;
    reorderLines(sourceId, line.id);
  });
}

function reorderLines(sourceId, targetId) {
  if (!sourceId || sourceId === targetId) return;
  const lines = currentCalc.data.lines;
  const fromIdx = lines.findIndex((l) => l.id === sourceId);
  const toIdx = lines.findIndex((l) => l.id === targetId);
  if (fromIdx === -1 || toIdx === -1) return;
  const [moved] = lines.splice(fromIdx, 1);
  lines.splice(toIdx, 0, moved);
  scheduleSave();
  renderCalcView();
}

// Full editable row: drag handle + role selector + role-specific controls + delete.
function renderEditLine(line) {
  const row = document.createElement('div');
  row.className = 'calc-line role-' + line.role;
  attachDropTarget(row, line);
  const rowState = { line, field: null, resultEl: null };

  row.appendChild(makeDragHandle(line));

  const roleSelect = document.createElement('select');
  roleSelect.className = 'role-select';
  for (const [value, label] of [['none', 'Eq'], ['input', 'Input'], ['output', 'Output']]) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    if (line.role === value) opt.selected = true;
    roleSelect.appendChild(opt);
  }
  roleSelect.addEventListener('change', () => {
    line.role = roleSelect.value;
    scheduleSave();
    renderCalcView();
  });
  row.appendChild(roleSelect);

  if (line.role === 'input') {
    const varInput = document.createElement('input');
    varInput.type = 'text';
    varInput.className = 'role-var-input';
    varInput.placeholder = 'var';
    varInput.value = line.varName || '';
    varInput.addEventListener('input', () => {
      line.varName = varInput.value;
      scheduleSave();
      computeAll();
    });
    onEnterInsertsLine(varInput, line);
    row.appendChild(varInput);

    const labelInput = makeLabelInput(line, 'Label (e.g. Voltage)');
    onEnterInsertsLine(labelInput, line);
    row.appendChild(labelInput);

    const field = document.createElement('math-field');
    setFieldLatex(field, line.value);
    field.addEventListener('input', () => {
      line.value = getFieldLatex(field);
      scheduleSave();
      computeAll();
    });
    onEnterInsertsLine(field, line);
    row.appendChild(field);
    rowState.field = field;
  } else if (line.role === 'output') {
    const labelInput = makeLabelInput(line, 'Label (e.g. Power)');
    onEnterInsertsLine(labelInput, line);
    row.appendChild(labelInput);

    const field = document.createElement('math-field');
    setFieldLatex(field, line.expr);
    field.addEventListener('input', () => {
      line.expr = getFieldLatex(field);
      scheduleSave();
      computeAll();
    });
    onEnterInsertsLine(field, line);
    row.appendChild(field);
    rowState.field = field;

    const resultEl = document.createElement('div');
    resultEl.className = 'line-result';
    row.appendChild(resultEl);
    rowState.resultEl = resultEl;
  } else {
    const field = document.createElement('math-field');
    setFieldLatex(field, line.latex);
    field.addEventListener('input', () => {
      line.latex = getFieldLatex(field);
      scheduleSave();
      computeAll();
    });
    onEnterInsertsLine(field, line);
    row.appendChild(field);
    rowState.field = field;

    const resultEl = document.createElement('div');
    resultEl.className = 'line-result';
    row.appendChild(resultEl);
    rowState.resultEl = resultEl;

    const hideLabel = document.createElement('label');
    hideLabel.className = 'hidden-check';
    const hideCheckbox = document.createElement('input');
    hideCheckbox.type = 'checkbox';
    hideCheckbox.checked = !!line.hidden;
    hideCheckbox.addEventListener('change', () => {
      line.hidden = hideCheckbox.checked;
      scheduleSave();
    });
    hideLabel.appendChild(hideCheckbox);
    hideLabel.appendChild(document.createTextNode('Hidden when locked'));
    row.appendChild(hideLabel);
  }

  const lineActions = document.createElement('div');
  lineActions.className = 'line-actions';
  lineActions.appendChild(makeDeleteButton(line));
  row.appendChild(lineActions);

  calcLinesEl.appendChild(row);
  return rowState;
}

// Clean locked-view row: inputs/outputs always show as labeled boxes;
// plain lines show only if not marked hidden; hidden plain lines render
// nothing but are still evaluated (via the latex bridge) so later lines
// and outputs still see their effect.
function renderLockedLine(line) {
  if (line.role === 'input') {
    const item = document.createElement('div');
    item.className = 'locked-item locked-input';
    const label = document.createElement('div');
    label.className = 'locked-label';
    label.textContent = line.label || line.varName || 'Input';
    item.appendChild(label);

    const field = document.createElement('math-field');
    setFieldLatex(field, line.value);
    field.addEventListener('input', () => {
      line.value = getFieldLatex(field);
      scheduleSave();
      computeAll();
    });
    item.appendChild(field);

    calcLinesEl.appendChild(item);
    return { line, field, resultEl: null };
  }

  if (line.role === 'output') {
    const item = document.createElement('div');
    item.className = 'locked-item locked-output';
    const label = document.createElement('div');
    label.className = 'locked-label';
    label.textContent = line.label || 'Output';
    item.appendChild(label);

    const valueEl = document.createElement('div');
    valueEl.className = 'locked-output-value';
    valueEl.textContent = '—';
    item.appendChild(valueEl);

    calcLinesEl.appendChild(item);
    return { line, field: null, resultEl: valueEl };
  }

  if (line.hidden) {
    return { line, field: null, resultEl: null };
  }

  const row = document.createElement('div');
  row.className = 'locked-plain-line';
  const field = document.createElement('math-field');
  setFieldLatex(field, line.latex);
  field.addEventListener('input', () => {
    line.latex = getFieldLatex(field);
    scheduleSave();
    computeAll();
  });
  row.appendChild(field);

  const resultEl = document.createElement('div');
  resultEl.className = 'line-result';
  row.appendChild(resultEl);

  calcLinesEl.appendChild(row);
  return { line, field, resultEl };
}

// Evaluates every line top-to-bottom into one shared scope, exactly like
// Desmos: plain lines and inputs are assignments that extend the scope,
// outputs are pure expressions read from it without mutating anything.
function computeAll() {
  const scope = {};
  for (const rowState of calcLineRows) {
    const { line, field, resultEl } = rowState;
    let ascii = '';
    try {
      if (line.role === 'input') {
        const valueAscii = field ? getFieldAscii(field) : latexToAscii(line.value);
        const varName = (line.varName || '').trim() || 'x';
        ascii = `${varName}=${valueAscii || '0'}`;
      } else if (line.role === 'output') {
        ascii = field ? getFieldAscii(field) : latexToAscii(line.expr);
      } else {
        ascii = field ? getFieldAscii(field) : latexToAscii(line.latex);
      }
    } catch {
      ascii = '';
    }

    if (!ascii.trim()) {
      if (resultEl) {
        resultEl.textContent = '';
        resultEl.classList.remove('line-error');
      }
      continue;
    }
    try {
      const value = math.evaluate(ascii, scope);
      if (resultEl) {
        resultEl.textContent = formatResult(value);
        resultEl.classList.remove('line-error');
      }
    } catch (err) {
      if (resultEl) {
        resultEl.textContent = 'error';
        resultEl.classList.add('line-error');
        resultEl.title = err.message;
      }
    }
  }
}

init();
