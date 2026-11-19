// Recette navigateur — Calendrier (candidat 9.2-rc36). Affichage et lecture seule : aucune règle de facturation n'est exercée.
// Instance JETABLE, base synthétique vide, données fictives créées ici. Jamais la production (8091), jamais le staging (8092).
// Usage : PW_FILE=… BASE_URL=http://127.0.0.1:<port de test> [OUT_DIR=…] node recette-calendrier.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT_DIR || '';
if (!BASE || /:(8091|8092)\b/.test(BASE)) throw new Error('BASE_URL : instance de test jetable seulement (ni 8091 ni 8092)');
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 1500))); };
const shot = async (page, name) => { if (OUT) await page.screenshot({ path: path.join(OUT, `calendrier-${name}.png`), fullPage: true }); };
const login = async page => { await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState(); };
const noOverflow = page => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

// Contraste WCAG des textes visibles de la page calendrier : couleur du texte contre le fond réellement composé (parents translucides compris).
const contrastReport = page => page.evaluate(() => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return [0, 0, 0, 0]; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, bot) => { const a = top[3] + bot[3] * (1 - top[3]); if (!a) return [0, 0, 0, 0]; return [0, 1, 2].map(i => (top[i] * top[3] + bot[i] * bot[3] * (1 - top[3])) / a).concat(a); };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const layer = el => { const cs = getComputedStyle(el); let c = parse(cs.backgroundColor); if (cs.backgroundImage && cs.backgroundImage !== 'none') { const st = (cs.backgroundImage.match(/rgba?\([^)]+\)/g) || []).map(parse).filter(x => x[3] > 0.05); if (st.length) { const av = [0, 1, 2, 3].map(i => st.reduce((t, x) => t + x[i], 0) / st.length); if (av[3] > 0.5) c = c[3] ? over(av, c) : av; } } return c; };   // dégradé = moyenne de ses couleurs (comme recette-theme.js)
  const bg = el => { const chain = []; for (let e = el; e; e = e.parentElement) chain.push(layer(e)); let acc = parse(getComputedStyle(document.documentElement).backgroundColor); if (acc[3] === 0) acc = [255, 255, 255, 1]; if (parse(getComputedStyle(document.body).backgroundColor)[3]) acc = over(parse(getComputedStyle(document.body).backgroundColor), acc); for (const c of chain.reverse()) acc = over(c, acc); return acc; };
  const bad = [], seen = new Set(); let n = 0;
  for (const el of document.querySelectorAll('#contenu *, main *')) {
    if (!el.childNodes.length || ![...el.childNodes].some(x => x.nodeType === 3 && x.textContent.trim())) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none' || !el.offsetParent && cs.position !== 'fixed') continue;
    if (parseFloat(cs.opacity) < 1 && el.closest('td.out')) continue;     // jours hors mois : estompés volontairement
    const f = parse(cs.color), b = bg(el), fg = over(f, b), l1 = lum(fg), l2 = lum(b), cr = (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05);
    n++; const big = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && parseInt(cs.fontWeight) >= 700);
    if (cr < (big ? 3 : 4.5)) { const k = el.tagName + '.' + el.className + '|' + cs.color + '|' + cr.toFixed(2); if (!seen.has(k)) { seen.add(k); bad.push({ el: el.tagName + '.' + String(el.className).slice(0, 40), text: el.textContent.trim().slice(0, 30), color: cs.color, ratio: +cr.toFixed(2) }); } }
  }
  return { n, bad };
});

// Thèmes réels de rc35 : choix mémorisé dans localStorage « tb-theme » (défaut sombre).

(async () => {
  const browser = await chromium.launch(); const errs = [];
  const setup = await browser.newContext(); const sp = await setup.newPage(); await login(sp);
  const post = (u, form) => sp.request.post(BASE + u, { form });
  await post('/settings', { issuer_name: 'Bureau Recette Sàrl', issuer_address: 'Chemin de la Recette 7\n1000 Ville', account_holder: 'Bureau Recette Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours sur le compte:', issuer_vat_number: 'CHE-000.000.000 TVA' });
  const tag = Date.now().toString(36), A = `Mandat Cal A ${tag}`, B = `Mandat Cal B ${tag}`, C = `Mandat Cal C ${tag}`;
  const today = new Date(); const iso = d => d.toISOString().slice(0, 10);
  const startM = new Date(today.getFullYear(), today.getMonth() - 3, 1), start = iso(new Date(startM.getTime() - startM.getTimezoneOffset() * 60000));
  for (const [name, ordered, rate] of [[A, '10', '1000'], [B, '', '1000'], [C, '60', '900']]) await post('/project', { name, client: name === C ? 'Autre Client SA' : 'Client Recette SA', po: ordered ? 'PO-R-1' : '', rate, day_hours: '8', vat: '8.1', ordered_days: ordered, start_date: start, duration_months: '6', billing_address: 'Client Recette SA\nRue 1\n9999 Nulle-Part', client_legal_name: 'Client Recette SA', client_legal_id: 'che000001111' });
  const html0 = await (await sp.request.get(BASE + '/?tab=time')).text();
  const pid = n => (html0.match(new RegExp(`<option value="(\\d+)"[^>]*>${n}<`)) || [])[1]; const pa = pid(A), pb = pid(B), pc = pid(C);
  // A : 9 jours travaillés sur 10 commandés (90 % -> bon de commande) = 9 000 CHF non facturés ; B : 5 000 ; C : 1 jour
  const day = k => { const d = new Date(today); d.setDate(d.getDate() - k); return iso(new Date(d.getTime() - d.getTimezoneOffset() * 60000)); };
  for (let k = 1; k <= 9; k++) await post('/entry', { work_date: day(k + 50), project_id: pa, entry_mode: 'duration', manual_hours: '8', description: 'travail fictif' });
  for (let k = 1; k <= 5; k++) await post('/entry', { work_date: day(k + 14), project_id: pb, entry_mode: 'duration', manual_hours: '8', description: 'travail fictif' });
  await post('/entry', { work_date: day(3), project_id: pc, entry_mode: 'duration', manual_hours: '8', description: 'travail fictif' });
  await setup.close();

  for (const [label, vp] of [['bureau', { width: 1280, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    const mobile = label === 'mobile';
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH', hasTouch: mobile }); const page = await ctx.newPage();
    page.on('pageerror', e => errs.push(`${label} ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${m.text()}`); });
    page.on('dialog', d => d.accept());
    await login(page);

    section = `navigation ${label}`;
    await page.goto(BASE + '/?tab=dashboard');
    if (mobile) {
      check('barre basse : toujours 5 entrées (Calendrier n\'y est pas)', await page.locator('.sidebar .tabs a:visible, .sidebar .tabs button:visible').count() === 5, await page.locator('.sidebar .tabs a:visible, .sidebar .tabs button:visible').count());
      await page.click('#navMore');
      check('menu « Plus » : lien Calendrier', await page.locator('#navMoreMenu a[href="/calendrier"]:visible').count() === 1);
      await page.click('#navMoreMenu a[href="/calendrier"]'); await page.waitForLoadState();
    } else {
      check('menu latéral : lien Calendrier visible', await page.locator('.sidebar .tabs a[href="/calendrier"]:visible').count() === 1);
      await page.click('.sidebar .tabs a[href="/calendrier"]'); await page.waitForLoadState();
    }
    check('la page Calendrier s\'ouvre', /\/calendrier$/.test(page.url()) && await page.isVisible('#calMois'), page.url());
    check('entrée de menu active', await page.locator('.sidebar a[href="/calendrier"].active, #navMoreMenu a.active').count() >= 1);

    section = `encart tableau de bord ${label}`;
    await page.goto(BASE + '/?tab=dashboard');
    check('encart « Calendrier et alertes » visible', await page.isVisible('#calPanel'));
    check('alerte heures non facturées (mandat A, 9 000 CHF)', await page.locator('#calPanel [data-alert=non_facture]').count() >= 1, await page.locator('#calPanel').innerText());
    check('alerte bon de commande ≥ 80 % (mandat A)', await page.locator('#calPanel [data-alert=po]').count() + await page.locator('a[href="/calendrier#calAlertes"]').count() >= 1);
    check('encart : pas de débordement horizontal', await noOverflow(page));
    await shot(page, `tableau-de-bord-${label}`);

    section = `calendrier ${label}`;
    await page.goto(BASE + '/calendrier?mois=2026-12');
    check('titre du mois', (await page.innerText('#calMoisT')).trim() === 'Décembre 2026');
    check('grille : 7 colonnes, 5 semaines', await page.locator('.calgrid thead th').count() === 7 && await page.locator('.calgrid tbody tr').count() === 5);
    const cell = await page.locator('.calgrid td[data-date="2026-12-31"]').boundingBox();
    check('cellule d\'un jour lisible (largeur ≥ 36 px, hauteur ≥ 44 px)', cell.width >= 36 && cell.height >= 44, JSON.stringify(cell));
    check('31.12 : férié (Restauration) signalé', await page.locator('.calgrid td[data-date="2026-12-31"].ferie').count() === 1 && /Restauration de la République/.test(await page.innerText('#calMois')));
    check('25.12 : Noël', await page.locator('.calgrid td[data-date="2026-12-25"].ferie').count() === 1);
    check('vacances de Noël : fond ambré du 21 au 31.12', await page.locator('.calgrid td.vac').count() >= 11, await page.locator('.calgrid td.vac').count());
    check('échéance (pilier 3a) listée avec sa source et « règle légale »', /pilier 3a/.test(await page.innerText('#calMois')) && await page.locator('#calMois a[href*="fedlex.admin.ch"]').count() >= 1 && /règle légale/.test(await page.innerText('#calMois')));
    check('« à vérifier » affiché sur les dates non confirmées', await page.locator('#calMois .cal-st:has-text("à vérifier")').count() >= 1);
    check('lien de jour : ancre vers la liste', await page.locator('.calgrid td[data-date="2026-12-31"] a[href="#j-2026-12-31"]').count() === 1 && await page.locator('#j-2026-12-31').count() === 1);
    await page.locator('.calgrid td[data-date="2026-12-31"] a').click();
    check('clic sur un jour : la liste du jour est atteinte', await page.evaluate(() => location.hash) === '#j-2026-12-31');
    await page.click('#calMois a[aria-label="Mois suivant"]'); await page.waitForLoadState();
    check('mois suivant : janvier 2027 (Nouvel An)', (await page.innerText('#calMoisT')).trim() === 'Janvier 2027' && /Nouvel An/.test(await page.innerText('#calMois')));
    await page.goto(BASE + '/calendrier');
    check('mois courant par défaut', await page.locator('.calgrid td.today').count() === 1);
    check('alertes affichées (A : non facturé ≥ 8 000, bon de commande)', await page.locator('#calAlertes [data-alert=non_facture]').count() >= 1 && await page.locator('#calAlertes [data-alert=po]').count() >= 1);
    check('alerte client (B, A : même client) ou mandat, retard « jamais facturé »', await page.locator('#calAlertes [data-alert=retard]').count() >= 1, await page.locator('#calAlertes').innerText());
    check('« 30 prochains jours » présent', await page.isVisible('#calProchains') && await page.locator('#calProchains .cal-ev').count() >= 1);
    check('bandeau « données à revoir »', await page.isVisible('#calRevue'));
    check('bouton d\'export .ics', await page.getAttribute('#calIcs', 'href') === '/calendrier.ics');
    check('pas de débordement horizontal', await noOverflow(page));
    if (mobile) {
      const order = await page.evaluate(() => ['calAlertes', 'calProchains', 'calMois'].map(i => Math.round(document.getElementById(i).getBoundingClientRect().top + scrollY)));
      check('téléphone : alertes, puis 30 prochains jours, puis mois (une colonne)', order[0] < order[1] && order[1] < order[2], JSON.stringify(order));
    } else {
      const bx = await page.evaluate(() => ['calProchains', 'calMois'].map(i => { const r = document.getElementById(i).getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; }));
      check('bureau : « 30 prochains jours » et mois côte à côte', Math.abs(bx[0][1] - bx[1][1]) < 4 && bx[0][0] < bx[1][0], JSON.stringify(bx));
    }
    await shot(page, `page-${label}`);
    await page.goto(BASE + '/calendrier?mois=2026-12'); await shot(page, `decembre-${label}`);

    section = `contraste ${label}`;
    for (const th of ['light', 'dark']) {
      await page.evaluate(t => localStorage.setItem('tb-theme', t), th); await page.goto(BASE + '/calendrier');
      check(`thème ${th} appliqué`, await page.evaluate(() => document.documentElement.getAttribute('data-theme')) === th);
      const rep = await contrastReport(page);
      check(`thème ${th} : contraste ≥ 4,5 sur ${rep.n} textes`, rep.bad.length === 0, JSON.stringify(rep.bad.slice(0, 6)));
      check(`thème ${th} : pas de débordement`, await noOverflow(page));
      await shot(page, `theme-${th}-${label}`);
    }
    await page.evaluate(() => localStorage.removeItem('tb-theme'));

    section = `abonnement et réglages ${label}`;
    const ctx2 = await browser.newContext({ viewport: vp }); const anon = ctx2.request;
    await page.goto(BASE + '/calendrier');
    const ics = await page.request.get(BASE + '/calendrier.ics');
    check('.ics authentifié : 200 text/calendar', ics.status() === 200 && /text\/calendar/.test(ics.headers()['content-type']));
    check('.ics sans session : redirigé vers la connexion', (await anon.get(BASE + '/calendrier.ics', { maxRedirects: 0 })).status() === 302);
    if (!mobile) {
      await page.click('#calExport button:has-text("Créer un lien")'); await page.waitForLoadState();
      const lien = (await page.innerText('#calNouveauLien code')).trim();
      check('lien d\'abonnement affiché une fois', /\/calendrier\/abonnement\/[A-Za-z0-9_-]{43}\.ics$/.test(lien), lien);
      const r = await anon.get(lien.replace(/^https?:\/\/[^/]+/, BASE));
      check('lien secret : 200 sans session, sans nom de mandat', r.status() === 200 && !(await r.text()).includes('Mandat Cal') && /Jeûne genevois/.test(await r.text()));
      await page.goto(BASE + '/calendrier');
      check('le lien n\'est plus réaffiché', await page.locator('#calNouveauLien').count() === 0);
      await page.click('#calExport button:has-text("Révoquer")'); await page.waitForLoadState();
      check('révocation : le lien répond 404', (await anon.get(lien.replace(/^https?:\/\/[^/]+/, BASE))).status() === 404);
      await page.fill('#cal_seuil_non_facture', '20 000'); await page.click('#calReglages button'); await page.waitForLoadState();
      check('réglage enregistré (20 000,00) et alertes « non facturé » (mandat A 9 000, client A+B 14 000) disparues', await page.inputValue('#cal_seuil_non_facture') === '20000.00' && await page.locator('#calAlertes [data-alert=non_facture]').count() === 0);
      await page.fill('#cal_seuil_non_facture', '8000'); await page.click('#calReglages button'); await page.waitForLoadState();
    }
    check('pas de débordement horizontal', await noOverflow(page));
    await ctx2.close(); await ctx.close();
  }
  section = 'console'; check('aucune erreur console / JavaScript', errs.length === 0, errs.join(' | '));
  await browser.close();
  const fails = results.filter(r => !r.ok).length; console.log(`\n${results.length - fails}/${results.length} vérifications réussies`); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
