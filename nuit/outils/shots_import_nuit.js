// Aperçu d'import (prévisualisation seulement, jamais « Valider l'import ») sur l'instance jetable : captures + contrôles simples.
// Usage : BASE=http://127.0.0.1:8300 OUT=… W=1440 H=900 PFX=bureau XLSX=/tmp/nuit/dev-data/releve-fictif-octobre-2025.xlsx node shots_import_nuit.js
const { chromium } = require('/root/node_modules/playwright'); const fs = require('fs');
const { BASE, OUT, XLSX } = process.env, W = +(process.env.W || 1440), H = +(process.env.H || 900), PFX = process.env.PFX || 'bureau';
const PW = fs.readFileSync('/root/demo-time-billing/mot-de-passe.txt', 'utf8').trim();
(async () => {
  fs.mkdirSync(OUT, { recursive: true }); const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: W, height: H }, locale: 'fr-CH' })).newPage();
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push(e.message));
  let fails = 0; const check = (n, ok, d = '') => { if (!ok) fails++; console.log((ok ? 'PASS ' : 'FAIL ') + n + (ok ? '' : ' :: ' + d)); };
  await p.goto(BASE + '/login'); await p.fill('input[name=username]', 'admin'); await p.fill('input[name=password]', PW); await p.click('button'); await p.waitForLoadState();
  await p.goto(BASE + '/?tab=migration'); await p.setInputFiles('input[name=workbook]', XLSX);
  await Promise.all([p.waitForURL(/import\/review/), p.locator('input[name=workbook]').evaluate(f => f.form.submit())]); await p.waitForLoadState('networkidle');
  check('barre latérale présente', await p.locator('aside.sidebar').count() === 1);
  check('entrée « Import historique » active', await p.locator('aside.sidebar a.active', { hasText: 'Import historique' }).count() === 1);
  check('aucun débordement horizontal', await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  const total = await p.locator('tr[data-status]:visible').count();
  await p.click('#filters button[data-f="valide"]'); const v = await p.locator('tr[data-status]:visible').count();
  check('pastille « Valides » active et filtre', (await p.locator('#filters button.active').innerText()).includes('Valides') && v <= total, `${total} -> ${v}`);
  const bg = await p.locator('#filters button.active').evaluate(e => getComputedStyle(e).backgroundColor); check('pastille active au bleu électrique (pas de bleu marine)', !/24, 59, 85/.test(bg), bg);
  await p.click('#filters button[data-f="all"]');
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(300); await p.screenshot({ path: `${OUT}/${PFX}-import-apercu.png`, fullPage: true });
  check('aucune erreur console', errs.length === 0, errs.join(' ; '));
  await b.close(); console.log(`import : ${fails} échec(s)`); process.exit(fails ? 1 : 0);
})();
