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
const HOLD = 9000;                    // ms each section stays on screen (VO lines are ~4-8s)

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
  mark('paste', 'start');
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
  mark('paste', 'end');

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
  await page.evaluate(() => { if (typeof autoAnalyzeCondition === 'function') autoAnalyzeCondition(); }).catch(() => {});
  await hideIcons();

  // gold focus ring on whatever the voice is talking about; scroll it clear of the sticky tab bar
  const focus = (sel, pick = 'self') => page.evaluate(([sel, pick]) => {
    document.querySelectorAll('[data-demo-focus]').forEach(e => { e.style.boxShadow = ''; e.removeAttribute('data-demo-focus'); });
    let el = null;
    if (sel.startsWith('text:')) {
      const rx = new RegExp(sel.slice(5), 'i');
      for (const e of document.querySelectorAll('body *')) {
        if (!e.offsetParent || !rx.test(e.textContent || '')) continue;
        if (!el || e.textContent.length < el.textContent.length) el = e;
      }
    } else {
      const vis = e => e.offsetParent !== null && e.getBoundingClientRect().height > 0;
      el = [...document.querySelectorAll(sel)].find(vis) || null;     // first *visible* match (desktop twins are hidden)
    }
    if (!el) return false;
    if (pick === 'card') el = el.closest('.card, [class*="rounded-2xl"], [class*="rounded-xl"]') || el.parentElement || el;
    if (pick === 'parent2') el = (el.parentElement && el.parentElement.parentElement) || el;
    const r = el.getBoundingClientRect();
    const y = window.scrollY + r.top - Math.max(150, (window.innerHeight - r.height) / 2);
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
    el.style.transition = 'box-shadow .35s ease'; el.style.borderRadius = el.style.borderRadius || '12px';
    el.setAttribute('data-demo-focus', '1');
    setTimeout(() => { el.style.boxShadow = '0 0 0 3px rgba(201,168,76,.95), 0 0 0 9px rgba(201,168,76,.22)'; }, 450);
    return true;
  }, [sel, pick]).catch(() => false);

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
