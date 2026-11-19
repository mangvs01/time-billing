// Recette navigateur rc17 — saisie passant minuit (décision C5) : UNE saisie, durée calculée au-dessus de minuit. Conteneur jetable, données fictives.
// Usage : PW_FILE=… BASE_URL=… EXPECT_VERSION=… node recette-minuit.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT_DIR || __dirname;
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
(async () => {
  const browser = await chromium.launch(); const errs = [];
  for (const [label, vp] of [['bureau', { width: 1360, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH' }); const page = await ctx.newPage();
    page.on('pageerror', e => errs.push(e.message)); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    const flash = async () => (await page.locator('.msg').allInnerTexts()).join(' | ');
    await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState();
    const name = `Mandat Minuit ${label}`;
    await page.request.post(BASE + '/project', { form: { name, rate: '650', day_hours: '8', vat: '0', ordered_days: '10', client: 'Client Fictif', start_date: '2026-01-01', duration_months: '12' } });
    section = `minuit ${label}`;
    await page.goto(BASE + '/?tab=time');
    await page.selectOption('select[name=project_id]', { label: name }); await page.fill('input[name=work_date]', '2026-08-12');
    await page.fill('#startTime', '22:00'); await page.fill('#endTime', '02:00');
    const calc = await page.innerText('#clockFields');
    check('durée calculée avant envoi : 4 h 00 min, passe minuit', /4\s*h\s*00/.test(calc) && /minuit/.test(calc), calc);
    await page.fill('input[name=description]', `Nuit fictive ${label}`); await page.screenshot({ path: path.join(OUT, `minuit-${label}-form.png`) });
    const lbl = (await page.innerText('#entrySubmit')).trim();   // UX lot 1 (B-4) : le bouton dit ce qui sera enregistré
    check('bouton « Enregistrer 4 h (fin le lendemain) » et lien « Inverser début et fin »', lbl === 'Enregistrer 4 h (fin le lendemain)' && await page.isVisible('#swapTimes'), lbl);
    await page.click('#entrySubmit');
    const f = await flash();
    check('une saisie enregistrée : 4 h, avertissement « passant minuit »', f.includes('Temps enregistré : 4 h') && f.includes('passant minuit') && !f.includes('refusée'), f);
    await page.goto(BASE + `/entries?q=${encodeURIComponent('Nuit fictive ' + label)}`);
    const rows = await page.locator('tr[data-entry]').count(); const t = await page.locator('tr[data-entry]').first().innerText();
    check('la liste montre UNE ligne 22:00 – 02:00 (+1 j), 4 h, le 12.08.2026', rows === 1 && /22:00\s*–\s*02:00/.test(t) && t.includes('(+1 j)') && t.includes('12.08.2026'), t);
    check('aucune ligne le lendemain', (await (await page.request.get(BASE + `/entries?date_from=2026-08-13&date_to=2026-08-13&q=${encodeURIComponent('Nuit fictive ' + label)}`)).text()).includes('data-entry') === false);
    await page.locator('tr[data-entry]').first().locator('text=Modifier').click(); await page.waitForLoadState();
    check('formulaire de correction : durée affichée au-dessus de minuit', /4\s*h\s*00/.test(await page.innerText('#calcDuration')) && /minuit/.test(await page.innerText('#calcDuration')), await page.innerText('#calcDuration'));
    await page.fill('#end_time', '22:00'); check('fin = début : « fin identique au début »', /identique/.test(await page.innerText('#calcDuration')), await page.innerText('#calcDuration'));
    check('pas de débordement horizontal', !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    await ctx.close();
  }
  check('aucune erreur console / JS', errs.length === 0, errs.join(' ; '));
  await browser.close();
  const ko = results.filter(r => !r.ok).length; console.log(`RÉSULTAT minuit : ${results.length - ko}/${results.length} OK, ${ko} KO`); process.exit(ko ? 1 : 0);
})();
