const detailRoot=document.getElementById('detail');
const escapeHtml=value=>{const node=document.createElement('div');node.textContent=String(value??'');return node.innerHTML};
function databaseSteps(instructions){
  const text=String(instructions??'').trim();
  const lines=text.split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
  return lines.length?lines:[text];
}
function renderRecipe(data){
  const steps=databaseSteps(data.instructions);
  const stepsHtml=steps.length>1
    ? `<ol class="step-list">${steps.map(step=>`<li>${escapeHtml(step.replace(/^\s*(?:bước\s*)?\d+[.)\-:]\s*/i,''))}</li>`).join('')}</ol>`
    : `<div class="instruction-single"><p>${escapeHtml(steps[0])}</p><small>Database hiện chưa lưu hướng dẫn thành từng bước; nội dung được hiển thị nguyên văn.</small></div>`;
  detailRoot.innerHTML=`<p class="eyebrow">Công thức chi tiết</p><h1>${escapeHtml(data.title)}</h1><div class="meta-row"><span>⏱ ${escapeHtml(data.minutes)} phút</span><span>🧺 ${escapeHtml(data.ingredients.length)} nguyên liệu</span></div><h2>Nguyên liệu</h2><ul class="ingredient-list">${data.ingredients.map(item=>`<li><span>${escapeHtml(item.name)}</span><span>${escapeHtml(item.quantity||'')}</span></li>`).join('')}</ul><h2>Các bước chế biến</h2>${stepsHtml}<p class="source">Nguồn: ${escapeHtml(data.source_url||'Tự biên soạn cho đồ án')}</p>`;
}
async function loadRecipe(){
  try{const response=await fetch(`/api/recipes/${detailRoot.dataset.recipeId}`);const envelope=await response.json();if(!response.ok)throw Error(envelope.error?.message||'Không tải được công thức');renderRecipe(envelope.data)}
  catch(error){detailRoot.innerHTML=`<div class="message error">${escapeHtml(error.message)}</div>`}
}
loadRecipe();
