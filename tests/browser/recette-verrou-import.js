// Recette navigateur — verrou partiel des saisies importées (REVUE-CODE-RC19) : une saisie que l'import accepte (durée > 24 h ou < 0,01 h,
// horaires avec secondes, début = fin, horaire seul, description longue ou sur plusieurs lignes) se corrige depuis le formulaire, sans que
// le navigateur bloque l'envoi (min/max/step) ni que l'application perde une valeur non modifiée (Chromium/Playwright).
// Conteneur JETABLE sur une COPIE d'une sauvegarde du staging, saisies « NAV … » ajoutées sur la copie : jamais le staging réel.
// Copie préparée par preparer-copie-verrou-import.py. Usage : PW_FILE=… BASE_URL=… DB_FILE=… OUT_DIR=… node recette-verrou-import.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), DBFILE = process.env.DB_FILE, OUT = process.env.OUT_DIR || __dirname;
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const sql = (q, ...a) => JSON.parse(execFileSync('python3', ['-c', 'import sqlite3,json,sys;c=sqlite3.connect("file:%s?mode=ro"%sys.argv[1],uri=True);c.row_factory=sqlite3.Row;print(json.dumps([dict(r) for r in c.execute(sys.argv[2],sys.argv[3:]).fetchall()]))', DBFILE, q, ...a]).toString());
const entry = desc => sql("SELECT * FROM entries WHERE description LIKE ? ORDER BY id DESC LIMIT 1", desc)[0];
(async () => {
  const browser = await chromium.launch(); const errs = [];
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: 'fr-CH' }); const page = await ctx.newPage();
  page.on('pageerror', e => errs.push(`${page.url()} : ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${page.url()} : ${m.text()}`); });
  page.on('dialog', d => d.accept());
  const flash = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
  await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState();
  // [libellé, motif LIKE, action dans le formulaire, valeurs attendues après]
  const cases = [
    ['durée 25 h', 'NAV gt24', async () => page.fill('#description', 'NAV gt24 b'), { description: 'NAV gt24 b', hours: 25 }],
    ['durée 0,005 h', 'NAV lt001', async () => page.fill('#description', 'NAV lt001 b'), { description: 'NAV lt001 b', hours: 0.005 }],
    ['horaires avec secondes', 'NAV secondes', async () => page.fill('#description', 'NAV secondes b'), { description: 'NAV secondes b', start_time: '07:05:30', end_time: '09:10:15', hours: 2.08 }],
    ['début = fin', 'NAV debut=fin', async () => page.fill('#description', 'NAV debut=fin b'), { description: 'NAV debut=fin b', start_time: '08:00', end_time: '08:00', hours: 3 }],
    ['horaire seul', 'NAV horaire seul', async () => page.fill('#description', 'NAV horaire seul b'), { description: 'NAV horaire seul b', start_time: '08:00', end_time: '', hours: 2 }],
    ['description sur 2 lignes', 'NAV multi%', async () => page.fill('#manual_hours', '3'), { description: 'NAV multi l1\nl2', hours: 3 }],
    ['description de 1 109 caractères', 'NAV long %', async () => page.fill('#manual_hours', '3'), { hours: 3 }],
    // relecture adverse : champ à pas d'une seconde (« 10:00:00 » envoyé), début = fin à la minute près, durée minuscule (« 5e-05 »)
    ['horaires avec secondes ramenés à la minute', 'NAV sec2', async () => { await page.fill('#start_time', '07:05:00'); await page.fill('#end_time', '10:00:00'); }, { start_time: '07:05', end_time: '10:00', hours: 175 / 60 }],
    ['début = fin à la minute près', 'NAV minute', async () => page.fill('#description', 'NAV minute b'), { description: 'NAV minute b', start_time: '08:00:30', end_time: '08:00', hours: 0.5 }],
    ['durée 0,00005 h', 'NAV minuscule', async () => page.fill('#description', 'NAV minuscule b'), { description: 'NAV minuscule b', hours: 5e-05 }],
  ];
  for (const [label, like, act, want] of cases) {
    section = label; const e0 = entry(like);
    await page.goto(`${BASE}/entry/${e0.id}/edit`); await act();
    await page.click('button:has-text("Enregistrer la correction")'); await page.waitForLoadState();
    const e1 = sql('SELECT * FROM entries WHERE id=?', String(e0.id))[0], msg = await flash();
    check('formulaire envoyé et correction enregistrée', !page.url().includes('/edit') && msg.includes(`Saisie n° ${e0.id} modifiée`), `${page.url()} ${msg}`);
    check('aucun message « Avertissements non calculés »', !msg.includes('non calculés'), msg);
    const bad = Object.entries(want).filter(([k, v]) => e1[k] !== v);
    check('valeurs attendues en base (valeurs non modifiées conservées)', bad.length === 0, JSON.stringify(bad.map(([k]) => [k, e1[k]])));
    if (label.startsWith('description de')) check('description longue conservée', e1.description === e0.description);
    check('une seule correction tracée', sql('SELECT COUNT(*) n FROM entry_changes WHERE entry_id=?', String(e0.id))[0].n === 1);
  }
  section = 'nouvelle valeur hors limites';
  const g = entry('NAV gt24%');
  await page.goto(`${BASE}/entry/${g.id}/edit`); await page.fill('#manual_hours', '26'); await page.click('button:has-text("Enregistrer la correction")');
  check('26 h bloqué par le navigateur (max = valeur enregistrée), rien d\'écrit', page.url().includes('/edit') && entry('NAV gt24%').hours === 25, page.url());
  await page.screenshot({ path: path.join(OUT, 'verrou-import-gt24.png'), fullPage: true });
  section = 'page';
  check('aucune erreur JavaScript / CSP', errs.length === 0, errs.join(' ; '));
  await browser.close();
  const ko = results.filter(r => !r.ok).length; console.log(`${results.length - ko}/${results.length}`); process.exit(ko ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
