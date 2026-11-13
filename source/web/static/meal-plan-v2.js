(() => {
  'use strict';
  const $ = id => document.getElementById(id), key = 'goiy-meal-plan-v2';
  const groups = ['main','vegetable','soup'];
  const maxDailyComboHistory = 1700;
  const preferenceCodes={diet:['non_vegetarian','vegetarian'],region:['north','central','south'],occasion:['daily','weekend','guests','birthday','tet','ancestral','snack','drinking']};
  const labels = {main:'Món chính', vegetable:'Món rau', soup:'Canh/Lẩu'};
  const fields = {'meal-max-minutes':['max_minutes',1,240], 'meal-max-total':['max_total_minutes',1,1440], 'meal-max-missing':['max_missing',0,50]};
  const emptyHistory = () => Object.fromEntries(groups.map(g => [g,[]]));
  const state = {names:new Map(), selected:new Set(), excluded:new Set(), pins:new Set(), history:emptyHistory(),
    dailyComboHistory:[], dailyComboHistorySignature:null, dailyNoResultKey:null,
    dataset:null, ready:false, busy:false, sequence:0, controller:null, view:null, retry:null, notice:'', error:false,
    people:4, adults:4, children:0, layoutMode:'automatic', customCounts:{main:1,vegetable:1,soup:1}, calculation:{sequence:0,controller:null,timer:null,deadline:null}, preferences:{occasion:'daily'}, metadata:null,
    filterSequence:0, filterController:null, autoTimer:null, autoPending:false, generationDeadline:null,
    catalogChangedNotice:'', season:'ALL'};
  const seasons=['ALL','SPRING','SUMMER','AUTUMN','WINTER'];
  const esc = v => { const e=document.createElement('span'); e.textContent=String(v ?? ''); return e.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); };
  const integer = (v,a,b) => Number.isSafeInteger(v) && v>=a && v<=b;
  const recipeID = v => integer(v,1,4294967295) || integer(v,4294967297,8589934591);
  const text = (v,n=255) => typeof v==='string' && v.trim().length>0 && v.length<=n;
  const unitLabel=unit=>({source_spoon:'muỗng (chưa rõ loại)',source_bowl:'chén (không quy đổi)',source_stack:'xấp'}[unit]||unit);
  const slot = v => typeof v==='string' && /^(main|vegetable|soup):[1-6]$/.test(v);
  const unique = a => Array.isArray(a) && new Set(a).size===a.length;
  const ids = (a,n=50,names=state.names) => unique(a) && a.length<=n && a.every(i=>integer(i,1,8589934591)&&i!==4294967296&&names.has(i));
  const same = (a,b) => unique(a)&&unique(b)&&a.length===b.length&&a.every(i=>b.includes(i));
  const signature = c => JSON.stringify(c);
  const dailyResultKey = c => JSON.stringify({conditions:c,adults:state.adults,children:state.children});
  const dailyComboSignature = c => JSON.stringify({conditions:c,adults:state.adults,children:state.children,pins:[...state.pins].sort()});
  const keysFor = counts => groups.flatMap(g=>Array.from({length:counts[g]},(_,i)=>g+':'+(i+1)));
  // Display preview only; TCP independently derives and validates the same policy.
  const countsForPeople=(n,occasion='daily')=>{
    if(occasion==='guests')return {main:n<=5?3:4,vegetable:1,soup:n>=4?1:0};
    if(occasion==='drinking')return {main:n<=3?2:n<=5?3:4,vegetable:n>=9?2:1,soup:0};
    return Object.fromEntries(groups.map((g,i)=>[g,(n<=2?[1,1,0]:n<=4?[1,1,1]:n<=6?[2,1,1]:n<=8?[2,2,1]:[2,2,2])[i]]));
  };
  const sameCounts=(a,b)=>groups.every(g=>a?.[g]===b?.[g]);
  const dailyClassicCounts=n=>({main:n<=3?1:n<=6?2:n<=9?3:n<=11?4:5,vegetable:1,soup:1});
  const desiredCounts=()=>state.layoutMode==='custom'?{...state.customCounts}:
    (state.preferences.occasion||'daily')==='daily'?dailyClassicCounts(state.people):countsForPeople(state.people,state.preferences.occasion);
  const layoutMismatch=()=>!!state.view?.data.plan&&((state.view.conditions.adaptive_daily?
    !sameCounts(state.view.data.counts,dailyClassicCounts(state.people))||state.view.data.daily_selection_policy!=='daily-demo-food-v1'||state.view.dailyHousehold!==JSON.stringify([state.adults,state.children]):!sameCounts(state.view.conditions.counts,desiredCounts()))||
    (state.view.conditions.layout_mode||'automatic')!==state.layoutMode);
  const conditions = () => ({ingredient_ids:(['guests','drinking'].includes(state.preferences.occasion)?[]:[...state.selected]).sort((a,b)=>a-b), excluded_ids:[...state.excluded].sort((a,b)=>a-b),
    ...Object.fromEntries(Object.entries(fields).map(([id,[name]])=>[name,
      id==='meal-max-missing'&&['guests','drinking'].includes(state.preferences.occasion)?null:$(id).value===''?null:Number($(id).value)])),
    counts:desiredCounts(), layout_mode:state.layoutMode, people:state.people,
    ...(state.layoutMode==='automatic'&&(state.preferences.occasion||'daily')==='daily'?{adaptive_daily:true}:{}),
    ...($('meal-weather').value?{weather:$('meal-weather').value}:{}),
    ...(state.layoutMode==='automatic'&&(state.preferences.occasion||'daily')==='daily'&&state.season!=='ALL'?{season:state.season}:{}),
    ...(Object.keys(state.preferences).length?{preferences:{...state.preferences}}:{})});
  const validPreferences=p=>p&&typeof p==='object'&&!Array.isArray(p)&&Object.keys(p).length<=3&&
    Object.entries(p).every(([k,v])=>k==='occasion'?['daily','guests','drinking'].includes(v):['diet','region'].includes(k)&&preferenceCodes[k]?.includes(v));
  function validConditions(c) {
    const mode=c?.layout_mode||'automatic';
    const occasion=c?.preferences?.occasion||'daily';
    const maxPerGroup=mode==='custom'?6:c?.adaptive_daily?5:['guests','drinking'].includes(occasion)?4:2;
    const allowedKeys=new Set(['ingredient_ids','excluded_ids','max_minutes','max_total_minutes','max_missing','counts','layout_mode','people','adaptive_daily','weather','preferences','season']);
    return c && typeof c==='object' && Object.keys(c).every(k=>allowedKeys.has(k)) && ['automatic','custom'].includes(mode) && integer(c.people,1,12) &&
      (c.adaptive_daily===undefined||c.adaptive_daily===true&&mode==='automatic'&&occasion==='daily') &&
      (c.season===undefined||seasons.includes(c.season)&&c.adaptive_daily===true) &&
      (!c.weather||['hot','cold','rain','sunny'].includes(c.weather)) && (!c.preferences||validPreferences(c.preferences)) && ids(c.ingredient_ids,30) && ids(c.excluded_ids,30) &&
      !c.ingredient_ids.some(i=>c.excluded_ids.includes(i)) && Object.values(fields).every(([name,a,b])=>c[name]===null||integer(c[name],a,b)) &&
      c.counts && Object.keys(c.counts).length===3 && groups.every(g=>integer(c.counts[g],0,maxPerGroup)) && keysFor(c.counts).length>0 && keysFor(c.counts).length<=(c.adaptive_daily?7:6) &&
      (!c.adaptive_daily||c.counts.main>=1&&c.counts.main<=5&&c.counts.vegetable>=1&&c.counts.vegetable<=4&&c.counts.soup<=4);
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
    if((d?.weather||'')!==(c?.weather||''))return false;
    if((d?.season||'ALL')!==(c?.season||'ALL'))return false;
    if(c?.season&&c.season!=='ALL'){
      const s=d?.seasonal_assessment;
      if(d?.plan!==null&&(!s||s.season!==c.season||!Array.isArray(s.items)||
        s.items.length!==d.plan.items.length||!text(s.summary,1000)||
        !s.items.every((v,i)=>v.recipe_id===d.plan.items[i].recipe_id&&Number.isSafeInteger(v.score)&&
          typeof v.standalone==='boolean'&&Array.isArray(v.reasons)&&v.reasons.every(r=>text(r,500)))))return false;
    }else if(d?.seasonal_assessment)return false;
    const names=planNames(d), dataIDs=a=>ids(a,50,names);
    const baseVersion=document.body.dataset.classificationVersion;
    const versionOK=validClassificationVersion(d?.classification_version,baseVersion);
    const adaptive=c?.adaptive_daily===true;
    if (d?.people!==undefined&&(!integer(d.people,1,12)||(!adaptive&&(c.layout_mode||'automatic')==='automatic'&&!sameCounts(d.counts,countsForPeople(d.people,c.preferences?.occasion||'daily')))))return false;
    if (c.preferences&&(!validPreferences(d?.preferences)||Object.keys(c.preferences).length!==Object.keys(d.preferences).length||
        !Object.entries(c.preferences).every(([k,v])=>d.preferences[k]===v)||!text(d.metadata_version))) return false;
    if (!d || d.algorithm!=='meal-plan-v2' || (d.layout_mode||'automatic')!==(c.layout_mode||'automatic') || d.dataset_version!==state.dataset ||
        !versionOK ||
        (adaptive?d.adaptive_daily!==true||d.counts.main<1||d.counts.main>5||d.counts.vegetable<1||d.counts.vegetable>4||d.counts.soup>4||keysFor(d.counts).length<2||keysFor(d.counts).length>7:
          d.adaptive_daily===true||!groups.every(g=>d.counts?.[g]===c.counts[g])) || !unique(d.changed_slots) || d.changed_slots.length>(adaptive?14:12) || !d.changed_slots.every(slot) ||
        !unique(d.warnings) || d.warnings.length>2 || !d.warnings.every(w=>['NO_COMPLETE_MEAL_PLAN','PARTIAL_REGENERATION','HISTORY_RECYCLED'].includes(w))) return false;
    if (adaptive&&(!d.daily_combo_search||!integer(d.daily_combo_search.found,0,1000000)||
        typeof d.daily_combo_search.complete!=='boolean'||
        d.plan!==null&&(!text(d.daily_combo_id,32)||!/^[a-f0-9]{32}$/.test(d.daily_combo_id))||
        d.daily_combo_note!==undefined&&!text(d.daily_combo_note,500))) return false;
    if (d.plan===null) return !d.changed_slots.length && d.warnings.includes('NO_COMPLETE_MEAL_PLAN') && text(d.reason?.code,80) &&
      text(d.reason?.message,500) && Array.isArray(d.reason.suggestions) && d.reason.suggestions.length<=3 && d.reason.suggestions.every(x=>text(x));
    const p=d.plan, expected=keysFor(adaptive?d.counts:c.counts);
    if (!p || d.reason!==null || !Array.isArray(p.items) || p.items.length!==expected.length ||
        !same(p.items.map(i=>i?.slot),expected) || !unique(p.items.map(i=>i?.recipe_id)) ||
        !dataIDs(p.required_ids)||!dataIDs(p.matched_ids)||!dataIDs(p.missing_ids)||!dataIDs(p.optional_missing_ids)||
        p.missing_count!==p.missing_ids.length||p.time_basis!=='sum_of_recipe_minutes'||
        !integer(p.total_minutes,1,adaptive?1680:1440)||c.max_total_minutes!==null&&p.total_minutes>c.max_total_minutes||
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
      Array.isArray(i.uses)&&i.uses.length>=1&&i.uses.length<=(adaptive?7:6)&&unique(i.uses.map(u=>u?.recipe_id))&&
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
      if(dailyOnly())sessionStorage.setItem(key+'-season',state.season);
      sessionStorage.setItem(key+'-people-groups',JSON.stringify({adults:state.adults,children:state.children}));
      const c=conditions(); if (!validConditions(c)) return;
      sessionStorage.setItem(key,JSON.stringify({version:3,conditions:c,view:state.view,pins:[...state.pins],history:state.history,
        ...(c.adaptive_daily===true?{dailyComboHistory:state.dailyComboHistory,dailyComboHistorySignature:state.dailyComboHistorySignature,dailyNoResultKey:state.dailyNoResultKey}:{}),
        publishedNames:[...state.names].filter(([id])=>id>4294967296).slice(0,500),
        notice:state.notice,error:state.error,scrollY:window.scrollY,people:state.people,retry:state.retry,autoPending:state.autoPending}));
    } catch { try {sessionStorage.removeItem(key);} catch {} }
  }
  function cancel() {
    ++state.sequence; state.controller?.abort(); state.controller=null; state.busy=false;
    clearTimeout(state.autoTimer);state.autoTimer=null;
    clearTimeout(state.generationDeadline);state.generationDeadline=null;
  }
  function archivePreviousDaily(previous) {
    let archive=document.getElementById('meal-previous-plan');
    if(previous){
      if(!archive){
        archive=document.createElement('details');archive.id='meal-previous-plan';archive.className='panel';
        const heading=document.createElement('summary');archive.append(heading);
        $('meal-summary').before(archive);archive.append($('meal-summary'),$('meal-cards'));
      }
      const context=dailyResultKey(conditions());
      if(archive.dataset.context!==context){archive.open=false;archive.dataset.context=context;}
      archive.firstElementChild.textContent='Xem mâm trước — không phải đề xuất cho '+state.people+' người';
    }else if(archive){
      archive.before($('meal-summary'),$('meal-cards'));archive.remove();
    }
  }
  function controls() {
    const p=state.view?.data.plan, dirty=!!p&&!!(state.view.signature!==signature(conditions())||dailyOnly()&&layoutMismatch()||
      state.view.conditions.preferences&&state.metadata&&state.view.data.metadata_version!==state.metadata.metadata_version);
    const working=state.busy||state.autoTimer!==null;
    const previousDaily=dailyOnly()&&!!p&&(dirty||state.dailyNoResultKey===dailyResultKey(conditions()));
    archivePreviousDaily(previousDaily);
    $('meal-generate').disabled=!state.ready||working;
    $('meal-regenerate').disabled=!p||working;
    $('meal-retry').disabled=!state.ready||working;
    $('meal-loading').classList.toggle('hidden',!working);
    $('meal-results').setAttribute('aria-busy',String(working));
    $('meal-stale').classList.toggle('hidden',!dirty&&!previousDaily);
    $('meal-stale').textContent=previousDaily?'Chưa có đề xuất hợp lệ cho '+state.people+' người. Mâm trước chỉ được lưu để tham khảo và giữ ghim; khẩu phần và danh sách đi chợ cũ không phải kết quả mới.':layoutMismatch()?'Mâm cũ chưa khớp cấu trúc cho '+state.people+' người. Mâm và ghim được giữ trong lúc hệ thống ghép lại.':'Đang cập nhật mâm theo lựa chọn mới; mâm hiện tại và các món ghim được giữ trong lúc tải.';
      'Bộ lọc đã đổi. Mâm sẽ tự cập nhật; món ghim được giữ lại.';
    $('meal-shopping').classList.toggle('hidden',!p||dirty||previousDaily);
    $('meal-daily-service')?.classList.toggle('hidden',!dailyOnly()||!p||dirty||previousDaily);
    if(!dailyOnly()&&$('meal-portion-summary')?.parentElement.id==='meal-daily-service')
      $('meal-copy-feedback').before($('meal-portion-summary'));
    $('meal-context').classList.toggle('hidden',!p||dirty||previousDaily);
    portionControls();
    $('meal-manual').classList.toggle('hidden',state.layoutMode!=='custom');
    $('meal-selected').closest('section').classList.toggle('hidden',['guests','drinking'].includes(state.preferences.occasion));
    renderFilters();
    for (const id of ['meal-ingredient-search',...Object.keys(fields)]) $(id).disabled=!state.ready;
    $('meal-max-missing').disabled=!state.ready||['guests','drinking'].includes(state.preferences.occasion);
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
    $('meal-season-field').classList.toggle('hidden',!dailyOnly());
    $('meal-season').disabled=!state.ready||!dailyOnly();
    $('meal-season').value=state.season;
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
  const portionPayload = () => ({recipe_ids:state.view?.data.plan?.items.map(i=>i.recipe_id)||[],people:state.people,
    adults:state.adults,children:state.children,layout_mode:state.layoutMode,occasion:['guests','drinking'].includes(state.preferences.occasion)?state.preferences.occasion:'daily'});
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
  function validServiceAssessment(value,people,recipeIDs,occasion) {
    if(value===null||value===undefined)return occasion!=='daily';
    if(!value||value.method!=='source_servings_by_role'||!decimal(value.requested_servings)||
       value.requested_servings!==people||!text(value.note,500)||!Array.isArray(value.groups)||value.groups.length>6)return false;
    const seen=new Set();
    for(const group of value.groups){
      if(!text(group.role,80)||!text(group.label)||!decimal(group.requested_servings)||group.requested_servings!==people||
         !(group.source_capacity===null||decimal(group.source_capacity))||
         !(group.adjustment_factor===null||decimal(group.adjustment_factor))||
         !['verified','estimated','unknown'].includes(group.status)||!Array.isArray(group.recipes)||
         !group.recipes.length||group.recipes.length>7)return false;
      if(group.status==='unknown'?(group.source_capacity!==null||group.adjustment_factor!==null):
         group.source_capacity===null||group.adjustment_factor===null)return false;
      for(const recipe of group.recipes){
        if(!recipeIDs.includes(recipe.recipe_id)||seen.has(recipe.recipe_id)||
           !(recipe.source_servings===null||decimal(recipe.source_servings))||
           !(recipe.target_servings===null||decimal(recipe.target_servings))||
           !['verified','estimated','unknown'].includes(recipe.status))return false;
        seen.add(recipe.recipe_id);
      }
    }
    return seen.size===recipeIDs.length&&recipeIDs.every(id=>seen.has(id));
  }
  function validDailyDemo(value,payload) {
    return payload.layout_mode==='automatic'&&payload.occasion==='daily'&&value?.version==='daily-demo-food-v1'&&
      ['conditional','risk','surplus','unknown'].includes(value.status)&&value.requested!==undefined&&decimal(value.requested)&&
      (value.meal_equivalents===null||decimal(value.meal_equivalents))&&decimal(value.main_equivalents)&&
      decimal(value.reference_g)&&decimal(value.standalone_reference_g)&&text(value.note)&&
      Array.isArray(value.recipes)&&value.recipes.length===payload.recipe_ids.length&&
      value.recipes.every((r,i)=>r.recipe_id===payload.recipe_ids[i]&&['estimated','unknown'].includes(r.status)&&
        ['shared','standalone'].includes(r.context)&&decimal(r.prepared_g)&&decimal(r.broth_ml)&&
        (r.dish_servings===null||decimal(r.dish_servings))&&(r.meal_equivalents===null||decimal(r.meal_equivalents))&&
        Array.isArray(r.drivers)&&Array.isArray(r.issues));
  }
  function validPortions(d,payload) {
    if (!d||d.dataset_version!==state.dataset||d.calculation_version!=='portion-v1'||d.people!==payload.people||
        d.adults!==payload.adults||d.children!==payload.children||d.occasion!==payload.occasion||
        !(d.daily_demo?validDailyDemo(d.daily_demo,payload)&&d.daily_demo.requested===d.equivalent_people:validServiceAssessment(d.service_assessment,d.equivalent_people,payload.recipe_ids,payload.occasion))||
        !decimal(d.equivalent_people)||!decimal(d.child_equivalent)||typeof d.policy_note!=='string'||
        !Array.isArray(d.portion_groups)||!d.portion_groups.every(g=>text(g.label)&&text(g.unit)&&
          ['gross','prepared'].includes(g.measurement_basis)&&['COMPLETE','INCOMPLETE'].includes(g.status)&&
          (g.target===null||decimal(g.target))&&(g.reason===null||typeof g.reason==='string'))||
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
  const dailyOnly=()=>state.layoutMode==='automatic'&&(state.preferences.occasion||'daily')==='daily';
  function dailyBeverageReason(reason){
    const parts=String(reason||'').replace('Admin phân loại phù hợp kiểu mâm đã chọn.','')
      .replace('Admin phân loại phù hợp mùa ','Hợp mùa ').replace(' theo mô tả Admin','')
      .replace('Có thể dùng mát theo cách pha đã lưu','Dùng mát').replace('Có thể dùng ấm theo cách pha đã lưu','Dùng ấm')
      .split(/[.!?]+\s*/).map(part=>part.trim()).filter(Boolean).slice(0,2);
    return parts.length?parts.map((part,index)=>index?part.charAt(0).toLocaleLowerCase('vi')+part.slice(1):part).join('; ')+'.':'Đồ uống không cồn dùng kèm mâm.';
  }
  function renderDailyBeverages(beverages){
    const suggestions=beverages.slice(0,2);
    if(!suggestions.length){$('meal-beverages').innerHTML='<p class="meal-beverage-empty">Chưa có đồ uống phù hợp với điều kiện đã chọn.</p>';return;}
    // The current advisory API has amount:null: input water is not a measured
    // finished yield or a per-person drink quantity. Do not infer either here.
    $('meal-beverages').innerHTML='<div class="meal-beverage-grid" role="list">'+suggestions.map(b=>
      '<article class="meal-beverage-card" role="listitem"><figure class="recipe-media" data-recipe-media data-recipe-id="'+b.recipe_id+'" data-recipe-title="'+esc(b.title)+'"></figure>'+
      '<div class="meal-beverage-copy"><a href="/recipes/'+b.recipe_id+'">'+esc(b.title)+'</a><p>'+esc(dailyBeverageReason(b.reason))+'</p><small>Chưa có định lượng tham khảo</small></div></article>').join('')+'</div>';
    window.RecipeImages?.mount($('meal-beverages'));
  }
  let dailyCalculation=null, dailyContext=null, dailyChange=null;
  const dailyLabels={main:'Món chính',vegetable:'Món rau',soup:'Canh'};
  const shoppingUnit=(unit,name='')=>{
    if(unit==='piece'){
      const ingredient=name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d').trim();
      if(['chanh','ca chua','ot','su su','trung','trung ga','trung vit'].includes(ingredient))return 'quả';
      if(['khoai tay','khoai lang','ca rot','hanh tay','hanh tim'].includes(ingredient))return 'củ';
      return 'piece (chưa rõ loại)';
    }
    return {clove:'tép',stalk:'nhánh',bunch:'bó',leaf:'lá',slice:'lát',tbsp:'muỗng canh',tsp:'muỗng cà phê',cup:'cốc',bowl:'bát',can:'lon',pack:'gói',l:'lít'}[unit]||unitLabel(unit);
  };
  // Shopping presentation only: never mutate API quantities or aggregate here.
  function formatShoppingQuantity(q,unit=q.unit) {
    const parse=value=>{const [whole,part='']=String(value).split('.');return {n:BigInt(whole+part),d:10n**BigInt(part.length)};};
    const count=['piece','clove','stalk','bunch','leaf','slice','tbsp','tsp','cup','bowl','can','pack','source_spoon','source_bowl','source_stack','quả','tép','củ','muỗng'].includes(unit);
    const digits=['g','ml'].includes(unit)?1:2, scale=10n**BigInt(digits);
    const decimalText=ticks=>{
      const raw=String(ticks).padStart(digits+1,'0');
      const fraction=raw.slice(-digits).replace(/0+$/,'');
      return raw.slice(0,-digits)+(fraction?','+fraction:'');
    };
    const valueText=(v,direction='nearest',approxFraction=true)=>{
      if(count){
        for(const denominator of [1n,2n,3n,4n,6n,8n]){
          const numerator=(v.n*denominator*2n+v.d)/(2n*v.d);
          const delta=v.n*denominator-numerator*v.d, error=delta<0n?-delta:delta;
          if(numerator>0n&&(error===0n||approxFraction&&direction==='nearest'&&error*1000000n<=2n*v.d*denominator)){
            const whole=numerator/denominator,remainder=numerator%denominator;
            return {text:remainder?(whole?whole+' ':'')+remainder+'/'+denominator:String(whole),changed:error!==0n};
          }
        }
      }
      const scaled=v.n*scale;
      const ticks=direction==='floor'?scaled/v.d:direction==='ceil'?(scaled+v.d-1n)/v.d:(scaled*2n+v.d)/(2n*v.d);
      if(ticks===0n&&v.n>0n&&direction==='nearest')return {text:'< '+decimalText(1n),changed:false};
      return {text:decimalText(ticks),changed:ticks*v.d!==scaled};
    };
    if(q.amount_kind==='exact'){
      const v=valueText(parse(q.quantity_value));return (v.changed?'≈ ':'')+v.text;
    }
    const low=parse(q.quantity_min),high=parse(q.quantity_max);
    const width=high.n*low.d-low.n*high.d,denominator=low.d*high.d;
    // Only collapse the microscopic outward rounding envelope, not a real range.
    if(q.precision==='outward_6dp'&&width>=0n&&width*1000000n<=2n*denominator){
      const midpoint={n:low.n*high.d+high.n*low.d,d:2n*denominator};
      const v=valueText(midpoint);return (v.text.startsWith('< ')?'':'≈ ')+v.text;
    }
    return valueText(low,'floor',false).text+'–'+valueText(high,'ceil',false).text;
  }
  // End shopping presentation.
  const dailyStatuses={conditional:'Phù hợp có điều kiện',risk:'Có nguy cơ thiếu',surplus:'Dư đáng kể',unknown:'Chưa xác định'};
  function dailyReasons() {
    if(!dailyOnly()||!state.view?.data.plan)return;
    const plan=state.view.data.plan;
    const calculation=state.view.data.seasonal_assessment&&(!dailyCalculation||
      dailyCalculation.people!==state.people||dailyCalculation.adults!==state.adults||dailyCalculation.children!==state.children||
      !same(dailyCalculation.recipe_ids,plan.items.map(i=>i.recipe_id)))?null:dailyCalculation;
    const assessment=calculation?.daily_demo?{assessment_status:calculation.daily_demo.status,limitations:[calculation.daily_demo.note]}:calculation?.service_assessment;
    const reasons=[assessment?dailyStatuses[assessment.assessment_status]+': '+
      (assessment.assessment_status==='risk'?'cần kiểm tra phần món chính và lượng ăn thực tế.':assessment.assessment_status==='surplus'?'công thức gốc có thể nhiều hơn nhu cầu.':assessment.assessment_status==='unknown'?'còn thiếu dữ liệu khẩu phần.':'ước tính theo công thức gốc, chưa bảo đảm mọi người ăn đủ.'):'Đang kiểm tra khả năng phục vụ theo dữ liệu các món.'];
    const counts=state.view.data.counts;
    reasons.push('Mâm gồm '+groups.filter(g=>counts[g]).map(g=>counts[g]+' '+dailyLabels[g].toLowerCase()).join(', ')+'.');
    const seasonal=state.view.data.seasonal_assessment;
    if(seasonal)reasons.push(seasonal.summary);
    const matched=(plan.required_ids||[]).filter(id=>state.selected.has(id));
    if(matched.length)reasons.push('Có sử dụng '+matched.length+' nguyên liệu bạn đánh dấu có sẵn; chưa biết lượng tồn.');
    else if(Object.keys(state.view.conditions.preferences||{}).some(k=>['diet','region'].includes(k))||state.view.conditions.excluded_ids?.length)
      reasons.push('Các món đã qua bộ lọc đang chọn và danh sách nguyên liệu không ăn.');
    if(reasons.length<3&&assessment?.limitations?.length)reasons.push(assessment.limitations[0]);
    if(reasons.length<3&&calculation){
      const estimated=calculation.recipes.filter(r=>r.data_status==='estimated').length;
      if(estimated)reasons.push('Có '+estimated+' món dùng số liệu tham khảo; hãy kiểm tra lại lượng ăn thực tế.');
    }
    if(dailyChange)reasons.push(dailyChange);
    const detail=dailyContext?'<details><summary>Xem chi tiết cách đánh giá</summary>'+(state.view.data.daily_layout_reason?'<p>'+esc(state.view.data.daily_layout_reason)+'</p>':'')+dailyContext.reasons.map(r=>'<p>'+esc(r)+'</p>').join('')+(dailyContext.warnings||[]).map(w=>'<p>'+esc(w)+'</p>').join('')+dailyContext.items.map(i=>'<p><strong>'+esc(i.title)+'</strong>: '+esc(i.reasons.join(' '))+'</p>').join('')+'</details>':'';
    const seasonDetail=seasonal?'<details><summary>Vì sao hợp mùa đã chọn?</summary><p>Quy tắc gợi ý demo, không xác nhận mùa thu hoạch hay lợi ích dinh dưỡng; mùa và thời tiết là hai lựa chọn độc lập.</p>'+seasonal.items.map(i=>'<p><strong>'+esc(plan.items.find(r=>r.recipe_id===i.recipe_id)?.title)+'</strong>: '+esc(i.reasons.join(' '))+'</p>').join('')+'</details>':'';
    $('meal-reasons').innerHTML='<ul>'+reasons.slice(0,4).map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul>'+detail+seasonDetail;
  }
  function renderDailyDemo(data) {
    const model=data.daily_demo, summary=$('meal-portion-summary');
    let panel=$('meal-daily-service');
    if(!panel){panel=document.createElement('section');panel.id='meal-daily-service';panel.className='panel';$('meal-shopping').before(panel);}
    panel.classList.remove('hidden');panel.append(summary);
    const titles=new Map(state.view.data.plan.items.map(i=>[i.recipe_id,i.title]));
    const grams=value=>formatShoppingQuantity({unit:'g',amount_kind:'exact',quantity_value:value,quantity_min:value,quantity_max:value,precision:'exact'});
    summary.innerHTML='<h3>Khả năng phục vụ · ƯỚC TÍNH</h3><p>Yêu cầu: <strong>'+data.people+' người</strong> · '+esc(customServingLabel(data.equivalent_people))+' suất người lớn tương đương.</p>'+
      '<p><strong>'+esc(dailyStatuses[model.status])+'</strong>'+(model.meal_equivalents===null?'':': khoảng '+esc(customServingLabel(model.meal_equivalents))+' phần bữa ăn tham khảo.')+'</p>'+
      '<p>Ước tính thử nghiệm từ nguyên liệu của mâm; không phải cam kết đủ ăn hay đủ dinh dưỡng. Mỗi món giữ nguyên một công thức.</p>'+
      '<details><summary>Xem khẩu phần từng món</summary><ul>'+model.recipes.map(r=>'<li><strong>'+esc(titles.get(r.recipe_id))+'</strong>: '+(r.status==='unknown'?'Chưa xác định':esc(grams(r.prepared_g))+' g thực phẩm sau quy đổi demo; khoảng '+esc(customServingLabel(r.dish_servings))+(r.context==='standalone'?' phần món ăn riêng':r.role==='soup'?' phần cái của canh':' phần món ăn kèm'))+
      (r.broth_ml!=='0'?'; nước đầu vào '+esc(r.broth_ml)+' ml, không cộng thành thịt/rau':'')+'.</li>').join('')+'</ul></details>'+
      '<details><summary>Cách ước tính demo</summary><p>Mốc bữa ăn kèm cơm: '+esc(model.reference_g)+' g thực phẩm chín ăn được quy đổi; món ăn riêng dùng '+esc(model.standalone_reference_g)+' g. Không dùng trọng số 55/30/15 hoặc số suất mặc định 4.</p>'+
      '<p>Món chính phải đóng góp ít nhất 50% nhu cầu quy chiếu. Chỉ nhận mâm từ 100–130% nhu cầu. Nước, dầu và gia vị không được tính thành thức ăn chính. Các hệ số hao hụt, nở và khối lượng đơn vị đếm đều là giả định demo.</p>'+
      model.recipes.map(r=>'<p>'+esc(titles.get(r.recipe_id))+': '+r.drivers.map(x=>esc(x.name)+' '+esc(x.input_g)+' g × '+esc(x.edible_fraction)+' × '+esc(x.cooking_factor)+' = '+esc(grams(x.prepared_g))+' g').join('; ')+'</p>').join('')+'</details>';
    dailyCalculation=data;dailyReasons();
  }
  function renderDailyService(data) {
    if(data.daily_demo){renderDailyDemo(data);return;}
    const assessment=data.service_assessment, summary=$('meal-portion-summary');
    let panel=$('meal-daily-service');
    if(!panel){panel=document.createElement('section');panel.id='meal-daily-service';panel.className='panel';panel.setAttribute('aria-label','Khả năng phục vụ');$('meal-shopping').before(panel);}
    panel.classList.remove('hidden');panel.append(summary);
    const known=assessment?.meal_capacity!==null&&assessment?.meal_capacity!==undefined;
    const status=assessment?.assessment_status||'unknown';
    const groupText=(assessment?.groups||[]).map(g=>'<li><strong>'+esc(g.label)+'</strong>: '+
      (g.source_capacity===null?'chưa rõ số suất gốc':esc(g.source_capacity)+' suất món theo công thức gốc')+
      (g.source_capacity!==null&&Number(g.source_capacity)<Number(data.equivalent_people)?' — cần chia phần nhỏ hơn nếu mọi người cùng ăn.':'.')+'</li>').join('');
    const titles=new Map(state.view.data.plan.items.map(i=>[i.recipe_id,i.title]));
    const capacities=Object.fromEntries((assessment?.groups||[]).map(g=>[g.role,g.source_capacity]));
    const calculation=known?['main','vegetable','soup'].map((role,i)=>['0,55','0,30','0,15'][i]+' × '+String(capacities[role]||'0').replace('.',',')).join(' + ')+' = '+String(assessment.meal_capacity).replace('.',','):null;
    summary.innerHTML='<h3>Khả năng phục vụ</h3><p>Yêu cầu: <strong>'+data.people+' người</strong> · '+esc(dailyStatuses[status])+'</p>'+
      '<p>'+(known?'Ước tính '+(status==='risk'?'còn hạn chế':status==='surplus'?'có thể dư nhiều':'gần mức nhu cầu')+' theo công thức gốc; chưa thể kết luận chính xác phục vụ được bao nhiêu người.':'Chưa đủ dữ liệu để ước tính khả năng phục vụ cả mâm.')+'</p>'+
      (status==='risk'?'<p>Bạn có thể bấm Đổi cả mâm để xem phương án khác. Hệ thống không tự thêm món để báo đủ khẩu phần.</p>':'')+
      '<ul>'+groupText+'</ul><p>Suất món chỉ mô tả phần món đó, không phải một bữa ăn đầy đủ.</p>'+
      '<details><summary>Xem chi tiết khẩu phần</summary><p>'+esc(assessment?.note||'Thiếu dữ liệu đánh giá.')+'</p>'+
      ((assessment?.limitations||[]).length?'<p>'+esc(assessment.limitations.join(' '))+'</p>':'')+
      (known?'<p>Phép tính: '+esc(calculation)+'. Mốc tham chiếu: '+esc(data.equivalent_people)+'. Phần rau nhiều làm tăng điểm bình quân, không tự bù được phần món chính hoặc canh ít. Đây không phải số người ăn đủ.</p>':'')+
      (assessment?.groups||[]).map(g=>'<p><strong>'+esc(g.label)+'</strong>: '+g.recipes.map(r=>esc(titles.get(r.recipe_id)||'Món ăn')+' — '+(r.source_servings===null?'chưa rõ suất gốc':esc(r.source_servings)+' suất gốc')+' ('+(r.status==='verified'?'đã xác minh':r.status==='estimated'?'ước tính':'cần kiểm tra')+')').join('; ')+'</p>').join('')+
      '<p>Suất gốc đọc từ recipes.servings trong MySQL, không đặt bằng số người đang chọn. Nếu nhiều món cùng 4 suất, đó là giá trị đang lưu của từng công thức; trạng thái ước tính/cần kiểm tra không phải dữ liệu đã xác minh.</p>'+
      '<p>Giữ nguyên một công thức mỗi món. Lượng nguyên liệu không thay đổi theo số người. Số suất không chứng minh mâm cân đối dinh dưỡng.</p></details>';
    dailyCalculation=data;dailyReasons();
  }
  // Custom portion presentation only. Never changes calculator inputs/outputs.
  function customServingLabel(value) {
    if(value===null||value===undefined||!decimal(String(value)))return 'Chưa xác định';
    const number=Number(value);
    if(!Number.isFinite(number))return 'Chưa xác định';
    const rounded=new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2}).format(number);
    return (Math.abs(number-Number(number.toFixed(2)))>1e-9?'≈ ':'')+rounded;
  }
  function customPortionPresentation(data,titles) {
    const known=value=>value!==null&&value!==undefined&&decimal(String(value))&&Number(value)>0;
    const groups=data.service_assessment?.groups||[];
    const members=new Map(groups.flatMap(group=>group.recipes.map(recipe=>[recipe.recipe_id,{recipe,group}])));
    const statusLabel=status=>status==='verified'?'Đã xác minh':status==='estimated'?'ƯỚC TÍNH':status==='needs_review'?'Cần duyệt':'Chưa xác định';
    const rows=data.recipes.map(recipe=>{
      const member=members.get(recipe.recipe_id);
      const base=recipe.base_servings??member?.recipe.source_servings??null;
      // A null group factor means the backend kept original quantities. Its
      // per-recipe target can equal base_servings without a valid allocation.
      const allocated=member?known(member.group.adjustment_factor)&&known(member.recipe.target_servings):
        known(recipe.base_servings)&&known(recipe.target_servings);
      return {recipe,base,allocated,target:member?member.recipe.target_servings:recipe.target_servings,
        title:titles.get(recipe.recipe_id)||'Món trong mâm'};
    });
    const incomplete=rows.filter(row=>row.recipe.status!=='COMPLETE'||!row.allocated);
    const complete=data.totals_complete&&incomplete.length===0&&data.portion_groups.every(group=>group.status==='COMPLETE');
    const needsReview=rows.some(row=>row.recipe.data_status==='needs_review');
    const estimated=rows.some(row=>row.recipe.data_status==='estimated');
    const badge=[estimated?'ƯỚC TÍNH':'',needsReview?'Cần duyệt':'',
      rows.some(row=>!['verified','estimated','needs_review'].includes(row.recipe.data_status))?'Chưa xác định':''].filter(Boolean).join(' · ');
    const sourceRows=rows.map(row=>'<li>'+esc(row.title)+': '+
      (row.base===null||row.base===undefined?'Chưa xác định số suất gốc':esc(customServingLabel(row.base))+' suất gốc')+
      ' · '+esc(statusLabel(row.recipe.data_status))+
      (!row.allocated&&row.base!==null?'; số suất này chưa đủ căn cứ để phân bổ.':'')+'</li>').join('');
    const allocatedRows=rows.map(row=>'<li>'+esc(row.title)+': '+(row.allocated?
      'mục tiêu phân bổ '+esc(customServingLabel(row.target))+' suất của món; '+
        (row.recipe.status==='COMPLETE'?'đã tính các lượng nguyên liệu.':'một số nguyên liệu chưa tính được.'):
      'chưa xác định được mục tiêu phân bổ; các lượng đọc được giữ theo công thức gốc.')+'</li>').join('');
    const issues=incomplete.map(row=>'<li>'+esc(row.title)+': '+(!row.allocated?'chưa đủ cơ sở phân bổ theo số người.':'chưa tính đủ nguyên liệu.')+'</li>').join('');
    const html='<strong>Định lượng chuẩn bị cho '+data.people+' người</strong>'+
      '<p>Nhu cầu: <strong>'+esc(customServingLabel(data.equivalent_people))+' suất người lớn tương đương</strong>.</p>'+
      '<p>'+(complete?'Đã tính định lượng tham khảo cho '+data.people+' người.':'Chưa tính đầy đủ định lượng chuẩn bị cho '+data.people+' người.')+
      (badge?' · '+esc(badge):'')+'</p>'+
      (issues?'<p>Món chưa đủ cơ sở tính:</p><ul>'+issues+'</ul>':'')+
      '<p>Đây là định lượng chuẩn bị theo nhu cầu, không phải kết luận mâm gốc đủ ăn hoặc đủ dinh dưỡng.</p>'+
      '<details><summary>Số suất công thức gốc (trước điều chỉnh)</summary><ul>'+sourceRows+'</ul></details>'+
      '<details><summary>Định lượng đã phân bổ</summary><ul>'+allocatedRows+'</ul>'+
      '<p>Lượng nguyên liệu tính được hiển thị trong Danh sách đi chợ; các dòng chưa tính được được ghi chú riêng.</p></details>'+
      '<details><summary>Cách tính và giới hạn dữ liệu</summary>'+
      '<p>Nhu cầu = '+data.adults+' người lớn + '+esc(customServingLabel(data.child_equivalent))+' × '+data.children+' trẻ em = '+esc(customServingLabel(data.equivalent_people))+
      ' suất người lớn tương đương. Hệ số trẻ em là giả định nghiệp vụ có thể cấu hình, không phải chuẩn dinh dưỡng.</p>'+
      '<p>Mỗi nhóm món được phân bổ riêng theo số suất gốc hợp lệ. Không cộng số suất các nhóm thành sức phục vụ toàn mâm. Khi nhóm thiếu căn cứ, lượng giữ nguyên không có nghĩa đã phân bổ đủ.</p>'+
      '<ul>'+groups.map(group=>'<li>'+esc(group.label)+': '+(group.source_capacity===null?'chưa xác định tổng số suất gốc':esc(customServingLabel(group.source_capacity))+' suất gốc')+
        (group.adjustment_factor===null?'; chưa xác định hệ số phân bổ.':'; hệ số phân bổ '+esc(customServingLabel(group.adjustment_factor))+'.')+'</li>').join('')+'</ul></details>';
    return {html,complete};
  }
  // End custom portion presentation.
  function renderCalculatedShopping(data,unscaledLines) {
    const titles=new Map(state.view.data.plan.items.map(i=>[i.recipe_id,i.title]));
    const amount=(q,unit=q.unit)=>esc(formatShoppingQuantity(q,unit));
    const labels={required:'B\u1eaft bu\u1ed9c',optional:'T\u00f9y ch\u1ecdn',unknown:'Ch\u01b0a r\u00f5'};
    const lists={required:[],optional:[],unknown:[]};
    for(const item of data.known_ingredients){
      const bucket=item.requirement in lists?item.requirement:'unknown';
      if(dailyOnly()){
        lists[bucket].push('<div class="shopping-entry"><strong>'+esc(item.name)+': '+amount(item)+' '+esc(shoppingUnit(item.unit,item.name))+'</strong>'+
          '<details><summary>'+labels[bucket]+(state.selected.has(item.ingredient_id)?' · Có sẵn':'')+' · Xem món sử dụng</summary><ul>'+
          item.uses.map(use=>'<li>'+esc(titles.get(use.recipe_id))+': '+amount(use,item.unit)+' '+esc(shoppingUnit(item.unit,item.name))+'</li>').join('')+'</ul></details></div>');
        continue;
      }
      lists[bucket].push('<div class="shopping-entry"><strong>'+esc(item.name)+': '+amount(item)+' '+esc(shoppingUnit(item.unit,item.name))+'</strong>'+
        '<p class="field-help">'+labels[bucket]+(state.selected.has(item.ingredient_id)?' \u00b7 \u0110\u00e3 c\u00f3 s\u1eb5n':'')+' \u00b7 '+(item.mergeable?(item.uses.length>1?'\u0110\u00e3 g\u1ed9p c\u00e1c d\u00f2ng t\u01b0\u01a1ng th\u00edch.':'C\u00f3 th\u1ec3 g\u1ed9p v\u1edbi d\u00f2ng t\u01b0\u01a1ng th\u00edch.'):'Gi\u1eef ri\u00eang t\u1eebng d\u00f2ng; kh\u00f4ng \u0111\u1ee7 c\u0103n c\u1ee9 \u0111\u1ec3 g\u1ed9p.')+
        (item.precision==='outward_6dp'?' \u00b7 Kho\u1ea3ng \u0111\u00e3 l\u00e0m tr\u00f2n ra ngo\u00e0i':'')+'</p><ul>'+
        item.uses.map(use=>'<li>'+esc(titles.get(use.recipe_id))+': '+amount(use,item.unit)+' '+esc(shoppingUnit(item.unit,item.name))+'</li>').join('')+'</ul></div>');
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
    const summary=$('meal-portion-summary');
    const customPresentation=summary&&state.layoutMode==='custom'?customPortionPresentation(data,titles):null;
    if(customPresentation)summary.innerHTML=customPresentation.html;
    else if(summary){
      const allocationMissing=data.portion_groups.some(g=>g.status!=='COMPLETE');
      const referenceOnly=data.recipes.some(r=>r.data_status!=='verified');
      const status=referenceOnly?'\u0110\u1ecbnh l\u01b0\u1ee3ng tham kh\u1ea3o'+(allocationMissing?' \u00b7 Ch\u01b0a ph\u00e2n b\u1ed5 \u0111\u1ee7 m\u00e2m':!data.totals_complete?' \u00b7 Thi\u1ebfu \u0111\u1ecbnh l\u01b0\u1ee3ng':''):allocationMissing?'Ch\u01b0a \u0111\u1ee7 d\u1eef li\u1ec7u':!data.totals_complete?'Thi\u1ebfu \u0111\u1ecbnh l\u01b0\u1ee3ng':'\u0110\u1ee7 \u0111\u1ecbnh l\u01b0\u1ee3ng';
      const service=data.service_assessment;
      const layoutReason=state.view?.data.daily_layout_reason;
      const planTitles=new Map((state.view?.data.plan?.items||[]).map(i=>[i.recipe_id,i.title]));
      const mealCapacity=service?.meal_capacity;
      const mealSummary=mealCapacity===null||mealCapacity===undefined?'': '<p>Suc phuc vu ca mam (uoc tinh): '+esc(mealCapacity)+' / '+esc(data.equivalent_people)+' suat bua an'+(Number(mealCapacity)<Number(data.equivalent_people)?' ? Chua dap ung':' ? Dap ung theo mo hinh thu nghiem')+'</p>';
      const serviceDetails=service?'<details><summary>Kh\u1ea3 n\u0103ng ph\u1ee5c v\u1ee5 theo nh\u00f3m m\u00f3n</summary><ul>'+service.groups.map(g=>
        '<li><strong>'+esc(g.label)+'</strong>: '+(g.source_capacity===null?'Ch\u01b0a x\u00e1c \u0111\u1ecbnh':esc(g.source_capacity)+' su\u1ea5t g\u1ed1c')+' \u00b7 c\u1ea7n '+esc(g.requested_servings)+' su\u1ea5t'+
        ' ? Dong gop theo vai tro trong ca mam'+
        ' \u00b7 '+(g.status==='verified'?'\u0110\u00e3 x\u00e1c minh':g.status==='estimated'?'\u01af\u1edaC T\u00cdNH':'Ch\u01b0a x\u00e1c \u0111\u1ecbnh')+
        '<ul>'+g.recipes.map(r=>'<li>'+esc(planTitles.get(r.recipe_id)||'M\u00f3n trong m\u00e2m')+': '+
          (r.source_servings===null?'Ch\u01b0a x\u00e1c \u0111\u1ecbnh':esc(r.source_servings)+' su\u1ea5t g\u1ed1c')+
          ''+
          ' \u00b7 '+(r.status==='verified'?'\u0110\u00e3 x\u00e1c minh':r.status==='estimated'?'\u01af\u1edaC T\u00cdNH':'Ch\u01b0a x\u00e1c \u0111\u1ecbnh')+'</li>').join('')+'</ul></li>'
      ).join('')+'</ul><small>'+esc(service.note)+'</small></details>':'';
      summary.innerHTML='<strong>Kh\u1ea9u ph\u1ea7n cho '+data.people+' ng\u01b0\u1eddi</strong> \u00b7 '+
        status+ (data.recipes.some(r=>r.data_status==='estimated')?' \u00b7 \u01af\u1edaC T\u00cdNH':data.recipes.some(r=>r.data_status!=='verified')?' \u00b7 D\u1eef li\u1ec7u c\u1ea7n duy\u1ec7t':' \u00b7 D\u1eef li\u1ec7u \u0111\u00e3 x\u00e1c minh')+
        ' \u00b7 '+esc(data.equivalent_people)+' su\u1ea5t t\u01b0\u01a1ng \u0111\u01b0\u01a1ng'+
        (layoutReason?'<p>'+esc(layoutReason)+'</p>':'')+
        mealSummary+serviceDetails+(data.portion_groups.length?'<details><summary>Xem \u0111\u1ecbnh m\u1ee9c tham chi\u1ebfu theo nh\u00f3m</summary><ul>'+data.portion_groups.map(g=>
          '<li>'+esc(g.label)+': '+(g.target===null?'Ch\u01b0a \u0111\u1ee7 d\u1eef li\u1ec7u':esc(g.target)+' '+esc(g.unit))+
          ' ('+(g.measurement_basis==='gross'?'nguy\u00ean li\u1ec7u \u0111\u1ea7u v\u00e0o':'th\u00e0nh ph\u1ea9m')+')'+
          (g.reason?' \u00b7 '+esc(g.reason):'')+'</li>').join('')+'</ul><small>'+esc(data.policy_note)+'</small></details>':'');
    }
    $('meal-shopping-note').textContent=data.recipes.some(r=>r.data_status!=='verified')?
      'Định lượng tham khảo từ công thức và các giả định đã lưu, không phải khuyến nghị dinh dưỡng chính thức. '+
      (data.totals_complete?'Chỉ gộp các lượng có đơn vị, dạng nguyên liệu và cơ sở đo tương thích.':'Các dòng chưa phân bổ được vẫn giữ lượng gốc và ghi rõ chưa nhân.'):
      data.totals_complete?
      'L\u01b0\u1ee3ng \u0111\u00e3 t\u00ednh d\u1ef1a tr\u00ean kh\u1ea9u ph\u1ea7n g\u1ed1c v\u00e0 \u0111\u1ecbnh l\u01b0\u1ee3ng c\u1ea5u tr\u00fac. C\u00e1c d\u00f2ng ch\u1ec9 \u0111\u01b0\u1ee3c g\u1ed9p khi \u0111\u01a1n v\u1ecb v\u00e0 th\u00f4ng tin t\u01b0\u01a1ng th\u00edch \u0111\u00e3 x\u00e1c nh\u1eadn.':
      'Danh s\u00e1ch gi\u1eef c\u1ea3 l\u01b0\u1ee3ng \u0111\u00e3 t\u00ednh v\u00e0 th\u00e0nh ph\u1ea7n ch\u01b0a x\u00e1c \u0111\u1ecbnh. D\u00f2ng ghi ?ch\u01b0a nh\u00e2n? gi\u1eef nguy\u00ean theo c\u00f4ng th\u1ee9c; kh\u00f4ng t\u1ef1 quy \u0111\u1ed5i ho\u1eb7c \u01b0\u1edbc l\u01b0\u1ee3ng.';
    if(dailyOnly()){
      renderDailyService(data);
      $('meal-shopping-note').textContent='Lượng gốc của các món đang chọn. Chỉ gộp nguyên liệu có đơn vị và cơ sở đo tương thích; xem nguồn theo từng món bên dưới.';
    }else if(customPresentation&&!customPresentation.complete){
      $('meal-shopping-note').textContent='Danh sách gồm lượng đã phân bổ và các lượng giữ nguyên khi chưa đủ cơ sở tính. Xem món còn thiếu dữ liệu ở trên; chỉ gộp các dòng có đơn vị và cơ sở đo tương thích.';
    }
  }
  function renderBaseShopping(plan) {
    if(!plan)return;
    const titles=new Map(plan.items.map(i=>[i.recipe_id,i.title]));
    $('meal-shopping-title').textContent='Danh s\u00e1ch \u0111i ch\u1ee3';
    $('meal-shopping-note').textContent='Danh s\u00e1ch nguy\u00ean li\u1ec7u theo c\u00f4ng th\u1ee9c; l\u01b0\u1ee3ng t\u00ednh \u0111\u01b0\u1ee3c s\u1ebd c\u1eadp nh\u1eadt theo s\u1ed1 ng\u01b0\u1eddi.';
    if($('meal-portion-summary'))$('meal-portion-summary').textContent=(state.layoutMode==='custom'?'Định lượng chuẩn bị cho ':'Kh\u1ea9u ph\u1ea7n cho ')+state.people+' ng\u01b0\u1eddi \u00b7 \u0110ang t\u00ednh';
    $('meal-shopping-unknown')?.replaceChildren();
    for (const [id,list] of [['meal-shopping-required',plan.shopping_list],['meal-shopping-optional',plan.optional_shopping_list]]) {
      $(id).innerHTML=list.map(i=>'<div class="shopping-entry"><strong>'+esc(i.name)+'</strong><ul>'+i.uses.map(u=>'<li>'+esc(titles.get(u.recipe_id))+': '+esc(u.quantity||'ch\u01b0a ghi \u0111\u1ecbnh l\u01b0\u1ee3ng')+(u.is_required?'':' (t\u00f9y ch\u1ecdn)')+'</li>').join('')+'</ul></div>').join('')||'<p>Kh\u00f4ng c\u1ea7n mua th\u00eam trong nh\u00f3m n\u00e0y.</p>';
    }
  }
  function queuePortions(delay=300) {
    cancelPortions(); portionControls();
    dailyCalculation=null;dailyContext=null;
    const c=state.calculation, payload=portionPayload(), sig=signature(payload), token=c.sequence;
    if (!payload.recipe_ids.length) return;
    if(dailyOnly()&&(layoutMismatch()||state.view.signature!==signature(conditions())||
        state.dailyNoResultKey===dailyResultKey(conditions())))return;
    renderBaseShopping(state.view?.data.plan);
    refreshContext();
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
        const summary=$('meal-portion-summary');
        if(summary)summary.textContent=(state.layoutMode==='custom'?'Định lượng chuẩn bị cho ':'Kh\u1ea9u ph\u1ea7n cho ')+payload.people+' ng\u01b0\u1eddi \u00b7 Ch\u01b0a t\u00ednh \u0111\u01b0\u1ee3c';
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
  function syncCustomPortionPeople(previousConditions) {
    if(state.layoutMode!=='custom'||!state.view?.data.plan)return false;
    // Only a people change can reuse this selection. Never clear stale filters.
    if(signature({...state.view.conditions,people:previousConditions.people})!==signature(previousConditions))return false;
    const c=conditions();
    state.view={...state.view,signature:signature(c),conditions:c,
      data:{...state.view.data,people:state.people}};
    return true;
  }
  function changePeople(delta,kind='adults') {
    const previousConditions=conditions();
    const previousAdults=state.adults,previousChildren=state.children;
    const previous=kind==='adults'?state.adults:state.children, value=previous+delta;
    if(!integer(value,0,12)||state.people+delta<1||state.people+delta>12)return;
    if(kind==='adults')state.adults=value;else state.children=value;
    const before=desiredCounts();state.people=state.adults+state.children;
    const p=state.view?.data.plan;
    if(syncCustomPortionPeople(previousConditions)){
      // People affect custom portions, never the user's recipe selection/layout.
      // Acknowledge this change so controls do not mark the retained plan stale.
      if(state.busy){cancel();state.autoPending=false;}
    }
    if(state.layoutMode==='automatic'&&(dailyOnly()||layoutMismatch()||state.autoPending||!p&&!sameCounts(before,countsForPeople(state.people)))) scheduleLayout();
    else {
      if(state.autoPending){cancel();state.autoPending=false;state.retry=null;message();$('meal-retry').classList.add('hidden');}
      controls();save();render();queuePortions();
    }
  }
  function scheduleLayout() {
    if(state.dailyComboHistorySignature!==null&&state.dailyComboHistorySignature!==dailyComboSignature(conditions())){
      state.dailyComboHistory=[];state.dailyComboHistorySignature=null;
    }
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
      '<button '+(['guests','drinking'].includes(state.preferences.occasion)?'hidden ':'')+'class="ingredient-action" type="button" data-select="'+id+'" aria-pressed="'+state.selected.has(id)+'">'+(state.selected.has(id)?'Đã có ✓':'Có sẵn')+'</button>'+
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
    try{const selected=sessionStorage.getItem(key+'-season');if(seasons.includes(selected))state.season=selected;}catch{}
    let staleIngredientSelection = false;
    try {
      const people=Number(sessionStorage.getItem(key+'-people')); if(integer(people,1,12))state.people=people;
      const saved=JSON.parse(sessionStorage.getItem(key));
      let household=null;try{household=JSON.parse(sessionStorage.getItem(key+'-people-groups'));}catch{}
      if(household&&integer(household.adults,0,12)&&integer(household.children,0,12)&&household.adults+household.children>=1&&household.adults+household.children<=12){state.adults=household.adults;state.children=household.children;state.people=household.adults+household.children;}
      else if(integer(people,1,12)){state.adults=people;state.children=0;}
      if (!saved) return;
      const savedOccasion=saved.conditions?.preferences?.occasion;
      if(saved.conditions?.layout_mode!=='custom'&&(!savedOccasion||!['daily','guests','drinking'].includes(savedOccasion))) {
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
      state.preferences={...(c.preferences||{})};$('meal-weather').value=c.weather||'';
      if(savedSnackMode){
        state.preferences.occasion='daily';
        state.autoPending=true;
        state.notice='Kiểu mâm Ăn vặt đã được bỏ. Đã chuyển sang Hằng ngày và sẽ tự cập nhật mâm.';
      }
      state.selected=new Set(c.ingredient_ids); state.excluded=new Set(c.excluded_ids);
      for (const [id,[name]] of Object.entries(fields)) $(id).value=c[name]??'';
      if (saved.view&&!savedSnackMode) {
        const v=saved.view;
        const storedSignature=signature(v.conditions);
        if (!validConditions(v.conditions)||v.signature!==storedSignature||!validData(v.data,v.conditions)) throw Error();
        state.view=v;
        syncCustomPortionPeople(conditions());
      }
      const planSlots=state.view?.data.plan?.items.map(i=>i.slot)||[];
      if (!unique(saved.pins)||saved.pins.length>(c.adaptive_daily?7:6)||!savedSnackMode&&!saved.pins.every(k=>planSlots.includes(k))) throw Error();
      state.pins=new Set(savedSnackMode?[]:saved.pins);
      state.autoPending=state.autoPending||saved.autoPending===true||(saved.version===1||c.adaptive_daily===true)&&layoutMismatch();
      const retry=saved.retry;
      if(retry&&['generate','regenerate'].includes(retry.action)&&(retry.target===null||slot(retry.target)))state.retry={action:retry.action,target:retry.target};
      $('meal-retry').classList.toggle('hidden',!state.retry);
      const h=saved.history;
      if (c.adaptive_daily!==true&&!savedSnackMode&&h&&Object.keys(h).length===3&&groups.every(g=>unique(h[g])&&h[g].length<=50&&h[g].every(i=>integer(i,1,8589934591)))&&groups.reduce((n,g)=>n+h[g].length,0)<=50) state.history=h;
      const comboHistory=saved.dailyComboHistory, comboHistorySignature=saved.dailyComboHistorySignature;
      if (c.adaptive_daily===true&&comboHistorySignature===dailyComboSignature(c)&&Array.isArray(comboHistory)&&
          comboHistory.length<=maxDailyComboHistory&&unique(comboHistory)&&comboHistory.every(id=>typeof id==='string'&&/^[a-f0-9]{32}$/.test(id))) {
        state.dailyComboHistory=comboHistory;state.dailyComboHistorySignature=comboHistorySignature;
      }
      if(c.adaptive_daily===true&&saved.dailyNoResultKey===dailyResultKey(c))state.dailyNoResultKey=saved.dailyNoResultKey;
      if (typeof saved.notice==='string'&&saved.notice.length<=2000) message(saved.notice,saved.error===true);
      if (Number.isFinite(saved.scrollY)&&saved.scrollY>=0) requestAnimationFrame(()=>window.scrollTo(0,saved.scrollY));
    } catch {
      state.view=null; state.pins.clear(); state.history=emptyHistory();
      state.dailyComboHistory=[];state.dailyComboHistorySignature=null;
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
    const sig=signature(c);
    if(c.adaptive_daily===true){
      const comboSig=dailyComboSignature(c);
      if(state.dailyComboHistorySignature!==comboSig){
        state.dailyComboHistory=[];state.dailyComboHistorySignature=comboSig;
      }
    }
    const payload={...c,people:state.people,adults:state.adults,children:state.children,action,current_plan:current,locked_slots:[...state.pins],
      avoid_recipe_ids:c.adaptive_daily===true?{}:previous?state.history:{}};
    if(c.adaptive_daily===true)payload.combo_history=[...state.dailyComboHistory];
    if (target) payload.replace_slot=target;
    const token=++state.sequence;
    state.controller=new AbortController(); state.busy=true; state.retry={action,target};
    state.autoPending=state.autoPending||layoutMismatch();
    message(state.catalogChangedNotice); $('meal-retry').classList.add('hidden'); controls();
    save();
    state.generationDeadline=setTimeout(()=>{
      if(token!==state.sequence)return;
      cancel();state.autoPending=false;
      if(c.adaptive_daily===true)state.dailyNoResultKey=dailyResultKey(c);
      message('Tạo mâm quá lâu. Mâm và ghim được giữ; hãy thử lại.',true);
      $('meal-retry').classList.remove('hidden');queuePortions(0);controls();save();
    },10000);
    try {
      const response=await fetch('/api/meal-plan/v2',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:state.controller.signal});
      const e=await response.json();
      if (token!==state.sequence||sig!==signature(conditions())) return;
      if (!response.ok||!e.ok) throw Error(e.error?.code==='UNKNOWN_OPERATION'?'TCP Server chưa hỗ trợ mâm linh hoạt. Hãy khởi động server mới hoặc mở bản ba món cũ.':e.error?.code==='TIMEOUT'?'TCP Server phản hồi quá lâu. Hãy thử lại.':e.error?.message||'Không thể tạo mâm.');
      const data=e.data;
      if (e.version!==1||!text(e.request_id,80)||data?.people!==payload.people||!validData(data,c)||c.adaptive_daily&&data.daily_selection_policy!=='daily-demo-food-v1') {
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
        if(c.adaptive_daily===true){
          state.dailyNoResultKey=null;
          if(data.warnings.includes('HISTORY_RECYCLED'))state.dailyComboHistory=[];
          if(!state.dailyComboHistory.includes(data.daily_combo_id)&&state.dailyComboHistory.length<maxDailyComboHistory)
            state.dailyComboHistory.push(data.daily_combo_id);
        }else{
          for (const g of groups) {
            const added=data.plan.items.filter(i=>i.slot.startsWith(g+':')).map(i=>i.recipe_id);
            if (data.warnings.includes('HISTORY_RECYCLED')) state.history[g]=previous?.items.filter(i=>i.slot.startsWith(g+':')).map(i=>i.recipe_id)||[];
            state.history[g]=[...new Set([...state.history[g],...added])];
          }
        }
        if(dailyOnly()){
          const before=state.view;
          dailyChange=before?.data.plan&&before.conditions.people!==c.people?
            'Khi đổi từ '+before.conditions.people+' sang '+c.people+' người, mâm đổi từ '+before.data.plan.items.length+' thành '+data.plan.items.length+' món; lượng mỗi công thức giữ nguyên.':null;
        }
        state.view={signature:sig,conditions:{...c,counts:{...data.counts}},data,
          ...(c.adaptive_daily?{dailyHousehold:JSON.stringify([state.adults,state.children])}:{})}; render(); queuePortions(0);
        message('Đã cập nhật mâm; món ghim được giữ nguyên.'+(!c.adaptive_daily&&data.warnings.includes('PARTIAL_REGENERATION')?' Chỉ đổi được một phần mâm.':'')+(!c.adaptive_daily&&data.warnings.includes('HISTORY_RECYCLED')?' Đã dùng lại một số món trong lịch sử.':'')+(data.daily_combo_note?' '+data.daily_combo_note:'')+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''));
        state.catalogChangedNotice='';
        state.retry=null;
      } else {
        if(c.adaptive_daily===true)state.dailyNoResultKey=dailyResultKey(c);
        if (!previous) {state.view={signature:sig,conditions:c,data};render();}
        message(data.reason.message+' '+data.reason.suggestions.join(' ')+(previous?' Mâm và ghim hiện tại được giữ lại.':'')+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''));
        state.catalogChangedNotice='';
        $('meal-retry').classList.remove('hidden');queuePortions(0);
      }
      state.autoPending=false; save();
    } catch (e) {
      if (token!==state.sequence||e.name==='AbortError') return;
      state.autoPending=false;
      if(c.adaptive_daily===true)state.dailyNoResultKey=dailyResultKey(c);
      const failure=e instanceof TypeError?'Kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c m\u00e1y ch\u1ee7.':e instanceof SyntaxError?'M\u00e1y ch\u1ee7 tr\u1ea3 d\u1eef li\u1ec7u kh\u00f4ng h\u1ee3p l\u1ec7.':e.message;
      message(failure+(previous?' M\u00e2m c\u0169 v\u1eabn \u0111\u01b0\u1ee3c gi\u1eef l\u00e0m b\u1ea3n tr\u01b0\u1edbc; y\u00eau c\u1ea7u ch\u01b0a c\u1eadp nh\u1eadt th\u00e0nh c\u00f4ng.':' Ch\u01b0a t\u1ea1o \u0111\u01b0\u1ee3c m\u00e2m m\u1edbi.')+(state.catalogChangedNotice?' '+state.catalogChangedNotice:''),true);
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
    state.autoPending=true;renderFilters();picker();scheduleLayout();
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
      refreshContext();
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
  let contextSequence=0, contextController=null, pendingProposal=null;
  function assessmentRequest() {
    return {...conditions(),people:state.people,current_plan:Object.fromEntries((state.view?.data.plan?.items||[]).map(i=>[i.slot,i.recipe_id])),
      locked_slots:[...state.pins]};
  }
  function acceptSelection(data,locks=[]) {
    if(!data?.plan)throw Error('Không có mâm phù hợp để áp dụng.');
    const c={...conditions(),counts:{...data.counts},layout_mode:data.layout_mode};
    if(!validData(data,c))throw Error('Kết quả mâm không hợp lệ; vui lòng tải lại.');
    state.layoutMode=data.layout_mode;state.customCounts={...data.counts};state.pins=new Set(locks);state.history=emptyHistory();
    state.view={signature:signature(c),conditions:c,data,
      ...(c.adaptive_daily?{dailyHousehold:JSON.stringify([state.adults,state.children])}:{})};state.autoPending=false;
    cancel();render();queuePortions(0);save();
  }
  async function refreshContext(extra={}) {
    if(!state.ready||!state.view?.data.plan||layoutMismatch())return;
    const token=++contextSequence, request=assessmentRequest(), sig=signature(request);
    contextController?.abort();contextController=new AbortController();
    const controller=contextController, timeout=setTimeout(()=>controller.abort(),10000);
    $('meal-reasons').replaceChildren();$('meal-context-warnings').replaceChildren();$('meal-beverages').replaceChildren();
    // Generation already supplies current seasonal reasons. Do not blank them
    // while an independent context request is in flight or unavailable.
    if(dailyOnly()&&state.view.data.seasonal_assessment){dailyContext=null;dailyReasons();}
    $('meal-context-status').textContent='Đang kiểm tra phối món và đồ uống…';
    try {
      const response=await fetch('/api/meal-plan/assess',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({request,adults:state.adults,children:state.children,query:$('meal-recipe-search').value.trim(),...extra}),signal:controller.signal});
      const envelope=await response.json();
      if(token!==contextSequence||sig!==signature(assessmentRequest()))return;
      if(!response.ok||!envelope.ok)throw Error(envelope.error?.message||'Không kiểm tra được mâm.');
      const d=envelope.data;
      if(d.dataset_version!==state.dataset)throw Error('Dữ liệu đã đổi; tải lại trang để tiếp tục.');
      if(extra.add_recipe_id||extra.remove_slot) {
        if(!d.selection?.plan)throw Error(d.selection?.reason?.message||'Món không đáp ứng điều kiện bắt buộc.');
        acceptSelection(d.selection,d.locked_slots);return;
      }
      $('meal-reasons').innerHTML='<ul>'+d.reasons.slice(0,3).map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul>'+
        '<details><summary>Xem đánh giá và lý do theo món</summary>'+d.reasons.slice(3).map(r=>'<p>'+esc(r)+'</p>').join('')+d.items.map(i=>'<p><strong>'+esc(i.title)+'</strong>: '+esc(i.reasons.join(' ')||'Chưa có tín hiệu thời tiết; vẫn xét các điều kiện phối mâm.')+'</p>').join('')+'</details>';
      if(dailyOnly()){dailyContext=d;dailyReasons();}
      $('meal-context-warnings').innerHTML=dailyOnly()?'':d.warnings.map(w=>'<p class="field-help">⚠ '+esc(w)+'</p>').join('');
      if(dailyOnly())renderDailyBeverages(d.beverages);
      else $('meal-beverages').innerHTML=d.beverages.length?d.beverages.map(b=>'<p><a href="/recipes/'+b.recipe_id+'">'+esc(b.title)+'</a><small>'+esc(b.quantity_note)+' · '+b.people+' người.</small></p><details><summary>Lý do gợi ý</summary><p>'+esc(b.reason)+'</p></details>').join(''):'Chưa có đồ uống không cồn phù hợp dữ liệu và nguyên liệu loại trừ.';
      $('meal-manual-candidates').innerHTML=d.candidates.map(r=>'<p>'+esc(r.title)+' <small>'+esc(labels[r.role])+(r.portion_ready?' · Có định lượng':' · Cần kiểm tra định lượng')+'</small> <button type="button" class="retry-button" data-manual-add="'+r.recipe_id+'">Thêm</button></p>').join('')||'<p>Không có ứng viên phù hợp.</p>';
      if(state.layoutMode==='custom')for(const item of state.view.data.plan.items) {
        const card=$('meal-cards').querySelector('[data-meal-slot="'+item.slot+'"]');
        if(card&&!card.querySelector('[data-manual-remove]')) {
          const button=document.createElement('button');button.type='button';button.className='retry-button';button.dataset.manualRemove=item.slot;
          button.textContent='Bỏ món';button.disabled=state.pins.has(item.slot);card.append(button);
        }
      }
      if(extra.propose) {
        pendingProposal={data:d.proposal,signature:sig};
        $('meal-proposal').innerHTML=d.proposal?.plan?'<p>'+esc((d.proposal_reasons||[]).join(' '))+' Các món ghim được giữ. Chưa áp dụng.</p><ul>'+d.proposal.plan.items.map(i=>'<li>'+esc(i.title)+'</li>').join('')+'</ul><button type="button" class="retry-button" id="meal-accept-proposal">Chấp nhận đề xuất</button>':'<p>'+esc(d.proposal?.reason?.message||'Không đủ ứng viên phù hợp; mâm hiện tại được giữ nguyên.')+'</p>';
      } else if(!pendingProposal) $('meal-proposal').replaceChildren();
      $('meal-context-status').textContent='Đã kiểm tra mâm theo dữ liệu hiện có.';
    } catch(error) {
      if(token===contextSequence)$('meal-context-status').textContent=error.name==='AbortError'?'Kiểm tra quá lâu; hãy thử lại.':error.message;
    } finally {clearTimeout(timeout);}
  }
  $('meal-weather').addEventListener('change',()=>{
    pendingProposal=null;$('meal-proposal').replaceChildren();
    const previous={...(state.view?.conditions||{})},next={...conditions()};
    delete previous.weather;delete next.weather;
    if(state.layoutMode==='custom'&&state.view?.data.plan&&signature(previous)===signature(next)&&!layoutMismatch()) {
      // Keep manually selected food; all weather scoring is performed by TCP.
      cancel();state.autoPending=false;
      const c=conditions();state.view={...state.view,signature:signature(c),conditions:c,data:{...state.view.data,weather:c.weather||null}};
      render();queuePortions(0);save();
    } else changed();
  });
  $('meal-season').addEventListener('change',e=>{
    if(!dailyOnly()||!seasons.includes(e.target.value))return;
    state.season=e.target.value;
    pendingProposal=null;$('meal-proposal').replaceChildren();
    changed();
  });
  $('meal-find-recipes').onclick=()=>refreshContext();
  $('meal-check').onclick=()=>refreshContext();
  $('meal-suggest').onclick=()=>refreshContext({propose:true});
  $('meal-manual-candidates').onclick=e=>{const b=e.target.closest('[data-manual-add]');if(b){pendingProposal=null;refreshContext({add_recipe_id:Number(b.dataset.manualAdd)});}};
  $('meal-cards').addEventListener('click',e=>{const b=e.target.closest('[data-manual-remove]');if(b&&!b.disabled){pendingProposal=null;refreshContext({remove_slot:b.dataset.manualRemove});}});
  $('meal-proposal').onclick=e=>{if(e.target.closest('#meal-accept-proposal')&&pendingProposal){const proposal=pendingProposal.data;const stillCurrent=pendingProposal.signature===signature(assessmentRequest());pendingProposal=null;$('meal-proposal').replaceChildren();try{if(!stillCurrent)throw Error('Mâm đã thay đổi; hãy lấy đề xuất mới.');acceptSelection(proposal,[...state.pins]);}catch(error){message(error.message,true);}}};
  load();
})();
