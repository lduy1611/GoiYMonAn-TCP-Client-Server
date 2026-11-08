(() => {
  const form=document.querySelector('#admin-login-form'),button=document.querySelector('#admin-login-submit'),message=document.querySelector('#admin-login-message');
  form.addEventListener('submit',async event=>{
    event.preventDefault();button.disabled=true;message.classList.remove('error');message.textContent='Đang xác thực…';
    try{
      const values=new FormData(form),response=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:values.get('username'),password:values.get('password')})});
      const envelope=await response.json();
      if(!response.ok||envelope.ok!==true)throw new Error(envelope.error?.code==='ADMIN_NOT_CONFIGURED'?'Máy chủ chưa được cấu hình thông tin Admin.':envelope.error?.message||'Không đăng nhập được.');
      const requested=new URLSearchParams(location.search).get('return_to')||'/admin';
      let destination='/admin';
      try{const parsed=new URL(requested,location.origin);if(parsed.origin===location.origin&&parsed.pathname==='/admin')destination=parsed.pathname+parsed.search+parsed.hash;}catch{}
      location.assign(destination);
    }catch(error){message.textContent=error instanceof TypeError?'Không kết nối được máy chủ. Thử lại sau.':error.message;message.classList.add('error');button.disabled=false;}
  });
})();
