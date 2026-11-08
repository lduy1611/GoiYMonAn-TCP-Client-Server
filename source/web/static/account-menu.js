(() => {
  const slot=document.querySelector('#account-entry');if(!slot)return;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  (async()=>{
    try{
      const response=await fetch('/api/auth/session',{credentials:'same-origin'}),envelope=await response.json();
      if(!response.ok||envelope.ok!==true||envelope.data?.authenticated!==true){
        slot.innerHTML='<a class="account-nav-link" href="/account/login">Đăng nhập</a><a class="account-nav-register" href="/account/register">Tạo tài khoản</a>';return;
      }
      const user=envelope.data;
      slot.innerHTML='<span class="account-nav-name">'+esc(user.username)+'</span><button type="button" class="account-nav-link" id="account-logout">Đăng xuất</button>';
      document.querySelector('#account-logout').addEventListener('click',async()=>{
        const button=document.querySelector('#account-logout');button.disabled=true;
        try{await fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':user.csrf_token||''},credentials:'same-origin'});}finally{location.reload();}
      });
    }catch{slot.innerHTML='<a class="account-nav-link" href="/account/login">Đăng nhập</a>';}
  })();
})();
