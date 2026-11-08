// Real installed browser via CDP; production HTTP/TCP path and temporary 50-recipe SQL fixture.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const [browser,base,profile,widthArg,catalogMode] = process.argv.slice(2), width = Number(widthArg);
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
const child = spawn(browser,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--disable-features=BackForwardCache','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
  '--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
let socket, session, serial=0, intercept='pass', held, activeWidth=width;
const pending=new Map(), errors=[], posts=[], screenshots=[], calcPosts=[];
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
    if(m.method==='Network.requestWillBeSent'&&m.params.request.method==='POST'&&new URL(m.params.request.url).pathname==='/api/meal-plan/v2') posts.push(m.params.request);
    if(m.method==='Network.requestWillBeSent'&&m.params.request.method==='POST'&&new URL(m.params.request.url).pathname==='/api/meal-plan/calculate') calcPosts.push(JSON.parse(m.params.request.postData));
    if(m.method==='Fetch.requestPaused'){
      const {requestId}=m.params;
      if(intercept==='hold'){held={requestId,sessionId:m.sessionId};return;}
      const fake=['error','timeout'].includes(intercept)?{version:1,request_id:'e35954bb-19f1-40a6-a8d2-77288ead8050',ok:false,data:null,error:{code:intercept==='timeout'?'TIMEOUT':'UPSTREAM_UNAVAILABLE',message:'Không thể kết nối TCP Server.'}}:
        intercept==='malformed'?{version:1,request_id:'e35954bb-19f1-40a6-a8d2-77288ead8050',ok:true,data:{bad:true},error:null}:null;
      const action=fake?send('Fetch.fulfillRequest',{requestId,responseCode:intercept==='error'?503:intercept==='timeout'?504:200,
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

  const snapshot=()=>evaluate('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v2"))');
  const pin=async slot=>{await click('[data-pin="'+slot+'"]');};
  const mapping=()=>evaluate('Object.fromEntries([...document.querySelectorAll("[data-meal-slot]")].map(e=>[e.dataset.mealSlot,Number(e.dataset.recipeId)]))');
  const regenerate=async()=>{await click('#meal-regenerate');await finished();};
  const unpinAll=()=>evaluate(`(()=>{const keys=[...document.querySelectorAll('[data-pin][aria-pressed="true"]')].map(b=>b.dataset.pin);for(const k of keys)document.querySelector('[data-pin="'+k+'"]').click();})()`);


  // TEST_ONLY complete plant declarations live only in this test's temporary SQLite DB.
  const published=catalogMode==='published-v2';
  const allowed=new Set(published?Array.from({length:6},(_,i)=>4294967297+i):[4,44,5,9,6,32]);
  const excludedIngredient=published?4294967368:5;
  const setPeople=n=>evaluate(`(()=>{const current=parseInt(document.getElementById('meal-people').value);for(let i=0;i<Math.abs(${n}-current);i++)document.getElementById(${n}>current?'meal-people-plus':'meal-people-minus').click();})()`);
  const settled=async()=>{await finished();await wait('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v2")).autoPending===false');};
  const checkMeal=async size=>{
    await settled();const ids=await recipeIDs();assert.equal(ids.length,size);assert.ok(ids.every(id=>allowed.has(id)));
    const s=await snapshot();assert.equal(s.conditions.preferences.diet,'vegetarian');
    assert.ok(!s.view.data.plan.required_ids.some(id=>[1,4,13,14,24,26,28,29,35,36,37,38,39].includes(id)));
  };
  await navigate('/meal-plan');await ready();await wait('!document.getElementById("meal-pref-diet").disabled');
  assert.equal(await evaluate('document.querySelector("#meal-pref-diet option[value=vegetarian]").disabled'),false);
  await evaluate('document.getElementById("meal-pref-diet").value="vegetarian";document.getElementById("meal-pref-diet").dispatchEvent(new Event("change",{bubbles:true}))');
  await make();await checkMeal(3);
  await pin('main:1');const held=(await mapping())['main:1'];
  const before=await mapping();await click('[data-replace="vegetable:1"]');await checkMeal(3);
  const after=await mapping();assert.notEqual(after['vegetable:1'],before['vegetable:1']);
  assert.equal(after['main:1'],before['main:1']);assert.equal(after['soup:1'],before['soup:1']);
  await regenerate();await checkMeal(3);assert.equal((await mapping())['main:1'],held);
  await setPeople(9);await checkMeal(6);assert.equal((await mapping())['main:1'],held);
  await pin('soup:2');const six=await mapping();await setPeople(8);await settled();assert.deepEqual(await mapping(),six);
  assert.ok((await snapshot()).pins.includes('soup:2'));
  await pin('soup:2');await checkMeal(5);await setPeople(4);await checkMeal(3);
  await unpinAll();await click('[data-exclude="'+excludedIngredient+'"]');await make();await settled();
  assert.equal((await snapshot()).conditions.preferences.diet,'vegetarian');
  assert.ok((await evaluate('document.getElementById("meal-message").textContent')).includes('chay'));
  const shortage=await snapshot();await navigate('/meal-plan');await ready();
  assert.deepEqual((await snapshot()).conditions,shortage.conditions);assert.deepEqual((await snapshot()).view,shortage.view);
  assert.ok((await evaluate('document.getElementById("meal-message").textContent')).includes('chay'));
  await evaluate('document.querySelector("#meal-excluded [data-remove]").click()');await make();await checkMeal(3);
  // A transport outage must retain the Chay preference and the last valid meal.
  const valid=await mapping();intercept='error';await send('Fetch.enable',{patterns:[{urlPattern:'*/api/meal-plan/v2',requestStage:'Request'}]});
  await setPeople(5);await settled();assert.deepEqual(await mapping(),valid);
  assert.equal(await evaluate('document.getElementById("meal-message").classList.contains("error")'),true);
  const failed=await snapshot();await navigate('/meal-plan');await ready();
  assert.equal((await snapshot()).people,5);assert.deepEqual((await snapshot()).conditions,failed.conditions);
  assert.equal(await evaluate('document.getElementById("meal-retry").classList.contains("hidden")'),false);
  intercept='pass';await click('#meal-retry');await checkMeal(4);await send('Fetch.disable');
  const saved=await snapshot();await click('.detail-link');await wait('location.pathname.startsWith("/recipes/")');
  await historyStep(-1,'/meal-plan');await ready();
  for(const field of ['people','pins','conditions','view'])assert.deepEqual((await snapshot())[field],saved[field]);
  // UI-only TEST_ONLY capability response: two-person data must not enable larger layouts.
  await evaluate(`window.metaFetch=window.fetch;window.fetch=async(url,opts)=>{
    const response=await metaFetch(url,opts);if(!String(url).startsWith('/api/meal-plan/filters'))return response;
    const e=await response.json(),c=e.data.choices.diet.find(c=>c.code==='vegetarian');
    c.supported_people=[1,2];c.role_counts={main:2,vegetable:2,soup:0};c.recipe_count=4;c.enabled=true;
    return new Response(JSON.stringify(e),{status:200,headers:{'Content-Type':'application/json'}});
  };document.getElementById('meal-filter-retry').onclick()`);
  await wait('document.querySelector("#meal-pref-diet option[value=vegetarian]").disabled');
  assert.equal(await evaluate('document.getElementById("meal-pref-diet").value'),'vegetarian','Unsupported selection is retained, not cleared');
  await setPeople(2);await checkMeal(2);
  assert.equal(await evaluate('document.querySelector("#meal-pref-diet option[value=vegetarian]").disabled'),false);
  await evaluate('window.fetch=window.metaFetch;document.getElementById("meal-filter-retry").onclick()');
  await wait('!document.querySelector("#meal-pref-diet option[value=vegetarian]").disabled');
  await setPeople(3);await checkMeal(3);
  await wait('document.getElementById("meal-portions").getAttribute("aria-busy")==="false"');
  assert.equal(await evaluate('document.getElementById("meal-portions-known").children.length'),0,'Diet review does not approve portions');
  await noOverflow();if(width<760){await resize(320);await noOverflow();await resize(width);}
  await screenshot('vegetarian-fixture');assert.deepEqual(errors,[]);
  console.log('PASS TEST_ONLY vegetarian UI '+width+': all dishes verified, pins, swaps, headcount, shortage, errors, retry, Back/reload, per-layout capability gate.');
} catch(error){
  try{if(evaluate)await writeFile(join(profile,'failure.json'),JSON.stringify({error:error.message,posts,errors,dom:await evaluate('document.body.innerText')},null,2));if(screenshot)await screenshot('failure');}catch{}
  throw error;
} finally {
  if(socket?.readyState===WebSocket.OPEN){try{await send('Browser.close',{},null);}catch{}socket.close();}
  if(child.exitCode===null)child.kill();for(const p of pending.values())clearTimeout(p.timer);
}
