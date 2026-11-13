(() => {
  const card=document.querySelector('.account-profile-shell .account-card');
  const message=document.querySelector('#profile-message');
  const button=document.querySelector('#profile-logout');
  let csrf='';
  const roleLabel=role=>role==='ADMIN'?'Quản trị viên':role==='USER'?'Người dùng':null;
  (async()=>{
    try{
      const response=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});
      const envelope=await response.json();
      if(response.status===401||envelope.data?.authenticated!==true){location.replace('/account/login');return;}
      if(!response.ok||envelope.ok!==true||typeof envelope.data?.username!=='string'||!roleLabel(envelope.data?.role))throw new Error('Không thể tải thông tin tài khoản. Hãy thử tải lại trang.');
      document.querySelector('#profile-username').textContent=envelope.data.username;
      document.querySelector('#profile-role').textContent=roleLabel(envelope.data.role);
      document.querySelector('#profile-status').textContent='Đang đăng nhập';
      csrf=typeof envelope.data.csrf_token==='string'?envelope.data.csrf_token:'';
      button.disabled=false;
    }catch(error){message.textContent=error instanceof TypeError?'Không thể kết nối tới máy chủ. Hãy thử lại.':error.message;message.classList.add('error');}
    finally{card?.setAttribute('aria-busy','false');}
  })();
  button?.addEventListener('click',async()=>{
    button.disabled=true;message.classList.remove('error');message.textContent='Đang đăng xuất…';
    try{
      const response=await fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':csrf},credentials:'same-origin'});
      const envelope=await response.json();
      if(!response.ok||envelope.ok!==true)throw new Error(envelope.error?.message||'Không thể đăng xuất. Hãy thử lại.');
      location.assign('/account/login');
    }catch(error){message.textContent=error instanceof TypeError?'Không thể kết nối tới máy chủ. Hãy thử lại.':error.message;message.classList.add('error');button.disabled=false;}
  });
})();
