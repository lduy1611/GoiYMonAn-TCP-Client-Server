(() => {
  const $ = selector => document.querySelector(selector);
  const dialog = $('#feedback-dialog'), form = $('#feedback-form');
  if (!dialog || !form) return;
  let csrf = '', toastTimer = 0;
  const status = $('#feedback-status'), submit = $('#feedback-submit');
  function showStatus(message, error = false) {
    status.textContent = message;
    status.classList.toggle('error', error);
  }
  function toast(message) {
    const node = $('#feedback-toast');
    node.textContent = message;
    node.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove('is-visible'), 3800);
  }
  async function sessionCsrf() {
    csrf = '';
    try {
      const response = await fetch('/api/auth/session', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) csrf = (await response.json()).data?.csrf_token || '';
    } catch { /* Guest feedback remains available while offline checks fail. */ }
  }
  function readFile(file) {
    if (!file) return Promise.resolve(null);
    if (file.size > 5 * 1024 * 1024) throw new Error('Ảnh đính kèm tối đa 5 MB.');
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Chỉ hỗ trợ ảnh JPG, PNG hoặc WebP.');
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Không đọc được ảnh đã chọn.'));
      reader.onload = () => resolve({ media_type: file.type, data_base64: String(reader.result).split(',', 2)[1] });
      reader.readAsDataURL(file);
    });
  }
  $('#feedback-open').addEventListener('click', async () => {
    showStatus('');
    await sessionCsrf();
    dialog.showModal();
    $('#feedback-category').focus();
  });
  $('#feedback-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  $('#feedback-image').addEventListener('change', () => {
    const file = $('#feedback-image').files[0];
    if (file && file.size > 5 * 1024 * 1024) {
      $('#feedback-image').value = '';
      showStatus('Ảnh đính kèm tối đa 5 MB.', true);
    } else showStatus('');
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const content = $('#feedback-content').value.trim();
    if (!content) { showStatus('Vui lòng nhập nội dung góp ý.', true); $('#feedback-content').focus(); return; }
    submit.disabled = true;
    try {
      const image = await readFile($('#feedback-image').files[0]);
      const headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = csrf;
      const response = await fetch('/api/feedback', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', headers,
        body: JSON.stringify({ category: $('#feedback-category').value, content,
          request_key: crypto.randomUUID(), image })
      });
      const envelope = await response.json();
      if (!response.ok || envelope.ok !== true) {
        const message = envelope.error?.message || 'Chưa gửi được góp ý. Vui lòng thử lại.';
        if (response.status === 401) throw new Error('Phiên User không hợp lệ. Hãy đăng nhập lại rồi gửi góp ý.');
        throw new Error(message);
      }
      form.reset();
      dialog.close();
      toast('Cảm ơn bạn! Góp ý đã được gửi.');
    } catch (error) {
      showStatus(error.message || 'Chưa gửi được góp ý. Vui lòng thử lại.', true);
    } finally {
      submit.disabled = false;
    }
  });
})();
