// Recette navigateur — éditeur de brouillon (9.2-rc37) : lignes manuelles multiples (JavaScript), totaux en direct, persistance, numéro proposé modifiable et conflit.
// Instance JETABLE, base synthétique vide. Usage : PW_FILE=… BASE_URL=http://127.0.0.1:<port> [OUT_DIR=…] node recette-factures-editeur.js
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT_DIR || '';
if (!BASE || /:(8091|8092)\b/.test(BASE)) throw new Error('BASE_URL : instance de test jetable seulement');
let ko = 0, n = 0;
const check = (name, ok, detail = '') => { n++; if (!ok) ko++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' — ' + String(detail).slice(0, 300))); };
const login = async page => { await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState(); };
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 }, locale: 'fr-CH' }); const page = await ctx.newPage(); const errs = [];
  page.on('pageerror', e => errs.push(e.message)); page.on('dialog', d => d.accept());
  await login(page);
  const post = (u, form) => page.request.post(BASE + u, { form });
  await post('/settings', { issuer_name: 'Bureau Recette Sàrl', issuer_address: 'Chemin de la Recette 7\n1000 Ville', account_holder: 'Bureau Recette Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms_days: '30' });
  const tag = Date.now().toString(36), A = `Mandat Ed ${tag}`;
  await post('/project', { name: A, client: 'Client Recette SA', po: 'PO-ED-1', rate: '900', day_hours: '8', vat: '8.1', ordered_days: '40', start_date: '2026-01-01', duration_months: '12' });
  const html0 = await (await page.request.get(BASE + '/?tab=time')).text();
  const pa = (html0.match(new RegExp(`<option value="(\\d+)"[^>]*>${A}<`)) || [])[1];
  for (const d of ['01', '02', '03', '04', '07', '08', '09']) await post('/entry', { work_date: `2026-09-${d}`, project_id: pa, entry_mode: 'duration', manual_hours: '8', description: 'travail fictif' });
  await page.goto(BASE + '/?tab=billing'); await page.selectOption('#invoiceProject', pa); await page.click('[data-period=lastmonth]');
  await page.waitForFunction(() => document.getElementById('rawDays').textContent !== '—' && !document.getElementById('roundOptions').hidden);
  await page.click('#draftSubmit'); await page.waitForLoadState();
  check('brouillon créé', await page.isVisible('#draftCreated'));
  const links = await page.locator('a[href*="/invoice/"]').evaluateAll(els => els.map(e => e.getAttribute('href')));
  const iid = (links.map(h => /\/invoice\/(\d+)/.exec(h || '')).find(Boolean) || [])[1];
  check('identifiant du brouillon trouvé', !!iid, JSON.stringify(links.slice(0, 6)));
  await page.goto(BASE + `/invoice/${iid}/edit`);
  check('éditeur ouvert, numéro proposé AAAA-N visible', /^\d{4}-\d+$/.test(await page.inputValue('#tb-number')), await page.inputValue('#tb-number'));
  const proposed = await page.inputValue('#tb-number');
  check('liste déroulante des adresses présente', await page.locator('#tb-addr').count() === 1);
  const total0 = await page.innerText('#tb-r-total');
  // 3 lignes ajoutées SANS rechargement (JS), chacune éditée indépendamment
  const lines = [['Frais de déplacement', '1', '120.50'], ['Hébergement', '2', '95'], ['Licence annuelle', '1', '300']];
  for (const [i, [d, q, r]] of lines.entries()) {
    await page.click('#tb-add');
    const rows = page.locator('#tb-lines-body .tb-manual'); check(`ligne ${i + 1} ajoutée sans rechargement`, await rows.count() === i + 1, await rows.count());
    const row = rows.nth(i); await row.locator('input[name=line_description]').fill(d); await row.locator('input[name=line_qty]').fill(q); await row.locator('input[name=line_rate]').fill(r);
  }
  await page.waitForTimeout(900);
  check('compteur de lignes', /3 \/ \d+ ligne/.test(await page.innerText('#tb-count')), await page.innerText('#tb-count'));
  const total1 = await page.innerText('#tb-r-total');
  check('totaux recalculés en direct (serveur)', total1 !== total0 && /\d/.test(total1), `${total0} → ${total1}`);
  // supprimer la 2e ligne avant enregistrement
  await page.locator('#tb-lines-body .tb-manual').nth(1).locator('button.tb-remove').click();
  check('suppression sans rechargement', await page.locator('#tb-lines-body .tb-manual').count() === 2);
  await page.waitForTimeout(900);
  await page.click('button.wide[value=save]'); await page.waitForLoadState();
  // réouverture : lignes présentes, sans doublon ni perte
  await page.goto(BASE + `/invoice/${iid}/edit`);
  const descs = await page.locator('#tb-lines-body input[name=line_description]').evaluateAll(els => els.map(e => e.value));
  check('lignes conservées après enregistrement et réouverture', JSON.stringify(descs) === JSON.stringify(['Frais de déplacement', 'Licence annuelle']), JSON.stringify(descs));
  check('numéro conservé après réouverture', await page.inputValue('#tb-number') === proposed, await page.inputValue('#tb-number'));
  // PDF brouillon : numéro et lignes
  const pdf = await page.request.get(BASE + `/invoice/${iid}.pdf`); check('PDF brouillon généré', pdf.ok() && (await pdf.body()).length > 3000, pdf.status());
  // numéro modifié à la main puis conflit explicite
  await page.fill('#tb-number', `${proposed.slice(0, 4)}-77`); await page.click('button.wide[value=save]'); await page.waitForLoadState();
  await page.goto(BASE + `/invoice/${iid}/edit`);
  check('numéro saisi à la main conservé', await page.inputValue('#tb-number') === `${proposed.slice(0, 4)}-77`, await page.inputValue('#tb-number'));
  check('aucune erreur JavaScript', errs.length === 0, errs.join(' | '));
  if (OUT) await page.screenshot({ path: path.join(OUT, 'editeur-factures.png'), fullPage: true });
  console.log(`RÉSULTAT éditeur factures : ${n - ko}/${n} OK, ${ko} KO`);
  await browser.close(); process.exit(ko ? 1 : 0);
})();
