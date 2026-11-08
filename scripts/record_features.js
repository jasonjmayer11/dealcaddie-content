#!/usr/bin/env node
// Feature-tour capture (investor): runs one analysis as the content account and screenshots the
// cards the "everything in one analysis" video talks about.
// Usage: node scripts/record_features.js "<zillow url>" <outdir>
// Produces: photo.jpg, card_hero, card_strats, card_comps, card_scen, card_maxoffer, card_offerplan,
//           card_share (what a recipient sees, opened logged-out), page_*.png, data.json
// Side effects on the content account: the analysis, and the share link the Share button creates.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [listing, outdir] = process.argv.slice(2);
if (!listing || !outdir) { console.error('usage: record_features.js <listing> <outdir>'); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });
const BASE = 'https://www.dealcaddie.ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = f => path.join(outdir, f);
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
const PHONE = { viewport: { width: 430, height: 932 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, userAgent: UA };

async function ev(page, fn, arg) {
  for (let k = 0; k < 4; k++) {
    try { return await page.evaluate(fn, arg); }
    catch (e) {
      if (!/context was destroyed|navigation/i.test(e.message)) throw e;
      await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {}); await sleep(1200);
    }
  }
  return null;
}

const hideIcons = page => ev(page, () => {
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length) continue;
    const t = (el.textContent || '').trim();
    if (t.length === 1 && /[ℹ①-⓿]/.test(t)) el.style.visibility = 'hidden';
  }
});

// smallest element whose text matches, walked up to the first ancestor >= minW of the viewport and >= minH tall
async function tagCard(page, pattern, minH, maxH = 1100, minW = 0.85) {
  return ev(page, ([src, minH, maxH, minW]) => {
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
    if (r.height > maxH) return null;
    cur.setAttribute('data-reel', '1');
    cur.scrollIntoView({ block: 'center' });
    return { w: Math.round(r.width), h: Math.round(r.height) };
  }, [pattern, minH, maxH, minW]);
}

async function shootCard(page, name, pattern, minH, maxH, minW) {
  await hideIcons(page);
  const box = await tagCard(page, pattern, minH, maxH, minW);
  if (!box) { console.log(`card ${name}: not found (${pattern})`); return false; }
  await sleep(800);
  try {
    await page.locator('[data-reel="1"]').first().screenshot({ path: out(`card_${name}.png`), animations: 'disabled' });
    console.log(`card ${name}: ${box.w}x${box.h} css px`);
    return true;
  } catch (e) { console.log(`card ${name}: screenshot failed — ${e.message}`); return false; }
}

async function clickTab(page, label) {
  const t = page.getByText(label, { exact: true }).first();
  if (await t.isVisible().catch(() => false)) { await t.click().catch(() => {}); await sleep(1800); return true; }
  console.log(`tab ${label}: not visible`); return false;
}

(async () => {
  const browser = await chromium.launch();
  const lctx = await browser.newContext();
  const lp = await lctx.newPage();
  await lp.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await lp.fill('#email', process.env.DC_EMAIL);
  await lp.fill('#password', process.env.DC_PASSWORD);
  await lp.check('#remember_me').catch(() => {});
  await Promise.all([lp.waitForNavigation({ timeout: 60000 }).catch(() => {}), lp.click('form button[type="submit"]')]);
  if (/\/login/.test(lp.url())) throw new Error('login failed');
  const storageState = await lctx.storageState(); await lctx.close();

  const ctx = await browser.newContext({ storageState, ...PHONE });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/analyze`, { waitUntil: 'networkidle', timeout: 60000 });
  const input = page.locator('input[name="address"]').first();
  await input.click(); await sleep(500);
  const sheet = page.locator('.dcs-sheet.on');
  const inSheet = await sheet.isVisible().catch(() => false);
  const box = inSheet ? sheet.locator('input[type="text"]').first() : input;
  await box.fill(listing); await sleep(400);
  if (inSheet) await box.press('Enter'); else await page.locator('button[type="submit"]').first().click();
  await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 90000 });

  const photoUrl = await page.waitForFunction(() => {
    const ok = u => u && /^https?:/.test(u) && !/\/static\//.test(u) && !/logo|icon|badge|avatar/i.test(u);
    const c = [];
    for (const i of document.querySelectorAll('img')) {
      const r = i.getBoundingClientRect(); const u = i.currentSrc || i.src;
      if (r.top < 700 && i.complete && i.naturalWidth >= 400 && ok(u)) c.push([i.naturalWidth * i.naturalHeight, u]);
    }
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect(); if (r.top > 700 || r.width < 300) continue;
      const m = getComputedStyle(el).backgroundImage.match(/url\(["']?(https?:[^"')]+)/);
      if (m && ok(m[1])) c.push([r.width * r.height, m[1]]);
    }
    c.sort((a, b) => b[0] - a[0]); return c.length ? c[0][1] : null;
  }, null, { timeout: 25000, polling: 500 }).then(h => h.jsonValue()).catch(() => null);
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(2500);

  const texts = [];
  const snap = async n => { texts.push(await ev(page, () => document.body.innerText) || ''); await page.screenshot({ path: out(`page_${n}.png`) }); };

  await snap('1_hero');
  await shootCard(page, 'hero', 'Deal ScoreCard', 300, 900);

  if (await clickTab(page, 'Cashflow')) await snap('2_cashflow');
  await shootCard(page, 'strats', 'Cashflow by Strategy', 60, 600);

  let scenCrop = null;
  if (await clickTab(page, 'Scenarios')) await snap('3_scenarios');
  if (await shootCard(page, 'scen', 'OPTION B', 400, 2400)) {
    // crop the table just below the "Cash to close" row
    scenCrop = await ev(page, () => {
      const card = document.querySelector('[data-reel="1"]'); if (!card) return null;
      const cr = card.getBoundingClientRect();
      const row = [...card.querySelectorAll('*')].filter(e => /^Cash to\s*close$/i.test((e.textContent || '').trim()))[0];
      if (!row) return null;
      let tr = row; for (let k = 0; k < 4 && tr.parentElement && tr.getBoundingClientRect().width < cr.width * 0.8; k++) tr = tr.parentElement;
      const hdr = [...card.querySelectorAll('*')].filter(e => /^YOURS$/i.test((e.textContent || '').trim()))[0];
      const top = hdr ? Math.max(0, (hdr.getBoundingClientRect().top - cr.top - 16) / cr.height) : 0;
      return [top, Math.min(1, (tr.getBoundingClientRect().bottom - cr.top + 14) / cr.height)];
    });
  }

  let maxOfferTarget = null;
  if (await clickTab(page, 'Offer')) await snap('4_offer');
  maxOfferTarget = await ev(page, () => {
    for (const i of document.querySelectorAll('input')) {
      if (!/^\d+(\.\d+)?$/.test(i.value || '') || i.type === 'range') continue;
      let n = i, txt = '';
      for (let k = 0; k < 4 && n; k++) { n = n.parentElement; txt = n ? n.innerText : ''; if (/Target/i.test(txt)) break; }
      if (/Target\s*\/mo/i.test(txt)) return i.value;
    }
    return null;
  });
  let maxOfferCard = null;
  await sleep(1500);
  if ((await shootCard(page, 'maxoffer', 'MAX OFFER PRICE', 150, 700, 0.6)) ||
      (await shootCard(page, 'maxoffer', 'vs\\s*asking', 100, 500, 0.55))) {
    const t = await page.locator('[data-reel="1"]').first().innerText().catch(() => '');
    const m = t.match(/MAX OFFER[A-Z ]*\s*\n?\s*(\$[0-9,]{5,})/i) || t.match(/(\$[0-9]{2,3},[0-9]{3})/);
    maxOfferCard = m ? m[1] : null; console.log('max offer on card:', maxOfferCard);
  }
  await shootCard(page, 'offerplan', 'Offer Plan & Negotiator', 120, 700, 0.8);

  if (await clickTab(page, 'Comps')) await snap('5_comps');
  await shootCard(page, 'comps', 'RECENTLY SOLD', 300, 1500);

  // ---- share: tap the share icon in the header, find the link, open it logged-out ----
  let shareUrl = null;
  try {
    await ev(page, () => { const s = document.querySelector('[data-probe-scroll]'); if (s) s.scrollTop = 0; });
    let btn = page.locator('[aria-label*="share" i], [title*="share" i]').first();
    if (!(await btn.isVisible().catch(() => false))) {
      // fall back to the right-most small button in the top bar
      const idx = await ev(page, () => {
        const bs = [...document.querySelectorAll('button, a')].filter(b => { const r = b.getBoundingClientRect(); return r.top < 70 && r.width < 70 && r.width > 0; });
        bs.sort((a, b) => b.getBoundingClientRect().left - a.getBoundingClientRect().left);
        if (!bs.length) return false; bs[0].setAttribute('data-share-btn', '1'); return true;
      });
      btn = page.locator('[data-share-btn="1"]').first();
    }
    await btn.click({ timeout: 5000 });
    await sleep(3500);
    await page.screenshot({ path: out('page_6_share_sheet.png') });
    const sheetText = await ev(page, () => document.body.innerText) || '';
    fs.writeFileSync(out('share_sheet.txt'), sheetText);
    shareUrl = await ev(page, () => {
      const re = /https?:\/\/[^\s"'<>]+\/(share|s)\/[A-Za-z0-9_-]{6,}[^\s"'<>]*/;
      for (const i of document.querySelectorAll('input, textarea')) { const m = (i.value || '').match(re); if (m) return m[0]; }
      for (const a of document.querySelectorAll('a[href]')) { const m = a.href.match(re); if (m) return m[0]; }
      const m = document.body.innerText.match(re); return m ? m[0] : null;
    });
    console.log('share url:', shareUrl);
  } catch (e) { console.log('share: ' + e.message); }

  if (shareUrl) {
    const gctx = await browser.newContext(PHONE);            // a recipient: not logged in
    const gp = await gctx.newPage();
    await gp.goto(shareUrl, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
    await sleep(3000);
    await hideIcons(gp);
    await gp.screenshot({ path: out('card_share.png') });
    await gp.screenshot({ path: out('page_7_share_recipient.png') });
    await gctx.close();
  }

  // ---- scrape ----
  const text = texts.join('\n');
  fs.writeFileSync(out('page_text.txt'), text);
  const grab = (re, i = 1) => { const m = text.match(re); return m ? m[i].trim() : null; };
  const strategies = {};
  for (const k of ['LTR', 'MTR', 'STR', 'S8', 'HH', 'BRRRR', 'FLIP']) {
    const v = grab(new RegExp(`\\n${k}\\n([+\\-−]?\\$[0-9,.]+k?)`, 'i'));
    if (v) strategies[k] = v;
  }
  const data = {
    listing,
    address: grab(/\n(\d+[^\n,]{3,60})\n(?:,\n)?([A-Za-z .'-]+, [A-Z]{2} \d{5})/, 1),
    cityLine: grab(/\n(\d+[^\n,]{3,60})\n(?:,\n)?([A-Za-z .'-]+, [A-Z]{2} \d{5})/, 2),
    price: grab(/\n(\$[0-9]{2,3},[0-9]{3}(?:,[0-9]{3})?)\n/),
    beds: grab(/(\d+)\s*bd/), baths: grab(/(\d+(?:\.\d)?)\s*ba/), sqft: grab(/([0-9,]+)\s*sqft/),
    score: grab(/\n(\d{1,2}\.\d)\n\/10/),
    strategies,
    compsPct: grab(/(\d{1,2})%\s+(?:below|under)\s+(?:comparable|comps|recent)/i),
    compsDir: grab(/\d{1,2}%\s+(below|under|above|over)\s+(?:comparable|comps|recent)/i),
    compCount: ((text.split(/RECENTLY SOLD/i)[1] || '').match(/\n\d{1,2}\n\d+ /g) || []).length || null,
    scenSaving: grab(/[−-]\$([0-9,]+)\s*vs yours/),
    scenDownA: grab(/\nDown\t([0-9.]+%)\n/),
    scenDownB: grab(/\nDown\t[0-9.]+%\n[^\n]*\n\t([0-9.]+%)/),
    scenCrop,
    maxOffer: maxOfferCard || grab(/MAX OFFER PRICE\n(\$[0-9,]+)/i),
    maxOfferTarget,
    shareUrl,
    photoUrl,
  };
  fs.writeFileSync(out('data.json'), JSON.stringify(data, null, 2));
  console.log('scraped', JSON.stringify(data));
  if (photoUrl) {
    try { const r = await page.request.get(photoUrl, { timeout: 15000 }); if (r.ok()) fs.writeFileSync(out('photo.jpg'), await r.body()); }
    catch (e) { console.log('photo download failed:', e.message); }
  }
  await browser.close();
})().catch(e => { console.error('FAILED:', e.message); process.exit(1); });
