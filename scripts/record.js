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
async function tagCard(page, pattern, minH, maxH = 1100, minW = 0.85) {
  return page.evaluate(([src, minH, maxH, minW]) => {
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
      if (r.width >= vw * minW && r.height >= minH) break;
      cur = cur.parentElement;
    }
    if (!cur || cur === document.body) return null;
    const r = cur.getBoundingClientRect();
    if (r.height > maxH) return null;           // walked too far up (whole page section)
    cur.setAttribute('data-reel', '1');
    cur.scrollIntoView({ block: 'center' });
    return { w: Math.round(r.width), h: Math.round(r.height) };
  }, [pattern, minH, maxH, minW]);
}

async function shootCard(page, name, pattern, minH, maxH, minW) {
  await page.evaluate(() => {
    for (const el of document.querySelectorAll('body *')) {
      if (el.children.length) continue;
      const t = (el.textContent || '').trim();
      if (t.length === 1 && /[\u2139\u2460-\u24FF]/.test(t)) el.style.visibility = 'hidden';
    }
  }).catch(() => {});
  const box = await tagCard(page, pattern, minH, maxH, minW);
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
    const ok = await page.waitForSelector('#live-score-num', { state: 'attached', timeout: 5000 }).then(() => true).catch(() => false);
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
  await page.waitForSelector('#live-score-num', { state: 'attached', timeout: 90000 });
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

  // ---- 4b. sanity-check insurance before anything is captured. Some listings carry a tiny
  // "listing estimate" ($60-70/mo on a $200K triplex). If it is below ~0.5% of price a year
  // (or $50/unit/mo), type a market figure into the app's own field — exactly what a careful
  // investor would do — so every strategy, the score and the cards recalculate with it.
  const insFix = await page.evaluate(() => {
    const num = id => +String((document.getElementById(id) || {}).value || '').replace(/[^0-9.]/g, '') || 0;
    const price = num('fin-price'), ins = num('fin-ins');
    const units = Math.max(1, document.querySelectorAll('[id^="mf-unit-box-"]').length);
    if (!price || !ins) return null;
    const floor = Math.max(0.005 * price / 12, 50 * units);
    if (ins >= floor) return null;
    const target = Math.round(Math.max(0.0075 * price / 12, 70 * units) / 5) * 5;
    const el = document.getElementById('fin-ins');
    el.value = String(target);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return { from: ins, to: target };
  }).catch(() => null);
  if (insFix) { console.log('insurance adjusted:', JSON.stringify(insFix)); await sleep(2000); }

  // ---- 5. card stills, collecting page text as each section renders ----
  const seen = [];
  const snap = async n => { seen.push(await page.evaluate(() => document.body.innerText)); await page.screenshot({ path: out(`page_${n}.png`) }); };

  // The app's little circled-i info icons (U+24BE etc.) have no glyph on the runner and render as
  // empty boxes. Hide those leaf nodes before any capture. Visual only — the page text is unchanged.
  const hideIcons = () => page.evaluate(() => {
    for (const el of document.querySelectorAll('body *')) {
      if (el.children.length) continue;
      const t = (el.textContent || '').trim();
      if (t.length === 1 && /[ℹ①-⓿]/.test(t)) el.style.visibility = 'hidden';
    }
  }).catch(() => {});
  await hideIcons();

  await snap('1_hero');
  if (!(await shootCard(page, 'hero', 'Deal ScoreCard', 300, 900))) {
    // facelift layout: the whole property card (photo + score chip + key numbers) is the hero
    try { await page.locator('#results-top').first().screenshot({ path: out('card_hero.png'), animations: 'disabled' }); console.log('card hero: #results-top'); }
    catch (e) { console.log('card hero: not captured — ' + e.message); }
  }

  if (await clickTab(page, 'Cashflow')) await snap('2_cashflow');
  await shootCard(page, 'strats', 'Cashflow by Strategy', 60, 600);
  await shootCard(page, 'ltr', 'Monthly Cash Flow', 160, 900);

  // the tab was renamed "Max Offer" -> "Offer"; try both
  if ((await clickTab(page, 'Offer')) || (await clickTab(page, 'Max Offer'))) await snap('3_maxoffer');
  let maxOfferCard = null;
  await sleep(1500);
  if ((await shootCard(page, 'maxoffer', 'MAX OFFER PRICE', 70, 420, 0.6)) ||
      (await shootCard(page, 'maxoffer', 'vs\\s*asking', 60, 420, 0.55))) {
    const t = await page.locator('[data-reel="1"]').first().innerText().catch(() => '');
    const m = t.match(/MAX OFFER[A-Z ]*\s*\n?\s*(\$[0-9,]{5,})/i) || t.match(/(\$[0-9]{2,3},[0-9]{3})/);
    maxOfferCard = m ? m[1] : null; console.log('max offer on card:', maxOfferCard);
  }  // no green card found -> the max-offer slide shows the big number without a card (never the tiny calculator)

  if (await clickTab(page, 'AI Take')) await snap('4_ai');

  // ---- 6. scrape ----
  // ---- auto-filled inputs the reels call out: per-unit rents (RentCast), taxes, insurance
  const auto = await page.evaluate(() => {
    const v = (id) => { const e = document.getElementById(id); return e ? String(e.value || '').replace(/[^0-9.]/g, '') : ''; };
    const srcOf = (id) => { const e = document.getElementById(id); const n = e && e.parentElement && e.parentElement.querySelector('div[style*="italic"]'); return n ? n.textContent.replace(/\s+/g, ' ').trim() : ''; };
    const units = [...document.querySelectorAll('[id^="mf-unit-box-"]')].map(b => ({
      label: ((b.querySelector('div') || {}).textContent || '').replace(/\s+/g, ' ').trim(),
      rent: ((b.querySelector('input') || {}).value || '').replace(/[^0-9.]/g, ''),
    })).filter(u => +u.rent > 0);
    return { units, ltrRent: v('ltr-rent'), tax: v('fin-tax'), taxSrc: srcOf('fin-tax'), ins: v('fin-ins'), insSrc: srcOf('fin-ins') };
  }).catch(() => ({}));
  if (insFix) { auto.insAdjusted = insFix; auto.ins = String(insFix.to); }
  console.log('auto-filled:', JSON.stringify(auto));
  // ---- rehab estimate from the listing photos (one AI call on the content account)
  let rehab = null;
  try {
    await page.evaluate(() => { if (typeof autoAnalyzeCondition === 'function') autoAnalyzeCondition(); });
    await page.waitForSelector('#cond-rehab', { state: 'attached', timeout: 90000 });
    rehab = await page.evaluate(() => {
      const el = document.getElementById('cond-rehab');
      const spans = el.querySelectorAll('span');
      return { range: (spans[0] || {}).textContent || '', level: (spans[1] || {}).textContent || '',
               scope: [...el.querySelectorAll('li')].map(li => li.textContent.trim()).slice(0, 4) };
    });
    console.log('rehab:', JSON.stringify(rehab));
  } catch (e) { console.log('rehab: none — ' + e.message.split('\n')[0]); }
  const domScore = await page.evaluate(() => (document.querySelector('#live-score-num') || {}).textContent || '').catch(() => '');
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
    score: ((domScore.match(/\d{1,2}(?:\.\d)?/) || [])[0]) || grab(/\n(\d{1,2}\.\d)\n\/10/) || grab(/SCORE\n(\d{1,2}\.\d)/),
    ltrCashflow: grab(/MONTHLY CASH FLOW[\s\S]{0,12}?([+\-−]?\$[0-9,]+)\/mo/i) || grab(/LTR CF\n([+\-−]?\$[0-9,]+)/),
    coc: grab(/COC RETURN[\s\S]{0,16}?(-?[0-9.]+%)/i),
    capRate: grab(/CAP RATE[\s\S]{0,16}?(-?[0-9.]+%)/i),
    cashToClose: grab(/TO CLOSE\n(\$[0-9,]+)/),
    rent: grab(/\nRENT[^\n]*\n(\$[0-9,]+)\/mo/i),
    maxOffer: maxOfferCard || grab(/MAX OFFER PRICE\n(\$[0-9,]+)/i) || grab(/MAX OFFER[^\n$]*\n(\$[0-9,]+)/i),
    strategies,
    strRestricted: /STR Restricted Market/i.test(text),
    auto, rehab,
    // only the app's own unit grid decides — page help text mentions duplex/multi-family on every listing
    propType: (auto.units || []).length >= 2 ? ({2: 'duplex', 3: 'triplex', 4: 'fourplex'}[auto.units.length] || `${auto.units.length}-unit`) : null,
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
