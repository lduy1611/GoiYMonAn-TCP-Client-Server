const detailRoot = document.getElementById('detail');
const returnTo = ['/', '/meal-plan'].includes(detailRoot.dataset.returnTo) ? detailRoot.dataset.returnTo : '/';
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
}

async function loadRecipe() {
  detailRoot.setAttribute('aria-busy', 'true');
  try {
    if (!Number.isSafeInteger(Number(detailRoot.dataset.recipeId)) || Number(detailRoot.dataset.recipeId) <= 0) throw Error('Đường dẫn công thức không hợp lệ. Hãy quay lại để chọn món.');
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
