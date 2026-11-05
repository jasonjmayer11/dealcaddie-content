#!/usr/bin/env node
// DealCaddie reel recorder.
// Usage: node scripts/record.js "<zillow url or address>" <outdir>
// Env:   DC_EMAIL / DC_PASSWORD  (content account; falls back to guest if unset)
//
// Produces in <outdir>:
//   raw.webm     full screen recording (540x960, upscaled later)
//   marks.json   timestamps (seconds) of each beat, aligned to the video
//   data.json    numbers scraped from the finished analysis
//   photo.jpg    the listing's hero photo, if one rendered
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const listing = process.argv[2];
const outdir = process.argv[3];
if (!listing || !outdir) { console.error('usage: record.js <listing> <outdir>'); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });

const BASE = 'https://www.dealcaddie.ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();

  // ---- 1. log in on a separate, unrecorded context, then reuse its cookies ----
  let storageState;
  if (process.env.DC_EMAIL && process.env.DC_PASSWORD) {
    const lctx = await browser.newContext();
    const lp = await lctx.newPage();
    await lp.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await lp.fill('#email', process.env.DC_EMAIL);
    await lp.fill('#password', process.env.DC_PASSWORD);
    await lp.check('#remember_me').catch(() => {});
    await Promise.all([
      lp.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {}),
      lp.click('form button[type="submit"]'),
    ]);
    if (/\/login/.test(lp.url())) throw new Error('Login failed — check DC_EMAIL / DC_PASSWORD secrets');
    storageState = await lctx.storageState();
    await lctx.close();
    console.log('logged in');
  } else {
    console.log('no credentials — running as guest (1 free analysis per runner)');
  }

  // ---- 2. recorded session ----
  const ctx = await browser.newContext({
    storageState,
    viewport: { width: 540, height: 960 },
    deviceScaleFactor: 1,
    isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    recordVideo: { dir: outdir, size: { width: 540, height: 960 } },
  });
  const page = await ctx.newPage();
  const t0 = Date.now();
  const marks = {};
  const mark = k => { marks[k] = (Date.now() - t0) / 1000; };

  await page.goto(`${BASE}/analyze`, { waitUntil: 'networkidle', timeout: 60000 });
  await sleep(600);
  mark('ready');

  const input = page.locator('input[name="address"]').first();
  await input.click();
  await sleep(500);

  // Signed-in users get a full-screen search sheet (div.dcs-sheet) with its own input;
  // guests get the inline form. Type into whichever one is live.
  const sheet = page.locator('.dcs-sheet.on');
  const inSheet = await sheet.isVisible().catch(() => false);
  const box = inSheet ? sheet.locator('input[type="text"]').first() : input;
  await box.fill('');
  await box.type(listing, { delay: 6 });
  await sleep(700);
  mark('pasted');

  // The signed-in flow POSTs back to /analyze, so the URL may not change.
  // Mark "submitted" at the moment of submit and wait for results to render.
  if (inSheet) {
    await box.press('Enter');
    mark('submitted');
    const ok = await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 5000 }).then(() => true).catch(() => false);
    if (!ok) {
      const opt = sheet.locator('[role="listbox"] [role="option"], [role="listbox"] li, [role="listbox"] button').first();
      if (await opt.isVisible().catch(() => false)) await opt.click();
    }
  } else {
    await page.locator('button[type="submit"]').first().click();
    mark('submitted');
  }
  console.log(`submitted via ${inSheet ? 'search sheet' : 'inline form'} → ${page.url()}`);

  if (/guest_limit|\/signup/.test(page.url())) {
    throw new Error(`Hit the guest limit (${page.url()}). Add DC_EMAIL / DC_PASSWORD secrets.`);
  }

  await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 90000 });
  mark('results_dom');

  // wait for the listing photo (sync prefetch or async retry). Ignore our own /static/ assets
  // and pick the largest real photo near the top of the page. Never block the reel on it.
  const photoUrl = await page.waitForFunction(() => {
    const ok = u => u && /^https?:/.test(u) && !/\/static\//.test(u) && !/logo|icon|badge|avatar/i.test(u);
    const cands = [];
    for (const i of document.querySelectorAll('img')) {
      const r = i.getBoundingClientRect(); const u = i.currentSrc || i.src;
      if (r.top < 700 && i.complete && i.naturalWidth >= 400 && ok(u)) cands.push([i.naturalWidth * i.naturalHeight, u]);
    }
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect(); if (r.top > 700 || r.width < 300) continue;
      const m = getComputedStyle(el).backgroundImage.match(/url\(["']?(https?:[^"')]+)/);
      if (m && ok(m[1])) cands.push([r.width * r.height, m[1]]);
    }
    cands.sort((a, b) => b[0] - a[0]);
    return cands.length ? cands[0][1] : null;
  }, null, { timeout: 20000, polling: 500 }).then(h => h.jsonValue()).catch(() => null);
  console.log('photo url:', photoUrl);
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(1200);
  mark('results');

  // ---- 3. walk the section tabs in beats ----
  // The signed-in app scrolls inside its shell (window.scrollTo does nothing) and renders
  // sections on demand, so click the section tabs instead and collect text after each one.
  await sleep(2200);                      // hold on the scorecard + photo
  const seen = [await page.evaluate(() => document.body.innerText)];
  for (const [tab, key] of [['Cashflow', 'tab_cashflow'], ['AI Take', 'tab_ai'], ['Max Offer', 'tab_maxoffer']]) {
    const t = page.getByText(tab, { exact: true }).first();
    if (await t.isVisible().catch(() => false)) {
      await t.click().catch(() => {});
      mark(key);
      await sleep(2600);
    } else {
      // fallback: scroll whatever element actually scrolls
      await page.evaluate(() => {
        const s = [...document.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 200 &&
          /auto|scroll/.test(getComputedStyle(e).overflowY)).sort((a, b) => b.scrollHeight - a.scrollHeight)[0]
          || document.scrollingElement;
        s.scrollBy({ top: s.clientHeight * 0.8, behavior: 'smooth' });
      });
      mark(key);
      await sleep(2000);
    }
    seen.push(await page.evaluate(() => document.body.innerText));
  }
  mark('end');

  // ---- 4. scrape the numbers from everything that rendered ----
  const text = seen.join('\n');
  console.log('----- PAGE TEXT (first 9000 chars) -----\n' + text.slice(0, 9000) + '\n----- END PAGE TEXT -----');
  const grab = (re, i = 1) => { const m = text.match(re); return m ? m[i].trim() : null; };
  const money = s => s ? Number(s.replace(/[^0-9.-]/g, '')) * (s.includes('-') || s.includes('−') ? -1 : 1) : null;
  const strategies = {};
  for (const k of ['LTR', 'MTR', 'STR', 'S8', 'HH', 'BRRRR', 'FLIP']) {
    const v = grab(new RegExp(`\\n${k}\\n([+\\-−]?\\$[0-9,.]+k?)`));
    if (v) strategies[k] = v;
  }
  const data = {
    listing,
    address: grab(/\n(\d+[^\n,]{3,60})\n(?:,\n)?([A-Za-z .'-]+, [A-Z]{2} \d{5})/, 1),
    cityLine: grab(/\n(\d+[^\n,]{3,60})\n(?:,\n)?([A-Za-z .'-]+, [A-Z]{2} \d{5})/, 2),
    price: grab(/\n(\$[0-9]{2,3},[0-9]{3}(?:,[0-9]{3})?)\n/),
    beds: grab(/(\d+)\s*bd/), baths: grab(/(\d+(?:\.\d)?)\s*ba/), sqft: grab(/([0-9,]+)\s*sqft/),
    score: grab(/\n(\d{1,2}\.\d)\n\/10/) || grab(/SCORE\n(\d{1,2}\.\d)/),
    ltrCashflow: grab(/MONTHLY CASH FLOW\n([+\-−]?\$[0-9,]+)\/mo/i) || grab(/LTR CF\n([+\-−]?\$[0-9,]+)/),
    coc: grab(/COC RETURN[^\n]*\n([0-9.\-]+%)/i),
    capRate: grab(/CAP RATE[^\n]*\n([0-9.\-]+%)/i),
    cashToClose: grab(/TO CLOSE\n(\$[0-9,]+)/),
    rent: grab(/\nRENT[^\n]*\n(\$[0-9,]+)\/mo/i),
    maxOffer: grab(/MAX OFFER\n(\$[0-9,]+)/i),
    strategies,
    photoUrl,
  };
  data.ltrCashflowNum = money(data.ltrCashflow);
  fs.writeFileSync(path.join(outdir, 'data.json'), JSON.stringify(data, null, 2));
  console.log('scraped', JSON.stringify(data));

  // ---- 5. grab the listing photo bytes for the opener ----
  if (photoUrl) {
    try {
      const r = await page.request.get(photoUrl, { timeout: 15000 });
      if (r.ok()) fs.writeFileSync(path.join(outdir, 'photo.jpg'), await r.body());
    } catch (e) { console.log('photo download failed:', e.message); }
  }

  fs.writeFileSync(path.join(outdir, 'marks.json'), JSON.stringify(marks, null, 2));
  await ctx.close();
  await browser.close();
  const vid = fs.readdirSync(outdir).find(f => f.endsWith('.webm') && f !== 'raw.webm');
  fs.renameSync(path.join(outdir, vid), path.join(outdir, 'raw.webm'));
  console.log('done', outdir);
})().catch(e => { console.error('FAILED:', e.message); process.exit(1); });
