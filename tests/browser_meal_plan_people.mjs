// Real browser + isolated HTTP/TCP/SQLite fixture. Synthetic quantities below are TEST_ONLY,
// never loaded into MySQL, dossier files, an approval, or a release.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const [browser,base,profile,widthArg]=process.argv.slice(2), width=Number(widthArg);
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const child=spawn(browser,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--disable-features=BackForwardCache','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
  '--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
let socket,session,serial=0,evaluate;
const pending=new Map(),errors=[],generationPosts=[],calculationPosts=[];
const send=(method,params={},sessionId=session)=>new Promise((resolve,reject)=>{
  const id=++serial,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},15000);
  pending.set(id,{resolve,reject,timer});
  socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
});
try {
  child.on('error',e=>errors.push(e.message));
  let port;
  for(let i=0;i<150;i++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{await pause(100);}}
  assert.ok(port,'Browser started');
  const version=await(await fetch('http://127.0.0.1:'+port+'/json/version')).json();
  socket=new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  socket.onmessage=event=>{
    const m=JSON.parse(event.data);
    if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
    if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);
    if(m.method==='Network.requestWillBeSent'&&m.params.request.method==='POST'){
      const path=new URL(m.params.request.url).pathname;
      if(path==='/api/meal-plan/v2')generationPosts.push(JSON.parse(m.params.request.postData));
      if(path==='/api/meal-plan/calculate')calculationPosts.push(JSON.parse(m.params.request.postData));
    }
  };
  const target=await send('Target.createTarget',{url:'about:blank'},null);
  session=(await send('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  for(const domain of ['Runtime','Page','Network'])await send(domain+'.enable');
  await send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:width<760});
  evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;
  };
  const wait=async expression=>{for(let i=0;i<120;i++){if(await evaluate(expression))return;await pause(75);}throw Error('UI timeout: '+expression);};
  const navigate=async path=>{
    const before=await evaluate('performance.timeOrigin');await send('Page.navigate',{url:base+path});
    await wait('performance.timeOrigin!=='+before+'&&document.readyState==="complete"&&location.pathname==='+JSON.stringify(new URL(path,base).pathname));
  };
  const ready=()=>wait('document.getElementById("meal-ingredients")?.getAttribute("aria-busy")==="false"&&!document.getElementById("meal-generate").disabled');
  const click=selector=>evaluate('document.querySelector('+JSON.stringify(selector)+').click()');
  const text=id=>evaluate('document.getElementById('+JSON.stringify(id)+').textContent');
  const done=()=>wait('document.getElementById("meal-portions").getAttribute("aria-busy")==="false"');
  const snapshot=()=>evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v2"))');
  const preserved=async baseline=>{
    const now=await snapshot();
    for(const name of ['view','pins','conditions','history'])assert.deepEqual(now[name],baseline[name],name+' preserved');
    assert.equal(generationPosts.length,1,'Changing people never regenerates meal');
    assert.ok(await evaluate('window.card===document.querySelector("[data-meal-slot]")'),'Card DOM preserved');
  };
  await navigate('/meal-plan');await ready();
  assert.equal(await text('meal-people'),'4 ng\u01b0\u1eddi');
  await click('#meal-people-minus');await pause(400);
  assert.equal(calculationPosts.length,0,'No empty recipe_ids request');
  await click('#meal-people-plus');
  await click('#meal-generate');
  await wait('document.querySelectorAll("[data-meal-slot]").length===3&&document.getElementById("meal-results").getAttribute("aria-busy")==="false"');await done();
  assert.ok((await text('meal-portions-message')).startsWith('Ch\u01b0a th\u1ec3 t\u00ednh kh\u1ea9u ph\u1ea7n'));
  assert.equal(await evaluate('document.getElementById("meal-portions-known").children.length'),0);
  assert.ok((await text('meal-portions-reasons')).length>0);
  assert.equal(await evaluate('document.getElementById("meal-shopping").classList.contains("hidden")'),false);
  assert.ok((await text('meal-shopping-required')).length>0,'Ingredient list remains visible');
  await click('[data-pin]');
  const baseline=await snapshot(),expectedIds=baseline.view.data.plan.items.map(i=>i.recipe_id);

  // Transport mocks are local browser fixtures only; the first assertions used real HTTP/TCP.
  await evaluate(`(()=>{
    window.originalFetch=window.fetch;window.calls=[];window.calcImpl=(url,opts)=>originalFetch(url,opts);
    window.fetch=(url,opts)=>{
      if(url!=='/api/meal-plan/calculate')return originalFetch(url,opts);
      const call={payload:JSON.parse(opts.body),signal:opts.signal};calls.push(call);
      return calcImpl(url,opts,call);
    };
    window.fixtureEnvelope=(p,partial=false)=>{
      const q={amount_kind:'exact',quantity_value:'250',quantity_min:'250',quantity_max:'250',precision:'exact'};
      const range={amount_kind:'range',quantity_value:null,quantity_min:'0.5',quantity_max:'1',precision:'outward_6dp'};
      const recipes=p.recipe_ids.map((id,i)=>({recipe_id:id,revision_id:100+i,status:partial&&i?'INCOMPLETE':'COMPLETE',
        base_servings:'4',target_servings:String(p.people),lines:partial&&i?[]:[{line_id:1,ingredient_id:90001,unit:'g',requirement:'required',...q}],
        reasons:partial&&i?[{code:'TEST_ONLY_MISSING',message:'TEST_ONLY: ChÆ°a xÃ¡c minh Ä‘á»‹nh lÆ°á»£ng.',line_id:1}]:[]}));
      // Distinct units/forms must remain distinct, including an opaque source unit.
      if(!partial)recipes[1].lines=[{line_id:1,ingredient_id:90001,unit:'ml',...range}];
      if(!partial)recipes[2].lines=[{line_id:1,ingredient_id:90001,unit:'source_TEST_ONLY_spoon',...q}];
      const ingredients=recipes.flatMap(r=>r.lines.map(l=>({...l,name:'TEST_ONLY <img src=x onerror=alert(1)>',ingredient_form:'TEST_ONLY_form',
        measurement_basis:'edible',purpose:'main',mergeable:true,uses:[{recipe_id:r.recipe_id,revision_id:r.revision_id,line_id:1,requirement:'required',
          ...Object.fromEntries(Object.keys(q).map(k=>[k,l[k]]))}]})));
      ingredients.forEach(i=>delete i.line_id);
      return {version:1,request_id:'TEST_ONLY_browser_fixture',ok:true,error:null,data:{
        dataset_version:JSON.parse(sessionStorage.getItem('goiy-meal-plan-v2')).view.data.dataset_version,
        calculation_version:'portion-v1',recipe_ids:p.recipe_ids,people:p.people,status:partial?'INCOMPLETE':'COMPLETE',
        totals_complete:!partial,portion_policy_version:'TEST_ONLY',recipes,known_ingredients:ingredients}};
    };
    window.reply=e=>new Response(JSON.stringify(e),{status:200,headers:{'Content-Type':'application/json'}});
    calcImpl=async(url,opts,c)=>reply(fixtureEnvelope(c.payload));
  })()`);
  await click('#meal-people-minus');await done();
  assert.equal(await text('meal-portions-message'),'\u0110\u00e3 t\u00ednh \u0111\u1ea7y \u0111\u1ee7 kh\u1ea9u ph\u1ea7n cho 3 ng\u01b0\u1eddi.');
  const knownAfter=await text('meal-portions-known');
  assert.ok(knownAfter.includes('C\u00f3 3 d\u00f2ng l\u01b0\u1ee3ng \u0111\u00e3 t\u00ednh'));
  assert.equal(await evaluate('document.getElementById("meal-portions-known").querySelectorAll("img").length'),0,'Escape names');
  const shopping=await text('meal-shopping-required')+await text('meal-shopping-optional');
  for(const value of ['250 g','0.5\u20131 ml','source_TEST_ONLY_spoon'])assert.ok(shopping.includes(value),value);
  await evaluate('calcImpl=async(url,opts,c)=>reply(fixtureEnvelope(c.payload,true))');
  await click('#meal-people-plus');await done();
  assert.ok((await text('meal-portions-known')).includes('d\u00f2ng l\u01b0\u1ee3ng \u0111\u00e3 t\u00ednh'));
  assert.ok((await text('meal-portions-reasons')).includes('TEST_ONLY: Ch\u01b0a x\u00e1c minh \u0111\u1ecbnh l\u01b0\u1ee3ng.'));
  assert.ok((await text('meal-shopping-required')+await text('meal-shopping-optional')).includes('Gi\u1eef nguy\u00ean theo c\u00f4ng th\u1ee9c'));
  await preserved(baseline);

  for(const failure of ['network','timeout','malformed','wrong_people','wrong_recipes']){
    await evaluate(`calcImpl=async(url,opts,c)=>{
      const mode=${JSON.stringify(failure)};
      if(mode==='network')throw TypeError('TEST_ONLY disconnected');
      if(mode==='timeout')return new Response(JSON.stringify({ok:false,error:{code:'TIMEOUT'}}),{status:504});
      const e=fixtureEnvelope(c.payload);
      if(mode==='malformed')e.data.known_ingredients[0].quantity_min='bad';
      if(mode==='wrong_people')e.data.people=1;
      if(mode==='wrong_recipes')e.data.recipe_ids=[999];
      return reply(e);
    }`);
    await click('#meal-portions-retry');await done();
    assert.equal(await evaluate('document.getElementById("meal-portions-retry").classList.contains("hidden")'),false,failure);
    assert.equal(await text('meal-portions-known'),'','No quantities after '+failure);
    await preserved(baseline);
  }
  // A stalled fetch ignoring AbortController must time out and remain stale forever.
  await evaluate(`window.realTimeout=window.setTimeout;window.setTimeout=(fn,ms,...args)=>realTimeout(fn,ms===10000?50:ms,...args);
    calcImpl=(url,opts,c)=>new Promise(resolve=>{c.resolve=()=>resolve(reply(fixtureEnvelope(c.payload)));});`);
  await click('#meal-portions-retry');await done();
  assert.ok((await text('meal-portions-message')).includes('quÃ¡ lÃ¢u'));
  assert.equal(await evaluate('calls.at(-1).signal.aborted'),true);
  await evaluate('calls.at(-1).resolve();window.setTimeout=window.realTimeout');await pause(100);
  assert.ok((await text('meal-portions-message')).includes('quÃ¡ lÃ¢u'),'Late timeout result discarded');

  // Older success and older failure arrive after a newer result, ignoring abort.
  await evaluate('window.held=[];calcImpl=(url,opts,c)=>new Promise((resolve,reject)=>held.push({...c,resolve,reject}))');
  await click('#meal-people-minus');await wait('held.length===1');
  await click('#meal-people-plus');await wait('held.length===2');
  assert.equal(await evaluate('held[0].signal.aborted'),true);
  await evaluate('held[1].resolve(reply(fixtureEnvelope(held[1].payload)))');await done();
  const newest=await text('meal-portions-message');
  await evaluate('held[0].resolve(reply(fixtureEnvelope(held[0].payload)))');await pause(100);
  assert.equal(await text('meal-portions-message'),newest);
  await click('#meal-people-minus');await wait('held.length===3');
  await click('#meal-people-plus');await wait('held.length===4');
  await evaluate('held[3].resolve(reply(fixtureEnvelope(held[3].payload)))');await done();
  const latest=await text('meal-portions-message');
  await evaluate('held[2].reject(Error("TEST_ONLY late failure"))');await pause(100);
  assert.equal(await text('meal-portions-message'),latest);
  await preserved(baseline);
  // TEST_ONLY display fixtures exercise known amounts, vague seasoning and missing base servings.
  await evaluate(`window.calcImpl=async(url,opts,c)=>reply(fixtureEnvelope(c.payload));`);
  await click('[data-meal-type="custom"]');
  await wait('document.getElementById("meal-results").getAttribute("aria-busy")==="false"');await done();
  await evaluate(`(()=>{
    const plan=JSON.parse(sessionStorage.getItem('goiy-meal-plan-v2')).view.data;
    const ids=plan.plan.items.map(x=>x.recipe_id), ds=plan.dataset_version;
    window.detailFixtures={};
    window.detailFixtures[ids[1]]={id:ids[1],title:plan.plan.items[1].title,dataset_version:ds,ingredients:[
      {line_no:1,id:90101,name:'TEST_ONLY meat',quantity:'400 g',requirement:'required',is_required:true},
      {line_no:2,id:90102,name:'TEST_ONLY salt',quantity:'n\u00eam v\u1eeba \u0103n',requirement:'required',is_required:true}]};
    window.detailFixtures[ids[2]]={id:ids[2],title:plan.plan.items[2].title,dataset_version:ds,ingredients:[
      {line_no:1,id:90103,name:'TEST_ONLY tofu',quantity:'200 g',requirement:'required',is_required:true},
      {line_no:2,id:90104,name:'TEST_ONLY pepper',quantity:'m\u1ed9t \u00edt',requirement:'optional',is_required:false}]};
    const exact=n=>({amount_kind:'exact',quantity_value:String(n),quantity_min:String(n),quantity_max:String(n),precision:'exact'});
    const known=(rid,lineId,iid,name,n)=>({ingredient_id:iid,name,ingredient_form:null,measurement_basis:'unknown',purpose:'main',unit:'g',requirement:'required',mergeable:false,...exact(n),uses:[{recipe_id:rid,revision_id:rid,line_id:lineId,requirement:'required',...exact(n)}]});
    window.portionFixture=p=>{
      const recipes=ids.map((id,i)=>({recipe_id:id,revision_id:id,status:i===0?'COMPLETE':'INCOMPLETE',base_servings:i===2?null:'4',target_servings:String(p.people),lines:[],reasons:i===0?[]:i===1?[{code:'UNKNOWN_QUANTITY',message:'TEST_ONLY seasoning quantity unknown',line_id:2}]:[{code:'INVALID_BASE_SERVINGS',message:'TEST_ONLY base servings missing'}]}));
      const data={dataset_version:ds,calculation_version:'portion-v1',recipe_ids:ids,people:p.people,status:'INCOMPLETE',totals_complete:false,portion_policy_version:'TEST_ONLY',recipes,
        known_ingredients:[known(ids[0],1,90100,'TEST_ONLY complete ingredient',100*p.people/4),known(ids[1],1,90101,'TEST_ONLY meat',400*p.people/4)]};
      return {version:1,request_id:'TEST_ONLY_display',ok:true,error:null,data};
    };
    window.calcImpl=async(url,opts,c)=>reply(portionFixture(c.payload));
    window.fetch=(url,opts)=>{
      if(url==='/api/meal-plan/calculate'){
        const call={payload:JSON.parse(opts.body),signal:opts.signal};calls.push(call);return calcImpl(url,opts,call);
      }
      const id=Number(String(url).split('/').pop());
      if(detailFixtures[id])return Promise.resolve(reply({ok:true,data:detailFixtures[id]}));
      return originalFetch(url,opts);
    };
  })()`);
  for(const [target,expected] of [[2,'200 g'],[4,'400 g'],[6,'600 g']]){
    let people=Number((await text('meal-people')).match(/\d+/)?.[0]||4);
    while(people>target){await click('#meal-adults-minus');people--;}
    while(people<target){await click('#meal-adults-plus');people++;}
    await done();
    const shopping=await text('meal-shopping-required')+await text('meal-shopping-optional')+await text('meal-shopping-unknown');
    assert.ok(shopping.includes('TEST_ONLY meat: '+expected),'Scaled meat at '+target+' servings');
    assert.ok(shopping.includes('TEST_ONLY salt: n\u00eam v\u1eeba \u0103n'),'Vague seasoning retained');
    assert.ok(shopping.includes('TEST_ONLY tofu: 200 g'),'No-base amount stays at source value');
    assert.ok(shopping.includes('TEST_ONLY pepper: m\u1ed9t \u00edt'),'Unquantified seasoning retained');
    assert.ok(shopping.includes('Kh\u00f4ng nh\u00e2n: c\u00f4ng th\u1ee9c thi\u1ebfu kh\u1ea9u ph\u1ea7n g\u1ed1c h\u1ee3p l\u1ec7.'),'Missing base is explained');
    assert.ok(shopping.includes('Ch\u01b0a c\u00f3 l\u01b0\u1ee3ng s\u1ed1 c\u1ee5 th\u1ec3; kh\u00f4ng t\u1ef1 coi l\u00e0 0.'),'Vague quantity is explained');
    assert.ok((await text('meal-portions-message')).includes('\u0110\u00e3 t\u00ednh m\u1ed9t ph\u1ea7n'));
  }
  await evaluate('window.fetch=window.originalFetch');await click('#meal-portions-retry');await done();
  assert.ok((await text('meal-portions-message')).startsWith('Ch\u01b0a th\u1ec3 t\u00ednh kh\u1ea9u ph\u1ea7n'));

  const saved=await snapshot();
  await navigate('/recipes/'+expectedIds[0]+'?return_to=%2Fmeal-plan');
  const history=await send('Page.getNavigationHistory');
  await send('Page.navigateToHistoryEntry',{entryId:history.entries[history.currentIndex-1].id});
  await wait('location.pathname==="/meal-plan"&&document.getElementById("meal-people")');await ready();await done();
  assert.equal(await text('meal-people'),saved.people+' ngÆ°á»i');
  for(const name of ['view','pins','conditions','history'])assert.deepEqual((await snapshot())[name],saved[name]);
  await navigate('/meal-plan');await ready();await done();
  assert.equal(await text('meal-people'),saved.people+' ngÆ°á»i');
  assert.equal(generationPosts.length,2,'Only the initial and selected custom-layout builds ran');
  for(const size of [width,320]){
    await send('Emulation.setDeviceMetricsOverride',{width:size,height:900,deviceScaleFactor:1,mobile:size<760});
    assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'No horizontal overflow at '+size);
    assert.ok(await evaluate('["meal-people-minus","meal-people-plus"].every(id=>{const r=document.getElementById(id).getBoundingClientRect();return r.height>=44&&r.width>=44})'),'Touch targets');
  }
  await send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:width<760});
  await evaluate('document.getElementById("meal-people").scrollIntoView({block:"center"})');
  const shot=await send('Page.captureScreenshot',{format:'png'});await writeFile(join(profile,'people-selector.png'),Buffer.from(shot.data,'base64'));
  assert.deepEqual(errors,[],'No uncaught browser errors');
  console.log('PASS people UI '+width+': real incomplete data, bounds, debounce, pins, quantities, partial results, retry, timeout, races, Back/reload, mobile.');
} catch(error){
  try{if(evaluate)await writeFile(join(profile,'failure.json'),JSON.stringify({error:error.message,errors,generationPosts,calculationPosts,dom:await evaluate('document.body.innerText')},null,2));}catch{}
  throw error;
} finally {
  if(socket?.readyState===WebSocket.OPEN){try{await send('Browser.close',{},null);}catch{}socket.close();}
  if(child.exitCode===null)child.kill();for(const p of pending.values())clearTimeout(p.timer);
}


