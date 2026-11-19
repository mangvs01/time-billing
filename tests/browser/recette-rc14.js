// Recette navigateur RC14 — intégration du design « Liquid Glass » : navigation latérale, cartes et anneaux du tableau de bord, recherche d'archive,
// parcours existants (saisie, calcul de facture), responsive bureau / tablette / téléphone, focus clavier, erreurs console et HTTP.
// Chromium/Playwright, données exclusivement fictives, conteneur jetable. Usage : PW_FILE=… BASE_URL=… OUT=<dossier> node recette-rc14.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT || '.';
const results = [], problems = []; let section = '', shotN = 0;
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' :: ' + String(detail).slice(0, 400))); };
(async () => {
  const browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'fr-CH' }); const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') problems.push(`console ${page.url()} : ${m.text()}`); }); page.on('pageerror', e => problems.push(`js ${page.url()} : ${e.message}`));
  page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  const shot = async n => { shotN++; await page.waitForTimeout(900); await page.screenshot({ path: path.join(OUT, `rc14-${String(shotN).padStart(2, '0')}-${n}.png`), fullPage: true }); };
  const step = async (name, fn) => { section = name; try { await fn(); } catch (e) { check('exception', false, e.stack); try { await shot('ERREUR'); } catch (_) {} } };
  const post = (u, form) => page.request.post(BASE + u, { form, maxRedirects: 0 });
  await page.goto(BASE + '/login'); check('connexion : carte vitrée affichée', await page.locator('.loginbox').count() === 1);
  await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForURL(u => !u.pathname.includes('login'));

  await step('0 préparation fictive', async () => {
    await post('/settings', { issuer_name: 'Bureau Fictif RC14 Sàrl', issuer_address: 'Rue du Test 1\n1000 Lausanne', account_holder: 'Bureau Fictif RC14 Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours', issuer_vat_number: 'CHE-000.000.000 TVA (fictif)' });
    for (const [n, rate, ord, st] of [['Mandat Alpha RC14', '900', '40', '2026-01-01'], ['Mandat Beta RC14', '650', '20', '2026-03-01']])
      await post('/project', { name: n, short_name: n.slice(0, 12), rate, day_hours: '8', vat: '8.1', ordered_days: ord, client: 'Client Fictif', po: 'PO-' + rate, start_date: st, duration_months: '12', billing_address: 'Client Fictif SA\nRue 2\n1000 Ville', client_legal_name: 'Client Fictif SA', client_legal_id: 'CHE-000.000.321' });
    for (let i = 0; i < 4; i++) await post('/entry', { work_date: `2026-06-0${2 + i}`, project_id: '1', entry_mode: 'duration', manual_hours: '8', description: 'Prestation fictive Alpha n°' + i });
    for (let i = 0; i < 4; i++) await post('/entry', { work_date: `2026-07-0${2 + i}`, project_id: '2', entry_mode: 'duration', manual_hours: i % 2 ? '8' : '4', description: 'Prestation fictive Beta n°' + i });
    for (let i = 0; i < 4; i++) await post('/entry', { work_date: `2026-08-1${i}`, project_id: '1', entry_mode: 'duration', manual_hours: '8', description: 'Prestation fictive août n°' + i });
    await post('/invoice', { project_id: '1', period_from: '2026-06-01', period_to: '2026-06-30', qty: '2' });
    const issuePage = await (await page.request.get(BASE + '/issue/1')).text(); const exp = issuePage.match(/name="expected_reliquat" value="([^"]+)"/)?.[1] || '0';
    await post('/issue/1', Object.assign({ reliquat_treatment: 'offert', expected_reliquat: exp, from_confirm: '1', derogation_12: 'Recette fictive : sous-facturation voulue (reliquat traité), exception explicite du seul contrôle 12' }, issuePage.includes('confirm_backdate') ? { confirm_backdate: '1' } : {}));
    await post('/invoice', { project_id: '2', period_from: '2026-07-01', period_to: '2026-07-31', qty: '1' });
    check('données fictives créées', (await (await page.request.get(BASE + '/?tab=archive')).text()).includes('badge b-issued'));
  });

  await step('1 navigation latérale', async () => {
    await page.goto(BASE + '/?tab=dashboard'); await page.waitForLoadState('networkidle');
    const side = await page.locator('aside.sidebar').boundingBox(); check('barre latérale visible et persistante (≥ 200 px)', side && side.width >= 200, JSON.stringify(side));
    for (const [tab, label] of [['dashboard', 'Tableau de bord'], ['time', 'Saisie des heures'], ['mandates', 'Mandats & prévisionnel'], ['billing', 'Édition des factures'], ['archive', 'Factures et brouillons'], ['migration', 'Import historique'], ['settings', 'Paramètres & sauvegardes']]) {
      await page.getByRole('button', { name: label }).click();
      const visible = await page.locator(`[data-panel~="${tab}"]`).first().isVisible(); const active = await page.locator(`button[data-tab=${tab}]`).evaluate(b => b.classList.contains('active'));
      const others = await page.locator('[data-panel]:visible').evaluateAll((els, t) => els.filter(e => !e.dataset.panel.split(' ').includes(t)).length, tab);
      check(`« ${label} » : panneau affiché, entrée active, aucun autre panneau`, visible && active && others === 0, `${visible} ${active} ${others}`);
    }
    await page.goto(BASE + '/entries'); await page.getByRole('link', { name: 'Tableau de bord' }).click(); await page.waitForLoadState();
    check('depuis une page de détail, le lien latéral ramène au tableau de bord', page.url().includes('tab=dashboard'), page.url());
    await page.goto(BASE + '/?tab=dashboard'); await page.waitForTimeout(1100); await shot('tableau-de-bord');
  });

  await step('2 tableau de bord : cartes et anneaux', async () => {
    check('5 cartes financières', await page.locator('.kpi').count() === 5);
    check('un anneau de progression par mandat actif', await page.locator('.ringcard svg').count() === 2, await page.locator('.ringcard svg').count());
    const label = await page.locator('.ringcard svg').first().getAttribute('aria-label'); check('anneau accessible (aria-label chiffré)', /\d+ %/.test(label || ''), label);
    const t = await page.locator('.kpis').innerText(); check('carte « Facturé » affiche un montant en CHF', /Facturé 2026[\s\S]*\d[\d\s’']*,\d\d\s*CHF/i.test(t), t);
  });

  await step('3 archive : badges et recherche', async () => {
    await page.goto(BASE + '/?tab=archive'); const total = await page.locator('#archiveTable tr:visible').count();
    check('badges de statut', await page.locator('#archiveTable .badge.b-issued').count() >= 1 && await page.locator('#archiveTable .badge.b-draft').count() >= 1);
    await page.fill('#archiveSearch', '2026-06'); await page.waitForTimeout(100);
    const shown = await page.locator('#archiveTable tr:visible').count(); check('la recherche réduit la liste (en-tête + document trouvé)', shown < total && shown >= 2, `${total} -> ${shown}`);
    check('compteur de résultats', /1 document sur \d+/.test(await page.locator('#archiveCount').innerText()), await page.locator('#archiveCount').innerText());
    await page.fill('#archiveSearch', 'zzz-introuvable'); await page.waitForTimeout(100); check('recherche sans résultat : aucune ligne', await page.locator('#archiveTable tr:visible').count() === 1);
    await page.fill('#archiveSearch', 'ÉMISE'); await page.waitForTimeout(100); check('recherche insensible à la casse et aux accents', await page.locator('#archiveTable tr:visible').count() >= 2);
    await page.fill('#archiveSearch', ''); await page.waitForTimeout(100); check('effacer la recherche rétablit la liste', await page.locator('#archiveTable tr:visible').count() === total);
    await shot('archive');
  });

  await step('4 parcours existants sous le nouveau design', async () => {
    await page.goto(BASE + '/?tab=time'); const f = page.locator('form[action="/entry"]');
    await f.locator('[name=work_date]').fill('2026-09-10'); await f.locator('[name=project_id]').selectOption({ index: 1 }); await f.locator('input[value=clock]').check();
    await f.locator('#startTime').fill('09:00'); await f.locator('#endTime').fill('12:30'); check('durée calculée en direct (3 h 30)', /3 h 30/.test(await f.locator('#durationDisplay').innerText()));
    await f.locator('[name=description]').fill('Saisie fictive depuis le nouveau design'); await shot('saisie-avant-envoi');
    const n0 = await page.locator('table tr').count(); await f.locator('#entrySubmit').click(); await page.waitForLoadState();
    check('saisie enregistrée (message affiché)', await page.locator('.msg').count() >= 1, await page.locator('body').innerText().then(t => t.slice(0, 200)));
    await page.goto(BASE + '/entries'); check('la saisie apparaît dans la liste', (await page.locator('body').innerText()).includes('Saisie fictive depuis le nouveau design'));
    await page.goto(BASE + '/?tab=billing'); await page.selectOption('#invoiceProject', { index: 0 }); await page.fill('#periodFrom', '2026-08-01'); await page.fill('#periodTo', '2026-08-31'); await page.click('#calculateBtn');
    await page.waitForFunction(() => document.getElementById('rawDays').textContent !== '—'); check('calcul de facture (jours exacts affichés)', /jours/.test(await page.locator('#rawDays').innerText()));
    await page.goto(BASE + '/issue/2'); check('page d\'émission : décision de reliquat demandée', /décision obligatoire|Traitement du reliquat/.test(await page.locator('body').innerText()));
    await shot('emission');
  });

  await step('5 responsive et clavier', async () => {
    for (const [w, h, label] of [[1440, 900, 'bureau'], [1024, 768, 'tablette paysage'], [820, 1180, 'tablette portrait'], [390, 844, 'téléphone']]) {
      await page.setViewportSize({ width: w, height: h });
      for (const tab of ['dashboard', 'time', 'mandates', 'billing', 'archive', 'settings']) {
        await page.goto(BASE + `/?tab=${tab}`); await page.waitForLoadState('networkidle');
        const ov = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth); check(`${label} ${w}px : ${tab} sans défilement horizontal de la page`, ov <= 2, ov);
      }
      await page.goto(BASE + '/?tab=dashboard'); const sb = await page.locator('aside.sidebar').boundingBox();
      if (w >= 1100) check(`${label} : barre latérale complète`, sb.width >= 200, sb.width);
      else if (w >= 761) check(`${label} : barre latérale réduite aux icônes`, sb.width < 100, sb.width);
      else check(`${label} : barre supérieure compacte`, sb.width > 300 && sb.height < 200, JSON.stringify(sb));
      if (w === 820 || w === 390) await shot(label.replace(/ /g, '-'));
    }
    await page.setViewportSize({ width: 1440, height: 900 }); await page.goto(BASE + '/?tab=dashboard');
    await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
    const ring = await page.evaluate(() => { const e = document.activeElement; const s = getComputedStyle(e); return { tag: e.tagName, outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow !== 'none' }; });
    check('focus clavier visible sur la navigation', ring.outline.startsWith('solid') || ring.shadow, JSON.stringify(ring));
  });

  check('aucune erreur console ni réponse HTTP en erreur', problems.length === 0, problems.join(' ; '));
  await browser.close();
  const fails = results.filter(r => !r.ok); console.log(`\nRC14 navigateur : ${results.length - fails.length}/${results.length} réussis, ${fails.length} échec(s)`); process.exit(fails.length ? 1 : 0);
})();
