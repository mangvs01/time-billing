// Captures d'audit UX (conteneur jetable tb-rc10-ux, données fictives). Usage: node shots.js <prefix> <width> <height> [tab ...]
const { chromium } = require('/root/node_modules/playwright'); const fs = require('fs'), path = require('path');
const BASE = 'http://127.0.0.1:8190', D = __dirname, PW = fs.readFileSync(path.join(D, 'pw.txt'), 'utf8').trim();
const [prefix, w, h, ...tabs] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: +w, height: +h }, locale: 'fr-CH' }); const p = await ctx.newPage();
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push(e.message));
  await p.goto(BASE + '/login'); await p.screenshot({ path: path.join(D, 'ecrans', `${prefix}-login.png`) });
  await p.fill('input[name=username]', 'admin'); await p.fill('input[name=password]', PW); await p.click('button'); await p.waitForLoadState();
  for (const t of (tabs.length ? tabs : ['dashboard', 'time', 'mandates', 'billing', 'archive', 'migration', 'settings'])) {
    await p.goto(`${BASE}/?tab=${t}`); await p.screenshot({ path: path.join(D, 'ecrans', `${prefix}-${t}.png`), fullPage: true });
    const ov = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2); console.log(t, 'overflow-x:', ov);
  }
  console.log('console errors:', errs.length, errs.slice(0, 3)); await b.close();
})();
