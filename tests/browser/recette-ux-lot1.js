// Recette navigateur — UX lot 1 (2026-10-20) : affichage et ergonomie seulement (décisions B-1 à B-8, lot 1 des propositions).
// Instance JETABLE, base synthétique vide, données fictives créées ici. Jamais la production (8091), jamais le staging.
// Usage : PW_FILE=… BASE_URL=http://127.0.0.1:<port de test> [OUT_DIR=…] node recette-ux-lot1.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT_DIR || '';
if (!BASE || /:(8091|8092)\b/.test(BASE)) throw new Error('BASE_URL : instance de test jetable seulement (ni 8091 ni 8092)');
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const shot = async (page, name) => { if (OUT) await page.screenshot({ path: path.join(OUT, `ux-lot1-${name}.png`), fullPage: true }); };
(async () => {
  const browser = await chromium.launch(); const errs = [];
  // rc35 : THEME=light|dark rejoue la recette dans ce thème (choix mémorisé posé avant le premier chargement de chaque contexte) ; sans THEME, le défaut du site (sombre)
  if (process.env.THEME) { const nc = browser.newContext.bind(browser); browser.newContext = async o => { const c = await nc(o); await c.addInitScript(t => { try { if (!sessionStorage.getItem('tb-theme-set')) { localStorage.setItem('tb-theme', t); sessionStorage.setItem('tb-theme-set', '1'); } } catch (e) {} }, process.env.THEME); return c; }; }
  // données fictives : un mandat, un mandat dépassé, une saisie
  const setup = await browser.newContext(); const sp = await setup.newPage();
  await sp.goto(BASE + '/login'); await sp.fill('input[name=username]', 'admin'); await sp.fill('input[name=password]', PW); await sp.click('button'); await sp.waitForLoadState();
  const tag = Date.now().toString(36);
  const M = `Mandat UX ${tag}`, D = `Mandat Dépassé ${tag}`;
  for (const [name, ordered] of [[M, '10'], [D, '1']]) await sp.request.post(BASE + '/project', { form: { name, rate: '650', day_hours: '8', vat: '0', ordered_days: ordered, client: 'Client Fictif', start_date: '2026-01-01', duration_months: '12', billing_address: 'Client Fictif SA\nRue Imaginaire 1\n9999 Nulle-Part' } });
  const html = await (await sp.request.get(BASE + '/?tab=time')).text();
  const pid = (html.match(new RegExp(`<option value="(\\d+)"[^>]*>${M}<`)) || [])[1], did = (html.match(new RegExp(`<option value="(\\d+)"[^>]*>${D}<`)) || [])[1];
  for (const d of ['2026-08-10', '2026-08-11']) await sp.request.post(BASE + '/entry', { form: { work_date: d, project_id: did, entry_mode: 'duration', manual_hours: '8', description: 'travail fictif' } });
  await setup.close();

  for (const [label, vp] of [['bureau', { width: 1280, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH', hasTouch: label === 'mobile' }); const page = await ctx.newPage();
    page.on('pageerror', e => errs.push(`${label} ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${m.text()}`); });
    section = `connexion ${label}`;
    await page.goto(BASE + '/login');
    const loginHtml = await page.content(); const ver = (await (await page.request.get(BASE + '/health')).json()).version;
    check('B-7 : version absente de /login', ver && !loginHtml.includes(ver), ver);
    check('B-7 : version présente sur /health', /^9\.2-/.test(ver || ''), ver);
    check('n° 11 : libellés visibles et repère <main>', await page.isVisible('label[for=loginUser]') && await page.locator('main').count() === 1);
    await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState();

    section = `saisie ${label}`;
    await page.goto(BASE + '/?tab=dashboard');
    const fab = page.locator('#fabSaisir');
    if (label === 'mobile') {
      // UX lot 2 (n° 5) : sur téléphone, l'onglet « Saisie » de la barre basse remplace le bouton flottant B-6 (même rôle : onglet Saisie, focus sur « Heure de début »)
      const saisie = page.locator('.sidebar .tabs [data-tab=time]');
      check('B-6 → lot 2 n° 5 : bouton flottant remplacé par la barre basse', !(await fab.isVisible()) && await saisie.isVisible());
      const box = await saisie.boundingBox(); check('lot 2 n° 5 : onglet « Saisie » d\'au moins 44 px, en bas de l\'écran', box && box.height >= 44 && box.width >= 44 && box.y + box.height > 844 - 80, JSON.stringify(box));
      await shot(page, `tableau-de-bord-${label}`);
      await saisie.click();
      check('B-6 : il ouvre l\'onglet Saisie', await page.evaluate(() => document.body.dataset.tab) === 'time');
      check('B-6 : focus sur « Heure de début »', await page.evaluate(() => document.activeElement && document.activeElement.id) === 'startTime');
      const small = await page.evaluate(() => [...document.querySelectorAll('.sidebar .tabs button,.sidebar .tabs a,.navmenu button')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 44; }).length);
      check('n° 12 : onglets visibles ≥ 44 px', small === 0, small);
    } else {
      check('B-6 : bouton flottant absent sur ordinateur', !(await fab.isVisible()));
      await page.click('[data-tab=time]');
    }
    check('n° 10 : l\'URL suit l\'onglet', page.url().includes('tab=time'), page.url());
    check('n° 10 : un seul <h1>, titre de l\'onglet', JSON.stringify(await page.locator('h1').allTextContents()) === '["Saisie des heures"]', await page.locator('h1').allTextContents());
    const today = await page.inputValue('input[name=work_date]');
    check('n° 5 : date du jour par défaut', /^\d{4}-\d{2}-\d{2}$/.test(today), today);
    await page.selectOption('#entryForm select[name=project_id]', pid);
    await page.fill('input[name=work_date]', '2026-08-12');
    await page.fill('#startTime', '17:00'); await page.fill('#endTime', '09:00');
    const lbl = (await page.innerText('#entrySubmit')).trim();
    check('B-4 : libellé « Enregistrer 16 h (fin le lendemain) »', lbl === 'Enregistrer 16 h (fin le lendemain)', lbl);
    check('B-4 : style d\'avertissement', await page.evaluate(() => document.getElementById('entrySubmit').classList.contains('warnbtn')));
    check('B-4 : lien « Inverser début et fin » visible', await page.isVisible('#swapTimes'));
    await shot(page, `saisie-nuit-${label}`);
    await page.click('#swapTimes');
    check('B-4 : inversion en un clic (09:00 → 17:00)', await page.inputValue('#startTime') === '09:00' && await page.inputValue('#endTime') === '17:00');
    const lbl2 = (await page.innerText('#entrySubmit')).trim();
    check('B-4 : libellé normal rétabli (avec la durée : lot 2 n° 4), lien masqué', lbl2 === 'Enregistrer le temps — 8 h' && !(await page.isVisible('#swapTimes')), lbl2);
    await page.fill('#startTime', '06:00'); await page.fill('#endTime', '20:00');
    check('B-4 : plage de plus de 12 h annoncée', (await page.innerText('#entrySubmit')).trim() === 'Enregistrer 14 h', await page.innerText('#entrySubmit'));
    await page.fill('#startTime', '09:00'); await page.fill('#endTime', '11:30');
    await page.fill('input[name=description]', `Saisie fictive ${label}`);
    await page.click('#entrySubmit'); await page.waitForLoadState();
    const msg = (await page.locator('.msg').allInnerTexts()).join(' | ');
    check('saisie enregistrée (règle inchangée)', msg.includes('Temps enregistré : 2,5 h'), msg);
    check('B-3 : même mandat présélectionné après l\'envoi', await page.inputValue('#entryForm select[name=project_id]') === pid);
    check('B-3 : indicateur visible', (await page.innerText('#lastProjectNote')).includes(M), await page.locator('#lastProjectNote').count());
    check('n° 5 : date conservée après l\'envoi', await page.inputValue('input[name=work_date]') === '2026-08-12');
    check('n° 5 : focus remis sur « Heure de début »', await page.evaluate(() => document.activeElement && document.activeElement.id) === 'startTime');

    section = `tableau de bord ${label}`;
    await page.goto(BASE + '/?tab=dashboard');
    const recent = page.locator('section:has(h2:has-text("Dernières saisies"))');
    check('B-5 : « Modifier » présent', await recent.locator('a:has-text("Modifier")').count() > 0);
    check('B-5 : aucun « Supprimer »', await recent.locator('button, a').filter({ hasText: /^\s*Supprimer/ }).count() === 0 && !(await recent.locator('form[action$="/delete"]').count()));
    check('n° 8 : réalisé > commandé signalé', await page.locator('.ringcard.over', { hasText: D }).locator('.badge.b-over').count() === 1 && await page.locator('.ringcard.over', { hasText: M }).count() === 0);
    check('B-8 : onglet « Factures et brouillons »', (await page.innerText('[data-tab=archive]')).trim() === 'Factures et brouillons' || label === 'mobile');
    if (label === 'mobile') {
      const hidden = await page.evaluate(() => { const f = document.querySelector('.sidebar .tabs').getBoundingClientRect(); window.scrollTo(0, document.body.scrollHeight); const last = [...document.querySelectorAll('main .panel')].pop().getBoundingClientRect(); return last.bottom > f.top + 1; });
      check('B-6 / lot 2 n° 5 : en bas de page, la barre basse ne masque pas le dernier panneau', !hidden);
    }
    check('pas de débordement horizontal', !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));

    section = `brouillon ${label}`;
    if (label === 'mobile') { await page.click('#navMore'); await page.click('#navMoreMenu [data-go=billing]'); }   // UX lot 2 (n° 5) : « Édition des factures » est dans « Plus » sur téléphone
    else await page.click('[data-tab=billing]');
    await page.selectOption('#invoiceProject', pid);
    await page.fill('#periodFrom', '2026-08-01'); await page.fill('#periodTo', '2099-08-31');
    check('n° 4 : contrôle 13 annoncé dès le formulaire', await page.isVisible('#periodAfterToday'));
    await page.fill('#periodTo', '2026-08-31');
    check('n° 4 : message retiré pour une période passée', !(await page.isVisible('#periodAfterToday')));
    await page.fill('#invoiceQty', '0.3125'); await page.click('#invoiceForm button:not([type=button])'); await page.waitForLoadState();
    check('n° 6 : deux boutons après « Créer le brouillon »', await page.isVisible('#draftCreated a:has-text("Ouvrir le brouillon")') && await page.isVisible('#draftCreated a:has-text("Contrôler avant émission")'));
    await page.click('#draftCreated a:has-text("Contrôler avant émission")'); await page.waitForLoadState();

    section = `émission ${label}`;
    check('n° 7 : lien « Aperçu PDF (brouillon) »', await page.isVisible('#draftPdfPreview'));
    check('B-2 : quantité à la précision imprimée', (await page.innerText('main')).includes('0,3125 j'));
    check('B-1 : détail du contrôle 3 au format suisse', (await page.textContent('#chk3')).includes('0,3125 × 650 = 203,13 CHF HT'), await page.textContent('#chk3'));   // textContent : sur mobile, le détail d'un contrôle conforme est replié (lot 2, R-3)
    if (label === 'mobile') {
      const hdr = await page.evaluate(() => getComputedStyle(document.querySelector('#issueChecks table.cards tr')).display);
      const row = await page.evaluate(() => getComputedStyle(document.getElementById('chk3')).display);
      check('n° 1 → lot 2 n° 2 (R-3) : contrôles en lignes compactes sur mobile (en-tête masqué, 14 lignes)', hdr === 'none' && row === 'grid' && await page.locator('#issueChecks tr[id^=chk]').count() === 14, `${hdr} ${row}`);
    }
    check('pas de débordement horizontal', !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    await shot(page, `emission-${label}`);
    // nettoyage : le brouillon fictif est supprimé (aucune émission dans cette recette)
    const iid = (page.url().match(/\/issue\/(\d+)/) || [])[1]; if (iid) await page.request.post(BASE + `/invoice/${iid}/delete`);
    await ctx.close();
  }
  section = 'global'; check('aucune erreur console / JS', errs.length === 0, errs.join(' ; '));
  await browser.close();
  const ko = results.filter(r => !r.ok).length; console.log(`RÉSULTAT ux-lot1 : ${results.length - ko}/${results.length} OK, ${ko} KO`); process.exit(ko ? 1 : 0);
})();
