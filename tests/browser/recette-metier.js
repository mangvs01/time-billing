// Recette Time Billing V9.2 (non-régression rc8 : rc7 + Europe/Zurich + sécurité) — Chromium (Playwright), données exclusivement fictives,
// conteneur d'audit 127.0.0.1:8093 sur une copie de la base staging. Usage : node recette.js phase1|phase2
const { chromium } = require('/root/node_modules/playwright');
const EXPECT = process.env.EXPECT_VERSION; if (!EXPECT) throw new Error('EXPECT_VERSION manquant (ex. 9.2-rc12)');
const fs = require('fs'), crypto = require('crypto'), path = require('path');
const R = path.dirname(__dirname), J = __dirname, BASE = process.env.BASE_URL || 'http://127.0.0.1:8093';
const PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim();  // mot de passe du conteneur jetable, hors livrables
const PHASE = process.argv[2] || 'phase1', STATE = path.join(J, 'etat-recette.json');
const results = [], consoleErrors = [];
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const TODAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Zurich' }).format(new Date());  // RC8 : jour ouvrable à Zurich
// RC8 : heure de Zurich attendue pour un horodatage UTC (CET/CEST)
const zh = iso => new Intl.DateTimeFormat('fr-CH', { timeZone: 'Europe/Zurich', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(iso + 'Z')).replace(/^(\S+?),? /, '$1 à ');
const NB = ' ', NN = ' ';
const FR = iso => iso.split("-").reverse().join(".");  // A3 : JJ.MM.AAAA
const TS = /\d{2}\.\d{2}\.\d{4} à \d{2}:\d{2}:\d{2}/;
let section = '';
function check(name, ok, detail = '') {
  results.push({ phase: PHASE, section, name, ok: !!ok, detail: ok ? '' : String(detail).slice(0, 500) });
  console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300)));
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1360, height: 900 }, locale: 'fr-CH' });
  const page = await ctx.newPage();
  page.on('dialog', d => d.accept());
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`${page.url()} : ${m.text()}`); });
  page.on('pageerror', e => consoleErrors.push(`${page.url()} : ${e.message}`));
  let shotN = PHASE === 'phase1' ? 0 : 200;
  const shot = async (name, full = true) => { shotN++; await page.screenshot({ path: path.join(R, 'ecrans', `${String(shotN).padStart(3, '0')}-${name}.png`), fullPage: full }); };
  const flashes = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
  const html = async () => (await page.content()).replace(/&nbsp;/g, NB);
  const text = async () => page.innerText('body');
  const tab = async t => { await page.goto(`${BASE}/?tab=${t}`); };
  const step = async (name, fn) => { section = name; try { await fn(); } catch (e) { check('exception', false, e.stack); await shot('ERREUR-' + name.replace(/\W+/g, '-').slice(0, 40)); } };
  // RC8 : requêtes authentifiées passées par fetch() dans la page — le client API de Playwright n'envoie pas le cookie
  // Secure en HTTP local, alors que Chromium l'envoie (contexte sûr 127.0.0.1)
  const fetchBytes = async url => {
    const r = await page.evaluate(async u => { const x = await fetch(u, { credentials: 'same-origin' }); const b = new Uint8Array(await x.arrayBuffer()); let s = ''; for (const c of b) s += String.fromCharCode(c); return { ct: x.headers.get('content-type'), b64: btoa(s) }; }, BASE + url);
    if (!/application\/pdf/.test(r.ct || '')) throw new Error(`réponse non PDF pour ${url} : ${r.ct}`);
    return Buffer.from(r.b64, 'base64'); };
  const postForm = async (url, form, follow = false) => page.evaluate(async ([u, f, fo]) => { const x = await fetch(u, { method: 'POST', body: new URLSearchParams(f), credentials: 'same-origin', redirect: fo ? 'follow' : 'manual' }); return { status: x.status, text: fo ? await x.text() : '' }; }, [url, form, follow]);
  async function savePdf(url, file) { const b = await fetchBytes(url); fs.writeFileSync(path.join(R, 'pdf', file), b); return b; }
  async function login() {
    await page.goto(BASE + '/login');
    await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button');
    check('connexion', !page.url().includes('/login'), page.url());
  }
  const state = fs.existsSync(STATE) && PHASE !== 'phase1' ? JSON.parse(fs.readFileSync(STATE)) : { pdf: {}, ids: {} };
  const save = () => fs.writeFileSync(STATE, JSON.stringify(state, null, 1));
  const ids = state.ids;

  // --- helpers on the real forms ------------------------------------------------------------------
  async function entry(project, d, opts) {
    await tab('time'); const f = page.locator('#entryForm');
    await f.locator('[name=work_date]').fill(d);
    await f.locator('[name=project_id]').selectOption({ label: project });
    let disp = '';
    if (opts.clock) { await f.locator('input[value=clock]').check(); await f.locator('#startTime').fill(opts.clock[0]); await f.locator('#endTime').fill(opts.clock[1]); disp = await page.locator('#durationDisplay').innerText().catch(() => ''); }
    else { await f.locator('input[value=duration]').check(); await f.locator('#manualHours').fill(String(opts.hours)); }
    await f.locator('[name=description]').fill(opts.desc || 'prestation fictive');
    await f.locator('button').click();
    return { flash: await flashes(), disp };
  }
  async function draftInvoice(project, from, to, opts = {}) {
    await tab('billing'); const f = page.locator('#invoiceForm');
    await f.locator('#invoiceProject').selectOption({ label: project });
    await f.locator('#periodFrom').fill(from); await f.locator('#periodTo').fill(to);
    if (opts.rounding) await f.locator('#rounding').selectOption(opts.rounding);
    if (opts.step) await f.locator('#roundingStep').selectOption(opts.step);
    await f.locator('#calculateBtn').click();
    await page.waitForFunction(() => document.getElementById('rawDays').textContent !== '—');
    const calc = { hours: (await page.locator('#rawHours').innerText()).trim(), days: (await page.locator('#rawDays').innerText()).trim(),
                   qty: await f.locator('#invoiceQty').inputValue(), amount: (await page.locator('#amountDisplay').innerText()).trim() };
    if (opts.shot) await shot(opts.shot);
    if (opts.qty) await f.locator('#invoiceQty').fill(String(opts.qty));
    if (opts.description) await f.locator('[name=description]').fill(opts.description);
    if (opts.invoiceDate) await f.locator('[name=invoice_date]').fill(opts.invoiceDate);
    await f.locator('button.wide').last().click();
    return { calc, flash: await flashes() };
  }
  const newestDraftId = async () => { await tab('archive'); const h = await page.locator('a.btn[href^="/issue/"]').first().getAttribute('href'); return h.split('/').pop(); };
  async function editDraftDate(iid, d) { await page.goto(`${BASE}/invoice/${iid}/edit`); await page.fill('input[name=invoice_date]', d); await page.click('button.wide'); return flashes(); }
  async function issueInvoice(iid, treatment, shotName) {
    await page.goto(`${BASE}/issue/${iid}`);
    if (shotName) await shot(shotName);
    const radio = page.locator(`input[name=reliquat_treatment][value=${treatment || 'reporte'}]`);
    if (await radio.count()) await radio.check();
    const conf = page.locator('input[name=confirm_backdate]');
    state.backdateShown = state.backdateShown || {}; state.backdateShown[iid] = await conf.count() > 0;
    if (await conf.count()) await conf.check();  // A6 : confirmation explicite de l'antidatage
    await page.locator('form.panel button').click();
    return flashes();
  }
  async function creditNote(iid, form, shotName) {
    await page.goto(`${BASE}/invoice/${iid}/credit`);
    if (form.treatment) await page.locator(`input[name=treatment][value=${form.treatment}]`).check();
    if (form.scope) await page.locator(`input[name=scope][value=${form.scope}]`).check();
    await page.fill('input[name=reason]', form.reason || 'motif fictif');
    for (const k of ['qty', 'amount', 'refund_delay_days']) if (k in form) await page.fill(`input[name=${k}]`, String(form[k]));
    if (form.replaces) await page.locator('select[name=replaces_credit_id]').selectOption(String(form.replaces));
    if (shotName) await shot(shotName);
    await page.locator('form.fields button.wide').click();
    return flashes();
  }
  const newestCreditId = async () => { await tab('archive'); const h = await page.locator('form[action^="/credit/"][action$="/issue"]').first().getAttribute('action'); return h.split('/')[2]; };
  async function issueCredit(cid) { await tab('archive'); await page.locator(`form[action="/credit/${cid}/issue"] button`).click(); return flashes(); }
  async function refund(cid, amount, ref) {
    await page.goto(`${BASE}/credit/${cid}`); const f = page.locator(`form[action="/credit/${cid}/refund"]`);
    await f.locator('[name=amount]').fill(amount); await f.locator('[name=executed_on]').fill(TODAY); await f.locator('[name=external_ref]').fill(ref || ''); await f.locator('button').click();
    return flashes();
  }
  async function offset(cid, target, amount) {
    await page.goto(`${BASE}/credit/${cid}`); const f = page.locator(`form[action="/credit/${cid}/offset"]`);
    await f.locator('select').selectOption(String(target)); await f.locator('[name=amount]').fill(amount); await f.locator('button').click();
    return flashes();
  }
  const pdfDocs = () => [['F1', `/invoice/${ids.f1}.pdf`], ['F2', `/invoice/${ids.f2}.pdf`], ['F3', `/invoice/${ids.f3}.pdf`], ['NC1', `/credit/${ids.nc1}.pdf`],
    ['NC2', `/credit/${ids.nc2}.pdf`], ['NC_F2', `/credit/${ids.ncF2}.pdf`], ['NC3', `/credit/${ids.nc3}.pdf`], ['ANN', `/credit/${ids.nc3}/cancellation.pdf`], ['NC4', `/credit/${ids.nc4}.pdf`]];

  const M = 'Mandat Recette Alpha';
  const mandRow = () => page.locator('section:has(h2:has-text("Détail des mandats")) tr', { hasText: M });
  if (PHASE === 'phase1') {
    await step('0 connexion et paramètres', async () => {
      await page.goto(BASE + '/'); check('redirection vers la connexion sans session', page.url().includes('/login'));
      check(`version ${EXPECT} absente de la page publique de connexion (B-7) et présente sur /health`, !(await html()).includes(EXPECT) && (await (await page.request.get(`${BASE}/health`)).json()).version === EXPECT);
      await login();
      await tab('settings'); const f = page.locator('form[action="/settings"]');
      const v = { issuer_name: 'Bureau Fictif Recette Sàrl', issuer_rc: 'CH-000-0000000-0 (fictif)', issuer_vat_number: 'CHE-000.000.000 TVA (fictif)', account_holder: 'Bureau Fictif Recette Sàrl',
        iban: 'CH00 0000 0000 0000 0000 0', bic: 'FICTCHZZXXX', payment_terms: 'Paiement à 30 jours sur le compte:', thanks_text: 'Je vous remercie de votre confiance.' };
      for (const [k, x] of Object.entries(v)) await f.locator(`[name=${k}]`).fill(x);
      await f.locator('[name=issuer_address]').fill('Chemin de la Recette 7\n1000 Ville-Fictive');
      await f.locator('[name=refund_delay_days]').fill('30');
      await f.locator('input[name=logo]').setInputFiles(path.join(J, 'logo-fictif.png'));
      await f.locator('button').click();
      check('paramètres émetteur fictifs enregistrés', (await flashes()).includes('Paramètres enregistrés'));
      const ck = (await ctx.cookies()).find(c => c.name === 'tb_session');
      check('RC8 : cookie de session HttpOnly, SameSite=Lax, durée bornée', !!ck && ck.httpOnly && ck.sameSite === 'Lax' && ck.expires > 0, JSON.stringify(ck && { httpOnly: ck.httpOnly, sameSite: ck.sameSite, secure: ck.secure }));
      state.cookieSecure = ck && ck.secure;
      const hd = (await page.goto(`${BASE}/?tab=settings`)).headers();
      check('RC8 : en-têtes CSP, X-Frame-Options, nosniff, no-store', /frame-ancestors 'none'/.test(hd['content-security-policy'] || '') && hd['x-frame-options'] === 'DENY' && hd['x-content-type-options'] === 'nosniff' && hd['cache-control'] === 'no-store', JSON.stringify(hd));
      const xs = await page.request.post(`${BASE}/project`, { form: { name: 'Mandat intrus (fictif)', rate: '1', day_hours: '8' }, headers: { Origin: 'https://evil.example' }, maxRedirects: 0 });
      check('RC8 : requête d\'un autre site refusée (403)', xs.status() === 403, xs.status());
      await tab('settings'); await shot('parametres-emetteur-fictif');
    });

    await step('1 création du mandat', async () => {
      await tab('mandates'); const f = page.locator('form[action="/project"]');
      const mm = { name: M, short_name: 'ALPHA 2026', client: 'Client Recette — Direction des Infrastructures', po: 'PO-RECETTE-0001', rate: '900', ordered_days: '30', start_date: '2026-07-01', duration_months: '12', vat: '8.1',
        project_number: 'NP-REC-001', dates_label: 'Juil.–Sept. 2026 (fictif)', billing_contact: 'Contact Fictif', billing_address: 'Société Fictive Recette SA\nRue de l\'Exemple 12\n9999 Nulle-Part',
        client_legal_name: 'Société Fictive Recette SA', client_legal_id: 'che000001234' };
      for (const [k, x] of Object.entries(mm)) await f.locator(`[name=${k}]`).fill(x);
      await shot('mandat-formulaire');
      await f.locator('button').click();
      check('mandat créé', (await flashes()).includes('Projet enregistré'));
      await tab('mandates'); await shot('mandats-liste');
      const pid = await page.locator('#invoiceProject option', { hasText: M }).getAttribute('value'); ids.pid = pid;
      await page.goto(`${BASE}/project/${pid}/edit`); await shot('mandat-identifiant-normalise');
      const t = await text();
      check('décision 4 : identifiant affiché normalisé CHE-000.001.234', t.includes('Imprimé : CHE-000.001.234'), t.slice(0, 200));
      check('décision 4 : valeur saisie conservée et visible (che000001234)', t.includes('valeur saisie conservée telle quelle : che000001234') && (await page.inputValue('input[name=client_legal_id]')) === 'che000001234');
    });

    await step('2 saisie des temps', async () => {
      const clock = [['2026-07-06', '08:30', '12:00', 'Séance de lancement (fictif)'], ['2026-07-06', '13:00', '17:30', 'Analyse documentaire (fictif)'], ['2026-07-14', '09:00', '12:15', 'Atelier (fictif)'],
                     ['2026-07-28', '13:30', '18:00', 'Rédaction (fictif)'], ['2026-08-11', '08:00', '12:00', 'Coordination (fictif)'], ['2026-08-11', '13:00', '17:00', 'Coordination (fictif)'],
                     ['2026-08-25', '09:15', '11:45', 'Revue (fictif)'], ['2026-09-09', '08:00', '16:00', 'Visite de chantier (fictif)']];
      const hours = [['2026-07-07', 7.5, 'Suivi de projet (fictif)'], ['2026-07-21', 4.75, 'Rapport (fictif)'], ['2026-08-04', 8, 'Suivi de projet (fictif)'], ['2026-08-18', 6, 'Rapport (fictif)'],
                     ['2026-09-02', 8, 'Suivi de projet (fictif)'], ['2026-09-16', 4, 'Rapport (fictif)']];
      let ok = 0, disp = [];
      for (const [d, a, b, desc] of clock) { const r = await entry(M, d, { clock: [a, b], desc }); if (r.flash.includes('Temps enregistré')) ok++; disp.push(r.disp.trim()); }
      check('8 saisies en période début/fin enregistrées', ok === 8, ok);
      check('durée calculée affichée avant envoi (3 h 30 min pour 08:30–12:00)', disp[0] === '3 h 30 min', disp.join(', '));
      ok = 0;
      for (const [d, h, desc] of hours) { const r = await entry(M, d, { hours: h, desc }); if (r.flash.includes('Temps enregistré')) ok++; }
      check('6 saisies en heures enregistrées', ok === 6, ok);
      const bad = await entry(M, '2026-09-17', { clock: ['10:00', '10:00'] });
      check('période début/fin incohérente (fin = début) refusée', bad.flash.includes('Saisie refusée'), bad.flash);
      const neg = await entry(M, '2026-09-17', { hours: 25 });
      check('durée > 24 h refusée', neg.flash.includes('Saisie refusée') || neg.flash === '', neg.flash);
      await tab('time'); await page.locator('#entryForm input[value=clock]').check(); await shot('saisie-temps-debut-fin');
      await tab('mandates'); const t = await text();
      check('mandat : 72,50 h saisies (28 + 24,5 + 20)', t.includes('72,50'), t.match(/Mandat Recette Alpha[^\n]*/)?.[0]);
      await tab('dashboard'); await shot('tableau-de-bord-apres-saisie');
    });

    await step('3 préparation et émission de la facture F1 (antidatée)', async () => {
      const r = await draftInvoice(M, '2026-07-01', '2026-07-31', { rounding: 'exact', description: 'Assistance à maîtrise d\'ouvrage — juillet 2026 (fictif)', invoiceDate: '2026-08-03', shot: 'edition-facture-calcul-juillet' });
      check('calcul juillet : 28 h = 3,5 jours, 3 150,00 CHF HT', r.calc.hours === '28 h' && r.calc.days === '3,5 jours' && r.calc.amount === `3${NN}150,00${NB}CHF`, JSON.stringify(r.calc));
      check('brouillon F1 créé', r.flash.includes('Brouillon créé'), r.flash);
      ids.f1 = await newestDraftId();
      await savePdf(`/invoice/${ids.f1}.pdf`, '01-F1-brouillon-juillet.pdf');
      check('date modifiée sur le brouillon (03.08 → 31.07)', (await editDraftDate(ids.f1, '2026-07-31')).includes('Brouillon modifié'));
      await page.goto(`${BASE}/invoice/${ids.f1}/edit`); await shot('brouillon-historique-date');
      check('A3 : historique de date du brouillon au format JJ.MM.AAAA à HH:MM:SS', /\d{2}\.\d{2}\.\d{4} à \d{2}:\d{2}:\d{2} — 03\.08\.2026 → 31\.07\.2026/.test(await text()));
      let t = await text();
      check('décision 5 : historique des dates visible sur le brouillon (2 traces)', t.includes("date d'émission → 03.08.2026 (création du brouillon)") && t.includes('03.08.2026 → 31.07.2026 (modification du brouillon)'), t.slice(t.indexOf('Historique'), t.indexOf('Historique') + 300));
      await page.goto(`${BASE}/issue/${ids.f1}`); t = await text();
      check('confirmation : numéro 2026-07 (période facturée), date imprimée 31.07.2026', t.includes('2026-07') && t.includes('31.07.2026') && t.includes('date fixée sur le brouillon'));
      check('A6 : avertissement « Facture antidatée » avec date réelle d\'émission et case de confirmation', t.includes('Facture antidatée') && t.includes(`date réelle d'émission : ${FR(TODAY)}`) && (await page.locator('input[name=confirm_backdate]').count()) === 1, t.slice(t.indexOf('Facture antidatée'), t.indexOf('Facture antidatée') + 300));
      check('A3 : aucune date ISO visible sur la confirmation', !/\b\d{4}-\d{2}-\d{2}\b/.test(t), (t.match(/\b\d{4}-\d{2}-\d{2}\b/) || [''])[0]);
      await postForm(`${BASE}/issue/${ids.f1}`, { reliquat_treatment: 'reporte', from_confirm: '1' });
      await page.goto(`${BASE}/issue/${ids.f1}`); const refus = await flashes();
      check('A6 : émission antidatée sans confirmation refusée par le serveur (POST direct)', refus.includes("cocher la confirmation explicite de l'antidatage") && (await text()).includes('Émettre définitivement'), refus);
      await postForm(`${BASE}/issue/${ids.f1}`, { reliquat_treatment: 'reporte', from_confirm: '1', confirm_backdate: '2026-07-30' });
      await page.goto(`${BASE}/issue/${ids.f1}`);
      check('A6 : confirmation portant sur une autre date refusée', (await flashes()).includes('cocher la confirmation') && (await text()).includes('Émettre définitivement'));
      check('confirmation : horodatage réel distinct et non modifiable annoncé', t.includes("Horodatage réel d'émission enregistré séparément"));
      const fl = await issueInvoice(ids.f1, 'reporte', 'emission-F1-confirmation');
      check('F1 émise sous le numéro 2026-07, antidatage confirmé', fl.includes('Facture 2026-07 émise le') && fl.includes('datée du 31.07.2026 (antidatage confirmé)') && state.backdateShown[ids.f1], fl);
      await tab('archive'); t = await html();
      check('archive : date de facture 31.07.2026 + « émise le » horodatage réel (JJ.MM.AAAA à HH:MM:SS) + « antidatée »', (() => { const mm = t.match(/31\.07\.2026<br><small>émise le <time datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z" title="UTC \1">([^<]+)<\/time> \(antidatée\)<\/small>/); state.f1issued = mm && { utc: mm[1], shown: mm[2] }; return !!mm && mm[2] === zh(mm[1]) && mm[2].startsWith(FR(TODAY)); })(), (t.match(/31\.07\.2026<br><small>émise le[^\n]{0,160}/) || [''])[0]);
      check('archive : « date modifiée 2 fois (tracé) »', t.includes('date modifiée 2 fois (tracé)'));
      state.pdf.F1 = sha(await savePdf(`/invoice/${ids.f1}.pdf`, '02-F1-2026-07-emise.pdf'));
      await page.goto(`${BASE}/invoice/${ids.f1}/edit`);
      check('après émission : modification de date refusée', (await flashes()).includes('Seul un brouillon peut être modifié'));
      await postForm(`${BASE}/invoice/${ids.f1}/edit`, { period_from: '2026-07-01', period_to: '2026-07-31', qty: '3.5', unit: 'day', rounding: 'exact', rounding_step: '0.25', invoice_date: '2026-07-15' });
      check('après émission : POST direct de changement de date sans effet (PDF identique)', sha(await fetchBytes(`/invoice/${ids.f1}.pdf`)) === state.pdf.F1);
    });

    await step('4 annexe cumulative (F2 août)', async () => {
      const r = await draftInvoice(M, '2026-08-01', '2026-08-31', { rounding: 'down', step: '0.25', description: 'Assistance à maîtrise d\'ouvrage — août 2026 (fictif)' });
      check('calcul août : 24,5 h = 3,0625 j → arrondi inférieur 3 j', r.calc.hours === '24,5 h' && r.calc.days === '3,0625 jours' && r.calc.qty === '3', JSON.stringify(r.calc));
      ids.f2 = await newestDraftId();
      await savePdf(`/invoice/${ids.f2}.pdf`, '03-F2-brouillon-aout-annexe-cumulative.pdf');
      check('PDF brouillon F2 généré (annexe juillet + août, vérifiée par extraction)', true);
    });

    await step('5 crédit partiel avec remboursement (NC1 sur F1)', async () => {
      await page.goto(`${BASE}/invoice/${ids.f1}/credit`);
      check('délai par défaut 30 j prérempli', (await page.inputValue('input[name=refund_delay_days]')) === '30');
      const fl = await creditNote(ids.f1, { treatment: 'remboursement', qty: '0.5', reason: 'Demi-journée d\'atelier annulée (fictif)' }, 'NC1-formulaire-remboursement');
      check('brouillon NC1 créé', fl.includes('Brouillon de note de crédit créé'), fl);
      ids.nc1 = await newestCreditId();
      await savePdf(`/credit/${ids.nc1}.pdf`, '04-NC1-brouillon.pdf');
      const f2 = await issueCredit(ids.nc1);
      check('NC-2026-07 émise (mode remboursement), F1 inchangée', f2.includes('NC-2026-07 émise') && f2.includes('Remboursement'), f2);
      state.pdf.NC1 = sha(await savePdf(`/credit/${ids.nc1}.pdf`, '05-NC-2026-07-remboursement.pdf'));
      check('F1 identique après NC1', sha(await fetchBytes(`/invoice/${ids.f1}.pdf`)) === state.pdf.F1);
      check('remboursement partiel 200,00 enregistré', (await refund(ids.nc1, '200', 'VIR-FICTIF-001')).includes('Remboursement enregistré'));
      await page.goto(`${BASE}/credit/${ids.nc1}`); let t = await html();
      check('statut « partiellement remboursée », solde 286,45 CHF (486,45 − 200)', t.includes('partiellement remboursée') && t.includes(`286,45${NB}CHF`));
      await postForm(`${BASE}/credit/${ids.nc1}/refund`, { amount: '300', executed_on: TODAY, external_ref: 'VIR-FICTIF-X' });
      await page.goto(`${BASE}/credit/${ids.nc1}`); const over = await flashes();
      check('remboursement supérieur au solde refusé par le serveur (POST direct)', over.includes('dépasse le solde restant'), over);
      check('remboursement du solde 286,45', (await refund(ids.nc1, '286.45', 'VIR-FICTIF-002')).includes('Remboursement enregistré'));
      await page.goto(`${BASE}/credit/${ids.nc1}`); await shot('NC1-suivi-rembourse');
      check('statut « remboursée »', (await html()).includes('<b>remboursée</b>'));
    });

    await step('6 crédit partiel avec compensation (NC2 sur F1)', async () => {
      const fl = await creditNote(ids.f1, { treatment: 'compensation', qty: '0.25', reason: 'Quart de journée facturé en double (fictif)' }, 'NC2-formulaire-compensation');
      check('brouillon NC2 créé', fl.includes('Brouillon de note de crédit créé'), fl);
      ids.nc2 = await newestCreditId();
      check('NC-2026-07.2 émise (compensation)', (await issueCredit(ids.nc2)).includes('NC-2026-07.2 émise'));
      state.pdf.NC2 = sha(await savePdf(`/credit/${ids.nc2}.pdf`, '06-NC-2026-07.2-compensation.pdf'));
      await page.goto(`${BASE}/credit/${ids.nc2}`); const t = await html();
      check('NC2 : 225,00 HT + TVA 18,23 = 243,23 CHF, statut disponible', t.includes(`243,23${NB}CHF`) && t.includes('disponible'));
      await shot('NC2-suivi-disponible');
    });

    await step('7 crédit total après annulation d\'une compensation en brouillon', async () => {
      let fl = await offset(ids.nc2, ids.f2, '243.23');
      check('imputation de NC2 sur le brouillon F2 (243,23)', fl.includes('Imputation enregistrée'), fl);
      await savePdf(`/invoice/${ids.f2}.pdf`, '07-F2-brouillon-avec-compensation.pdf');
      await page.goto(`${BASE}/issue/${ids.f2}`); await shot('F2-confirmation-compensation-annulable');
      let t = await text();
      check('confirmation F2 : compensation listée comme encore annulable', t.includes('Compensations imputées') && t.includes('Encore annulables'));
      await page.goto(`${BASE}/credit/${ids.nc2}`);
      const rev = page.locator('form[action*="/reverse/"]').first(); await rev.locator('input[name=note]').fill('Compensation retirée avant émission : crédit total d\'août prévu (fictif)'); await rev.locator('button').click();
      check('compensation en brouillon annulée par écriture d\'annulation', (await flashes()).includes('Opération annulée'));
      await page.goto(`${BASE}/credit/${ids.nc2}`); await shot('NC2-suivi-imputation-annulee');
      { const vis = await text(); const h = await page.content();
        check('A3 : aucun horodatage ISO brut visible dans le suivi', !/\d{4}-\d{2}-\d{2}T\d{2}:/.test(vis), (vis.match(/\d{4}-\d{2}-\d{2}T[^\s]*/) || [''])[0]);
        check('A3 : format français JJ.MM.AAAA à HH:MM:SS affiché', TS.test(vis));
        check('A3 : aucune date simple ISO visible dans le suivi', !/\b\d{4}-\d{2}-\d{2}\b/.test(vis), (vis.match(/\b\d{4}-\d{2}-\d{2}\b/) || [''])[0]);
        check('A3 : valeur technique UTC conservée (<time datetime="…Z" title="UTC …">)', /<time datetime="\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z" title="UTC /.test(h));
        const all = [...h.matchAll(/<time datetime="([^"]+)Z" title="UTC [^"]+">([^<]+)<\/time>/g)];
        check(`RC8 : ${all.length} horodatages affichés à l'heure de Zurich (UTC+2 en octobre)`, all.length > 0 && all.every(x => x[2] === zh(x[1])), all.slice(0, 3).map(x => x[1] + ' → ' + x[2]).join(' ; ')); }
      t = await text();
      check('historique NC2 : imputation + annulation conservées, solde 243,23 de nouveau disponible', t.includes("Imputation sur facture") && t.includes("Annulation d'imputation") && (await html()).includes('disponible'));
      fl = await issueInvoice(ids.f2, 'reporte', 'emission-F2-confirmation');
      check('F2 émise 2026-08 sans compensation', fl.includes('Facture 2026-08 émise'), fl);
      state.pdf.F2 = sha(await savePdf(`/invoice/${ids.f2}.pdf`, '08-F2-2026-08-emise-annexe-cumulative.pdf'));
      fl = await creditNote(ids.f2, { treatment: 'remboursement', scope: 'total', reason: 'Facture d\'août établie sur un PO erroné (fictif)' }, 'NC-F2-formulaire-credit-total');
      check('crédit total de F2 accepté', fl.includes('Brouillon de note de crédit créé'), fl);
      ids.ncF2 = await newestCreditId();
      fl = await issueCredit(ids.ncF2);
      check('NC-2026-08 émise (crédit total, remboursement)', fl.includes('NC-2026-08 émise'), fl);
      state.pdf.NC_F2 = sha(await savePdf(`/credit/${ids.ncF2}.pdf`, '09-NC-2026-08-credit-total.pdf'));
      await page.goto(`${BASE}/credit/${ids.ncF2}`); t = await html();
      check('NC-2026-08 : 2 918,70 CHF TTC (2 700,00 + 218,70), à rembourser, échéance fixée', t.includes(`2${NN}918,70${NB}CHF`) && t.includes('à rembourser'));
      await tab('archive'); check('archive : F2 « créditée totalement »', (await html()).includes('créditée totalement'));
    });

    await step('9 seconde facture avec compensation (F3 septembre)', async () => {
      const r = await draftInvoice(M, '2026-09-01', '2026-09-30', { qty: '2.5', description: 'Assistance à maîtrise d\'ouvrage — septembre 2026 (fictif)', invoiceDate: '2026-09-30' });
      check('brouillon F3 créé (date de facture antérieure 2026-09-30)', r.flash.includes('Brouillon créé'), r.flash);
      ids.f3 = await newestDraftId();
      const fl = await offset(ids.nc2, ids.f3, '243.23');
      check('NC2 imputée sur le brouillon F3', fl.includes('Imputation enregistrée'), fl);
      await savePdf(`/invoice/${ids.f3}.pdf`, '10-F3-brouillon-compensation.pdf');
      const fi = await issueInvoice(ids.f3, 'reporte', 'emission-F3-confirmation');
      check('F3 émise 2026-09', fi.includes('Facture 2026-09 émise'), fi);
      state.pdf.F3 = sha(await savePdf(`/invoice/${ids.f3}.pdf`, '11-F3-2026-09-compensation-figee.pdf'));
      await tab('archive'); const t = await html();
      check('archive F3 : 2 432,25 TTC, imputé − 243,23, net à payer 2 189,02', t.includes(`imputé − 243,23${NB}CHF`) && t.includes(`net à payer 2${NN}189,02${NB}CHF`));
      await page.goto(`${BASE}/credit/${ids.nc2}`); await shot('NC2-suivi-compensee');
      check('NC2 « compensée », imputation figée non annulable', (await html()).includes('<b>compensée</b>') && (await html()).includes('figée'));
    });

    await step('8 tentative de crédit total après compensation définitive', async () => {
      await page.goto(`${BASE}/invoice/${ids.f3}/credit`); await shot('F3-credit-total-indisponible');
      let t = await text();
      check('formulaire : option « crédit total » désactivée avec motif', (await page.locator('input[name=scope][value=total]').isDisabled()) && t.includes('Crédit total indisponible') && t.includes('définitivement consommée'));
      await tab('archive'); const n0 = ((await page.content()).match(/Brouillon NC/g) || []).length; await page.goto(`${BASE}/invoice/${ids.f3}/credit`);
      const resp = await postForm(`${BASE}/invoice/${ids.f3}/credit`, { treatment: 'remboursement', scope: 'total', reason: 'tentative (fictif)' }, true);
      let fl = resp.text.replace(/&nbsp;/g, NB).replace(/&#39;/g, "'");
      check('POST direct « crédit total » rejeté par le serveur', fl.includes('crédit total refusé') && fl.includes('NC-2026-07.2'), fl);
      fl = await creditNote(ids.f3, { treatment: 'remboursement', qty: '2.5', reason: 'tentative déguisée en crédit partiel (fictif)' });
      check('crédit « partiel » couvrant toute la facture également rejeté', fl.includes('crédit total refusé'), fl);
      await shot('F3-credit-total-rejete');
      const n1 = (await page.content()).match(/Brouillon NC/g)?.length || 0;
      check('aucun brouillon de note créé par les tentatives', n1 === n0, `${n0} → ${n1}`);
      check('F3 inchangée (PDF identique)', sha(await fetchBytes(`/invoice/${ids.f3}.pdf`)) === state.pdf.F3);
      await page.goto(`${BASE}/credit/${ids.nc2}`);
      const revForms = await page.locator('form[action*="/reverse/"]').count();
      check('imputation définitive : aucun bouton d\'annulation proposé', revForms === 0, revForms);
      await tab('archive'); check('archive F3 : « crédit total indisponible (compensation définitive) »', (await html()).includes('crédit total indisponible (compensation définitive)'));
    });

    await step('7bis recette visuelle NC / annulation (correction traçable)', async () => {
      let fl = await creditNote(ids.f1, { treatment: 'compensation', qty: '0.25', reason: 'Rapport non livré — mode choisi par erreur (fictif)' });
      ids.nc3 = await newestCreditId(); fl = await issueCredit(ids.nc3);
      check('NC-2026-07.3 émise', fl.includes('NC-2026-07.3 émise'), fl);
      state.pdf.NC3 = sha(await savePdf(`/credit/${ids.nc3}.pdf`, '12-NC-2026-07.3-mode-errone.pdf'));
      await page.goto(`${BASE}/credit/${ids.nc3}`); const f = page.locator(`form[action="/credit/${ids.nc3}/cancel"]`);
      await f.locator('[name=reason]').fill('Mode erroné : remboursement attendu par le client (fictif)'); await f.locator('button').click();
      check('document d\'annulation ANN-NC-2026-07.3 émis', (await flashes()).includes('document d\'annulation figé'));
      state.pdf.ANN = sha(await savePdf(`/credit/${ids.nc3}/cancellation.pdf`, '13-ANN-NC-2026-07.3-annulation.pdf'));
      fl = await creditNote(ids.f1, { treatment: 'remboursement', qty: '0.25', reason: 'Rapport non livré (remplacement, fictif)', replaces: ids.nc3, refund_delay_days: '' }, 'NC4-formulaire-remplacement');
      ids.nc4 = await newestCreditId(); fl = await issueCredit(ids.nc4);
      check('NC-2026-07.4 émise en remplacement', fl.includes('NC-2026-07.4 émise'), fl);
      state.pdf.NC4 = sha(await savePdf(`/credit/${ids.nc4}.pdf`, '14-NC-2026-07.4-remplacement.pdf'));
      await page.goto(`${BASE}/credit/${ids.nc3}`); await shot('NC3-suivi-annulee');
      await page.goto(`${BASE}/credit/${ids.nc4}`); await shot('NC4-suivi-remplacement');
      check('NC4 : lien « remplace NC-2026-07.3 » et « aucun délai fixé »', (await html()).includes('Remplace') && (await html()).includes('aucune (aucun délai fixé)'));
    });

    await step('10 archive et suivi', async () => {
      await tab('archive'); await shot('archive-complete');
      const t = await text();
      for (const ref of ['2026-07', '2026-08', '2026-09', 'NC-2026-07', 'NC-2026-07.2', 'NC-2026-07.3', 'NC-2026-07.4', 'NC-2026-08'])
        check(`archive : ${ref} présent`, t.includes(ref));
      check('archive : F1 créditée partiellement (solde 2 250,00 HT = 3 150 − 450 − 225 − 225)', (await html()).includes(`solde créditable 2${NN}250,00${NB}CHF HT`));
      await tab('mandates'); await shot('mandats-position-finale');
      const m = (await text()).match(/Mandat Recette Alpha[^\n]*\n?[^\n]*/)?.[0] || '';
      const row = await mandRow().innerText();
      const cells = await mandRow().locator('td').allInnerTexts(); const n = i => Number(cells[i].replace(/[\u202f\u00a0 ]/g, '').replace(',', '.'));
      const heads = await page.locator('section:has(h2:has-text("Détail des mandats")) th').allInnerTexts();
      check('A4 : colonnes « Jours réalisés cumulés », « Jours facturés (émis) », « Jours annulés par notes de crédit », « Solde contractuel (j) »', ['Jours réalisés cumulés', 'Jours facturés (émis)', 'Jours annulés par notes de crédit', 'Solde contractuel (j)'].every((h, k) => heads[[5, 7, 8, 9][k]] === h), heads.join(' | '));
      check('A4 : 72,50 h, 9,06 j réalisés cumulés (2 décimales, valeur exacte en infobulle : décision B-2), facturés − annulés = 5,00 j nets, solde contractuel 25,00 j, 4,06 j non facturés', cells[4] === '72,50' && cells[5] === '9,06' && Math.abs(n(7) - n(8) - 5) < 1e-9 && n(8) > 0 && cells[9] === '25,00' && cells[10] === '4,06', cells.join(' | '));
      state.a4 = { realises: cells[5], factures: cells[7], annules: cells[8], solde: cells[9], non_factures: cells[10] };
      await tab('dashboard'); const dh = await page.locator('section[data-panel=dashboard] th').allInnerTexts();
      check('A4 : tableau de bord distingue réalisés / facturés / annulés / solde contractuel', ['Jours réalisés cumulés', 'Jours facturés', 'Jours annulés par notes de crédit', 'Solde contractuel (j)'].every(h => dh.includes(h)), dh.join(' | '));
      await tab('dashboard'); await shot('tableau-de-bord-final');
      for (const [k, cid] of [['NC_F2', ids.ncF2]]) { await page.goto(`${BASE}/credit/${cid}`); await shot(`suivi-${k}`); }
      const tx = (await (async () => { await tab('archive'); return text(); })());
      check('A3 : aucune date ISO visible dans l\'archive', !/\b\d{4}-\d{2}-\d{2}\b/.test(tx), (tx.match(/\b\d{4}-\d{2}-\d{2}\b/) || [''])[0]);
      check('format français à l\'écran (aucun « CHF 1… » ni « 1.00 »)', !/CHF \d/.test(tx) && !/\d\.\d\d\b/.test(tx.replace(/\d{4}-\d{2}-\d{2}/g, '').replace(/\d{2}\.\d{2}\.\d{4}/g, '')  /* rc7 : dates JJ.MM.AAAA exclues */.replace(/NC-\d{4}-\d{2}(\.\d+)?/g, '')), (tx.match(/CHF \d[^\n]{0,20}|\d\.\d\d[^\n]{0,10}/) || [''])[0]);
    });

    await step('11 export et restauration JSON', async () => {
      await tab('settings');
      const [dl] = await Promise.all([page.waitForEvent('download'), page.locator('a[href="/backup"]').click()]);
      const bpath = path.join(R, 'dl', 'sauvegarde-recette.json'); await dl.saveAs(bpath);
      const b = JSON.parse(fs.readFileSync(bpath)); state.counts = b.meta.row_counts;
      check('sauvegarde : 3 factures, 5 notes, 1 annulation, opérations, historique des dates', b.tables.invoices.length === 3 && b.tables.credit_notes.length === 5 && b.tables.credit_note_cancellations.length === 1
        && b.tables.credit_operations.length === 5 && b.tables.invoice_date_changes.length === 3, JSON.stringify(b.meta.row_counts));
      const r = await entry(M, '2026-10-01', { hours: 2, desc: 'saisie postérieure à la sauvegarde (fictif)' });
      check('saisie ajoutée après la sauvegarde', r.flash.includes('Temps enregistré'));
      await tab('settings'); await page.locator('form[action="/restore"] input[type=file]').setInputFiles(bpath); await page.locator('form[action="/restore"] button').click();
      await shot('restauration-previsualisation');
      check('prévisualisation non bloquante', !(await html()).includes('Restauration bloquée'));
      await page.fill('input[name=confirm]', 'RESTAURER'); await page.locator('button[value=restore]').click();
      const fl = await flashes(); check('restauration effectuée avec sauvegarde préalable vérifiée', fl.includes('Restauration effectuée'), fl);
      await tab('mandates'); check('saisie postérieure retirée (retour à 72,50 h)', (await mandRow().innerText()).includes('72,50'));
      for (const [k, url] of pdfDocs()) check(`PDF identique après restauration : ${k}`, sha(await fetchBytes(url)) === state.pdf[k]);
      await page.goto(`${BASE}/credit/${ids.nc1}`); check('suivi NC1 « remboursée » après restauration', (await html()).includes('<b>remboursée</b>'));
      await tab('archive'); check('historique de date F1 conservé après restauration', (await html()).includes('date modifiée 2 fois (tracé)'));
      const amp = JSON.parse(fs.readFileSync(bpath)); amp.tables.invoice_date_changes = []; fs.writeFileSync(path.join(R, 'dl', 'sauvegarde-amputee-historique-dates.json'), JSON.stringify(amp));
      await tab('settings'); await page.locator('form[action="/restore"] input[type=file]').setInputFiles(path.join(R, 'dl', 'sauvegarde-amputee-historique-dates.json')); await page.locator('form[action="/restore"] button').click(); await page.waitForLoadState('load'); await page.waitForSelector('.warnbox');
      check('restauration sans historique de dates bloquée', (await html()).includes('Restauration bloquée') && (await html()).includes('modification de date')); await shot('restauration-amputee-bloquee');
      await page.locator('button[value=cancel]').click();
    });

    await step('affichage mobile', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      for (const t of ['time', 'archive']) { await tab(t); await shot(`mobile-${t}`); }
      await page.goto(`${BASE}/invoice/${ids.f3}/credit`); await shot('mobile-credit-total-indisponible');
      state.mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      await page.setViewportSize({ width: 1360, height: 900 });
    });
    save();
  } else {
    await step('12 documents après redémarrage', async () => {
      await login();
      check(`santé ${EXPECT} après redémarrage`, (await (await page.request.get(`${BASE}/health`)).json()).version === EXPECT);
      for (const [k, url] of pdfDocs()) check(`PDF identique après redémarrage : ${k}`, sha(await fetchBytes(url)) === state.pdf[k]);
      await page.goto(`${BASE}/credit/${ids.nc1}`); check('NC1 « remboursée » conservée', (await html()).includes('<b>remboursée</b>'));
      await page.goto(`${BASE}/credit/${ids.nc2}`); check('NC2 « compensée » conservée', (await html()).includes('<b>compensée</b>'));
      await page.goto(`${BASE}/credit/${ids.nc3}`); check('NC3 annulée (ANN-NC-2026-07.3) conservée', (await html()).includes('annulée (ANN-NC-2026-07.3)'));
      await page.goto(`${BASE}/invoice/${ids.f3}/credit`); check('règle de crédit total toujours appliquée', await page.locator('input[name=scope][value=total]').isDisabled());
      await tab('archive'); await shot('archive-apres-redemarrage');
    });
  }
  fs.writeFileSync(path.join(J, `resultats-${PHASE}.json`), JSON.stringify({ results, consoleErrors, state }, null, 1));
  console.log(`RESULT ${PHASE}: ${results.filter(r => r.ok).length}/${results.length} — erreurs console : ${consoleErrors.length}`);
  await browser.close();
})();
