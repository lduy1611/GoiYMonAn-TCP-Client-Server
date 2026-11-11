const state = {
  available: new Map(), excluded: new Map(), ingredients: new Map(),
  visible: [], busy: false, searchVersion: 0, datasetVersion: null, view: null,
  mode: 'recommend', offset: 0, advancedOpen: false, requestVersion: 0, controller: null, recommendTimer: null,
  selectionNotice: ''
};
const $ = id => document.getElementById(id);
const validRecipeID = value => Number.isSafeInteger(value) && (value >= 1 && value <= 4294967295 || value > 4294967296 && value <= 8589934591);
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
  const common = {
    ingredient_ids: [...state.available.keys()].sort((a, b) => a - b),
    excluded_ids: [...state.excluded.keys()].sort((a, b) => a - b),
    max_minutes: $('max-minutes').value === '' ? null : Number($('max-minutes').value)
  };
  return state.mode === 'search' ? {
    ...common, query: $('recipe-query').value,
    max_missing: $('max-missing').value === '' ? null : Number($('max-missing').value),
    limit: Number($('search-limit').value), offset: state.offset
  } : {...common, top_k: Number($('top-k').value), algorithm: 'proposed'};
}

function conditionSignature() {
  return JSON.stringify({mode: state.mode, ...searchConditions()});
}

function saveSelection() {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({
      version: 3,
      conditions: {
        available: [...state.available.keys()], excluded: [...state.excluded.keys()],
        maxMinutes: $('max-minutes').value, topK: $('top-k').value,
        mode: state.mode, recipeQuery: $('recipe-query').value,
        maxMissing: $('max-missing').value, limit: $('search-limit').value, offset: state.offset
      },
      view: state.view, searchQuery: $('ingredient-search').value, scrollY: window.scrollY,
      advancedOpen: state.advancedOpen
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

function validPublicIngredientId(id) {
  return Number.isSafeInteger(id) &&
    (id >= 1 && id <= 4294967295 || id > 4294967296 && id <= 8589934591);
}

function validPublicIds(ids, limit = 30) {
  return Array.isArray(ids) && ids.length <= limit && new Set(ids).size === ids.length &&
    ids.every(validPublicIngredientId);
}

function validCachedView(view) {
  if (!view || typeof view !== 'object' || view.signature !== conditionSignature() ||
      view.datasetVersion !== state.datasetVersion) return false;
  if (view.kind === 'error') return typeof view.message === 'string' && view.message.length > 0 && view.message.length <= 500;
  const searching = state.mode === 'search';
  const limit = Number($(searching ? 'search-limit' : 'top-k').value);
  if (view.kind !== 'results' || !Array.isArray(view.items) || view.items.length > limit) return false;
  if (searching && (!Number.isInteger(view.total) || view.total < view.items.length || view.total < 0 ||
      view.limit !== limit || view.offset !== state.offset || typeof view.has_more !== 'boolean' ||
      view.has_more !== (view.offset + view.items.length < view.total) ||
      view.items.length > 0 && view.total < view.offset + view.items.length)) return false;
  const unitScore = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const recipeIds = new Set();
  return view.items.every(item => {
    if (!item || typeof item !== 'object' || !validRecipeID(item.recipe_id) || recipeIds.has(item.recipe_id)) return false;
    recipeIds.add(item.recipe_id);
    return typeof item.title === 'string' && item.title.trim().length > 0 && item.title.length <= 255 &&
      Number.isInteger(item.minutes) && item.minutes >= 1 && item.minutes <= 240 &&
      (!$('max-minutes').value || item.minutes <= Number($('max-minutes').value)) &&
      (searching ? !('score' in item) && !('coverage' in item) && !('input_use' in item)
        : unitScore(item.score) && unitScore(item.coverage) && unitScore(item.input_use)) &&
      validIds(item.matched_ids) && (searching || item.matched_ids.length > 0) && validPublicIds(item.missing_ids, 50) &&
      Number.isInteger(item.missing_count) && item.missing_count === item.missing_ids.length &&
      (!searching || $('max-missing').value === '' || item.missing_count <= Number($('max-missing').value)) &&
      item.matched_ids.every(id => state.available.has(id)) &&
      item.missing_ids.every(id => !state.available.has(id)) &&
      [...item.matched_ids, ...item.missing_ids].every(id => !state.excluded.has(id));
  });
}

function restoreSelection() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (!saved) return;
    if (typeof saved !== 'object' || Array.isArray(saved) || ![undefined, 2, 3].includes(saved.version)) throw Error('Invalid snapshot');
    // Accept the old selection-only format without treating it as cached results.
    const conditions = saved.version >= 2 ? saved.conditions : saved;
    const validNumber = (value, max, min = 1) => typeof value === 'string' && /^\d+$/.test(value) && Number(value) >= min && Number(value) <= max;
    const mode = saved.version === 3 ? conditions?.mode : 'recommend';
    if (!conditions || !validPublicIds(conditions.available) || !validPublicIds(conditions.excluded) ||
        conditions.available.some(id => conditions.excluded.includes(id)) ||
        !['recommend', 'search'].includes(mode) ||
        !(conditions.maxMinutes === '' || validNumber(conditions.maxMinutes, 240)) ||
        mode === 'recommend' && !validNumber(conditions.topK, 20) ||
        mode === 'search' && (typeof conditions.recipeQuery !== 'string' || conditions.recipeQuery.length > 80 ||
          !(conditions.maxMissing === '' || validNumber(conditions.maxMissing, 50, 0)) ||
          !validNumber(conditions.limit, 20) || !Number.isSafeInteger(conditions.offset) || conditions.offset < 0)) throw Error('Invalid conditions');
    state.mode = mode;
    state.advancedOpen = saved.advancedOpen === true;
    state.offset = mode === 'search' ? conditions.offset : 0;
    const available=conditions.available.filter(id=>state.ingredients.has(id));
    const excluded=conditions.excluded.filter(id=>state.ingredients.has(id));
    const staleCount=conditions.available.length-available.length+conditions.excluded.length-excluded.length;
    state.selectionNotice=staleCount
      ?'Danh m\u1ee5c nguy\u00ean li\u1ec7u \u0111\u00e3 thay \u0111\u1ed5i. \u0110\u00e3 b\u1ecf '+staleCount+' l\u1ef1a ch\u1ecdn c\u0169 kh\u00f4ng c\u00f2n trong danh m\u1ee5c User; kh\u00f4ng thay b\u1eb1ng nguy\u00ean li\u1ec7u kh\u00e1c. H\u00e3y ch\u1ecdn l\u1ea1i n\u1ebfu c\u1ea7n.'
      :'';
    state.available = new Map(available.map(id => [id, state.ingredients.get(id)]));
    state.excluded = new Map(excluded.map(id => [id, state.ingredients.get(id)]));
    $('max-minutes').value = conditions.maxMinutes;
    $('top-k').value = validNumber(conditions.topK, 20) ? conditions.topK : '5';
    $('recipe-query').value = typeof conditions.recipeQuery === 'string' && conditions.recipeQuery.length <= 80 ? conditions.recipeQuery : '';
    $('max-missing').value = conditions.maxMissing === '' || validNumber(conditions.maxMissing, 50, 0) ? conditions.maxMissing : '';
    $('search-limit').value = validNumber(conditions.limit, 20) ? conditions.limit : '12';
    syncMode();
    // Upgrade the exact v1.1.2 signature without reusing mismatched results.
    if (saved.version === 2 && saved.view && saved.view.signature === JSON.stringify({
      ingredient_ids: [...state.available.keys()].sort((a, b) => a - b),
      excluded_ids: [...state.excluded.keys()].sort((a, b) => a - b),
      top_k: Number($('top-k').value), algorithm: 'proposed',
      max_minutes: $('max-minutes').value === '' ? null : Number($('max-minutes').value)
    })) saved.view.signature = conditionSignature();
    if (typeof saved.searchQuery === 'string' && saved.searchQuery.length <= 80) $('ingredient-search').value = saved.searchQuery;
    if (saved.version >= 2 && (state.mode === 'search' || state.available.size) && validCachedView(saved.view)) {
      state.view = saved.view;
      if (state.view.kind === 'results') renderRecommendations(state.view.items);
      else showError(state.view.message);
    } else {
      invalidateResults();
    }
    saveSelection();
    if(state.selectionNotice)$('selection-feedback').textContent=state.selectionNotice;
    if (Number.isFinite(saved.scrollY) && saved.scrollY >= 0) requestAnimationFrame(() => window.scrollTo(0, saved.scrollY));
  } catch {
    try { sessionStorage.removeItem(storageKey); } catch { /* Storage is optional. */ }
    state.view = null;
    state.selectionNotice='L\u1ef1a ch\u1ecdn \u0111\u00e3 l\u01b0u kh\u00f4ng c\u00f2n h\u1ee3p l\u1ec7; \u0111\u00e3 x\u00f3a l\u1ef1a ch\u1ecdn c\u0169. Kh\u00f4ng c\u00f3 nguy\u00ean li\u1ec7u n\u00e0o \u0111\u01b0\u1ee3c t\u1ef1 thay th\u1ebf.';
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
    const response = await fetch('/api/ingredients?query=' + encodeURIComponent(query) + '&limit=250');
    const envelope = await response.json();
    if (version !== state.searchVersion) return;
    if (!response.ok || !envelope.ok) throw Error(envelope.error?.message || 'Không tải được nguyên liệu.');
    const items = envelope.data.items || [];
    if (restore) state.datasetVersion = envelope.data.dataset_version;
    items.forEach(item => state.ingredients.set(item.id, item.name));
    state.visible = items;
    if (restore) {
      restoreSelection();
      const entryView = new URLSearchParams(location.search).get('view');
      if (entryView === 'explore') { state.mode = 'search'; $('recipe-query').value = ''; state.offset = 0; }
      else if (entryView === 'fridge') { state.mode = 'recommend'; state.offset = 0; }
      else if (entryView === 'lunch') { state.mode = 'search'; $('recipe-query').value = ''; $('max-minutes').value = '30'; state.offset = 0; }
      document.querySelectorAll('[data-user-tab]').forEach(link => {
        const active = link.dataset.userTab === entryView;
        if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
      });
    }
    render();
    if (restore && state.mode === 'recommend' && state.available.size && !state.view) scheduleRecommendation();
    if (restore && state.selectionNotice) $('selection-feedback').textContent=state.selectionNotice;
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
  state.offset = 0;
  $('pagination').classList.add('hidden');
  $('message').classList.add('hidden');
  $('results').innerHTML = '';
  $('result-count').textContent = '';
  $('result-context').textContent = 'Kết quả dựa trên nguyên liệu và bộ lọc bạn chọn.';
  showEmpty(
    state.mode === 'search' ? 'Bạn muốn tìm món gì?' : state.available.size ? 'Sẵn sàng tìm món phù hợp' : 'Bữa ngon bắt đầu từ đây',
    state.mode === 'search' ? 'Nhập tên món hoặc để trống để duyệt. Không cần chọn nguyên liệu.' : state.available.size ? 'Kết quả tự động cập nhật theo nguyên liệu và bộ lọc.' : 'Chọn ít nhất một nguyên liệu có sẵn để bắt đầu.'
  );
  saveSelection();
}

function chooseIngredient(id, destination) {
  if (!state.ingredients.has(id)) return;
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

// Invalidate immediately, including the debounce window: an older response must
// never update the view, storage, or loading state for newer filters.
function cancelRecommendation() {
  clearTimeout(state.recommendTimer);
  ++state.requestVersion;
  state.controller?.abort();
  state.controller = null;
  state.busy = false;
  $('loading').classList.add('hidden');
  $('results-area').setAttribute('aria-busy', 'false');
}

function scheduleRecommendation() {
  cancelRecommendation();
  state.offset = 0;
  state.view = null;
  $('pagination').classList.add('hidden');
  $('message').classList.add('hidden');
  render();
  if (state.mode !== 'recommend' || !state.available.size) {
    invalidateResults();
    return;
  }
  saveSelection();
  if (!$('recommend-form').checkValidity()) {
    $('selection-feedback').textContent = 'Hãy nhập thời gian từ 1–240 phút và số món từ 1–20.';
    return;
  }
  $('selection-feedback').textContent = state.selectionNotice || 'Đang cập nhật gợi ý theo lựa chọn mới…';
  $('loading').classList.remove('hidden');
  $('results-area').setAttribute('aria-busy', 'true');
  state.recommendTimer = setTimeout(() => recommend(), 300);
}

function selectionChanged() {
  state.selectionNotice='';
  scheduleRecommendation();
}

function syncAdvanced() {
  const searching = state.mode === 'search';
  const expanded = !searching || state.advancedOpen;
  const panel = $('ingredient-panel');
  const toggle = $('advanced-toggle');
  if (!expanded && panel.contains(document.activeElement)) toggle.focus({preventScroll: true});
  toggle.classList.toggle('hidden', !searching);
  toggle.disabled = false;
  toggle.setAttribute('aria-expanded', String(expanded));
  panel.classList.toggle('hidden', !expanded);
  panel.classList.toggle('advanced-content', searching);
  $('advanced-summary').textContent = 'Có sẵn: ' + state.available.size + ' • Loại trừ: ' + state.excluded.size;
}

function syncMode() {
  const searching = state.mode === 'search';
  const slot = $(searching ? 'search-filter-slot' : 'recommend-filter-slot');
  if ($('basic-filters').parentElement !== slot) slot.appendChild($('basic-filters'));
  $('recommend-form').setAttribute('aria-labelledby', searching ? 'search-title' : 'controls-title');
  $('hero-title').innerHTML = searching ? 'Bạn muốn nấu<br>món gì hôm nay?' : 'Có nguyên liệu gì,<br>mình nấu món đó.';
  $('hero-copy').textContent = searching ? 'Tìm công thức theo tên. Thêm bộ lọc khi cần, không cần chọn nguyên liệu để bắt đầu.' : 'Chọn những gì bạn đang có. Tìm món phù hợp và biết rõ cần chuẩn bị thêm gì.';
  const steps = searching ? ['Nhập tên món', 'Lọc theo sở thích', 'Xem cách nấu'] : ['Chọn nguyên liệu', 'Nhận gợi ý tự động', 'Xem cách nấu'];
  $('journey').innerHTML = steps.map((step, index) => '<li><span>' + (index + 1) + '</span> ' + step + '</li>').join('');
  syncAdvanced();
  $('search-fields').classList.toggle('hidden', !searching);
  $('search-limit-field').classList.toggle('hidden', !searching);
  $('recommend-limit-field').classList.toggle('hidden', searching);
  for (const id of ['recipe-query', 'max-missing', 'search-limit']) $(id).disabled = !searching;
  $('top-k').disabled = searching;
  $('recommend-button').classList.toggle('hidden', !searching);
  $('auto-update-help').classList.toggle('hidden', searching);
  $('recommend-button').querySelector('span').textContent = searching ? 'Tìm kiếm món ăn' : 'Tìm món phù hợp';
  const entryView = new URLSearchParams(location.search).get('view');
  const activeTab = entryView === 'lunch' ? 'lunch' : searching ? 'explore' : 'fridge';
  document.querySelectorAll('[data-user-tab]').forEach(link => {
    if (link.dataset.userTab === activeTab) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

function render() {
  syncMode();
  $('selected-count').textContent = state.available.size + '/30';
  $('excluded-count').textContent = state.excluded.size + '/30';
  const chip = (id, name, excluded) => '<span class="chip' + (excluded ? ' excluded' : '') + '"><span>' + esc(name) + '</span>' +
    '<button type="button" data-move="' + id + '" data-destination="' + (excluded ? 'available' : 'excluded') + '" aria-label="' + (excluded ? 'Chuyển sang có sẵn: ' : 'Chuyển sang loại trừ: ') + esc(name) + '" title="' + (excluded ? 'Chuyển sang có sẵn' : 'Chuyển sang loại trừ') + '">' + (excluded ? '↶' : '⊘') + '</button>' +
    '<button type="button" data-remove="' + id + '" data-group="' + (excluded ? 'excluded' : 'available') + '" aria-label="Bỏ chọn: ' + esc(name) + '" title="Bỏ chọn">×</button></span>';
  $('selected-ingredients').className = 'chips' + (state.available.size ? '' : ' empty');
  $('selected-ingredients').innerHTML = state.available.size ? [...state.available].map(([id, name]) => chip(id, name, false)).join('') : 'Chưa chọn nguyên liệu';
  $('excluded-ingredients').className = 'chips' + (state.excluded.size ? '' : ' empty');
  $('excluded-ingredients').innerHTML = state.excluded.size ? [...state.excluded].map(([id, name]) => chip(id, name, true)).join('') : 'Không loại trừ nguyên liệu nào';
  $('recommend-button').disabled = state.busy || state.mode === 'recommend' && !state.available.size;
  $('clear-selection').disabled = !(state.available.size + state.excluded.size);
  $('submit-help').textContent = state.mode === 'search' ? 'Chưa chọn nguyên liệu: tính tất cả nguyên liệu bắt buộc là thiếu. Bạn vẫn có thể tìm hoặc duyệt món.' : state.available.size
    ? 'Bạn có thể đổi bộ lọc để tự động cập nhật gợi ý.'
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
  $('pagination').classList.add('hidden');
  state.view = {kind: 'error', signature: conditionSignature(), datasetVersion: state.datasetVersion, message};
  saveSelection();
}

function showEmpty(message, detail) {
  $('empty-state').classList.remove('hidden');
  $('empty-state').querySelector('h3').textContent = message;
  $('empty-state').querySelector('p').textContent = detail;
}

function ingredientTags(ids) {
  return ids.map(id => '<span class="ingredient-tag">' + esc(state.ingredients.get(id) || (id > 4294967296 ? 'Nguyên liệu chưa có trong danh mục User' : 'Nguyên liệu #' + id)) + '</span>').join('');
}

function renderRecommendations(items) {
  const body = searchConditions();
  const searching = state.mode === 'search';
  $('message').classList.add('hidden');
  $('empty-state').classList.add('hidden');
  $('results').innerHTML = '';
  $('result-count').textContent = searching ? state.view.total + ' món · ' + items.length + ' trên trang' : items.length + ' món';
  $('result-context').textContent = (searching ? 'Tìm theo tên' + (body.query ? ': ' + body.query : ': tất cả món') + ' · ' : '') + state.available.size + ' nguyên liệu có sẵn · ' + state.excluded.size + ' loại trừ' +
    (body.max_minutes ? ' · Tối đa ' + body.max_minutes + ' phút' : '') + (searching ? '. Số thiếu chỉ đếm nguyên liệu bắt buộc.' : '. Điểm P1 là điểm xếp hạng, không phải đánh giá chất lượng món ăn.');
  $('pagination').classList.toggle('hidden', !searching || state.view.total <= body.limit && !state.offset);
  if (searching) {
    $('page-label').textContent = 'Trang ' + (Math.floor(state.offset / body.limit) + 1) + ' / ' + Math.max(1, Math.ceil(state.view.total / body.limit));
    $('page-prev').disabled = state.offset === 0;
    $('page-next').disabled = !state.view.has_more;
  }
  if (!items.length) {
    showEmpty('Chưa tìm thấy món phù hợp', searching ? 'Thử tên khác, bỏ bớt bộ lọc hoặc tăng thời gian tối đa.' : 'Thử bỏ bớt nguyên liệu loại trừ hoặc tăng thời gian tối đa.');
  } else {
    $('results').innerHTML = items.map((item, index) =>
      '<article class="recipe-card"><figure class="recipe-media" data-recipe-media data-recipe-id="' + item.recipe_id + '" data-recipe-title="' + esc(item.title) + '"></figure><div class="recipe-top"><span class="recipe-rank">' + (searching ? 'Kết quả ' : 'Gợi ý ') + String((searching ? state.offset : 0) + index + 1).padStart(2, '0') + '</span>' + (searching ? '' : '<span class="score" title="Điểm xếp hạng P1 trên thang 1">P1 · ' + Number(item.score).toFixed(2) + '</span>') + '</div>' +
      '<h3><a href="/recipes/' + item.recipe_id + '">' + esc(item.title) + '</a></h3><div class="meta-row"><span>◷ ' + esc(item.minutes) + ' phút</span><span>Thiếu ' + esc(item.missing_count) + ' nguyên liệu bắt buộc</span></div>' +
      '<div class="card-description"><div class="tag-label">Đã có · ' + item.matched_ids.length + '</div><div class="id-list">' + (ingredientTags(item.matched_ids) || 'Chưa có nguyên liệu bắt buộc nào') + '</div>' +
      '<div class="tag-label missing">Còn thiếu · ' + esc(item.missing_count) + '</div><div class="id-list missing">' + (ingredientTags(item.missing_ids) || 'Đã đủ nguyên liệu bắt buộc') + '</div></div>' +
      '<a class="detail-link" href="/recipes/' + item.recipe_id + '">Xem công thức <span aria-hidden="true">→</span></a></article>'
    ).join('');
    window.RecipeImages?.mount($('results'));
  }
}

async function recommend(event, offset = 0) {
  event?.preventDefault();
  // Enter in recommendation mode follows the same debounce path.
  if (event && state.mode === 'recommend') { scheduleRecommendation(); return; }
  if (state.mode === 'recommend' && !state.available.size || !$('recommend-form').checkValidity()) return;
  cancelRecommendation();
  const version = state.requestVersion;
  const controller = new AbortController();
  state.controller = controller;
  state.offset = state.mode === 'search' ? offset : 0;
  const mode = state.mode;
  const signature = conditionSignature();
  const isCurrent = () => version === state.requestVersion && signature === conditionSignature();
  state.busy = true;
  state.view = null;
  $('recommend-button').disabled = true;
  $('loading').classList.remove('hidden');
  $('message').classList.add('hidden');
  $('results-area').setAttribute('aria-busy', 'true');
  $('pagination').classList.add('hidden');
  saveSelection();
  try {
    const body = searchConditions();
    const response = await fetch(mode === 'search' ? '/api/search' : '/api/recommend', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      signal: controller.signal
    });
    const envelope = await response.json();
    if (!isCurrent()) return;
    if (!response.ok || !envelope.ok) throw Error(envelope.error?.code === 'UNKNOWN_OPERATION' && mode === 'search' ? 'TCP Server chưa hỗ trợ tìm kiếm. Hãy cập nhật server lên v1.2.' : envelope.error?.message || 'Không thể lấy kết quả. Hãy thử lại.');
    state.view = {
      kind: 'results', signature,
      datasetVersion: envelope.data.dataset_version, items: envelope.data.items,
      ...(mode === 'search' ? {total: envelope.data.total, limit: envelope.data.limit, offset: envelope.data.offset, has_more: envelope.data.has_more} : {})
    };
    if (!validCachedView(state.view)) throw Error('Dữ liệu gợi ý không hợp lệ hoặc đã thay đổi. Hãy tải lại trang và tìm lại.');
    renderRecommendations(state.view.items);
    saveSelection();
  } catch (error) {
    if (isCurrent() && error.name !== 'AbortError') showError(readableError(error));
  } finally {
    if (isCurrent()) {
      state.busy = false;
      state.controller = null;
      // Keep selection DOM/focus intact when only results changed.
      $('recommend-button').disabled = false;
      $('selection-feedback').textContent = state.selectionNotice || (state.view?.kind === 'error' ? 'Lựa chọn được giữ lại. Đổi bộ lọc để thử lại.' : 'Đã cập nhật gợi ý theo nguyên liệu và bộ lọc.');
      $('loading').classList.add('hidden');
      $('results-area').setAttribute('aria-busy', 'false');
    }
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
  state.available.clear();
  state.excluded.clear();
  $('selection-feedback').textContent = 'Đã xóa lựa chọn. Bộ lọc thời gian và số món được giữ lại.';
  selectionChanged();
};
for (const id of ['max-minutes', 'top-k', 'recipe-query', 'max-missing', 'search-limit']) {
  $(id).addEventListener('input', selectionChanged);
}
$('page-prev').onclick = event => recommend(event, Math.max(0, state.offset - Number($('search-limit').value)));
$('page-next').onclick = event => recommend(event, state.offset + Number($('search-limit').value));
$('advanced-toggle').onclick = () => {
  state.advancedOpen = !state.advancedOpen;
  syncAdvanced();
  saveSelection();
};
let timer;
$('ingredient-search').addEventListener('input', event => {
  clearTimeout(timer);
  // Invalidate previous responses immediately, including the debounce interval.
  ++state.searchVersion;
  timer = setTimeout(() => loadIngredients(event.target.value), 250);
});
$('recommend-form').addEventListener('submit', recommend);
window.addEventListener('pagehide', () => { saveSelection(); cancelRecommendation(); });
window.addEventListener('pageshow', event => {
  if (event.persisted && state.mode === 'recommend' && state.available.size && !state.view) scheduleRecommendation();
});
render();
loadIngredients('', true);
fetch('/api/health').then(response => {
  if (!response.ok) throw Error();
  $('server-status').textContent = 'Kết nối sẵn sàng';
}).catch(() => {
  $('server-status').textContent = 'Chưa kết nối máy chủ';
  $('server-status').classList.add('offline');
});
