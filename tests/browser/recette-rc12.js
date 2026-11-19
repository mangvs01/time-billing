// Recette navigateur RC12 — points ouverts de la QA (QA-09 saisie conservée après refus, QA-25 deux onglets, QA-21 PDF à adresses longues,
// QA-24 archive vide). Chromium/Playwright, données exclusivement fictives, conteneur jetable.
// Usage : PW_FILE=… BASE_URL=… OUT=<dossier> node recette-rc12.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT || '.';
const results = [], consoleErrors = []; let section = '', shotN = 0;
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' :: ' + String(detail).slice(0, 400))); };
const LONG = 'Direction générale des infrastructures et de la mobilité numérique du canton, bureau des grands projets transversaux';
(async () => {
  const browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: 'fr-CH', acceptDownloads: true });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`${page.url()} : ${m.text()}`); }); page.on('pageerror', e => consoleErrors.push(`${page.url()} : ${e.message}`));
  page.on('dialog', d => d.accept());
  const shot = async n => { shotN++; await page.screenshot({ path: path.join(OUT, `rc12-${shotN}-${n}.png`), fullPage: true }); };
  const step = async (name, fn) => { section = name; try { await fn(); } catch (e) { check('exception', false, e.stack); try { await shot('ERREUR'); } catch (_) {} } };
  const flash = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
  await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button');
  await page.waitForURL(u => !u.pathname.includes('login'));

  await step('0 préparation fictive', async () => {
    await page.request.post(BASE + '/settings', { form: { issuer_name: LONG, issuer_address: `${LONG}\nRue de la Très Longue Avenue du Général-Guisan-Dufour 123bis\n1000 Lausanne`, account_holder: 'Bureau Fictif RC12 Sàrl',
      iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours net dès réception de la facture, sans escompte, par virement bancaire exclusivement, en francs suisses', thanks_text: 'Merci de votre confiance', issuer_rc: 'CHE-123.456.789', issuer_vat_number: 'CHE-123.456.789 TVA' } });
    const r = await page.request.post(BASE + '/project', { form: { name: 'Mandat RC12', rate: '800', day_hours: '8', vat: '8.1', ordered_days: '20', client: 'Client Fictif', po: 'PO-RC12', project_number: 'NP-RC12',
      billing_contact: 'Madame Prénom Nom-Très-Long-De-Famille, cheffe de projet', billing_address: `${LONG}\nAvenue de la Gare 1\n1003 Lausanne`, dates_label: 'Sept 2026', start_date: '2026-01-01', duration_months: '12',
      client_legal_name: 'Département Fictif des Infrastructures et de la Mobilité de la République et canton', client_legal_id: 'CHE-000.000.123' } });
    check('mandat fictif créé', r.ok());
  });

  await step('1 QA-09 : saisie refusée, valeurs conservées', async () => {
    await page.goto(BASE + '/?tab=time');
    await page.selectOption('select[name=project_id]', { label: 'Mandat RC12' }); await page.fill('input[name=work_date]', '2026-09-07');
    await page.check('input[name=entry_mode][value=duration]'); await page.fill('#manualHours', '99'); await page.fill('input[name=description]', 'Atelier à conserver après refus');
    await page.click('text=Enregistrer le temps'); await page.waitForLoadState();
    check('refus affiché', (await flash()).includes('Saisie refusée'), await flash());
    check('onglet saisie rouvert', await page.locator('#manualHours').isVisible());
    check('description conservée', (await page.inputValue('input[name=description]')) === 'Atelier à conserver après refus', await page.inputValue('input[name=description]'));
    check('durée conservée et mode « durée » rétabli', (await page.inputValue('#manualHours')) === '99' && await page.locator('#startTime').isDisabled());
    check('date et projet conservés', (await page.inputValue('input[name=work_date]')) === '2026-09-07' && (await page.locator('#entryForm select[name=project_id] option:checked').innerText()) === 'Mandat RC12');
    await shot('saisie-refusee-conservee');
    await page.fill('#manualHours', '4.25'); await page.click('text=Enregistrer le temps'); await page.waitForLoadState();
    check('correction acceptée', (await flash()).includes('4,25 h'), await flash());
    await page.goto(BASE + '/?tab=time'); check('formulaire vide après succès', (await page.inputValue('input[name=description]')) === '');
  });

  await step('2 QA-09 : mandat refusé, valeurs conservées', async () => {
    await page.goto(BASE + '/?tab=mandates'); const href = await page.locator('a[href$="/edit"][href^="/project/"]').first().getAttribute('href');
    await page.goto(BASE + href); await page.fill('input[name=name]', 'N'.repeat(201)); await page.fill('textarea[name=billing_address]', 'Adresse tapée à conserver\nRue 1');
    await page.click('button:has-text("Enregistrer")'); await page.waitForLoadState();
    check('refus affiché', (await flash()).includes('Mandat non modifié'), await flash());
    check('adresse tapée conservée', (await page.inputValue('textarea[name=billing_address]')).startsWith('Adresse tapée à conserver'));
  });

  await step('3 QA-25 : deux onglets sur la même saisie', async () => {
    await page.goto(BASE + '/entries'); const href = await page.locator('a[href*="/entry/"][href*="/edit"]').first().getAttribute('href');
    const p1 = await ctx.newPage(), p2 = await ctx.newPage(); p1.on('dialog', d => d.accept()); p2.on('dialog', d => d.accept());
    await p1.goto(BASE + href); await p2.goto(BASE + href);
    for (const [p, h] of [[p1, '3'], [p2, '5']]) { await p.check('input[name=entry_mode][value=duration]'); await p.fill('#manual_hours', h); }
    await p1.click('button:has-text("Enregistrer")'); await p1.waitForLoadState();
    await p2.click('button:has-text("Enregistrer")'); await p2.waitForLoadState();
    const msg = (await p2.locator('.msg').allInnerTexts()).join(' | ');
    check('2e onglet refusé', msg.includes('modifiée depuis l'), msg);
    check('valeur saisie dans le 2e onglet conservée', (await p2.inputValue('#manual_hours')) === '5', await p2.inputValue('#manual_hours'));
    await p2.screenshot({ path: path.join(OUT, 'rc12-conflit-onglets.png'), fullPage: true });
    await p2.click('button:has-text("Enregistrer")'); await p2.waitForLoadState();
    check('enregistrement volontaire ensuite accepté', !(await p2.locator('.msg').allInnerTexts()).join('').includes('modifiée depuis l'));
    await p1.close(); await p2.close();
  });

  await step('4 QA-21 : facture à adresses très longues, PDF contrôlé', async () => {
    await page.goto(BASE + '/?tab=billing');
    await page.selectOption('#invoiceProject', { label: 'Mandat RC12' }); await page.fill('#periodFrom', '2026-09-01'); await page.fill('#periodTo', '2026-09-30'); await page.fill('#invoiceQty', '0.5');
    await page.click('button:has-text("Créer le brouillon")'); await page.waitForLoadState();
    check('brouillon créé', (await flash()).includes('Brouillon créé'), await flash());
    check('message vers « Factures et brouillons » (QA-24, onglet renommé : décision B-8)', (await flash()).includes('Factures et brouillons'));
    await page.goto(BASE + '/?tab=archive'); const issue = await page.locator('a:has-text("Émettre")').first().getAttribute('href');
    await page.goto(BASE + issue); await page.check('input[name=reliquat_treatment][value=offert]');
    await page.click('button:has-text("Émettre définitivement")'); await page.waitForLoadState();
    const em = await flash(); check('émission acceptée malgré les textes longs', /émise/.test(em), em);
    const pdf = await page.request.get(BASE + '/invoice/' + issue.match(/\/issue\/(\d+)/)[1] + '.pdf');
    const f = path.join(OUT, 'rc12-facture-longue.pdf'); fs.writeFileSync(f, await pdf.body());
    const txt = execFileSync('pdftotext', ['-layout', '-f', '1', '-l', '1', f, '-']).toString();
    check('PDF produit', txt.includes('FACTURE'));
    const bb = execFileSync('pdftotext', ['-bbox', '-f', '1', '-l', '1', f, '-']).toString();
    const xs = [...bb.matchAll(/xMax="([\d.]+)"/g)].map(m => +m[1]), x0 = [...bb.matchAll(/xMin="([\d.]+)"/g)].map(m => +m[1]);
    check(`aucun mot hors de la page (xMax ${Math.max(...xs).toFixed(0)} ≤ 565, xMin ${Math.min(...x0).toFixed(0)} ≥ 30)`, Math.max(...xs) <= 565 && Math.min(...x0) >= 30);
    check('adresse longue imprimée en entier', txt.includes('transversaux') && txt.includes('Lausanne'));
    execFileSync('pdftoppm', ['-r', '70', '-png', '-f', '1', '-l', '1', f, path.join(OUT, 'rc12-facture-longue')]);
  });

  await step('5 QA-24 : archive d\'une année sans document', async () => {
    const r = await page.request.get(BASE + '/archive.zip?year=1999', { maxRedirects: 0 }); check('redirection (pas de ZIP vide)', r.status() === 302, r.status());
    await page.goto(BASE + '/archive.zip?year=1999').catch(() => {});   // la redirection affiche le message
    const ok = (await flash()).includes('Aucun document émis en 1999'); check('message explicite', ok, await flash());
  });

  check('aucune erreur console', consoleErrors.length === 0, consoleErrors.join(' ; '));
  await browser.close();
  const fails = results.filter(r => !r.ok); console.log(`\nRC12 navigateur : ${results.length - fails.length}/${results.length} réussis, ${fails.length} échec(s)`); process.exit(fails.length ? 1 : 0);
})();
