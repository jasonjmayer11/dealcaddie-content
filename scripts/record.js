#!/usr/bin/env node
// DealCaddie reel capture — stills mode.
// Usage: node scripts/record.js "<zillow url or address>" <outdir>
// Env:   DC_EMAIL / DC_PASSWORD  (content account; falls back to guest if unset)
//
// Instead of filming the screen (busy, small text, motion we don't control), this runs the
// analysis once and takes high-resolution screenshots of just the cards the reel talks about.
// assemble.py then builds calm, one-idea-per-beat frames from them.
//
// Produces in <outdir>:
//   photo.jpg        the listing photo (opener)
//   card_hero.png    property card with the Deal ScoreCard
//   card_ltr.png     long-term rental cashflow card
//   card_strats.png  cashflow-by-strategy strip
//   card_maxoffer.png max offer card
//   logo.png         the DealCaddie logo from the nav (for the end card)
//   page_*.png       full-viewport debug shots
//   data.json        numbers scraped from the finished analysis
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const listing = process.argv[2];
const outdir = process.argv[3];
if (!listing || !outdir) { console.error('usage: record.js <listing> <outdir>'); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });

const BASE = 'https://www.dealcaddie.ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = f => path.join(outdir, f);

// Find the card that holds `pattern`: the smallest element whose text matches, then walk up
// to the first ancestor that is (nearly) full width and at least minH tall. Tag it so a
// locator can screenshot it. Returns the card's size, or null if nothing matched.
async function tagCard(page, pattern, minH, maxH = 1100) {
  return page.evaluate(([src, minH, maxH]) => {
    document.querySelectorAll('[data-reel]').forEach(e => e.removeAttribute('data-reel'));
    const re = new RegExp(src, 'i');
    const hits = [...document.querySelectorAll('body *')]
      .filter(e => e.offsetParent !== null && re.test(e.textContent || ''))
      .sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
    if (!hits.length) return null;
    const vw = window.innerWidth;
    let cur = hits[0];
    while (cur && cur !== document.body) {
      const r = cur.getBoundingClientRect();
      if (r.width >= vw * 0.85 && r.height >= minH) break;
      cur = cur.parentElement;
    }
    if (!cur || cur === document.body) return null;
    const r = cur.getBoundingClientRect();
    if (r.height > maxH) return null;           // walked too far up (whole page section)
    cur.setAttribute('data-reel', '1');
    cur.scrollIntoView({ block: 'center' });
    return { w: Math.round(r.width), h: Math.round(r.height) };
  }, [pattern, minH, maxH]);
}

async function shootCard(page, name, pattern, minH, maxH) {
  const box = await tagCard(page, pattern, minH, maxH);
  if (!box) { console.log(`card ${name}: not found (${pattern})`); return false; }
  await sleep(700);                              // let scroll + lazy content settle
  try {
    await page.locator('[data-reel="1"]').first().screenshot({ path: out(`card_${name}.png`), animations: 'disabled' });
    console.log(`card ${name}: ${box.w}x${box.h} css px`);
    return true;
  } catch (e) { console.log(`card ${name}: screenshot failed — ${e.message}`); return false; }
}

async function clickTab(page, label) {
  const t = page.getByText(label, { exact: true }).first();
  if (await t.isVisible().catch(() => false)) { await t.click().catch(() => {}); await sleep(1500); return true; }
  return false;
}

(async () => {
  const browser = await chromium.launch();

  // ---- 1. log in ----
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

  // ---- 2. phone-sized, 3x pixel density so card screenshots are crisp at 1080 wide ----
  const ctx = await browser.newContext({
    storageState,
    viewport: { width: 430, height: 932 },
    deviceScaleFactor: 3,
    isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  });
  const page = await ctx.newPage();

  await page.goto(`${BASE}/analyze`, { waitUntil: 'networkidle', timeout: 60000 });
  await sleep(500);

  // logo from the nav, for the end card
  try {
    const logo = page.locator('nav img, header img, a[href="/"] img').first();
    if (await logo.isVisible()) { await logo.screenshot({ path: out('logo.png'), omitBackground: true }); console.log('logo captured'); }
  } catch (e) { console.log('logo: not captured'); }

  // ---- 3. run the analysis ----
  const input = page.locator('input[name="address"]').first();
  await input.click();
  await sleep(500);
  const sheet = page.locator('.dcs-sheet.on');          // signed-in full-screen search sheet
  const inSheet = await sheet.isVisible().catch(() => false);
  const box = inSheet ? sheet.locator('input[type="text"]').first() : input;
  await box.fill(listing);
  await sleep(400);
  if (inSheet) {
    await box.press('Enter');
    const ok = await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 5000 }).then(() => true).catch(() => false);
    if (!ok) {
      const opt = sheet.locator('[role="listbox"] [role="option"], [role="listbox"] li, [role="listbox"] button').first();
      if (await opt.isVisible().catch(() => false)) await opt.click();
    }
  } else {
    await page.locator('button[type="submit"]').first().click();
  }
  if (/guest_limit|\/signup/.test(page.url())) {
    throw new Error(`Hit the guest limit (${page.url()}). Add DC_EMAIL / DC_PASSWORD secrets.`);
  }
  await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 90000 });
  console.log(`analysis loaded via ${inSheet ? 'search sheet' : 'inline form'}`);

  // ---- 4. listing photo (largest non-/static/ image near the top) ----
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
  await sleep(1500);                                     // splash gone, scorecard settled

  // ---- 5. card stills, collecting page text as each section renders ----
  const seen = [];
  const snap = async n => { seen.push(await page.evaluate(() => document.body.innerText)); await page.screenshot({ path: out(`page_${n}.png`) }); };

  await snap('1_hero');
  await shootCard(page, 'hero', 'Deal ScoreCard', 300, 900);

  if (await clickTab(page, 'Cashflow')) await snap('2_cashflow');
  await shootCard(page, 'strats', 'Cashflow by Strategy', 60, 600);
  await shootCard(page, 'ltr', 'Monthly Cash Flow', 160, 900);

  if (await clickTab(page, 'Max Offer')) await snap('3_maxoffer');
  await shootCard(page, 'maxoffer', 'Max Offer Calculator', 120, 800);

  if (await clickTab(page, 'AI Take')) await snap('4_ai');

  // ---- 6. scrape ----
  const text = seen.join('\n');
  console.log('----- PAGE TEXT (first 6000 chars) -----\n' + text.slice(0, 6000) + '\n----- END PAGE TEXT -----');
  const grab = (re, i = 1) => { const m = text.match(re); return m ? m[i].trim() : null; };
  const money = s => s ? Number(s.replace(/−/g, '-').replace(/[^0-9.-]/g, '')) : null;
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
    ltrCashflow: grab(/MONTHLY CASH FLOW[\s\S]{0,12}?([+\-−]?\$[0-9,]+)\/mo/i) || grab(/LTR CF\n([+\-−]?\$[0-9,]+)/),
    coc: grab(/COC RETURN[\s\S]{0,16}?(-?[0-9.]+%)/i),
    capRate: grab(/CAP RATE[\s\S]{0,16}?(-?[0-9.]+%)/i),
    cashToClose: grab(/TO CLOSE\n(\$[0-9,]+)/),
    rent: grab(/\nRENT[^\n]*\n(\$[0-9,]+)\/mo/i),
    maxOffer: grab(/MAX OFFER[^\n$]*\n(\$[0-9,]+)/i),
    strategies,
    photoUrl,
    cards: fs.readdirSync(outdir).filter(f => f.startsWith('card_')),
  };
  data.ltrCashflowNum = money(data.ltrCashflow);
  fs.writeFileSync(out('data.json'), JSON.stringify(data, null, 2));
  console.log('scraped', JSON.stringify(data));

  if (photoUrl) {
    try {
      const r = await page.request.get(photoUrl, { timeout: 15000 });
      if (r.ok()) fs.writeFileSync(out('photo.jpg'), await r.body());
    } catch (e) { console.log('photo download failed:', e.message); }
  }

  await ctx.close();
  await browser.close();
  console.log('done', outdir);
})().catch(e => { console.error('FAILED:', e.message); process.exit(1); });
