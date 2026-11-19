// Recette d'affichage RC10 : toutes les pages principales à 390 px (téléphone), 820 px (tablette) et 1400 px (bureau) :
// aucun débordement horizontal du document, aucune erreur console. Conteneur jetable déjà rempli de données fictives.
// Usage : PW_FILE=… BASE_URL=… DB_FILE=… OUT=<dossier> node recette-responsive.js
const { chromium } = require('/root/node_modules/playwright'); const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), DB = process.env.DB_FILE, OUT = process.env.OUT;
const sql = q => JSON.parse(execFileSync('python3', ['-c', 'import sqlite3,json,sys;c=sqlite3.connect("file:%s?mode=ro"%sys.argv[1],uri=True);print(json.dumps(c.execute(sys.argv[2]).fetchall()))', DB, q]).toString());
(async () => {
  const one = q => { const r = sql(q); return r.length ? r[0][0] : null; };
  const ids = { entry: one("SELECT id FROM entries WHERE import_batch_id IS NULL ORDER BY id LIMIT 1"), draft: one("SELECT id FROM invoices WHERE status='draft' LIMIT 1"), issued: one("SELECT id FROM invoices WHERE status='issued' ORDER BY id LIMIT 1"),
    credit: one("SELECT id FROM credit_notes WHERE status='issued' ORDER BY id LIMIT 1"), project: one("SELECT id FROM projects LIMIT 1") };
  const pages = ['/?tab=dashboard', '/?tab=time', '/?tab=mandates', '/?tab=billing', '/?tab=archive', '/?tab=migration', '/?tab=settings', '/entries', '/login',
    ids.entry && `/entry/${ids.entry}/edit`, ids.draft && `/issue/${ids.draft}`, ids.draft && `/invoice/${ids.draft}/edit`, ids.issued && `/invoice/${ids.issued}/credit`, ids.credit && `/credit/${ids.credit}`, ids.project && `/project/${ids.project}/edit`].filter(Boolean);
  const browser = await chromium.launch(); const results = []; const errs = [];
  for (const [label, w, h] of [['tel', 390, 844], ['tablette', 820, 1100], ['bureau', 1400, 900]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, locale: 'fr-CH' }); const p = await ctx.newPage();
    p.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${p.url()} ${m.text()}`); }); p.on('pageerror', e => errs.push(`${label} ${e.message}`));
    await p.goto(BASE + '/login'); const loginOverflow = await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    await p.fill('input[name=username]', 'admin'); await p.fill('input[name=password]', PW); await p.click('button'); await p.waitForLoadState();
    for (const u of pages) {
      const r = await p.goto(BASE + u); const ov = u === '/login' ? loginOverflow : await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      const clipped = await p.evaluate(() => [...document.querySelectorAll('button,a.btn,a.btnlink,input:not([type=hidden]),select')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > innerWidth + 1 || r.left < -1) && !e.closest('.tablewrap,.panel[style*="overflow"],table,.sidebar .tabs'); }).length);
      results.push({ label, u, status: r.status(), overflow: ov, clipped }); console.log(`${ov || clipped ? 'FAIL' : 'PASS'} ${label} ${u} http ${r.status()} débordement=${ov} éléments hors écran=${clipped}`);
      if (OUT && label === 'tel') await p.screenshot({ path: path.join(OUT, `tel-${u.replace(/[^a-z0-9]+/gi, '_')}.png`), fullPage: true });
    }
    await ctx.close();
  }
  await browser.close(); const bad = results.filter(r => r.overflow || r.clipped || r.status >= 400);
  console.log(`RESULT: ${results.length - bad.length}/${results.length} pages sans défaut — erreurs console : ${errs.length}`); errs.slice(0, 5).forEach(e => console.log('console:', e));
  process.exit(bad.length || errs.length ? 1 : 0);
})();
