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

  const setPeople=n=>evaluate(`(()=>{const current=parseInt(document.getElementById('meal-people').value);for(let i=0;i<Math.abs(${n}-current);i++)document.getElementById(${n}>current?'meal-people-plus':'meal-people-minus').click();})()`);
  const settled=async()=>{await finished();await wait('JSON.parse(sessionStorage.getItem("goiy-meal-plan-v2")).autoPending===false');};
  const calcDone=()=>wait('document.getElementById("meal-portions").getAttribute("aria-busy")==="false"');
  const expectSize=async(size,people)=>{
    await settled();assert.equal((await recipeIDs()).length,size);
    assert.equal((await snapshot()).people,people);
    assert.ok((await evaluate('document.getElementById("meal-structure").textContent')).includes(size+' món'));
    assert.equal(JSON.parse(posts.at(-1).postData).people,people);
    assert.equal('counts' in JSON.parse(posts.at(-1).postData),false,'TCP derives counts');
    await calcDone();assert.deepEqual(calcPosts.at(-1),{recipe_ids:await recipeIDs(),people});
  };
  await navigate('/meal-plan');await ready();
  assert.equal(await evaluate('document.querySelectorAll("[id^=meal-count-]").length'),0,'No manual mode');
  assert.equal(await evaluate('document.getElementById("meal-people").value'),'4 người');
  await make();await expectSize(3,4);
  const start=await recipeIDs(), count=posts.length;
  await setPeople(3);await calcDone();assert.equal(posts.length,count);assert.deepEqual(await recipeIDs(),start);
  assert.equal(calcPosts.at(-1).people,3,'Same structure only recalculates');
  await setPeople(2);await expectSize(2,2);
  await pin('main:1');const pinned=(await mapping())['main:1'];
  for(const [before,after,size] of [[2,3,3],[4,5,4],[6,7,5],[8,9,6]]){
    await setPeople(before);await calcDone();const requests=posts.length;
    await setPeople(after);await expectSize(size,after);
    assert.equal(posts.length,requests+1,'One generation at '+before+'→'+after);
    assert.equal((await mapping())['main:1'],pinned,'Compatible pin retained');
  }
  await evaluate('window.card=document.querySelector("[data-meal-slot]")');
  const sameBand=posts.length, six=await mapping();await setPeople(10);await calcDone();
  assert.equal(posts.length,sameBand);assert.deepEqual(await mapping(),six);
  assert.ok(await evaluate('window.card===document.querySelector("[data-meal-slot]")'),'Same-band DOM retained');
  // Shrinking cannot silently remove a pinned slot; original meal survives reload.
  await pin('soup:2');const pinnedPlan=await mapping(), calcs=calcPosts.length;
  await setPeople(8);await settled();
  assert.deepEqual(await mapping(),pinnedPlan);assert.equal(calcPosts.length,calcs,'No calculation for a conflicting layout');
  assert.ok((await evaluate('document.getElementById("meal-message").textContent')).includes('ghim'));
  assert.equal(await evaluate('document.getElementById("meal-stale").classList.contains("hidden")'),false);
  const conflict=await snapshot(), beforeReload=posts.length;
  await navigate('/meal-plan');await ready();
  assert.equal(posts.length,beforeReload,'Failed layout is not silently retried on reload');
  assert.deepEqual((await snapshot()).pins,conflict.pins);assert.equal((await snapshot()).people,8);
  assert.deepEqual(await mapping(),pinnedPlan);
  assert.equal(await evaluate('document.getElementById("meal-retry").classList.contains("hidden")'),false);
  await pin('soup:2');await expectSize(5,8);assert.equal((await mapping())['main:1'],pinned);
  // Individual replacement still locks all other slots on TCP.
  const beforeReplace=await mapping();await click('[data-replace="vegetable:1"]');await settled();
  const afterReplace=await mapping();assert.notEqual(afterReplace['vegetable:1'],beforeReplace['vegetable:1']);
  for(const key of Object.keys(beforeReplace).filter(k=>k!=='vegetable:1'))assert.equal(afterReplace[key],beforeReplace[key]);
  await evaluate(`(()=>{const keys=[...document.querySelectorAll('[data-pin][aria-pressed="false"]')].map(b=>b.dataset.pin);for(const k of keys)document.querySelector('[data-pin="'+k+'"]').click();})()`);
  const allPinned=await mapping();await regenerate();assert.deepEqual(await mapping(),allPinned);
  await unpinAll();await regenerate();assert.notDeepEqual(await mapping(),allPinned);
  await click('[data-select="1"]');await click('[data-exclude="13"]');
  await input('meal-max-minutes','60');await make();await settled();
  assert.equal((await snapshot()).view.data.plan.required_ids.includes(13),false);
  assert.ok((await snapshot()).view.data.plan.items.every(i=>i.minutes<=60));
  await wait('!document.getElementById("meal-pref-diet").disabled');
  assert.equal(await evaluate('document.querySelector("#meal-pref-diet option[value=vegetarian]").disabled'),true);
  assert.equal(await evaluate('document.getElementById("meal-pref-region").disabled&&document.getElementById("meal-pref-occasion").disabled'),true);
  await evaluate('document.getElementById("meal-pref-diet").value="non_vegetarian";document.getElementById("meal-pref-diet").dispatchEvent(new Event("change",{bubbles:true}))');
  await make();await settled();assert.ok((await snapshot()).view.data.plan.required_ids.some(id=>[4,14,28,35,36,37,38,39].includes(id)));
  // Invalid time input must not leave the automatic generation spinner stuck.
  const beforeInvalid=await mapping(), invalidPosts=posts.length;
  await input('meal-max-minutes','0');await setPeople(9);
  await wait('document.getElementById("meal-message").classList.contains("error")&&document.getElementById("meal-results").getAttribute("aria-busy")==="false"');
  assert.deepEqual(await mapping(),beforeInvalid);assert.equal(posts.length,invalidPosts);
  await input('meal-max-minutes','60');await setPeople(8);await calcDone();
  // HTTP timeout during a layout change: retain old meal, preferences, headcount and retry.
  const old=await mapping();intercept='timeout';await send('Fetch.enable',{patterns:[{urlPattern:'*/api/meal-plan/v2',requestStage:'Request'}]});
  await setPeople(9);await settled();assert.deepEqual(await mapping(),old);
  assert.ok((await evaluate('document.getElementById("meal-message").textContent')).includes('lâu'));
  const failed=await snapshot(), failedPosts=posts.length;
  await navigate('/meal-plan');await ready();
  assert.equal(posts.length,failedPosts);assert.equal((await snapshot()).people,9);
  assert.deepEqual((await snapshot()).conditions,failed.conditions);
  assert.equal(await evaluate('document.getElementById("meal-retry").classList.contains("hidden")'),false);
  intercept='pass';await click('#meal-retry');await expectSize(6,9);await send('Fetch.disable');
  // Ignore abort deliberately: a previous headcount must not overwrite the newest meal.
  await evaluate(`window.realFetch=window.fetch;window.requests=[];window.fetch=(url,opts)=>url==='/api/meal-plan/v2'?new Promise((resolve,reject)=>{const held={resolve,reject,signal:opts.signal};requests.push(held);realFetch(url,{...opts,signal:undefined}).then(r=>held.response=r);}):realFetch(url,opts)`);
  await setPeople(8);await wait('requests.length===1&&!!requests[0].response');
  await setPeople(6);await wait('requests.length===2&&!!requests[1].response');
  assert.equal(await evaluate('requests[0].signal.aborted'),true);
  await evaluate('requests[1].resolve(requests[1].response)');await expectSize(4,6);
  const newest=await snapshot();await evaluate('requests[0].resolve(requests[0].response)');await pause(100);
  assert.deepEqual(await snapshot(),newest);
  await setPeople(7);await wait('requests.length===3&&!!requests[2].response');
  await setPeople(9);await wait('requests.length===4&&!!requests[3].response');
  await evaluate('requests[3].resolve(requests[3].response)');await expectSize(6,9);
  const latest=await snapshot();await evaluate('requests[2].reject(Error("TEST_ONLY late failure"))');await pause(100);assert.deepEqual(await snapshot(),latest);
  await evaluate('window.realTimeout=window.setTimeout;window.setTimeout=(fn,ms,...args)=>realTimeout(fn,ms===10000?50:ms,...args)');
  await setPeople(8);await settled();assert.equal(await evaluate('requests.at(-1).signal.aborted'),true);
  assert.ok((await evaluate('document.getElementById("meal-message").textContent')).includes('lâu'));
  await evaluate('window.setTimeout=window.realTimeout;window.fetch=window.realFetch');
  await click('#meal-retry');await expectSize(5,8);
  // Reload while a layout request is pending resumes the intent using current people.
  await evaluate(`window.requests=[];window.fetch=(url,opts)=>url==='/api/meal-plan/v2'?new Promise(resolve=>requests.push({resolve,signal:opts.signal})):realFetch(url,opts)`);
  await setPeople(9);await wait('requests.length===1');await navigate('/meal-plan');await ready();await expectSize(6,9);
  await setPeople(1);await expectSize(2,1);assert.equal(await evaluate('document.getElementById("meal-people-minus").disabled'),true);
  await setPeople(12);await expectSize(6,12);assert.equal(await evaluate('document.getElementById("meal-people-plus").disabled'),true);
  const saved=await snapshot();await click('.detail-link');await wait('location.pathname.startsWith("/recipes/")');
  await historyStep(-1,'/meal-plan');await ready();await calcDone();
  for(const field of ['people','view','pins','conditions'])assert.deepEqual((await snapshot())[field],saved[field]);
  await noOverflow();await screenshot('automatic-layout');
  // An old manual snapshot is retained, then checked against the new headcount policy.
  const legacy=structuredClone(saved);legacy.version=1;legacy.people=4;legacy.pins=['soup:2'];delete legacy.view.data.people;delete legacy.autoPending;delete legacy.retry;
  const {identifier}=await send('Page.addScriptToEvaluateOnNewDocument',{source:'sessionStorage.setItem("goiy-meal-plan-v2",'+JSON.stringify(JSON.stringify(legacy))+');sessionStorage.setItem("goiy-meal-plan-v2-people","4");'});
  try{await navigate('/meal-plan');await ready();await settled();}finally{await send('Page.removeScriptToEvaluateOnNewDocument',{identifier});}
  assert.deepEqual((await snapshot()).pins,['soup:2']);assert.equal((await recipeIDs()).length,6);
  assert.equal((await snapshot()).people,4);assert.ok((await evaluate('document.getElementById("meal-message").textContent')).includes('ghim'));
  assert.deepEqual(errors,[],'Uncaught browser errors');
  console.log('PASS automatic meal UI '+width+': all boundaries, same-band calculation, pins/conflicts, single/all replacement, preferences, filters, retry/timeout, races, pending/failed reload, Back and legacy storage migration.');
} catch(error){
  try{if(evaluate)await writeFile(join(profile,'failure.json'),JSON.stringify({error:error.message,posts,errors,dom:await evaluate('document.body.innerText')},null,2));if(screenshot)await screenshot('failure');}catch{}
  throw error;
} finally {
  if(socket?.readyState===WebSocket.OPEN){try{await send('Browser.close',{},null);}catch{}socket.close();}
  if(child.exitCode===null)child.kill();for(const p of pending.values())clearTimeout(p.timer);
}
