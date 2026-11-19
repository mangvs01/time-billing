// Recette navigateur rc19 — saisies toujours éditables, facture émise immuable, écart post-facturation, décision (Chromium/Playwright).
// Conteneur JETABLE sur une COPIE de la base staging (saisies historiques réelles) : jamais le staging réel ; captures dans OUT_DIR (hors dépôt).
// Usage : PW_FILE=… BASE_URL=… DB_FILE=… OUT_DIR=… node recette-rc19.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path'), crypto = require('crypto'), { execFileSync } = require('child_process');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), DBFILE = process.env.DB_FILE, OUT = process.env.OUT_DIR || __dirname;
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const sql = q => JSON.parse(execFileSync('python3', ['-c', 'import sqlite3,json,sys;c=sqlite3.connect("file:%s?mode=ro"%sys.argv[1],uri=True);print(json.dumps(c.execute(sys.argv[2]).fetchall()))', DBFILE, q]).toString());
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
(async () => {
  const browser = await chromium.launch(); const errs = [];
  const plan = [['bureau', { width: 1360, height: 900 }, '2026-10-01', '2026-10-02'], ['mobile', { width: 390, height: 844 }, '2026-10-03', '2026-10-04']];
  for (const [label, vp, d0, d1] of plan) {
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH' }); const page = await ctx.newPage();
    page.on('pageerror', e => errs.push(`${label} ${page.url()} : ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${page.url()} : ${m.text()}`); });
    page.on('dialog', d => d.accept());
    const flash = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
    const noOverflow = async () => !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1));
    const shot = async n => page.screenshot({ path: path.join(OUT, `rc19-${label}-${n}.png`), fullPage: true });
    await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState();

    section = `${label} 1 saisie historique importée (mandat clôturé)`;
    const imp = sql("SELECT e.id,e.description FROM entries e JOIN projects p ON p.id=e.project_id WHERE e.import_batch_id IS NOT NULL AND p.active=0 AND e.start_time='' ORDER BY e.id LIMIT 1 OFFSET " + (label === 'bureau' ? 0 : 1))[0];
    await page.goto(`${BASE}/entries?origin=import`);
    check('liste des saisies importées : aucune « verrouillée », Modifier partout', (await page.locator('.lockbadge').count()) === 0 && (await page.locator('tr[data-entry] >> text=Modifier').count()) === (await page.locator('tr[data-entry]').count()));
    await page.goto(`${BASE}/entry/${imp[0]}/edit`); const b1 = await page.innerText('body');
    check('provenance affichée (fichier, onglet · ligne, lot, date d\'import, valeurs du classeur), formulaire actif', ['Provenance (import historique)', 'Time sheet CP.xlsx', ' · ligne ', 'Date d\'import', 'Valeurs lues dans le classeur'].every(x => b1.includes(x)) && await page.locator('button:has-text("Enregistrer la correction")').isEnabled() && (await page.locator('#work_date:disabled, #project_id:disabled, #description:disabled, #reason:disabled').count()) === 0, b1.slice(b1.indexOf('Provenance'), b1.indexOf('Provenance') + 400));
    check('pas de débordement horizontal (page de correction)', await noOverflow()); await shot('saisie-importee');
    await page.fill('#description', imp[1] + ' — corrigée (recette ' + label + ')'); await page.click('button:has-text("Enregistrer la correction")'); await page.waitForLoadState();
    check('description d\'une saisie importée corrigée par le formulaire', (await flash()).includes('modifiée') && sql('SELECT description FROM entries WHERE id=' + imp[0])[0][0].endsWith('(recette ' + label + ')'), await flash());

    section = `${label} 2 saisie facturée`;
    const pid = sql("SELECT id FROM projects WHERE name='NHAF 2026'")[0][0];
    await page.goto(BASE + '/?tab=time'); await page.selectOption('select[name=project_id]', String(pid)); await page.fill('input[name=work_date]', d0);
    await page.check('input[name=entry_mode][value=duration]'); await page.fill('#manualHours', '5'); await page.fill('input[name=description]', 'Atelier recette rc19 ' + label); await page.click('text=Enregistrer le temps');
    const eid = sql(`SELECT id FROM entries WHERE description='Atelier recette rc19 ${label}'`)[0][0];
    await page.request.post(BASE + '/invoice', { form: { project_id: String(pid), period_from: d0, period_to: d1, qty: '0.625', unit: 'day', rounding: 'exact', rounding_step: '0.25' } });
    const iid = sql('SELECT MAX(id) FROM invoices')[0][0]; const ip = await (await page.request.get(`${BASE}/issue/${iid}`)).text();
    const ex = (ip.match(/name="expected_reliquat" value="([^"]+)"/) || [])[1];
    await page.request.post(`${BASE}/issue/${iid}`, { form: Object.assign({ from_confirm: '1', reliquat_treatment: 'reporte' }, ex ? { expected_reliquat: ex } : {}) });
    const num = sql('SELECT number,status FROM invoices WHERE id=' + iid)[0]; check('facture émise (5 h = 0,625 j)', num[1] === 'issued', num);
    const pdf0 = sha(await (await page.request.get(`${BASE}/invoice/${iid}.pdf`)).body()); const snap0 = JSON.stringify(sql('SELECT invoice_id,frozen_at,header_json,annex_json,pdf_sha256 FROM invoice_snapshots WHERE invoice_id=' + iid));
    await page.goto(`${BASE}/entry/${eid}/edit`);
    check('avertissement explicite visible (facture citée), motif et case de confirmation', (await page.locator('#billedWarning').innerText()).includes(num[0]) && await page.locator('#reason').getAttribute('required') !== null && await page.locator('#confirm_billed').count() === 1);
    await page.fill('#manual_hours', '4.5'); await page.click('button:has-text("Enregistrer la correction")');
    check('sans motif : le navigateur bloque l\'envoi (champ obligatoire), saisie inchangée', sql('SELECT hours FROM entries WHERE id=' + eid)[0][0] === 5);
    await page.fill('#reason', 'durée réelle 4,5 h'); await page.check('#confirm_billed'); await shot('saisie-facturee'); await page.click('button:has-text("Enregistrer la correction")'); await page.waitForLoadState();
    const f2 = await flash();
    check('correction acceptée : « facture inchangée », écart −0,50 h (−0,0625 j)', f2.includes('inchangée') && f2.includes('−0,50 h') && f2.includes('−0,0625 j') && sql('SELECT hours FROM entries WHERE id=' + eid)[0][0] === 4.5, f2);
    check('facture émise strictement inchangée (copie figée, PDF octet pour octet)', sha(await (await page.request.get(`${BASE}/invoice/${iid}.pdf`)).body()) === pdf0 && JSON.stringify(sql('SELECT invoice_id,frozen_at,header_json,annex_json,pdf_sha256 FROM invoice_snapshots WHERE invoice_id=' + iid)) === snap0);

    section = `${label} 3 écart post-facturation, avoir, décision`;
    await page.goto(BASE + '/?tab=archive'); const line = page.locator(`tr[data-variance="${iid}"]`);
    check('historique : ligne d\'écart sous la facture', (await line.count()) === 1 && (await line.innerText()).includes('−0,50 h'), await line.count());
    check('pas de débordement horizontal (historique)', await noOverflow());
    await line.locator('text=Détail et décision').click(); await page.waitForLoadState(); const vb = await page.innerText('body');
    check('page d\'écart : 5,00 h figées, 4,50 h actuelles, −0,50 h, saisie « modifiée »', ['5,00 h', '4,50 h', '−0,50 h', 'modifiée'].every(x => vb.includes(x)), vb.slice(0, 400));
    check('pas de débordement horizontal (page d\'écart)', await noOverflow()); await shot('ecart');
    await page.locator('#varianceDecision a[href*="/credit?ecart=1"]').click(); await page.waitForLoadState();
    check('note de crédit pré-remplie (0,0625 j, motif)', (await page.inputValue('input[name=qty]')) === '0.0625' && (await page.inputValue('input[name=reason]')).includes('Ajustement des heures facturées'));
    await page.check('input[name=treatment][value=remboursement]'); await page.click('button:has-text("Créer le brouillon de note de crédit")'); await page.waitForLoadState();
    const cid = sql('SELECT MAX(id) FROM credit_notes')[0][0]; await page.request.post(`${BASE}/credit/${cid}/issue`);
    check('note de crédit émise', sql('SELECT status FROM credit_notes WHERE id=' + cid)[0][0] === 'issued');
    await page.goto(`${BASE}/invoice/${iid}/ecart`); await page.check('input[name=decision][value=avoir]'); await page.selectOption('#credit_note_id', String(cid)); await shot('decision');
    await page.click('button:has-text("Enregistrer la décision")'); await page.waitForLoadState();
    check('décision « note de crédit » enregistrée', (await flash()).includes('Décision enregistrée') && sql('SELECT decision,credit_note_id FROM invoice_variance_decisions WHERE invoice_id=' + iid).length === 1, await flash());
    await page.goto(BASE + '/?tab=dashboard'); check('tableau de bord : plus d\'alerte d\'écart pour cette facture', !((await page.locator('#variancesAlert').count()) && (await page.locator('#variancesAlert').innerText()).includes(num[0])));
    check('facture émise toujours identique après avoir et décision', sha(await (await page.request.get(`${BASE}/invoice/${iid}.pdf`)).body()) === pdf0);
    await ctx.close();
  }
  section = 'global'; check('aucune erreur console / JS', errs.length === 0, errs.join(' ; '));
  await browser.close();
  const ko = results.filter(r => !r.ok).length; console.log(`RÉSULTAT rc19 navigateur : ${results.length - ko}/${results.length} OK, ${ko} KO`); process.exit(ko ? 1 : 0);
})();
