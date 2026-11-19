// Recette navigateur de la nuit RC14 : filtres d'archive, panneau de position (mandats / facturation), ordre de lecture des mandats,
// jauge du tableau de bord, synthèse d'avoir, aperçu d'import dans la coque, rendu téléphone (cartes, barre d'outils non collante).
// Chromium/Playwright, données exclusivement fictives, conteneur jetable vide. Jamais « Valider l'import ».
// Usage : PW_FILE=… BASE_URL=… OUT=<dossier> node recette-nuit.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT || '.';
const results = [], problems = []; let section = '', shotN = 0;
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' :: ' + String(detail).slice(0, 400))); };
(async () => {
  const browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'fr-CH' }); const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') problems.push(`console ${page.url()} : ${m.text()}`); }); page.on('pageerror', e => problems.push(`js ${page.url()} : ${e.message}`));
  page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  const shot = async n => { shotN++; await page.evaluate(() => scrollTo(0, 0)); await page.waitForTimeout(700); await page.screenshot({ path: path.join(OUT, `nuit-${String(shotN).padStart(2, '0')}-${n}.png`), fullPage: true }); };
  const step = async (name, fn) => { section = name; try { await fn(); } catch (e) { check('exception', false, e.stack); try { await shot('ERREUR'); } catch (_) {} } };
  const post = (u, form) => page.request.post(BASE + u, { form, maxRedirects: 0 });
  const visibleRows = () => page.locator('#archiveTable tr:visible').count();
  await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForURL(u => !u.pathname.includes('login'));

  await step('0 préparation fictive', async () => {
    await post('/settings', { issuer_name: 'Bureau Fictif Nuit Sàrl', issuer_address: 'Rue du Test 1\n1000 Lausanne', account_holder: 'Bureau Fictif Nuit Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours', issuer_vat_number: 'CHE-000.000.000 TVA (fictif)' });
    for (const [n, rate, ord] of [['Mandat Alpha Nuit', '900', '40'], ['Mandat Beta Nuit', '650', '20']])
      await post('/project', { name: n, short_name: n.slice(0, 12), rate, day_hours: '8', vat: '8.1', ordered_days: ord, client: 'Client Fictif', po: 'PO-' + rate, start_date: '2026-01-01', duration_months: '12', billing_address: 'Client Fictif SA\nRue 2\n1000 Ville', client_legal_name: 'Client Fictif SA', client_legal_id: 'CHE-000.000.321' });
    for (let i = 0; i < 4; i++) await post('/entry', { work_date: `2026-06-0${2 + i}`, project_id: '1', entry_mode: 'duration', manual_hours: '8', description: 'Prestation fictive Alpha ' + i });
    for (let i = 0; i < 2; i++) await post('/entry', { work_date: `2026-07-0${2 + i}`, project_id: '2', entry_mode: 'duration', manual_hours: '8', description: 'Prestation fictive Beta ' + i });
    await post('/invoice', { project_id: '1', period_from: '2026-06-01', period_to: '2026-06-30', qty: '3' });
    const ip = await (await page.request.get(BASE + '/issue/1')).text(); const exp = ip.match(/name="expected_reliquat" value="([^"]+)"/)?.[1] || '0';
    await post('/issue/1', Object.assign({ reliquat_treatment: 'reporte', expected_reliquat: exp, from_confirm: '1', derogation_12: 'Recette fictive : sous-facturation voulue (reliquat traité), exception explicite du seul contrôle 12' }, ip.includes('confirm_backdate') ? { confirm_backdate: '1' } : {}));
    await post('/invoice/1/credit', { treatment: 'remboursement', scope: 'partial', reason: 'Geste commercial fictif', amount: '100', refund_delay_days: '30' });
    const cn = await (await page.request.get(BASE + '/?tab=archive')).text(); const cid = cn.match(/action="\/credit\/(\d+)\/issue"/)?.[1];
    if (cid) await post(`/credit/${cid}/issue`, {});
    await post('/invoice', { project_id: '2', period_from: '2026-07-01', period_to: '2026-07-31', qty: '1' });
    const a = await (await page.request.get(BASE + '/?tab=archive')).text();
    check('données fictives : une facture émise créditée et un brouillon', a.includes('badge b-issued') && a.includes('badge b-draft') && /class="subrow"/.test(a));
  });

  await step('1 archive : filtres de statut', async () => {
    await page.goto(BASE + '/?tab=archive'); const all = await visibleRows();
    await page.click('#archiveFilters [data-af=draft]'); const d = await visibleRows();
    check('« Brouillons » : seulement les brouillons', d === 2 && await page.locator('#archiveTable tr:visible .badge.b-issued').count() === 0, `${all} -> ${d}`);
    check('pastille active annoncée (aria-pressed)', await page.locator('#archiveFilters [data-af=draft]').getAttribute('aria-pressed') === 'true');
    check('compteur de résultats', /1 document sur 2/.test(await page.locator('#archiveCount').innerText()), await page.locator('#archiveCount').innerText());
    await page.click('#archiveFilters [data-af=issued]'); check('« Émises » : la facture émise et sa note de crédit', await visibleRows() === 3, await visibleRows());
    await page.click('#archiveFilters [data-af=credit]'); check('« Avec note de crédit »', await visibleRows() === 3 && await page.locator('#archiveTable tr.subrow:visible').count() === 1);
    await page.fill('#archiveSearch', 'Beta'); check('filtre combiné à la recherche : aucun résultat', await visibleRows() === 1);
    await page.click('#archiveFilters [data-af=all]'); check('« Tous » + recherche', await visibleRows() === 2);
    await page.fill('#archiveSearch', ''); check('tout rétabli', await visibleRows() === all, `${await visibleRows()} / ${all}`);
    await shot('archive-filtres');
  });

  await step('2 mandats : position et ordre de lecture', async () => {
    await page.goto(BASE + '/?tab=mandates');
    const y = async s => (await page.locator(s).boundingBox()).y;
    check('ordre : positions, détail, prévisions, création', await y('.p-balances') < await y('.p-detail') && await y('.p-detail') < await y('.p-forecast') && await y('.p-forecast') < await y('.p-create'));
    check('une barre par mandat actif', await page.locator('.p-balances .bal').count() === 2);
    const w = await page.locator('.p-balances .bal').first().locator('.s-bill').evaluate(e => e.getBoundingClientRect().width / e.parentElement.getBoundingClientRect().width);
    check('barre « facturé net » de l\'Alpha ≈ 3/40', Math.abs(w - 3 / 40) < 0.01, w);
    check('lien « Nouveau mandat » vers le formulaire', await page.locator('.p-balances a[href="#nouveau-mandat"]').isVisible());
    await shot('mandats');
  });

  await step('3 facturation : panneau de position', async () => {
    await page.goto(BASE + '/?tab=billing');
    const f = await page.locator('#invoiceForm').boundingBox(), b = await page.locator('.p-balances').boundingBox();
    check('panneau à droite du formulaire (bureau)', b.x > f.x + f.width - 2 && Math.abs(b.y - f.y) < 120, JSON.stringify([f, b]));
    check('lien « Nouveau mandat » masqué en facturation', !(await page.locator('.p-balances a[href="#nouveau-mandat"]').isVisible()));
    await page.selectOption('#invoiceProject', { label: 'Mandat Beta Nuit' });
    check('mandat choisi mis en évidence', await page.locator('.p-balances .bal.sel').count() === 1 && (await page.locator('.p-balances .bal.sel').innerText()).includes('Mandat Beta Nuit'));
    await shot('facturation');
  });

  await step('4 tableau de bord et avoir', async () => {
    await page.goto(BASE + '/?tab=dashboard');
    check('carte principale sur deux rangées, plus grande que les autres', (await page.locator('.kpi.primary').boundingBox()).height > 1.6 * (await page.locator('.kpi:not(.primary)').first().boundingBox()).height);
    const cn = await (await page.request.get(BASE + '/?tab=archive')).text(); const cid = cn.match(/href="\/credit\/(\d+)"/)?.[1];
    await page.goto(BASE + `/credit/${cid}`); check('suivi d\'avoir : synthèse chiffrée', await page.locator('.cn-sum').isVisible() && /Reste à rembourser/.test(await page.locator('.cn-sum').innerText()));
    check('entrée « Factures et brouillons » active sur la page de détail (B-8)', await page.locator('aside.sidebar a.active').innerText() === 'Factures et brouillons');
    await shot('avoir');
  });

  await step('5 aperçu d\'import (prévisualisation seulement)', async () => {
    await page.goto(BASE + '/?tab=migration'); await page.setInputFiles('input[name=workbook]', path.join(__dirname, 'releve-fictif-nuit.xlsx'));
    await Promise.all([page.waitForURL(/import\/review/), page.locator('input[name=workbook]').evaluate(f => f.form.submit())]); await page.waitForLoadState('networkidle');
    check('coque : barre latérale, entrée « Import historique » active', await page.locator('aside.sidebar a.active', { hasText: 'Import historique' }).count() === 1);
    await page.click('#filters button[data-f=bloquante]'); const bg = await page.locator('#filters button.active').evaluate(e => getComputedStyle(e).backgroundColor);
    check('pastille active au bleu du design (plus de bleu marine)', !/24, 59, 85/.test(bg), bg);
    await page.click('#filters button[data-f=all]'); await shot('import-bureau');
    await page.setViewportSize({ width: 390, height: 844 }); await page.reload(); await page.waitForLoadState('networkidle');
    check('téléphone : aucun débordement horizontal', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    check('téléphone : barre de filtres non collante', await page.locator('#toolbar').evaluate(e => getComputedStyle(e).position) === 'static');
    await shot('import-telephone');
    await page.locator('form[action$="/cancel"] button').click(); await page.waitForLoadState();
    check('prévisualisation abandonnée, rien importé', !(await page.content()).includes('COMMITTED'));
  });

  await step('6 téléphone : archive en cartes', async () => {
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(BASE + '/?tab=archive');
    check('en-tête du tableau masqué, lignes en cartes', !(await page.locator('#archiveTable tr').first().isVisible()) && await page.locator('#archiveTable tr').nth(1).evaluate(e => getComputedStyle(e).display) === 'block');
    check('aucun débordement horizontal', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.click('#archiveFilters [data-af=draft]'); check('filtres utilisables au téléphone', await visibleRows() === 1, await visibleRows());
    await shot('archive-telephone');
  });

  await step('7 tablette et téléphone : tableaux larges lisibles sans défilement', async () => {
    for (const [w, h] of [[834, 1112], [1024, 768]]) {
      await page.setViewportSize({ width: w, height: h });
      for (const [tab, sel] of [['archive', '#archiveTable td.actions a.btn'], ['mandates', '.p-detail a.btn[href^="/entries"]']]) {
        await page.goto(BASE + `/?tab=${tab}`); const r = await page.locator(sel).first().boundingBox();
        check(`${w}px ${tab} : actions visibles dans l'écran`, r && r.x >= 0 && r.x + r.width <= w, JSON.stringify(r));
      }
    }
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(BASE + '/?tab=mandates');
    const lab = await page.locator('.p-detail tr').nth(1).locator('td').nth(9).getAttribute('data-label');
    check('téléphone : libellés de cartes repris des en-têtes (« Solde contractuel (j) »)', lab === 'Solde contractuel (j)', lab);
    check('téléphone : aucun débordement (mandats)', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await shot('mandats-telephone');
  });

  section = 'fin'; check('aucune erreur console ni réponse HTTP en erreur', problems.length === 0, problems.join(' ; '));
  await browser.close();
  const fails = results.filter(r => !r.ok); console.log(`\nNUIT navigateur : ${results.length - fails.length}/${results.length} réussis, ${fails.length} échec(s)`); process.exit(fails.length ? 1 : 0);
})();
