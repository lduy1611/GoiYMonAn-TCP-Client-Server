(() => {
  const form=document.querySelector('#account-form');
  const button=document.querySelector('#account-submit');
  const message=document.querySelector('#account-message');
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!form.reportValidity())return;
    const values=new FormData(form),mode=form.dataset.mode;
    if(mode==='register'&&values.get('password')!==values.get('password_confirmation')){
      message.textContent='Hai mật khẩu chưa khớp.';message.classList.add('error');return;
    }
    button.disabled=true;message.classList.remove('error');message.textContent=mode==='login'?'Đang đăng nhập…':'Đang tạo tài khoản…';
    try{
      const response=await fetch(mode==='login'?'/api/auth/login':'/api/auth/register',{
        method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
        body:JSON.stringify(mode==='login'?{username:values.get('username'),password:values.get('password')}:
          {username:values.get('username'),password:values.get('password'),password_confirmation:values.get('password_confirmation')})
      });
      const envelope=await response.json();
      if(!response.ok||envelope.ok!==true){
        const code=envelope.error?.code;
        const text=code==='USER_ACCOUNT_CONFLICT'?'Tên đăng nhập đã được sử dụng.':
          code==='USER_ACCOUNT_UNAVAILABLE'?'Đăng ký/đăng nhập đang tạm thời chưa sẵn sàng.':
          code==='USER_LOCKED'?'Tài khoản đang bị khóa. Hãy liên hệ quản trị viên.':
          code==='USER_UNAUTHORIZED'?'Tên đăng nhập hoặc mật khẩu không đúng.':
          envelope.error?.message||'Không thể hoàn tất yêu cầu.';
        throw new Error(text);
      }
      location.assign('/');
    }catch(error){message.textContent=error instanceof TypeError?'Không kết nối được máy chủ. Hãy thử lại.':error.message;message.classList.add('error');button.disabled=false;}
  });
})();
