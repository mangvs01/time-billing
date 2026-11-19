// Recette navigateur — UX lot 2 (2026-10-23) : affichage et ergonomie seulement (propositions n° 1 à 11, recommandations R-1 à R-7).
// Instance JETABLE, base synthétique vide, données fictives créées ici. Jamais la production (8091), jamais le staging (8092).
// Usage : PW_FILE=… BASE_URL=http://127.0.0.1:<port de test> [OUT_DIR=…] node recette-ux-lot2.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT_DIR || '';
if (!BASE || /:(8091|8092)\b/.test(BASE)) throw new Error('BASE_URL : instance de test jetable seulement (ni 8091 ni 8092)');
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const shot = async (page, name) => { if (OUT) await page.screenshot({ path: path.join(OUT, `ux-lot2-${name}.png`), fullPage: true }); };
const login = async page => { await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState(); };
const noOverflow = page => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
(async () => {
  const browser = await chromium.launch(); const errs = [];
  // rc35 : THEME=light|dark rejoue la recette dans ce thème (choix mémorisé posé avant le premier chargement de chaque contexte) ; sans THEME, le défaut du site (sombre)
  if (process.env.THEME) { const nc = browser.newContext.bind(browser); browser.newContext = async o => { const c = await nc(o); await c.addInitScript(t => { try { if (!sessionStorage.getItem('tb-theme-set')) { localStorage.setItem('tb-theme', t); sessionStorage.setItem('tb-theme-set', '1'); } } catch (e) {} }, process.env.THEME); return c; }; }
  // données fictives : émetteur, un mandat avec PO (TVA 8,1 %) et un mandat sans PO ; août à octobre 2026
  const setup = await browser.newContext(); const sp = await setup.newPage(); await login(sp);
  const post = (u, form) => sp.request.post(BASE + u, { form });
  await post('/settings', { issuer_name: 'Bureau Recette Sàrl', issuer_address: 'Chemin de la Recette 7\n1000 Ville', account_holder: 'Bureau Recette Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours sur le compte:', issuer_vat_number: 'CHE-000.000.000 TVA' });
  const tag = Date.now().toString(36), A = `Mandat Lot2 A ${tag}`, B = `Mandat Lot2 B ${tag}`;
  for (const [name, ordered, vat] of [[A, '40', '8.1'], [B, '', '0']]) await post('/project', { name, client: 'Client Recette SA', po: ordered ? 'PO-R-1' : '', rate: '900', day_hours: '8', vat, ordered_days: ordered, start_date: '2026-01-01', duration_months: '12', billing_address: 'Client Recette SA\nRue 1\n9999 Nulle-Part', client_legal_name: 'Client Recette SA', client_legal_id: 'che000001111' });
  const html0 = await (await sp.request.get(BASE + '/?tab=time')).text();
  const pid = n => (html0.match(new RegExp(`<option value="(\\d+)"[^>]*>${n}<`)) || [])[1]; const pa = pid(A), pb = pid(B);
  // septembre : 55,75 h = 6,96875 j (cas de la recette : « au plus proche 0,25 j » donne 7,00 j, refusé sans dérogation par le contrôle 12)
  for (const [d, h] of [['01', 7.75], ['02', 8], ['03', 8], ['04', 8], ['07', 8], ['08', 8], ['09', 8]]) await post('/entry', { work_date: `2026-09-${d}`, project_id: pa, entry_mode: 'duration', manual_hours: String(h), description: 'travail fictif' });
  // août : 2 j de travail antérieur non facturés — le cumul réalisé dépasse alors 7 j (contrôle 14, non dérogeable, conforme) ; seul le contrôle 12 compare à la période
  for (const d of ['03', '04']) await post('/entry', { work_date: `2026-08-${d}`, project_id: pa, entry_mode: 'duration', manual_hours: '8', description: 'travail antérieur fictif' });
  for (const d of ['01', '02', '05']) await post('/entry', { work_date: `2026-10-${d}`, project_id: pa, entry_mode: 'clock', start_time: '08:30', end_time: '12:15', description: 'atelier fictif' });
  for (const d of ['03', '04']) await post('/entry', { work_date: `2026-08-${d}`, project_id: pb, entry_mode: 'duration', manual_hours: '6', description: 'assistance fictive' });
  await setup.close();

  for (const [label, vp] of [['bureau', { width: 1280, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    const mobile = label === 'mobile';
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH', hasTouch: mobile }); const page = await ctx.newPage();
    page.on('pageerror', e => errs.push(`${label} ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${m.text()}`); });
    page.on('dialog', d => d.accept());
    await login(page);

    section = `saisie ${label}`;                                                            // n° 4, n° 10
    await page.goto(BASE + '/?tab=time');
    const sub = await page.locator('#entrySubmit').boundingBox();
    check('n° 4 : bouton « Enregistrer » dans le premier écran', sub && sub.y + sub.height <= vp.height, JSON.stringify(sub));
    await page.click('[data-setdate]:has-text("Hier")');
    const y = await page.inputValue('#entryForm input[name=work_date]');
    check('n° 4 : raccourci « Hier »', y === await page.getAttribute('[data-setdate]:has-text("Hier")', 'data-setdate'), y);
    await page.selectOption('#entryForm select[name=project_id]', pb);
    await page.check('input[name=entry_mode][value=duration]'); await page.fill('#manualHours', '4.25');
    check('n° 4 : durée dans le bouton (mode durée)', (await page.innerText('#entrySubmit')).trim() === 'Enregistrer le temps — 4 h 15', await page.innerText('#entrySubmit'));
    await page.check('input[name=entry_mode][value=clock]'); await page.fill('#startTime', '08:30'); await page.fill('#endTime', '12:15');
    check('n° 4 : durée dans le bouton (début / fin)', (await page.innerText('#entrySubmit')).trim() === 'Enregistrer le temps — 3 h 45', await page.innerText('#entrySubmit'));
    const nEntries = (await (await page.request.get(BASE + '/entries')).text()).match(/<strong>(\d+)<\/strong> saisie/)[1];
    await page.locator('button.reprise').first().click();
    check('n° 10 : « Reprendre » pré-remplit à la date du jour', await page.inputValue('#entryForm input[name=work_date]') === await page.getAttribute('[data-setdate]:has-text("Aujourd")', 'data-setdate'));
    check('n° 10 : rien n\'est enregistré par « Reprendre »', (await (await page.request.get(BASE + '/entries')).text()).match(/<strong>(\d+)<\/strong> saisie/)[1] === nEntries);
    check('pas de débordement horizontal', await noOverflow(page));
    await shot(page, `saisie-${label}`);

    section = `brouillon ${label}`;                                                         // n° 3 (R-1, R-2, R-5)
    await page.goto(BASE + '/?tab=billing');
    check('R-5 : aucune date pré-remplie', await page.inputValue('#periodFrom') === '' && await page.inputValue('#periodTo') === '');
    check('R-2 : règle par défaut inchangée (« Sans arrondi »)', await page.inputValue('#rounding') === 'exact');
    await page.selectOption('#invoiceProject', pa);
    if (!mobile) {
      check('R-5 : « Depuis la dernière facture » inactif sans facture émise', await page.isDisabled('[data-period=since]'));
      await page.click('[data-period=lastmonth]');
      check('R-5 : « Mois dernier » remplit les deux dates', await page.inputValue('#periodFrom') === '2026-09-01' && await page.inputValue('#periodTo') === '2026-09-30', await page.inputValue('#periodFrom'));
    } else {
      await page.click('[data-period=since]');                                               // après l'émission de septembre (bureau)
      check('R-5 : « Depuis la dernière facture » part du lendemain de la dernière période émise', await page.inputValue('#periodFrom') === '2026-10-01', await page.inputValue('#periodFrom'));
    }
    await page.waitForFunction(() => document.getElementById('rawDays').textContent !== '—' && !document.getElementById('roundOptions').hidden);
    check('n° 3 : calcul automatique (sans bouton)', /jours/.test(await page.innerText('#rawDays')));
    check('n° 3 : quatre règles d\'arrondi affichées', await page.locator('#roundOptions .ropt').count() === 4);
    if (!mobile) {
      check('R-1 : « Au plus proche » annonce le contrôle 12', await page.locator('#roundOptions .ropt.warn[data-mode=nearest]').count() === 1);
      check('R-1 : « À l\'inférieur » dans la tolérance', await page.locator('#roundOptions .ropt.warn[data-mode=down]').count() === 0);
      await page.click('#roundOptions .ropt[data-mode=down]'); await page.waitForTimeout(600);
      check('n° 3 : choisir une règle règle la quantité et la liste', await page.inputValue('#invoiceQty') === '6.75' && await page.inputValue('#rounding') === 'down', await page.inputValue('#invoiceQty'));
      await page.fill('#invoiceQty', '7'); await page.waitForFunction(() => /dérogation écrite/.test(document.getElementById('qtyCheck').innerText), null, { timeout: 5000 }).catch(() => {});
      check('R-1 : quantité saisie 7 j → contrôle 12 annoncé (serveur)', /Contrôle 12 \(prévision\) : dérogation écrite/.test(await page.innerText('#qtyCheck')), await page.innerText('#qtyCheck'));
      await page.waitForTimeout(700);
      check('n° 3 : la quantité saisie n\'est pas écrasée par le calcul', await page.inputValue('#invoiceQty') === '7', await page.inputValue('#invoiceQty'));
      check('n° 3 : bouton qui rappelle la quantité et le montant', /Créer le brouillon — 7 j · 6 300,00 CHF HT/.test(await page.innerText('#draftSubmit')), await page.innerText('#draftSubmit'));
      check('n° 3 : options repliées', !(await page.locator('#draftOptions').evaluate(d => d.open)));
      await shot(page, `brouillon-${label}`);
      await page.click('#draftSubmit'); await page.waitForLoadState();
      check('brouillon créé (règles inchangées)', await page.isVisible('#draftCreated'));
      await page.selectOption('#invoiceProject', pa); await page.click('[data-period=lastmonth]');
      await page.waitForFunction(() => document.getElementById('draftAlerts').innerText.length > 0, null, { timeout: 5000 }).catch(() => {});
      check('n° 3 : brouillon chevauchant annoncé AVANT la création, avec lien', /Un brouillon couvre déjà cette période/.test(await page.innerText('#draftAlerts')) && await page.locator('#draftAlerts a[href$="/edit"]').count() === 1);
    } else {
      await page.click('#draftSubmit'); await page.waitForLoadState();
      check('brouillon créé (mobile)', await page.isVisible('#draftCreated'));
    }
    check('pas de débordement horizontal', await noOverflow(page));

    section = `tableau de bord ${label}`;                                                   // n° 1, n° 11
    await page.goto(BASE + '/?tab=dashboard');
    const todo = page.locator('#todoPanel li[data-todo=draft]');
    check('n° 1 : le brouillon figure dans « À traiter »', await todo.count() >= 1);
    if (!mobile) check('R-4 : contrôles en échec du brouillon (n° 12)', /1 contrôle en échec \(n° 12\)/.test(await todo.first().innerText()), await todo.first().innerText());
    check('n° 11 : 5 dernières saisies au plus sur le tableau de bord', await page.locator('.recent-table tr:not(.month-total):visible').count() <= 6);
    check('n° 11 : synthèse repliée sur téléphone, ouverte sur ordinateur', await page.locator('#synthFold').evaluate(d => d.open) === !mobile);
    check('pas de débordement horizontal', await noOverflow(page));
    await shot(page, `tableau-de-bord-${label}`);
    await todo.first().locator('a.btn').click(); await page.waitForLoadState();

    section = `émission ${label}`;                                                          // n° 2 (R-3)
    check('n° 1 : le bouton mène au contrôle avant émission', /\/issue\/\d+$/.test(page.url()), page.url());
    check('n° 2 : 14 lignes de contrôle dans leur ordre', JSON.stringify(await page.locator('#issueChecks tr[id^=chk]').evaluateAll(r => r.map(x => x.id))) === JSON.stringify([...Array(14)].map((_, i) => `chk${i + 1}`)));
    const recapY = (await page.locator('#issueRecap').boundingBox()).y;
    check('n° 2 : récapitulatif dans le premier écran', recapY < vp.height);
    const btnY = (await page.locator('#issueForm button:not([type=button])').boundingBox()).y + await page.evaluate(() => scrollY);
    check(`n° 2 : bouton d'émission plus haut qu'en rc33 (${Math.round(btnY)} px)`, btnY < (mobile ? 4296 : 2254), btnY);
    if (!mobile) {
      check('R-3 : position détaillée repliée (aucune alerte)', !(await page.locator('#issuePosition').evaluate(d => d.open)));
      const ta = page.locator('#chk12 textarea[name=derogation_12]');
      check('n° 2 : le motif se saisit dans la ligne du contrôle 12', await ta.count() === 1 && await ta.getAttribute('form') === 'issueForm');
      await page.check('input[name=reliquat_treatment][value=reporte]').catch(() => {});
      await ta.fill('Arrondi convenu avec le client pour la période (recette fictive)');
      await shot(page, `emission-${label}`);
      await page.click('#issueForm button:not([type=button])'); await page.waitForLoadState();
      const msg = (await page.locator('.msg').allInnerTexts()).join(' | ');
      check('n° 2 : émission par le bouton, motif envoyé (attribut form)', /Facture \d{4}-\d+ émise/.test(msg), msg);
    } else {
      check('R-3 : contrôles conformes compacts (une ligne)', (await page.locator('#chk3').boundingBox()).height < 70, (await page.locator('#chk3').boundingBox()).height);
      check('pas de débordement horizontal', await noOverflow(page));
      await shot(page, `emission-${label}`);
      const iid = (page.url().match(/\/issue\/(\d+)/) || [])[1]; if (iid) await page.request.post(BASE + `/invoice/${iid}/delete`);   // aucune émission sur mobile
    }

    section = `factures et brouillons ${label}`;                                            // n° 6
    await page.goto(BASE + '/?tab=archive');
    const firstGroup = await page.locator('#archiveTable tr.grouprow').first().innerText();
    if (await page.locator('#archiveTable tr[data-st=draft]').count()) check('n° 6 : brouillons d\'abord', /Brouillons à émettre/.test(firstGroup), firstGroup);
    check('n° 6 : une action principale par document émis (PDF) + « Plus »', await page.locator('#archiveTable tr[data-st=issued] td.actions > a.btn').count() === await page.locator('#archiveTable tr[data-st=issued]').count());
    await page.locator('#archiveTable tr[data-st=issued] details.more > summary').first().click();
    check('n° 6 : « Plus » ouvre « Note de crédit… »', await page.locator('#archiveTable tr[data-st=issued] details.more[open] a:has-text("Note de crédit")').first().isVisible());
    await page.click('#archiveFilters [data-af=issued]');
    check('n° 6 : titres de groupe masqués sous filtre', await page.locator('#archiveTable tr.grouprow:visible').count() === 0);
    check('pas de débordement horizontal', await noOverflow(page));
    await shot(page, `archive-${label}`);

    section = `navigation ${label}`;                                                        // n° 5
    if (mobile) {
      const bar = await page.locator('.sidebar .tabs').boundingBox();
      check('n° 5 : barre d\'onglets en bas de l\'écran', bar && bar.y + bar.height >= vp.height - 30, JSON.stringify(bar));
      check('n° 5 : 5 entrées visibles', await page.locator('.sidebar .tabs > :visible').count() === 5, await page.locator('.sidebar .tabs > :visible').count());
      await page.click('#navMore');
      check('n° 5 : « Plus » ouvre le menu', await page.isVisible('#navMoreMenu') && await page.getAttribute('#navMore', 'aria-expanded') === 'true');
      await page.click('#navMoreMenu [data-go=billing]');
      check('n° 5 : « Édition des factures » depuis « Plus »', await page.evaluate(() => document.body.dataset.tab) === 'billing' && !(await page.isVisible('#navMoreMenu')));
    } else {
      check('n° 5 : barre latérale inchangée sur ordinateur (« Plus » absent)', !(await page.isVisible('#navMore')) && await page.isVisible('.sidebar .tabs [data-tab=billing]'));
    }

    section = `saisies ${label}`;                                                           // n° 7
    await page.goto(BASE + '/entries'); await page.click('.quickperiods a:has-text("Mois dernier")'); await page.waitForLoadState();
    check('n° 7 : « Mois dernier » filtre par les paramètres existants', /date_from=2026-09-01&date_to=2026-09-30/.test(page.url()), page.url());
    check('n° 7 : total par semaine', await page.locator('#entriesTable tr.weektotal').count() >= 1);
    await Promise.all([page.waitForURL(/project=/, { timeout: 10000 }).catch(() => {}), page.selectOption('#f_project', pa)]); await page.waitForLoadState();
    check('n° 7 : filtrage dès la sélection du mandat', page.url().includes(`project=${pa}`), page.url());
    check('pas de débordement horizontal', await noOverflow(page));
    await shot(page, `saisies-${label}`);

    section = `mandats ${label}`;                                                           // n° 9 (R-7)
    await page.goto(BASE + '/?tab=mandates');
    check('R-7 : plus de « Clôturer » dans le tableau des mandats', await page.locator('.p-detail form[action$="/close"]').count() === 0);
    await page.goto(BASE + `/project/${pb}/edit`);
    check('R-7 : « Clôturer » dans la page du mandat, motif obligatoire', await page.locator(`#cloture form[action="/project/${pb}/close"] input[name=reason][required]`).count() === 1);
    check('pas de débordement horizontal', await noOverflow(page));
    await ctx.close();
  }
  section = 'global'; check('aucune erreur console / JS', errs.length === 0, errs.join(' ; '));
  await browser.close();
  const ko = results.filter(r => !r.ok).length; console.log(`RÉSULTAT ux-lot2 : ${results.length - ko}/${results.length} OK, ${ko} KO`); process.exit(ko ? 1 : 0);
})();
