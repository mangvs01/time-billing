// Recette navigateur RC10 — gestion des saisies de temps (Chromium/Playwright). Données exclusivement fictives, conteneur jetable.
// Usage : PW_FILE=… BASE_URL=… DB_FILE=… node recette-saisies.js phase1|phase2
const { chromium } = require('/root/node_modules/playwright');
const EXPECT = process.env.EXPECT_VERSION; if (!EXPECT) throw new Error('EXPECT_VERSION manquant (ex. 9.2-rc12)');
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const J = __dirname, R = path.dirname(J), BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), DBFILE = process.env.DB_FILE;
const PHASE = process.argv[2] || 'phase1', STATE = path.join(J, 'etat-saisies.json');
const results = [], consoleErrors = []; let section = '', shotN = PHASE === 'phase1' ? 300 : 400;
const check = (name, ok, detail = '') => { results.push({ phase: PHASE, section, name, ok: !!ok, detail: ok ? '' : String(detail).slice(0, 400) }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const sql = q => JSON.parse(execFileSync('python3', ['-c', 'import sqlite3,json,sys;c=sqlite3.connect("file:%s?mode=ro"%sys.argv[1],uri=True);print(json.dumps(c.execute(sys.argv[2]).fetchall()))', DBFILE, q]).toString());
(async () => {
  const browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: 'fr-CH' }); const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`${page.url()} : ${m.text()}`); }); page.on('pageerror', e => consoleErrors.push(`${page.url()} : ${e.message}`));
  let dialogs = []; page.on('dialog', async d => { dialogs.push(d.message()); await d.accept(); });
  const shot = async (n, full = true) => { shotN++; await page.screenshot({ path: path.join(R, 'ecrans', `${shotN}-${n}.png`), fullPage: full }); };
  const step = async (name, fn) => { section = name; try { await fn(); } catch (e) { check('exception', false, e.stack); try { await shot('ERREUR'); } catch (_) {} } };
  const flash = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
  const login = async () => { await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState(); };
  const rowsOn = async () => page.locator('tr[data-entry]').count();
  const noOverflow = async () => !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1));
  await login();
  const state = PHASE === 'phase1' ? {} : JSON.parse(fs.readFileSync(STATE));

  if (PHASE === 'phase1') {
    await step('0 préparation fictive', async () => {
      await page.request.post(BASE + '/settings', { form: { issuer_name: 'Bureau Fictif Saisies Sàrl', issuer_address: 'Rue Test 1\n1000 Lieu', account_holder: 'Bureau Fictif Saisies Sàrl', iban: 'CH00 0000 0000 0000 0000 0', issuer_vat_number: 'CHE-000.000.000 TVA (fictif)', payment_terms: 'Paiement à 30 jours sur le compte:' } });
      for (const n of ['Mandat Saisies A', 'Mandat Saisies B']) await page.request.post(BASE + '/project', { form: { name: n, rate: '800', day_hours: '8', vat: '8.1', ordered_days: '20', client: 'Client Fictif', billing_address: 'Client Fictif SA\nRue 1\n1000 Lieu', start_date: '2026-01-01', duration_months: '12' } });
      await page.goto(BASE + '/?tab=dashboard'); check('panneau « Pour commencer » absent une fois mandat et émetteur renseignés', !(await page.content()).includes('Pour commencer'));
    });
    await step('1 saisie par l\'interface (début/fin puis durée directe)', async () => {
      await page.goto(BASE + '/?tab=time');
      await page.selectOption('select[name=project_id]', { label: 'Mandat Saisies A' }); await page.fill('input[name=work_date]', '2026-09-07');
      await page.fill('#startTime', '08:30'); await page.fill('#endTime', '12:15');
      check('durée calculée affichée avant envoi', /3\s*h\s*45/.test(await page.innerText('#clockFields')), await page.innerText('#clockFields'));
      await page.fill('input[name=description]', 'Atelier cadrage (fictif)'); await shot('saisie-debut-fin'); await page.click('text=Enregistrer le temps');
      check('saisie début/fin enregistrée', (await flash()).includes('3,75 h'), await flash());
      await page.check('input[name=entry_mode][value=duration]'); await page.fill('input[name=work_date]', '2026-09-08');
      check('en mode durée, début et fin ne sont plus requis', await page.locator('#startTime').isDisabled() && await page.locator('#manualHours').isEnabled());
      await page.fill('#manualHours', '4.25'); await page.fill('input[name=description]', 'Rédaction note (fictif)'); await page.click('text=Enregistrer le temps');
      check('saisie par durée directe enregistrée', (await flash()).includes('4,25 h'), await flash());
      for (let i = 0; i < 3; i++) await page.request.post(BASE + '/entry', { form: { work_date: `2026-09-1${i}`, project_id: '2', entry_mode: 'duration', manual_hours: '2', description: `Étude B ${i} (fictif)` } });
      await page.goto(BASE + '/?tab=time'); check('« Dernières saisies » visible sur l\'onglet Saisie avec Modifier', (await page.locator('text=Modifier').count()) >= 5);
      await shot('onglet-saisie-dernieres');
    });
    await step('2 liste, filtres, export', async () => {
      await page.click('text=Voir, filtrer, corriger'); await page.waitForURL(/\/entries/);
      check('5 saisies listées', await rowsOn() === 5, await rowsOn());
      check('total affiché 14,00 h', (await page.innerText('.sum')).includes('14,00'), await page.innerText('.sum'));
      await page.selectOption('#f_project', { label: 'Mandat Saisies A' }); await page.click('button:has-text("Filtrer")'); await page.waitForLoadState();
      check('filtre mandat : 2 saisies', await rowsOn() === 2, await rowsOn());
      await page.fill('#f_q', 'cadrage'); await page.click('button:has-text("Filtrer")'); await page.waitForLoadState();
      check('filtre texte : 1 saisie', await rowsOn() === 1, await rowsOn()); await shot('liste-filtree');
      const [dl] = await Promise.all([page.waitForEvent('download'), page.click('text=Exporter ces saisies')]);
      const f = path.join(R, 'dl', 'saisies-filtrees.csv'); await dl.saveAs(f); const csv = fs.readFileSync(f, 'utf8');
      check('export CSV : en-tête + 1 ligne filtrée', csv.replace(/^﻿/, '').trim().split(/\r?\n/).length === 2 && csv.includes('Atelier cadrage'), csv.slice(0, 200));
      await page.click('text=Effacer les filtres'); await page.waitForLoadState(); check('filtres effacés : 5 saisies', await rowsOn() === 5);
    });
    await step('3 correction par l\'interface', async () => {
      await page.locator('tr[data-entry]', { hasText: 'Rédaction note' }).locator('text=Modifier').click(); await page.waitForURL(/\/edit/);
      check('formulaire prérempli en mode durée', (await page.inputValue('#manual_hours')) === '4.25' && await page.isChecked('input[value=duration]'));
      await page.check('input[value=clock]'); await page.fill('#start_time', '14:00'); await page.fill('#end_time', '16:30'); await page.selectOption('#project_id', { label: 'Mandat Saisies B' });
      check('durée recalculée à l\'écran', /2\s*h\s*30/.test(await page.innerText('#calcDuration')));
      await page.fill('#description', 'Rédaction note — corrigée (fictif)'); await shot('edition-saisie'); await page.click('text=Enregistrer la correction'); await page.waitForURL(/\/entries/);
      check('message de correction + historique annoncé', (await flash()).includes('modifiée') && (await flash()).includes('historique'), await flash());
      const row = page.locator('tr[data-entry]', { hasText: 'corrigée' }); check('ligne corrigée : mandat B, 14:00 – 16:30, 2,50 h', (await row.innerText()).includes('Mandat Saisies B') && (await row.innerText()).includes('14:00 – 16:30') && (await row.innerText()).includes('2,50'), await row.innerText());
      const id = await row.getAttribute('data-entry'); state.editedId = id;
      await page.goto(`${BASE}/entry/${id}/edit`); check('historique visible sur la page de la saisie (avant → après)', (await page.innerText('body')).includes('Historique des corrections') && (await page.innerText('body')).includes('Rédaction note (fictif)'));
      await page.check('input[value=duration]'); await page.fill('#manual_hours', '30'); await page.click('text=Enregistrer la correction');
      check('durée > 24 h bloquée par le navigateur (max=24) : la page n\'envoie rien', page.url().includes('/edit') && !(await page.locator('#manual_hours').evaluate(e => e.checkValidity())));
      const r3 = await page.request.post(`${BASE}/entry/${id}/edit`, { form: { work_date: '2026-09-09', project_id: '2', entry_mode: 'duration', manual_hours: '30', description: 'x' } });
      check('même valeur envoyée directement : refusée par le serveur avec explication, saisie inchangée', (await r3.text()).includes('supérieure à 24 h') && sql('SELECT hours FROM entries WHERE id=' + id)[0][0] === 2.5);
      check('base : 1 trace de correction', sql('SELECT COUNT(*) FROM entry_changes')[0][0] === 1, JSON.stringify(sql('SELECT COUNT(*) FROM entry_changes')));
    });
    await step('4 suppression par l\'interface', async () => {
      await page.goto(BASE + '/entries'); const before = await rowsOn(); dialogs = [];
      await page.locator('tr[data-entry]', { hasText: 'Étude B 2' }).locator('button:has-text("Supprimer")').click(); await page.waitForLoadState();
      check('confirmation demandée avant suppression', dialogs.length === 1 && dialogs[0].includes('historique'), dialogs.join('|'));
      check('ligne retirée et message', await rowsOn() === before - 1 && (await flash()).includes('supprimée'), await flash());
      check('base : copie de la saisie supprimée conservée', sql("SELECT COUNT(*) FROM entry_changes WHERE action='delete'")[0][0] === 1 && sql("SELECT COUNT(*) FROM entries WHERE description LIKE 'Étude B 2%'")[0][0] === 0);
    });
    await step('5 saisie facturée : toujours modifiable, facture émise inchangée (rc19)', async () => {
      await page.request.post(BASE + '/invoice', { form: { project_id: '1', period_from: '2026-09-01', period_to: '2026-09-30', qty: '0.46875', rounding: 'exact', rounding_step: '0.25' } });   // rc25 : 3 h 45 enregistrées = 0,46875 j ; le contrôle 14 (jamais dérogeable) interdit de facturer au-delà du travail enregistré
      const iid = sql('SELECT MAX(id) FROM invoices')[0][0];
      await page.request.post(`${BASE}/issue/${iid}`, { form: { reliquat_treatment: 'reporte' } });   // rc25 : aucune dérogation (quantité = travail enregistré)
      check('facture émise', sql('SELECT status FROM invoices WHERE id=?'.replace('?', iid))[0][0] === 'issued');
      state.pdfSha = require('crypto').createHash('sha256').update(await (await page.request.get(`${BASE}/invoice/${iid}.pdf`)).body()).digest('hex'); state.iid = iid;
      await page.goto(BASE + '/entries?project=1'); const t = await page.innerText('#entriesTable');
      check('liste : aucune saisie « verrouillée », un bouton Modifier par ligne, badge « facturée »', await page.locator('.lockbadge').count() === 0 && await page.locator('tr[data-entry] >> text=Modifier').count() === await rowsOn() && t.includes('facturée 2026-09'), t.slice(0, 300));
      await shot('liste-facturee');
      const eid = sql("SELECT id FROM entries WHERE description LIKE 'Atelier cadrage%'")[0][0]; state.billedId = eid; state.billedHours = sql('SELECT hours FROM entries WHERE id=' + eid)[0][0];
      await page.goto(`${BASE}/entry/${eid}/edit`); const body = await page.innerText('body');
      check('page de la saisie facturée : avertissement explicite, formulaire actif, motif et confirmation', body.includes('Saisie déjà facturée') && body.includes('2026-09') && await page.locator('button:has-text("Enregistrer la correction")').isEnabled() && await page.locator('#confirm_billed').count() === 1);
      const r = await page.request.post(`${BASE}/entry/${eid}/delete`, { form: {} }); check('POST direct de suppression sans motif : aucun effet', sql('SELECT COUNT(*) FROM entries WHERE id=' + eid)[0][0] === 1);
      await page.fill('#reason', 'durée réelle (recette)'); await page.check('#confirm_billed');
      await page.check('input[name=entry_mode][value=duration]'); await page.fill('#manual_hours', String(state.billedHours - 0.5)); await shot('saisie-facturee-confirmation');
      await page.click('button:has-text("Enregistrer la correction")'); await page.waitForLoadState();
      const f = await flash();
      check('correction enregistrée : facture inchangée, écart post-facturation −0,50 h affiché', f.includes('modifiée') && f.includes('inchangée') && f.includes('−0,50 h'), f);
      check('PDF de la facture émise identique octet pour octet', require('crypto').createHash('sha256').update(await (await page.request.get(`${BASE}/invoice/${iid}.pdf`)).body()).digest('hex') === state.pdfSha);
      await page.goto(`${BASE}/invoice/${iid}/ecart`); const v = await page.innerText('body');
      check('page d\'écart : −0,50 h, saisie « modifiée », décision à prendre', v.includes('−0,50 h') && v.includes('modifiée') && v.includes('Décision'), v.slice(0, 300)); await shot('ecart-post-facturation');
      await page.goto(BASE + '/?tab=dashboard'); check('tableau de bord : encadré « Écarts post-facturation »', await page.locator('#variancesAlert').count() === 1);
    });
    await step('6 affichage étroit (390 px)', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      for (const u of ['/?tab=time', '/?tab=dashboard', '/?tab=mandates', '/entries', `/entry/${state.editedId}/edit`]) { await page.goto(BASE + u); check(`aucun débordement horizontal : ${u}`, await noOverflow()); }
      await page.goto(BASE + '/entries'); await shot('mobile-entries'); await page.goto(`${BASE}/entry/${state.editedId}/edit`); await shot('mobile-edit');
      await page.setViewportSize({ width: 1360, height: 900 });
    });
    state.changes = sql('SELECT COUNT(*) FROM entry_changes')[0][0]; state.count = sql('SELECT COUNT(*) FROM entries')[0][0];
    fs.writeFileSync(STATE, JSON.stringify(state));
  } else {
    await step('7 après redémarrage', async () => {
      check(`santé ${EXPECT}`, (await (await page.request.get(`${BASE}/health`)).json()).version === EXPECT);
      check('saisies et historique conservés', sql('SELECT COUNT(*) FROM entries')[0][0] === state.count && sql('SELECT COUNT(*) FROM entry_changes')[0][0] === state.changes);
      await page.goto(BASE + '/entries'); check('liste identique', await rowsOn() === state.count);
      check('PDF de la facture émise identique', require('crypto').createHash('sha256').update(await (await page.request.get(`${BASE}/invoice/${state.iid}.pdf`)).body()).digest('hex') === state.pdfSha);
      await page.goto(`${BASE}/entry/${state.billedId}/edit`); check('saisie facturée toujours modifiable, correction conservée (motif dans l\'historique)', (await page.innerText('body')).includes('motif : durée réelle (recette)') && await page.locator('button:has-text("Enregistrer la correction")').isEnabled());
      await page.goto(`${BASE}/invoice/${state.iid}/ecart`); check('écart post-facturation toujours affiché après redémarrage', (await page.innerText('body')).includes('−0,50 h'));
      await page.goto(`${BASE}/entry/${state.editedId}/edit`); check('historique de la correction toujours lisible', (await page.innerText('body')).includes('Historique des corrections'));
      check('intégrité SQLite ok', sql('PRAGMA integrity_check')[0][0] === 'ok');
    });
  }
  fs.writeFileSync(path.join(J, `resultats-saisies-${PHASE}.json`), JSON.stringify({ results, consoleErrors }, null, 1));
  console.log(`RESULT ${PHASE}: ${results.filter(r => r.ok).length}/${results.length} — erreurs console : ${consoleErrors.length}`); await browser.close();
})();
