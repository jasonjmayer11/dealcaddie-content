#!/usr/bin/env node
// Capture fresh app screens for the Feature Showcase (Pipeline, Compare) from the live app,
// as the content account. If its pipeline has fewer than 4 deals, it saves up to 4 listings
// from done.csv first (public listings the reels already used). Writes PNGs to <outdir>.
// Usage: node scripts/capture_screens.js <outdir>
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const outdir = process.argv[2]; fs.mkdirSync(outdir, { recursive: true });
const BASE = 'https://www.dealcaddie.ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = f => path.join(outdir, f);
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

async function deals(page) {
  const r = await page.request.get(`${BASE}/api/saved-analyses`);
  if (!r.ok()) return [];
  const j = await r.json();
  return Array.isArray(j) ? j : (j.analyses || j.deals || j.items || []);
}

(async () => {
  const browser = await chromium.launch();
  const lctx = await browser.newContext(); const lp = await lctx.newPage();
  await lp.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await lp.fill('#email', process.env.DC_EMAIL); await lp.fill('#password', process.env.DC_PASSWORD);
  await Promise.all([lp.waitForNavigation({ timeout: 60000 }).catch(() => {}), lp.click('form button[type="submit"]')]);
  const storageState = await lctx.storageState(); await lctx.close();
  const ctx = await browser.newContext({ storageState, viewport: { width: 430, height: 932 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, userAgent: UA });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle' });

  let list = await deals(page);
  console.log('saved deals:', list.length);
  if (list.length < 4) {
    const rows = fs.readFileSync('done.csv', 'utf8').trim().split('\n').map(l => l.split(',').pop()).filter(u => /zillow\.com/.test(u));
    const want = rows.slice(-6).reverse();
    for (const url of want) {
      if ((await deals(page)).length >= 4) break;
      try {
        await page.goto(`${BASE}/analyze`, { waitUntil: 'networkidle' });
        const input = page.locator('input[name="address"]').first(); await input.click(); await sleep(500);
        const sheet = page.locator('.dcs-sheet.on'); const inSheet = await sheet.isVisible().catch(() => false);
        const box = inSheet ? sheet.locator('input[type="text"]').first() : input;
        await box.fill(url); await sleep(300);
        if (inSheet) await box.press('Enter'); else await page.locator('button[type="submit"]').first().click();
        await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 90000 });
        await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {}); await sleep(3000);
        const resp = page.waitForResponse(r => /\/api\/save-analysis/.test(r.url()), { timeout: 30000 }).catch(() => null);
        await page.evaluate(() => window.saveDeal && window.saveDeal());
        const r = await resp; console.log('saved', url, r ? r.status() : 'no response');
        await sleep(1500);
      } catch (e) { console.log('save failed', url, e.message); }
    }
    list = await deals(page);
  }
  console.log('deals now:', list.map(d => `${d.id}:${d.address}`).join(' | '));

  // Pipeline
  await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle' }); await sleep(3500);
  // screenshot only: hide one-off promo/onboarding banners so the deal cards show
  await page.evaluate(() => {
    for (const el of document.querySelectorAll('body *')) {
      const t = (el.innerText || '');
      if (/Compare your deals side by side/i.test(t) && el.getBoundingClientRect().height < 400 && el.children.length) {
        let box = el; while (box.parentElement && box.parentElement.getBoundingClientRect().height < 400) box = box.parentElement;
        box.style.display = 'none'; break;
      }
    }
  });
  await sleep(600);
  await page.screenshot({ path: out('pipeline_raw.png') });
  fs.writeFileSync(out('pipeline.txt'), await page.evaluate(() => document.body.innerText));
  // Compare (needs 2+ ids)
  const ids = list.slice(0, 3).map(d => d.id).filter(Boolean);
  if (ids.length >= 2) {
    await page.goto(`${BASE}/compare?ids=${ids.join(',')}`, { waitUntil: 'networkidle' }); await sleep(3000);
    await page.screenshot({ path: out('compare_raw.png') });
  }
  await browser.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
