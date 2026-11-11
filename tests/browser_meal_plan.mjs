// Real installed browser via CDP; production HTTP/TCP path and temporary 50-recipe SQL fixture.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const [browser,base,profile,widthArg] = process.argv.slice(2), width = Number(widthArg);
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
const child = spawn(browser,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--disable-features=BackForwardCache','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
  '--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
let socket, session, serial=0, intercept='pass', held, activeWidth=width;
const pending=new Map(), errors=[], posts=[], screenshots=[];
const send=(method,params={},sessionId=session) => new Promise((resolve,reject) => {
  const id=++serial, timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},15000);
  pending.set(id,{resolve,reject,timer});
  socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
});
let evaluate, screenshot;
try {
  child.on('error',error=>errors.push(error.message));
  let port;
  for(let i=0;i<150;i++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{await pause(100);}}
  assert.ok(port,'Chrome startup');
  const version=await(await fetch('http://127.0.0.1:'+port+'/json/version')).json();
  socket=new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  socket.onmessage=event=>{
    const m=JSON.parse(event.data);
    if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
    if(m.method==='Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text);
    if(m.method==='Runtime.consoleAPICalled'&&m.params.type==='error') errors.push(m.params.args.map(a=>a.value??a.description).join(' '));
    if(m.method==='Network.requestWillBeSent'&&m.params.request.method==='POST'&&new URL(m.params.request.url).pathname==='/api/meal-plan') posts.push(m.params.request);
    if(m.method==='Fetch.requestPaused'){
      const {requestId}=m.params;
      if(intercept==='hold'){held={requestId,sessionId:m.sessionId};return;}
      const fake=intercept==='error'?{version:1,request_id:'e35954bb-19f1-40a6-a8d2-77288ead8050',ok:false,data:null,error:{code:'UPSTREAM_UNAVAILABLE',message:'Không thể kết nối TCP Server.'}}:
        intercept==='malformed'?{version:1,request_id:'e35954bb-19f1-40a6-a8d2-77288ead8050',ok:true,data:{bad:true},error:null}:null;
      const action=fake?send('Fetch.fulfillRequest',{requestId,responseCode:intercept==='error'?503:200,
        responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(fake)).toString('base64')},m.sessionId):
        send('Fetch.continueRequest',{requestId},m.sessionId);
      action.catch(error=>errors.push(error.message));
    }
  };
  const target=await send('Target.createTarget',{url:'about:blank'},null);
  session=(await send('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  for(const domain of ['Runtime','Page','Network']) await send(domain+'.enable');
  const resize=async size=>{activeWidth=size;return send('Emulation.setDeviceMetricsOverride',{width:size,height:900,deviceScaleFactor:1,mobile:size<760});};
  await resize(width);
  evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const wait=async(expression,note=expression)=>{for(let i=0;i<120;i++){if(await evaluate(expression))return;await pause(75);}throw Error('UI timeout: '+note);};
  const frames=()=>evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  const navigate=async path=>{const previous=await evaluate('performance.timeOrigin');await send('Page.navigate',{url:base+path});await wait('performance.timeOrigin!=='+previous+'&&document.readyState==="complete"&&location.pathname==='+JSON.stringify(new URL(path,base).pathname));};
  const ready=async()=>{await wait('document.getElementById("meal-ingredients")?.getAttribute("aria-busy")==="false"&&!document.getElementById("meal-generate").disabled');await frames();};
  const reloadSnapshot=async snapshot=>{
    // Install after pagehide saves the old document, before the new app reads storage.
    const {identifier}=await send('Page.addScriptToEvaluateOnNewDocument',{source:'sessionStorage.setItem("goiy-meal-plan-v1",'+JSON.stringify(snapshot)+')'});
    try{await navigate('/meal-plan/v1');await ready();}finally{await send('Page.removeScriptToEvaluateOnNewDocument',{identifier});}
  };
  const click=async selector=>{
    await frames();
    await evaluate('document.querySelector('+JSON.stringify(selector)+')?.scrollIntoView({block:"center",behavior:"instant"})');
    await frames();
    const point=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('Missing button');const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;if(!e.contains(document.elementFromPoint(x,y)))throw Error('Click obstructed');return{x,y};})()`);
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...point,...(type==='mouseMoved'?{}:{button:'left',clickCount:1})});
  };
  const input=(id,value)=>evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  const historyStep=async(delta,path)=>{
    const before=await evaluate('performance.timeOrigin'),h=await send('Page.getNavigationHistory');
    await send('Page.navigateToHistoryEntry',{entryId:h.entries[h.currentIndex+delta].id});
    await wait('performance.timeOrigin!=='+before+'&&location.pathname==='+JSON.stringify(path)+'&&document.readyState==="complete"');
  };
  const key=async(key,code,keyCode)=>{await send('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode:keyCode,...(key==='Enter'?{text:'\r',unmodifiedText:'\r'}:{})});await send('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode:keyCode});};
  const recipeIDs=()=>evaluate('[...document.querySelectorAll("[data-meal-slot]")].map(e=>Number(e.dataset.recipeId))');
  const finished=()=>wait('document.getElementById("meal-results").getAttribute("aria-busy")==="false"&&!document.getElementById("meal-message").classList.contains("hidden")');
  const make=async()=>{await click('#meal-generate');await finished();};
  const noOverflow=async()=>assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Horizontal overflow');
  screenshot=async label=>{
    await evaluate('document.activeElement?.blur();window.scrollTo(0,0)');await frames();
    const {cssContentSize}=await send('Page.getLayoutMetrics');
    // Paint the full export viewport to avoid missing mobile compositor tiles offscreen.
    try{
      await send('Emulation.setDeviceMetricsOverride',{width:activeWidth,height:Math.ceil(cssContentSize.height),deviceScaleFactor:1,mobile:activeWidth<760});
      await frames();
      const {data}=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
      await writeFile(join(profile,label+'.png'),Buffer.from(data,'base64'));screenshots.push(label+'.png');
    }finally{await resize(activeWidth);}
  };
  await navigate('/');
  await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")==="false"');
  await click('[data-select="1"]');await pause(400);await wait('document.getElementById("results-area").getAttribute("aria-busy")==="false"');
  await wait('document.querySelector(".detail-link")!==null');
  const oldTitles=await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(e=>e.textContent)');
  await navigate('/meal-plan/v1');await wait('location.pathname==="/meal-plan/v1"');await ready();
  const homeSnapshot=await evaluate('sessionStorage.getItem("goiy-selection-v1")');
  // Fresh document: real Tab/Enter/Space and a hidden skip link.
  await navigate('/meal-plan/v1');await ready();
  assert.ok(await evaluate('document.querySelector(".skip-link").getBoundingClientRect().bottom<=0'));
  await key('Tab','Tab',9);assert.equal(await evaluate('document.activeElement.className'),'skip-link');
  await key('Enter','Enter',13);await key('Tab','Tab',9);
  assert.equal(await evaluate('document.activeElement.id'),'meal-ingredient-search');
  await input('meal-ingredient-search','trung');await key('Tab','Tab',9);await key(' ','Space',32);
  assert.equal(await evaluate('document.getElementById("meal-selected-count").textContent'),'1/30');
  await input('meal-ingredient-search','');
  for(const id of [2,6,7])await click('[data-select="'+id+'"]');
  for(const [id,v] of [['meal-max-minutes','60'],['meal-max-total','90'],['meal-max-missing','2']])await input(id,v);
  await make();assert.deepEqual(await recipeIDs(),[1,5,29]);
  assert.ok(await evaluate('document.getElementById("meal-summary").textContent.includes("82")'));
  const catalog=await evaluate('window.RecipeImages.ready()');
  for(const slot of ['main','vegetable','soup']){
    await evaluate(`document.querySelector('[data-meal-slot="${slot}"]').scrollIntoView({block:'center'})`);
    await wait(`(()=>{const i=document.querySelector('[data-meal-slot="${slot}"] img');return i?.complete&&i.naturalWidth>0&&i.dataset.placeholder==='false'})()`);
    const photo=await evaluate(`(()=>{const i=document.querySelector('[data-meal-slot="${slot}"] img');return{id:Number(i.dataset.recipeId),path:new URL(i.currentSrc).pathname,loading:i.loading,alt:i.alt,width:i.getBoundingClientRect().width}})()`);
    assert.equal(photo.loading,'lazy');assert.ok(photo.alt);assert.ok(Object.values(catalog.recipes[photo.id].variants).includes(photo.path));assert.ok(photo.width<=width);
  }
  await noOverflow();await screenshot('meal-'+width);
  if(width<760){await resize(320);await noOverflow();await screenshot('meal-320');await resize(width);}
  const beforeBack=posts.length;
  const beforeShopping=await evaluate('document.getElementById("meal-shopping").textContent');
  await click('[data-meal-slot="main"] .detail-link');await wait('location.pathname==="/recipes/1"&&document.querySelector(".detail-heading h1")!==null');
  const mealSnapshot=await evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v1"))');
  assert.equal(await evaluate('document.querySelector(".back").getAttribute("href")'),'/meal-plan/v1');
  assert.equal(await evaluate('document.querySelector(".header-link").getAttribute("href")'),'/meal-plan/v1');
  // UI return is an allowlisted link, distinct from native browser Back/Forward.
  await click('.back');await wait('location.pathname==="/meal-plan/v1"');await ready();
  assert.deepEqual(await recipeIDs(),[1,5,29]);assert.equal(posts.length,beforeBack);
  assert.equal(await evaluate('document.getElementById("meal-shopping").textContent'),beforeShopping);
  assert.deepEqual(await evaluate('["meal-max-minutes","meal-max-total","meal-max-missing"].map(id=>document.getElementById(id).value)'),['60','90','2']);
  assert.equal(await evaluate('document.getElementById("meal-selected-count").textContent'),'4/30');
  assert.ok(Math.abs(await evaluate('window.scrollY')-mealSnapshot.scrollY)<=2,'UI return restores scroll');
  await click('[data-meal-slot="main"] .detail-link');await wait('location.pathname==="/recipes/1"&&document.getElementById("detail").getAttribute("aria-busy")==="false"');
  await historyStep(-1,'/meal-plan/v1');await ready();assert.deepEqual(await recipeIDs(),[1,5,29]);
  await historyStep(1,'/recipes/1');await wait('document.querySelector(".back")!==null');
  await click('.header-link');await wait('location.pathname==="/meal-plan/v1"');await ready();assert.deepEqual(await recipeIDs(),[1,5,29]);
  await navigate('/meal-plan/v1');await ready();assert.deepEqual(await recipeIDs(),[1,5,29]);
  assert.equal(await evaluate('sessionStorage.getItem("goiy-selection-v1")'),homeSnapshot);
  // Tight filters leave no alternate soup: retain both the dishes and grocery list.
  const shopping=await evaluate('document.getElementById("meal-shopping").textContent');
  await click('[data-replace="soup"]');await finished();
  assert.deepEqual(await recipeIDs(),[1,5,29]);
  assert.equal(await evaluate('document.getElementById("meal-shopping").textContent'),shopping);
  assert.ok(await evaluate('document.getElementById("meal-message").textContent.includes("giữ lại")'));
  let payload=JSON.parse(posts.at(-1).postData);
  assert.deepEqual(payload.locked_slots,['main','vegetable']);assert.deepEqual(payload.current_plan,{main:1,vegetable:5,soup:29});
  await input('meal-max-missing','');await input('meal-max-total','');
  assert.deepEqual(await recipeIDs(),[]);assert.ok(await evaluate('document.getElementById("meal-shopping").classList.contains("hidden")'));
  await make();await click('[data-replace="soup"]');await finished();assert.deepEqual(await recipeIDs(),[1,5,30]);
  await click('#meal-regenerate');await finished();
  assert.ok((await recipeIDs()).every((id,i)=>id!==[1,5,30][i]));assert.deepEqual(JSON.parse(posts.at(-1).postData).locked_slots,[]);
  // Use actual filters on the full fixture to leave exactly one vegetable option.
  for(const id of [1,2,6,7])await click('#meal-selected [data-remove="'+id+'"]');
  await input('meal-max-minutes','');
  for(const [id,query] of [[11,'khoai tay'],[46,'nam rom'],[22,'chanh']]){await input('meal-ingredient-search',query);await click('[data-exclude="'+id+'"]');}
  await input('meal-ingredient-search','');await make();await click('#meal-regenerate');await finished();
  assert.ok(await evaluate('document.getElementById("meal-message").textContent.includes("một phần")'));
  await screenshot('partial-'+width);
  await input('meal-max-missing','0');await make();assert.deepEqual(await recipeIDs(),[]);
  assert.ok(await evaluate('!document.getElementById("meal-empty").classList.contains("hidden")'));
  await screenshot('empty-'+width);
  // Broken storage is discarded safely; namespace of the home page stays intact.
  await reloadSnapshot('{broken');
  assert.deepEqual(await recipeIDs(),[]);await make();
  for(const mutation of ['s.view.data.dataset_version="old"','s.view.data.classification_version="old"','s.view.signature="wrong"','s.view.data.plan.items[0].slot="soup"']){
    const snapshot=await evaluate(`(()=>{const s=JSON.parse(sessionStorage.getItem('goiy-meal-plan-v1'));${mutation};return JSON.stringify(s);})()`);
    await reloadSnapshot(snapshot);assert.deepEqual(await recipeIDs(),[]);await make();
  }
  // Six feasible soups with the other two slots locked: visit each before a new cycle.
  await make();const seenSoups=[(await recipeIDs())[2]];
  for(let n=0;n<5;n++){
    await click('[data-replace="soup"]');await finished();const id=(await recipeIDs())[2];
    assert.ok(!seenSoups.includes(id),'Do not bounce to a previously seen soup');seenSoups.push(id);
    assert.deepEqual(JSON.parse(posts.at(-1).postData).locked_slots,['main','vegetable']);
    if(n===1){
      const h=await evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v1")).history');
      const beforeReload=await recipeIDs();await navigate('/meal-plan/v1');await ready();
      assert.deepEqual(await recipeIDs(),beforeReload);
      assert.deepEqual(await evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v1")).history'),h);
    }
  }
  assert.equal(new Set(seenSoups).size,6);
  await click('[data-replace="soup"]');await finished();
  assert.ok(await evaluate('document.getElementById("meal-message").textContent.includes("vòng mới")'));
  assert.equal(JSON.parse(posts.at(-1).postData).avoid_recipe_ids.soup.length,6);
  assert.equal((await evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v1")).history.soup')).length,2);
  await input('meal-max-minutes','25');
  assert.deepEqual(await evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v1")).history'),{main:[],vegetable:[],soup:[]});
  await make();const twoSoups=[(await recipeIDs())[2]];
  for(let n=0;n<2;n++){await click('[data-replace="soup"]');await finished();twoSoups.push((await recipeIDs())[2]);}
  assert.notEqual(twoSoups[0],twoSoups[1]);assert.equal(twoSoups[0],twoSoups[2]);
  assert.ok(await evaluate('document.getElementById("meal-message").textContent.includes("vòng mới")'));
  // Simulated HTTP failures exercise presentation; normal cases use real gateway/TCP.
  await send('Fetch.enable',{patterns:[{urlPattern:'*/api/meal-plan',requestStage:'Request'}]});
  let old=await recipeIDs();intercept='error';await click('[data-replace="main"]');await finished();
  assert.deepEqual(await recipeIDs(),old);assert.ok(await evaluate('!document.getElementById("meal-retry").classList.contains("hidden")'));
  intercept='pass';await click('#meal-retry');await finished();assert.notDeepEqual(await recipeIDs(),old);
  old=await recipeIDs();intercept='malformed';await click('[data-replace="main"]');await finished();assert.deepEqual(await recipeIDs(),old);
  intercept='hold';const beforeDouble=posts.length;await click('#meal-regenerate');await wait('document.getElementById("meal-results").getAttribute("aria-busy")==="true"');
  await click('#meal-generate');assert.equal(posts.length,beforeDouble+1,'Double click must not send another request');
  await input('meal-max-missing','0');assert.deepEqual(await recipeIDs(),[]);
  intercept='pass';if(held){await send('Fetch.continueRequest',{requestId:held.requestId},held.sessionId).catch(()=>{});held=null;}
  await make();assert.deepEqual(await recipeIDs(),[]);await send('Fetch.disable');
  // Actual error event on a local image must mount the existing placeholder.
  await input('meal-max-missing','');await make();
  await evaluate('(()=>{const i=document.querySelector("#meal-cards img");i.removeAttribute("srcset");i.src="/static/images/recipes/missing-test.webp";})()');
  await wait('document.querySelector("#meal-cards img").dataset.placeholder==="true"');
  assert.equal(await evaluate('document.querySelector("#meal-cards img").getAttribute("src")'),'/static/images/recipes/placeholder.svg');
  await noOverflow();assert.equal(await evaluate('sessionStorage.getItem("goiy-selection-v1")'),homeSnapshot);
  await navigate('/');await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")==="false"');
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(e=>e.textContent)'),oldTitles);
  const homeRecipePath=await evaluate('new URL(document.querySelector(".detail-link").href).pathname');
  await click('.detail-link');await wait('document.getElementById("detail")?.getAttribute("aria-busy")==="false"');
  assert.equal(await evaluate('document.querySelector(".back").getAttribute("href")'),'/');
  await click('.back');await wait('location.pathname==="/"');
  await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")==="false"');
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(e=>e.textContent)'),oldTitles);
  await click('.detail-link');await wait('document.getElementById("detail")?.getAttribute("aria-busy")==="false"');
  await historyStep(-1,'/');await wait('document.querySelector(".detail-link")!==null');
  await historyStep(1,homeRecipePath);await wait('document.querySelector(".back")!==null');
  await click('.back');await wait('location.pathname==="/"');
  await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")==="false"');await frames();
  await navigate('/?view=explore');await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")=="false"');await input('recipe-query','dau phu');await click('#recommend-button');
  await wait('document.getElementById("results-area").getAttribute("aria-busy")==="false"&&document.querySelector(".detail-link")!==null');
  const searchTitles=await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(e=>e.textContent)');
  await click('.detail-link');await wait('document.getElementById("detail")?.getAttribute("aria-busy")==="false"');
  assert.equal(await evaluate('document.querySelector(".back").getAttribute("href")'),'/');
  await click('.back');await wait('location.pathname==="/"');await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")==="false"');
  assert.equal(await evaluate("document.querySelector('[data-user-tab=\"explore\"]').getAttribute('aria-current')"),'page');
  assert.equal(await evaluate('document.getElementById("recipe-query").value'),'dau phu');
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(e=>e.textContent)'),searchTitles);
  await navigate('/recipes/999?return_to=https%3A%2F%2Fevil.example');
  await wait('document.querySelector(".detail-error-back")!==null');
  assert.equal(await evaluate('document.querySelector(".detail-error-back").getAttribute("href")'),'/');
  assert.equal(await evaluate('document.querySelector(".back").getAttribute("href")'),'/');
  await navigate('/recipes/invalid');await wait('document.querySelector(".detail-error-back")!==null');
  assert.equal(await evaluate('document.querySelector(".detail-error-back").getAttribute("href")'),'/');
  assert.deepEqual(errors,[],'Uncaught browser JavaScript/console errors');
  await writeFile(join(profile,'browser-summary.json'),JSON.stringify({width,posts:posts.map(p=>JSON.parse(p.postData)),seenSoups,twoSoups,screenshots,errors},null,2));
  console.log('PASS meal UI '+width+': TCP-backed create/replace/partial/empty, images, Back/reload, cache, keyboard, double click, stale response and retry.');
} catch(error){
  try{if(evaluate)await writeFile(join(profile,'failure.json'),JSON.stringify({error:error.message,posts,errors,dom:await evaluate('document.body.innerText')},null,2));if(screenshot)await screenshot('failure');}catch{}
  throw error;
} finally {
  if(socket?.readyState===WebSocket.OPEN){try{await send('Browser.close',{},null);}catch{}socket.close();}
  if(child.exitCode===null)child.kill();for(const p of pending.values())clearTimeout(p.timer);
}
