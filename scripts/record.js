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

  const startUrl = page.url();
  const nav = page.waitForURL(u => u.toString() !== startUrl, { timeout: 120000, waitUntil: 'domcontentloaded' });
  if (inSheet) {
    await box.press('Enter');
    // if Enter didn't submit, pick the first suggestion in the sheet
    const moved = await Promise.race([nav.then(() => true), sleep(4000).then(() => false)]);
    if (!moved) {
      const opt = sheet.locator('[role="listbox"] [role="option"], [role="listbox"] li, [role="listbox"] button').first();
      if (await opt.isVisible().catch(() => false)) await opt.click();
    }
  } else {
    await page.locator('button[type="submit"]').first().click();
  }
  await nav.catch(() => {});
  mark('submitted');
  console.log(`submitted via ${inSheet ? 'search sheet' : 'inline form'} → ${page.url()}`);

  if (/guest_limit|\/signup/.test(page.url())) {
    throw new Error(`Hit the guest limit (${page.url()}). Add DC_EMAIL / DC_PASSWORD secrets.`);
  }

  await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 90000 });
  mark('results_dom');

  // wait for the hero photo (sync prefetch or async retry) — up to 12s, never block on it
  const photoUrl = await page.waitForFunction(() => {
    const big = [...document.querySelectorAll('img')]
      .filter(i => i.getBoundingClientRect().top < 520 && i.complete && i.naturalWidth >= 400 && !i.src.startsWith('data:'));
    if (big.length) return big[0].currentSrc || big[0].src;
    for (const el of document.querySelectorAll('[style*="background-image"], .results-top, [class*="hero"]')) {
      const m = getComputedStyle(el).backgroundImage.match(/url\(["']?(https?:[^"')]+)/);
      if (m && el.getBoundingClientRect().top < 520) return m[1];
    }
    return null;
  }, null, { timeout: 12000, polling: 400 }).then(h => h.jsonValue()).catch(() => null);
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(1200);
  mark('results');

  // ---- 3. scrape the numbers from the rendered page ----
  const text = await page.evaluate(() => document.body.innerText);
  const grab = (re, i = 1) => { const m = text.match(re); return m ? m[i].trim() : null; };
  const money = s => s ? Number(s.replace(/[^0-9.-]/g, '')) * (s.includes('-') || s.includes('−') ? -1 : 1) : null;
  const strategies = {};
  for (const k of ['LTR', 'MTR', 'STR', 'S8', 'HH', 'BRRRR', 'FLIP']) {
    const v = grab(new RegExp(`\\n${k}\\n([+\\-−]?\\$[0-9,.]+k?)`));
    if (v) strategies[k] = v;
  }
  const data = {
    listing,
    address: grab(/\n(\d+[^\n]{3,60})\n([A-Za-z .'-]+, [A-Z]{2} \d{5})/, 1),
    cityLine: grab(/\n(\d+[^\n]{3,60})\n([A-Za-z .'-]+, [A-Z]{2} \d{5})/, 2),
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

  // ---- 4. scroll the analysis in beats ----
  const H = await page.evaluate(() => document.body.scrollHeight);
  for (const f of [0.17, 0.34, 0.52, 0.7]) {
    await page.evaluate(y => window.scrollTo({ top: y, behavior: 'smooth' }), Math.min(H - 960, H * f));
    await sleep(1700);
    mark(`scroll_${Math.round(f * 100)}`);
  }
  mark('end');

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
