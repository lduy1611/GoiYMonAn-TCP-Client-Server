(() => {
  const $=selector=>document.querySelector(selector);
  let imagePreviewUrl=null;
  const state={csrf:'',writeReady:false,recipeCatalogReady:false,reviewReady:false,ingredientAdminReady:false,legacyIngredientAdminReady:false,legacyOverlayReady:false,revisionId:null,revisionVersion:null,legacyVersion:null,recipeId:null,createKey:null,legacyRecipeId:null,legacyVisible:true,imageRecipeId:null,imageUrl:null,pendingImageFile:null,savedAdminImage:false,imageReady:false,savedDraftSnapshot:'',dirty:false,busy:false,reauthenticating:false,imageBusy:false,ingredientOptions:[],ingredientOffset:0,ingredientTotal:0,ingredientRequestVersion:0,recipeOffset:0,recipeTotal:0,recipeSearchVersion:0,detailRequestVersion:0,activeEditorTab:'info',editingIngredientId:null,editingIngredientSource:'LEGACY',ingredientBusy:false,dialogContext:null};
  const errorCopy={
    ADMIN_UNAUTHORIZED:'Phiên Admin đã hết hạn. Biểu mẫu chưa lưu sẽ được giữ để bạn đăng nhập lại.',
    ADMIN_CSRF:'Mã bảo vệ yêu cầu không khớp. Nội dung biểu mẫu vẫn được giữ; hãy đăng nhập lại rồi thử lại.',
    INVALID_PAYLOAD:'Dữ liệu chưa hợp lệ. Hãy kiểm tra tên món, thời gian và nguyên liệu.',
    NOT_FOUND:'Không tìm thấy món hoặc bản ghi yêu cầu.',
    ADMIN_RECIPE_CONFLICT:'Món ăn đã thay đổi hoặc xung đột. Hãy tải lại chi tiết món trước khi lưu tiếp.',
    ADMIN_DRAFT_CONFLICT:'Bản nháp đã thay đổi hoặc không còn được sửa. Hãy tải lại chi tiết.',
    ADMIN_RECIPE_CONSTRAINT:'Dữ liệu món ăn vi phạm ràng buộc lưu trữ. Hãy kiểm tra lại nguyên liệu và thông tin món.',
    ADMIN_RECIPE_INVALID_DATA:'Một giá trị không phù hợp với kiểu dữ liệu được lưu. Hãy kiểm tra thời gian và nội dung định lượng.',
    DB_UNAVAILABLE:'Không kết nối được MySQL để lưu món. Nội dung bạn nhập vẫn được giữ lại; hãy thử lại sau.',
    ADMIN_LEGACY_RECIPE_CONFLICT:'Món ăn hoặc nguyên liệu xung đột với danh mục hiện tại. Hãy kiểm tra lại các nguyên liệu.',
    ADMIN_INGREDIENT_CONFLICT:'Nguyên liệu bị trùng tên hoặc không còn hợp lệ.',
    ADMIN_WRITE_DENIED:'Tài khoản Admin không có quyền ghi thao tác này.',
    ADMIN_WRITE_UNAVAILABLE:'Tài khoản ghi Admin chưa sẵn sàng.',
    ADMIN_SCHEMA_UNAVAILABLE:'Cấu trúc cơ sở dữ liệu chưa sẵn sàng cho thao tác này.',
    DB_ERROR:'Cơ sở dữ liệu gặp lỗi. Hãy tải lại dữ liệu trước khi thử lại.',
    INTERNAL_ERROR:'Đã xảy ra lỗi nội bộ. Hãy thử lại hoặc liên hệ quản trị viên.',
    UPSTREAM_UNAVAILABLE:'Không kết nối được tới TCP Server.',
    TIMEOUT:'Yêu cầu quá thời gian chờ. Hãy tải lại để kiểm tra trạng thái mới nhất.',
  };
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const newRequestKey=()=>crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]%16;return(c==='x'?r:(r&3|8)).toString(16);});
  const safeUrl=value=>{try{const parsed=new URL(String(value||''),location.origin);return ['http:','https:'].includes(parsed.protocol)?parsed.href:'#';}catch{return '#';}};
  const setMessage=(node,text,error=false)=>{node.textContent=text;node.classList.toggle('error',error);};
  function preserveDraftForReauth(){
    if(!state.dirty)return;
    try{
      sessionStorage.setItem('adminDraftReauth',JSON.stringify({version:1,savedAt:Date.now(),revisionId:state.revisionId,revisionVersion:state.revisionVersion,legacyVersion:state.legacyVersion,recipeId:state.recipeId,createKey:state.createKey,
        legacyRecipeId:state.legacyRecipeId,legacyVisible:state.legacyVisible,body:currentDraft(),imageNeedsReselect:Boolean(state.pendingImageFile)}));
    }catch{}
  }
  function beginReauthWithDraft(){preserveDraftForReauth();state.reauthenticating=true;location.assign('/admin/login?return_to='+encodeURIComponent('/admin?restore_draft=1'));}
  function showDraftError(error){
    const node=$('#draft-message');
    let message=error.message||'Không lưu được thay đổi.';
    if(error.requestId)message+=' (Mã yêu cầu: '+error.requestId+')';
    setMessage(node,message,true);
    if(error.code==='ADMIN_CSRF'){
      const button=document.createElement('button');button.type='button';button.className='button-secondary';
      button.textContent='Đăng nhập lại và giữ biểu mẫu';button.addEventListener('click',beginReauthWithDraft,{once:true});node.append(document.createTextNode(' '),button);
    }
  }
  async function api(url,options={}){
    const headers={...(options.headers||{})};if(state.csrf)headers['X-CSRF-Token']=state.csrf;
    const response=await fetch(url,{...options,headers,credentials:'same-origin',cache:'no-store'});
    const envelope=await response.json();
    if(!response.ok||envelope.ok!==true){const code=envelope.error?.code;let message=errorCopy[code]||envelope.error?.message||'Thao tác không thành công.';if((response.status===401||response.status===403)&&code)message+=' ('+code+').';const error=new Error(message);error.code=code;error.status=response.status;error.requestId=response.headers.get('X-Request-ID')||envelope.request_id||null;
      if(response.status===401)beginReauthWithDraft();
      throw error;}
    return envelope.data;
  }
  async function loadSession(){const data=await api('/api/admin/session');state.csrf=data.csrf_token;$('#admin-user').textContent=data.username;}
  async function loadDashboard(){
    let data;
    try{data=await api('/api/admin/dashboard');}
    catch(error){
      const button=$('#admin-create'),note=$('#admin-write-note');
      button.disabled=true;button.title='Không thể xác nhận backend sẵn sàng. Hãy tải lại hoặc kiểm tra FastAPI/TCP.';
      note.textContent='Chưa xác nhận được quyền và trạng thái catalog từ backend.';
      throw error;
    }
    for(const [id,value] of [['recipes',data.recipes_total],['ingredients',data.ingredients_total],['users',data.users_total],['published',data.published_total]])$('#stat-'+id).textContent=value===null||value===undefined?'—':Number(value).toLocaleString('vi-VN');
    $('#stat-published-summary').textContent=data.published_total===null||data.published_total===undefined?'—':Number(data.published_total).toLocaleString('vi-VN');
    $('#stat-hidden-summary').textContent=data.published_total===null||data.recipes_total===null?'—':Math.max(0,Number(data.recipes_total)-Number(data.published_total)).toLocaleString('vi-VN');
    $('#stat-catalog-ready').textContent=data.published_total===null?'Chưa kết nối':'Đang hoạt động';
    $('#nav-recipe-count').textContent=Number(data.recipes_total||0).toLocaleString('vi-VN');
    $('#nav-user-count').textContent=data.users_total===null||data.users_total===undefined?'—':Number(data.users_total).toLocaleString('vi-VN');
    state.writeReady=data.draft_write_ready===true;state.recipeCatalogReady=data.recipe_catalog_ready===true;
    const createButton=$('#admin-create'),writeNote=$('#admin-write-note');
    createButton.disabled=!state.recipeCatalogReady;
    const createReason=state.recipeCatalogReady
      ?'Lưu món hợp lệ sẽ hiển thị ngay trên User.'
      :!state.writeReady
        ?'Backend chưa sẵn sàng ghi công thức: kiểm tra migration mô tả và các quyền writer cần thiết.'
        :'Backend chưa sẵn sàng catalog công khai: kiểm tra migration 009 và quyền trên bảng catalog.';
    createButton.title=createReason;writeNote.textContent=createReason;
    state.reviewReady=data.review_write_ready===true;
    state.legacyOverlayReady=data.legacy_recipe_overlay_ready===true;
    state.ingredientAdminReady=data.ingredient_admin_ready===true;$('#admin-ingredient-create').disabled=!state.ingredientAdminReady;
    $('#admin-ingredient-readiness').textContent=state.ingredientAdminReady?'Danh m\u1ee5c nguy\u00ean li\u1ec7u d\u00f9ng chung v\u1edbi User.':'Danh m\u1ee5c v\u1eabn xem \u0111\u01b0\u1ee3c; quy\u1ec1n qu\u1ea3n l\u00fd ch\u01b0a s\u1eb5n s\u00e0ng.';
    const legacyNote=$('#admin-legacy-readiness');
    if(legacyNote)legacyNote.textContent=state.legacyOverlayReady
      ?'Danh s\u00e1ch m\u00f3n \u0103n s\u1eb5n s\u00e0ng \u0111\u1ec3 qu\u1ea3n l\u00fd.'
      :'Danh s\u00e1ch m\u00f3n \u0103n v\u1eabn xem \u0111\u01b0\u1ee3c; ch\u1ec9nh s\u1eeda ho\u1eb7c \u1ea9n/hi\u1ec7n ch\u01b0a s\u1eb5n s\u00e0ng.';
  }
  function renderIngredientRows(rows){
    const body=$('#admin-ingredients');body.replaceChildren();$('#admin-ingredient-empty').classList.toggle('hidden',rows.length>0);
    for(const item of rows){
      const tr=document.createElement('tr'),managed=item.can_manage===true;
      const edit=item.can_edit&&managed?'<button type="button" class="button-secondary" data-ingredient-edit="'+esc(item.ingredient_id)+'">Sửa</button>':'';
      const toggle=item.can_manage&&managed?'<button type="button" class="button-secondary" data-ingredient-active="'+esc(item.ingredient_id)+'" data-next-active="'+String(!item.is_active)+'">'+(item.is_active?'Ngừng sử dụng':'Kích hoạt lại')+'</button>':'';
      const statusLabel=item.is_active?'Đang sử dụng':'Ngừng sử dụng';
      tr.innerHTML='<td><strong>'+esc(item.name)+'</strong></td><td>'+esc(item.usage_count)+'</td><td><span class="status-pill '+(item.is_active?'':'status-inactive')+'">'+statusLabel+'</span></td><td class="admin-ingredient-actions">'+(edit||'<span class="admin-muted">'+(managed?'Không thể sửa mục này':'Chưa sẵn sàng')+'</span>')+toggle+'</td>';
      body.append(tr);
    }
    const from=state.ingredientTotal?state.ingredientOffset+1:0,to=Math.min(state.ingredientOffset+rows.length,state.ingredientTotal);
    $('#admin-ingredient-page-status').textContent=from+'–'+to+' / '+state.ingredientTotal;
    $('#admin-ingredient-prev').disabled=state.ingredientOffset===0;
    $('#admin-ingredient-next').disabled=state.ingredientOffset+rows.length>=state.ingredientTotal;
  }
  async function loadIngredientPage(){
    const version=++state.ingredientRequestVersion;
    setMessage($('#admin-ingredient-readiness'),'Đang tải danh mục dùng chung…');
    try{
      const query=$('#admin-ingredient-query').value.trim();
      const data=await api('/api/admin/ingredients?catalog=shared&query='+encodeURIComponent(query)+'&limit=20&offset='+state.ingredientOffset);
      if(version!==state.ingredientRequestVersion)return;
      if(data.total>0&&state.ingredientOffset>=data.total&&state.ingredientOffset>0){state.ingredientOffset=Math.floor((data.total-1)/20)*20;return loadIngredientPage();}
      state.ingredientTotal=data.total;state.ingredientAdminReady=data.ingredient_admin_ready===true;
      state.legacyIngredientAdminReady=data.legacy_ingredient_admin_ready===true;
      $('#admin-ingredient-create').disabled=!state.ingredientAdminReady;
      $('#admin-ingredient-readiness').textContent=state.legacyIngredientAdminReady?
        'Danh m\u1ee5c nguy\u00ean li\u1ec7u d\u00f9ng chung v\u1edbi User. T\u00ean v\u00e0 tr\u1ea1ng th\u00e1i \u0111\u01b0\u1ee3c c\u1eadp nh\u1eadt an to\u00e0n.'
        :'Danh m\u1ee5c nguy\u00ean li\u1ec7u d\u00f9ng chung v\u1edbi User \u1edf ch\u1ebf \u0111\u1ed9 ch\u1ec9 \u0111\u1ecdc.';
      state.ingredientRows=data.items;renderIngredientRows(data.items);
    }catch(error){setMessage($('#admin-ingredient-readiness'),error.message||'Không tải được danh mục nguyên liệu.',true);}
  }
  function openIngredientForm(item=null){
    const ready=item?item.can_manage===true:state.ingredientAdminReady;
    if(!ready)return;
    state.editingIngredientId=item?item.ingredient_id:null;state.editingIngredientSource='SHARED';state.ingredientBusy=false;
    $('#admin-ingredient-form').reset();$('#admin-ingredient-name').value=item?.name||'';
    $('#admin-ingredient-form-title').textContent=item?'Sửa nguyên liệu':'Thêm nguyên liệu';
    $('#admin-ingredient-save').disabled=false;$('#admin-ingredient-form').classList.remove('hidden');
    setMessage($('#admin-ingredient-message'),'');$('#admin-ingredient-name').focus();
  }
  async function saveIngredient(event){
    event.preventDefault();if(state.ingredientBusy)return;
    const name=$('#admin-ingredient-name').value.trim();
    if(name.length<2||name.length>255){setMessage($('#admin-ingredient-message'),'T\u00ean nguy\u00ean li\u1ec7u ph\u1ea3i d\u00e0i t\u1eeb 2 \u0111\u1ebfn 255 k\u00fd t\u1ef1.',true);return;}
    state.ingredientBusy=true;$('#admin-ingredient-save').disabled=true;setMessage($('#admin-ingredient-message'),'\u0110ang l\u01b0u\u2026');
    const id=state.editingIngredientId;
    const url=id===null?'/api/admin/ingredients':'/api/admin/ingredients/'+encodeURIComponent(id);
    try{
      await api(url,{method:id!==null?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      $('#admin-ingredient-form').classList.add('hidden');setMessage($('#admin-ingredient-message'),'\u0110\u00e3 l\u01b0u nguy\u00ean li\u1ec7u.');
      await Promise.all([loadDashboard(),loadIngredientPage(),refreshIngredientOptions()]);
    }catch(error){setMessage($('#admin-ingredient-message'),error.message||'Kh\u00f4ng l\u01b0u \u0111\u01b0\u1ee3c nguy\u00ean li\u1ec7u.',true);}
    finally{state.ingredientBusy=false;$('#admin-ingredient-save').disabled=false;}
  }
  async function setIngredientActive(id,isActive){
    const button=$('#admin-ingredients [data-ingredient-active="'+CSS.escape(String(id))+'"]');
    const row=button?.closest('tr');
    if(!isActive&&row&&Number(row.children[1].textContent)>0&&!confirm('Nguyên liệu đang được dùng trong công thức. Ngừng sử dụng sẽ giữ nguyên công thức và chỉ ẩn nguyên liệu khỏi lựa chọn mới. Tiếp tục?'))return;
    if(isActive&&!confirm('Kích hoạt lại nguyên liệu này?'))return;
    const base='/api/admin/ingredients/';
    try{await api(base+encodeURIComponent(id)+'/active',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_active:isActive})});await loadIngredientPage();await refreshIngredientOptions();}
    catch(error){setMessage($('#admin-ingredient-readiness'),error.message||'Không cập nhật được trạng thái nguyên liệu.',true);}
  }
  function renderRows(rows){
    const body=$('#admin-recipes');body.replaceChildren();$('#admin-list-empty').classList.toggle('hidden',rows.length>0);
    const roles={main:'M\u00f3n ch\u00ednh',vegetable:'M\u00f3n rau',soup:'M\u00f3n canh'};
    for(const row of rows){
      const tr=document.createElement('tr'),edit=row.legacy?state.legacyOverlayReady:state.recipeCatalogReady;
      const visibility=row.visible?'<span class="admin-visibility is-visible"><i></i>Hi\u1ec3n th\u1ecb</span>':'<span class="admin-visibility is-hidden"><i></i>\u0110ang \u1ea9n</span>';
      const canState=state.recipeCatalogReady;
      const lifecycleButton=row.deleted
        ?'<button type="button" class="button-primary" data-restore="'+esc(row.recipe_id)+'" data-visible="'+String(row.stored_visible!==false)+'" data-title="'+esc(row.title)+'" '+(!canState?'disabled title="C\u1ea7n migration danh m\u1ee5c v\u00e0 quy\u1ec1n writer"':'')+'>Kh\u00f4i ph\u1ee5c</button>'
        :'<button type="button" class="button-danger" data-delete="'+esc(row.recipe_id)+'" data-title="'+esc(row.title)+'" data-visible="'+String(row.stored_visible!==false)+'" '+(!canState?'disabled title="C\u1ea7n migration danh m\u1ee5c v\u00e0 quy\u1ec1n writer"':'')+'>X\u00f3a</button>';
      const view=row.legacy?'<button type="button" class="button-secondary" data-view-legacy="'+esc(row.recipe_id)+'">Xem</button>':'<button type="button" class="button-secondary" data-view="'+esc(row.revision_id)+'">Xem</button>';
      const editButton=edit?(row.legacy?' <button type="button" data-edit-legacy="'+esc(row.recipe_id)+'">S\u1eeda</button>':' <button type="button" data-edit="'+esc(row.edit_revision_id||row.revision_id)+'" data-public-id="'+esc(row.recipe_id)+'">S\u1eeda</button>'):'';
      tr.innerHTML='<td><div class="admin-recipe-name"><span class="admin-recipe-thumb"><img data-recipe-thumb="'+esc(row.recipe_id)+'" src="/static/images/recipes/placeholder.svg" alt="" loading="lazy"></span><span><strong>'+esc(row.title)+'</strong></span></div></td><td>'+esc(roles[row.role]||'Ch\u01b0a ph\u00e2n lo\u1ea1i')+'</td><td>'+esc(row.minutes??'\u2014')+(row.minutes?' ph\u00fat':'')+'</td><td>'+(row.deleted?'<span class="admin-visibility is-hidden"><i></i>\u0110\u00e3 x\u00f3a</span>':visibility)+'</td><td class="admin-table-actions">'+view+editButton+' '+lifecycleButton+'</td>';
      body.append(tr);
    }
  }
  async function hydrateRecipeThumbnails(rows,version){
    await Promise.all(rows.map(async row=>{try{const data=await api('/api/admin/recipes/'+encodeURIComponent(row.recipe_id)+'/image');if(version!==state.recipeSearchVersion)return;const image=$('#admin-recipes [data-recipe-thumb="'+CSS.escape(String(row.recipe_id))+'"]');if(image&&typeof data.image_url==='string')image.src=data.image_url;}catch{}}));
  }
  async function search(){
    const version=++state.recipeSearchVersion;
    setMessage($('#admin-status'),'Đang tải danh sách…');
    try{const params=new URLSearchParams({query:$('#admin-query').value.trim(),limit:'20',offset:String(state.recipeOffset)});const role=$('#admin-recipe-role').value,visibility=$('#admin-recipe-visibility').value,minutes=$('#admin-recipe-max-minutes').value;if(role)params.set('role',role);if(visibility)params.set('visibility',visibility);if(minutes)params.set('max_minutes',minutes);const data=await api('/api/admin/recipes?'+params);if(version!==state.recipeSearchVersion)return;if(data.total>0&&state.recipeOffset>=data.total&&state.recipeOffset>0){state.recipeOffset=Math.floor((data.total-1)/20)*20;return search();}state.recipeTotal=data.total;renderRows(data.items);void hydrateRecipeThumbnails(data.items,version);const from=data.total?state.recipeOffset+1:0,to=Math.min(state.recipeOffset+data.items.length,data.total);$('#admin-recipe-page-status').textContent=from+'–'+to+' / '+data.total;$('#admin-recipes-prev').disabled=state.recipeOffset===0;$('#admin-recipes-next').disabled=state.recipeOffset+data.items.length>=data.total;setMessage($('#admin-status'),'Có '+Number(data.total).toLocaleString('vi-VN')+' món phù hợp.');}
    catch(error){setMessage($('#admin-status'),error.message||'Không tải được danh sách.',true);}
  }
  async function setRecipeLifecycle(event){
    const remove=event.target.closest('[data-delete]'),restore=event.target.closest('[data-restore]');
    const target=remove||restore;if(!target)return;
    const id=Number(target.dataset.delete||target.dataset.restore),name=target.dataset.title||'m\u00f3n \u0103n';
    const visible=target.dataset.visible==='true',deleted=Boolean(remove);
    const question=remove
      ?'X\u00f3a m\u1ec1m m\u00f3n \u201c'+name+'\u201d? M\u00f3n s\u1ebd kh\u00f4ng c\u00f2n xu\u1ea5t hi\u1ec7n v\u1edbi User v\u00e0 c\u00f3 th\u1ec3 kh\u00f4i ph\u1ee5c sau. Kh\u00f4ng x\u00f3a c\u00f4ng th\u1ee9c, nguy\u00ean li\u1ec7u ho\u1eb7c \u1ea3nh.'
      :'Kh\u00f4i ph\u1ee5c m\u00f3n \u201c'+name+'\u201d v\u1ec1 danh s\u00e1ch qu\u1ea3n l\u00fd?';
    if(!confirm(question))return;
    try{
      await api('/api/admin/catalog-recipes/'+encodeURIComponent(id)+'/state',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_visible:visible,is_deleted:deleted})});
      setMessage($('#admin-status'),remove?'\u0110\u00e3 chuy\u1ec3n m\u00f3n v\u00e0o danh s\u00e1ch \u0111\u00e3 x\u00f3a.':'\u0110\u00e3 kh\u00f4i ph\u1ee5c m\u00f3n \u0103n.');
      await Promise.all([loadDashboard(),search()]);
    }catch(error){setMessage($('#admin-status'),error.message||'Kh\u00f4ng c\u1eadp nh\u1eadt \u0111\u01b0\u1ee3c tr\u1ea1ng th\u00e1i m\u00f3n \u0103n.',true);}
  }
  function currentDraft(){
    const lines=[...$('#draft-lines').querySelectorAll('.admin-line')].map(row=>({ingredient_id:Number(row.querySelector('select').value),quantity_raw:row.querySelector('[data-quantity]').value.trim()||null}));
    return {title:$('#draft-title').value.trim(),description:$('#draft-description').value.trim(),instructions:$('#draft-instructions').value.trim(),minutes:$('#draft-minutes').value?Number($('#draft-minutes').value):null,role:$('#draft-role').value,ingredients:lines};
  }
  function markDirty(){state.dirty=JSON.stringify(currentDraft())!==state.savedDraftSnapshot||Boolean(state.pendingImageFile);}
  function renderImagePreview(url,alt='Ảnh đại diện món ăn'){
    const preview=$('#draft-image-preview');preview.replaceChildren();if(url){const image=document.createElement('img');image.src=url;image.alt=alt;image.loading='lazy';preview.append(image);preview.setAttribute('aria-label',alt);}else{preview.textContent='＋';preview.setAttribute('aria-label','Chưa có ảnh xem trước');}
  }
  function imageMessage(text,error=false){const node=$('#draft-image-message');node.textContent=text;node.classList.toggle('error',error);}
  function openDialog(dialog,returnFocus=document.activeElement){if(!state.dialogContext)state.dialogContext={returnFocus,windowY:window.scrollY,mainY:$('.admin-main').scrollTop};if(!dialog.open)dialog.showModal();}
  function closeDialog(dialog,{restore=true}={}){if(dialog.open)dialog.close();if(!restore)return;const context=state.dialogContext;state.dialogContext=null;requestAnimationFrame(()=>{const target=context?.returnFocus;if(target?.isConnected)target.focus({preventScroll:true});else $('#admin-create')?.focus({preventScroll:true});if(context){window.scrollTo({top:context.windowY,behavior:'instant'});$('.admin-main').scrollTo({top:context.mainY,behavior:'instant'});}});}
  function switchEditorTab(name){const names=['info','ingredients','instructions'];if(!names.includes(name))return;for(const item of names){const active=item===name,tab=$('#editor-tab-button-'+item),panel=$('#editor-tab-'+item);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;panel.classList.toggle('hidden',!active);panel.setAttribute('aria-hidden',String(!active));}state.activeEditorTab=name;}
  function updateImageControls(){const hasFile=Boolean(state.pendingImageFile),hasRecipe=Boolean(state.imageRecipeId),ready=state.imageReady;$('#draft-image-picker').disabled=state.imageBusy||(hasRecipe&&!ready);$('#draft-image-save').disabled=state.imageBusy||!hasFile||!hasRecipe||!ready;$('#draft-image-remove').disabled=state.imageBusy||!state.savedAdminImage||!ready;$('#draft-image-cancel').hidden=!hasFile;$('#draft-image-picker').textContent=state.savedAdminImage?'Thay ảnh':'Chọn ảnh';}
  async function loadEditorImage(){
    if(!state.imageRecipeId){state.imageUrl=null;state.savedAdminImage=false;state.imageReady=false;renderImagePreview(null);updateImageControls();imageMessage('Lưu món trước để tải ảnh đã chọn lên. Ảnh mặc định hoặc URL cũ không thể gỡ.');return;}
    state.imageBusy=true;updateImageControls();imageMessage('Đang tải ảnh hiện tại…');
    try{const data=await api('/api/admin/recipes/'+encodeURIComponent(state.imageRecipeId)+'/image');state.imageReady=data.ready===true;state.savedAdminImage=Boolean(data.image);state.imageUrl=data.image_url||null;if(imagePreviewUrl){URL.revokeObjectURL(imagePreviewUrl);imagePreviewUrl=null;}renderImagePreview(state.imageUrl,state.savedAdminImage?'Ảnh Admin đã lưu':'Ảnh mặc định hoặc URL cũ đang hiển thị');if(!state.imageReady)imageMessage('Chưa thể lưu ảnh: cần migration 007 và quyền writer ảnh.');else if(state.savedAdminImage)imageMessage('Ảnh Admin đã lưu. Có thể thay ảnh hoặc gỡ ảnh này.');else imageMessage('Đang hiển thị ảnh mặc định/URL cũ; ảnh này không phải ảnh Admin lưu nên không thể gỡ. Chọn ảnh mới để thay thế.');}
    catch(error){state.imageReady=false;state.savedAdminImage=false;state.imageUrl=null;renderImagePreview(null);imageMessage(error.message||'Không tải được trạng thái ảnh.',true);}finally{state.imageBusy=false;updateImageControls();}
  }
  async function uploadSelectedImage(){
    if(!state.imageRecipeId){imageMessage('Lưu món trước, ảnh đã chọn sẽ được tải lên sau đó.');return;}if(!state.pendingImageFile||!state.imageReady||state.imageBusy)return;
    state.imageBusy=true;updateImageControls();imageMessage('Đang kiểm tra và lưu ảnh…');
    try{await api('/api/admin/recipes/'+encodeURIComponent(state.imageRecipeId)+'/image',{method:'POST',headers:{'Content-Type':state.pendingImageFile.type},body:state.pendingImageFile});state.pendingImageFile=null;$('#draft-image-file').value='';if(imagePreviewUrl){URL.revokeObjectURL(imagePreviewUrl);imagePreviewUrl=null;}await loadEditorImage();markDirty();imageMessage('Ảnh đại diện đã được lưu.');await search();}
    catch(error){imageMessage(error.message||'Không lưu được ảnh. Hãy thử lại.',true);}finally{state.imageBusy=false;updateImageControls();}
  }
  async function removeEditorImage(){
    if(state.pendingImageFile){imageMessage('Hãy lưu hoặc bỏ ảnh mới chọn trước khi gỡ ảnh đã lưu.');return;}if(!state.imageRecipeId||!state.savedAdminImage||!state.imageReady||state.imageBusy)return;if(!window.confirm('Gỡ ảnh đại diện do Admin đã lưu cho món này?'))return;
    state.imageBusy=true;updateImageControls();imageMessage('Đang gỡ ảnh đã lưu…');try{await api('/api/admin/recipes/'+encodeURIComponent(state.imageRecipeId)+'/image',{method:'DELETE'});state.savedAdminImage=false;await loadEditorImage();imageMessage('Đã gỡ ảnh Admin. Ảnh mặc định/URL cũ sẽ được dùng lại.');await search();}catch(error){imageMessage(error.message||'Không gỡ được ảnh. Ảnh hiện tại vẫn được giữ.',true);}finally{state.imageBusy=false;updateImageControls();}
  }
  function populateOptions(select,selectedId,selectedName){select.replaceChildren(new Option('Chọn nguyên liệu v2',''));for(const row of state.ingredientOptions)select.add(new Option(row.name,String(row.ingredient_id)));if(selectedId&&!([...select.options].some(o=>o.value===String(selectedId))))select.add(new Option(selectedName||('ingredient #'+selectedId),String(selectedId)));select.value=selectedId?String(selectedId):'';}
  function addLine(line={}){
    const row=document.createElement('div');row.className='admin-line';const ingredientLabel=document.createElement('label');ingredientLabel.textContent='Nguyên liệu';const select=document.createElement('select');select.required=true;select.setAttribute('aria-label','Nguyên liệu');populateOptions(select,line.ingredient_id,line.name);ingredientLabel.append(select);
    const quantityLabel=document.createElement('label');quantityLabel.textContent='Lượng theo nguồn (nếu có)';const quantity=document.createElement('input');quantity.type='text';quantity.maxLength=255;quantity.placeholder='Để trống nếu chưa xác minh';quantity.dataset.quantity='1';quantity.value=line.quantity_raw||'';quantityLabel.append(quantity);
    const remove=document.createElement('button');remove.type='button';remove.className='button-secondary';remove.textContent='Xóa dòng';remove.onclick=()=>{row.remove();markDirty();};row.append(ingredientLabel,quantityLabel,remove);row.addEventListener('input',markDirty);row.addEventListener('change',markDirty);$('#draft-lines').append(row);
  }
  async function refreshIngredientOptions(){const query=$('#draft-ingredient-query').value.trim();try{const data=await api('/api/ingredients?query='+encodeURIComponent(query)+'&limit=50');state.ingredientOptions=(data.items||[]).filter(row=>Number.isSafeInteger(row.id)&&row.id>0).map(row=>({ingredient_id:row.id,name:row.name}));for(const row of $('#draft-lines').querySelectorAll('.admin-line')){const select=row.querySelector('select'),id=select.value,name=select.selectedOptions[0]?.textContent;populateOptions(select,id,name);}}catch(error){setMessage($('#draft-message'),error.message||'Kh\u00f4ng t\u1ea3i đ\u01b0\u1ee3c nguy\u00ean li\u1ec7u.',true);}}
  function invalidField(element,message,tab){switchEditorTab(tab);setMessage($('#draft-message'),message,true);element.setAttribute('aria-invalid','true');element.focus({preventScroll:true});return false;}
  function validateEditor(body){for(const field of $('#admin-draft-form').querySelectorAll('[aria-invalid=true]'))field.removeAttribute('aria-invalid');if(!body.title)return invalidField($('#draft-title'),'Nhập tên món ăn.','info');if(!Number.isInteger(body.minutes)||body.minutes<1||body.minutes>240)return invalidField($('#draft-minutes'),'Thời gian cần là số nguyên từ 1 đến 240 phút.','info');if(body.ingredients.length===0||body.ingredients.some(line=>!Number.isSafeInteger(line.ingredient_id)||line.ingredient_id<=0))return invalidField($('#draft-ingredient-query'),'Thêm ít nhất một nguyên liệu hợp lệ.','ingredients');if(!body.instructions)return invalidField($('#draft-instructions'),'Nhập hướng dẫn chế biến.','instructions');return true;}
  async function openEditor(revisionId=null,legacyRecipeId=null,returnFocus=document.activeElement,publicRecipeId=null){
    if(legacyRecipeId!==null?!state.legacyOverlayReady:!state.recipeCatalogReady){setMessage($('#admin-status'),$('#admin-create').title||'Backend chưa sẵn sàng tạo món.',true);return;}const detail=$('#admin-detail');if(detail.open)closeDialog(detail,{restore:false});
    state.revisionId=revisionId;state.revisionVersion=null;state.legacyVersion=null;state.recipeId=publicRecipeId;state.legacyRecipeId=legacyRecipeId;state.createKey=(!revisionId&&legacyRecipeId===null)?newRequestKey():null;state.imageRecipeId=legacyRecipeId??publicRecipeId;state.imageUrl=null;state.savedAdminImage=false;state.imageReady=false;state.pendingImageFile=null;state.dirty=false;state.busy=false;state.imageBusy=false;
    $('#admin-draft-form').reset();$('#draft-lines').replaceChildren();$('#draft-image-file').value='';if(imagePreviewUrl){URL.revokeObjectURL(imagePreviewUrl);imagePreviewUrl=null;}renderImagePreview(null);switchEditorTab('info');$('#admin-editor-title').textContent=revisionId||legacyRecipeId!==null?'S\u1eeda m\u00f3n \u0103n':'Th\u00eam m\u00f3n \u0103n';$('#admin-editor').setAttribute('aria-busy','true');setMessage($('#draft-message'),'\u0110ang t\u1ea3i d\u1eef li\u1ec7u\u2026');openDialog($('#admin-editor'),returnFocus);
    try{await refreshIngredientOptions();if(legacyRecipeId!==null){const row=await api('/api/admin/legacy-recipes/'+encodeURIComponent(legacyRecipeId));state.legacyVisible=row.is_visible;state.legacyVersion=row.edit_version;$('#draft-role').value='main';$('#draft-title').value=row.title;$('#draft-description').value=row.description||'';$('#draft-instructions').value=row.instructions;$('#draft-minutes').value=row.minutes;for(const line of row.ingredients)addLine({ingredient_id:line.id,name:line.name,quantity_raw:line.quantity||''});}else if(revisionId){const row=await api('/api/admin/revisions/'+encodeURIComponent(revisionId));state.revisionVersion=row.edit_version;state.recipeId=Number(row.recipe_id);state.imageRecipeId=state.recipeId;$('#draft-role').value=row.role||'main';$('#draft-title').value=row.title;$('#draft-description').value=row.description||'';$('#draft-instructions').value=row.instructions;$('#draft-minutes').value=row.minutes??'';for(const line of row.ingredients)addLine(line);}else{state.recipeId=null;state.imageRecipeId=null;$('#draft-role').value='main';addLine();}
      await loadEditorImage();state.savedDraftSnapshot=JSON.stringify(currentDraft());state.dirty=false;setMessage($('#draft-message'),legacyRecipeId!==null?'Thay đổi món ăn đã được lưu.':'Lưu hợp lệ sẽ hiển thị món trên website User.');$('#draft-title').focus({preventScroll:true});
    }catch(error){setMessage($('#draft-message'),error.message||'Không tải được dữ liệu món.',true);}finally{$('#admin-editor').setAttribute('aria-busy','false');updateImageControls();}
  }
  async function restoreDraftAfterReauth(){
    if(new URLSearchParams(location.search).get('restore_draft')!=='1')return;
    let saved;try{saved=JSON.parse(sessionStorage.getItem('adminDraftReauth')||'null');}catch{saved=null;}
    if(!saved||saved.version!==1||Date.now()-saved.savedAt>30*60*1000||!saved.body||typeof saved.body.title!=='string'){
      sessionStorage.removeItem('adminDraftReauth');setMessage($('#admin-status'),'Không tìm thấy biểu mẫu chưa lưu để khôi phục.',true);return;
    }
    try{
      await openEditor(saved.revisionId??null,saved.legacyRecipeId??null,$('#admin-create'));
      $('#draft-title').value=saved.body.title;$('#draft-description').value=saved.body.description||'';
      $('#draft-instructions').value=saved.body.instructions||'';$('#draft-minutes').value=saved.body.minutes??'';
      $('#draft-role').value=saved.body.role||'main';state.recipeId=saved.recipeId??state.recipeId;state.revisionVersion=saved.revisionVersion??state.revisionVersion;state.createKey=saved.createKey||state.createKey;state.imageRecipeId=state.recipeId;
      state.legacyVersion=saved.legacyVersion??state.legacyVersion;$('#draft-lines').replaceChildren();for(const line of saved.body.ingredients||[])addLine(line);
      if(saved.legacyRecipeId!==null&&saved.legacyRecipeId!==undefined)state.legacyVisible=saved.legacyVisible===true;
      state.dirty=true;sessionStorage.removeItem('adminDraftReauth');
      setMessage($('#draft-message'),saved.imageNeedsReselect?'Đã khôi phục nội dung biểu mẫu. Hãy chọn lại ảnh vì tệp ảnh chưa tải lên không thể giữ sau khi đăng nhập.':'Đã khôi phục nội dung chưa lưu. Kiểm tra rồi nhấn “Lưu thay đổi”.');
    }catch(error){setMessage($('#admin-status'),error.message||'Không khôi phục được biểu mẫu chưa lưu.',true);}
  }
  function finishEditor(){if(imagePreviewUrl){URL.revokeObjectURL(imagePreviewUrl);imagePreviewUrl=null;}state.pendingImageFile=null;state.dirty=false;state.revisionId=null;state.revisionVersion=null;state.legacyVersion=null;state.legacyRecipeId=null;state.imageRecipeId=null;state.savedAdminImage=false;state.imageReady=false;$('#draft-image-file').value='';}
  function closeEditor(force=false){if(state.dirty&&!force&&!window.confirm('Hủy các thay đổi chưa lưu?'))return;finishEditor();closeDialog($('#admin-editor'));}
  async function saveDraft(event){event.preventDefault();if(state.busy)return;const body=currentDraft();if(!validateEditor(body))return;state.busy=true;const save=$('#draft-save');save.disabled=true;save.textContent='Đang lưu…';$('#admin-editor').setAttribute('aria-busy','true');setMessage($('#draft-message'),'Đang lưu thay đổi…');let recipeSaved=false;
    try{const legacy=state.legacyRecipeId!==null;if(legacy){const data={...body,minutes:body.minutes,is_visible:state.legacyVisible,expected_version:state.legacyVersion,ingredients:body.ingredients.map(line=>({ingredient_id:line.ingredient_id,quantity:line.quantity_raw||'',is_required:true}))};await api('/api/admin/legacy-recipes/'+encodeURIComponent(state.legacyRecipeId),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});recipeSaved=true;}else{const update=state.recipeId!==null&&state.revisionId!==null;const url=update?'/api/admin/catalog-recipes/'+encodeURIComponent(state.recipeId)+'?revision_id='+encodeURIComponent(state.revisionId):'/api/admin/catalog-recipes';const wireBody=update?{...body,expected_version:state.revisionVersion}:{...body,idempotency_key:state.createKey};const saved=await api(url,{method:update?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(wireBody)});recipeSaved=true;state.recipeId=Number(saved.recipe_id);state.revisionId=Number(saved.revision_id);state.imageRecipeId=state.recipeId;await loadEditorImage();}
      state.savedDraftSnapshot=JSON.stringify(currentDraft());markDirty();if(state.pendingImageFile){await uploadSelectedImage();if(state.pendingImageFile)throw new Error('Món đã lưu nhưng ảnh chưa tải lên; ảnh vẫn được giữ để thử lại.');}state.dirty=false;setMessage($('#admin-status'),legacy?'Đã lưu thay đổi món ăn.':'Đã lưu món ăn.');closeEditor(true);await Promise.all([loadDashboard(),search()]);
    }catch(error){showDraftError(error);if(recipeSaved)await Promise.all([loadDashboard(),search()]);}finally{state.busy=false;save.disabled=false;save.textContent='Lưu thay đổi';$('#admin-editor').setAttribute('aria-busy','false');}
  }
  async function loadDetailImage(recipeId){
    try{const data=await api('/api/admin/recipes/'+encodeURIComponent(recipeId)+'/image');if(Number($('#admin-detail').dataset.recipeId)!==Number(recipeId))return;const figure=document.createElement('figure');figure.className='admin-detail-cover';const img=document.createElement('img');img.src=data.image_url||'/static/images/recipes/placeholder.svg';img.alt='Ảnh đại diện món ăn';figure.append(img);$('#admin-detail-content').prepend(figure);}catch{}
  }
  async function showRevision(id){
    const version=++state.detailRequestVersion;
    const dialog=$('#admin-detail');openDialog(dialog);dialog.dataset.recipeId='';$('#admin-detail-title').textContent='\u0110ang t\u1ea3i chi ti\u1ebft\u2026';
    const detail=$('#admin-detail-content');detail.className='admin-dialog-scroll admin-detail-content';detail.textContent='\u0110ang t\u1ea3i th\u00f4ng tin m\u00f3n\u2026';
    try{
      const row=await api('/api/admin/revisions/'+encodeURIComponent(id));if(version!==state.detailRequestVersion)return;
      dialog.dataset.recipeId=String(row.recipe_id);$('#admin-detail-title').textContent=row.title;$('#admin-detail-title').dataset.revisionId=String(id);
      const items=row.ingredients.length?row.ingredients.map(item=>'<li>'+esc(item.name||'')+(item.quantity_raw?' \u2014 '+esc(item.quantity_raw):'')+'</li>').join(''):'<li>Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u nguy\u00ean li\u1ec7u.</li>';
      const roles={main:'M\u00f3n ch\u00ednh',vegetable:'M\u00f3n rau',soup:'M\u00f3n canh'};
      detail.innerHTML='<div class="admin-detail-grid"><p><b>Lo\u1ea1i m\u00f3n:</b> '+esc(roles[row.role]||'Ch\u01b0a ph\u00e2n lo\u1ea1i')+'</p><p><b>Th\u1eddi gian n\u1ea5u:</b> '+esc(row.minutes??'\u2014')+(row.minutes?' ph\u00fat':'')+'</p><p><b>M\u00f4 t\u1ea3:</b> '+esc(row.description||'Ch\u01b0a c\u00f3 m\u00f4 t\u1ea3')+'</p></div><h3>Nguy\u00ean li\u1ec7u</h3><ul>'+items+'</ul><h3>H\u01b0\u1edbng d\u1eabn ch\u1ebf bi\u1ebfn</h3><p class="admin-steps">'+esc(row.instructions||'Ch\u01b0a c\u00f3 h\u01b0\u1edbng d\u1eabn.')+'</p>';
      void loadDetailImage(row.recipe_id);
      if(state.recipeCatalogReady){const actions=document.createElement('div');actions.className='admin-modal-actions';const edit=document.createElement('button');edit.type='button';edit.className='button-primary';edit.textContent='Chỉnh sửa';edit.onclick=()=>openEditor(id,null,edit,row.recipe_id);actions.append(edit);detail.append(actions);}
    }catch(error){if(version===state.detailRequestVersion)detail.textContent=error.message||'Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c th\u00f4ng tin m\u00f3n \u0103n.';}
  }
  async function showLegacyRecipe(id){
    const version=++state.detailRequestVersion;
    const dialog=$('#admin-detail');openDialog(dialog);dialog.dataset.recipeId=String(id);$('#admin-detail-title').textContent='\u0110ang t\u1ea3i chi ti\u1ebft\u2026';
    const detail=$('#admin-detail-content');detail.className='admin-dialog-scroll admin-detail-content';detail.textContent='\u0110ang t\u1ea3i th\u00f4ng tin m\u00f3n\u2026';
    try{
      const row=await api('/api/admin/legacy-recipes/'+encodeURIComponent(id));if(version!==state.detailRequestVersion)return;
      dialog.dataset.recipeId=String(row.recipe_id);$('#admin-detail-title').textContent=row.title;
      const items=row.ingredients.length?row.ingredients.map(item=>'<li>'+esc(item.name)+(item.quantity?' \u2014 '+esc(item.quantity):'')+'</li>').join(''):'<li>Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u nguy\u00ean li\u1ec7u.</li>';
      const roles={main:'M\u00f3n ch\u00ednh',vegetable:'M\u00f3n rau',soup:'M\u00f3n canh'};
      detail.innerHTML='<div class="admin-detail-grid"><p><b>Lo\u1ea1i m\u00f3n:</b> '+esc(roles[row.role]||'Ch\u01b0a ph\u00e2n lo\u1ea1i')+'</p><p><b>Th\u1eddi gian n\u1ea5u:</b> '+esc(row.minutes??'\u2014')+(row.minutes?' ph\u00fat':'')+'</p><p><b>M\u00f4 t\u1ea3:</b> '+esc(row.description||'Ch\u01b0a c\u00f3 m\u00f4 t\u1ea3')+'</p></div><h3>Nguy\u00ean li\u1ec7u</h3><ul>'+items+'</ul><h3>H\u01b0\u1edbng d\u1eabn ch\u1ebf bi\u1ebfn</h3><p class="admin-steps">'+esc(row.instructions||'Ch\u01b0a c\u00f3 h\u01b0\u1edbng d\u1eabn.')+'</p>';
      void loadDetailImage(row.recipe_id);
      if(state.legacyOverlayReady){const actions=document.createElement('div');actions.className='admin-modal-actions';const edit=document.createElement('button');edit.type='button';edit.className='button-primary';edit.textContent='Ch\u1ec9nh s\u1eeda';edit.onclick=()=>openEditor(null,Number(id));actions.append(edit);detail.append(actions);}
    }catch(error){if(version===state.detailRequestVersion)detail.textContent=error.message||'Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c th\u00f4ng tin m\u00f3n \u0103n.';}
  }
  $('#admin-search').addEventListener('submit',e=>{e.preventDefault();state.recipeOffset=0;search();});
  for(const id of ['admin-recipe-role','admin-recipe-visibility','admin-recipe-max-minutes'])$('#'+id).addEventListener('change',()=>{state.recipeOffset=0;search();});
  $('#admin-recipes-prev').onclick=()=>{state.recipeOffset=Math.max(0,state.recipeOffset-20);search();};
  $('#admin-recipes-next').onclick=()=>{state.recipeOffset+=20;search();};
  $('#admin-ingredient-search').addEventListener('submit',e=>{e.preventDefault();state.ingredientOffset=0;loadIngredientPage();});
  $('#admin-ingredient-create').onclick=()=>openIngredientForm();
  $('#admin-ingredient-cancel').onclick=()=>$('#admin-ingredient-form').classList.add('hidden');
  $('#admin-ingredient-form').addEventListener('submit',saveIngredient);
  $('#admin-ingredient-prev').onclick=()=>{state.ingredientOffset=Math.max(0,state.ingredientOffset-20);loadIngredientPage();};
  $('#admin-ingredient-next').onclick=()=>{state.ingredientOffset+=20;loadIngredientPage();};
  $('#admin-ingredients').addEventListener('click',event=>{
    const edit=event.target.closest('[data-ingredient-edit]'),toggle=event.target.closest('[data-ingredient-active]');
    if(edit){const id=Number(edit.dataset.ingredientEdit),item=state.ingredientRows?.find(row=>row.ingredient_id===id);if(item)openIngredientForm(item);}
    else if(toggle)setIngredientActive(Number(toggle.dataset.ingredientActive),toggle.dataset.nextActive==='true');
  });
  $('#admin-recipes').addEventListener('click',e=>{const view=e.target.closest('[data-view]'),edit=e.target.closest('[data-edit]'),legacyView=e.target.closest('[data-view-legacy]'),legacyEdit=e.target.closest('[data-edit-legacy]');if(legacyView)showLegacyRecipe(legacyView.dataset.viewLegacy);else if(legacyEdit)openEditor(null,Number(legacyEdit.dataset.editLegacy),legacyEdit);else if(view)showRevision(view.dataset.view);else if(edit)openEditor(Number(edit.dataset.edit),null,edit,Number(edit.dataset.publicId));else setRecipeLifecycle(e);});
  $('#admin-detail-close').onclick=()=>closeDialog($('#admin-detail'));
  $('#admin-create').onclick=()=>openEditor(null,null,$('#admin-create'));$('#admin-editor-close').onclick=()=>closeEditor();$('#draft-cancel').onclick=()=>closeEditor();
  $('#draft-add-line').onclick=()=>{addLine();markDirty();};$('#admin-draft-form').addEventListener('input',event=>{event.target.removeAttribute('aria-invalid');markDirty();});$('#admin-draft-form').addEventListener('change',event=>{if(event.target.id!=='draft-image-file'){event.target.removeAttribute('aria-invalid');markDirty();}});$('#admin-draft-form').addEventListener('submit',saveDraft);
  for(const name of ['info','ingredients','instructions'])$('#editor-tab-button-'+name).addEventListener('click',()=>switchEditorTab(name));
  $('.admin-editor-tabs').addEventListener('keydown',event=>{const tabs=['info','ingredients','instructions'],index=tabs.indexOf(state.activeEditorTab);let next=null;if(event.key==='ArrowRight')next=(index+1)%tabs.length;else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=tabs.length-1;if(next!==null){event.preventDefault();const name=tabs[next];switchEditorTab(name);$('#editor-tab-button-'+name).focus({preventScroll:true});}});
  let ingredientTimer;$('#draft-ingredient-query').addEventListener('input',()=>{clearTimeout(ingredientTimer);ingredientTimer=setTimeout(refreshIngredientOptions,250);});
  $('#draft-image-picker').addEventListener('click',()=>{if(!$('#draft-image-picker').disabled)$('#draft-image-file').click();});
  $('#draft-image-file').addEventListener('change',event=>{
    const file=event.target.files?.[0];if(imagePreviewUrl){URL.revokeObjectURL(imagePreviewUrl);imagePreviewUrl=null;}
    if(!file){state.pendingImageFile=null;renderImagePreview(state.imageUrl);markDirty();updateImageControls();return;}
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>5*1024*1024){event.target.value='';state.pendingImageFile=null;renderImagePreview(state.imageUrl);imageMessage('Ảnh cần là JPG, PNG hoặc WebP và tối đa 5 MB.',true);markDirty();updateImageControls();return;}
    state.pendingImageFile=file;imagePreviewUrl=URL.createObjectURL(file);renderImagePreview(imagePreviewUrl,'Ảnh mới xem trước trên thiết bị');markDirty();updateImageControls();imageMessage(state.imageRecipeId?'Ảnh mới chỉ đang xem trước. Nhấn “Lưu ảnh” để tải lên; biểu mẫu món chưa được gửi.':'Ảnh sẽ tải lên sau khi lưu món mới.');
  });
  $('#draft-image-save').onclick=uploadSelectedImage;$('#draft-image-remove').onclick=removeEditorImage;
  $('#draft-image-cancel').onclick=()=>{state.pendingImageFile=null;$('#draft-image-file').value='';if(imagePreviewUrl){URL.revokeObjectURL(imagePreviewUrl);imagePreviewUrl=null;}renderImagePreview(state.imageUrl);markDirty();updateImageControls();imageMessage(state.savedAdminImage?'Ảnh Admin hiện tại vẫn được giữ.':'Ảnh mặc định/URL cũ vẫn được giữ.');};
  const editorDialog=$('#admin-editor'),detailDialog=$('#admin-detail');
  editorDialog.addEventListener('cancel',event=>{event.preventDefault();closeEditor();});
  detailDialog.addEventListener('cancel',event=>{event.preventDefault();closeDialog(detailDialog);});
  editorDialog.addEventListener('click',event=>{if(event.target===editorDialog&&!state.dirty)closeEditor(true);});
  detailDialog.addEventListener('click',event=>{if(event.target===detailDialog)closeDialog(detailDialog);});
  window.addEventListener('beforeunload',e=>{if(state.dirty&&!state.busy&&!state.reauthenticating){e.preventDefault();e.returnValue='';}});
  $('#admin-logout').onclick=async()=>{try{await api('/api/admin/logout',{method:'POST'});}finally{location.assign('/admin/login');}};
  (async()=>{try{await loadSession();await loadDashboard();await Promise.all([search(),loadIngredientPage()]);await restoreDraftAfterReauth();}catch(error){setMessage($('#admin-status'),error.message||'Không tải được dữ liệu Admin.',true);}})();
})();
