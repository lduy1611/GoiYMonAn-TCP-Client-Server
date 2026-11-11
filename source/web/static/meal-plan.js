(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const key = 'goiy-meal-plan-v1';
  const returnPath = location.pathname === '/meal-plan/v1' ? '/meal-plan/v1' : '/meal-plan';
  const slots = ['main', 'vegetable', 'soup'];
  const labels = {main: 'Món mặn', vegetable: 'Món rau', soup: 'Món canh'};
  const fields = {'meal-max-minutes': ['max_minutes', 1, 240], 'meal-max-total': ['max_total_minutes', 1, 720], 'meal-max-missing': ['max_missing', 0, 50]};
  const emptyHistory = () => Object.fromEntries(slots.map(slot => [slot, []]));
  const state = {names: new Map(), selected: new Set(), excluded: new Set(), dataset: null,
    ready: false, busy: false, sequence: 0, controller: null, view: null, retry: null, history: emptyHistory()};
  const classHint = document.body.dataset.classificationVersion;
  const esc = value => { const el = document.createElement('span'); el.textContent = String(value); return el.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;'); };
  const text = (v, max = 255) => typeof v === 'string' && v.trim().length > 0 && v.length <= max;
  const integer = (v, low, high) => Number.isSafeInteger(v) && v >= low && v <= high;
  const same = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(v => b.includes(v));
  const ids = (a, max = 50) => Array.isArray(a) && a.length <= max && new Set(a).size === a.length && a.every(id => Number.isSafeInteger(id) && state.names.has(id));
  const roleList = list => Array.isArray(list) && list.length <= 3 && new Set(list).size === list.length && list.every(slot => slots.includes(slot));
  const conditions = () => ({ingredient_ids: [...state.selected].sort((a,b) => a-b), excluded_ids: [...state.excluded].sort((a,b) => a-b),
    ...Object.fromEntries(Object.entries(fields).map(([id, [name]]) => [name, $(id).value === '' ? null : Number($(id).value)]))});
  const signature = c => JSON.stringify(c);

  function validConditions(c) {
    return c && typeof c === 'object' && !Array.isArray(c) &&
      Object.keys(c).length === 5 && ['ingredient_ids','excluded_ids',...Object.values(fields).map(f => f[0])].every(k => k in c) &&
      ids(c.ingredient_ids, 30) && ids(c.excluded_ids, 30) && !c.ingredient_ids.some(id => c.excluded_ids.includes(id)) &&
      Object.values(fields).every(([name, low, high]) => c[name] === null || integer(c[name], low, high));
  }

  function validData(d, c) {
    if (!d || d.dataset_version !== state.dataset || !text(d.classification_version,80) || d.algorithm !== 'meal-plan-v1' ||
        !roleList(d.changed_slots) || !Array.isArray(d.warnings) || d.warnings.length > 2 ||
        !d.warnings.every(w => ['PARTIAL_REGENERATION','NO_COMPLETE_MEAL_PLAN','HISTORY_RECYCLED'].includes(w))) return false;
    if (d.plan === null) return d.changed_slots.length === 0 && d.warnings.includes('NO_COMPLETE_MEAL_PLAN') &&
      d.reason && text(d.reason.code,80) && text(d.reason.message,500) && roleList(d.reason.slots);
    const p = d.plan;
    if (!p || d.reason !== null || !Array.isArray(p.items) || p.items.length !== 3 ||
        new Set(p.items.map(i => i?.recipe_id)).size !== 3 || !roleList(p.items.map(i => i?.slot)) ||
        !ids(p.required_ids) || !ids(p.matched_ids) || !ids(p.missing_ids) || !ids(p.optional_missing_ids) ||
        p.time_basis !== 'sum_of_recipe_minutes' || p.missing_count !== p.missing_ids.length ||
        !integer(p.total_minutes,3,720) || c.max_total_minutes !== null && p.total_minutes > c.max_total_minutes ||
        c.max_missing !== null && p.missing_count > c.max_missing) return false;
    const validItem = i => Number.isSafeInteger(i.recipe_id) && i.recipe_id > 0 && text(i.title) && integer(i.minutes,1,240) &&
      (c.max_minutes === null || i.minutes <= c.max_minutes) && ids(i.matched_ids) && ids(i.missing_ids) &&
      i.missing_count === i.missing_ids.length && i.matched_ids.every(id => c.ingredient_ids.includes(id)) &&
      i.missing_ids.every(id => !c.ingredient_ids.includes(id) && !c.excluded_ids.includes(id));
    if (!p.items.every(validItem) || p.items.reduce((sum,i) => sum+i.minutes,0) !== p.total_minutes ||
        !same(p.matched_ids, [...new Set(p.items.flatMap(i => i.matched_ids))]) ||
        !same(p.missing_ids, [...new Set(p.items.flatMap(i => i.missing_ids))]) ||
        !same(p.required_ids, [...p.matched_ids,...p.missing_ids])) return false;
    const recipeIDs = p.items.map(i => i.recipe_id);
    const validateShopping = (list, required) => Array.isArray(list) && list.length <= 50 &&
      new Set(list.map(i => i?.ingredient_id)).size === list.length && list.every(i => i && state.names.get(i.ingredient_id) === i.name &&
        !c.ingredient_ids.includes(i.ingredient_id) && !c.excluded_ids.includes(i.ingredient_id) &&
        Array.isArray(i.uses) && i.uses.length >= 1 && i.uses.length <= 3 && new Set(i.uses.map(u => u?.recipe_id)).size === i.uses.length &&
        i.uses.every(u => u && recipeIDs.includes(u.recipe_id) && (u.quantity === null || typeof u.quantity === 'string' && u.quantity.length <= 255) && typeof u.is_required === 'boolean') &&
        i.uses.some(u => u.is_required) === required);
    return validateShopping(p.shopping_list,true) && validateShopping(p.optional_shopping_list,false) &&
      same(p.shopping_list.map(i => i.ingredient_id),p.missing_ids) &&
      same(p.optional_shopping_list.map(i => i.ingredient_id),p.optional_missing_ids) &&
      !p.optional_missing_ids.some(id => p.required_ids.includes(id));
  }

  function save() {
    try {
      const c = conditions();
      if (!validConditions(c)) { sessionStorage.removeItem(key); return; }
      sessionStorage.setItem(key, JSON.stringify({version:2, conditions:c, view:state.view, history:state.history, scrollY:window.scrollY}));
    } catch { try { sessionStorage.removeItem(key); } catch { /* Storage is optional. */ } }
  }

  function message(value = '', error = false) {
    $('meal-message').textContent = value;
    $('meal-message').classList.toggle('hidden', !value);
    $('meal-message').classList.toggle('error', error);
    $('meal-message').setAttribute('role', error ? 'alert' : 'status');
  }

  function controls() {
    $('meal-generate').disabled = !state.ready || state.busy;
    $('meal-regenerate').disabled = state.busy || !state.view?.data.plan;
    $('meal-retry').disabled = state.busy || !state.ready;
    $('meal-loading').classList.toggle('hidden', !state.busy);
    $('meal-results').setAttribute('aria-busy', String(state.busy));
    for (const button of $('meal-cards').querySelectorAll('button')) button.disabled = state.busy;
    for (const id of ['meal-ingredient-search',...Object.keys(fields)]) $(id).disabled = !state.ready;
  }

  const fold = value => value.toLowerCase().replace(/đ/g,'d').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  function picker() {
    const query = fold($('meal-ingredient-search').value.trim());
    $('meal-ingredients').innerHTML = [...state.names].filter(([,name]) => fold(name).includes(query)).map(([id,name]) =>
      '<div class="ingredient-row"><span class="ingredient-name">'+esc(name)+'</span><div class="ingredient-actions">'+
      '<button class="ingredient-action" type="button" data-select="'+id+'" aria-label="Có sẵn: '+esc(name)+'" aria-pressed="'+state.selected.has(id)+'">'+(state.selected.has(id)?'Đã có ✓':'Có sẵn')+'</button>'+
      '<button class="ingredient-action exclude" type="button" data-exclude="'+id+'" aria-label="Loại trừ: '+esc(name)+'" aria-pressed="'+state.excluded.has(id)+'">'+(state.excluded.has(id)?'Đã loại ✓':'Loại trừ')+'</button></div></div>').join('') || '<p class="field-help">Không tìm thấy nguyên liệu.</p>';
    for (const [group, list] of [['selected',state.selected],['excluded',state.excluded]]) {
      $('meal-'+group+'-count').textContent = list.size+'/30';
      $('meal-'+group).innerHTML = [...list].map(id => '<span class="chip'+(group==='excluded'?' excluded':'')+'"><span>'+esc(state.names.get(id))+'</span><button type="button" data-remove="'+id+'" data-group="'+group+'" aria-label="Bỏ chọn '+esc(state.names.get(id))+'">×</button></span>').join('');
    }
  }

  function render() {
    const p = state.view?.data.plan;
    $('meal-cards').innerHTML = '';
    $('meal-empty').classList.toggle('hidden', !!p);
    for (const id of ['meal-summary','meal-shopping','meal-regenerate']) $(id).classList.toggle('hidden', !p);
    $('meal-shopping-required').replaceChildren();
    $('meal-shopping-optional').replaceChildren();
    if (!p) { controls(); return; }
    $('meal-summary').textContent = '3 món · '+p.total_minutes+' phút cộng theo công thức · Cần mua '+p.missing_count+' loại bắt buộc. Chưa tính nấu song song.';
    $('meal-cards').innerHTML = slots.map(slot => {
      const i = p.items.find(item => item.slot === slot);
      return '<article class="recipe-card" data-meal-slot="'+slot+'" data-recipe-id="'+i.recipe_id+'"><figure class="recipe-media" data-recipe-media data-recipe-id="'+i.recipe_id+'" data-recipe-title="'+esc(i.title)+'"></figure>'+
        '<span class="meal-slot">'+labels[slot]+'</span><h3><a href="/recipes/'+i.recipe_id+'?return_to=' + encodeURIComponent(returnPath) + '">'+esc(i.title)+'</a></h3><div class="meta-row">◷ '+i.minutes+' phút</div>'+
        '<p class="meal-missing">'+(i.missing_count?'Còn thiếu '+i.missing_count+' loại bắt buộc: '+i.missing_ids.map(id => esc(state.names.get(id))).join(', '):'Đã có đủ loại nguyên liệu bắt buộc')+'</p>'+
        '<div class="meal-card-actions"><a class="detail-link" href="/recipes/'+i.recipe_id+'?return_to=' + encodeURIComponent(returnPath) + '">Xem công thức →</a><button class="retry-button" type="button" data-replace="'+slot+'" aria-label="Đổi '+labels[slot].toLowerCase()+'">Đổi món ↻</button></div></article>';
    }).join('');
    window.RecipeImages?.mount($('meal-cards'));
    const titles = new Map(p.items.map(i => [i.recipe_id,i.title]));
    for (const [id,list] of [['meal-shopping-required',p.shopping_list],['meal-shopping-optional',p.optional_shopping_list]]) {
      $(id).innerHTML = list.length ? list.map(i => '<div class="shopping-entry" data-ingredient-id="'+i.ingredient_id+'"><strong>'+esc(i.name)+'</strong><ul>'+i.uses.map(u => '<li>'+esc(titles.get(u.recipe_id))+': '+esc(u.quantity || 'chưa ghi định lượng')+(u.is_required?'':' (tùy chọn)')+'</li>').join('')+'</ul></div>').join('') : '<p class="field-help">Không cần mua thêm trong nhóm này.</p>';
    }
    controls();
  }

  function invalidate() {
    ++state.sequence;
    state.controller?.abort();
    state.busy = false;
    state.view = null;
    state.history = emptyHistory();
    state.retry = null;
    $('meal-retry').classList.add('hidden');
    message('Điều kiện đã thay đổi. Hãy tạo mâm mới để cập nhật món và danh sách mua.');
    render();
    save();
  }

  function restore() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(key));
      if (!saved) return;
      if (![1,2].includes(saved.version) || !validConditions(saved.conditions)) throw Error('snapshot');
      const c = saved.conditions;
      state.selected = new Set(c.ingredient_ids);
      state.excluded = new Set(c.excluded_ids);
      for (const [id,[name]] of Object.entries(fields)) $(id).value = c[name] ?? '';
      const v = saved.view;
      if (v) {
        if (v.signature === signature(c) && classHint && v.data?.classification_version === classHint && validData(v.data,c)) {
          state.view = v;
          const h = saved.history;
          const validHistory = h && typeof h === 'object' && !Array.isArray(h) && Object.keys(h).length === 3 && slots.every(slot =>
            Array.isArray(h[slot]) && h[slot].length <= 50 && new Set(h[slot]).size === h[slot].length &&
            h[slot].every(id => Number.isSafeInteger(id) && id > 0)) && slots.reduce((n,s) => n+h[s].length,0) <= 50 &&
            new Set(slots.flatMap(s => h[s])).size === slots.reduce((n,s) => n+h[s].length,0) &&
            (v.data.plan?.items || []).every(item => h[item.slot].includes(item.recipe_id));
          state.history = saved.version === 2 && validHistory ? h : emptyHistory();
          for (const item of v.data.plan?.items || []) if (!state.history[item.slot].includes(item.recipe_id)) state.history[item.slot].push(item.recipe_id);
          if (v.data.plan === null) message(v.data.reason.message);
          else {
            const notices = [];
            if (v.data.warnings.includes('PARTIAL_REGENERATION')) notices.push('Chỉ đổi được một phần mâm: '+v.data.changed_slots.map(s => labels[s]).join(', ')+'.');
            if (v.data.warnings.includes('HISTORY_RECYCLED')) notices.push('Đã hết món chưa dùng phù hợp; bắt đầu vòng mới cho các món đã duyệt.');
            if (notices.length) message(notices.join(' '));
          }
        } else message('Kết quả lưu không còn hợp lệ hoặc phiên bản dữ liệu đã đổi. Hãy tạo mâm mới.');
      }
      if (Number.isFinite(saved.scrollY) && saved.scrollY >= 0) requestAnimationFrame(() => window.scrollTo(0,saved.scrollY));
    } catch {
      state.view = null;
      state.history = emptyHistory();
      state.selected.clear(); state.excluded.clear();
      for (const id of Object.keys(fields)) $(id).value = '';
      try { sessionStorage.removeItem(key); } catch { /* Storage is optional. */ }
      message('Không thể khôi phục dữ liệu lưu. Bạn có thể tạo mâm mới.');
    }
  }

  async function load() {
    state.ready = false;
    state.view = null;
    state.history = emptyHistory();
    render();
    $('meal-ingredients').setAttribute('aria-busy','true');
    $('meal-load-retry').classList.add('hidden');
    try {
      const response = await fetch('/api/ingredients?limit=250');
      const envelope = await response.json();
      const data = envelope.data;
      if (!response.ok || !envelope.ok || !text(data?.dataset_version) || !Array.isArray(data.items) || data.items.length > 250 ||
          !data.items.every(i => i && Number.isSafeInteger(i.id) && i.id > 0 && text(i.name)) || new Set(data.items.map(i => i.id)).size !== data.items.length) throw Error('Không tải được danh sách nguyên liệu.');
      state.names = new Map(data.items.map(i => [i.id,i.name]));
      state.dataset = data.dataset_version;
      restore();
      state.ready = true;
      picker(); render();
    } catch (error) {
      message(error instanceof TypeError ? 'Không kết nối được máy chủ. Hãy thử tải nguyên liệu lại.' : error.message,true);
      $('meal-load-retry').classList.remove('hidden');
    } finally {
      $('meal-ingredients').setAttribute('aria-busy','false');
      controls();
    }
  }

  async function generate(slot = null) {
    if (state.busy || !state.ready || !$('meal-form').reportValidity()) return;
    const c = conditions(), sig = signature(c), previous = state.view?.signature === sig ? state.view.data.plan : null;
    if (!validConditions(c) || slot && !previous) return;
    const payload = {...c};
    if (slot) {
      payload.current_plan = Object.fromEntries(previous.items.map(i => [i.slot,i.recipe_id]));
      payload.locked_slots = slot === 'all' ? [] : slots.filter(s => s !== slot);
      payload.avoid_recipe_ids = Object.fromEntries(slots.map(s => [s, [...state.history[s]]]));
    }
    const token = ++state.sequence;
    state.controller = new AbortController();
    state.busy = true;
    state.retry = {slot, signature:sig};
    $('meal-retry').classList.add('hidden');
    message(); controls();
    try {
      const response = await fetch('/api/meal-plan', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload), signal:state.controller.signal});
      const envelope = await response.json();
      if (token !== state.sequence || sig !== signature(conditions())) return;
      if (!response.ok || envelope.ok !== true) {
        const code = envelope.error?.code;
        throw Error(code === 'UNKNOWN_OPERATION' ? 'TCP Server chưa hỗ trợ mâm cơm. Hãy khởi động phiên bản mới.' :
          code === 'TIMEOUT' ? 'TCP Server phản hồi quá lâu. Hãy thử lại.' :
          code === 'UPSTREAM_UNAVAILABLE' ? 'Không kết nối được TCP Server. Hãy kiểm tra máy chủ rồi thử lại.' :
          envelope.error?.message || 'Không thể tạo mâm. Hãy thử lại.');
      }
      const d = envelope.data;
      if (text(d?.dataset_version) && d.dataset_version !== state.dataset) {
        state.view = null; render();
        throw Error('Phiên bản dữ liệu đã thay đổi. Hãy tải lại trang trước khi tạo mâm mới.');
      }
      if (envelope.version !== 1 || typeof envelope.request_id !== 'string' || !validData(d,c)) throw Error('Dữ liệu mâm cơm không hợp lệ. Hãy tải lại trang và thử lại.');
      if (d.plan && slot) {
        const changed = slots.filter(s => d.plan.items.find(i => i.slot===s).recipe_id !== payload.current_plan[s]);
        if (!changed.length || !same(changed,d.changed_slots) || payload.locked_slots.some(s => changed.includes(s))) throw Error('Phản hồi đổi món không hợp lệ; mâm hiện tại được giữ lại.');
      } else if (d.plan && d.changed_slots.length) throw Error('Phản hồi tạo mâm không hợp lệ.');
      if (!d.plan && previous) {
        message(d.reason.message+' Mâm hiện tại được giữ lại.');
      } else {
        if (!slot) state.history = emptyHistory();
        for (const item of d.plan?.items || []) {
          const seen = state.history[item.slot];
          if (slot && d.changed_slots.includes(item.slot) && seen.includes(item.recipe_id)) {
            // Start a new cycle with the previous and new dish, preventing an immediate bounce.
            state.history[item.slot] = [payload.current_plan[item.slot], item.recipe_id];
          } else if (!seen.includes(item.recipe_id)) seen.push(item.recipe_id);
        }
        state.view = {signature:sig,data:d};
        render();
        if (!d.plan) message(d.reason.message);
        else if (slot) {
          const parts = [d.warnings.includes('PARTIAL_REGENERATION') ? 'Chỉ đổi được một phần mâm: '+d.changed_slots.map(s => labels[s]).join(', ')+'. Các món còn lại được giữ nguyên.' : 'Đã đổi '+d.changed_slots.map(s => labels[s].toLowerCase()).join(', ')+'.'];
          if (d.warnings.includes('HISTORY_RECYCLED')) parts.push('Đã hết món chưa dùng phù hợp với bộ lọc; bắt đầu vòng mới.');
          message(parts.join(' '));
        }
        else message('Đã tạo mâm cơm. Danh sách mua đã được cập nhật.');
        if (slot && slot !== 'all') $('meal-cards').querySelector('[data-replace="'+slot+'"]')?.focus({preventScroll:true});
        else $('meal-results-title').focus({preventScroll:true});
      }
      state.retry = null;
      save();
    } catch (error) {
      if (token !== state.sequence || error.name === 'AbortError') return;
      message(error instanceof TypeError ? 'Không kết nối được máy chủ. Hãy thử lại.' : error instanceof SyntaxError ? 'Máy chủ trả dữ liệu không hợp lệ. Hãy thử lại.' : error.message,true);
      $('meal-retry').classList.remove('hidden');
    } finally {
      if (token === state.sequence) { state.busy = false; controls(); }
    }
  }

  $('meal-form').addEventListener('submit', event => { event.preventDefault(); generate(); });
  $('meal-regenerate').onclick = () => generate('all');
  $('meal-cards').addEventListener('click', event => { const b = event.target.closest('[data-replace]'); if (b) generate(b.dataset.replace); });
  $('meal-retry').onclick = () => { if (state.retry?.signature === signature(conditions())) generate(state.retry.slot); };
  $('meal-load-retry').onclick = load;
  $('meal-ingredient-search').addEventListener('input', picker);
  for (const id of Object.keys(fields)) $(id).addEventListener('input', invalidate);
  $('meal-ingredients').addEventListener('click', event => {
    const b = event.target.closest('[data-select], [data-exclude]');
    if (!b || !state.ready) return;
    const selected = b.hasAttribute('data-select'), id = Number(b.dataset[selected?'select':'exclude']);
    const target = selected ? state.selected : state.excluded, other = selected ? state.excluded : state.selected;
    if (target.has(id)) target.delete(id);
    else {
      if (target.size >= 30) { $('meal-feedback').textContent = 'Mỗi nhóm tối đa 30 nguyên liệu.'; return; }
      other.delete(id); target.add(id);
    }
    invalidate(); picker();
    $('meal-ingredients').querySelector('[data-'+(selected?'select':'exclude')+'="'+id+'"]')?.focus({preventScroll:true});
  });
  for (const group of ['selected','excluded']) $('meal-'+group).addEventListener('click', event => {
    const b = event.target.closest('[data-remove]');
    if (!b) return;
    state[group].delete(Number(b.dataset.remove)); invalidate(); picker();
  });
  window.addEventListener('pagehide', () => { save(); ++state.sequence; state.controller?.abort(); state.busy=false; });
  window.addEventListener('pageshow', event => { if (event.persisted) load(); });
  load();
})();
