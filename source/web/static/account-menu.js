(() => {
  const link=document.querySelector('#user-account-tab');if(!link)return;
  (async()=>{
    try{
      const response=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});
      const envelope=await response.json();
      link.href=response.ok&&envelope.ok===true&&envelope.data?.authenticated===true?'/account/profile':'/account/login';
    }catch{link.href='/account/login';}
  })();
})();
