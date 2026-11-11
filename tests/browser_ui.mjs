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
const imageMetrics = [];
const posts = [];
const apiRequests = [];
let legacyCss;
let imageCatalogOverride = null;
let imageCatalogFails = false;
let serveImageFixture = false;
// Authored neutral SVG for exercising successful image loading, not a downloaded dish image.
const imageFixture = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600"><rect width="960" height="600" fill="#e5eddc"/><circle cx="480" cy="300" r="120" fill="#61754f"/></svg>').toString('base64');
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
      const url = new URL(request.url);
      const overrideImages = url.pathname === '/static/recipe-images.json' && (imageCatalogOverride !== null || imageCatalogFails);
      const fixtureImage = serveImageFixture && url.pathname === '/static/images/recipes/test-approved-image.svg';
      const method = fixtureImage || overrideImages || legacyCss && url.pathname === '/static/styles.css' && !url.search
        ? 'Fetch.fulfillRequest' : 'Fetch.continueRequest';
      const params = method === 'Fetch.fulfillRequest'
        ? {requestId, responseCode: overrideImages && imageCatalogFails ? 503 : 200,
           responseHeaders: [{name: 'Content-Type', value: fixtureImage ? 'image/svg+xml' : overrideImages ? 'application/json' : 'text/css'}],
           body: fixtureImage ? imageFixture : overrideImages ? Buffer.from(JSON.stringify(imageCatalogOverride || {})).toString('base64') : legacyCss}
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
    if (message.method === 'Network.requestWillBeSent' && message.params.request.url.startsWith(baseUrl + '/api/')) apiRequests.push(message.params.request);
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
    await wait('performance.timeOrigin !== ' + previousDocument + ' && document.readyState === "complete" && location.pathname === ' + JSON.stringify(new URL(path, location.origin).pathname) + ' && location.search === ' + JSON.stringify(new URL(path, location.origin).search));
  };
  const settleRecommendations = async () => {
    await pause(400);
    await wait('document.getElementById("results-area").getAttribute("aria-busy") === "false"');
  };
  const click = async selector => {
    if (selector === '#mode-search') { await navigate('/?view=explore'); await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")=="false"'); return; }
    if (selector === '#mode-recommend') { await navigate('/?view=fridge'); await wait('document.getElementById("ingredient-results").getAttribute("aria-busy")=="false"'); return; }
    if (selector === '#recommend-button' && await evaluate("document.querySelector('[data-user-tab=\"fridge\"]').getAttribute('aria-current') === 'page'")) {
      await settleRecommendations(); return;
    }
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
  const checkImages = async detail => {
    const catalog = await evaluate('window.RecipeImages.ready()');
    const selector = detail ? '#detail .recipe-photo' : '.recipe-card .recipe-photo';
    await wait('document.querySelectorAll(' + JSON.stringify(selector) + ').length > 0');
    const photos = await evaluate(`Array.from(document.querySelectorAll(${JSON.stringify(selector)}), image => ({
      id: Number(image.dataset.recipeId), path: image.getAttribute('src'), alt: image.alt, loading: image.loading,
      placeholder: image.dataset.placeholder, width: image.width, height: image.height,
      link: image.closest('figure').querySelector('a')?.getAttribute('href') || null,
      credit: image.closest('figure').querySelector('figcaption').textContent,
      srcset: image.getAttribute('srcset'), sizes: image.sizes,
      fit: getComputedStyle(image).objectFit, renderedWidth: image.getBoundingClientRect().width,
      viewport: innerWidth
    }))`);
    if (!detail) assert.equal(photos.length, await evaluate('document.querySelectorAll(".recipe-card").length'));
    for (const photo of photos) {
      const entry = catalog.recipes[String(photo.id)];
      const real = entry?.is_placeholder === false;
      assert.equal(photo.path, real ? entry.image_path : '/static/images/recipes/placeholder.svg');
      assert.equal(photo.placeholder, real ? 'false' : 'page');
      assert.ok(photo.alt.trim().length > 0);
      assert.ok(photo.path.startsWith('/static/images/recipes/'), 'Never hotlink images');
      assert.equal(photo.loading, detail ? 'eager' : 'lazy');
      assert.ok(photo.width > 0 && photo.height > 0);
      if (real) {
        assert.equal(photo.srcset, Object.entries(entry.variants || {}).map(([w,p]) => p + ' ' + w + 'w').join(', ') || null);
        if (entry.variants) assert.ok(photo.sizes.length > 0);
        if (entry.source_type === 'project_ai') {
          assert.equal(photo.link, null, 'Project AI credit has no invented source URL');
          assert.equal(photo.credit, entry.source_name);
          assert.equal(photo.fit, 'contain', 'Do not crop project originals');
        } else assert.ok(photo.link && new URL(photo.link).href === new URL(entry.source_url).href);
      }
      assert.ok(photo.renderedWidth <= photo.viewport, 'Image fits viewport');
    }
    await evaluate('document.querySelector(' + JSON.stringify(selector) + ').scrollIntoView({block:"center"})');
    await wait('(() => {const image=document.querySelector(' + JSON.stringify(selector) + ');return image.complete && image.naturalWidth > 0})()');
    const current = await evaluate('document.querySelector(' + JSON.stringify(selector) + ').currentSrc');
    const firstEntry = catalog.recipes[String(photos[0].id)];
    assert.equal(new URL(current).origin, new URL(baseUrl).origin);
    if (firstEntry?.variants) assert.ok(Object.values(firstEntry.variants).includes(new URL(current).pathname));
    imageMetrics.push(...photos.map(photo => ({...photo, current: photo.id === photos[0].id ? current : null})));
    return catalog;
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
  // Exercise the automatic path without clicking submit, on desktop and mobile.
  await navigate('/');
  await wait('document.querySelectorAll("[data-select]").length > 0');
  const beforeRapid = posts.length;
  await evaluate(`(() => {
    document.querySelector('[data-select="1"]').click();
    document.querySelector('[data-select="2"]').click();
    document.querySelector('[data-exclude="7"]').click();
    for (const [id,value] of [['max-minutes','20'],['top-k','3']]) {
      const el=document.getElementById(id); el.value=value; el.dispatchEvent(new Event('input'));
    }
  })()`);
  const selectionScroll = await evaluate('window.scrollY');
  await settleRecommendations();
  assert.equal(posts.length, beforeRapid + 1, 'Rapid changes debounce to a single POST');
  assert.equal(await evaluate('window.scrollY'), selectionScroll, 'Automatic results must not scroll');
  assert.equal(await evaluate('document.getElementById("ingredient-controls").disabled'), false);
  await noOverflow();

  // Deliberately ignore abort in this transport double, then deliver old success
  // and failure after a newer success. Sequence protection must work by itself.
  await evaluate(`(() => {
    window.originalFetch=window.fetch; window.heldRecommendations=[];
    window.fetch=(url,options)=>url==='/api/recommend' ? new Promise((resolve,reject)=> {
      const held={resolve,reject,signal:options.signal}; window.heldRecommendations.push(held);
      originalFetch(url,{...options,signal:undefined}).then(r=>held.response=r);
    }) : originalFetch(url,options);
  })()`);
  await input('top-k', '2');
  await wait('window.heldRecommendations.length === 1 && !!heldRecommendations[0].response');
  await input('top-k', '1');
  assert.equal(await evaluate('heldRecommendations[0].signal.aborted'), true);
  await wait('window.heldRecommendations.length === 2 && !!heldRecommendations[1].response');
  await evaluate('heldRecommendations[1].resolve(heldRecommendations[1].response)');
  await wait('document.getElementById("result-count").textContent === "1 món"');
  const newestSnapshot = await evaluate('sessionStorage.getItem("goiy-selection-v1")');
  await evaluate('heldRecommendations[0].resolve(heldRecommendations[0].response)');
  await pause(100);
  assert.equal(await evaluate('sessionStorage.getItem("goiy-selection-v1")'), newestSnapshot);
  await input('top-k', '2');
  await wait('heldRecommendations.length === 3');
  await input('top-k', '1');
  await wait('heldRecommendations.length === 4 && !!heldRecommendations[3].response');
  await evaluate('heldRecommendations[3].resolve(heldRecommendations[3].response)');
  await wait('document.getElementById("results-area").getAttribute("aria-busy") === "false"');
  await evaluate('heldRecommendations[2].reject(Error("late timeout"))');
  await pause(100);
  assert.equal(await evaluate('document.getElementById("message").classList.contains("hidden")'), true);
  await evaluate('window.fetch=window.originalFetch');
  const beforeUnexclude = posts.length;
  await evaluate('document.querySelector(\'[data-exclude="7"]\').click()');
  await settleRecommendations();
  assert.equal(posts.length, beforeUnexclude + 1);
  assert.deepEqual(JSON.parse(posts.at(-1).postData).excluded_ids, []);
  // The HTTP errors produced by a disconnected or timed out TCP server preserve
  // all selections. Recovery is automatic on the next filter edit.
  for (const [code,status] of [['UPSTREAM_UNAVAILABLE',503],['TIMEOUT',504]]) {
    await evaluate(`window.fetch=(url,options)=>url==='/api/recommend'
      ? Promise.resolve(new Response(JSON.stringify({ok:false,error:{code:${JSON.stringify(code)},message:'TCP unavailable or timeout'}}),{status:${status}}))
      : originalFetch(url,options)`);
    await input('top-k', status === 503 ? '2' : '3');
    await settleRecommendations();
    assert.equal(await evaluate('document.getElementById("message").textContent'), 'TCP unavailable or timeout');
    assert.equal(await evaluate('document.getElementById("selected-count").textContent'), '2/30');
    assert.equal(await evaluate('document.getElementById("ingredient-controls").disabled'), false);
  }
  await evaluate('window.fetch=window.originalFetch');
  await input('top-k', '4');
  // Leave during debounce; Back must finish the pending filter rather than
  // restore a result belonging to an older filter.
  await navigate('/meal-plan');
  await back();
  await settleRecommendations();
  assert.equal(await evaluate('document.getElementById("top-k").value'), '4');
  assert.equal(await evaluate('JSON.parse(sessionStorage.getItem("goiy-selection-v1")).view.kind'), 'results');
  const beforeClear = posts.length;
  await click('#clear-selection');
  await settleRecommendations();
  assert.equal(posts.length, beforeClear, 'Empty available selection must not POST');
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0);
  await input('max-minutes', '');
  await input('top-k', '5');
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
  assert.equal(await evaluate('document.activeElement.getAttribute("aria-pressed")'), 'page');
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
  assert.equal(await evaluate('document.getElementById("ingredient-controls").disabled'), false);
  assert.notEqual(await evaluate('getComputedStyle(document.getElementById("loading")).display'), 'none');
  await click('#recommend-button');
  await wait('document.querySelectorAll(".recipe-card").length > 0');
  await wait('document.getElementById("results-area").getAttribute("aria-busy") === "false"');
  await send('Network.emulateNetworkConditions', {offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1});
  assert.equal(posts.length, beforeSubmit + 1, 'Rapid filter edits must debounce to one request');
  const payload = JSON.parse(posts.at(-1).postData);
  assert.deepEqual(payload, {ingredient_ids: [1, 2], excluded_ids: [7], top_k: 3, algorithm: 'proposed', max_minutes: 20});
  assert.equal(await evaluate('getComputedStyle(document.getElementById("empty-state")).display'), 'none');
  assert.ok(await evaluate('document.querySelectorAll(".recipe-card").length <= 3'));
  const expected = await evaluate('fetch("/api/recommend", {method:"POST",headers:{"Content-Type":"application/json"},body:' + JSON.stringify(JSON.stringify(payload)) + '}).then(r=>r.json()).then(r=>r.data.items)');
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), expected.map(item => item.title));
  await checkImages(false);
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
  await checkImages(true);
  await noOverflow();
  await screenshot('recipe-' + width);
  if (width < 760) { await resize(320); await checkImages(true); await noOverflow(); await screenshot('recipe-320'); await resize(width); }
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
  const legacySnapshot = JSON.parse(validSnapshot);
  legacySnapshot.version = 2;
  const legacyConditions = legacySnapshot.conditions;
  legacySnapshot.conditions = {available: legacyConditions.available, excluded: legacyConditions.excluded,
    maxMinutes: legacyConditions.maxMinutes, topK: legacyConditions.topK};
  legacySnapshot.view.signature = JSON.stringify({ingredient_ids: [...legacyConditions.available].sort((a,b)=>a-b),
    excluded_ids: [...legacyConditions.excluded].sort((a,b)=>a-b), top_k: Number(legacyConditions.topK),
    algorithm: 'proposed', max_minutes: legacyConditions.maxMinutes === '' ? null : Number(legacyConditions.maxMinutes)});
  await reloadWithSnapshot(JSON.stringify(legacySnapshot));
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), savedTitles, 'v1.1.2 cache must upgrade without losing results');
  // Native form validation blocks an invalid filter before any POST.
  const beforeInvalid = posts.length;
  await input('top-k', '21');
  assert.ok(await evaluate('document.querySelectorAll(".recipe-card").length > 0'), 'Keep cards stable while editing filters');
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
  await input('top-k', '4');
  await settleRecommendations();
  await wait('document.querySelectorAll(".recipe-card").length > 0');
  await click('#clear-selection');
  assert.equal(await evaluate('document.getElementById("recommend-button").disabled'), true);
  assert.equal(await evaluate('document.getElementById("excluded-count").textContent'), '0/30');
  if (width < 760) { await resize(320); await noOverflow(); await resize(width); }
  // v1.2: server-side name search without ingredient selection.
  const beforeSearchModePosts = posts.length;
  await click('#mode-search');
  assert.equal(await evaluate('document.getElementById("recommend-button").disabled'), false);
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'false');
  assert.equal(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).display'), 'none');
  assert.equal(await evaluate('document.getElementById("advanced-summary").textContent'), 'Có sẵn: 0 • Loại trừ: 0');
  assert.equal(await evaluate('document.getElementById("max-minutes").closest("#search-filter-slot") !== null'), true);
  assert.equal(posts.length, beforeSearchModePosts, 'Entering search mode must not submit a search automatically');
  await noOverflow();
  await screenshot('search-collapsed-' + width);
  if (width < 760) { await resize(320); await noOverflow(); await screenshot('search-collapsed-320'); await resize(width); }
  await input('max-minutes', '');
  for (const [query, firstRecipe] of [['cá',7],['ca',7],['cà',1],['canh',6],['gà',6],['ga',6]]) {
    await input('recipe-query', query);
    await click('#recommend-button');
    await wait('document.getElementById("results-area").getAttribute("aria-busy") === "false" && document.querySelector(".detail-link") !== null');
    assert.equal(await evaluate('document.querySelector(".detail-link").getAttribute("href")'), '/recipes/' + firstRecipe);
    if (query === 'cá') {
      assert.deepEqual(await evaluate('[...document.querySelectorAll(".recipe-card h3")].map(n=>n.textContent)'), ['Cá basa kho gừng']);
    }
    await noOverflow();
  }
  for (const query of ['đậu phụ', 'dau phu', 'ĐẬU PHỤ'.normalize('NFD')]) {
    await input('recipe-query', query);
    const beforeSearchPosts = posts.length;
    if (query === 'đậu phụ') {
      await click('#recipe-query');
      await key('Enter', 'Enter', 13);
    } else await click('#recommend-button');
    await wait('document.querySelectorAll(".recipe-card").length === 1');
    assert.equal(posts.length, beforeSearchPosts + 1, 'Enter/click must submit exactly one request');
    assert.equal(await evaluate('document.querySelector(".recipe-card h3").textContent'), 'Đậu phụ sốt cà chua');
    assert.equal(await evaluate('document.querySelectorAll(".recipe-card .score").length'), 0, 'Search must not invent a P1 score');
    const request = JSON.parse(posts.at(-1).postData);
    assert.ok(posts.at(-1).url.endsWith('/api/search'));
    assert.deepEqual(request.ingredient_ids, []);
    assert.equal(request.max_missing, null);
  }
  await click('.detail-link');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await back();
  assert.equal(await evaluate('document.getElementById("selected-count").textContent'), '0/30');
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 1, 'Search cache with zero selected ingredients must restore');
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'false', 'Back must restore the collapsed panel');
  await input('recipe-query', '');
  await input('search-limit', '2');
  await click('#recommend-button');
  await wait('document.querySelectorAll(".recipe-card").length === 2');
  assert.equal(await evaluate('document.getElementById("result-count").textContent'), '10 món · 2 trên trang');
  await click('#page-next');
  await wait('document.getElementById("page-label").textContent === "Trang 2 / 5"');
  assert.equal(await evaluate('document.querySelector(".detail-link").getAttribute("href")'), '/recipes/3');
  await click('#page-prev');
  await wait('document.getElementById("page-label").textContent === "Trang 1 / 5"');
  await input('recipe-query', 'khong-co-mon-nay');
  await click('#recommend-button');
  await wait('document.getElementById("result-count").textContent === "0 món · 0 trên trang"');
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0);
  await input('recipe-query', 'trung');
  await input('max-minutes', '20');
  await input('max-missing', '0');
  await input('search-limit', '1');
  const beforeDisclosureRequests = apiRequests.length;
  await click('#advanced-toggle');
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'page');
  assert.notEqual(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).display'), 'none');
  await key('Enter', 'Enter', 13);
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'false');
  await send('Emulation.setEmulatedMedia', {features: [{name: 'prefers-reduced-motion', value: 'reduce'}]});
  await key(' ', 'Space', 32);
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'page');
  assert.equal(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).animationDuration'), '0s');
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".advanced-chevron")).transitionDuration'), '0s');
  await send('Emulation.setEmulatedMedia', {features: []});
  assert.equal(apiRequests.length, beforeDisclosureRequests, 'Opening/closing filters must not fetch or submit');
  await click('[data-select="1"]');
  await click('[data-select="2"]');
  await click('[data-exclude="7"]');
  assert.equal(await evaluate('document.getElementById("advanced-summary").textContent'), 'Có sẵn: 2 • Loại trừ: 1');
  await screenshot('search-expanded-' + width);
  if (width < 760) { await resize(320); await noOverflow(); await screenshot('search-expanded-320'); await resize(width); }
  await click('#advanced-toggle');
  assert.equal(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).display'), 'none');
  await click('#recommend-button');
  await wait('document.querySelectorAll(".recipe-card").length === 1');
  assert.equal(await evaluate('document.querySelector(".detail-link").getAttribute("href")'), '/recipes/1');
  assert.deepEqual(JSON.parse(posts.at(-1).postData).ingredient_ids, [1, 2]);
  assert.deepEqual(JSON.parse(posts.at(-1).postData).excluded_ids, [7]);
  await click('#page-next');
  await wait('document.getElementById("page-label").textContent === "Trang 2 / 2"');
  assert.equal(await evaluate('document.querySelector(".detail-link").getAttribute("href")'), '/recipes/3');
  await checkImages(false);
  await screenshot('search-' + width);
  if (width < 760) { await resize(320); await noOverflow(); await screenshot('search-320'); await resize(width); }
  await click('.detail-link');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await back();
  assert.equal(await evaluate(`document.querySelector('[data-user-tab="explore"]').getAttribute('aria-current')`), 'page');
  assert.equal(await evaluate('document.getElementById("recipe-query").value'), 'trung');
  assert.equal(await evaluate('document.getElementById("max-missing").value'), '0');
  assert.equal(await evaluate('document.getElementById("page-label").textContent'), 'Trang 2 / 2');
  assert.equal(await evaluate('document.querySelector(".detail-link").getAttribute("href")'), '/recipes/3');
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'false');
  const searchSnapshot = await evaluate('sessionStorage.getItem("goiy-selection-v1")');
  await reloadHome();
  assert.equal(await evaluate('document.getElementById("page-label").textContent'), 'Trang 2 / 2');
  assert.equal(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).display'), 'none');
  const beforeOpenRequests = apiRequests.length;
  await click('#advanced-toggle');
  assert.equal(apiRequests.length, beforeOpenRequests);
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 1, 'Opening filters must retain valid results');
  await click('.detail-link');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await back();
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'true', 'Back must restore the open panel');
  assert.equal(await evaluate('document.getElementById("page-label").textContent'), 'Trang 2 / 2');
  await reloadHome();
  assert.equal(await evaluate('document.getElementById("advanced-toggle").getAttribute("aria-expanded")'), 'true', 'Reload must restore the open panel');
  assert.equal(await evaluate('document.getElementById("advanced-summary").textContent'), 'Có sẵn: 2 • Loại trừ: 1');
  await click('#advanced-toggle');
  const wrongSearch = JSON.parse(searchSnapshot);
  wrongSearch.conditions.recipeQuery = 'dau phu';
  await reloadWithSnapshot(JSON.stringify(wrongSearch));
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0);
  const wrongPage = JSON.parse(searchSnapshot);
  wrongPage.conditions.offset = 0;
  await reloadWithSnapshot(JSON.stringify(wrongPage));
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0, 'Cached items for another page must not render');
  await reloadWithSnapshot(searchSnapshot);
  await input('recipe-query', 'đậu phụ');
  assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0);
  assert.equal(await evaluate('JSON.parse(sessionStorage.getItem("goiy-selection-v1")).conditions.offset'), 0);
  const beforeModeSwitchPosts = posts.length;
  for (let cycle = 0; cycle < 4; cycle++) {
    await click('#mode-recommend');
    assert.notEqual(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).display'), 'none');
    assert.equal(await evaluate('getComputedStyle(document.getElementById("advanced-toggle")).display'), 'none');
    assert.equal(await evaluate('document.getElementById("max-minutes").closest("#recommend-filter-slot") !== null'), true);
    await click('#mode-search');
    assert.equal(await evaluate('getComputedStyle(document.getElementById("ingredient-panel")).display'), 'none');
    assert.equal(await evaluate('document.getElementById("selected-count").textContent'), '2/30');
    assert.equal(await evaluate('document.getElementById("excluded-count").textContent'), '1/30');
    assert.equal(await evaluate('document.querySelectorAll(".recipe-card").length'), 0);
  }
  assert.ok(posts.length >= beforeModeSwitchPosts, 'Navigation may refresh recommendations; it must not lose the view');
  await click('#mode-recommend');
  await click('#recommend-button');
  await wait('document.querySelectorAll(".recipe-card .score").length > 0');
  await noOverflow();
  await navigate('/recipes/999999');
  await wait('document.querySelector("[role=alert]") !== null');
  assert.ok(await evaluate('document.querySelector("[role=alert]").textContent.includes("Không tìm thấy")'));
  await click('#retry-recipe');
  await wait('document.getElementById("detail").getAttribute("aria-busy") === "false"');
  await noOverflow();
  // Use actual local B2 assets in both card modes and on the detail page.
  await navigate('/');
  // Buttons can exist while restoreSelection() still has a queued scroll frame.
  // Settle that frame before measuring coordinates for a real mouse click.
  await wait('document.getElementById("ingredient-results").getAttribute("aria-busy") === "false" && document.querySelectorAll("[data-select]").length > 0');
  await wait(`document.getElementById("selected-count").textContent === "2/30" && document.querySelector('[data-exclude="7"]')?.getAttribute("aria-pressed") === "true"`);
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  await click('[data-exclude="7"]');
  await wait(`document.getElementById("excluded-count").textContent === "0/30" && document.querySelector('[data-exclude="7"]').getAttribute("aria-pressed") === "false"`);
  await click('#mode-search');
  await wait(`document.querySelector('[data-user-tab="explore"]').getAttribute('aria-current') === "page" && !document.getElementById("recipe-query").disabled`);
  await input('recipe-query', 'dau phu');
  await input('max-missing', '');
  await input('max-minutes', '');
  const beforeTofuSearch = posts.length;
  await click('#recommend-button');
  await wait('document.getElementById("results-area").getAttribute("aria-busy") === "false" && document.getElementById("result-count").textContent !== ""', 'Tofu search must finish before checking its results');
  assert.equal(posts.length, beforeTofuSearch + 1, 'Tofu search must issue exactly one request');
  assert.equal(new URL(posts.at(-1).url).pathname, '/api/search');
  const tofuPayload = JSON.parse(posts.at(-1).postData);
  assert.deepEqual(tofuPayload.excluded_ids, [], 'Remove garlic before expecting a tofu result');
  assert.equal(tofuPayload.query, 'dau phu');
  assert.equal(tofuPayload.max_minutes, null);
  assert.equal(tofuPayload.max_missing, null);
  assert.equal(await evaluate('document.querySelector(".detail-link")?.getAttribute("href")'), '/recipes/4');
  await checkImages(false);
  assert.equal(await evaluate('document.querySelector(".recipe-photo").dataset.placeholder'), 'false');
  await screenshot('photo-search-' + width);
  await click('.detail-link');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await checkImages(true);
  await screenshot('photo-recipe-' + width);
  if (width < 760) { await resize(320); await noOverflow(); await screenshot('photo-recipe-320'); await resize(width); }
  await back();
  await checkImages(false);
  await reloadHome();
  await checkImages(false);
  await click('#mode-recommend');
  await input('max-minutes', '20');
  await input('top-k', '5');
  await click('[data-select="5"]');
  await click('#recommend-button');
  await wait('document.querySelector(\'[data-recipe-media][data-recipe-id="4"]\') !== null');
  await checkImages(false);
  await noOverflow();
  await screenshot('photo-results-' + width);
  if (width < 760) { await resize(320); await checkImages(false); await noOverflow(); await screenshot('photo-results-320'); await resize(width); }
  // Exercise an approved-image entry with a local test fixture; no claim of actual source approval.
  serveImageFixture = true;
  imageCatalogOverride = {recipes: {'1': {recipe_id: 1, is_placeholder: false,
    image_path: '/static/images/recipes/test-approved-image.svg', alt: 'Neutral AI illustration test fixture',
    source_url: 'https://example.invalid/test-source', source_name: 'Test fixture', generated_ai: true,
    variants: {'960': '/static/images/recipes/test-approved-image.svg'}}}};
  await send('Fetch.enable', {patterns: [{urlPattern: '*recipe-images.json*'}, {urlPattern: '*test-approved-image.svg'}]});
  await reloadWithSnapshot(validSnapshot);
  await checkImages(false);
  assert.ok(await evaluate('document.querySelector(\'[data-recipe-media][data-recipe-id="1"] figcaption\').textContent.includes("Minh họa AI")'));
  await click('[data-recipe-media][data-recipe-id="1"] + .recipe-top ~ .detail-link');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await checkImages(true);
  await back();
  await checkImages(false);
  await reloadHome();
  await checkImages(false);
  await reloadWithSnapshot(searchSnapshot);
  await click('#page-prev');
  await wait('document.getElementById("page-label").textContent === "Trang 1 / 2"');
  await checkImages(false);
  await send('Fetch.disable');
  imageCatalogOverride = null;
  serveImageFixture = false;
  // Missing metadata and missing/cross-origin photos must fall back without changing recipe data.
  for (const override of [
    {recipes: {}},
    {recipes: null},
    {recipes: {'1': {recipe_id: 2, is_placeholder: false, image_path: '/static/images/recipes/placeholder.svg'}}},
    {recipes: {'1': {recipe_id: 1, is_placeholder: false, image_path: '/static/images/recipes/test-missing-image.webp',
      source_url: 'https://example.invalid/test-source', source_name: 'Test fixture', alt: 'Test missing photo'}}},
    {recipes: {'1': {recipe_id: 1, is_placeholder: false, image_path: '/static/images/recipes/test-missing-image.webp',
      source_type: 'project_ai', generated_ai: true, source_url: null, source_name: 'Project AI fixture'}}},
    {recipes: {'1': {recipe_id: 1, is_placeholder: false, image_path: '/static/images/recipes/test-approved-image.svg',
      source_type: 'unknown', generated_ai: true, source_url: null, source_name: 'Untrusted missing source'}}},
    {recipes: {'1': {recipe_id: 1, is_placeholder: false, image_path: 'https://example.invalid/never-hotlink.webp',
      source_url: 'https://example.invalid/test-source', source_name: 'Test fixture'}}}
  ]) {
    imageCatalogOverride = override;
    await send('Fetch.enable', {patterns: [{urlPattern: '*recipe-images.json*'}]});
    await navigate('/recipes/1');
    await wait('document.querySelector(".detail-heading h1") !== null');
    await evaluate('window.RecipeImages.ready()');
    await wait('document.querySelector(".detail-media img")?.dataset.placeholder === "true" && document.querySelector(".detail-media img").complete && document.querySelector(".detail-media img").naturalWidth > 0');
    assert.equal(await evaluate('document.querySelector(".detail-media img").getAttribute("src")'), '/static/images/recipes/placeholder.svg');
    assert.equal(await evaluate('document.querySelector(".detail-media img").getAttribute("srcset")'), null);
    await send('Fetch.disable');
    imageCatalogOverride = null;
  }
  imageCatalogFails = true;
  await send('Fetch.enable', {patterns: [{urlPattern: '*recipe-images.json*'}]});
  await navigate('/recipes/1');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await checkImages(true);
  await send('Fetch.disable');
  imageCatalogFails = false;
  // Component-level coverage for every real catalog ID, independent of the 10-recipe SQLite fixture.
  // This only mounts image metadata; it does not invent recipes or call a modified API.
  await navigate('/recipes/1');
  await wait('document.querySelector(".detail-heading h1") !== null');
  await evaluate(`(async () => {
    const catalog = await window.RecipeImages.ready();
    const root = document.createElement('section'); root.id = 'catalog-image-check';
    for (const entry of Object.values(catalog.recipes)) {
      const figure = document.createElement('figure'); figure.dataset.recipeMedia = '';
      figure.dataset.recipeId = String(entry.recipe_id); figure.dataset.recipeTitle = entry.alt;
      root.append(figure);
    }
    document.body.append(root); window.RecipeImages.mount(root);
    await Promise.resolve();
    root.querySelectorAll('img').forEach(image => {image.loading = 'eager'; image.sizes = '320px';});
  })()`);
  await wait('document.querySelectorAll("#catalog-image-check img").length === 50 && [...document.querySelectorAll("#catalog-image-check img")].every(image => image.complete && image.naturalWidth > 0 && image.dataset.placeholder === "false")');
  assert.equal(await evaluate('document.querySelectorAll(\'#catalog-image-check [data-source-type="project_ai"]\').length'), 15);
  assert.ok(await evaluate('[...document.querySelectorAll("#catalog-image-check img")].every(image => new URL(image.currentSrc).pathname.includes("recipe-" + image.dataset.recipeId.padStart(2,"0") + "-"))'));
  await evaluate('document.getElementById("catalog-image-check").remove()');
  await writeFile(join(profileDir, 'image-metrics-' + width + '.json'), JSON.stringify(imageMetrics, null, 2));
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
