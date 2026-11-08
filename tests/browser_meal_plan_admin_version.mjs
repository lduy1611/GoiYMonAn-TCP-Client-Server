// Headless real-browser interaction via Chrome's own dump-dom runner.
// The injected extension clicks the page's real Generate button and records a result marker.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const [browser,base,root,widthArg]=process.argv.slice(2),width=Number(widthArg);
const extension=join(root,'extension'),profile=join(root,'profile');
await mkdir(extension,{recursive:true});await mkdir(profile,{recursive:true});
await writeFile(join(extension,'manifest.json'),JSON.stringify({manifest_version:3,name:'TEST_ONLY meal browser check',version:'1.0',
  content_scripts:[{matches:['http://127.0.0.1/*'],js:['test.js'],run_at:'document_idle'}]}));
await writeFile(join(extension,'test.js'),`(()=>{
 const started=Date.now();let clicked=false;
 const tick=()=>{
   const btn=document.getElementById('meal-generate'),results=document.getElementById('meal-results');
   if(!clicked&&btn&&!btn.disabled){clicked=true;btn.click();}
   if(clicked&&results?.getAttribute('aria-busy')==='false'){
     const cards=document.querySelectorAll('[data-meal-slot]').length;
     if(cards===3){
       const state=JSON.parse(sessionStorage.getItem('goiy-meal-plan-v2'));
       const result={ok:document.getElementById('meal-message').classList.contains('hidden'),
         cards,version:state?.view?.data?.classification_version,
         overflow:document.documentElement.scrollWidth>innerWidth,width:innerWidth};
       document.documentElement.setAttribute('data-meal-plan-browser-test',btoa(unescape(encodeURIComponent(JSON.stringify(result)))));return;
     }
     if(!document.getElementById('meal-message').classList.contains('hidden')){
       document.documentElement.setAttribute('data-meal-plan-browser-test',btoa(JSON.stringify({ok:false,
         message:document.getElementById('meal-message').textContent,cards})));return;
     }
   }
   if(Date.now()-started>12000){document.documentElement.setAttribute('data-meal-plan-browser-test',btoa(JSON.stringify({ok:false,timeout:true,cards:document.querySelectorAll('[data-meal-slot]').length})));return;}
   setTimeout(tick,50);
 };tick();
})()`);
const child=spawn(browser,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--disable-extensions-except='+extension,'--load-extension='+extension,'--user-data-dir='+profile,
  `--window-size=${width},900`,'--virtual-time-budget=15000','--dump-dom',base+'/meal-plan'],{windowsHide:true,stdio:['ignore','pipe','pipe']});
let stdout='',stderr='';child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
child.stdout.on('data',chunk=>stdout+=chunk);child.stderr.on('data',chunk=>stderr+=chunk);
const exit=await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{child.kill();reject(Error('Chrome dump-dom timed out'));},30000);
  child.on('error',reject);child.on('close',(code,signal)=>{clearTimeout(timer);resolve({code,signal});});
});
if(exit.code!==0&&/GPU process isn't usable|Failed to open persistent cache files/.test(stderr+stdout)){
  console.log('BROWSER_UNAVAILABLE: local browser GPU/cache sandbox prevented headless startup');process.exit(77);
}
assert.equal(exit.code,0,stderr.slice(-2000));
const match=stdout.match(/data-meal-plan-browser-test="([^"]+)"/);assert.ok(match,'Browser interaction marker was written');
const report=JSON.parse(Buffer.from(match[1],'base64').toString('utf8'));
assert.equal(report.ok,true,JSON.stringify(report));assert.equal(report.cards,3);assert.equal(report.overflow,false);
assert.match(report.version,/^meal-categories-v1:v2:[a-f0-9]{16}:admin:[a-f0-9]{12}$/);
console.log(`PASS real browser ${width}px: three meal cards, Admin catalog response accepted, no layout overflow`);
