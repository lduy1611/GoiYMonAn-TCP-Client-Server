(() => {
  const app = document.querySelector('#admin-app');
  if (!app) return;
  const $ = selector => document.querySelector(selector);
  const state = { csrf: '', offset: 0, total: 0, loaded: false, busy: false };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const categories = { bug: 'Báo lỗi', feature: 'Đề xuất tính năng', other: 'Góp ý khác' };
  const statuses = { open: 'Chưa xử lý', resolved: 'Đã xử lý' };
  function date(value) { try { return new Intl.DateTimeFormat('vi-VN', {dateStyle:'medium', timeStyle:'short'}).format(new Date(value)); } catch { return '—'; } }
  async function api(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options,
      headers:{...(options.headers||{}), ...(state.csrf ? {'X-CSRF-Token':state.csrf} : {})}});
    const envelope = await response.json();
    if (!response.ok || envelope.ok !== true) throw new Error(envelope.error?.message || 'Không hoàn tất thao tác.');
    return envelope.data;
  }
  async function load() {
    if (state.busy) return;
    state.busy = true;
    const status = $('#admin-feedback-status');
    status.textContent = 'Đang tải góp ý…'; status.classList.remove('error');
    try {
      const filter = $('#admin-feedback-status-filter').value;
      const data = await api('/api/admin/feedback?status=' + encodeURIComponent(filter) + '&limit=20&offset=' + state.offset);
      state.total = data.total;
      const rows = data.items || [], tbody = $('#admin-feedback-list'); tbody.replaceChildren();
      $('#admin-feedback-empty').classList.toggle('hidden', rows.length > 0);
      for (const row of rows) {
        const tr = document.createElement('tr');
        const image = row.image ? '<br><img class="admin-feedback-thumb" src="' + esc(row.image.image_url) + '" alt="Ảnh đính kèm" loading="lazy">' : '';
        tr.innerHTML = '<td><span class="admin-feedback-kind">' + esc(categories[row.category] || row.category) + '</span><p class="admin-feedback-excerpt">' + esc(row.content.slice(0,180)) + '</p>' + image + '</td>' +
          '<td>' + esc(row.username) + '</td><td>' + esc(date(row.created_at)) + '</td><td><span class="admin-feedback-state is-' + esc(row.status) + '">' + esc(statuses[row.status]) + '</span></td>' +
          '<td class="admin-table-actions"><button class="button-secondary" type="button" data-feedback-view="' + esc(row.feedback_id) + '">Xem</button> <button class="button-secondary" type="button" data-feedback-toggle="' + esc(row.feedback_id) + '" data-next-status="' + (row.status === 'open' ? 'resolved' : 'open') + '">' + (row.status === 'open' ? 'Đánh dấu đã xử lý' : 'Đánh dấu chưa xử lý') + '</button> <button class="button-danger" type="button" data-feedback-delete="' + esc(row.feedback_id) + '">Xóa</button></td>';
        tbody.append(tr);
      }
      const from = state.total ? state.offset + 1 : 0, to = Math.min(state.offset + rows.length, state.total);
      $('#admin-feedback-page-status').textContent = from + '–' + to + ' / ' + state.total;
      $('#admin-feedback-prev').disabled = state.offset === 0;
      $('#admin-feedback-next').disabled = state.offset + rows.length >= state.total;
      status.textContent = 'Đã tải ' + state.total.toLocaleString('vi-VN') + ' góp ý.';
      state.loaded = true;
    } catch (error) { status.textContent = error.message; status.classList.add('error'); }
    finally { state.busy = false; }
  }
  async function detail(id) {
    try {
      const data = await api('/api/admin/feedback/' + encodeURIComponent(id));
      const image = data.image ? '<img class="admin-feedback-full-image" src="/api/admin/feedback/media/' + encodeURIComponent(data.image.storage_key) + '" alt="Ảnh đính kèm">' : '<p>Không có ảnh đính kèm.</p>';
      $('#admin-feedback-dialog-title').textContent = categories[data.category] || 'Góp ý';
      $('#admin-feedback-dialog-content').innerHTML = '<p><b>Người gửi:</b> ' + esc(data.username) + '</p><p><b>Thời gian:</b> ' + esc(date(data.created_at)) + '</p><p><b>Trạng thái:</b> ' + esc(statuses[data.status]) + '</p><div class="admin-feedback-full-content">' + esc(data.content) + '</div>' + image;
      $('#admin-feedback-dialog').showModal();
    } catch (error) { window.alert(error.message); }
  }
  async function updateStatus(id, status) {
    try { await api('/api/admin/feedback/' + encodeURIComponent(id) + '/status', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status})}); await load(); }
    catch (error) { $('#admin-feedback-status').textContent = error.message; $('#admin-feedback-status').classList.add('error'); }
  }
  async function remove(id) {
    if (!window.confirm('Xóa vĩnh viễn góp ý #' + id + '? Ảnh đính kèm cũng sẽ được gỡ.')) return;
    try { const result = await api('/api/admin/feedback/' + encodeURIComponent(id), {method:'DELETE'}); await load(); if (result.image_cleanup_pending) $('#admin-feedback-status').textContent = 'Góp ý đã xóa; chưa dọn được một tệp ảnh.'; }
    catch (error) { $('#admin-feedback-status').textContent = error.message; $('#admin-feedback-status').classList.add('error'); }
  }
  $('#admin-feedback-list').addEventListener('click', event => {
    const view = event.target.closest('[data-feedback-view]'), toggle = event.target.closest('[data-feedback-toggle]'), removeButton = event.target.closest('[data-feedback-delete]');
    if (view) void detail(view.dataset.feedbackView);
    else if (toggle) void updateStatus(toggle.dataset.feedbackToggle, toggle.dataset.nextStatus);
    else if (removeButton) void remove(removeButton.dataset.feedbackDelete);
  });
  $('#admin-feedback-status-filter').addEventListener('change', () => { state.offset = 0; void load(); });
  $('#admin-feedback-prev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - 20); void load(); });
  $('#admin-feedback-next').addEventListener('click', () => { state.offset += 20; void load(); });
  $('#admin-feedback-dialog-close').addEventListener('click', () => $('#admin-feedback-dialog').close());
  $('#admin-feedback-dialog').addEventListener('click', event => { if (event.target === $('#admin-feedback-dialog')) $('#admin-feedback-dialog').close(); });
  document.querySelectorAll('[data-admin-view="feedback"]').forEach(button => button.addEventListener('click', async () => {
    try { state.csrf = (await api('/api/admin/session')).csrf_token; }
    catch { $('#admin-feedback-status').textContent = 'Phiên Admin không còn hợp lệ.'; return; }
    if (!state.loaded) void load();
  }));
})();
