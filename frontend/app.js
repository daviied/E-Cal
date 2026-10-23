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
// MathLive's ascii-math output needs a couple of fixups before math.js can
// evaluate it:
//   - multi-character subscripts (typed as e.g. V_{2ab4s}) come out as
//     "V_(2a b4s)" - parens instead of braces, and a stray space inserted
//     between run-together alphanumeric groups. Collapse that back into one
//     plain identifier "V_2ab4s" so it matches how the same name is typed as
//     plain text elsewhere (e.g. an Input line's variable-name field).
//   - absolute value bars |x| come out as literal pipe characters, which
//     math.js's parser doesn't support at all (| means something else there)
//     - rewrite |...| pairs as abs(...) instead.
//   - some operators come out as Unicode symbols or ascii-math-specific
//     notation math.js's parser doesn't accept: "*" typed directly (not via
//     the usual \cdot/\times smart conversion) renders as "∗" (U+2217, not
//     a plain asterisk), and \div renders as the sequence " -: " rather
//     than "/".
//   - a matrix (e.g. from \begin{pmatrix}...\end{pmatrix}) comes out as
//     ascii-math's own nested-paren notation "((1,2),(3,4))", not math.js's
//     nested-bracket array literal "[[1,2],[3,4]]" that det()/other matrix
//     functions expect.
function cleanSubscripts(ascii) {
  return ascii.replace(/_\(([^()]*)\)/g, (_, inner) => '_' + inner.replace(/\s+/g, ''));
}
function convertAbsBars(ascii) {
  let prev;
  let result = ascii;
  let guard = 0;
  do {
    prev = result;
    result = result.replace(/\|([^|]*)\|/, 'abs($1)');
    guard++;
  } while (result !== prev && guard < 20);
  return result;
}
function convertMatrixParens(ascii) {
  // Matches a paren group whose entire content is one or more paren groups
  // (the rows), comma separated - i.e. specifically the doubly-nested
  // "tuple of tuples" shape ascii-math uses for a matrix, not a plain
  // function call like "sqrt(4)" or a plain tuple like "(2,3)".
  const pattern = /\(\s*(\([^()]*\)(?:\s*,\s*\([^()]*\))*)\s*\)/g;
  let prev;
  let result = ascii;
  let guard = 0;
  do {
    prev = result;
    result = result.replace(pattern, (whole, inner, offset, full) => {
      const bracketed = `[${inner.replace(/\(/g, '[').replace(/\)/g, ']')}]`;
      // "det (...)" is a valid function call in math.js's ascii syntax, but
      // once the argument itself becomes "[...]" square brackets, "det
      // [...]" (space then bracket) parses as array *indexing* instead -
      // wrap it back into an explicit call, "det([...])", when a function
      // name (e.g. det, \det from MathLive) precedes the matrix.
      const precededByIdentifier = /[A-Za-z_]\w*\s*$/.test(full.slice(0, offset));
      return precededByIdentifier ? `(${bracketed})` : bracketed;
    });
    guard++;
  } while (result !== prev && guard < 10);
  return result;
}
function normalizeOperators(ascii) {
  return ascii
    .replace(/∗|×|·/g, '*') // ∗, ×, · (middle dot - some apps' clipboard multiplication sign)
    .replace(/\s*-:\s*/g, '/') // \div
    .replace(/÷/g, '/') // ÷
    .replace(/−/g, '-') // unicode minus sign
    .replace(/≥/g, '>=')
    .replace(/≤/g, '<=')
    .replace(/\barc(sin|cos|tan)\b/g, 'a$1') // \arcsin etc -> math.js's asin/acos/atan
    .replace(/≠/g, '!='); // MathLive exports \geq/\leq/\neq as these unicode
    // symbols in ascii-math, but math.js's parser only accepts the ASCII
    // forms - needed for piecewise-style conditions (x>=0 ? a : b).
}
// Complex-number functions. math.js has re/im/conj/arg (and `i` as the
// imaginary unit), but MathLive hands them over differently: \Re and \Im
// come out as the symbols "ℜ"/"ℑ", \operatorname{Re} and plain typed letters
// as spaced-out letters ("R e(z)", "c o n j(z)"). Pasted TI-Nspire text spells
// them real(), imag() and angle(). All of those are mapped to math.js's names,
// but only when followed by "(" so letters multiplied together aren't touched.
const COMPLEX_NAMES = { Re: 're', Im: 'im', conj: 'conj', real: 're', imag: 'im', angle: 'arg' };
const COMPLEX_NAME_PATTERNS = Object.entries(COMPLEX_NAMES).map(([word, fn]) => [
  new RegExp('(?<![A-Za-z0-9_])' + word.split('').join(' ?') + '\\s*\\(', 'g'),
  fn + '(',
]);
function normalizeComplexNames(ascii) {
  let out = ascii.replace(/ℜ/g, 're').replace(/ℑ/g, 'im');
  for (const [pattern, replacement] of COMPLEX_NAME_PATTERNS) out = out.replace(pattern, replacement);
  return out;
}
function postProcessAscii(ascii) {
  return normalizeComplexNames(normalizeOperators(convertMatrixParens(convertAbsBars(cleanSubscripts(ascii)))));
}

// MathLive's ascii-math export drops \overline{z} (complex conjugate)
// entirely, so it is rewritten to conj(z) before conversion.
function rewriteOverline(latex) {
  let out = latex;
  for (let i = 0; i < 10 && out.includes('\\overline'); i++) {
    out = out.replace(/\\overline\s*\{([^{}]*)\}/g, '\\operatorname{conj}\\left($1\\right)');
  }
  return out;
}

// ---------- copying equations out to TI-Nspire ----------
// TI-Nspire's clipboard is plain text, and (confirmed against a real Nspire)
// it writes multiplication as an explicit "*" rather than the bare
// juxtaposition ("ab", "2x") that math.js's ascii-math output uses for
// implicit multiplication - e.g. copying `14229ab+1` off an Nspire and
// pasting it into a plain text editor yields the literal text
// "14229*ab+1". Reassuringly, that direction already works today with zero
// code changes: MathLive parses pasted plain text the same way it parses
// typed input, so "ab" becomes two separate single-letter variables `a`,
// `b` (implicit multiplication) exactly like Desmos/Nspire's own
// convention, and math.js's ascii-math parser already accepts the
// resulting "a b" as a * b.
//
// The other direction - copying one of *this* app's equations in a form
// Nspire will accept when pasted into its entry line - needs the reverse
// transform: walk the parsed expression tree and force every implicit
// multiplication node back into an explicit "*", since we can't be sure
// Nspire's parser accepts a bare space (or bare juxtaposition of a
// multi-character/subscripted variable) as multiplication the way math.js
// does.
const NSPIRE_FUNCTION_NAMES = { re: 'real', im: 'imag', arg: 'angle' };
function explicitMultiplyHandler(node, options) {
  if (node.type === 'OperatorNode' && node.fn === 'multiply' && node.implicit) {
    return node.args.map((arg) => arg.toString(options)).join(' * ');
  }
  if (node.type === 'FunctionNode' && node.fn && NSPIRE_FUNCTION_NAMES[node.fn.name]) {
    return NSPIRE_FUNCTION_NAMES[node.fn.name] + '(' + node.args.map((arg) => arg.toString(options)).join(', ') + ')';
  }
  return undefined; // fall through to math.js's default rendering
}
function toNspireText(ascii) {
  if (!ascii || !ascii.trim()) return '';
  try {
    return math.parse(ascii).toString({ handler: explicitMultiplyHandler });
  } catch {
    // Incomplete/invalid expression (e.g. still being typed) - fall back to
    // the raw ascii-math text rather than showing nothing.
    return ascii;
  }
}

function getFieldAscii(field) {
  try {
    const latex = field.getValue('latex') || '';
    if (latex.includes('\\overline')) return latexToAscii(latex);
    return postProcessAscii(field.getValue('ascii-math') || '');
  } catch {
    return getFieldLatex(field);
  }
}

// ---------- CAS (symbolic differentiation/integration via nerdamer) ----------
// nerdamer's own math notation disagrees with this app's log()/ln()
// convention in the exact opposite way math.js's does: nerdamer's bare
// log(x) IS natural log, and it has no ln() at all (an ln(...) call parses
// as the variable "ln" implicitly multiplied by its "argument"). So before
// handing an expression to nerdamer we rewrite the app's log(x) (base 10)
// as log(x)/log(10) in nerdamer's own natural-log terms, and the app's
// ln(x) as nerdamer's log(x) - then undo exactly that renaming on the way
// back (every bare log( nerdamer hands back, including inside the log(10)
// denominators we introduced, is natural log, so it always maps to ln().
// Finds the index of the ')' matching the '(' at str[openParenIdx].
function matchingParen(str, openParenIdx) {
  let depth = 0;
  for (let i = openParenIdx; i < str.length; i++) {
    if (str[i] === '(') depth++;
    else if (str[i] === ')') {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}
function isIdentChar(ch) {
  return !!ch && /[A-Za-z0-9_]/.test(ch);
}
// MathLive's ascii-math export puts a space between a function name and its
// parenthesized argument (e.g. "log (x)", "sin (x)"), which math.js's
// parser tolerates but nerdamer's does not - nerdamer parses "log (x)" as
// the bare identifier "log" implicitly multiplied by "(x)", and (worse)
// parses "log (x)+ln (x)" as a nonsensical single expression rather than a
// sum, since two of these misparsed calls next to each other confuses its
// tokenizer. Collapse that space away for known function names before
// nerdamer ever sees the text.
const CAS_FUNCTION_NAMES = [
  'log', 'ln', 'sqrt', 'abs', 'exp', 'det',
  'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh',
];
const CAS_FUNCTION_CALL_SPACE_RE = new RegExp('\\b(' + CAS_FUNCTION_NAMES.join('|') + ')\\s+\\(', 'g');
function stripCasFunctionCallSpaces(ascii) {
  return ascii.replace(CAS_FUNCTION_CALL_SPACE_RE, '$1(');
}
function rewriteLogForCas(ascii) {
  let out = '';
  let i = 0;
  while (i < ascii.length) {
    const isLn = ascii.startsWith('ln(', i) && !isIdentChar(ascii[i - 1]);
    const isLog = !isLn && ascii.startsWith('log(', i) && !isIdentChar(ascii[i - 1]);
    if (isLn || isLog) {
      const openIdx = i + (isLn ? 2 : 3);
      const closeIdx = matchingParen(ascii, openIdx);
      if (closeIdx !== -1) {
        const inner = rewriteLogForCas(ascii.slice(openIdx + 1, closeIdx));
        out += isLn ? `log(${inner})` : `(log(${inner})/log(10))`;
        i = closeIdx + 1;
        continue;
      }
    }
    out += ascii[i];
    i++;
  }
  return out;
}
function nerdamerLatexToAppConvention(tex) {
  return tex.replace(/\\mathrm\{log\}/g, '\\ln');
}
const CAS_RESERVED_NAMES = new Set([
  'pi', 'e', 'i', 'abs', 'sqrt', 'exp', 'log', 'ln', 'det',
  'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh', 'min', 'max', 'mod',
]);
function guessCasVariable(ascii) {
  const idents = ascii.match(/[A-Za-z_][A-Za-z0-9_]*/g) || [];
  return idents.find((s) => !CAS_RESERVED_NAMES.has(s)) || 'x';
}
function computeDerivativeLatex(ascii, varName) {
  const casExpr = rewriteLogForCas(stripCasFunctionCallSpaces(ascii));
  return nerdamerLatexToAppConvention(nerdamer.diff(casExpr, varName).toTeX());
}

// ---------- modal (replaces window.prompt/confirm, which don't render
// reliably/consistently styled across browser contexts) ----------
const modalOverlay = document.getElementById('modal-overlay');
const modalMessage = document.getElementById('modal-message');
const modalInput = document.getElementById('modal-input');
const modalCancel = document.getElementById('modal-cancel');
const modalOk = document.getElementById('modal-ok');

function askModal({ message, defaultValue = '', showInput = true, hideCancel = false }) {
  return new Promise((resolve) => {
    modalMessage.textContent = message;
    modalInput.hidden = !showInput;
    modalInput.value = defaultValue;
    modalCancel.hidden = hideCancel;
    modalOverlay.hidden = false;
    if (showInput) modalInput.focus();

    const cleanup = () => {
      modalOverlay.hidden = true;
      modalCancel.hidden = false;
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
const askAlert = (message) => askModal({ message, showInput: false, hideCancel: true });

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
const apiPut = (p, body) => api(p, { method: 'PUT', body: JSON.stringify(body) });
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
  f.setValue(rewriteOverline(latex), { format: 'latex' });
  return postProcessAscii(f.getValue('ascii-math') || '');
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
let treeData = { folders: [], calculators: [], globals: { lines: [] } };
let selected = null; // { id, kind }
// Folders start collapsed by default; opening one adds its id here, and it
// stays open (even across tree re-renders/reloads within this session)
// until explicitly collapsed again.
const expandedFolderIds = new Set();
let currentCalc = null; // full calculator object being edited
let saveTimer = null;

// ---------- auth ----------
const loginOverlay = document.getElementById('login-overlay');
const appRoot = document.getElementById('app');

// ---------- collapsible sidebar ----------
// Desktop: the sidebar can be hidden/shown, remembered per-device. Phone-width
// screens: it becomes an off-canvas drawer that starts closed and closes
// itself when a calculator is picked.
const MOBILE_QUERY = window.matchMedia('(max-width: 760px)');
const SIDEBAR_PREF_KEY = 'calcvault.sidebarCollapsed';

function setSidebarCollapsed(collapsed, { persist = true } = {}) {
  appRoot.classList.toggle('sidebar-collapsed', collapsed);
  if (persist && !MOBILE_QUERY.matches) {
    try {
      localStorage.setItem(SIDEBAR_PREF_KEY, collapsed ? '1' : '0');
    } catch {
      // storage unavailable (private mode etc.) - preference just won't stick
    }
  }
}
function applyInitialSidebarState() {
  let collapsed = MOBILE_QUERY.matches;
  if (!collapsed) {
    try {
      collapsed = localStorage.getItem(SIDEBAR_PREF_KEY) === '1';
    } catch {
      collapsed = false;
    }
  }
  setSidebarCollapsed(collapsed, { persist: false });
}
document.getElementById('btn-sidebar-close').addEventListener('click', () => setSidebarCollapsed(true));
document.querySelectorAll('[data-sidebar-open]').forEach((btn) => {
  btn.addEventListener('click', () => setSidebarCollapsed(false));
});
document.getElementById('sidebar-backdrop').addEventListener('click', () => setSidebarCollapsed(true));
MOBILE_QUERY.addEventListener('change', applyInitialSidebarState);

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
  if (!treeData.globals || !Array.isArray(treeData.globals.lines)) treeData.globals = { lines: [] };
  renderTree();
  populateFolderSelects();
  refreshOpenDocument();
}

// After the tree changes (rename, move, delete), an open document's folder
// chain - and so what it inherits - may have changed. Update the banner and
// the results without rebuilding the editing fields (focus stays put).
function refreshOpenDocument() {
  if (!currentCalc) return;
  if (currentCalc.kind === 'calc') {
    const meta = treeData.calculators.find((c) => c.id === currentCalc.id);
    if (meta) currentCalc.folder_id = meta.folder_id;
  } else if (currentCalc.kind === 'folder' && !treeData.folders.some((f) => f.id === currentCalc.id)) {
    clearSelection();
    return;
  }
  renderCalcContext();
  computeAll();
}

function childFolders(parentId) {
  return treeData.folders.filter((f) => f.parent_id === parentId);
}
function calcsInFolder(folderId) {
  return treeData.calculators.filter((c) => c.folder_id === folderId);
}

function sharedLineCount(data) {
  return data && Array.isArray(data.lines) ? data.lines.length : 0;
}
function sharedBadge(data) {
  const n = sharedLineCount(data);
  return n ? ` <small class="shared-badge" title="${n} shared line${n === 1 ? '' : 's'}">&#931;${n}</small>` : '';
}

function renderTree() {
  const root = document.getElementById('tree');
  root.innerHTML = '';

  const globalItem = document.createElement('div');
  globalItem.className = 'tree-item tree-global' + (selected && selected.kind === 'global' ? ' active' : '');
  globalItem.title = 'Lines every calculator can use (constants, formulas, givens)';
  globalItem.innerHTML = `<span>&#127760; Global lines${sharedBadge(treeData.globals)}</span>`;
  globalItem.addEventListener('click', () => selectShared('global'));
  root.appendChild(globalItem);

  root.appendChild(renderFolderLevel(null));
}

// Drag-and-drop reorganizing of the sidebar tree: folders can be dragged
// onto other folders to nest them, and calculators can be dragged onto any
// folder (or onto empty space, to land at the top level) to move them
// there. { type: 'folder' | 'calc', id }
let draggingItem = null;

// Dropping something onto empty sidebar space (not onto a folder header,
// which stops propagation in renderFolder) moves it back to the top level.
// #tree is a static element that's never recreated, so this only needs to
// be wired up once - not on every renderTree() call.
const treeRootEl = document.getElementById('tree');
treeRootEl.addEventListener('dragover', (e) => {
  if (!draggingItem) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
});
treeRootEl.addEventListener('drop', (e) => {
  e.preventDefault();
  if (!draggingItem) return;
  if (draggingItem.type === 'folder') moveFolder(draggingItem.id, null);
  else moveCalcToFolder(draggingItem.id, null);
});

// A folder can't be moved into itself or into one of its own descendants -
// that would orphan it from the tree entirely.
function isFolderOrDescendant(candidateId, rootId) {
  if (candidateId === rootId) return true;
  return childFolders(rootId).some((f) => isFolderOrDescendant(candidateId, f.id));
}

async function moveFolder(folderId, newParentId) {
  if (folderId === newParentId) return;
  if (isFolderOrDescendant(newParentId, folderId)) return; // would create a cycle
  await apiPatch(`/api/folders/${folderId}`, { parent_id: newParentId });
  if (newParentId !== null) expandedFolderIds.add(newParentId);
  await loadTree();
}

async function moveCalcToFolder(calcId, folderId) {
  await apiPatch(`/api/calculators/${calcId}`, { folder_id: folderId });
  if (folderId !== null) expandedFolderIds.add(folderId);
  await loadTree();
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
  header.className = 'tree-folder-header' + (selected && selected.kind === 'folder' && selected.id === folder.id ? ' active' : '');
  header.draggable = true;
  header.innerHTML = `<span>&#128193; ${escapeHtml(folder.name)}${sharedBadge(folder.data)}</span>`;

  const actions = document.createElement('span');
  actions.className = 'tree-row-actions';
  actions.innerHTML = `<button data-act="shared" title="Shared lines for every calculator in this folder">&#931;</button><button data-act="add-sub" title="New subfolder here">+</button><button data-act="rename" title="Rename">&#9998;</button><button data-act="delete" title="Delete">&#10005;</button>`;
  header.appendChild(actions);

  const children = document.createElement('div');
  children.className = 'tree-folder-children';
  children.appendChild(renderFolderLevel(folder.id));
  // Folders start collapsed and stay that way across re-renders (the whole
  // sidebar rebuilds on every create/rename/delete/move) until explicitly
  // opened - expandedFolderIds is the source of truth, not this style.
  children.hidden = !expandedFolderIds.has(folder.id);

  header.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    if (expandedFolderIds.has(folder.id)) {
      expandedFolderIds.delete(folder.id);
      children.hidden = true;
    } else {
      expandedFolderIds.add(folder.id);
      children.hidden = false;
    }
  });

  // Drag this folder onto another folder's header to nest it there. This
  // header is also a valid drop target for a dragged calculator (to file it
  // into this folder).
  header.addEventListener('dragstart', (e) => {
    draggingItem = { type: 'folder', id: folder.id };
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(folder.id));
    e.stopPropagation();
    requestAnimationFrame(() => header.classList.add('dragging'));
  });
  header.addEventListener('dragend', () => {
    draggingItem = null;
    document.querySelectorAll('.dragging, .drag-over').forEach((el) => {
      el.classList.remove('dragging', 'drag-over');
    });
  });
  header.addEventListener('dragover', (e) => {
    if (!draggingItem) return;
    if (draggingItem.type === 'folder' && draggingItem.id === folder.id) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';
    header.classList.add('drag-over');
  });
  header.addEventListener('dragleave', () => header.classList.remove('drag-over'));
  header.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    header.classList.remove('drag-over');
    if (!draggingItem) return;
    if (draggingItem.type === 'folder') moveFolder(draggingItem.id, folder.id);
    else moveCalcToFolder(draggingItem.id, folder.id);
  });

  actions.querySelector('[data-act="shared"]').addEventListener('click', (e) => {
    e.stopPropagation();
    selectShared('folder', folder.id);
  });
  actions.querySelector('[data-act="add-sub"]').addEventListener('click', async (e) => {
    e.stopPropagation();
    const name = await askPrompt('Subfolder name');
    if (!name) return;
    await apiPost('/api/folders', { name, parent_id: folder.id });
    expandedFolderIds.add(folder.id);
    await loadTree();
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
  item.className = 'tree-item' + (selected && selected.kind === 'calc' && selected.id === calc.id ? ' active' : '');
  item.draggable = true;
  item.innerHTML = `<span>${escapeHtml(calc.name)}</span>`;

  const actions = document.createElement('span');
  actions.className = 'tree-row-actions';
  actions.innerHTML = `<button data-act="delete" title="Delete">&#10005;</button>`;
  item.appendChild(actions);

  item.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    selectCalculator(calc.id);
  });

  // Drag onto a folder header to file it there, or onto empty sidebar
  // space to move it back to the top level.
  item.addEventListener('dragstart', (e) => {
    draggingItem = { type: 'calc', id: calc.id };
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(calc.id));
    requestAnimationFrame(() => item.classList.add('dragging'));
  });
  item.addEventListener('dragend', () => {
    draggingItem = null;
    document.querySelectorAll('.dragging, .drag-over').forEach((el) => {
      el.classList.remove('dragging', 'drag-over');
    });
  });
  actions.querySelector('[data-act="delete"]').addEventListener('click', async (e) => {
    e.stopPropagation();
    if (await askConfirm(`Delete "${calc.name}"?`)) {
      await apiDelete(`/api/calculators/${calc.id}`);
      if (selected && selected.kind === 'calc' && selected.id === calc.id) clearSelection();
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
  clearTimeout(saveTimer);
  saveTimer = null;
  selected = null;
  currentCalc = null;
  views.empty.hidden = false;
  views.calculator.hidden = true;
  renderTree();
}

// Calculators created under older versions of this app can have data
// shapes the current UI doesn't expect. Rather than crash on them (which
// would look like "the update deleted my calculator"), convert them into
// the current { locked, lines } shape on load, preserving whatever they
// contained.
function normalizeCalcData(data) {
  if (Array.isArray(data.lines)) {
    if (data.locked === undefined) data.locked = false;
    return data;
  }
  // Pre-unification "Function" kind: { paramName, paramDefault, formulaLatex, outputLabel }
  if ('formulaLatex' in data || 'paramName' in data) {
    const varName = data.paramName || 'x';
    return {
      locked: false,
      lines: [
        newLine('input', { varName, label: varName, value: data.paramDefault || '0' }),
        newLine('output', { expr: data.formulaLatex || '', label: data.outputLabel || 'Result' }),
      ],
    };
  }
  // Unrecognized/empty - start fresh rather than crash the view.
  return { locked: false, lines: [] };
}

async function selectCalculator(id) {
  await flushSave();
  if (MOBILE_QUERY.matches) setSidebarCollapsed(true, { persist: false });
  currentCalc = await apiGet(`/api/calculators/${id}`);
  currentCalc.kind = 'calc';
  currentCalc.data = normalizeCalcData(currentCalc.data);
  selected = { kind: 'calc', id };
  views.empty.hidden = true;
  views.calculator.hidden = false;
  renderCalcView();
  renderTree();
  // Online mode opens this calculator on the HP Prime too: hp.js when this
  // page runs it, the PC tool (`cvsync online`) through the server. Only a
  // hint, so failures are ignored.
  window.dispatchEvent(new CustomEvent('calcvault:calc-opened', { detail: { id } }));
  apiPut('/api/hp-focus', { calc_id: id }).catch(() => {});
}

// What is open can be a calculator, a folder's shared lines, or the global
// lines; each saves to its own place.
async function saveNow() {
  const doc = currentCalc;
  if (!doc) return;
  if (doc.kind === 'global') {
    await apiPut('/api/globals', { data: { lines: doc.data.lines } });
  } else if (doc.kind === 'folder') {
    await apiPatch(`/api/folders/${doc.id}`, { data: { lines: doc.data.lines } });
  } else {
    await apiPatch(`/api/calculators/${doc.id}`, { name: doc.name, data: doc.data });
    const idx = treeData.calculators.findIndex((c) => c.id === doc.id);
    if (idx >= 0) treeData.calculators[idx].name = doc.name;
  }
  renderTree();
}

// Opens the global lines (kind 'global') or one folder's shared lines (kind
// 'folder') in the same line editor a calculator uses. The editor works on
// the tree's own copy of the lines, so every calculator sees changes at once.
async function selectShared(kind, folderId = null) {
  await flushSave();
  if (MOBILE_QUERY.matches) setSidebarCollapsed(true, { persist: false });
  let data;
  let name;
  if (kind === 'global') {
    data = treeData.globals;
    name = 'Global lines';
  } else {
    const folder = treeData.folders.find((f) => f.id === folderId);
    if (!folder) return;
    if (!folder.data || !Array.isArray(folder.data.lines)) folder.data = { lines: [] };
    data = folder.data;
    name = 'Shared lines: ' + folder.name;
  }
  data.locked = false;
  currentCalc = { kind, id: folderId, name, folder_id: null, data };
  selected = { kind, id: folderId };
  views.empty.hidden = true;
  views.calculator.hidden = false;
  renderCalcView();
  renderTree();
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    saveNow();
  }, 400);
}

// Switching documents must not lose (or misdirect) an edit still waiting for
// its debounce timer: write it out first, while it is still the open one.
async function flushSave() {
  if (!saveTimer) return;
  clearTimeout(saveTimer);
  saveTimer = null;
  await saveNow();
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
//
// A new plain line starts hidden when locked: the locked view is meant to
// show Inputs and Outputs, with the working out of sight.
function newLine(role = 'none', overrides = {}) {
  return {
    id: crypto.randomUUID(),
    role,
    hidden: role === 'none',
    latex: '',
    varName: '',
    label: '',
    value: '',
    expr: '',
    ...overrides,
  };
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
  currentCalc.folder_id = folder_id;
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
  // Shared-line sets have no name of their own to edit, can't be moved or
  // deleted from here, and have no locked view.
  const isCalc = currentCalc.kind === 'calc';
  views.calculator.classList.toggle('shared-doc', !isCalc);
  calcNameInput.readOnly = !isCalc;
  calcNameInput.value = currentCalc.name;
  calcMoveSelect.value = currentCalc.folder_id ? String(currentCalc.folder_id) : '';
  const locked = isCalc && !!currentCalc.data.locked;
  renderCalcContext();
  calcLockToggle.textContent = locked ? 'Locked' : 'Unlocked';
  calcLockToggle.classList.toggle('locked', locked);
  calcLinesEl.innerHTML = '';
  calcLineRows = locked
    ? currentCalc.data.lines.map(renderLockedLine)
    : currentCalc.data.lines.map(renderEditLine);
  computeAll();
  if (systemKeyboard) calcLineRows.forEach((r) => setFieldInputMode(r.field));

  if (pendingFocusLineId) {
    const target = calcLineRows.find((r) => r.line.id === pendingFocusLineId);
    pendingFocusLineId = null;
    if (target && target.field) {
      activeLineId = target.line.id;
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

// Used by the CAS (d/dx) button: drops the symbolic result into a
// fresh plain Eq line right below the one it was computed from, leaving
// the original expression untouched.
function insertLineAfterWithLatex(line, latex) {
  const idx = currentCalc.data.lines.findIndex((l) => l.id === line.id);
  const created = newLine('none', { latex });
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

// Inserts a matrix template (\begin{pmatrix}...\end{pmatrix}, zero-filled)
// into a math-field at the cursor, sized from a quick "rows,cols" prompt.
// Dispatches a synthetic input event afterward so the field's own existing
// input listener (already wired per-role in renderEditLine) picks up the
// change the same way typing would.
function makeMatrixButton(field) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'matrix-insert-btn';
  btn.textContent = '⊞';
  btn.title = 'Insert a matrix';
  btn.addEventListener('click', async () => {
    const dims = await askPrompt('Matrix size as rows,cols', '2,2');
    if (!dims) return;
    const [rowsStr, colsStr] = dims.split(',');
    const rows = Math.max(1, Math.min(8, parseInt(rowsStr, 10) || 0));
    const cols = Math.max(1, Math.min(8, parseInt((colsStr || '').trim(), 10) || 0));
    if (!rows || !cols) return;
    const rowLatex = Array(cols).fill('0').join('&');
    const body = Array(rows).fill(rowLatex).join('\\\\');
    field.insert(`\\begin{pmatrix}${body}\\end{pmatrix}`);
    field.focus();
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
  return btn;
}

// Symbolic differentiation (via nerdamer, vendored in
// frontend/lib/nerdamer/). Leaves the original line untouched and drops
// the result into a fresh line right below it - same "insert a line"
// pattern as pressing Enter. Note: this app's V_2ab4s-style multi-character
// subscript variable names aren't recognized as single symbols by
// nerdamer's parser (it splits them into separate implicitly-multiplied
// tokens the way it would "2ab4s" on its own) - stick to single-letter
// variable names when using this button.
function makeDiffButton(line, field) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'cas-btn';
  btn.textContent = 'd/dx';
  btn.title = 'Differentiate (adds a new line below)';
  btn.addEventListener('click', async () => {
    const ascii = getFieldAscii(field);
    if (!ascii.trim()) return;
    const varName = await askPrompt('Differentiate with respect to:', guessCasVariable(ascii));
    if (!varName) return;
    try {
      const latex = computeDerivativeLatex(ascii, varName.trim());
      insertLineAfterWithLatex(line, latex);
    } catch (err) {
      await askAlert('Could not compute that: ' + err.message);
    }
  });
  return btn;
}

// Copies a computed result as plain text - meant for pasting into any other
// app's number entry (TI-Nspire's entry line included), which sidesteps
// needing to know that app's own math notation/clipboard format at all.
// getText is read lazily at click time so it always reflects the latest
// computed value, not whatever it was when the button was created.
function makeCopyButton(getText, opts = {}) {
  const icon = opts.icon || '⧉';
  const idleTitle = opts.title || 'Copy value';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'copy-btn';
  btn.textContent = icon;
  btn.title = idleTitle;
  btn.addEventListener('click', async () => {
    const text = getText();
    if (!text) return;
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      // Clipboard API needs a secure context (https, or http://localhost) -
      // fall back to the legacy selection-based copy for plain http hosts.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try {
        copied = document.execCommand('copy');
      } catch {
        copied = false;
      }
      ta.remove();
    }
    const original = btn.textContent;
    btn.textContent = copied ? '✓' : '✗';
    btn.title = copied ? idleTitle : 'Copy failed - select and copy manually';
    setTimeout(() => {
      btn.textContent = original;
      btn.title = idleTitle;
    }, 1000);
  });
  return btn;
}

// Copies the line's underlying equation (not just its computed value) as
// plain text meant for pasting directly into TI-Nspire's entry line - see
// toNspireText() above for why this needs its own conversion step rather
// than reusing the ascii-math text math.js evaluates internally.
function makeCopyEquationButton(field) {
  return makeCopyButton(() => toNspireText(getFieldAscii(field)), {
    icon: '⇄',
    title: 'Copy equation (for TI-Nspire)',
  });
}

// Every math-field in a calculator line comes from here. On phone-width
// screens the on-screen calculator keypad (below) takes over from MathLive's
// own virtual keyboard, so that one is switched to manual (never auto-shown).
function createCalcField() {
  const field = document.createElement('math-field');
  if (MOBILE_QUERY.matches) field.mathVirtualKeyboardPolicy = 'manual';
  return field;
}

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

    const field = createCalcField();
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

    const field = createCalcField();
    setFieldLatex(field, line.expr);
    field.addEventListener('input', () => {
      line.expr = getFieldLatex(field);
      scheduleSave();
      computeAll();
    });
    onEnterInsertsLine(field, line);
    row.appendChild(field);
    rowState.field = field;
    row.appendChild(makeMatrixButton(field));
    row.appendChild(makeDiffButton(line, field));

    const resultEl = document.createElement('div');
    resultEl.className = 'line-result';
    row.appendChild(resultEl);
    row.appendChild(makeCopyButton(() => resultEl.textContent));
    row.appendChild(makeCopyEquationButton(field));
    rowState.resultEl = resultEl;
  } else {
    const field = createCalcField();
    setFieldLatex(field, line.latex);
    field.addEventListener('input', () => {
      line.latex = getFieldLatex(field);
      scheduleSave();
      computeAll();
    });
    onEnterInsertsLine(field, line);
    row.appendChild(field);
    rowState.field = field;
    row.appendChild(makeMatrixButton(field));
    row.appendChild(makeDiffButton(line, field));

    const resultEl = document.createElement('div');
    resultEl.className = 'line-result';
    row.appendChild(resultEl);
    row.appendChild(makeCopyButton(() => resultEl.textContent));
    row.appendChild(makeCopyEquationButton(field));
    rowState.resultEl = resultEl;

    const hideLabel = document.createElement('label');
    hideLabel.className = 'hidden-check';
    hideLabel.hidden = currentCalc.kind !== 'calc';
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

    const field = createCalcField();
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

    const valueRow = document.createElement('div');
    valueRow.className = 'locked-output-value-row';
    const valueEl = document.createElement('div');
    valueEl.className = 'locked-output-value';
    valueEl.textContent = '—';
    valueRow.appendChild(valueEl);
    valueRow.appendChild(makeCopyButton(() => valueEl.textContent));
    item.appendChild(valueRow);

    calcLinesEl.appendChild(item);
    return { line, field: null, resultEl: valueEl };
  }

  if (line.hidden) {
    return { line, field: null, resultEl: null };
  }

  const row = document.createElement('div');
  row.className = 'locked-plain-line';
  const field = createCalcField();
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
  row.appendChild(makeCopyButton(() => resultEl.textContent));
  row.appendChild(makeCopyEquationButton(field));

  calcLinesEl.appendChild(row);
  return { line, field, resultEl };
}

// Evaluates every line top-to-bottom into one shared scope, exactly like
// Desmos: plain lines and inputs are assignments that extend the scope,
// outputs are pure expressions read from it without mutating anything.
// math.js's built-in log(x) is natural log and it has no ln() at all - the
// opposite of every calculator/Desmos convention, where log() means base 10
// and ln() means natural log. Override both in the scope every line
// evaluates against (a line can still shadow these by assigning its own
// "log"/"ln" variable, same as it could shadow any other scope entry).
function baseScope() {
  return {
    log: (x, base) => (base === undefined ? Math.log10(x) : Math.log(x) / Math.log(base)),
    ln: (x) => Math.log(x),
  };
}

// ---------- shared lines: global -> folder chain -> this calculator ----------
// Every calculator evaluates, in order: the global lines, then the shared
// lines of each folder from the outermost down to the one it sits in, then its
// own lines. Later lines win, so a question can override anything shared by
// assigning it again.

// The folder to start from when walking outwards: a calculator's own folder,
// or (for a folder's shared lines) that folder's parent.
function inheritanceStartFolder(doc) {
  if (doc.kind === 'calc') return doc.folder_id;
  if (doc.kind === 'folder') {
    const folder = treeData.folders.find((f) => f.id === doc.id);
    return folder ? folder.parent_id : null;
  }
  return null;
}

// -> [{ kind, id, label, lines }], outermost first.
function inheritedSets(doc) {
  if (doc.kind === 'global') return [];
  const sets = [{ kind: 'global', id: null, label: 'Global', lines: (treeData.globals && treeData.globals.lines) || [] }];
  const chain = [];
  const seen = new Set();
  let id = inheritanceStartFolder(doc);
  while (id !== null && id !== undefined && !seen.has(id)) {
    seen.add(id);
    const folder = treeData.folders.find((f) => f.id === id);
    if (!folder) break;
    chain.unshift({ kind: 'folder', id: folder.id, label: folder.name, lines: (folder.data && folder.data.lines) || [] });
    id = folder.parent_id;
  }
  return sets.concat(chain);
}

function renderCalcContext() {
  const el = document.getElementById('calc-context');
  if (!currentCalc) {
    el.hidden = true;
    return;
  }
  el.innerHTML = '';
  const intro = document.createElement('span');
  const sets = inheritedSets(currentCalc);
  if (currentCalc.kind === 'global') {
    intro.textContent = 'Shared by every calculator. Anything defined here (constants, formulas, givens) can be used in all of them.';
  } else if (currentCalc.kind === 'folder') {
    intro.textContent = 'Shared by every calculator in this folder and its subfolders. Also uses:';
  } else {
    intro.textContent = 'Also uses shared lines from (tap to edit):';
  }
  el.appendChild(intro);
  for (const set of sets) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'ctx-chip';
    chip.textContent = `${set.label} (${set.lines.length})`;
    chip.title = `Edit ${set.label} shared lines`;
    chip.addEventListener('click', () => selectShared(set.kind, set.id));
    el.appendChild(chip);
  }
  el.hidden = false;
}

// The ascii form of a shared line, cached per line: they are re-evaluated
// on every keystroke in the calculator being edited, and converting each
// through MathLive every time would be wasteful.
const sharedAsciiCache = new WeakMap();
function sharedLineAscii(line) {
  const body = line.role === 'input' ? line.value : line.latex;
  const key = `${line.role}|${line.varName}|${body}`;
  const hit = sharedAsciiCache.get(line);
  if (hit && hit.key === key) return hit.ascii;
  let ascii = '';
  try {
    if (line.role === 'input') {
      ascii = `${(line.varName || '').trim() || 'x'}=${latexToAscii(line.value) || '0'}`;
    } else {
      ascii = latexToAscii(line.latex);
    }
  } catch {
    ascii = '';
  }
  sharedAsciiCache.set(line, { key, ascii });
  return ascii;
}

// Runs the inherited lines into `scope`, silently: errors in a shared line
// show up where it is edited, not in every calculator that inherits it.
function evaluateInherited(scope) {
  for (const set of inheritedSets(currentCalc)) {
    for (const line of set.lines) {
      if (line.role === 'output') continue;
      const ascii = sharedLineAscii(line);
      if (!ascii.trim()) continue;
      try {
        math.evaluate(ascii, scope);
      } catch {
        // see above
      }
    }
  }
}

function computeAll() {
  const scope = baseScope();
  evaluateInherited(scope);
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

// ---------- calculator-style keypad (phone layout) ----------
// On phone-width screens the calculator is laid out like a handheld (HP Prime
// style): the lines are the "screen", and this on-screen keypad replaces both
// MathLive's own virtual keyboard and the OS keyboard. Keys drive whichever
// math-field was focused last, via MathLive's own typing/command API, so
// results go through exactly the same path as real keystrokes.
const keypadEl = document.getElementById('keypad');
const keypadState = { shift: false, alpha: false, alphaLock: false };
let activeLineId = null;

// Remember which line the user is working in. Tracked from focus *and* from
// taps (capture phase), since the keypad's own taps must never be what
// decides this, and focus events alone aren't reliable everywhere.
function noteActiveLine(target) {
  const field = target && target.closest ? target.closest('math-field') : null;
  const row = field && calcLineRows.find((r) => r.field === field);
  if (row) {
    activeLineId = row.line.id;
    setFieldInputMode(field);
  }
}

// Optional "use the phone's own keyboard" mode. MathLive hard-codes
// inputmode=none on each field's hidden input (so no OS keyboard appears);
// flipping that attribute to text brings the normal keyboard up instead,
// and the keypad is hidden while it's on.
let systemKeyboard = false;
function setFieldInputMode(field) {
  const sink = field && field.shadowRoot && field.shadowRoot.querySelector('.ML__keyboard-sink');
  if (sink) sink.setAttribute('inputmode', systemKeyboard ? 'text' : 'none');
}
document.getElementById('calc-kbd').addEventListener('click', () => {
  systemKeyboard = !systemKeyboard;
  document.getElementById('main').classList.toggle('system-keyboard', systemKeyboard);
  document.getElementById('calc-kbd').classList.toggle('active', systemKeyboard);
  for (const r of calcLineRows) setFieldInputMode(r.field);
  const row = activeKeypadRow();
  if (row) {
    try {
      row.field.blur();
    } catch {
      // see safeFocus
    }
    safeFocus(row.field);
  }
});
calcLinesEl.addEventListener('focusin', (e) => noteActiveLine(e.target));
calcLinesEl.addEventListener('pointerdown', (e) => noteActiveLine(e.target), true);

function activeKeypadRow() {
  const byId = calcLineRows.find((r) => r.field && r.line.id === activeLineId);
  if (byId) return byId;
  const editable = calcLineRows.filter((r) => r.field);
  return editable[editable.length - 1] || null;
}

const T = (text) => ({ text });
const L = (latex) => ({ latex });
const C = (cmd) => ({ cmd });
// A named function: the real \sin-style command (typing the letters would be
// read as a product of variables), then an opening paren.
const FN = (name) => [L('\\' + name), T('(')];

// A key: main label, action, optional shifted label + action, style class.
function key(label, action, shiftLabel = '', shiftAction = null, cls = '', span = 1) {
  return { label, action, shiftLabel, shiftAction, cls, span };
}
const digit = (d, shiftLabel = '', shiftAction = null) => key(d, [T(d)], shiftLabel, shiftAction, 'k-num');

const KEYPAD_MAIN = [
  [
    { id: 'shift', label: 'SHIFT', cls: 'k-shift-key' },
    { id: 'alpha', label: 'ALPHA', cls: 'k-alpha-key' },
    key('◀', [C('moveToPreviousChar')], '', null, 'k-nav'),
    key('▶', [C('moveToNextChar')], '', null, 'k-nav'),
    { id: 'del', label: 'DEL', shiftLabel: 'CLEAR', cls: 'k-del' },
  ],
  [
    key('sin', FN('sin'), 'sin⁻¹', FN('arcsin')),
    key('cos', FN('cos'), 'cos⁻¹', FN('arccos')),
    key('tan', FN('tan'), 'tan⁻¹', FN('arctan')),
    key('ln', FN('ln'), 'eˣ', [L('e^{#?}')]),
    key('log', FN('log'), '10ˣ', [L('10^{#?}')]),
  ],
  [
    key('x', [T('x')], 'y', [T('y')]),
    key('x²', [T('^'), T('2'), C('moveToNextChar')], 'x⁻¹', [T('^'), T('-1'), C('moveToNextChar')]),
    key('^', [T('^')], '|x|', [L('\\left|#?\\right|')]),
    key('√', [L('\\sqrt{#?}')], 'π', [L('\\pi')]),
    key('(', [T('(')], '<', [T('<')]),
  ],
  [
    digit('7', '≥', [L('\\geq')]),
    digit('8', '≤', [L('\\leq')]),
    digit('9', '≠', [L('\\neq')]),
    key(')', [T(')')], '>', [T('>')], 'k-op'),
    key('÷', [L('\\div')], 'a/b', [L('\\frac{#?}{#?}')], 'k-op'),
  ],
  [
    digit('4', '?', [T('?')]),
    digit('5', ':', [T(':')]),
    digit('6', '_', [T('_')]),
    key('×', [L('\\cdot')], 'e', [T('e')], 'k-op'),
    key('−', [T('-')], '=', [T('=')], 'k-op'),
  ],
  [
    digit('1', 'i', [T('i')]),
    digit('2', 'Re', [L('\\operatorname{Re}'), T('(')]),
    digit('3', 'Im', [L('\\operatorname{Im}'), T('(')]),
    key('+', [T('+')], 'conj', [L('\\operatorname{conj}'), T('(')], 'k-op'),
    { id: 'enter', label: 'ENTER', cls: 'k-enter', span: 1, rows: 2 },
  ],
  [
    digit('0', 'arg', FN('arg')),
    key('.', [T('.')], ',', [T(',')], 'k-num'),
    { id: 'up', label: '▲', shiftLabel: 'd/dx', cls: 'k-nav' },
    { id: 'down', label: '▼', cls: 'k-nav' },
  ],
];

const ALPHA_LETTERS = 'abcdefghijklmnopqrstuvwxyz'.split('');
function alphaRows() {
  const upper = keypadState.shift;
  const ch = (c) => (upper ? c.toUpperCase() : c);
  const letterKey = (c) => key(ch(c), [T(ch(c))], '', null, 'k-letter');
  const rows = [KEYPAD_MAIN[0]];
  for (let i = 0; i < 25; i += 5) rows.push(ALPHA_LETTERS.slice(i, i + 5).map(letterKey));
  rows.push([
    letterKey('z'),
    key('_', [T('_')], '', null, 'k-letter'),
    key(',', [T(',')], '', null, 'k-letter'),
    { id: 'back-to-main', label: '123', cls: 'k-nav' },
    { id: 'enter', label: 'ENTER', cls: 'k-enter' },
  ]);
  return rows;
}

// MathLive can throw from focus() when the previously focused field was
// just removed by a re-render (it tries to read that dead field's value as
// it blurs). The new field still ends up focused, so swallowing is safe.
function safeFocus(field) {
  try {
    field.focus();
  } catch {
    // see above
  }
}

function runKeyActions(actions) {
  const row = activeKeypadRow();
  if (!row) return;
  const field = row.field;
  safeFocus(field);
  for (const step of actions) {
    if (step.text !== undefined) field.executeCommand(['typedText', step.text]);
    else if (step.latex !== undefined) field.insert(step.latex, { format: 'latex' });
    else if (step.cmd) field.executeCommand(step.cmd);
  }
  field.dispatchEvent(new Event('input', { bubbles: true }));
}

function moveToNeighborLine(delta) {
  const editable = calcLineRows.filter((r) => r.field);
  const row = activeKeypadRow();
  const idx = editable.indexOf(row);
  const target = editable[idx + delta];
  if (target) {
    activeLineId = target.line.id;
    safeFocus(target.field);
  }
}

function pressDiff() {
  const row = activeKeypadRow();
  const btn = row && row.field.closest('.calc-line')?.querySelector('.cas-btn');
  if (btn) btn.click();
}

function pressSpecialKey(id) {
  const row = activeKeypadRow();
  switch (id) {
    case 'del':
      if (!row) return;
      if (keypadState.shift) {
        row.field.setValue('', { format: 'latex' });
        row.field.dispatchEvent(new Event('input', { bubbles: true }));
        safeFocus(row.field);
      } else {
        runKeyActions([C('deleteBackward')]);
      }
      break;
    case 'enter':
      if (row) insertLineAfter(row.line);
      break;
    case 'up':
      if (keypadState.shift) pressDiff();
      else moveToNeighborLine(-1);
      break;
    case 'down':
      moveToNeighborLine(1);
      break;
    case 'back-to-main':
      keypadState.alpha = false;
      keypadState.alphaLock = false;
      break;
    default:
  }
}

function renderKeypad() {
  const rows = keypadState.alpha ? alphaRows() : KEYPAD_MAIN;
  keypadEl.innerHTML = '';
  keypadEl.classList.toggle('keypad-alpha', keypadState.alpha);
  keypadEl.classList.toggle('keypad-shift', keypadState.shift);
  rows.forEach((rowKeys, r) => {
    rowKeys.forEach((k, c) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'kp-key ' + (k.cls || '');
      if (k.span > 1) btn.style.gridColumn = `span ${k.span}`;
      if (k.rows > 1) {
        btn.style.gridRow = `${r + 1} / span ${k.rows}`;
        btn.style.gridColumn = String(c + 1);
      }
      const sub = document.createElement('span');
      sub.className = 'kp-sub';
      sub.textContent = k.shiftLabel || '';
      const main = document.createElement('span');
      main.className = 'kp-main';
      main.textContent = k.label;
      btn.append(sub, main);

      if (k.id === 'shift') btn.classList.toggle('active', keypadState.shift);
      if (k.id === 'alpha') {
        btn.classList.toggle('active', keypadState.alpha);
        btn.classList.toggle('locked', keypadState.alphaLock);
      }

      // Keep the math-field focused: don't let the tap steal focus.
      btn.addEventListener('pointerdown', (e) => e.preventDefault());
      btn.addEventListener('mousedown', (e) => e.preventDefault());
      btn.addEventListener('click', () => pressKeypadKey(k));
      keypadEl.appendChild(btn);
    });
  });
}

function pressKeypadKey(k) {
  if (k.id === 'shift') {
    keypadState.shift = !keypadState.shift;
    renderKeypad();
    return;
  }
  if (k.id === 'alpha') {
    if (!keypadState.alpha) {
      keypadState.alpha = true;
    } else if (!keypadState.alphaLock) {
      keypadState.alphaLock = true; // second tap while on = lock
    } else {
      keypadState.alpha = false;
      keypadState.alphaLock = false;
    }
    renderKeypad();
    return;
  }

  if (k.id) {
    pressSpecialKey(k.id);
  } else {
    const actions = keypadState.shift && k.shiftAction ? k.shiftAction : k.action;
    runKeyActions(actions);
  }

  const wasAlphaLetter = keypadState.alpha && k.cls === 'k-letter';
  keypadState.shift = false;
  if (wasAlphaLetter && !keypadState.alphaLock) keypadState.alpha = false;
  renderKeypad();
}

renderKeypad();

document.getElementById('calc-more').addEventListener('click', () => {
  document.querySelector('.view-header').classList.toggle('show-more');
});

applyInitialSidebarState();

// Registering a service worker (together with /manifest.json) is what makes
// the app installable. Browsers only allow this over HTTPS or localhost.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

init();
