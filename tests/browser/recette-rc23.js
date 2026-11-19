// Recette navigateur rc23 — factures historiques : « Corriger » (ligne rejetée + ligne corrigée validée) et « Ajouter » (Chromium/Playwright).
// Conteneur JETABLE sur une COPIE d'une sauvegarde du staging (24 historiques « à valider ») : jamais le staging réel ; captures dans OUT_DIR (hors dépôt).
// Usage : PW_FILE=… BASE_URL=… DB_FILE=… OUT_DIR=… node recette-rc23.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), DBFILE = process.env.DB_FILE, OUT = process.env.OUT_DIR || __dirname;
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const sql = q => JSON.parse(execFileSync('python3', ['-c', 'import sqlite3,json,sys;c=sqlite3.connect("file:%s?mode=ro"%sys.argv[1],uri=True);print(json.dumps(c.execute(sys.argv[2]).fetchall()))', DBFILE, q]).toString());
const one = q => sql(q)[0][0];
(async () => {
  const browser = await chromium.launch(); const errs = [];
  const n0 = one('SELECT COUNT(*) FROM historical_invoices');
  const plan = [['bureau', { width: 1360, height: 900 }], ['mobile', { width: 390, height: 844 }]];
  for (const [label, vp] of plan) {
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH' }); const page = await ctx.newPage();
    page.on('pageerror', e => errs.push(`${label} ${page.url()} : ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${page.url()} : ${m.text()}`); });
    page.on('dialog', d => d.accept());
    const flash = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
    const noOverflow = async () => !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1));
    const shot = async n => page.screenshot({ path: path.join(OUT, `rc23-${label}-${n}.png`), fullPage: true });
    await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState();

    section = `${label} 1 page Factures historiques`;
    await page.goto(BASE + '/historique'); const body = await page.innerText('body');
    check('explication « Corriger » / « Ajouter » affichée', body.includes('Corriger') && (await page.locator('#historicalCorrection a[href="/historique/ajouter"]').count()) === 1, body.slice(0, 300));
    check('un lien « Corriger » par ligne non remplacée', (await page.locator('a[href$="/corriger"]').count()) === one('SELECT COUNT(*) FROM historical_invoices h WHERE NOT EXISTS (SELECT 1 FROM historical_invoices x WHERE x.status=\'validated\' AND x.source_sheet=h.source_sheet AND x.source_cell LIKE h.source_cell||\' (correction %\') '), await page.locator('a[href$="/corriger"]').count());
    check('pas de débordement horizontal (registre)', await noOverflow()); await shot('registre');

    // bureau : la ligne D2 (M15, 4 550) est corrigée à 4 600 ; mobile : la ligne M8 (STC GEM Avril) reçoit une date future (refus), puis on ajoute une facture manquante
    if (label === 'bureau') {
      section = `${label} 2 corriger une ligne (M15)`;
      const [hid, amt] = sql("SELECT id,amount_ht FROM historical_invoices WHERE source_sheet='SUIVI 2026' AND source_cell='M15'")[0];
      await page.goto(`${BASE}/historique/${hid}/corriger`);
      check('formulaire prérempli avec les valeurs enregistrées', Number(await page.inputValue('#amount_ht')) === amt && (await page.inputValue('#invoice_date')) === one(`SELECT invoice_date FROM historical_invoices WHERE id=${hid}`), [await page.inputValue('#amount_ht'), amt]);
      check('pas de débordement horizontal (correction)', await noOverflow()); await shot('corriger');
      await page.fill('#amount_ht', '4600'); await page.fill('#motif', '');
      await page.click('button:has-text("Enregistrer la correction")');
      check('motif vide : le navigateur bloque l\'envoi (champ obligatoire), rien d\'écrit', page.url().endsWith(`/historique/${hid}/corriger`) && one('SELECT COUNT(*) FROM historical_invoices') === n0, page.url());
      await page.fill('#motif', 'recette rc23 bureau : montant réel 4 600'); await page.click('button:has-text("Enregistrer la correction")'); await page.waitForLoadState();
      const f = await flash(); const nw = one('SELECT MAX(id) FROM historical_invoices');
      check('message : ligne remplacée par la nouvelle, validée', f.includes(`la ligne n° ${hid} est remplacée par la ligne n° ${nw}, validée`), f);
      const [st, rs] = sql(`SELECT status,source_cell FROM historical_invoices WHERE id IN (${hid},${nw}) ORDER BY id`).map(r => r);
      check('base : ligne d\'origine rejetée, ligne « M15 (correction 1) » validée à 4 600, valeurs du classeur conservées',
        one(`SELECT status FROM historical_invoices WHERE id=${hid}`) === 'rejected' && one(`SELECT amount_ht FROM historical_invoices WHERE id=${hid}`) === amt
        && JSON.stringify(sql(`SELECT status,source_cell,amount_ht FROM historical_invoices WHERE id=${nw}`)[0]) === JSON.stringify(['validated', 'M15 (correction 1)', 4600]), JSON.stringify([st, rs]));
      check('journal d\'audit : historical_invoice_corrected', one("SELECT COUNT(*) FROM audit WHERE event='historical_invoice_corrected'") === 1);
      check('registre : « remplacée par la ligne n° … (validée) » sur l\'origine', (await page.locator('.hreplaced', { hasText: `remplacée par la ligne n° ${nw}` }).count()) === 1, await page.locator('.hreplaced').allInnerTexts());
      check('registre : provenance « SUIVI 2026!M15 (correction 1) » affichée', (await page.innerText('body')).includes('M15 (correction 1)'));
      check('pas de débordement horizontal (registre après correction)', await noOverflow()); await shot('registre-apres-correction');
    } else {
      section = `${label} 2 correction refusée (date future)`;
      const hid = one("SELECT id FROM historical_invoices WHERE source_sheet='SUIVI 2026' AND source_cell='M8'"); const n1 = one('SELECT COUNT(*) FROM historical_invoices');
      await page.goto(`${BASE}/historique/${hid}/corriger`); check('pas de débordement horizontal (correction, mobile)', await noOverflow());
      await page.fill('#invoice_date', '2099-01-01'); await page.fill('#motif', 'recette rc23 mobile : date future'); await page.click('button:has-text("Enregistrer la correction")'); await page.waitForLoadState();
      check('refus affiché, saisie conservée, rien d\'écrit', (await flash()).includes('Correction non enregistrée') && (await page.inputValue('#invoice_date')) === '2099-01-01' && one('SELECT COUNT(*) FROM historical_invoices') === n1 && one(`SELECT status FROM historical_invoices WHERE id=${hid}`) === 'proposed', await flash());
      await shot('correction-refusee');

      section = `${label} 3 ajouter une facture manquante`;
      const [pid, pname] = sql("SELECT id,name FROM projects WHERE active=1 ORDER BY name LIMIT 1")[0];
      await page.goto(BASE + '/historique/ajouter'); check('pas de débordement horizontal (ajout)', await noOverflow()); await shot('ajouter');
      await page.selectOption('#project_id', String(pid)); await page.fill('#invoice_date', '2026-09-30'); await page.fill('#qty_days', '1'); await page.fill('#amount_ht', '650');
      await page.fill('#motif', 'recette rc23 mobile : facture absente du classeur'); await page.click('button:has-text("Ajouter la facture historique")'); await page.waitForLoadState();
      const f = await flash(); const nw = one('SELECT MAX(id) FROM historical_invoices');
      check('message : facture ajoutée, validée', f.includes(`Facture historique ajoutée (${pname}) : ligne n° ${nw}, validée`), f);
      check('base : « ajout manuel » « n° 1 », validée, 1 j, 650', JSON.stringify(sql(`SELECT source_sheet,source_cell,status,qty_days,amount_ht FROM historical_invoices WHERE id=${nw}`)[0]) === JSON.stringify(['ajout manuel', 'n° 1', 'validated', 1, 650]), JSON.stringify(sql(`SELECT * FROM historical_invoices WHERE id=${nw}`)));
      check('journal d\'audit : historical_invoice_added', one("SELECT COUNT(*) FROM audit WHERE event='historical_invoice_added'") === 1);
      await page.goto(BASE + '/historique/ajouter'); await page.selectOption('#project_id', String(pid)); await page.fill('#invoice_date', '2026-09-30'); await page.fill('#qty_days', '1'); await page.fill('#amount_ht', '650');
      await page.fill('#motif', 'recette rc23 mobile : doublon'); await page.click('button:has-text("Ajouter la facture historique")'); await page.waitForLoadState();
      check('même facture ajoutée deux fois : refusée (jamais comptée deux fois)', (await flash()).includes('Facture historique non ajoutée') && one('SELECT MAX(id) FROM historical_invoices') === nw, await flash());
      await page.goto(BASE + '/historique'); check('registre : « ajout manuel n° 1 » affiché', (await page.innerText('body')).includes('ajout manuel n° 1'));
      check('pas de débordement horizontal (registre, mobile)', await noOverflow()); await shot('registre-apres-ajout');
    }
    await ctx.close();
  }
  section = 'global';
  check('aucune erreur JavaScript ni violation CSP dans la console', errs.length === 0, errs.join(' | '));
  await browser.close();
  const ko = results.filter(r => !r.ok).length; console.log(`RÉSULTAT rc23 navigateur : ${results.length - ko}/${results.length} OK, ${ko} KO`); process.exit(ko ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
