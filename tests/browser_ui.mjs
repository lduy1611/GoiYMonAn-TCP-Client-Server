// Browser regression tests with installed Chrome/Edge and Node's built-in CDP WebSocket.
// No npm packages, external images, or modified application endpoints are required.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const [browserPath, baseUrl, profileDir, widthArg, mode = 'test', legacyCssPath] = process.argv.slice(2);
const width = Number(widthArg);
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const processHandle = spawn(browserPath, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-features=BackForwardCache',
  '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
  '--user-data-dir=' + profileDir, '--window-size=' + width + ',900', 'about:blank'
], {stdio: 'ignore', windowsHide: true});
let socket;
let serial = 0;
let session;
const pending = new Map();
const pageErrors = [];
const posts = [];
let legacyCss;
const send = (method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
  const id = ++serial;
  const timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 15000);
  pending.set(id, {resolve, reject, timer});
  socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
});

try {
  processHandle.on('error', error => pageErrors.push(error.message));
  let port;
  for (let attempt = 0; attempt < 150; attempt++) {
    try { port = (await readFile(join(profileDir, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; }
    catch { await pause(100); }
  }
  assert.ok(port, 'Browser did not expose DevToolsActivePort; ' + pageErrors.join('; '));
  const version = await (await fetch('http://127.0.0.1:' + port + '/json/version')).json();
  socket = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Fetch.requestPaused') {
      const {requestId, request} = message.params;
      const method = legacyCss && new URL(request.url).pathname === '/static/styles.css' && !new URL(request.url).search
        ? 'Fetch.fulfillRequest' : 'Fetch.continueRequest';
      const params = method === 'Fetch.fulfillRequest'
        ? {requestId, responseCode: 200, responseHeaders: [{name: 'Content-Type', value: 'text/css'}], body: legacyCss}
        : {requestId};
      send(method, params, message.sessionId).catch(error => pageErrors.push(error.message));
    }
    if (message.id && pending.has(message.id)) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(request.timer);
      if (message.error) request.reject(Error(JSON.stringify(message.error)));
      else request.resolve(message.result);
    }
    if (message.method === 'Runtime.exceptionThrown') pageErrors.push(message.params.exceptionDetails.text);
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      pageErrors.push(message.params.args.map(arg => arg.value ?? arg.description).join(' '));
    }
    if (message.method === 'Network.requestWillBeSent' && message.params.request.method === 'POST') posts.push(message.params.request);
  };
  const {targetId} = await send('Target.createTarget', {url: 'about:blank'}, null);
  session = (await send('Target.attachToTarget', {targetId, flatten: true}, null)).sessionId;
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Network.enable');
  const resize = async size => {
    await send('Emulation.setDeviceMetricsOverride', {width: size, height: 900, deviceScaleFactor: 1, mobile: size < 760});
  };
  await resize(width);
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const wait = async (expression, note = expression) => {
    for (let attempt = 0; attempt < 120; attempt++) {
      if (await evaluate(expression)) return;
      await pause(75);
    }
    throw Error('UI timeout: ' + note);
  };
  const navigate = async path => {
    const previousDocument = await evaluate('performance.timeOrigin');
    await send('Page.navigate', {url: baseUrl + path});
    await wait('performance.timeOrigin !== ' + previousDocument + ' && document.readyState === "complete" && location.pathname === ' + JSON.stringify(path));
  };
  const click = async selector => {
    assert.ok(await evaluate('!!document.querySelector(' + JSON.stringify(selector) + ')'), 'Missing: ' + selector);
    const point = await evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      el.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'});
      const rect = el.getBoundingClientRect();
      const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
      const hit = document.elementFromPoint(x, y);
      if (!el.contains(hit)) throw Error('Click blocked by ' + hit?.outerHTML);
      return {x, y};
    })()`);
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', ...point});
    await send('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...point});
    await send('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...point});
  };
  const back = async () => {
    const previousDocument = await evaluate('performance.timeOrigin');
    const history = await send('Page.getNavigationHistory');
    await send('Page.navigateToHistoryEntry', {entryId: history.entries[history.currentIndex - 1].id});
    await wait('performance.timeOrigin !== ' + previousDocument + ' && location.pathname === "/" && document.readyState === "complete"');
    await wait('document.querySelectorAll("[data-select]").length > 0');
  };
  const key = async (key, code, windowsVirtualKeyCode) => {
    await send('Input.dispatchKeyEvent', {
      type: 'keyDown', key, code, windowsVirtualKeyCode,
      ...(key === 'Enter' ? {text: '\r', unmodifiedText: '\r'} : {})
    });
    await send('Input.dispatchKeyEvent', {type: 'keyUp', key, code, windowsVirtualKeyCode});
  };
  const input = async (id, value) => {
    await evaluate(`(() => { const el = document.getElementById(${JSON.stringify(id)}); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', {bubbles:true})); })()`);
  };
  const noOverflow = async () => {
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Horizontal overflow at ' + width);
  };
  const screenshot = async label => {
    // Capture at the top so sticky headers are positioned correctly in a full-page image.
    await evaluate('window.scrollTo(0, 0); document.activeElement?.blur(); new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    const {cssContentSize} = await send('Page.getLayoutMetrics');
    const {data} = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true, clip: {...cssContentSize, scale: 1}});
    await writeFile(join(profileDir, label + '.png'), Buffer.from(data, 'base64'));
  };
  await navigate('/');
  await wait('document.querySelectorAll("[data-select]").length > 0');
  if (mode === 'before') {
    await screenshot('before-fresh-' + width);
    legacyCss = (await readFile(legacyCssPath)).toString('base64');
    await send('Network.setCacheDisabled', {cacheDisabled: true});
    await send('Fetch.enable', {patterns: [{urlPattern: '*styles.css*'}]});
    await navigate('/');
    await wait('document.querySelectorAll("[data-select]").length > 0');
    await screenshot('before-simulated-stale-css-' + width);
    const diagnosis = await evaluate(`({skipPosition:getComputedStyle(document.querySelector('.skip-link')).position,
      journeyDisplay:getComputedStyle(document.querySelector('.journey')).display,
      ingredientHeight:document.getElementById('ingredient-results').getBoundingClientRect().height})`);
    await send('Fetch.disable');
    legacyCss = null;
    await send('Network.setCacheDisabled', {cacheDisabled: false});
    await navigate('/');
    await wait('document.querySelectorAll("[data-select]").length > 0');
    await click('[data-select="1"]');
    await click('[data-select="2"]');
    await click('#recommend-button');
    await wait('document.querySelectorAll(".recipe-card").length > 0');
    const beforeTitles = await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(el=>el.textContent)');
    await click('.detail-link');
    await wait('document.querySelector(".detail-heading h1") !== null');
    await back();
    await screenshot('before-back-' + width);
    const afterTitles = await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(el=>el.textContent)');
    await writeFile(join(profileDir, 'before-diagnosis-' + width + '.json'), JSON.stringify({
      note: 'Stale CSS is an explicit simulation using the report stylesheet, not a capture of the user browser cache.',
      diagnosis, beforeTitles, afterTitles, mouseClickWorked: beforeTitles.length > 0
    }, null, 2));
    console.log('BEFORE: ' + width + ' ' + JSON.stringify({diagnosis, beforeTitles, afterTitles}));
  } else {
  // A previous release can be cached at the old URLs. Versioned URLs must avoid it.
  legacyCss = Buffer.from('/* stale stylesheet without the v1.1 selectors */').toString('base64');
  await send('Network.setCacheDisabled', {cacheDisabled: true});
  await send('Fetch.enable', {patterns: [{urlPattern: '*styles.css*'}]});
  await navigate('/');
  await wait('document.querySelectorAll("[data-select]").length > 0');
  const assetVersions = await evaluate(`[
    document.querySelector('link[rel=stylesheet]').href,
    document.querySelector('script[src]').src
  ].map(url => new URL(url).searchParams.get('v'))`);
  assert.ok(assetVersions[0] && assetVersions[0] === assetVersions[1], 'CSS and JS must share a release version');
  await send('Fetch.disable');
  legacyCss = null;
  await send('Network.setCacheDisabled', {cacheDisabled: false});
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".journey")).display'), 'flex');
  assert.ok(await evaluate('document.querySelector(".skip-link").getBoundingClientRect().bottom <= 0'), 'Skip link must be hidden before keyboard focus');
  await key('Tab', 'Tab', 9);
  assert.equal(await evaluate('document.activeElement.className'), 'skip-link');
  assert.ok(await evaluate('document.activeElement.getBoundingClientRect().top >= 0'));
  await key('Enter', 'Enter', 13);
  await key('Tab', 'Tab', 9);
  assert.equal(await evaluate('document.activeElement.id'), 'ingredient-search');
  await key('Tab', 'Tab', 9);
  assert.equal(await evaluate('document.activeElement.dataset.select'), '1');
  await key(' ', 'Space', 32);
  assert.equal(await evaluate('document.getElementById("selected-count").textContent'), '1/30');
  assert.equal(await evaluate('document.activeElement.getAttribute("aria-pressed")'), 'true');
  await click('[data-select="1"]');
  await key('Tab', 'Tab', 9);
  assert.equal(await evaluate('document.activeElement.dataset.exclude'), '1');
  await key('Enter', 'Enter', 13);
  assert.equal(await evaluate('document.getElementById("excluded-count").textContent'), '1/30');
  await click('[data-exclude="1"]');
  assert.ok(await evaluate('document.querySelector(".skip-link").getBoundingClientRect().bottom <= 0'), 'Mouse selection must not reveal the skip link');
  assert.equal(await evaluate('document.getElementById("recommend-button").disabled'), true);
  await noOverflow();
  // Every selectable ingredient originates in the real API response.
  const ingredients = await evaluate('fetch("/api/ingredients?limit=50").then(r=>r.json()).then(r=>r.data.items)');
  assert.equal(await evaluate('document.querySelectorAll("[data-select]").length'), ingredients.length);
  await click('[data-select="1"]');
  await click('[data-exclude="1"]');
  assert.equal(await evaluate('document.getElementById("selected-count").textContent'), '0/30');
  assert.equal(await evaluate('document.getElementById("excluded-count").textContent'), '1/30');
  await click('#excluded-ingredients [data-move="1"]');
  await click('[data-select="2"]');
  await click('[data-exclude="7"]');
  await input('ingredient-search', 'cà');
  await wait(`document.getElementById('ingredient-results').getAttribute('aria-busy') === 'false' && document.querySelector('[data-select="2"]') !== null && document.querySelector('[data-select="1"]') === null`);
  await input('ingredient-search', 'khong-co-nguyen-lieu-nay');
  await wait('document.getElementById("ingredient-results").textContent.includes("Không tìm thấy nguyên liệu")');
  await input('ingredient-search', '');
  await wait('document.querySelectorAll("[data-select]").length === ' + ingredients.length);
  await input('max-minutes', '20');
  await input('top-k', '3');
  const beforeSubmit = posts.length;
  await send('Network.emulateNetworkConditions', {offline: false, latency: 200, downloadThroughput: -1, uploadThroughput: -1});
  await click('#recommend-button');
  assert.equal(await evaluate('document.getElementById("ingredient-controls").disabled'), true);
  assert.notEqual(await evaluate('getComputedStyle(document.getElementById("loading")).display'), 'none');
  await click('#recommend-button');
  await wait('document.querySelectorAll(".recipe-card").length > 0');
  await wait('document.getElementById("results-area").getAttribute("aria-busy") === "false"');
  await send('Network.emulateNetworkConditions', {offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1});
  assert.equal(posts.length, beforeSubmit + 1, 'Double submit must not create duplicate requests');
  const payload = JSON.parse(posts.at(-1).postData);
  assert.deepEqual(payload, {ingredient_ids: [1, 2], excluded_ids: [7], top_k: 3, algorithm: 'proposed', max_minutes: 20});
  assert.equal(await evaluate('getComputedStyle(document.getElementById("empty-state")).display'), 'none');
  assert.ok(await evaluate('document.querySelectorAll(".recipe-card").length <= 3'));
  const expected = await evaluate('fetch("/api/recommend", {method:"POST",headers:{"Content-Type":"application/json"},body:' + JSON.stringify(JSON.stringify(payload)) + '}).then(r=>r.json()).then(r=>r.data.items)');
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), expected.map(item => item.title));
  await noOverflow();
  await screenshot('results-' + width);
  if (width < 760) { await resize(320); await noOverflow(); await screenshot('results-320'); await resize(width); }
  const detailPath = await evaluate('document.querySelector(".detail-link").getAttribute("href")');
  const savedTitles = await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)');
  await click('.detail-link');
  await wait('document.querySelector(".detail-heading h1") !== null');
  const recipe = await evaluate('fetch(' + JSON.stringify('/api' + detailPath) + ').then(r=>r.json()).then(r=>r.data)');
  assert.equal(await evaluate('document.querySelector("h1").textContent'), recipe.title);
  assert.equal(await evaluate('document.querySelectorAll(".ingredient-list input").length'), recipe.ingredients.length);
  await click('.ingredient-list input');
  assert.equal(await evaluate('document.querySelector(".ingredient-list input").checked'), true);
  assert.equal(await evaluate('document.querySelector(".instruction-single p").textContent'), recipe.instructions);
  await noOverflow();
  await screenshot('recipe-' + width);
  await back();
  await wait('document.getElementById("selected-count").textContent === "2/30"');
  await screenshot('back-restored-' + width);
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), savedTitles, 'Browser Back must restore recommendation cards');
  assert.equal(await evaluate('document.getElementById("excluded-count").textContent'), '1/30');
  assert.equal(await evaluate('document.getElementById("max-minutes").value'), '20');
  assert.equal(await evaluate('document.getElementById("top-k").value'), '3');
  const validSnapshot = await evaluate('sessionStorage.getItem("goiy-selection-v1")');
  const reloadHome = async () => {
    const previousDocument = await evaluate('performance.timeOrigin');
    await send('Page.reload', {ignoreCache: false});
    await wait('performance.timeOrigin !== ' + previousDocument + ' && document.readyState === "complete" && document.getElementById("ingredient-results")?.getAttribute("aria-busy") === "false"');
  };
  const reloadWithSnapshot = async snapshot => {
    // Inject after the previous document's pagehide saved its own live state.
    const {identifier} = await send('Page.addScriptToEvaluateOnNewDocument', {
      source: 'sessionStorage.setItem("goiy-selection-v1", ' + JSON.stringify(snapshot) + ')'
    });
    try { await reloadHome(); }
    finally { await send('Page.removeScriptToEvaluateOnNewDocument', {identifier}); }
  };
  const beforeReloadPosts = posts.length;
  await reloadHome();
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), savedTitles, 'Reload must restore cached results');
  assert.equal(posts.length, beforeReloadPosts, 'Restoration should not silently rerun the search');
  for (const mutate of [
    `return '{broken';`,
    `return JSON.stringify({version:2,conditions:{available:'invalid'}});`,
    `saved.view.signature = 'different-conditions'; return JSON.stringify(saved);`,
    `saved.conditions.maxMinutes = '1'; return JSON.stringify(saved);`,
    `saved.view.datasetVersion = 'different-dataset'; return JSON.stringify(saved);`,
    `saved.view.items = [{recipe_id:1}]; return JSON.stringify(saved);`,
    `saved.conditions.available.push(999999); return JSON.stringify(saved);`
  ]) {
    const damaged = Function('saved', mutate)(JSON.parse(validSnapshot));
    await reloadWithSnapshot(damaged);
    assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0, 'Invalid or mismatched cache must not render stale results: ' + mutate);
    assert.equal(await evaluate('document.getElementById("ingredient-controls").disabled'), false);
  }
  await reloadWithSnapshot(validSnapshot);
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), savedTitles);
  // Native form validation blocks an invalid filter before any POST.
  const beforeInvalid = posts.length;
  await input('top-k', '21');
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0, 'Changing filters invalidates previous cards immediately');
  assert.equal(await evaluate('JSON.parse(sessionStorage.getItem("goiy-selection-v1")).view'), null);
  await click('#recommend-button');
  await pause(150);
  assert.equal(posts.length, beforeInvalid);
  await input('top-k', '5');
  await input('max-minutes', '1');
  await click('#recommend-button');
  await wait('document.getElementById("result-count").textContent === "0 món"');
  assert.notEqual(await evaluate('getComputedStyle(document.getElementById("empty-state")).display'), 'none');
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0);
  await screenshot('empty-' + width);
  await navigate('/recipes/1');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await back();
  assert.equal(await evaluate('document.getElementById("result-count").textContent'), '0 món');
  assert.ok(await evaluate('document.getElementById("empty-state").textContent.includes("Chưa tìm thấy")'));
  await input('max-minutes', '20');
  // Force an actual browser network failure and verify recovery without a reload.
  await send('Network.emulateNetworkConditions', {offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1});
  await click('#recommend-button');
  await wait('!document.getElementById("message").classList.contains("hidden")');
  assert.ok(await evaluate('document.getElementById("message").textContent.includes("Không thể kết nối")'));
  assert.equal(await evaluate('document.getElementById("ingredient-controls").disabled'), false);
  await send('Network.emulateNetworkConditions', {offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1});
  await navigate('/recipes/1');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await back();
  assert.ok(await evaluate('!document.getElementById("message").classList.contains("hidden") && document.getElementById("message").textContent.includes("Không thể kết nối")'), 'Back must restore the error state and allow retry');
  await click('#recommend-button');
  await wait('document.querySelectorAll(".recipe-card").length > 0');
  await click('#clear-selection');
  assert.equal(await evaluate('document.getElementById("recommend-button").disabled'), true);
  assert.equal(await evaluate('document.getElementById("excluded-count").textContent'), '0/30');
  if (width < 760) { await resize(320); await noOverflow(); await resize(width); }
  await navigate('/recipes/999999');
  await wait('document.querySelector("[role=alert]") !== null');
  assert.ok(await evaluate('document.querySelector("[role=alert]").textContent.includes("Không tìm thấy")'));
  await click('#retry-recipe');
  await wait('document.getElementById("detail").getAttribute("aria-busy") === "false"');
  await noOverflow();
  assert.deepEqual(pageErrors, [], 'Uncaught browser JavaScript errors');
  console.log('PASS: viewport ' + width + '; search, selection, exclusions, filters, ranking, detail, persistence, empty/error/retry, no horizontal overflow.');
  }
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    try { await send('Browser.close', {}, null); } catch { /* Browser may close before acknowledging. */ }
    socket.close();
  }
  if (processHandle.exitCode === null) processHandle.kill();
  for (const request of pending.values()) clearTimeout(request.timer);
}
