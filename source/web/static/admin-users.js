(() => {
  const $=selector=>document.querySelector(selector);
  const state={csrf:'',offset:0,total:0,busy:false};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const message=(text,error=false)=>{const node=$('#admin-users-readiness');node.textContent=text;node.classList.toggle('error',error);};
  async function api(url,options={}){
    const headers={...(options.headers||{})};if(state.csrf)headers['X-CSRF-Token']=state.csrf;
    const response=await fetch(url,{...options,headers,credentials:'same-origin',cache:'no-store'}),envelope=await response.json();
    if(response.status===401||response.status===403){location.assign('/admin/login');throw new Error('Phiên Admin đã hết hạn.');}
    if(!response.ok||envelope.ok!==true)throw new Error(envelope.error?.code==='USER_ACCOUNT_UNAVAILABLE'?'Cần migration 005 và writer riêng cho tài khoản.':envelope.error?.message||'Không thể tải tài khoản.');
    return envelope.data;
  }
  async function load(){
    if(state.busy)return;state.busy=true;message('Đang tải danh sách…');
    try{
      const session=await api('/api/admin/session');state.csrf=session.csrf_token;
      const query=$('#admin-users-query').value.trim();
      const data=await api('/api/admin/users?query='+encodeURIComponent(query)+'&limit=20&offset='+state.offset);
      state.total=data.total;const body=$('#admin-users');body.replaceChildren();
      $('#admin-users-empty').classList.toggle('hidden',data.items.length>0);
      for(const item of data.items){
        const tr=document.createElement('tr');
        const active=item.account_status==='ACTIVE';
        const action='<button type="button" class="button-secondary" data-user-id="'+esc(item.user_id)+'" data-status="'+(active?'LOCKED':'ACTIVE')+'">'+(active?'Khóa tài khoản':'Mở khóa')+'</button>';
        const roleOptions=['USER','ADMIN'].map(role=>'<option value="'+role+'" '+(role===item.role?'selected':'')+'>'+role+'</option>').join('');
        const roleControl='<div class="admin-role-control"><select aria-label="Vai trò '+esc(item.username)+'" data-role-select="'+esc(item.user_id)+'">'+roleOptions+'</select><button type="button" class="button-secondary" data-role-id="'+esc(item.user_id)+'">Lưu vai trò</button></div>';
        tr.innerHTML='<td><strong>'+esc(item.username)+'</strong><small class="admin-muted admin-ingredient-id">Mã '+esc(item.user_id)+'</small></td><td><span class="status-pill">'+esc(item.role)+'</span>'+roleControl+'</td><td><span class="status-pill '+(active?'':'status-inactive')+'">'+(active?'Đang hoạt động':'Đã khóa')+'</span></td><td>'+esc(item.created_at||'—')+'</td><td>'+esc(item.last_login_at||'Chưa đăng nhập')+'</td><td class="admin-user-actions">'+action+'</td>';
        body.append(tr);
      }
      const from=state.total?state.offset+1:0,to=Math.min(state.offset+data.items.length,state.total);
      $('#admin-users-page-status').textContent=from+'–'+to+' / '+state.total;
      $('#admin-users-prev').disabled=state.offset===0;$('#admin-users-next').disabled=state.offset+data.items.length>=state.total;
      message(data.account_admin_ready?'Quản lý tài khoản sẵn sàng · '+state.total+' tài khoản':'Quản lý tài khoản chưa sẵn sàng',!data.account_admin_ready);
    }catch(error){message(error.message||'Không tải được tài khoản.',true);}
    finally{state.busy=false;}
  }
  $('#admin-users-search').addEventListener('submit',event=>{event.preventDefault();state.offset=0;load();});
  $('#admin-users-prev').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-20);load();});
  $('#admin-users-next').addEventListener('click',()=>{state.offset+=20;load();});
  $('#admin-users').addEventListener('click',async event=>{
    const roleButton=event.target.closest('[data-role-id]');
    if(roleButton){
      const id=roleButton.dataset.roleId,role=$('[data-role-select="'+CSS.escape(id)+'"]').value;
      if(!confirm('Đổi vai trò tài khoản này thành '+role+'? Tài khoản ADMIN có thể mở khu vực quản trị sau khi đăng nhập lại.'))return;
      roleButton.disabled=true;
      try{await api('/api/admin/users/'+encodeURIComponent(id)+'/role',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({role})});await load();}
      catch(error){message(error.message||'Không cập nhật được vai trò.',true);roleButton.disabled=false;}
      return;
    }
    const button=event.target.closest('[data-user-id]');if(!button)return;
    const status=button.dataset.status,verb=status==='LOCKED'?'khóa':'mở khóa';
    if(!confirm('Bạn có chắc muốn '+verb+' tài khoản '+button.closest('tr').querySelector('strong').textContent+'?'))return;
    button.disabled=true;
    try{await api('/api/admin/users/'+encodeURIComponent(button.dataset.userId)+'/status',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_status:status})});await load();}
    catch(error){message(error.message||'Không cập nhật được trạng thái.',true);button.disabled=false;}
  });
  load();
})();
