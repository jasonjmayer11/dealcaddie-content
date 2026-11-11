#!/usr/bin/env node
// DealCaddie narrated demo — real screen recording of one analysis.
// Usage: node scripts/record_demo.js "<zillow url>" <outdir>
// Env:   DC_EMAIL / DC_PASSWORD (content account)
//
// Films the phone-sized app while it: takes the pasted link → loads the analysis (score) →
// shows the auto-filled rent/taxes/insurance → cash flow by strategy → rehab estimate from photos.
// Each section is held on screen generously; narrate.py trims every section to its voice line.
//
// Writes to <outdir>:  screen.webm (raw recording), markers.json (section start/end, seconds),
//                      data.json (numbers the script talks about)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const listing = process.argv[2];
const outdir = process.argv[3];
if (!listing || !outdir) { console.error('usage: record_demo.js <listing> <outdir>'); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });
const BASE = 'https://www.dealcaddie.ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = f => path.join(outdir, f);
const HOLD = 9000;
const STORY = process.env.STORY ? JSON.parse(fs.readFileSync(process.env.STORY, 'utf8')) : null;
const SEARCH_INTRO = !STORY || STORY.start === 'search';
const NO_ANALYSIS = !!STORY && STORY.start === 'none';     // feature lives outside an analysis (Deals, Pipeline…)                    // ms each section stays on screen (VO lines are ~4-8s)

(async () => {
  const browser = await chromium.launch();
  // ---- log in (separate, unrecorded context) ----
  const lctx = await browser.newContext();
  const lp = await lctx.newPage();
  await lp.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await lp.fill('#email', process.env.DC_EMAIL || '');
  await lp.fill('#password', process.env.DC_PASSWORD || '');
  await Promise.all([lp.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {}),
                     lp.click('form button[type="submit"]')]);
  if (/\/login/.test(lp.url())) throw new Error('Login failed — check DC_EMAIL / DC_PASSWORD');
  const storageState = await lctx.storageState();
  await lctx.close();

  // ---- recorded phone context ----
  const vw = 430, vh = 932;
  const ctx = await browser.newContext({
    storageState, viewport: { width: vw, height: vh }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  });
  const page = await ctx.newPage();
  const t0 = Date.now();
  // Crisp capture: Playwright's recordVideo films at 1x CSS pixels. The DevTools screencast gives
  // device pixels (2x), one JPEG per painted frame with a timestamp — stitched into video below.
  const fdir = out('frames'); fs.mkdirSync(fdir, { recursive: true });
  const frames = [];
  const cdp = await ctx.newCDPSession(page);
  cdp.on('Page.screencastFrame', async (f) => {
    const file = path.join(fdir, `f${String(frames.length).padStart(5, '0')}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
    frames.push({ t: f.metadata.timestamp - t0 / 1000, file });
    cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: vw * 2, maxHeight: vh * 2, everyNthFrame: 1 });
  const now = () => (Date.now() - t0) / 1000;
  const markers = {};
  const mark = (k, edge) => { (markers[k] = markers[k] || {})[edge] = +now().toFixed(2); console.log(`${k}.${edge} @ ${markers[k][edge]}s`); };

  // smooth-scroll the smallest visible element matching `re` to the middle of the screen
  const scrollTo = async (re, block = 'center') => page.evaluate(([src, blk]) => {
    const rx = new RegExp(src, 'i'); let best = null;
    for (const el of document.querySelectorAll('body *')) {
      if (!el.offsetParent || !rx.test(el.textContent || '')) continue;
      if (!best || (el.textContent.length < best.textContent.length)) best = el;
    }
    if (best) best.scrollIntoView({ behavior: 'smooth', block: blk });
    return !!best;
  }, [re, block]).catch(() => false);
  const clickTab = async (label) => {
    const t = page.getByText(label, { exact: true }).first();
    if (await t.isVisible().catch(() => false)) { await t.click().catch(() => {}); await sleep(900); return true; }
    return false;
  };
  const hideIcons = () => page.evaluate(() => {
    for (const el of document.querySelectorAll('body *')) {
      if (el.children.length) continue;
      const t = (el.textContent || '').trim();
      if (t.length === 1 && /[ℹ①-⓿]/.test(t)) el.style.visibility = 'hidden';
    }
  }).catch(() => {});

  // ---- 1. paste the link ----
  await page.goto(`${BASE}/analyze`, { waitUntil: 'networkidle', timeout: 60000 });
  await sleep(800);
  if (SEARCH_INTRO) { mark('intro', 'start'); await sleep(3200); mark('intro', 'end'); }   // sit on the search page first
  if (SEARCH_INTRO) mark('paste', 'start');
  if (!NO_ANALYSIS) {
  const input = page.locator('input[name="address"]').first();
  await input.click(); await sleep(600);
  const sheet = page.locator('.dcs-sheet.on');
  const inSheet = await sheet.isVisible().catch(() => false);
  const box = inSheet ? sheet.locator('input[type="text"]').first() : input;
  await box.fill(listing); await sleep(900);
  if (inSheet) {
    await box.press('Enter');
    const ok = await page.waitForSelector('#live-score-num', { state: 'attached', timeout: 5000 }).then(() => true).catch(() => false);
    if (!ok) { const opt = sheet.locator('[role="listbox"] [role="option"], [role="listbox"] li, [role="listbox"] button').first();
               if (await opt.isVisible().catch(() => false)) await opt.click(); }
  } else {
    await page.locator('button[type="submit"]').first().click();
  }
  await page.waitForSelector('#live-score-num', { state: 'attached', timeout: 90000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(1200);
  if (SEARCH_INTRO) mark('paste', 'end');
  }

  // insurance sanity fix, same rule as the reels (typed into the app's own field so it recalculates)
  const insFix = await page.evaluate(() => {
    const num = id => +String((document.getElementById(id) || {}).value || '').replace(/[^0-9.]/g, '') || 0;
    const price = num('fin-price'), ins = num('fin-ins');
    const units = Math.max(1, document.querySelectorAll('[id^="mf-unit-box-"]').length);
    if (!price || !ins || ins >= Math.max(0.005 * price / 12, 50 * units)) return null;
    const target = Math.round(Math.max(0.0075 * price / 12, 70 * units) / 5) * 5;
    const el = document.getElementById('fin-ins'); el.value = String(target);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return { from: ins, to: target };
  }).catch(() => null);
  if (insFix) console.log('insurance adjusted:', JSON.stringify(insFix));
  // start the photo rehab estimate now so it is ready by the time we get there
  if (!STORY || STORY.rehab) await page.evaluate(() => { if (typeof autoAnalyzeCondition === 'function') autoAnalyzeCondition(); }).catch(() => {});
  await hideIcons();

  // gold focus ring on whatever the voice is talking about; scroll it clear of the sticky tab bar
  const focus = (sel, pick = 'self', setScope = false) => page.evaluate(([sel, pick, setScope]) => {
    const root = window.__demoScope || document;
    document.querySelectorAll('[data-demo-focus]').forEach(e => { e.style.boxShadow = ''; e.removeAttribute('data-demo-focus'); });
    let el = null;
    if (sel.startsWith('text:')) {
      const rx = new RegExp(sel.slice(5), 'i');
      for (const e of root.querySelectorAll('*')) {
        if (!e.offsetParent || !rx.test(e.textContent || '')) continue;
        if (!el || e.textContent.length < el.textContent.length) el = e;
      }
    } else {
      const vis = e => e.offsetParent !== null && e.getBoundingClientRect().height > 0;
      el = [...document.querySelectorAll(sel)].find(vis) || null;     // first *visible* match (desktop twins are hidden)
    }
    if (!el) return false;
    if (pick === 'card') {                       // the section card: climb until it's a real block (≥ 280px tall)
      let c = el;
      while (c.parentElement && c.parentElement !== document.body && c.getBoundingClientRect().height < 280) c = c.parentElement;
      el = c;
    }
    if (pick === 'parent2') el = (el.parentElement && el.parentElement.parentElement) || el;
    if (pick === 'parent') el = el.parentElement || el;
    if (pick === 'row') el = el.closest('tr') || el.parentElement || el;
    window.__demoFocus = el;
    if (setScope) window.__demoScope = el;
    // scroll whichever element actually scrolls (signed-in pages scroll an inner shell, not the window)
    let sc = el.parentElement;
    while (sc && sc !== document.body) {
      const cs = getComputedStyle(sc);
      if (/(auto|scroll)/.test(cs.overflowY) && sc.scrollHeight > sc.clientHeight + 20) break;
      sc = sc.parentElement;
    }
    const r = el.getBoundingClientRect();
    if (sc && sc !== document.body) {
      const sr = sc.getBoundingClientRect();
      const top = sc.scrollTop + (r.top - sr.top) - Math.max(130, (sc.clientHeight - r.height) / 2);
      sc.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    } else {
      const y = window.scrollY + r.top - Math.max(150, (window.innerHeight - r.height) / 2);
      window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
    }
    el.style.transition = 'box-shadow .35s ease'; el.style.borderRadius = el.style.borderRadius || '12px';
    el.setAttribute('data-demo-focus', '1');
    setTimeout(() => { el.style.boxShadow = '0 0 0 3px rgba(201,168,76,.95), 0 0 0 9px rgba(201,168,76,.22)'; }, 450);
    return true;
  }, [sel, pick, setScope]).catch(() => false);

  const vars = {};
  if (STORY) {
    // ---- storyboard: each scene = actions, a hold, and numbers grabbed from the focused element ----
    for (const sc of STORY.scenes) {
      for (const act of sc.do || []) {
        if (act.tab) { await clickTab(act.tab); await hideIcons(); }
        if (act.top) await page.evaluate(() => { window.scrollTo({ top: 0, behavior: 'smooth' });
          document.querySelectorAll('*').forEach(e => { if (e.scrollTop > 0 && /(auto|scroll)/.test(getComputedStyle(e).overflowY)) e.scrollTo({ top: 0, behavior: 'smooth' }); }); });
        if (act.goto) {
          let url = act.goto;
          if (url.includes('{ids')) {                       // best-scoring saved deals from the Pipeline, for /compare
            const ids = await page.evaluate(() => [...new Set([...document.querySelectorAll('a[href*="/analysis/"]')]
              .map(a => (a.getAttribute('href').match(/\/analysis\/(\d+)/) || [])[1]).filter(Boolean))]).catch(() => []);
            url = url.replace('{ids3}', ids.slice(0, 3).join(',')).replace('{ids2}', ids.slice(0, 2).join(','));
            console.log('compare ids', url);
          }
          await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {}); await hideIcons();
        }
        if (act.click) {
          const t = act.click.startsWith('text:') ? page.getByText(new RegExp(act.click.slice(5), 'i')).first() : page.locator(act.click).first();
          await t.scrollIntoViewIfNeeded().catch(() => {}); await t.click({ timeout: 5000 }).catch(e => console.log('click miss', act.click));
          await sleep(900);
        }
        if (act.fill) { const [sel, val] = act.fill; const el = page.locator(sel).first();
          await el.click().catch(() => {}); await el.fill(''); await el.type(String(val), { delay: 90 }).catch(() => {}); await sleep(600); }
        if (act.unscope) await page.evaluate(() => { window.__demoScope = null; });
        if (act.focus) { const ok = await focus(act.focus, act.pick || 'self', !!act.scope); console.log(`focus ${act.focus}: ${ok}`); }
        if (act.press) { await page.keyboard.press(act.press).catch(() => {}); await sleep(800); }
        if (act.typein) {                                     // type into whatever field is focused/open, like a person
          const [sel, val] = act.typein; const el = page.locator(sel).first();
          await el.click().catch(() => {}); await sleep(400);
          const target = (await page.locator('.dcs-sheet.on input[type="text"]').first().isVisible().catch(() => false))
            ? page.locator('.dcs-sheet.on input[type="text"]').first() : el;
          await target.type(String(val), { delay: 55 }).catch(e => console.log('typein miss', e.message));
          await sleep(500);
        }
        if (act.wait) await sleep(act.wait);
        if (act.waitgone) {                                   // wait for async sections (AI) to finish loading
          await page.waitForFunction(t => !document.body.innerText.includes(t), act.waitgone, { timeout: 90000, polling: 500 })
            .catch(() => console.log('still loading:', act.waitgone));
          await sleep(800);
        }
      }
      mark(sc.id, 'start');
      await sleep(900);                                   // let the smooth scroll land, then note where the subject is
      if (sc.zoom !== false) {
        const rect = await page.evaluate(() => { const e = window.__demoFocus; if (!e) return null;
          const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }).catch(() => null);
        if (rect) markers[sc.id].rect = rect.map(x => +x.toFixed(1));
      }
      await sleep(Math.max(0, (sc.hold || 7) * 1000 - 900));
      // grab numbers for the voice from the focused element's text (or the whole page)
      const txt = await page.evaluate(() => (window.__demoFocus || document.body).innerText || '').catch(() => '');
      const pageTxt = await page.evaluate(() => document.body.innerText).catch(() => '');
      for (const [k, rx] of Object.entries(sc.grab || {})) {
        const m = (txt.match(new RegExp(rx, 'i')) || pageTxt.match(new RegExp(rx, 'i')));
        if (m) vars[k] = (m[1] || m[0]).trim();
      }
      mark(sc.id, 'end');
    }
    // closing shot for the spoken wrap-up: glide back to the top of the page
    await page.evaluate(() => {
      document.querySelectorAll('[data-demo-focus]').forEach(e => { e.style.boxShadow = ''; e.removeAttribute('data-demo-focus'); });
      window.scrollTo({ top: 0, behavior: 'smooth' });
      document.querySelectorAll('*').forEach(e => { if (e.scrollTop > 0 && /(auto|scroll)/.test(getComputedStyle(e).overflowY)) e.scrollTo({ top: 0, behavior: 'smooth' }); });
    }).catch(() => {});
    mark('wrap', 'start'); await sleep(7000); mark('wrap', 'end');
    console.log('vars', JSON.stringify(vars));
  } else {
  // ---- 2. score: the property card at the top ----
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  mark('score', 'start');
  await sleep(1200);
  await focus('#results-top'); await sleep(HOLD); mark('score', 'end');

  // ---- 3. auto-filled inputs: rent (RentCast) → taxes + insurance ----
  mark('auto', 'start');
  const nUnits = await page.evaluate(() => [...document.querySelectorAll('[id^="mf-unit-box-"]')].filter(e => e.offsetParent !== null || e.closest('#mf-units-grid')).length).catch(() => 0);
  console.log('units on page:', nUnits);
  if (nUnits >= 2) {
    for (const tab of ['Financials', 'Cashflow', 'All']) {
      if (await page.locator('#mf-units-grid').isVisible().catch(() => false)) break; await clickTab(tab);
    }
    await focus('#mf-units-grid');
  } else {
    await clickTab('Cashflow'); await hideIcons();
    const okR = (await focus('#live-ltr-rent', 'parent2')) || (await focus('text:^\\s*Long-Term Rental\\s*$', 'card'));
    console.log('focus rent:', okR);
  }
  // the LTR card shows the RentCast rent next to expenses (taxes + insurance included) — one steady shot
  await sleep(HOLD);
  mark('auto', 'end');

  // ---- 4. cash flow by strategy ----
  (await clickTab('Cashflow')) || (await clickTab('All'));
  await hideIcons();
  mark('strategies', 'start');
  await focus('text:^\\s*Cashflow by Strategy', 'card');
  await sleep(HOLD); mark('strategies', 'end');

  // ---- 5. rehab estimate from photos ----
  let gotRehab = await page.waitForSelector('#cond-rehab', { state: 'attached', timeout: 45000 }).then(() => true).catch(() => false);
  if (!gotRehab) {                     // cached report without an estimate, or the first call raced the page — ask again
    console.log('rehab: retrying');
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find(x => /estimate rehab from these photos/i.test(x.textContent || ''));
      if (b) b.click(); else if (typeof autoAnalyzeCondition === 'function') autoAnalyzeCondition();
    }).catch(() => {});
    gotRehab = await page.waitForSelector('#cond-rehab', { state: 'attached', timeout: 90000 }).then(() => true).catch(() => false);
  }
  console.log('rehab ready:', gotRehab);
  for (const tab of ['AI Take', 'Financials', 'Comps', 'All', 'Cashflow']) {
    if (await page.locator('#cond-rehab').isVisible().catch(() => false)) break;
    await clickTab(tab);
  }
  mark('rehab', 'start');
  await focus('#cond-rehab');
  await sleep(HOLD); mark('rehab', 'end');

  // ---- 6. wrap: glide back up to the finished analysis while the voice sums it up ----
  await page.evaluate(() => {
    document.querySelectorAll('[data-demo-focus]').forEach(e => { e.style.boxShadow = ''; e.removeAttribute('data-demo-focus'); });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }).catch(() => {});
  mark('wrap', 'start'); await sleep(HOLD); mark('wrap', 'end');

  }

  // ---- numbers for the script ----
  const data = await page.evaluate(() => {
    const v = id => { const e = document.getElementById(id); return e ? String(e.value || '').replace(/[^0-9.]/g, '') : ''; };
    const tx = id => { const e = document.getElementById(id); return e ? e.textContent.replace(/\s+/g, ' ').trim() : ''; };
    const strategies = {};
    for (const k of ['ltr', 'mtr', 'str', 's8', 'hh', 'brrrr']) strategies[k] = tx('tab-cf-' + k);
    const units = [...document.querySelectorAll('[id^="mf-unit-box-"]')].map(b => ((b.querySelector('input') || {}).value || '').replace(/[^0-9.]/g, '')).filter(r => +r > 0);
    const body = document.body.innerText;
    const el = document.getElementById('cond-rehab'); const spans = el ? el.querySelectorAll('span') : [];
    return {
      score: tx('live-score-num'), price: v('fin-price'), ltrRent: v('ltr-rent'), tax: v('fin-tax'), ins: v('fin-ins'),
      units, strategies, strRestricted: /STR Restricted Market/i.test(body),
      cityLine: (body.match(/\n([A-Z][A-Za-z .'-]+, [A-Z]{2} \d{5})/) || [])[1] || '',
      rehab: el ? { range: (spans[0] || {}).textContent || '', level: (spans[1] || {}).textContent || '' } : null,
    };
  });
  data.insAdjusted = insFix;
  data.vars = vars;
  console.log('data', JSON.stringify(data));
  fs.writeFileSync(out('data.json'), JSON.stringify(data, null, 2));
  fs.writeFileSync(out('markers.json'), JSON.stringify(markers, null, 2));

  await sleep(500);
  await cdp.send('Page.stopScreencast').catch(() => {});
  await ctx.close(); await browser.close();
  // stitch: each frame lasts until the next one arrives (the screencast only sends changes)
  if (!frames.length) throw new Error('screencast produced no frames');
  const lines = ['ffconcat version 1.0'];
  frames.forEach((f, i) => {
    const start = i === 0 ? 0 : f.t;
    const next = i + 1 < frames.length ? frames[i + 1].t : f.t + 1.0;
    lines.push(`file '${path.resolve(f.file)}'`, `duration ${Math.max(0.001, next - start).toFixed(3)}`);
  });
  lines.push(`file '${path.resolve(frames[frames.length - 1].file)}'`);
  fs.writeFileSync(out('frames.txt'), lines.join('\n'));
  require('child_process').execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', out('frames.txt'),
    '-vf', 'fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-crf', '14', '-pix_fmt', 'yuv420p', out('screen.mp4')]);
  console.log(`recorded ${frames.length} frames → ${out('screen.mp4')}`);
})().catch(e => { console.error(e); process.exit(1); });
