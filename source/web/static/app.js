const state = {
  available: new Map(), excluded: new Map(), ingredients: new Map(),
  visible: [], busy: false, searchVersion: 0, datasetVersion: null, view: null
};
const $ = id => document.getElementById(id);
const storageKey = 'goiy-selection-v1';
const readableError = error => error instanceof TypeError
  ? 'Không thể kết nối máy chủ. Hãy kiểm tra kết nối và thử lại.'
  : error.message;
const esc = value => {
  const node = document.createElement('div');
  node.textContent = String(value ?? '');
  return node.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

function searchConditions() {
  return {
    ingredient_ids: [...state.available.keys()].sort((a, b) => a - b),
    excluded_ids: [...state.excluded.keys()].sort((a, b) => a - b),
    top_k: Number($('top-k').value), algorithm: 'proposed',
    max_minutes: $('max-minutes').value === '' ? null : Number($('max-minutes').value)
  };
}

function conditionSignature() {
  return JSON.stringify(searchConditions());
}

function saveSelection() {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({
      version: 2,
      conditions: {
        available: [...state.available.keys()], excluded: [...state.excluded.keys()],
        maxMinutes: $('max-minutes').value, topK: $('top-k').value
      },
      view: state.view, searchQuery: $('ingredient-search').value, scrollY: window.scrollY
    }));
  } catch {
    // Do not leave an older snapshot available after a failed write (e.g. quota).
    try { sessionStorage.removeItem(storageKey); } catch { /* Storage is optional. */ }
  }
}

function validIds(ids, limit = 30) {
  return Array.isArray(ids) && ids.length <= limit && new Set(ids).size === ids.length &&
    ids.every(id => Number.isInteger(id) && id > 0 && state.ingredients.has(id));
}

function validCachedView(view) {
  if (!view || typeof view !== 'object' || view.signature !== conditionSignature() ||
      view.datasetVersion !== state.datasetVersion) return false;
  if (view.kind === 'error') return typeof view.message === 'string' && view.message.length > 0 && view.message.length <= 500;
  if (view.kind !== 'results' || !Array.isArray(view.items) || view.items.length > Number($('top-k').value)) return false;
  const unitScore = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const recipeIds = new Set();
  return view.items.every(item => {
    if (!item || typeof item !== 'object' || !Number.isInteger(item.recipe_id) || item.recipe_id <= 0 || recipeIds.has(item.recipe_id)) return false;
    recipeIds.add(item.recipe_id);
    return typeof item.title === 'string' && item.title.trim().length > 0 && item.title.length <= 255 &&
      Number.isInteger(item.minutes) && item.minutes >= 1 && item.minutes <= 240 &&
      (!$('max-minutes').value || item.minutes <= Number($('max-minutes').value)) &&
      unitScore(item.score) && unitScore(item.coverage) && unitScore(item.input_use) &&
      validIds(item.matched_ids) && item.matched_ids.length > 0 && validIds(item.missing_ids, 50) &&
      Number.isInteger(item.missing_count) && item.missing_count === item.missing_ids.length &&
      item.matched_ids.every(id => state.available.has(id)) &&
      item.missing_ids.every(id => !state.available.has(id)) &&
      [...item.matched_ids, ...item.missing_ids].every(id => !state.excluded.has(id));
  });
}

function restoreSelection() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (!saved) return;
    if (typeof saved !== 'object' || Array.isArray(saved) || (saved.version !== undefined && saved.version !== 2)) throw Error('Invalid snapshot');
    // Accept the old selection-only format without treating it as cached results.
    const conditions = saved.version === 2 ? saved.conditions : saved;
    const validNumber = (value, max) => typeof value === 'string' && /^\d+$/.test(value) && Number(value) >= 1 && Number(value) <= max;
    if (!conditions || !validIds(conditions.available) || !validIds(conditions.excluded) ||
        conditions.available.some(id => conditions.excluded.includes(id)) ||
        !(conditions.maxMinutes === '' || validNumber(conditions.maxMinutes, 240)) || !validNumber(conditions.topK, 20)) throw Error('Invalid conditions');
    state.available = new Map(conditions.available.map(id => [id, state.ingredients.get(id)]));
    state.excluded = new Map(conditions.excluded.map(id => [id, state.ingredients.get(id)]));
    $('max-minutes').value = conditions.maxMinutes;
    $('top-k').value = conditions.topK;
    if (typeof saved.searchQuery === 'string' && saved.searchQuery.length <= 80) $('ingredient-search').value = saved.searchQuery;
    if (saved.version === 2 && state.available.size && validCachedView(saved.view)) {
      state.view = saved.view;
      if (state.view.kind === 'results') renderRecommendations(state.view.items);
      else showError(state.view.message);
    } else {
      invalidateResults();
    }
    if (Number.isFinite(saved.scrollY) && saved.scrollY >= 0) requestAnimationFrame(() => window.scrollTo(0, saved.scrollY));
  } catch {
    try { sessionStorage.removeItem(storageKey); } catch { /* Storage is optional. */ }
    state.view = null;
  }
}

function renderIngredientResults() {
  const box = $('ingredient-results');
  if (!state.visible.length) {
    box.innerHTML = '<p class="field-help">Không tìm thấy nguyên liệu. Hãy thử tên khác.</p>';
    return;
  }
  box.innerHTML = state.visible.map(item => {
    const name = esc(item.name);
    return '<div class="ingredient-row"><span class="ingredient-name">' + name + '</span><div class="ingredient-actions">' +
      '<button type="button" class="ingredient-action" data-select="' + item.id + '" aria-label="Có sẵn: ' + name + '" aria-pressed="' + state.available.has(item.id) + '">' + (state.available.has(item.id) ? 'Đã chọn ✓' : 'Có sẵn') + '</button>' +
      '<button type="button" class="ingredient-action exclude" data-exclude="' + item.id + '" aria-label="Loại trừ: ' + name + '" aria-pressed="' + state.excluded.has(item.id) + '">' + (state.excluded.has(item.id) ? 'Đã loại ✓' : 'Loại trừ') + '</button></div></div>';
  }).join('');
}

async function loadIngredients(query = '', restore = false) {
  const version = ++state.searchVersion;
  const box = $('ingredient-results');
  box.setAttribute('aria-busy', 'true');
  try {
    const response = await fetch('/api/ingredients?query=' + encodeURIComponent(query) + '&limit=50');
    const envelope = await response.json();
    if (version !== state.searchVersion) return;
    if (!response.ok || !envelope.ok) throw Error(envelope.error?.message || 'Không tải được nguyên liệu.');
    const items = envelope.data.items || [];
    if (restore) state.datasetVersion = envelope.data.dataset_version;
    items.forEach(item => state.ingredients.set(item.id, item.name));
    state.visible = items;
    if (restore) restoreSelection();
    render();
    if (restore && $('ingredient-search').value) loadIngredients($('ingredient-search').value);
  } catch (error) {
    if (version !== state.searchVersion) return;
    box.innerHTML = '<div class="field-help error">' + esc(readableError(error)) + '</div><button type="button" id="retry-ingredients" class="retry-button">Thử tải lại</button>';
    $('retry-ingredients').onclick = () => loadIngredients($('ingredient-search').value, restore);
  } finally {
    if (version === state.searchVersion) box.setAttribute('aria-busy', 'false');
  }
}

function invalidateResults() {
  state.view = null;
  $('message').classList.add('hidden');
  $('results').innerHTML = '';
  $('result-count').textContent = '';
  $('result-context').textContent = 'Kết quả dựa trên nguyên liệu và bộ lọc bạn chọn.';
  showEmpty(
    state.available.size ? 'Sẵn sàng tìm món phù hợp' : 'Bữa ngon bắt đầu từ đây',
    state.available.size ? 'Bấm “Tìm món phù hợp” để cập nhật gợi ý theo lựa chọn mới.' : 'Chọn ít nhất một nguyên liệu có sẵn để bắt đầu.'
  );
  saveSelection();
}

function chooseIngredient(id, destination) {
  if (state.busy || !state.ingredients.has(id)) return;
  const target = destination === 'available' ? state.available : state.excluded;
  const other = destination === 'available' ? state.excluded : state.available;
  if (target.has(id)) {
    target.delete(id);
  } else {
    if (target.size >= 30) {
      $('selection-feedback').textContent = 'Nhóm này đã đủ 30 nguyên liệu. Hãy bỏ bớt trước khi thêm.';
      return;
    }
    other.delete(id);
    target.set(id, state.ingredients.get(id));
  }
  $('selection-feedback').textContent = 'Đã cập nhật lựa chọn nguyên liệu.';
  selectionChanged();
}

function selectionChanged() {
  render();
  invalidateResults();
}

function render() {
  $('selected-count').textContent = state.available.size + '/30';
  $('excluded-count').textContent = state.excluded.size + '/30';
  const chip = (id, name, excluded) => '<span class="chip' + (excluded ? ' excluded' : '') + '"><span>' + esc(name) + '</span>' +
    '<button type="button" data-move="' + id + '" data-destination="' + (excluded ? 'available' : 'excluded') + '" aria-label="' + (excluded ? 'Chuyển sang có sẵn: ' : 'Chuyển sang loại trừ: ') + esc(name) + '" title="' + (excluded ? 'Chuyển sang có sẵn' : 'Chuyển sang loại trừ') + '">' + (excluded ? '↶' : '⊘') + '</button>' +
    '<button type="button" data-remove="' + id + '" data-group="' + (excluded ? 'excluded' : 'available') + '" aria-label="Bỏ chọn: ' + esc(name) + '" title="Bỏ chọn">×</button></span>';
  $('selected-ingredients').className = 'chips' + (state.available.size ? '' : ' empty');
  $('selected-ingredients').innerHTML = state.available.size ? [...state.available].map(([id, name]) => chip(id, name, false)).join('') : 'Chưa chọn nguyên liệu';
  $('excluded-ingredients').className = 'chips' + (state.excluded.size ? '' : ' empty');
  $('excluded-ingredients').innerHTML = state.excluded.size ? [...state.excluded].map(([id, name]) => chip(id, name, true)).join('') : 'Không loại trừ nguyên liệu nào';
  $('recommend-button').disabled = state.busy || !state.available.size;
  $('clear-selection').disabled = state.busy || !(state.available.size + state.excluded.size);
  $('submit-help').textContent = state.available.size
    ? 'Bạn có thể đổi bộ lọc để tìm món khác.'
    : 'Chọn ít nhất 1 nguyên liệu có sẵn để bắt đầu.';
  renderIngredientResults();
}

function showError(message) {
  const box = $('message');
  box.classList.remove('hidden');
  box.textContent = message;
  $('empty-state').classList.add('hidden');
  $('results').innerHTML = '';
  $('result-count').textContent = '';
  state.view = {kind: 'error', signature: conditionSignature(), datasetVersion: state.datasetVersion, message};
  saveSelection();
}

function showEmpty(message, detail) {
  $('empty-state').classList.remove('hidden');
  $('empty-state').querySelector('h3').textContent = message;
  $('empty-state').querySelector('p').textContent = detail;
}

function ingredientTags(ids) {
  return ids.map(id => '<span class="ingredient-tag">' + esc(state.ingredients.get(id) || 'Nguyên liệu #' + id) + '</span>').join('');
}

function renderRecommendations(items) {
  const body = searchConditions();
  $('message').classList.add('hidden');
  $('empty-state').classList.add('hidden');
  $('results').innerHTML = '';
  $('result-count').textContent = items.length + ' món';
  $('result-context').textContent = state.available.size + ' nguyên liệu có sẵn · ' + state.excluded.size + ' loại trừ' +
    (body.max_minutes ? ' · Tối đa ' + body.max_minutes + ' phút' : '') + '. Điểm P1 là điểm xếp hạng, không phải đánh giá chất lượng món ăn.';
  if (!items.length) {
    showEmpty('Chưa tìm thấy món phù hợp', 'Thử bỏ bớt nguyên liệu loại trừ hoặc tăng thời gian tối đa.');
  } else {
    $('results').innerHTML = items.map((item, index) =>
      '<article class="recipe-card"><div class="recipe-top"><span class="recipe-rank">Gợi ý ' + String(index + 1).padStart(2, '0') + '</span><span class="score" title="Điểm xếp hạng P1 trên thang 1">P1 · ' + Number(item.score).toFixed(2) + '</span></div>' +
      '<h3><a href="/recipes/' + item.recipe_id + '">' + esc(item.title) + '</a></h3><div class="meta-row"><span>◷ ' + esc(item.minutes) + ' phút</span><span>Thiếu ' + esc(item.missing_count) + ' nguyên liệu bắt buộc</span></div>' +
      '<div class="card-description"><div class="tag-label">Đã có · ' + item.matched_ids.length + '</div><div class="id-list">' + ingredientTags(item.matched_ids) + '</div>' +
      '<div class="tag-label missing">Còn thiếu · ' + esc(item.missing_count) + '</div><div class="id-list missing">' + (ingredientTags(item.missing_ids) || 'Đã đủ nguyên liệu bắt buộc') + '</div></div>' +
      '<a class="detail-link" href="/recipes/' + item.recipe_id + '">Xem công thức <span aria-hidden="true">→</span></a></article>'
    ).join('');
  }
}

async function recommend(event) {
  event.preventDefault();
  if (state.busy || !state.available.size || !$('recommend-form').reportValidity()) return;
  state.busy = true;
  state.view = null;
  $('ingredient-controls').disabled = true;
  $('recommend-button').disabled = true;
  $('loading').classList.remove('hidden');
  $('message').classList.add('hidden');
  $('results').innerHTML = '';
  $('result-count').textContent = '';
  $('empty-state').classList.add('hidden');
  $('results-area').setAttribute('aria-busy', 'true');
  saveSelection();
  try {
    const body = {
      ingredient_ids: [...state.available.keys()], excluded_ids: [...state.excluded.keys()],
      top_k: Number($('top-k').value), algorithm: 'proposed'
    };
    if ($('max-minutes').value) body.max_minutes = Number($('max-minutes').value);
    const response = await fetch('/api/recommend', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const envelope = await response.json();
    if (!response.ok || !envelope.ok) throw Error(envelope.error?.message || 'Không thể lấy gợi ý. Hãy thử lại.');
    const items = envelope.data.items;
    state.view = {
      kind: 'results', signature: conditionSignature(),
      datasetVersion: envelope.data.dataset_version, items
    };
    if (!validCachedView(state.view)) throw Error('Dữ liệu gợi ý không hợp lệ hoặc đã thay đổi. Hãy tải lại trang và tìm lại.');
    renderRecommendations(items);
    saveSelection();
    $('results-title').focus({preventScroll: true});
    if (matchMedia('(max-width: 760px)').matches) $('results-area').scrollIntoView({block: 'start', behavior: 'auto'});
  } catch (error) {
    showError(readableError(error));
  } finally {
    state.busy = false;
    $('ingredient-controls').disabled = false;
    $('recommend-button').disabled = !state.available.size;
    $('loading').classList.add('hidden');
    $('results-area').setAttribute('aria-busy', 'false');
  }
}

$('ingredient-results').addEventListener('click', event => {
  const button = event.target.closest('button[data-select], button[data-exclude]');
  if (!button) return;
  const available = button.hasAttribute('data-select');
  const id = Number(button.dataset[available ? 'select' : 'exclude']);
  chooseIngredient(id, available ? 'available' : 'excluded');
  $('ingredient-results').querySelector('[data-' + (available ? 'select' : 'exclude') + '="' + id + '"]')?.focus({preventScroll: true});
});
for (const group of ['selected-ingredients', 'excluded-ingredients']) {
  $(group).addEventListener('click', event => {
    if (state.busy) return;
    const move = event.target.closest('button[data-move]');
    const remove = event.target.closest('button[data-remove]');
    if (move) chooseIngredient(Number(move.dataset.move), move.dataset.destination);
    if (remove) {
      state[remove.dataset.group].delete(Number(remove.dataset.remove));
      selectionChanged();
    }
  });
}
$('clear-selection').onclick = () => {
  if (state.busy) return;
  state.available.clear();
  state.excluded.clear();
  $('selection-feedback').textContent = 'Đã xóa lựa chọn. Bộ lọc thời gian và số món được giữ lại.';
  selectionChanged();
};
for (const id of ['max-minutes', 'top-k']) {
  $(id).addEventListener('input', invalidateResults);
}
let timer;
$('ingredient-search').addEventListener('input', event => {
  clearTimeout(timer);
  // Invalidate previous responses immediately, including the debounce interval.
  ++state.searchVersion;
  timer = setTimeout(() => loadIngredients(event.target.value), 250);
});
$('recommend-form').addEventListener('submit', recommend);
window.addEventListener('pagehide', saveSelection);
render();
loadIngredients('', true);
fetch('/api/health').then(response => {
  if (!response.ok) throw Error();
  $('server-status').textContent = 'Kết nối sẵn sàng';
}).catch(() => {
  $('server-status').textContent = 'Chưa kết nối máy chủ';
  $('server-status').classList.add('offline');
});
