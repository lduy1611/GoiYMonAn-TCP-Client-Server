(() => {
  const app=document.querySelector('#admin-app');
  if(!app)return;
  const $=(selector)=>document.querySelector(selector);
  const copy={
    overview:{title:'Tổng quan',eyebrow:'TỔNG QUAN',description:'Theo dõi danh mục món ăn, nguyên liệu và tài khoản từ dữ liệu MySQL.'},
    recipes:{title:'Quản lý món ăn',eyebrow:'NỘI DUNG',description:'Tìm, xem, chỉnh sửa và quản lý món đang hiển thị.'},
    ingredients:{title:'Nguyên liệu',eyebrow:'DANH MỤC BẾP',description:'Quản lý thành phần đang được sử dụng trong công thức.'},
    users:{title:'Người dùng',eyebrow:'TÀI KHOẢN',description:'Tìm kiếm tài khoản, kiểm tra trạng thái và vai trò.'}
    ,achievements:{title:'Quản lý thành quả',eyebrow:'BÀI ĐĂNG',description:'Xem bài đăng, ảnh và bình luận của người dùng.'}
  };
  const mobile=window.matchMedia('(max-width: 900px)');
  function navigate(view,{save=true}={}){
    if(!copy[view])view='overview';
    document.querySelectorAll('[data-admin-view-panel]').forEach(panel=>{
      const active=panel.dataset.adminViewPanel===view;
      panel.classList.toggle('hidden',!active);
      panel.setAttribute('aria-hidden',String(!active));
    });
    document.querySelectorAll('[data-admin-view]').forEach(button=>{
      const active=button.dataset.adminView===view;
      button.classList.toggle('is-active',active);
      if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
    $('#admin-breadcrumb').textContent=copy[view].title;
    $('#admin-page-title').textContent=copy[view].title;
    $('#admin-page-eyebrow').textContent=copy[view].eyebrow;
    $('#admin-page-description').textContent=copy[view].description;
    if(save){
      try{sessionStorage.setItem('goiy-admin-view',view);}catch{}
      history.replaceState(null,'','#'+view);
    }
    app.classList.remove('drawer-open');
    $('#admin-sidebar-toggle').setAttribute('aria-expanded','false');
    $('.admin-main').scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  }
  document.querySelectorAll('[data-admin-view]').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.adminView)));
  document.querySelectorAll('[data-admin-goto]').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.adminGoto)));
  document.querySelectorAll('[data-admin-open-create]').forEach(button=>button.addEventListener('click',()=>{
    navigate('recipes');
    const create=$('#admin-create');
    if(create.disabled){$('#admin-status').textContent='Chức năng ghi món chưa sẵn sàng trên tài khoản hiện tại.';$('#admin-status').classList.add('error');return;}
    create.click();
  }));
  document.querySelectorAll('[data-admin-open-ingredient]').forEach(button=>button.addEventListener('click',()=>{
    navigate('ingredients');
    const create=$('#admin-ingredient-create');
    if(create.disabled){$('#admin-ingredient-readiness').textContent='Chức năng ghi nguyên liệu chưa sẵn sàng trên tài khoản hiện tại.';$('#admin-ingredient-readiness').classList.add('error');return;}
    create.click();
  }));
  $('#admin-sidebar-toggle').addEventListener('click',()=>{
    if(mobile.matches){
      const open=!app.classList.contains('drawer-open');
      app.classList.toggle('drawer-open',open);
      $('#admin-sidebar-toggle').setAttribute('aria-expanded',String(open));
    }else{
      app.classList.toggle('sidebar-collapsed');
      try{localStorage.setItem('goiy-admin-sidebar-collapsed',String(app.classList.contains('sidebar-collapsed')));}catch{}
    }
  });
  const closeDrawer=()=>{app.classList.remove('drawer-open');$('#admin-sidebar-toggle').setAttribute('aria-expanded','false');};
  $('#admin-sidebar-close').addEventListener('click',closeDrawer);
  $('#admin-sidebar-scrim').addEventListener('click',closeDrawer);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeDrawer();});
  mobile.addEventListener('change',()=>closeDrawer());
  let collapsed=false;try{collapsed=localStorage.getItem('goiy-admin-sidebar-collapsed')==='true';}catch{}
  if(collapsed&&!mobile.matches)app.classList.add('sidebar-collapsed');
  let initial=location.hash.slice(1);
  if(!copy[initial]){try{initial=sessionStorage.getItem('goiy-admin-view')||'overview';}catch{initial='overview';}}
  navigate(initial,{save:false});
})();
