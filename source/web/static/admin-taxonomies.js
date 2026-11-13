(() => {
  const managers=[...document.querySelectorAll('[data-taxonomy-manager]')];
  if(!managers.length)return;
  const groups={region:'Vùng miền',diet:'Chay / mặn',occasion:'Hoàn cảnh',weather:'Thời tiết',cooking_method:'Cách chế biến',main_ingredient:'Nguyên liệu chính',dish_type:'Loại món'};
  const state={csrf:''};
  async function api(url,options={}){
    const headers={...(options.headers||{})};
    if(state.csrf)headers['X-CSRF-Token']=state.csrf;
    const response=await fetch(url,{...options,headers,credentials:'same-origin',cache:'no-store'});
    const envelope=await response.json();
    if(response.status===401){location.assign('/admin/login');throw new Error('Phiên Admin đã hết hạn.');}
    if(!response.ok||envelope.ok!==true)throw new Error(envelope.error?.message||'Không thể hoàn tất thao tác.');
    return envelope.data;
  }
  function setMessage(root,text,error=false){const node=root.querySelector('[data-taxonomy-status]');node.textContent=text;node.classList.toggle('error',error);}
  function element(tag,text,attrs={}){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);return node;}

  for(const root of managers){
    const kind=root.dataset.kind;
    const query=root.querySelector('[data-taxonomy-query]');
    const group=root.querySelector('[data-taxonomy-group]');
    const stateSelect=root.querySelector('[data-taxonomy-state]');
    const form=root.querySelector('[data-taxonomy-form]');
    const code=root.querySelector('[data-taxonomy-code]');
    const label=root.querySelector('[data-taxonomy-label]');
    const description=root.querySelector('[data-taxonomy-description]');
    const editGroup=root.querySelector('[data-taxonomy-edit-group]');
    const rows=root.querySelector('[data-taxonomy-rows]');
    const recipeSelect=root.querySelector('[data-taxonomy-recipe]');
    const recipeQuery=root.querySelector('[data-taxonomy-recipe-query]');
    const options=root.querySelector('[data-taxonomy-options]');
    const linkSave=root.querySelector('[data-taxonomy-save-links]');
    const local={items:[],editing:null,recipeId:'',busy:false,reloadPending:false};
    const listUrl=()=>{
      const params=new URLSearchParams({kind,query:query.value.trim(),status:stateSelect.value,limit:'100',offset:'0'});
      if(group&&group.value)params.set('group',group.value);
      return '/api/admin/taxonomies?'+params;
    };
    function hideForm(){form.classList.add('hidden');local.editing=null;form.reset();if(kind==='dish_type')code.readOnly=false;}
    function showForm(item=null){
      local.editing=item;form.classList.remove('hidden');
      root.querySelector('[data-taxonomy-form-title]').textContent=item?(kind==='dish_type'?'Sửa loại món':'Sửa phân loại'):(kind==='dish_type'?'Thêm loại món':'Thêm phân loại');
      if(editGroup)editGroup.value=item?.group||'region';
      code.value=item?.code||'';code.readOnly=Boolean(item);
      label.value=item?.label||'';description.value=item?.description||'';
      label.focus();
    }
    async function load(){
      if(local.busy){local.reloadPending=true;return;}local.busy=true;setMessage(root,'Đang tải danh mục…');
      try{
        const data=await api(listUrl());local.items=data.items;rows.replaceChildren();
        root.querySelector('[data-taxonomy-empty]').classList.toggle('hidden',data.items.length>0);
        for(const item of data.items){
          const tr=document.createElement('tr');
          const title=element('td');title.append(element('strong',item.label));
          if(item.is_core)title.append(element('small','Loại cốt lõi · không thể xóa vĩnh viễn',{class:'admin-muted'}));
          tr.append(title);
          if(kind==='classification')tr.append(element('td',groups[item.group]||item.group));
          tr.append(element('td',item.code));tr.append(element('td',String(item.recipe_count)));
          tr.append(element('td',item.deleted?'Đã xóa mềm':'Đang dùng'));
          const actions=element('td');actions.className='admin-taxonomy-actions';
          const edit=element('button','Sửa',{type:'button','data-taxonomy-action':'edit','data-id':item.tag_id,class:'button-secondary'});actions.append(edit);
          if(item.deleted){actions.append(element('button','Khôi phục',{type:'button','data-taxonomy-action':'restore','data-id':item.tag_id,class:'button-secondary'}));}
          else if(!item.is_core){actions.append(element('button','Xóa mềm',{type:'button','data-taxonomy-action':'soft-delete','data-id':item.tag_id,class:'button-secondary'}));}
          if(!item.is_core)actions.append(element('button','Xóa vĩnh viễn',{type:'button','data-taxonomy-action':'permanent','data-id':item.tag_id,class:'button-danger'}));
          tr.append(actions);rows.append(tr);
        }
        setMessage(root,`${data.total} mục trong danh mục.`);
      }catch(error){setMessage(root,error.message,true);}finally{local.busy=false;if(local.reloadPending){local.reloadPending=false;await load();}}
    }
    async function loadRecipes(){
      try{
        const params=new URLSearchParams({query:recipeQuery.value.trim(),limit:'50',offset:'0',visibility:'visible'});
        const data=await api('/api/admin/recipes?'+params);recipeSelect.replaceChildren(element('option','Chọn công thức',{value:''}));
        for(const recipe of data.items){const option=element('option',`${recipe.title} · #${recipe.recipe_id}`,{value:recipe.recipe_id});recipeSelect.append(option);}
        if(local.recipeId&&data.items.some(item=>String(item.recipe_id)===local.recipeId))recipeSelect.value=local.recipeId;
        if(data.total>data.items.length)setMessage(root,`Đã tải ${data.items.length}/${data.total} công thức. Hãy thu hẹp nội dung tìm kiếm.`);
      }catch(error){setMessage(root,error.message,true);}
    }
    async function loadAssignments(){
      local.recipeId=recipeSelect.value;options.replaceChildren();
      if(!local.recipeId)return;
      try{
        const data=await api(`/api/admin/recipes/${local.recipeId}/taxonomies?kind=${kind}`);
        const byGroup=new Map();
        for(const item of data.items){if(!byGroup.has(item.group))byGroup.set(item.group,[]);byGroup.get(item.group).push(item);}
        for(const [groupName,items] of byGroup){
          const fieldset=element('fieldset');fieldset.className='admin-taxonomy-group';fieldset.append(element('legend',groups[groupName]||groupName));
          for(const item of items){
            const line=element('label');line.className='admin-taxonomy-choice';
            const input=element('input',undefined,{type:'checkbox','data-tag-id':item.tag_id});input.checked=item.selected;
            if(item.deleted&&!item.selected)input.disabled=true;
            input.addEventListener('change',()=>{if(item.deleted&&!input.checked)input.dataset.removed='true';});
            line.append(input,document.createTextNode(`${item.label}${item.deleted?' · đã xóa mềm':''}${item.is_core?' · cốt lõi':''}`));fieldset.append(line);
          }
          options.append(fieldset);
        }
        setMessage(root,'Đã tải liên kết hiện có của công thức.');
      }catch(error){setMessage(root,error.message,true);}
    }
    root.querySelector('[data-taxonomy-search]').addEventListener('submit',event=>{event.preventDefault();load();});
    root.querySelector('[data-taxonomy-create]').addEventListener('click',()=>showForm());
    root.querySelector('[data-taxonomy-cancel]').addEventListener('click',hideForm);
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      const body={kind,group:kind==='dish_type'?'dish_type':editGroup.value,code:code.value.trim(),label:label.value.trim(),description:description.value.trim()};
      try{await api(local.editing?`/api/admin/taxonomies/${local.editing.tag_id}`:'/api/admin/taxonomies',{method:local.editing?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});hideForm();setMessage(root,'Đã lưu danh mục.');await load();}
      catch(error){setMessage(root,error.message,true);}
    });
    rows.addEventListener('click',async event=>{
      const button=event.target.closest('[data-taxonomy-action]');if(!button)return;
      const item=local.items.find(row=>row.tag_id===Number(button.dataset.id));if(!item)return;
      const action=button.dataset.taxonomyAction;
      try{
        if(action==='edit'){showForm(item);return;}
        if(action==='permanent'&&!window.confirm(`Xóa vĩnh viễn “${item.label}”? Chỉ thực hiện được khi không còn công thức liên kết.`))return;
        if(action==='permanent')await api(`/api/admin/taxonomies/${item.tag_id}/permanent`,{method:'DELETE'});
        else await api(`/api/admin/taxonomies/${item.tag_id}/deleted`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({deleted:action==='soft-delete'})});
        setMessage(root,'Đã cập nhật danh mục.');await load();
      }catch(error){setMessage(root,error.message,true);}
    });
    root.querySelector('[data-taxonomy-find-recipes]').addEventListener('click',loadRecipes);
    recipeQuery.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();loadRecipes();}});
    recipeSelect.addEventListener('change',loadAssignments);
    linkSave.addEventListener('click',async()=>{
      if(!recipeSelect.value){setMessage(root,'Hãy chọn công thức trước khi lưu liên kết.',true);return;}
      const tag_ids=[...options.querySelectorAll('input[data-tag-id]:checked')].map(input=>Number(input.dataset.tagId));
      try{await api(`/api/admin/recipes/${recipeSelect.value}/taxonomies`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,tag_ids})});setMessage(root,'Đã lưu các liên kết với công thức.');await loadAssignments();await load();}
      catch(error){setMessage(root,error.message,true);}
    });
    stateSelect.addEventListener('change',load);if(group)group.addEventListener('change',load);
    (async()=>{try{const session=await api('/api/admin/session');state.csrf=session.csrf_token;await Promise.all([load(),loadRecipes()]);}catch(error){setMessage(root,error.message,true);}})();
  }
})();
