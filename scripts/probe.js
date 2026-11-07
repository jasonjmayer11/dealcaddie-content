#!/usr/bin/env node
// Read-only recon for feature videos: logs in as the content account, runs one analysis,
// clicks every section tab and scrolls each one, then visits the other app pages.
// Saves viewport screenshots + page text to <outdir>. Writes nothing to the app
// (no save, no share, no client changes) beyond the one analysis.
// Usage: node scripts/probe.js "<zillow url>" <outdir>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [listing, outdir] = process.argv.slice(2);
fs.mkdirSync(outdir, { recursive: true });
const BASE = 'https://www.dealcaddie.ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = f => path.join(outdir, f);
const log = [];
const note = s => { console.log(s); log.push(s); };

async function scrollShots(page, prefix, max = 10) {
  // the signed-in shell scrolls inside an element, not the window: find the tallest scroller
  const sel = await page.evaluate(() => {
    let best = null, bh = 0;
    for (const el of document.querySelectorAll('body *')) {
      const cs = getComputedStyle(el);
      if (!/(auto|scroll)/.test(cs.overflowY) || el.scrollHeight <= el.clientHeight + 40) continue;
      if (el.scrollHeight > bh) { bh = el.scrollHeight; best = el; }
    }
    if (!best) return null;
    best.setAttribute('data-probe-scroll', '1');
    return { h: best.scrollHeight, ch: best.clientHeight };
  });
  for (let i = 0; i < max; i++) {
    await page.screenshot({ path: out(`${prefix}_${String(i).padStart(2, '0')}.png`) });
    const more = await page.evaluate(() => {
      const el = document.querySelector('[data-probe-scroll]') || document.scrollingElement;
      const before = el.scrollTop; el.scrollTop += el.clientHeight * 0.85;
      return el.scrollTop > before + 5;
    });
    if (!more) break;
    await sleep(900);
  }
  await page.evaluate(() => { const el = document.querySelector('[data-probe-scroll]'); if (el) el.scrollTop = 0; });
}

(async () => {
  const browser = await chromium.launch();
  const lctx = await browser.newContext();
  const lp = await lctx.newPage();
  await lp.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await lp.fill('#email', process.env.DC_EMAIL);
  await lp.fill('#password', process.env.DC_PASSWORD);
  await Promise.all([lp.waitForNavigation({ timeout: 60000 }).catch(() => {}), lp.click('form button[type="submit"]')]);
  const storageState = await lctx.storageState(); await lctx.close();

  const ctx = await browser.newContext({
    storageState, viewport: { width: 430, height: 932 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  });
  const page = await ctx.newPage();

  // ---- other pages first (cheap, read-only) ----
  for (const p of ['/dashboard', '/deals', '/clients', '/settings', '/agent/branding', '/pricing']) {
    try {
      const r = await page.goto(BASE + p, { waitUntil: 'networkidle', timeout: 45000 });
      await sleep(1200);
      const name = p.replace(/\//g, '_').replace(/^_/, '') || 'home';
      note(`PAGE ${p} -> ${page.url()} status=${r && r.status()}`);
      await scrollShots(page, `pg_${name}`, 6);
      fs.writeFileSync(out(`pg_${name}.txt`), await page.evaluate(() => document.body.innerText));
    } catch (e) { note(`PAGE ${p} failed: ${e.message}`); }
  }

  // ---- one analysis, every tab ----
  await page.goto(`${BASE}/analyze`, { waitUntil: 'networkidle', timeout: 60000 });
  const input = page.locator('input[name="address"]').first();
  await input.click(); await sleep(500);
  const sheet = page.locator('.dcs-sheet.on');
  const inSheet = await sheet.isVisible().catch(() => false);
  const box = inSheet ? sheet.locator('input[type="text"]').first() : input;
  await box.fill(listing); await sleep(400);
  if (inSheet) await box.press('Enter'); else await page.locator('button[type="submit"]').first().click();
  await page.waitForSelector('text=/Deal ScoreCard/i', { timeout: 90000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(2500);
  note('analysis loaded ' + page.url());

  // tab labels: short buttons in a horizontal strip near the top of the results
  const tabs = await page.evaluate(() => {
    const seen = new Set(), outL = [];
    for (const el of document.querySelectorAll('button, a, [role="tab"]')) {
      const t = (el.innerText || '').trim();
      const r = el.getBoundingClientRect();
      if (!t || t.length > 18 || r.width === 0 || seen.has(t)) continue;
      const strip = el.parentElement && el.parentElement.scrollWidth > el.parentElement.clientWidth;
      if (el.getAttribute('role') === 'tab' || strip) { seen.add(t); outL.push(t); }
    }
    return outL;
  });
  note('TABS ' + JSON.stringify(tabs));
  fs.writeFileSync(out('an_00_text.txt'), await page.evaluate(() => document.body.innerText));
  await scrollShots(page, 'an_00_overview', 12);

  let i = 1;
  for (const t of tabs) {
    const el = page.getByText(t, { exact: true }).first();
    if (!(await el.isVisible().catch(() => false))) continue;
    await el.click().catch(() => {}); await sleep(1800);
    const slug = `an_${String(i).padStart(2, '0')}_${t.replace(/[^a-z0-9]+/gi, '').slice(0, 14)}`;
    fs.writeFileSync(out(`${slug}.txt`), await page.evaluate(() => document.body.innerText));
    await scrollShots(page, slug, 6);
    i++;
  }
  fs.writeFileSync(out('log.txt'), log.join('\n'));
  await browser.close();
})().catch(e => { console.error('FAILED', e.message); fs.writeFileSync(out('log.txt'), log.join('\n') + '\nFAILED ' + e.message); process.exit(1); });
