const detailRoot = document.getElementById('detail');
const validRecipeID = value => Number.isSafeInteger(value) && (value >= 1 && value <= 4294967295 || value > 4294967296 && value <= 8589934591);
const returnTo = ['/', '/meal-plan', '/meal-plan/v1'].includes(detailRoot.dataset.returnTo) ? detailRoot.dataset.returnTo : '/';
const escapeHtml = value => {
  const node = document.createElement('div');
  node.textContent = String(value ?? '');
  return node.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

function databaseSteps(instructions) {
  return String(instructions ?? '').trim().split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

function sourceMarkup(sourceUrl) {
  if (!sourceUrl) return 'Chưa có liên kết nguồn trong dữ liệu.';
  try {
    const url = new URL(sourceUrl);
    if (['https:', 'http:'].includes(url.protocol)) {
      return 'Nguồn công thức: <a href="' + escapeHtml(url.href) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(sourceUrl) + '</a>';
    }
  } catch { /* Keep non-URL source text readable without creating an unsafe link. */ }
  return 'Nguồn công thức: ' + escapeHtml(sourceUrl);
}

function renderRecipe(data) {
  const steps = databaseSteps(data.instructions);
  const stepsHtml = steps.length > 1
    ? '<ol class="step-list">' + steps.map(step => '<li>' + escapeHtml(step.replace(/^\s*(?:bước\s*)?\d+[.)\-:]\s*/i, '')) + '</li>').join('') + '</ol>'
    : '<div class="instruction-single"><p>' + (escapeHtml(steps[0]) || 'Chưa có hướng dẫn trong dữ liệu.') + '</p></div>';
  document.title = data.title + ' · Hôm nay ăn gì?';
  detailRoot.innerHTML = '<header class="detail-heading"><p class="eyebrow">Từ lựa chọn đến bữa ăn</p><h1>' + escapeHtml(data.title) + '</h1><div class="meta-row"><span>◷ ' + escapeHtml(data.minutes) + ' phút</span><span>' + data.ingredients.length + ' nguyên liệu</span></div><figure class="recipe-media detail-media" data-recipe-media data-recipe-id="' + data.id + '" data-recipe-title="' + escapeHtml(data.title) + '"></figure></header>' +
    '<div class="detail-layout"><section class="recipe-ingredients panel" aria-labelledby="ingredients-title"><h2 id="ingredients-title">Chuẩn bị nguyên liệu</h2><p class="field-help">Tích để đánh dấu những gì bạn đã chuẩn bị.</p><ul class="ingredient-list">' +
    data.ingredients.map(item => '<li><label><input type="checkbox" aria-label="Đã chuẩn bị: ' + escapeHtml(item.name) + '"><span class="ingredient-copy"><span>' + escapeHtml(item.name) + '</span><span class="quantity">' + escapeHtml(item.quantity || '') + '</span></span></label></li>').join('') +
    '</ul></section><section class="recipe-instructions" aria-labelledby="instructions-title"><h2 id="instructions-title">Các bước chế biến</h2><p class="field-help">Hướng dẫn từ công thức được lưu trong hệ thống.</p>' + stepsHtml + '</section></div>' +
    '<p class="source">' + sourceMarkup(data.source_url) + '</p>';
  window.RecipeImages?.mount(detailRoot);
  mountAchievementForm(data.id);
}

function mountAchievementForm(recipeId) {
  const section=document.createElement('section');section.id='achievement-form';section.className='achievement-submit-section panel';
  section.innerHTML='<div class="achievement-submit-heading"><p class="eyebrow">CHIA SẺ CÙNG CỘNG ĐỒNG</p><h2>Thành quả</h2><p>Chia sẻ món bạn đã nấu theo công thức này.</p></div><form id="achievement-submit-form"><label for="achievement-photos">Ảnh thành quả <span>(chọn 1–3 ảnh)</span></label><input id="achievement-photos" name="photos" type="file" accept="image/jpeg,image/png,image/webp" multiple required><div id="achievement-photo-preview" class="achievement-photo-preview"></div><label for="achievement-description">Mô tả</label><textarea id="achievement-description" name="description" maxlength="3000" rows="4" required placeholder="Chia sẻ đôi điều về món bạn vừa nấu…"></textarea><label for="achievement-changed">Bạn đã thay đổi nguyên liệu gì? <span>(không bắt buộc)</span></label><input id="achievement-changed" name="changed_ingredients" maxlength="1000" placeholder="Ví dụ: thay thịt bò bằng thịt gà"><p id="achievement-submit-status" role="status" aria-live="polite"></p><button id="achievement-submit-button" type="submit">Đăng thành quả</button></form>';
  detailRoot.after(section);
  const form=section.querySelector('form'),photos=section.querySelector('#achievement-photos'),preview=section.querySelector('#achievement-photo-preview'),status=section.querySelector('#achievement-submit-status'),button=section.querySelector('button');
  let user=null,requestKey=crypto.randomUUID();
  fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'}).then(r=>r.json()).then(envelope=>{if(envelope.ok&&envelope.data?.authenticated)user=envelope.data;}).catch(()=>{});
  photos.addEventListener('change',()=>{preview.replaceChildren();const files=[...(photos.files||[])];if(files.length>3){photos.value='';status.textContent='Chọn tối đa 3 ảnh.';status.className='error';return;}for(const file of files){const image=document.createElement('img');image.alt='Ảnh xem trước';image.src=URL.createObjectURL(file);preview.append(image);}});
  const readBase64=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',',2)[1]||'');reader.onerror=()=>reject(new Error('Không đọc được ảnh đã chọn.'));reader.readAsDataURL(file);});
  form.addEventListener('submit',async event=>{event.preventDefault();const files=[...(photos.files||[])];if(!user){location.assign('/account/login?next='+encodeURIComponent(location.pathname+'#achievement-form'));return;}if(files.length<1||files.length>3){status.textContent='Chọn từ 1 đến 3 ảnh.';status.className='error';return;}if(files.some(file=>file.size>5*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type))){status.textContent='Mỗi ảnh cần là JPG, PNG hoặc WebP và không quá 5 MB.';status.className='error';return;}button.disabled=true;status.textContent='Đang đăng thành quả…';status.className='';
    try{const images=[];for(const file of files)images.push({media_type:file.type,data_base64:await readBase64(file)});const response=await fetch('/api/achievements',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':user.csrf_token},body:JSON.stringify({recipe_id:Number(recipeId),description:form.elements.description.value,changed_ingredients:form.elements.changed_ingredients.value,request_key:requestKey,images})});const envelope=await response.json();if(!response.ok||envelope.ok!==true){const err=new Error(envelope.error?.message||'Không đăng được thành quả.');err.code=envelope.error?.code;throw err;}const url=envelope.data?.url||('/achievements?post_id='+encodeURIComponent(envelope.data.post_id));status.textContent='Đăng thành quả thành công. ';const link=document.createElement('a');link.href=url;link.textContent='Xem bài vừa đăng';status.append(link);form.reset();preview.replaceChildren();requestKey=crypto.randomUUID();
    }catch(error){if(error.status===401||error.code==='USER_UNAUTHORIZED'){location.assign('/account/login?next='+encodeURIComponent(location.pathname+'#achievement-form'));return;}status.textContent=error.message||'Không đăng được thành quả.';status.className='error';}finally{button.disabled=false;}
  });
}

async function loadRecipe() {
  detailRoot.setAttribute('aria-busy', 'true');
  try {
    if (!validRecipeID(Number(detailRoot.dataset.recipeId))) throw Error('Đường dẫn công thức không hợp lệ. Hãy quay lại để chọn món.');
    const response = await fetch('/api/recipes/' + detailRoot.dataset.recipeId);
    const envelope = await response.json();
    if (!response.ok || !envelope.ok) throw Error(envelope.error?.message || 'Không tải được công thức.');
    renderRecipe(envelope.data);
  } catch (error) {
    const message = error instanceof TypeError ? 'Không thể kết nối máy chủ. Hãy kiểm tra kết nối và thử lại.' : error.message;
    detailRoot.innerHTML = '<div class="empty-state panel"><h1>Chưa thể mở công thức</h1><p class="message error" role="alert">' + escapeHtml(message) + '</p><button class="retry-button" id="retry-recipe" type="button">Thử lại</button><p><a class="detail-error-back" href="' + returnTo + '">' + (returnTo === '/meal-plan' ? 'Quay về mâm cơm' : 'Quay về trang gợi ý') + '</a></p></div>';
    document.getElementById('retry-recipe').onclick = loadRecipe;
  } finally {
    detailRoot.setAttribute('aria-busy', 'false');
  }
}
loadRecipe();
