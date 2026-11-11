(() => {
  'use strict';
  const $ = id => document.getElementById(id), key = 'goiy-meal-plan-v2';
  const groups = ['main','vegetable','soup'];
  const preferenceCodes={diet:['non_vegetarian','vegetarian'],region:['north','central','south'],occasion:['daily','weekend','guests','birthday','tet','ancestral','snack','drinking']};
  const labels = {main:'Món chính', vegetable:'Món rau', soup:'Canh/Lẩu'};
  const fields = {'meal-max-minutes':['max_minutes',1,240], 'meal-max-total':['max_total_minutes',1,1440], 'meal-max-missing':['max_missing',0,50]};
  const emptyHistory = () => Object.fromEntries(groups.map(g => [g,[]]));
  const state = {names:new Map(), selected:new Set(), excluded:new Set(), pins:new Set(), history:emptyHistory(),
    dataset:null, ready:false, busy:false, sequence:0, controller:null, view:null, retry:null, notice:'', error:false,
    people:4, adults:4, children:0, layoutMode:'automatic', customCounts:{main:1,vegetable:1,soup:1}, calculation:{sequence:0,controller:null,timer:null,deadline:null}, preferences:{occasion:'daily'}, metadata:null,
    filterSequence:0, filterController:null, autoTimer:null, autoPending:false, generationDeadline:null,
    catalogChangedNotice:''};
  const esc = v => { const e=document.createElement('span'); e.textContent=String(v ?? ''); return e.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); };
  const integer = (v,a,b) => Number.isSafeInteger(v) && v>=a && v<=b;
  const recipeID = v => integer(v,1,4294967295) || integer(v,4294967297,8589934591);
  const text = (v,n=255) => typeof v==='string' && v.trim().length>0 && v.length<=n;
  const slot = v => typeof v==='string' && /^(main|vegetable|soup):[1-6]$/.test(v);
  const unique = a => Array.isArray(a) && new Set(a).size===a.length;
  const ids = (a,n=50,names=state.names) => unique(a) && a.length<=n && a.every(i=>integer(i,1,8589934591)&&i!==4294967296&&names.has(i));
  const same = (a,b) => unique(a)&&unique(b)&&a.length===b.length&&a.every(i=>b.includes(i));
  const signature = c => JSON.stringify(c);
  const keysFor = counts => groups.flatMap(g=>Array.from({length:counts[g]},(_,i)=>g+':'+(i+1)));
  // Display preview only; TCP independently derives and validates the same policy.
  const countsForPeople=(n,occasion='daily')=>{
    if(occasion==='guests')return {main:n<=5?3:4,vegetable:1,soup:n>=4?1:0};
    if(occasion==='drinking')return {main:n<=3?2:n<=5?3:4,vegetable:n>=9?2:1,soup:0};
    return Object.fromEntries(groups.map((g,i)=>[g,(n<=2?[1,1,0]:n<=4?[1,1,1]:n<=6?[2,1,1]:n<=8?[2,2,1]:[2,2,2])[i]]));
  };
  const sameCounts=(a,b)=>groups.every(g=>a?.[g]===b?.[g]);
  const desiredCounts=()=>state.layoutMode==='custom'?{...state.customCounts}:countsForPeople(state.people,state.preferences.occasion||'daily');
  const layoutMismatch=()=>!!state.view?.data.plan&&(!sameCounts(state.view.conditions.counts,desiredCounts())||(state.view.conditions.layout_mode||'automatic')!==state.layoutMode);
  const conditions = () => ({ingredient_ids:[...state.selected].sort((a,b)=>a-b), excluded_ids:[...state.excluded].sort((a,b)=>a-b),
    ...Object.fromEntries(Object.entries(fields).map(([id,[name]])=>[name,$(id).value===''?null:Number($(id).value)])),
    counts:desiredCounts(), layout_mode:state.layoutMode,
    ...(Object.keys(state.preferences).length?{preferences:{...state.preferences}}:{})});
  const validPreferences=p=>p&&typeof p==='object'&&!Array.isArray(p)&&Object.keys(p).length<=3&&
    Object.entries(p).every(([k,v])=>k==='occasion'?['daily','guests','drinking'].includes(v):['diet','region'].includes(k)&&preferenceCodes[k]?.includes(v));
  function validConditions(c) {
    const mode=c?.layout_mode||'automatic';
    const occasion=c?.preferences?.occasion||'daily';
    const maxPerGroup=mode==='custom'?6:['guests','drinking'].includes(occasion)?4:2;
    return c && typeof c==='object' && ['automatic','custom'].includes(mode) && Object.keys(c).length===(c.preferences?(c.layout_mode?8:7):(c.layout_mode?7:6)) &&
      (!c.preferences||validPreferences(c.preferences)) && ids(c.ingredient_ids,30) && ids(c.excluded_ids,30) &&
      !c.ingredient_ids.some(i=>c.excluded_ids.includes(i)) && Object.values(fields).every(([name,a,b])=>c[name]===null||integer(c[name],a,b)) &&
      c.counts && Object.keys(c.counts).length===3 && groups.every(g=>integer(c.counts[g],0,maxPerGroup)) && keysFor(c.counts).length>0 && keysFor(c.counts).length<=6;
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
    // Unified v3 derives recipe roles from its catalog rather than the local
    // legacy JSON file. Accept the server-owned version bound to that same base.
    if (typeof version==='string'&&typeof base==='string'&&version==='unified:'+base) return true;
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
    if (d?.people!==undefined&&(!integer(d.people,1,12)||((c.layout_mode||'automatic')==='automatic'&&!sameCounts(d.counts,countsForPeople(d.people,c.preferences?.occasion||'daily')))))return false;
    if (c.preferences&&(!validPreferences(d?.preferences)||Object.keys(c.preferences).length!==Object.keys(d.preferences).length||
        !Object.entries(c.preferences).every(([k,v])=>d.preferences[k]===v)||!text(d.metadata_version))) return false;
    if (!d || d.algorithm!=='meal-plan-v2' || (d.layout_mode||'automatic')!==(c.layout_mode||'automatic') || d.dataset_version!==state.dataset ||
        !versionOK ||
        !groups.every(g=>d.counts?.[g]===c.counts[g]) || !unique(d.changed_slots) || d.changed_slots.length>12 || !d.changed_slots.every(slot) ||
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
      sessionStorage.setItem(key+'-people-groups',JSON.stringify({adults:state.adults,children:state.children}));
      const c=conditions(); if (!validConditions(c)) return;
      sessionStorage.setItem(key,JSON.stringify({version:3,conditions:c,view:state.view,pins:[...state.pins],history:state.history,
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
    $('meal-stale').textContent=layoutMismatch()?'Mâm cũ chưa khớp cấu trúc cho '+state.people+' người. Mâm và ghim được giữ trong lúc hệ thống ghép lại.':'Đang cập nhật mâm theo lựa chọn mới; mâm hiện tại và các món ghim được giữ trong lúc tải.';
      'Bộ lọc đã đổi. Mâm sẽ tự cập nhật; món ghim được giữ lại.';
    $('meal-shopping').classList.toggle('hidden',!p||dirty);
    portionControls();
    renderFilters();
    for (const id of ['meal-ingredient-search',...Object.keys(fields)]) $(id).disabled=!state.ready;
    for (const b of $('meal-cards').querySelectorAll('[data-replace]')) b.disabled=working||dirty||state.pins.has(b.dataset.replace);
    document.querySelectorAll('[data-layout-plus],[data-layout-minus]').forEach(b=>{
      const group=b.dataset.layoutPlus||b.dataset.layoutMinus, value=state.customCounts[group], total=keysFor(state.customCounts).length;
      b.disabled=!state.ready||state.layoutMode!=='custom'||(b.hasAttribute('data-layout-plus')?(value>=6||total>=6):(value<=0||total<=1));
    });
  }
  const choiceEnabled=c=>c.enabled&&(!Array.isArray(c.supported_people)||c.supported_people.includes(state.people));
  function choiceReason(c) {
    if(choiceEnabled(c)||!c.enabled)return c.reason;
    if(c.code==='snack')return 'Chưa đủ món ăn vặt khác nhau cho '+state.people+' người; hệ thống không tự giảm số món.';
    if(c.code!=='vegetarian')return c.reason;
    return 'Chưa đủ món chay được xác minh cho '+state.people+' người. Hiện có '+c.role_counts.main+' chính, '+c.role_counts.vegetable+' rau, '+c.role_counts.soup+' canh; không tự giảm số món hoặc thay món chưa xác minh.';
  }
  function renderFilters() {
    renderMealTypes();
    for (const group of ['diet','region']) {
      const el=$('meal-pref-'+group), allChoices=state.metadata?.choices[group]||[];
      const choices=allChoices, selected=state.preferences[group]||'';
      el.innerHTML='<option value="">Không giới hạn</option>'+choices.map(c=>'<option value="'+esc(c.code)+'"'+(!choiceEnabled(c)?' disabled':'')+'>'+esc(c.label)+(!choiceEnabled(c)?' — chưa đủ dữ liệu':'')+'</option>').join('');
      if (selected&&!choices.some(c=>c.code===selected)) el.add(new Option('Lựa chọn đã lưu — chưa kiểm tra được dữ liệu',selected));
      el.value=selected;
      el.disabled=!state.ready||!selected&&!choices.some(choiceEnabled);
    }
  }
  function renderMealTypes() {
    const choices=state.metadata?.choices?.occasion||[];
    for(const button of document.querySelectorAll('[data-meal-type]')) {
      const buttonKey=button.dataset.mealType;
      const key=buttonKey==='snacks'?'snack':buttonKey==='drinks'?'drinking':buttonKey;
      if(buttonKey==='custom') {button.setAttribute('aria-pressed',String(state.layoutMode==='custom'));continue;}
      const choice=choices.find(item=>item.code===key), enabled=!!choice&&choiceEnabled(choice);
      button.disabled=!state.ready||!enabled;
      button.title=choice?choiceReason(choice):'Chưa có metadata dịp ăn phù hợp trong catalog.';
      button.setAttribute('aria-pressed',String(state.preferences.occasion===key));
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
              (c.supported_people===undefined||unique(c.supported_people)&&c.supported_people.every(n=>integer(n,1,12)))&&
              (c.code!=='vegetarian'||groups.every(g=>integer(c.role_counts?.[g],0,Number.MAX_SAFE_INTEGER)))))) throw Error();
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
    $('meal-adults').value=state.adults;
    $('meal-children').value=state.children;
    $('meal-adults-minus').disabled=!state.ready||state.people<=1||state.adults<=0;
    $('meal-adults-plus').disabled=!state.ready||state.people>=12;
    $('meal-children-minus').disabled=!state.ready||state.people<=1||state.children<=0;
    $('meal-children-plus').disabled=!state.ready||state.people>=12;
    const c=desiredCounts(), total=keysFor(c).length;
    $('meal-custom-layout').classList.toggle('hidden',state.layoutMode!=='custom');
    $('meal-custom-total').textContent=total+'/6';
    for(const group of groups)$('meal-count-'+group).textContent=c[group];
    if($('meal-people-help'))$('meal-people-help').textContent='';
  }
  function cancelPortions() {
    const c=state.calculation;
    ++c.sequence; clearTimeout(c.timer); clearTimeout(c.deadline); c.controller?.abort();
    c.timer=null; c.deadline=null; c.controller=null;
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
    return d.known_ingredients.every(i=>integer(i.ingredient_id,1,8589934591)&&text(i.name)&&text(i.unit,80)&&['required','optional','unknown'].includes(i.requirement)&&
      (i.ingredient_form===null||text(i.ingredient_form,120))&&['gross','edible','prepared','unknown'].includes(i.measurement_basis)&&
      ['main','seasoning','cooking_medium','garnish','unknown','consumed'].includes(i.purpose)&&typeof i.mergeable==='boolean'&&validAmount(i)&&
      Array.isArray(i.uses)&&i.uses.length>0&&i.uses.length<=300&&(!i.mergeable?i.uses.length===1:
        !!i.ingredient_form&&i.measurement_basis!=='unknown'&&i.purpose!=='unknown'&&i.requirement!=='unknown')&&
      i.uses.every(u=>payload.recipe_ids.includes(u.recipe_id)&&u.requirement===i.requirement&&validAmount(u)));
  }
  function validRecipeDetail(data,recipeID,datasetVersion) {
    if(!data||data.id!==recipeID||data.dataset_version!==datasetVersion||!Array.isArray(data.ingredients)||data.ingredients.length>100)return false;
    const seen=new Set();
    return data.ingredients.every(line=>integer(line.line_no,1,100)&&!seen.has(line.line_no)&&seen.add(line.line_no)&&
      integer(line.id,1,8589934591)&&text(line.name)&&
      (line.quantity===null||typeof line.quantity==='string'&&line.quantity.length<=500)&&
      ['required','optional','unknown'].includes(line.requirement||(line.is_required===true?'required':line.is_required===false?'optional':'unknown')));
  }
  async function incompleteSourceLines(data,signal) {
    const incomplete=data.recipes.filter(r=>r.status==='INCOMPLETE');
    const groups=await Promise.all(incomplete.map(async recipe=>{
      const response=await fetch('/api/recipes/'+recipe.recipe_id,{signal});
      const envelope=await response.json();
      const detail=envelope?.data;
      if(!response.ok||envelope.ok!==true||!validRecipeDetail(detail,recipe.recipe_id,data.dataset_version))
        throw Error('Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c th\u00e0nh ph\u1ea7n g\u1ed1c c\u1ee7a m\u00f3n ch\u01b0a t\u00ednh \u0111\u1ee7.');
      const known=new Set(data.known_ingredients.flatMap(item=>(item.uses||[])
        .filter(use=>use.recipe_id===recipe.recipe_id).map(use=>use.line_id)));
      const recipeReasons=recipe.reasons||[];
      const noBase=recipeReasons.some(reason=>['INVALID_BASE_SERVINGS','SERVINGS_NOT_APPROVED'].includes(reason.code));
      const reasonsByLine=new Map(recipeReasons.filter(reason=>reason.line_id!==null&&reason.line_id!==undefined)
        .map(reason=>[reason.line_id,reason]));
      return detail.ingredients.filter(line=>!known.has(line.line_no)).map(line=>({
        recipe_id:recipe.recipe_id,title:detail.title,name:line.name,id:line.id,quantity:line.quantity,
        requirement:line.requirement||(line.is_required===true?'required':line.is_required===false?'optional':'unknown'),
        line_no:line.line_no,no_base:noBase,reason:reasonsByLine.get(line.line_no)||null
      }));
    }));
    return groups.flat();
  }
  function renderCalculatedShopping(data,unscaledLines) {
    const titles=new Map(state.view.data.plan.items.map(i=>[i.recipe_id,i.title]));
    const amount=q=>esc(q.amount_kind==='exact'?q.quantity_value:q.quantity_min+'\u2013'+q.quantity_max);
    const labels={required:'B\u1eaft bu\u1ed9c',optional:'T\u00f9y ch\u1ecdn',unknown:'Ch\u01b0a r\u00f5'};
    const lists={required:[],optional:[],unknown:[]};
    for(const item of data.known_ingredients){
      const bucket=item.requirement in lists?item.requirement:'unknown';
      lists[bucket].push('<div class="shopping-entry"><strong>'+esc(item.name)+': '+amount(item)+' '+esc(item.unit)+'</strong>'+ 
        '<p class="field-help">'+labels[bucket]+(state.selected.has(item.ingredient_id)?' \u00b7 \u0110\u00e3 c\u00f3 s\u1eb5n':'')+' \u00b7 '+(item.mergeable?(item.uses.length>1?'\u0110\u00e3 g\u1ed9p c\u00e1c d\u00f2ng t\u01b0\u01a1ng th\u00edch.':'C\u00f3 th\u1ec3 g\u1ed9p v\u1edbi d\u00f2ng t\u01b0\u01a1ng th\u00edch.'):'Gi\u1eef ri\u00eang t\u1eebng d\u00f2ng; kh\u00f4ng \u0111\u1ee7 c\u0103n c\u1ee9 \u0111\u1ec3 g\u1ed9p.')+
        (item.precision==='outward_6dp'?' \u00b7 Kho\u1ea3ng \u0111\u00e3 l\u00e0m tr\u00f2n ra ngo\u00e0i':'')+'</p><ul>'+ 
        item.uses.map(use=>'<li>'+esc(titles.get(use.recipe_id))+': '+amount(use)+' '+esc(item.unit)+'</li>').join('')+'</ul></div>');
    }
    for(const line of unscaledLines){
      const bucket=line.requirement in lists?line.requirement:'unknown';
      const note=line.no_base?'Kh\u00f4ng nh\u00e2n: c\u00f4ng th\u1ee9c thi\u1ebfu kh\u1ea9u ph\u1ea7n g\u1ed1c h\u1ee3p l\u1ec7.':
        line.reason?line.reason.message:'Gi\u1eef nguy\u00ean l\u01b0\u1ee3ng g\u1ed1c v\u00ec ch\u01b0a c\u00f3 \u0111\u1ecbnh l\u01b0\u1ee3ng s\u1ed1 \u0111\u1ee7 c\u0103n c\u1ee9.';
      lists[bucket].push('<div class="shopping-entry"><strong>'+esc(line.name)+': '+esc(line.quantity?.trim()||'ch\u01b0a ghi \u0111\u1ecbnh l\u01b0\u1ee3ng')+'</strong>'+ 
        '<p class="field-help">'+esc(line.title)+' \u00b7 '+labels[bucket]+(state.selected.has(line.id)?' \u00b7 \u0110\u00e3 c\u00f3 s\u1eb5n':'')+' \u00b7 '+esc(note)+'</p></div>');
    }
    $('meal-shopping-required').innerHTML=lists.required.join('')||'<p>Kh\u00f4ng c\u00f3 m\u1ee5c trong nh\u00f3m n\u00e0y.</p>';
    $('meal-shopping-optional').innerHTML=lists.optional.join('')||'<p>Kh\u00f4ng c\u00f3 m\u1ee5c trong nh\u00f3m n\u00e0y.</p>';
    const unknownRoot=$('meal-shopping-unknown');
    if(unknownRoot)unknownRoot.innerHTML=lists.unknown.join('')||'<p>Kh\u00f4ng c\u00f3 m\u1ee5c trong nh\u00f3m n\u00e0y.</p>';
    $('meal-shopping-title').textContent='Danh s\u00e1ch \u0111i ch\u1ee3';
    $('meal-shopping-note').textContent=data.totals_complete?
      'L\u01b0\u1ee3ng \u0111\u00e3 t\u00ednh d\u1ef1a tr\u00ean kh\u1ea9u ph\u1ea7n g\u1ed1c v\u00e0 \u0111\u1ecbnh l\u01b0\u1ee3ng c\u1ea5u tr\u00fac. C\u00e1c d\u00f2ng ch\u1ec9 \u0111\u01b0\u1ee3c g\u1ed9p khi \u0111\u01a1n v\u1ecb v\u00e0 th\u00f4ng tin t\u01b0\u01a1ng th\u00edch \u0111\u00e3 x\u00e1c nh\u1eadn.':
      'Danh s\u00e1ch gi\u1eef c\u1ea3 l\u01b0\u1ee3ng \u0111\u00e3 t\u00ednh v\u00e0 th\u00e0nh ph\u1ea7n ch\u01b0a x\u00e1c \u0111\u1ecbnh. D\u00f2ng ghi ?ch\u01b0a nh\u00e2n? gi\u1eef nguy\u00ean theo c\u00f4ng th\u1ee9c; kh\u00f4ng t\u1ef1 quy \u0111\u1ed5i ho\u1eb7c \u01b0\u1edbc l\u01b0\u1ee3ng.';
  }
  function renderBaseShopping(plan) {
    if(!plan)return;
    const titles=new Map(plan.items.map(i=>[i.recipe_id,i.title]));
    $('meal-shopping-title').textContent='Danh s\u00e1ch \u0111i ch\u1ee3';
    $('meal-shopping-note').textContent='Danh s\u00e1ch nguy\u00ean li\u1ec7u theo c\u00f4ng th\u1ee9c; l\u01b0\u1ee3ng t\u00ednh \u0111\u01b0\u1ee3c s\u1ebd c\u1eadp nh\u1eadt theo s\u1ed1 ng\u01b0\u1eddi.';
    $('meal-shopping-unknown')?.replaceChildren();
    for (const [id,list] of [['meal-shopping-required',plan.shopping_list],['meal-shopping-optional',plan.optional_shopping_list]]) {
      $(id).innerHTML=list.map(i=>'<div class="shopping-entry"><strong>'+esc(i.name)+'</strong><ul>'+i.uses.map(u=>'<li>'+esc(titles.get(u.recipe_id))+': '+esc(u.quantity||'ch\u01b0a ghi \u0111\u1ecbnh l\u01b0\u1ee3ng')+(u.is_required?'':' (t\u00f9y ch\u1ecdn)')+'</li>').join('')+'</ul></div>').join('')||'<p>Kh\u00f4ng c\u1ea7n mua th\u00eam trong nh\u00f3m n\u00e0y.</p>';
    }
  }
  function queuePortions(delay=300) {
    cancelPortions(); portionControls();
    const c=state.calculation, payload=portionPayload(), sig=signature(payload), token=c.sequence;
    if (!payload.recipe_ids.length) return;
    renderBaseShopping(state.view?.data.plan);
    if(layoutMismatch()) {
      $('meal-shopping-note').textContent='Ch\u01b0a t\u00ednh \u0111\u01b0\u1ee3c l\u01b0\u1ee3ng v\u00ec m\u00e2m ch\u01b0a kh\u1edbp c\u1ea5u tr\u00fac; danh s\u00e1ch v\u1eabn gi\u1eef l\u01b0\u1ee3ng g\u1ed1c theo c\u00f4ng th\u1ee9c.';
      return;
    }
    $('meal-shopping-note').textContent='\u0110ang t\u00ednh l\u01b0\u1ee3ng cho '+payload.people+' ng\u01b0\u1eddi; danh s\u00e1ch nguy\u00ean li\u1ec7u v\u1eabn \u0111\u01b0\u1ee3c gi\u1eef.';
    c.timer=setTimeout(async()=>{
      c.timer=null; const controller=new AbortController(); c.controller=controller;
      const current=()=>token===c.sequence&&sig===signature(portionPayload());
      const fail=msg=>{
        if (!current()) return;
        $('meal-shopping-note').textContent=msg+' Danh s\u00e1ch v\u1eabn gi\u1eef l\u01b0\u1ee3ng g\u1ed1c theo c\u00f4ng th\u1ee9c.';
      };
      c.deadline=setTimeout(()=>{
        if (!current()) return;
        fail('T\u00ednh kh\u1ea9u ph\u1ea7n qu\u00e1 l\u00e2u. H\u00e3y th\u1eed l\u1ea1i.'); cancelPortions();
      },10000);
      try {
        const response=await fetch('/api/meal-plan/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
        const e=await response.json(); if (!current()) return;
        if (!response.ok||!e.ok) throw Error(e.error?.code==='TIMEOUT'?'T\u00ednh kh\u1ea9u ph\u1ea7n qu\u00e1 l\u00e2u. H\u00e3y th\u1eed l\u1ea1i.':'Ch\u01b0a th\u1ec3 t\u00ednh kh\u1ea9u ph\u1ea7n. H\u00e3y th\u1eed l\u1ea1i.');
        if (e.version!==1||!text(e.request_id,80)||!validPortions(e.data,payload)) throw Error('K\u1ebft qu\u1ea3 kh\u1ea9u ph\u1ea7n kh\u00f4ng h\u1ee3p l\u1ec7. H\u00e3y th\u1eed l\u1ea1i.');
        try {
          const unresolved=await incompleteSourceLines(e.data,controller.signal);
          if (!current()) return;
          renderCalculatedShopping(e.data,unresolved);
        } catch(error) {
          if (!current()||controller.signal.aborted) return;
          renderBaseShopping(state.view?.data.plan);
          $('meal-shopping-note').textContent=(error.message||'Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c th\u00e0nh ph\u1ea7n ch\u01b0a t\u00ednh.')+' Danh s\u00e1ch v\u1eabn gi\u1eef l\u01b0\u1ee3ng g\u1ed1c theo c\u00f4ng th\u1ee9c.';
        }
      } catch(e) {if (current()) fail(e instanceof TypeError?'Kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c m\u00e1y ch\u1ee7 \u0111\u1ec3 t\u00ednh kh\u1ea9u ph\u1ea7n. H\u00e3y th\u1eed l\u1ea1i.':e instanceof SyntaxError?'K\u1ebft qu\u1ea3 kh\u1ea9u ph\u1ea7n kh\u00f4ng h\u1ee3p l\u1ec7. H\u00e3y th\u1eed l\u1ea1i.':e.message);}
      finally {if (current()) {clearTimeout(c.deadline);c.deadline=null;c.controller=null;}}
    },delay);
  }
  function changePeople(delta,kind='adults') {
    const previous=kind==='adults'?state.adults:state.children, value=previous+delta;
    if(!integer(value,0,12)||state.people+delta<1||state.people+delta>12)return;
    if(kind==='adults')state.adults=value;else state.children=value;
    const before=desiredCounts();state.people=state.adults+state.children;
    const p=state.view?.data.plan;
    if(state.layoutMode==='automatic'&&(layoutMismatch()||state.autoPending||!p&&!sameCounts(before,countsForPeople(value)))) scheduleLayout();
    else {
      if(state.autoPending){cancel();state.autoPending=false;state.retry=null;message();$('meal-retry').classList.add('hidden');}
      controls();save();render();queuePortions();
    }
  }
  function scheduleLayout() {
    cancel();cancelPortions();state.autoPending=true;state.retry=null;
    $('meal-retry').classList.add('hidden');
    if(state.ready)state.autoTimer=setTimeout(()=>{state.autoTimer=null;generate();},300);
    message((state.layoutMode==='custom'?'Đang cập nhật mâm theo số món đã chọn; món ghim được giữ nếu phù hợp.':'Đang cập nhật cấu trúc mâm cho '+state.people+' người; món ghim được giữ nếu phù hợp.')+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''));
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
      const occasion=state.view?.conditions?.preferences?.occasion||'daily', group=i.slot.split(':')[0], index=Number(i.slot.split(':')[1]);
      const roleLabel=occasion==='guests'?(group==='main'?(index===1?'Khai v\u1ecb':'M\u00f3n ch\u00ednh'):group==='vegetable'?'M\u00f3n rau':'Canh/L\u1ea9u'):
        occasion==='drinking'?(group==='main'?'M\u00f3n nh\u1eadu':group==='vegetable'?'\u0102n k\u00e8m':''):labels[group];
      const label=roleLabel+(occasion==='guests'&&group==='main'&&index>1?' '+(index-1):occasion==='drinking'?' '+index:'');
      const pinned=state.pins.has(i.slot);
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
      renderBaseShopping(p);
    }
    controls();
  }
  function changed() {
    state.autoPending=true;
    scheduleLayout();
  }

  function restore() {
    let staleIngredientSelection = false;
    try {
      const people=Number(sessionStorage.getItem(key+'-people')); if(integer(people,1,12))state.people=people;
      const saved=JSON.parse(sessionStorage.getItem(key));
      let groups=null;try{groups=JSON.parse(sessionStorage.getItem(key+'-people-groups'));}catch{}
      if(groups&&integer(groups.adults,0,12)&&integer(groups.children,0,12)&&groups.adults+groups.children>=1&&groups.adults+groups.children<=12){state.adults=groups.adults;state.children=groups.children;state.people=groups.adults+groups.children;}
      else if(integer(people,1,12)){state.adults=people;state.children=0;}
      if (!saved) return;
      const savedOccasion=saved.conditions?.preferences?.occasion;
      if(!savedOccasion||!['daily','guests','drinking'].includes(savedOccasion)) {
        const cleanPreferences={...(saved.conditions.preferences||{})};delete cleanPreferences.occasion;
        cleanPreferences.occasion='daily';
        saved.conditions={...saved.conditions,preferences:cleanPreferences,
          counts:saved.conditions.layout_mode==='custom'?saved.conditions.counts:countsForPeople(state.people,'daily')};
        if(saved.view) {
          const viewConditions={...saved.conditions};
          saved.view={...saved.view,conditions:viewConditions,signature:signature(viewConditions),
            data:{...saved.view.data,preferences:cleanPreferences}};
        }
        saved.autoPending=true;
        if(savedOccasion)state.notice='Bộ lọc dịp ăn cũ đã được bỏ. Đã chuyển về Hằng ngày.';
      }
      // Persisted names are labels for an old result, not catalog authority.
      // Only IDs from the current /api/ingredients response may be selectable.
      staleIngredientSelection = [saved.conditions?.ingredient_ids,saved.conditions?.excluded_ids]
        .some(list=>Array.isArray(list)&&list.some(id=>integer(id,1,8589934591)&&!state.names.has(id)));
      if (!sessionStorage.getItem(key+'-people')&&integer(saved.people,1,12))state.people=saved.people;
      if (![1,2,3].includes(saved.version)||!validConditions(saved.conditions)) throw Error();
      const c=saved.conditions;
      const savedSnackMode=false;
      state.layoutMode=c.layout_mode||'automatic';state.customCounts={...c.counts};
      state.preferences={...(c.preferences||{})};
      if(savedSnackMode){
        state.preferences.occasion='daily';
        state.autoPending=true;
        state.notice='Kiểu mâm Ăn vặt đã được bỏ. Đã chuyển sang Hằng ngày và sẽ tự cập nhật mâm.';
      }
      state.selected=new Set(c.ingredient_ids); state.excluded=new Set(c.excluded_ids);
      for (const [id,[name]] of Object.entries(fields)) $(id).value=c[name]??'';
      if (saved.view&&!savedSnackMode) {
        const v=saved.view;
        if (!validConditions(v.conditions)||v.signature!==signature(v.conditions)||!validData(v.data,v.conditions)) throw Error();
        state.view=v;
      }
      const planSlots=state.view?.data.plan?.items.map(i=>i.slot)||[];
      if (!unique(saved.pins)||saved.pins.length>6||!savedSnackMode&&!saved.pins.every(k=>planSlots.includes(k))) throw Error();
      state.pins=new Set(savedSnackMode?[]:saved.pins);
      state.autoPending=state.autoPending||saved.autoPending===true||saved.version===1&&layoutMismatch();
      const retry=saved.retry;
      if(retry&&['generate','regenerate'].includes(retry.action)&&(retry.target===null||slot(retry.target)))state.retry={action:retry.action,target:retry.target};
      $('meal-retry').classList.toggle('hidden',!state.retry);
      const h=saved.history;
      if (!savedSnackMode&&h&&Object.keys(h).length===3&&groups.every(g=>unique(h[g])&&h[g].length<=50&&h[g].every(i=>integer(i,1,8589934591)))&&groups.reduce((n,g)=>n+h[g].length,0)<=50) state.history=h;
      if (typeof saved.notice==='string'&&saved.notice.length<=2000) message(saved.notice,saved.error===true);
      if (Number.isFinite(saved.scrollY)&&saved.scrollY>=0) requestAnimationFrame(()=>window.scrollTo(0,saved.scrollY));
    } catch {
      state.view=null; state.pins.clear(); state.history=emptyHistory();
      state.selected.clear(); state.excluded.clear();
      state.catalogChangedNotice=staleIngredientSelection
        ? 'Danh mục nguyên liệu đã thay đổi. Các lựa chọn cũ không còn hợp lệ đã được bỏ; không có nguyên liệu nào được tự thay thế. Hãy chọn lại nếu cần.'
        : 'Mâm/ghim lưu không còn hợp lệ hoặc dữ liệu đã đổi. Bộ lọc hợp lệ được giữ; hãy tạo mâm mới.';
      message(state.catalogChangedNotice,true);
      try {sessionStorage.removeItem(key);} catch {}
    }
  }
  async function load() {
    cancelPortions();
    const token=++state.sequence; state.ready=false; controls();
    $('meal-load-retry').classList.add('hidden'); $('meal-ingredients').setAttribute('aria-busy','true');
    try {
      const response=await fetch('/api/ingredients?limit=250'), e=await response.json();
      if (token!==state.sequence) return;
      if (!response.ok||!e.ok||!text(e.data?.dataset_version)||!Array.isArray(e.data.items)||e.data.items.length>250||
          !unique(e.data.items.map(i=>i?.id))||!e.data.items.every(i=>integer(i.id,1,8589934591)&&text(i.name))) throw Error('Không tải được nguyên liệu.');
      state.names=new Map(e.data.items.map(i=>[i.id,i.name])); state.dataset=e.data.dataset_version;
      restore();
      state.ready=true; picker(); render();
      const params=new URLSearchParams(location.search);
      let cleanURL=false;
      for(const k of ['occasion','meal_occasion','occasion_code','event','budget','min_budget','max_budget','budget_min','budget_max'])
        if(params.has(k)){params.delete(k);cleanURL=true;}
      if(['snack','snacks'].includes(params.get('type'))){params.delete('type');cleanURL=true;state.preferences.occasion='daily';state.autoPending=true;}
      if(cleanURL)history.replaceState(null,'',location.pathname+(params.size?'?'+params.toString():'')+location.hash);
      $('meal-ingredients').setAttribute('aria-busy','false');
      if(state.autoPending||!state.view){state.autoPending=true;scheduleLayout();}else queuePortions(0);
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
    const payload={...c,people:state.people,action,current_plan:current,locked_slots:[...state.pins],avoid_recipe_ids:previous?state.history:{}};
    if (target) payload.replace_slot=target;
    const token=++state.sequence, sig=signature(c);
    state.controller=new AbortController(); state.busy=true; state.retry={action,target};
    state.autoPending=state.autoPending||layoutMismatch();
    message(state.catalogChangedNotice); $('meal-retry').classList.add('hidden'); controls();
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
        message('Đã cập nhật mâm; món ghim được giữ nguyên.'+(data.warnings.includes('PARTIAL_REGENERATION')?' Chỉ đổi được một phần mâm.':'')+(data.warnings.includes('HISTORY_RECYCLED')?' Đã dùng lại một số món trong lịch sử.':'')+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''));
        state.catalogChangedNotice='';
        state.retry=null;
      } else {
        if (!previous) {state.view={signature:sig,conditions:c,data};render();}
        message(data.reason.message+' '+data.reason.suggestions.join(' ')+(previous?' Mâm và ghim hiện tại được giữ lại.':'')+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''));
        state.catalogChangedNotice='';
        $('meal-retry').classList.remove('hidden');queuePortions(0);
      }
      state.autoPending=false; save();
    } catch (e) {
      if (token!==state.sequence||e.name==='AbortError') return;
      state.autoPending=false;
      message((e instanceof TypeError?'Không kết nối được máy chủ. Mâm và ghim được giữ; hãy thử lại.':e instanceof SyntaxError?'Máy chủ trả dữ liệu không hợp lệ. Hãy thử lại.':e.message)+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''),true);
      state.catalogChangedNotice='';
      $('meal-retry').classList.remove('hidden');queuePortions(0); save();
    } finally {if(token===state.sequence){clearTimeout(state.generationDeadline);state.generationDeadline=null;state.busy=false;state.controller=null;controls();}}
  }
  $('meal-form').addEventListener('submit',e=>{e.preventDefault();generate();});
  $('meal-regenerate').onclick=()=>generate('regenerate');
  $('meal-retry').onclick=()=>{if(state.retry)generate(state.retry.action,state.retry.target);};
  $('meal-load-retry').onclick=load;
  $('meal-filter-retry').onclick=loadFilters;
  $('meal-types').addEventListener('click',e=>{
    const button=e.target.closest('[data-meal-type]');if(!button||button.disabled)return;
    const buttonKey=button.dataset.mealType;
    const key=buttonKey==='snacks'?'snack':buttonKey==='drinks'?'drinking':buttonKey;
    if(buttonKey==='custom') {
      if(state.layoutMode!=='custom')state.customCounts=countsForPeople(state.people);
      state.layoutMode='custom';delete state.preferences.occasion;
    }
    else {
      const choice=state.metadata?.choices.occasion.find(item=>item.code===key);
      if(!choice||!choiceEnabled(choice))return;
      state.layoutMode='automatic';state.preferences.occasion=key;
    }
    state.autoPending=true;renderFilters();scheduleLayout();
  });
  $('meal-custom-layout').addEventListener('click',e=>{
    const button=e.target.closest('[data-layout-plus],[data-layout-minus]');
    if(!button||state.layoutMode!=='custom')return;
    const group=button.dataset.layoutPlus||button.dataset.layoutMinus;
    const delta=button.hasAttribute('data-layout-plus')?1:-1;
    const next=state.customCounts[group]+delta,total=keysFor(state.customCounts).length+delta;
    if(next<0||next>6||total<1||total>6)return;
    state.customCounts={...state.customCounts,[group]:next};
    state.autoPending=true;controls();scheduleLayout();
  });
  $('meal-copy-list').addEventListener('click',async()=>{
    const lines=['Danh s\u00e1ch \u0111i ch\u1ee3'];
    for(const [title,id] of [['B\u1eaft bu\u1ed9c','meal-shopping-required'],['T\u00f9y ch\u1ecdn','meal-shopping-optional'],['Ch\u01b0a r\u00f5 t\u00ednh ch\u1ea5t','meal-shopping-unknown']]) {
      const text=$(id).innerText.trim();lines.push('',title,text||'Kh\u00f4ng c\u00f3 m\u1ee5c');
    }
    try {
      if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(lines.join('\n'));
      else {const field=document.createElement('textarea');field.value=lines.join('\n');field.style.position='fixed';field.style.opacity='0';document.body.append(field);field.select();if(!document.execCommand('copy'))throw Error();field.remove();}
      $('meal-copy-feedback').textContent='\u0110\u00e3 sao ch\u00e9p danh s\u00e1ch.';
    } catch {$('meal-copy-feedback').textContent='Kh\u00f4ng th\u1ec3 sao ch\u00e9p. H\u00e3y ch\u1ecdn v\u00e0 sao ch\u00e9p n\u1ed9i dung danh s\u00e1ch.';}
  });
  for (const group of ['diet','region']) $('meal-pref-'+group).addEventListener('change',e=>{
    const value=e.target.value;
    if (value&&!state.metadata?.choices[group].some(c=>c.code===value&&choiceEnabled(c))) {renderFilters();return;}
    if (value)state.preferences[group]=value;else delete state.preferences[group];
    changed();
  });
  $('meal-adults-minus').onclick=()=>changePeople(-1,'adults');
  $('meal-adults-plus').onclick=()=>changePeople(1,'adults');
  $('meal-children-minus').onclick=()=>changePeople(-1,'children');
  $('meal-children-plus').onclick=()=>changePeople(1,'children');
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
