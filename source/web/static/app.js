const state={available:new Map(),excluded:new Map(),ingredients:new Map()};
const $=id=>document.getElementById(id);
const esc=value=>{const node=document.createElement('div');node.textContent=String(value??'');return node.innerHTML};

async function loadIngredients(query=''){
  const box=$('ingredient-results');
  try{
    const response=await fetch('/api/ingredients?query='+encodeURIComponent(query)+'&limit=50');
    const envelope=await response.json();
    if(!response.ok)throw Error(envelope.error?.message||'Không tải được nguyên liệu');
    (envelope.data.items||[]).forEach(item=>state.ingredients.set(item.id,item.name));
    box.innerHTML=(envelope.data.items||[]).filter(item=>!state.available.has(item.id)&&!state.excluded.has(item.id)).map(item=>`<button class="ingredient-option" data-id="${item.id}">${esc(item.name)}<small>+ chọn</small></button>`).join('');
    box.querySelectorAll('[data-id]').forEach(button=>button.onclick=()=>selectIngredient(Number(button.dataset.id)));
  }catch(error){box.innerHTML=`<div class="message error">${esc(error.message)}</div>`}
}

function selectIngredient(id){
  if(state.available.size>=30)return;
  const name=state.ingredients.get(id)||`Nguyên liệu #${id}`;
  state.excluded.delete(id); state.available.set(id,name); render(); loadIngredients($('ingredient-search').value);
}
function removeAvailable(id){state.available.delete(id);render();loadIngredients($('ingredient-search').value)}
function toggleExclude(id){
  const name=state.available.get(id);
  if(!name)return;
  state.available.delete(id);state.excluded.set(id,name);render();loadIngredients($('ingredient-search').value);
}
function restoreIngredient(id){
  const name=state.excluded.get(id);
  if(!name)return;
  if(state.available.size<30){state.excluded.delete(id);state.available.set(id,name);render();loadIngredients($('ingredient-search').value)}
}
function render(){
  const selected=$('selected-ingredients');
  selected.className='chips'+(state.available.size?'':' empty');
  selected.innerHTML=state.available.size?[...state.available].map(([id,name])=>`<span class="chip">${esc(name)}<button title="Chuyển sang loại trừ" data-exclude="${id}">⊘</button><button title="Xóa" data-remove="${id}">×</button></span>`).join(''):'Chưa có nguyên liệu nào';
  $('selected-count').textContent=state.available.size+'/30';
  const excluded=$('excluded-ingredients');
  excluded.className='chips'+(state.excluded.size?'':' empty');
  excluded.innerHTML=state.excluded.size?[...state.excluded].map(([id,name])=>`<span class="chip excluded">${esc(name)}<button title="Chuyển lại nguyên liệu có sẵn" data-restore="${id}">↶</button></span>`).join(''):'Chưa loại trừ nguyên liệu nào';
  $('recommend-button').disabled=!state.available.size;
  selected.querySelectorAll('[data-exclude]').forEach(button=>button.onclick=()=>toggleExclude(Number(button.dataset.exclude)));
  selected.querySelectorAll('[data-remove]').forEach(button=>button.onclick=()=>removeAvailable(Number(button.dataset.remove)));
  excluded.querySelectorAll('[data-restore]').forEach(button=>button.onclick=()=>restoreIngredient(Number(button.dataset.restore)));
}

function showError(message){
  const box=$('message');box.className='message error';box.textContent=message;$('empty-state').classList.add('hidden');$('results').innerHTML='';$('result-count').textContent='';
}
function showEmpty(message='Hãy chọn vài nguyên liệu',detail='Chúng tôi sẽ tìm những món có thể nấu ngay hôm nay.'){
  $('empty-state').classList.remove('hidden');$('empty-state').querySelector('h3').textContent=message;$('empty-state').querySelector('p').textContent=detail;
}
async function recommend(){
  const loading=$('loading');loading.classList.remove('hidden');$('message').className='message hidden';$('results').innerHTML='';$('empty-state').classList.add('hidden');
  try{
    const body={ingredient_ids:[...state.available.keys()],excluded_ids:[...state.excluded.keys()],top_k:Number($('top-k').value||5),algorithm:'proposed'};
    if($('max-minutes').value)body.max_minutes=Number($('max-minutes').value);
    const response=await fetch('/api/recommend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const envelope=await response.json();
    if(!response.ok)throw Error(envelope.error?.message||'Không thể lấy gợi ý');
    const items=envelope.data.items||[];$('result-count').textContent=items.length+' món';
    if(!items.length){showEmpty('Chưa tìm thấy món phù hợp','Thử bỏ bớt nguyên liệu loại trừ hoặc tăng thời gian tối đa.');return}
    $('results').innerHTML=items.map(item=>`<article class="recipe-card"><div class="recipe-top"><h3>${esc(item.title)}</h3><span class="score">${Math.round(item.score*100)}%</span></div><div class="meta-row"><span>⏱ ${item.minutes} phút</span><span>Phù hợp theo P1</span></div><div class="tag-label">Đã có · ${item.matched_ids.length}</div><div class="id-list">${item.matched_ids.map(id=>esc(state.ingredients.get(id)||'Nguyên liệu #'+id)).join(', ')||'—'}</div><div class="tag-label">Còn thiếu · ${item.missing_count}</div><div class="id-list missing">${item.missing_ids.map(id=>esc(state.ingredients.get(id)||'Nguyên liệu #'+id)).join(', ')||'Không thiếu nguyên liệu bắt buộc'}</div><a class="detail-link" href="/recipes/${item.recipe_id}">Xem công thức →</a></article>`).join('');
  }catch(error){showError(error.message)}finally{loading.classList.add('hidden')}
}

let timer;
$('ingredient-search').addEventListener('input',event=>{clearTimeout(timer);timer=setTimeout(()=>loadIngredients(event.target.value),250)});
$('recommend-button').onclick=recommend;
loadIngredients();render();
fetch('/api/health').then(response=>{if(!response.ok)throw Error();$('server-status').textContent='TCP Server đang hoạt động'}).catch(()=>{$('server-status').textContent='TCP Server không khả dụng';$('server-status').style.background='#fff0ec';$('server-status').style.color='#a34d36'});
