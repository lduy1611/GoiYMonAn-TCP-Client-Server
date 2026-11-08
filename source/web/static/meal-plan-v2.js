(() => {
  'use strict';
  const $ = id => document.getElementById(id), key = 'goiy-meal-plan-v2';
  const groups = ['main','vegetable','soup'];
  const preferenceCodes={diet:['non_vegetarian','vegetarian'],region:['north','central','south'],occasion:['daily','weekend','guests','birthday','tet','ancestral']};
  const labels = {main:'Món chính', vegetable:'Món rau', soup:'Món canh'};
  const fields = {'meal-max-minutes':['max_minutes',1,240], 'meal-max-total':['max_total_minutes',1,1440], 'meal-max-missing':['max_missing',0,50]};
  const emptyHistory = () => Object.fromEntries(groups.map(g => [g,[]]));
  const state = {names:new Map(), selected:new Set(), excluded:new Set(), pins:new Set(), history:emptyHistory(),
    dataset:null, ready:false, busy:false, sequence:0, controller:null, view:null, retry:null, notice:'', error:false,
    people:4, calculation:{sequence:0,controller:null,timer:null,deadline:null}, preferences:{}, metadata:null,
    filterSequence:0, filterController:null, autoTimer:null, autoPending:false, generationDeadline:null};
  const esc = v => { const e=document.createElement('span'); e.textContent=String(v ?? ''); return e.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); };
  const integer = (v,a,b) => Number.isSafeInteger(v) && v>=a && v<=b;
  const recipeID = v => integer(v,1,4294967295) || integer(v,4294967297,8589934591);
  const text = (v,n=255) => typeof v==='string' && v.trim().length>0 && v.length<=n;
  const slot = v => typeof v==='string' && /^(main|vegetable|soup):[12]$/.test(v);
  const unique = a => Array.isArray(a) && new Set(a).size===a.length;
  const ids = (a,n=50,names=state.names) => unique(a) && a.length<=n && a.every(i=>integer(i,1,8589934591)&&i!==4294967296&&names.has(i));
  const same = (a,b) => unique(a)&&unique(b)&&a.length===b.length&&a.every(i=>b.includes(i));
  const signature = c => JSON.stringify(c);
  const keysFor = counts => groups.flatMap(g=>Array.from({length:counts[g]},(_,i)=>g+':'+(i+1)));
  // Display preview only; TCP independently derives and validates the same policy.
  const countsForPeople=n=>Object.fromEntries(groups.map((g,i)=>[g,(n<=2?[1,1,0]:n<=4?[1,1,1]:n<=6?[2,1,1]:n<=8?[2,2,1]:[2,2,2])[i]]));
  const sameCounts=(a,b)=>groups.every(g=>a?.[g]===b?.[g]);
  const layoutMismatch=()=>!!state.view?.data.plan&&!sameCounts(state.view.conditions.counts,countsForPeople(state.people));
  const conditions = () => ({ingredient_ids:[...state.selected].sort((a,b)=>a-b), excluded_ids:[...state.excluded].sort((a,b)=>a-b),
    ...Object.fromEntries(Object.entries(fields).map(([id,[name]])=>[name,$(id).value===''?null:Number($(id).value)])),
    counts:countsForPeople(state.people),
    ...(Object.keys(state.preferences).length?{preferences:{...state.preferences}}:{})});
  const validPreferences=p=>p&&typeof p==='object'&&!Array.isArray(p)&&Object.keys(p).length<=3&&
    Object.entries(p).every(([k,v])=>preferenceCodes[k]?.includes(v));
  function validConditions(c) {
    return c && typeof c==='object' && Object.keys(c).length===(c.preferences?7:6) &&
      (!c.preferences||validPreferences(c.preferences)) && ids(c.ingredient_ids,30) && ids(c.excluded_ids,30) &&
      !c.ingredient_ids.some(i=>c.excluded_ids.includes(i)) && Object.values(fields).every(([name,a,b])=>c[name]===null||integer(c[name],a,b)) &&
      c.counts && Object.keys(c.counts).length===3 && groups.every(g=>integer(c.counts[g],0,2)) && keysFor(c.counts).length>0;
  }
  function planNames(d) {
    const names=new Map(state.names);
    for (const list of [d?.plan?.shopping_list,d?.plan?.optional_shopping_list]) {
      if(!Array.isArray(list)||list.length>50)continue;
      for(const i of list)if(integer(i?.ingredient_id,4294967297,8589934591)&&text(i.name)&&!names.has(i.ingredient_id))names.set(i.ingredient_id,i.name);
    }
    return names;
  }
  function validClassificationVersion(version,base) {
    if (version===base) return true;
    if (typeof version!=='string'||typeof base!=='string'||!version.startsWith(base)) return false;
    const suffix=version.slice(base.length);
    // The server fingerprints both the approved v2 release and direct Admin
    // catalog overlays. With no active v2 release the current server format
    // contains a double separator before :admin; accept that exact legacy form
    // as well so saved plans and current responses remain readable.
    return [/^:v2:[a-f0-9]{16}$/,/^:v2:[a-f0-9]{16}:admin:[a-f0-9]{12}$/,
      /^:admin:[a-f0-9]{12}$/,/^::admin:[a-f0-9]{12}$/].some(pattern=>pattern.test(suffix));
  }
  function validData(d,c) {
    const names=planNames(d), dataIDs=a=>ids(a,50,names);
    const baseVersion=document.body.dataset.classificationVersion;
    const versionOK=validClassificationVersion(d?.classification_version,baseVersion);
    if (d?.people!==undefined&&(!integer(d.people,1,12)||!sameCounts(d.counts,countsForPeople(d.people))))return false;
    if (c.preferences&&(!validPreferences(d?.preferences)||Object.keys(c.preferences).length!==Object.keys(d.preferences).length||
        !Object.entries(c.preferences).every(([k,v])=>d.preferences[k]===v)||!text(d.metadata_version))) return false;
    if (!d || d.algorithm!=='meal-plan-v2' || d.dataset_version!==state.dataset ||
        !versionOK ||
        !groups.every(g=>d.counts?.[g]===c.counts[g]) || !unique(d.changed_slots) || d.changed_slots.length>6 || !d.changed_slots.every(slot) ||
        !unique(d.warnings) || d.warnings.length>2 || !d.warnings.every(w=>['NO_COMPLETE_MEAL_PLAN','PARTIAL_REGENERATION','HISTORY_RECYCLED'].includes(w))) return false;
    if (d.plan===null) return !d.changed_slots.length && d.warnings.includes('NO_COMPLETE_MEAL_PLAN') && text(d.reason?.code,80) &&
      text(d.reason?.message,500) && Array.isArray(d.reason.suggestions) && d.reason.suggestions.length<=3 && d.reason.suggestions.every(x=>text(x));
    const p=d.plan, expected=keysFor(c.counts);
    if (!p || d.reason!==null || !Array.isArray(p.items) || p.items.length!==expected.length ||
        !same(p.items.map(i=>i?.slot),expected) || !unique(p.items.map(i=>i?.recipe_id)) ||
        !dataIDs(p.required_ids)||!dataIDs(p.matched_ids)||!dataIDs(p.missing_ids)||!dataIDs(p.optional_missing_ids)||
        p.missing_count!==p.missing_ids.length||p.time_basis!=='sum_of_recipe_minutes'||
        !integer(p.total_minutes,1,1440)||c.max_total_minutes!==null&&p.total_minutes>c.max_total_minutes||
        c.max_missing!==null&&p.missing_count>c.max_missing) return false;
    if (!p.items.every(i=>recipeID(i.recipe_id)&&text(i.title)&&integer(i.minutes,1,240)&&
        (c.max_minutes===null||i.minutes<=c.max_minutes)&&dataIDs(i.matched_ids)&&dataIDs(i.missing_ids)&&i.missing_count===i.missing_ids.length&&
        i.matched_ids.every(id=>c.ingredient_ids.includes(id)&&!c.excluded_ids.includes(id))&&
        i.missing_ids.every(id=>!c.ingredient_ids.includes(id)&&!c.excluded_ids.includes(id)))) return false;
    if (p.items.reduce((sum,i)=>sum+i.minutes,0)!==p.total_minutes ||
        !same(p.matched_ids,[...new Set(p.items.flatMap(i=>i.matched_ids))]) ||
        !same(p.missing_ids,[...new Set(p.items.flatMap(i=>i.missing_ids))]) ||
        !same(p.required_ids,[...p.matched_ids,...p.missing_ids])) return false;
    const recipeIDs=p.items.map(i=>i.recipe_id);
    const shopping=(list,required)=>Array.isArray(list)&&list.length<=50&&unique(list.map(i=>i?.ingredient_id))&&list.every(i=>
      names.get(i.ingredient_id)===i.name&&!c.ingredient_ids.includes(i.ingredient_id)&&!c.excluded_ids.includes(i.ingredient_id)&&
      Array.isArray(i.uses)&&i.uses.length>=1&&i.uses.length<=6&&unique(i.uses.map(u=>u?.recipe_id))&&
      i.uses.every(u=>recipeID(u.recipe_id)&&recipeIDs.includes(u.recipe_id)&&(u.quantity===null||typeof u.quantity==='string'&&u.quantity.length<=255)&&typeof u.is_required==='boolean')&&
      i.uses.some(u=>u.is_required)===required);
    return shopping(p.shopping_list,true)&&shopping(p.optional_shopping_list,false)&&
      same(p.shopping_list.map(i=>i.ingredient_id),p.missing_ids)&&same(p.optional_shopping_list.map(i=>i.ingredient_id),p.optional_missing_ids)&&
      !p.optional_missing_ids.some(i=>p.required_ids.includes(i));
  }
  function message(value='',error=false) {
    state.notice=value; state.error=error;
    $('meal-message').textContent=value; $('meal-message').classList.toggle('hidden',!value);
    $('meal-message').classList.toggle('error',error); $('meal-message').setAttribute('role',error?'alert':'status');
  }
  function save() {
    try {
      sessionStorage.setItem(key+'-people',String(state.people));
      const c=conditions(); if (!validConditions(c)) return;
      sessionStorage.setItem(key,JSON.stringify({version:2,conditions:c,view:state.view,pins:[...state.pins],history:state.history,
        publishedNames:[...state.names].filter(([id])=>id>4294967296).slice(0,500),
        notice:state.notice,error:state.error,scrollY:window.scrollY,people:state.people,retry:state.retry,autoPending:state.autoPending}));
    } catch { try {sessionStorage.removeItem(key);} catch {} }
  }
  function cancel() {
    ++state.sequence; state.controller?.abort(); state.controller=null; state.busy=false;
    clearTimeout(state.autoTimer);state.autoTimer=null;
    clearTimeout(state.generationDeadline);state.generationDeadline=null;
  }
  function controls() {
    const p=state.view?.data.plan, dirty=!!p&&!!(state.view.signature!==signature(conditions())||
      state.view.conditions.preferences&&state.metadata&&state.view.data.metadata_version!==state.metadata.metadata_version);
    const working=state.busy||state.autoTimer!==null;
    $('meal-generate').disabled=!state.ready||working;
    $('meal-regenerate').disabled=!p||working;
    $('meal-retry').disabled=!state.ready||working;
    $('meal-loading').classList.toggle('hidden',!working);
    $('meal-results').setAttribute('aria-busy',String(working));
    $('meal-stale').classList.toggle('hidden',!dirty);
    $('meal-stale').textContent=layoutMismatch()?'Mâm đang hiển thị có '+p.items.length+' món, chưa khớp cấu trúc cho '+state.people+' người. Mâm và ghim được giữ; hãy bỏ ghim món xung đột, điều chỉnh số người hoặc thử tạo lại.':
      'Bộ lọc đã đổi. Nhấn Tạo mâm cơm để áp dụng; món ghim được giữ lại.';
    $('meal-shopping').classList.toggle('hidden',!p||dirty);
    portionControls();
    renderFilters();
    for (const id of ['meal-ingredient-search',...Object.keys(fields)]) $(id).disabled=!state.ready;
    for (const b of $('meal-cards').querySelectorAll('[data-replace]')) b.disabled=working||dirty||state.pins.has(b.dataset.replace);
  }
  const choiceEnabled=c=>c.enabled&&(c.code!=='vegetarian'||Array.isArray(c.supported_people)&&c.supported_people.includes(state.people));
  function choiceReason(c) {
    if(c.code!=='vegetarian'||choiceEnabled(c)||!c.enabled)return c.reason;
    return 'Chưa đủ món chay được xác minh cho '+state.people+' người. Hiện có '+c.role_counts.main+' chính, '+c.role_counts.vegetable+' rau, '+c.role_counts.soup+' canh; không tự giảm số món hoặc thay món chưa xác minh.';
  }
  function renderFilters() {
    for (const group of Object.keys(preferenceCodes)) {
      const el=$('meal-pref-'+group), choices=state.metadata?.choices[group]||[], selected=state.preferences[group]||'';
      el.innerHTML='<option value="">Không giới hạn</option>'+choices.map(c=>'<option value="'+esc(c.code)+'"'+(!choiceEnabled(c)?' disabled':'')+'>'+esc(c.label)+(!choiceEnabled(c)?' — chưa đủ dữ liệu':'')+'</option>').join('');
      if (selected&&!choices.some(c=>c.code===selected)) el.add(new Option('Lựa chọn đã lưu — chưa kiểm tra được dữ liệu',selected));
      el.value=selected;
      el.disabled=!state.ready||!selected&&!choices.some(choiceEnabled);
      const picked=choices.find(c=>c.code===selected), supported=choices.filter(choiceEnabled);
      $('meal-pref-'+group+'-help').textContent=picked?choiceReason(picked):
        supported.length?supported.map(c=>c.label+': '+c.recipe_count+' món có bằng chứng thành phần. '+c.reason).join(' ')+
          choices.filter(c=>!choiceEnabled(c)).map(c=>' '+c.label+': '+choiceReason(c)).join(''):
        choices[0]?.reason||'Chưa tải được dữ liệu để sử dụng bộ lọc này.';
    }
  }
  async function loadFilters() {
    const token=++state.filterSequence, dataset=state.dataset;
    state.filterController?.abort(); const controller=new AbortController(); state.filterController=controller;
    const timeout=setTimeout(()=>controller.abort(),9000);
    $('meal-filter-retry').classList.add('hidden'); $('meal-filter-message').classList.add('hidden');
    try {
      const r=await fetch('/api/meal-plan/filters?layout_support=true',{signal:controller.signal}), e=await r.json();
      if(token!==state.filterSequence||dataset!==state.dataset)return;
      const d=e.data;
      if (!r.ok||e.ok!==true||e.version!==1||!text(e.request_id,80)||!d||d.dataset_version!==dataset||!text(d.metadata_version)||
          !d.choices||Object.keys(d.choices).length!==3||!Object.entries(preferenceCodes).every(([g,codes])=>
            Array.isArray(d.choices[g])&&same(d.choices[g].map(c=>c?.code),codes)&&d.choices[g].every(c=>
              text(c.label)&&text(c.reason,500)&&typeof c.enabled==='boolean'&&integer(c.recipe_count,0,Number.MAX_SAFE_INTEGER)&&
              (c.code!=='vegetarian'||unique(c.supported_people)&&c.supported_people.every(n=>integer(n,1,12))&&
                groups.every(g=>integer(c.role_counts?.[g],0,Number.MAX_SAFE_INTEGER)))))) throw Error();
      state.metadata=d;
    } catch {
      if(token!==state.filterSequence)return;
      state.metadata=null;
      $('meal-filter-message').textContent='Chưa tải được dữ liệu bộ lọc. Các lựa chọn đã lưu được giữ; hãy thử lại.';
      $('meal-filter-message').classList.remove('hidden'); $('meal-filter-retry').classList.remove('hidden');
    } finally {clearTimeout(timeout);if(token===state.filterSequence){state.filterController=null;controls();}}
  }
  // Portion requests are independent of meal generation, filters and pins.
  const portionPayload = () => ({recipe_ids:state.view?.data.plan?.items.map(i=>i.recipe_id)||[],people:state.people});
  function portionControls() {
    $('meal-people').value=state.people+' người';
    $('meal-people-minus').disabled=!state.ready||state.people<=1;
    $('meal-people-plus').disabled=!state.ready||state.people>=12;
    const c=countsForPeople(state.people);
    $('meal-structure').textContent='Đề xuất '+keysFor(c).length+' món · '+c.main+' chính + '+c.vegetable+' rau + '+c.soup+' canh';
    $('meal-people-help').textContent='Đổi mốc số món sẽ tự cập nhật mâm; món ghim được giữ nếu phù hợp.';
    $('meal-portions').classList.toggle('hidden',!state.view?.data.plan);
  }
  function cancelPortions() {
    const c=state.calculation;
    ++c.sequence; clearTimeout(c.timer); clearTimeout(c.deadline); c.controller?.abort();
    c.timer=null; c.deadline=null; c.controller=null;
  }
  function portionMessage(value,error=false) {
    const el=$('meal-portions-message'); el.textContent=value;
    el.classList.toggle('error',error); el.setAttribute('role',error?'alert':'status');
  }
  const decimal = v => typeof v==='string'&&/^(?:0|[1-9][0-9]{0,40})(?:\.[0-9]{1,50})?$/.test(v);
  const validAmount = q => q&&decimal(q.quantity_min)&&decimal(q.quantity_max)&&
    ['exact','outward_6dp'].includes(q.precision)&&
    (q.amount_kind==='exact'?decimal(q.quantity_value)&&q.quantity_value===q.quantity_min&&q.quantity_min===q.quantity_max&&q.precision==='exact':
      q.amount_kind==='range'&&q.quantity_value===null&&q.quantity_min!==q.quantity_max);
  function validPortions(d,payload) {
    if (!d||d.dataset_version!==state.dataset||d.calculation_version!=='portion-v1'||d.people!==payload.people||
        JSON.stringify(d.recipe_ids)!==JSON.stringify(payload.recipe_ids)||!['COMPLETE','INCOMPLETE'].includes(d.status)||
        typeof d.totals_complete!=='boolean'||(d.status==='COMPLETE')!==d.totals_complete||
        !Array.isArray(d.recipes)||d.recipes.length!==payload.recipe_ids.length||
        !d.recipes.every((r,i)=>r.recipe_id===payload.recipe_ids[i]&&['COMPLETE','INCOMPLETE'].includes(r.status)&&
          Array.isArray(r.reasons)&&r.reasons.length<=64&&(r.status==='COMPLETE'?r.reasons.length===0:r.reasons.length>0)&&
          r.reasons.every(x=>text(x.code,80)&&text(x.message,500)))||
        d.totals_complete!==d.recipes.every(r=>r.status==='COMPLETE')||
        !Array.isArray(d.known_ingredients)||d.known_ingredients.length>300) return false;
    // V2 ingredient IDs are independent of the legacy ingredient picker IDs.
    return d.known_ingredients.every(i=>integer(i.ingredient_id,1,8589934591)&&text(i.name)&&text(i.unit,80)&&
      text(i.ingredient_form,80)&&['gross','edible','prepared'].includes(i.measurement_basis)&&
      ['consumed','cooking_medium','garnish'].includes(i.purpose)&&validAmount(i)&&
      Array.isArray(i.uses)&&i.uses.length>0&&i.uses.length<=300&&i.uses.every(u=>payload.recipe_ids.includes(u.recipe_id)&&validAmount(u)));
  }
  function renderPortions(data) {
    const titles=new Map(state.view.data.plan.items.map(i=>[i.recipe_id,i.title]));
    const amount=q=>esc(q.amount_kind==='exact'?q.quantity_value:q.quantity_min+'–'+q.quantity_max);
    const basis={gross:'trước sơ chế',edible:'phần ăn được',prepared:'đã chế biến'};
    const purpose={consumed:'dùng trong món',cooking_medium:'dùng để nấu',garnish:'trang trí'};
    portionMessage(data.totals_complete?'Đã tính đủ định lượng cho '+state.people+' người.':
      data.known_ingredients.length?'Mới tính được một phần định lượng cho '+state.people+' người.':'Chưa đủ dữ liệu để tính khẩu phần cho mâm này');
    $('meal-portions-known').innerHTML=data.known_ingredients.length?
      '<h3>'+(data.totals_complete?'Định lượng cho cả mâm':'Định lượng đã tính được — chưa đầy đủ')+'</h3><p class="field-help">Theo dữ liệu đã duyệt. Hãy trừ lượng có sẵn trước khi mua.</p>'+
      data.known_ingredients.map(i=>'<div class="shopping-entry"><strong>'+esc(i.name)+': '+amount(i)+' '+esc(i.unit)+'</strong>'+
        '<p class="field-help">'+esc(i.ingredient_form)+' · '+basis[i.measurement_basis]+' · '+purpose[i.purpose]+(i.precision==='outward_6dp'?' · Khoảng đã làm tròn ra ngoài':'')+'</p><ul>'+
        i.uses.map(u=>'<li>'+esc(titles.get(u.recipe_id))+': '+amount(u)+' '+esc(i.unit)+'</li>').join('')+'</ul></div>').join(''):'';
    $('meal-portions-reasons').innerHTML=data.recipes.filter(r=>r.status==='INCOMPLETE').map(r=>
      '<div class="shopping-entry"><h3>'+esc(titles.get(r.recipe_id))+'</h3><ul>'+r.reasons.map(x=>'<li>'+esc(x.message)+'</li>').join('')+'</ul></div>').join('');
  }
  function queuePortions(delay=300) {
    cancelPortions(); portionControls();
    const c=state.calculation, payload=portionPayload(), sig=signature(payload), token=c.sequence;
    $('meal-portions-known').replaceChildren(); $('meal-portions-reasons').replaceChildren();
    $('meal-portions-retry').classList.add('hidden');
    $('meal-portions').setAttribute('aria-busy',String(!!payload.recipe_ids.length));
    if (!payload.recipe_ids.length) return;
    if(layoutMismatch()) {
      $('meal-portions').setAttribute('aria-busy','false');
      portionMessage('Mâm chưa khớp cấu trúc đề xuất. Hãy xử lý thông báo tạo mâm trước khi tính khẩu phần.');return;
    }
    portionMessage('Đang tính khẩu phần cho '+payload.people+' người…');
    c.timer=setTimeout(async()=>{
      c.timer=null; const controller=new AbortController(); c.controller=controller;
      const current=()=>token===c.sequence&&sig===signature(portionPayload());
      const fail=msg=>{
        if (!current()) return;
        portionMessage(msg,true); $('meal-portions-retry').classList.remove('hidden');
        $('meal-portions').setAttribute('aria-busy','false');
      };
      // Invalidate even if an upstream/mock ignores HTTP cancellation.
      c.deadline=setTimeout(()=>{
        if (!current()) return;
        fail('Tính khẩu phần quá lâu. Hãy thử lại.'); cancelPortions();
      },10000);
      try {
        const response=await fetch('/api/meal-plan/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
        const e=await response.json(); if (!current()) return;
        if (!response.ok||!e.ok) throw Error(e.error?.code==='TIMEOUT'?'Tính khẩu phần quá lâu. Hãy thử lại.':'Chưa thể tính khẩu phần. Hãy thử lại.');
        if (e.version!==1||!text(e.request_id,80)||!validPortions(e.data,payload)) throw Error('Kết quả khẩu phần không hợp lệ. Hãy thử lại.');
        renderPortions(e.data);
      } catch(e) {if (current()) fail(e instanceof TypeError?'Không kết nối được máy chủ để tính khẩu phần. Hãy thử lại.':e instanceof SyntaxError?'Kết quả khẩu phần không hợp lệ. Hãy thử lại.':e.message);}
      finally {if (current()) {clearTimeout(c.deadline);c.deadline=null;c.controller=null;$('meal-portions').setAttribute('aria-busy','false');}}
    },delay);
  }
  function changePeople(delta) {
    const value=state.people+delta; if (!integer(value,1,12)) return;
    const before=countsForPeople(state.people);state.people=value;
    const p=state.view?.data.plan;
    if(layoutMismatch()||!p&&(!sameCounts(before,countsForPeople(value))||state.autoPending)) scheduleLayout();
    else {
      if(state.autoPending){cancel();state.autoPending=false;state.retry=null;message();$('meal-retry').classList.add('hidden');}
      controls();save();queuePortions();
    }
  }
  function scheduleLayout() {
    cancel();cancelPortions();state.autoPending=true;state.retry=null;
    $('meal-retry').classList.add('hidden');
    $('meal-portions-known').replaceChildren();$('meal-portions-reasons').replaceChildren();
    $('meal-portions').setAttribute('aria-busy','false');
    portionMessage('Đang cập nhật mâm trước khi tính khẩu phần…');
    if(state.ready)state.autoTimer=setTimeout(()=>{state.autoTimer=null;generate();},300);
    message('Đang cập nhật cấu trúc mâm cho '+state.people+' người; món ghim được giữ nếu phù hợp.');
    controls();save();
  }
  const fold = v => v.toLowerCase().replace(/đ/g,'d').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  function picker() {
    const q=fold($('meal-ingredient-search').value.trim());
    $('meal-ingredients').innerHTML=[...state.names].filter(([,n])=>fold(n).includes(q)).map(([id,n])=>
      '<div class="ingredient-row"><span class="ingredient-name">'+esc(n)+'</span><div class="ingredient-actions">'+
      '<button class="ingredient-action" type="button" data-select="'+id+'" aria-pressed="'+state.selected.has(id)+'">'+(state.selected.has(id)?'Đã có ✓':'Có sẵn')+'</button>'+
      '<button class="ingredient-action exclude" type="button" data-exclude="'+id+'" aria-pressed="'+state.excluded.has(id)+'">'+(state.excluded.has(id)?'Đã loại ✓':'Loại trừ')+'</button></div></div>').join('')||'<p class="field-help">Không tìm thấy nguyên liệu.</p>';
    for (const [g,list] of [['selected',state.selected],['excluded',state.excluded]]) {
      $('meal-'+g+'-count').textContent=list.size+'/30';
      $('meal-'+g).innerHTML=[...list].map(id=>'<span class="chip"><span>'+esc(state.names.get(id))+'</span><button type="button" data-remove="'+id+'" data-group="'+g+'" aria-label="Bỏ chọn '+esc(state.names.get(id))+'">×</button></span>').join('');
    }
  }
  function render() {
    const p=state.view?.data.plan;
    $('meal-empty').classList.toggle('hidden',!!p);
    for (const id of ['meal-summary','meal-regenerate']) $(id).classList.toggle('hidden',!p);
    $('meal-cards').innerHTML=p?p.items.map(i=>{
      const pinned=state.pins.has(i.slot), label=labels[i.slot.split(':')[0]]+' '+i.slot.split(':')[1];
      return '<article class="recipe-card'+(pinned?' is-pinned':'')+'" data-meal-slot="'+i.slot+'" data-recipe-id="'+i.recipe_id+'">'+
        '<figure class="recipe-media" data-recipe-media data-recipe-id="'+i.recipe_id+'" data-recipe-title="'+esc(i.title)+'"></figure>'+
        '<span class="meal-slot">'+label+'</span><h3>'+esc(i.title)+'</h3><div class="meta-row">◷ '+i.minutes+' phút</div>'+
        '<p class="meal-missing">Còn thiếu '+i.missing_count+' loại bắt buộc</p>'+
        '<button class="retry-button meal-pin" type="button" data-pin="'+i.slot+'" aria-pressed="'+pinned+'" aria-label="'+(pinned?'Bỏ ghim ':'Ghim ')+esc(i.title)+'">'+(pinned?'Đã ghim · Bỏ ghim':'Ghim món')+'</button>'+
        '<div class="meal-card-actions"><a class="detail-link" href="/recipes/'+i.recipe_id+'?return_to=%2Fmeal-plan">Xem công thức →</a><button class="retry-button" type="button" data-replace="'+i.slot+'" aria-label="Đổi '+esc(i.title)+'">Đổi món ↻</button></div></article>';
    }).join(''):'';
    if (p) {
      $('meal-summary').textContent=p.items.length+' món · '+state.pins.size+' đã ghim · '+p.total_minutes+' phút cộng công thức · Cần mua '+p.missing_count+' loại bắt buộc.';
      window.RecipeImages?.mount($('meal-cards'));
      const titles=new Map(p.items.map(i=>[i.recipe_id,i.title]));
      for (const [id,list] of [['meal-shopping-required',p.shopping_list],['meal-shopping-optional',p.optional_shopping_list]]) {
        $(id).innerHTML=list.map(i=>'<div class="shopping-entry"><strong>'+esc(i.name)+'</strong><ul>'+i.uses.map(u=>'<li>'+esc(titles.get(u.recipe_id))+': '+esc(u.quantity||'chưa ghi định lượng')+(u.is_required?'':' (tùy chọn)')+'</li>').join('')+'</ul></div>').join('')||'<p>Không cần mua thêm trong nhóm này.</p>';
      }
    }
    controls();
  }
  function changed() {
    const resume=state.autoPending;
    cancel(); state.retry=null; $('meal-retry').classList.add('hidden');
    message('Điều kiện đã thay đổi. Nhấn Tạo mâm cơm để áp dụng; món ghim và mâm trước được giữ lại.');
    controls(); save();
    if(resume)scheduleLayout();
  }
  function restore() {
    try {
      const people=Number(sessionStorage.getItem(key+'-people')); if(integer(people,1,12))state.people=people;
      const saved=JSON.parse(sessionStorage.getItem(key)); if (!saved) return;
      if(Array.isArray(saved.publishedNames)&&saved.publishedNames.length<=500)for(const entry of saved.publishedNames){
        if(Array.isArray(entry)&&entry.length===2&&integer(entry[0],4294967297,8589934591)&&text(entry[1]))state.names.set(entry[0],entry[1]);
      }
      state.names=planNames(saved.view?.data);
      if (!sessionStorage.getItem(key+'-people')&&integer(saved.people,1,12))state.people=saved.people;
      if (![1,2].includes(saved.version)||!validConditions(saved.conditions)) throw Error();
      const c=saved.conditions;
      state.preferences={...(c.preferences||{})};
      state.selected=new Set(c.ingredient_ids); state.excluded=new Set(c.excluded_ids);
      for (const [id,[name]] of Object.entries(fields)) $(id).value=c[name]??'';
      if (saved.view) {
        const v=saved.view;
        if (!validConditions(v.conditions)||v.signature!==signature(v.conditions)||!validData(v.data,v.conditions)) throw Error();
        state.view=v;
      }
      const planSlots=state.view?.data.plan?.items.map(i=>i.slot)||[];
      if (!unique(saved.pins)||saved.pins.length>6||!saved.pins.every(k=>planSlots.includes(k))) throw Error();
      state.pins=new Set(saved.pins);
      state.autoPending=saved.autoPending===true||saved.version===1&&layoutMismatch();
      const retry=saved.retry;
      if(retry&&['generate','regenerate'].includes(retry.action)&&(retry.target===null||slot(retry.target)))state.retry={action:retry.action,target:retry.target};
      $('meal-retry').classList.toggle('hidden',!state.retry);
      const h=saved.history;
      if (h&&Object.keys(h).length===3&&groups.every(g=>unique(h[g])&&h[g].length<=50&&h[g].every(i=>integer(i,1,8589934591)))&&groups.reduce((n,g)=>n+h[g].length,0)<=50) state.history=h;
      if (typeof saved.notice==='string'&&saved.notice.length<=2000) message(saved.notice,saved.error===true);
      if (Number.isFinite(saved.scrollY)&&saved.scrollY>=0) requestAnimationFrame(()=>window.scrollTo(0,saved.scrollY));
    } catch {
      state.view=null; state.pins.clear(); state.history=emptyHistory();
      message('Mâm/ghim lưu không còn hợp lệ hoặc dữ liệu đã đổi. Bộ lọc hợp lệ được giữ; hãy tạo mâm mới.',true);
      try {sessionStorage.removeItem(key);} catch {}
    }
  }
  async function load() {
    cancelPortions();
    const token=++state.sequence; state.ready=false; controls();
    $('meal-load-retry').classList.add('hidden'); $('meal-ingredients').setAttribute('aria-busy','true');
    try {
      const response=await fetch('/api/ingredients?limit=50'), e=await response.json();
      if (token!==state.sequence) return;
      if (!response.ok||!e.ok||!text(e.data?.dataset_version)||!Array.isArray(e.data.items)||e.data.items.length>50||
          !unique(e.data.items.map(i=>i?.id))||!e.data.items.every(i=>integer(i.id,1,8589934591)&&text(i.name))) throw Error('Không tải được nguyên liệu.');
      state.names=new Map(e.data.items.map(i=>[i.id,i.name])); state.dataset=e.data.dataset_version;
      restore(); state.ready=true; picker(); render();
      $('meal-ingredients').setAttribute('aria-busy','false');
      if(state.autoPending)scheduleLayout();else queuePortions(0);
      loadFilters();
    } catch (e) { if(token===state.sequence) {message(e instanceof TypeError?'Không kết nối được máy chủ. Hãy thử lại.':e.message,true);$('meal-load-retry').classList.remove('hidden');} }
    finally {if(token===state.sequence) {$('meal-ingredients').setAttribute('aria-busy','false');controls();}}
  }
  async function generate(action='generate',target=null) {
    if (!state.ready||state.busy) return;
    const c=conditions();
    if (!$('meal-form').reportValidity()||!validConditions(c)) {
      state.autoPending=false;state.retry={action,target};
      message('Bộ lọc chưa hợp lệ. Mâm và ghim được giữ; hãy sửa bộ lọc rồi tạo lại mâm.',true);
      $('meal-retry').classList.remove('hidden');queuePortions(0);controls();save();return;
    }
    const previous=state.view?.data.plan, current=Object.fromEntries((previous?.items||[]).map(i=>[i.slot,i.recipe_id]));
    const {counts,...filters}=c;
    const payload={...filters,people:state.people,action,current_plan:current,locked_slots:[...state.pins],avoid_recipe_ids:previous?state.history:{}};
    if (target) payload.replace_slot=target;
    const token=++state.sequence, sig=signature(c);
    state.controller=new AbortController(); state.busy=true; state.retry={action,target};
    state.autoPending=state.autoPending||layoutMismatch();
    message(); $('meal-retry').classList.add('hidden'); controls();
    save();
    state.generationDeadline=setTimeout(()=>{
      if(token!==state.sequence)return;
      cancel();state.autoPending=false;
      message('Tạo mâm quá lâu. Mâm và ghim được giữ; hãy thử lại.',true);
      $('meal-retry').classList.remove('hidden');queuePortions(0);controls();save();
    },10000);
    try {
      const response=await fetch('/api/meal-plan/v2',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:state.controller.signal});
      const e=await response.json();
      if (token!==state.sequence||sig!==signature(conditions())) return;
      if (!response.ok||!e.ok) throw Error(e.error?.code==='UNKNOWN_OPERATION'?'TCP Server chưa hỗ trợ mâm linh hoạt. Hãy khởi động server mới hoặc mở bản ba món cũ.':e.error?.code==='TIMEOUT'?'TCP Server phản hồi quá lâu. Hãy thử lại.':e.error?.message||'Không thể tạo mâm.');
      const data=e.data;
      if (e.version!==1||!text(e.request_id,80)||data?.people!==payload.people||!validData(data,c)) {
        const requestRef=text(e.request_id,80)?' Mã yêu cầu: '+e.request_id+'.':'';
        throw Error('Phản hồi không hợp lệ hoặc dữ liệu đã đổi; mâm và ghim hiện tại được giữ lại.'+requestRef);
      }
      if (data.plan) {
        const next=Object.fromEntries(data.plan.items.map(i=>[i.slot,i.recipe_id]));
        const actual=Object.keys({...current,...next}).filter(k=>current[k]!==next[k]);
        if (!same(previous?actual:[],data.changed_slots)||payload.locked_slots.some(k=>next[k]!==current[k])||
            target&&(next[target]===current[target]||Object.keys(current).some(k=>k!==target&&next[k]!==current[k]))||
            action==='regenerate'&&previous&&!actual.length) throw Error('Phản hồi không giữ đúng món hoặc không đổi món; mâm hiện tại được giữ lại.');
        state.names=planNames(data); picker();
        for (const g of groups) {
          const added=data.plan.items.filter(i=>i.slot.startsWith(g+':')).map(i=>i.recipe_id);
          if (data.warnings.includes('HISTORY_RECYCLED')) state.history[g]=previous?.items.filter(i=>i.slot.startsWith(g+':')).map(i=>i.recipe_id)||[];
          state.history[g]=[...new Set([...state.history[g],...added])];
        }
        state.view={signature:sig,conditions:c,data}; render(); queuePortions(0);
        message('Đã cập nhật mâm; món ghim được giữ nguyên.'+(data.warnings.includes('PARTIAL_REGENERATION')?' Chỉ đổi được một phần mâm.':'')+(data.warnings.includes('HISTORY_RECYCLED')?' Đã dùng lại một số món trong lịch sử.':''));
        state.retry=null;
      } else {
        if (!previous) {state.view={signature:sig,conditions:c,data};render();}
        message(data.reason.message+' '+data.reason.suggestions.join(' ')+(previous?' Mâm và ghim hiện tại được giữ lại.':''));
        $('meal-retry').classList.remove('hidden');queuePortions(0);
      }
      state.autoPending=false; save();
    } catch (e) {
      if (token!==state.sequence||e.name==='AbortError') return;
      state.autoPending=false;
      message(e instanceof TypeError?'Không kết nối được máy chủ. Mâm và ghim được giữ; hãy thử lại.':e instanceof SyntaxError?'Máy chủ trả dữ liệu không hợp lệ. Hãy thử lại.':e.message,true);
      $('meal-retry').classList.remove('hidden');queuePortions(0); save();
    } finally {if(token===state.sequence){clearTimeout(state.generationDeadline);state.generationDeadline=null;state.busy=false;state.controller=null;controls();}}
  }
  $('meal-form').addEventListener('submit',e=>{e.preventDefault();generate();});
  $('meal-regenerate').onclick=()=>generate('regenerate');
  $('meal-retry').onclick=()=>{if(state.retry)generate(state.retry.action,state.retry.target);};
  $('meal-load-retry').onclick=load;
  $('meal-filter-retry').onclick=loadFilters;
  for (const group of Object.keys(preferenceCodes)) $('meal-pref-'+group).addEventListener('change',e=>{
    const value=e.target.value;
    if (value&&!state.metadata?.choices[group].some(c=>c.code===value&&choiceEnabled(c))) {renderFilters();return;}
    if (value)state.preferences[group]=value;else delete state.preferences[group];
    changed();
  });
  $('meal-people-minus').onclick=()=>changePeople(-1);
  $('meal-people-plus').onclick=()=>changePeople(1);
  $('meal-portions-retry').onclick=()=>queuePortions(0);
  $('meal-cards').addEventListener('click',e=>{
    const pin=e.target.closest('[data-pin]'), replace=e.target.closest('[data-replace]');
    if (pin) {
      cancel(); state.retry=null; $('meal-retry').classList.add('hidden');
      const k=pin.dataset.pin; if(state.pins.has(k))state.pins.delete(k);else state.pins.add(k);
      render();message(state.pins.has(k)?'Đã ghim món.':'Đã bỏ ghim món.');save();
      $('meal-cards').querySelector('[data-pin="'+k+'"]')?.focus({preventScroll:true});
      if(layoutMismatch()||state.autoPending)scheduleLayout();
    } else if (replace&&!replace.disabled) generate('generate',replace.dataset.replace);
  });
  $('meal-ingredient-search').addEventListener('input',picker);
  for (const id of Object.keys(fields)) $(id).addEventListener('input',changed);
  $('meal-ingredients').addEventListener('click',e=>{
    const b=e.target.closest('[data-select],[data-exclude]');if(!b||!state.ready)return;
    const available=b.hasAttribute('data-select'), id=Number(b.dataset[available?'select':'exclude']);
    const list=available?state.selected:state.excluded,other=available?state.excluded:state.selected;
    if(list.has(id))list.delete(id);else {if(list.size>=30){message('Mỗi nhóm tối đa 30 nguyên liệu.',true);return;}other.delete(id);list.add(id);}
    changed();picker();$('meal-ingredients').querySelector('[data-'+(available?'select':'exclude')+'="'+id+'"]')?.focus({preventScroll:true});
  });
  for (const g of ['selected','excluded']) $('meal-'+g).addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(b){state[g].delete(Number(b.dataset.remove));changed();picker();}});
  window.addEventListener('pagehide',()=>{save();cancel();cancelPortions();++state.filterSequence;state.filterController?.abort();});
  window.addEventListener('pageshow',e=>{if(e.persisted)load();});
  load();
})();
