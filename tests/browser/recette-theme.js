// Recette navigateur — rc35 (BILLING-THÈME, 24.10.2026) : thème sombre par défaut, bascule clair / sombre, lisibilité de tous les écrans (lots 1 et 2).
// Instance JETABLE, base synthétique vide, données fictives créées ici. Jamais la production (8091), jamais le staging (8092).
// Usage : PW_FILE=… BASE_URL=http://127.0.0.1:<port de test> [OUT_DIR=…] [THEMES=dark,light] [CAPTURE_ONLY=1] node recette-theme.js
//   OUT_DIR : captures <OUT_DIR>/<thème>/<écran>-<largeur>.png (premier écran ; pleine page pour les écrans du lot 2) + contrastes.json
//   CAPTURE_ONLY=1 : captures seulement (version sans bascule, p. ex. rc34 pour les captures « avant » : le thème demandé n'y existe pas, la page reste claire)
const { chromium } = require('/root/node_modules/playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL, PW = fs.readFileSync(process.env.PW_FILE, 'utf8').trim(), OUT = process.env.OUT_DIR || '';
const THEMES = (process.env.THEMES || 'dark,light').split(','), CAPTURE_ONLY = process.env.CAPTURE_ONLY === '1';
if (!BASE || /:(8091|8092)\b/.test(BASE)) throw new Error('BASE_URL : instance de test jetable seulement (ni 8091 ni 8092)');
const results = []; let section = '';
const check = (name, ok, detail = '') => { results.push({ section, name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + `[${section}] ${name}` + (ok ? '' : ' — ' + String(detail).slice(0, 400))); };
const login = async page => { await page.goto(BASE + '/login'); await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState(); };
const noOverflow = page => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
const theme = page => page.evaluate(() => document.documentElement.getAttribute('data-theme'));
const stored = page => page.evaluate(() => { try { return localStorage.getItem('tb-theme') } catch (e) { return 'ERR' } });
const bg = page => page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor);
const DARK_BG = 'rgb(17, 19, 21)';
const VPS = [['1280', { width: 1280, height: 900 }], ['390', { width: 390, height: 844 }]];

// Contraste WCAG de chaque texte visible : couleur du texte contre le fond effectif (fonds semi-transparents composés jusqu'à la page ; dégradé = moyenne de ses couleurs).
// Exemptés comme le prévoit WCAG 1.4.3 : contrôles désactivés, texte masqué (lecteurs d'écran). Seuil 4,5:1, 3:1 pour le grand texte (≥ 24 px, ou ≥ 18,66 px gras).
function audit() {
  const parse = s => { const m = String(s).match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, under) => { const a = top[3]; return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1]; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const layer = el => {   // fond propre d'un élément (couleur, ou moyenne des couleurs d'un dégradé)
    const cs = getComputedStyle(el); let c = parse(cs.backgroundColor) || [0, 0, 0, 0];
    if (cs.backgroundImage && cs.backgroundImage !== 'none') {
      const stops = (cs.backgroundImage.match(/rgba?\([^)]+\)/g) || []).map(parse).filter(s => s[3] > 0.05);
      if (stops.length) { const avg = [0, 1, 2, 3].map(i => stops.reduce((t, s) => t + s[i], 0) / stops.length); if (avg[3] > 0.5) c = c[3] ? over(avg, c) : avg; }
    }
    return c;
  };
  const backdrop = el => {
    const chain = []; for (let e = el; e && e.nodeType === 1; e = e.parentElement) chain.push(layer(e));
    let c = parse(getComputedStyle(document.documentElement).backgroundColor) || [255, 255, 255, 1]; if (c[3] < 1) c = over(c, [255, 255, 255, 1]);
    for (let i = chain.length - 1; i >= 0; i--) if (chain[i][3] > 0) c = over(chain[i], c);
    return c;
  };
  const out = [], seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    if (el.closest('script,style,noscript,.vh,[hidden],option,optgroup')) continue;
    const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.closest('button:disabled,input:disabled,select:disabled,textarea:disabled,fieldset:disabled')) continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= Number(getComputedStyle(e).opacity); if (op < 0.99) continue;
    const svg = el instanceof SVGElement;
    const fg = parse(svg ? cs.fill : cs.color); if (!fg || fg[3] === 0) continue;
    const back = backdrop(el), col = fg[3] < 1 ? over(fg, back) : fg;
    const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700, large = size >= 24 || (size >= 18.66 && bold);
    const k = ratio(col, back), need = large ? 3 : 4.5;
    if (k < need) out.push({ text: n.textContent.trim().slice(0, 60), tag: el.tagName.toLowerCase(), cls: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className).slice(0, 60),
      fg: cs.color, bg: `rgb(${back.slice(0, 3).map(Math.round).join(', ')})`, ratio: Math.round(k * 100) / 100, need });
  }
  return out;
}

(async () => {
  const browser = await chromium.launch(); const errs = [], report = {};
  const ctxFor = async (vp, t, mobile, extra) => {
    const ctx = await browser.newContext({ viewport: vp, locale: 'fr-CH', hasTouch: mobile });
    if (t) await ctx.addInitScript(v => { try { if (!localStorage.getItem('tb-theme-recette')) { localStorage.setItem('tb-theme', v); localStorage.setItem('tb-theme-recette', '1'); } } catch (e) {} }, t);
    if (extra) await ctx.addInitScript(extra);
    return ctx;
  };
  const watch = (page, label) => { page.on('pageerror', e => errs.push(`${label} ${e.message}`)); page.on('console', m => { if (m.type() === 'error') errs.push(`${label} ${m.text()}`); }); page.on('dialog', d => d.accept()); };

  // ---------- données fictives (même jeu pour rc34 et rc35) : émetteur, mandat A avec PO (TVA 8,1 %), mandat B sans PO, facture émise, écart, note de crédit, brouillon ----------
  const setup = await browser.newContext({ viewport: { width: 1280, height: 900 } }); const sp = await setup.newPage(); watch(sp, 'setup'); await login(sp);
  const post = (u, form) => sp.request.post(BASE + u, { form });
  await post('/settings', { issuer_name: 'Bureau Recette Sàrl', issuer_address: 'Chemin de la Recette 7\n1000 Ville', account_holder: 'Bureau Recette Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours sur le compte:', issuer_vat_number: 'CHE-000.000.000 TVA' });
  const A = 'Mandat Thème A', B = 'Mandat Thème B';
  for (const [name, ordered, vat] of [[A, '40', '8.1'], [B, '', '0']]) await post('/project', { name, client: 'Client Recette SA', po: ordered ? 'PO-R-1' : '', rate: '900', day_hours: '8', vat, ordered_days: ordered, start_date: '2026-01-01', duration_months: '12', billing_address: 'Client Recette SA\nRue 1\n9999 Nulle-Part', client_legal_name: 'Client Recette SA', client_legal_id: 'che000001111' });
  const html0 = await (await sp.request.get(BASE + '/?tab=time')).text();
  const pid = n => (html0.match(new RegExp(`<option value="(\\d+)"[^>]*>${n}<`)) || [])[1]; const pa = pid(A), pb = pid(B);
  for (const [d, h] of [['01', 7.75], ['02', 8], ['03', 8], ['04', 8], ['07', 8], ['08', 8], ['09', 8]]) await post('/entry', { work_date: `2026-09-${d}`, project_id: pa, entry_mode: 'duration', manual_hours: String(h), description: 'travail fictif' });
  for (const d of ['03', '04']) await post('/entry', { work_date: `2026-08-${d}`, project_id: pa, entry_mode: 'duration', manual_hours: '8', description: 'travail antérieur fictif' });
  for (const d of ['01', '02', '05']) await post('/entry', { work_date: `2026-10-${d}`, project_id: pa, entry_mode: 'clock', start_time: '08:30', end_time: '12:15', description: 'atelier fictif' });
  for (const d of ['03', '04']) await post('/entry', { work_date: `2026-08-${d}`, project_id: pb, entry_mode: 'duration', manual_hours: '6', description: 'assistance fictive' });
  await post('/invoice', { project_id: pa, period_from: '2026-09-01', period_to: '2026-09-30', qty: '7', invoice_date: '2026-09-30' });
  const archive = async () => (await (await sp.request.get(BASE + '/?tab=archive')).text());
  const issueId = ((await archive()).match(/href="\/issue\/(\d+)"/) || [])[1];
  await post(`/issue/${issueId}`, { reliquat_treatment: 'reporte', derogation_12: 'Arrondi convenu avec le client pour la période (recette fictive)', confirm_backdate: '2026-09-30' });
  const iid = issueId;
  await post('/invoice', { project_id: pa, period_from: '2026-10-01', period_to: '2026-10-31', qty: '1', invoice_date: '2026-10-31' });
  const did = ((await archive()).match(/href="\/issue\/(\d+)"/) || [])[1];
  // écart post-facturation : une saisie facturée corrigée (motif + confirmation, la facture émise ne change pas)
  const eid = ((await (await sp.request.get(BASE + `/entries?project=${pa}&date_from=2026-09-01&date_to=2026-09-30`)).text()).match(/\/entry\/(\d+)\/edit/) || [])[1];
  await sp.goto(BASE + `/entry/${eid}/edit`); await sp.check('input[name=entry_mode][value=duration]').catch(() => {}); await sp.fill('input[name=manual_hours]', '8.5');
  await sp.fill('[name=reason]', 'Correction fictive après émission (recette)'); await sp.check('input[name=confirm_billed]').catch(() => {});
  await sp.click('form button:has-text("Enregistrer")'); await sp.waitForLoadState();
  // note de crédit (brouillon) depuis la facture émise
  await sp.goto(BASE + `/invoice/${iid}/credit`); await sp.fill('[name=reason]', 'Geste commercial fictif (recette)').catch(() => {}); await sp.check('input[name=treatment] >> nth=0').catch(() => {}); await sp.fill('input[name=qty]', '0.5').catch(() => {});
  await sp.click('button:has-text("Créer le brouillon de note de crédit")'); await sp.waitForLoadState();
  const cid = ((await archive()).match(/\/credit\/(\d+)/) || [])[1];
  await setup.close();
  section = 'jeu de données';
  check('facture émise, brouillon, saisie corrigée et note de crédit créés', iid && did && did !== iid && eid && cid, JSON.stringify({ iid, did, eid, cid }));

  const SCREENS = [['login', '/login', 'anon'], ['dashboard', '/?tab=dashboard'], ['time', '/?tab=time'], ['mandates', '/?tab=mandates'], ['billing', '/?tab=billing'], ['billing-calc', '/?tab=billing', 'calc'],
    ['archive', '/?tab=archive'], ['migration', '/?tab=migration'], ['settings', '/?tab=settings'], ['entries', '/entries'], ['entry-edit', `/entry/${eid}/edit`], ['project-edit', `/project/${pb}/edit`],
    ['issue', `/issue/${did}`], ['ecart', `/invoice/${iid}/ecart`], ['credit-new', `/invoice/${iid}/credit`], ['credit', `/credit/${cid}`], ['menu-plus', '/?tab=dashboard', 'menu']];
  const FULL = new Set(['dashboard', 'billing-calc', 'archive', 'issue', 'ecart', 'entries', 'time']);

  // ---------- 1. lisibilité de chaque écran, par thème et par largeur ; captures ----------
  for (const t of THEMES) for (const [w, vp] of VPS) {
    const mobile = w === '390';
    const ctx = await ctxFor(vp, t, mobile); const page = await ctx.newPage(); watch(page, `${t} ${w}`);
    await page.goto(BASE + '/login');
    for (const [name, url, mode] of SCREENS) {
      if (mode === 'menu' && !mobile) continue;
      if (name === 'dashboard' && page.url().includes('/login')) await login(page);
      section = `${CAPTURE_ONLY ? 'captures' : 'lisibilité'} ${t} ${w}`;
      await page.goto(BASE + url); await page.waitForLoadState('networkidle').catch(() => {});
      if (mode === 'calc') { await page.selectOption('#invoiceProject', pa); await page.click('[data-period=lastmonth]').catch(() => {}); await page.waitForFunction(() => !document.getElementById('roundOptions').hidden, null, { timeout: 5000 }).catch(() => {}); await page.waitForTimeout(400); }
      if (mode === 'menu') { await page.click('#navMore'); await page.waitForTimeout(150); }
      await page.waitForTimeout(250);   // anneaux du tableau de bord (animation < 1,1 s) : la mesure porte sur l'état stable
      if (name === 'dashboard') await page.waitForTimeout(900);
      if (!CAPTURE_ONLY) {
        check(`${name} : thème ${t} appliqué`, await theme(page) === t && (t !== 'dark' || await bg(page) === DARK_BG), `${await theme(page)} ${await bg(page)}`);
        const bad = await page.evaluate(audit); report[`${t}-${w}-${name}`] = bad;
        check(`${name} : contrastes AA (${bad.length} texte(s) sous le seuil)`, bad.length === 0, JSON.stringify(bad.slice(0, 4)));
        check(`${name} : pas de débordement horizontal`, await noOverflow(page));
      }
      if (OUT) { const dir = path.join(OUT, t); fs.mkdirSync(dir, { recursive: true }); await page.screenshot({ path: path.join(dir, `${name}-${w}.png`), fullPage: FULL.has(name) }); }
    }
    await ctx.close();
  }
  if (OUT && !CAPTURE_ONLY) fs.writeFileSync(path.join(OUT, 'contrastes.json'), JSON.stringify(report, null, 1));

  if (!CAPTURE_ONLY) {
    // ---------- 2. défaut sombre, bascule, mémorisation, aucun premier rendu clair ----------
    for (const [w, vp] of VPS) {
      const mobile = w === '390';
      section = `bascule ${w}`;
      const ctx = await ctxFor(vp, '', mobile); const page = await ctx.newPage(); watch(page, `bascule ${w}`);
      await page.goto(BASE + '/login');
      check('connexion : sombre par défaut (aucun choix mémorisé)', await theme(page) === 'dark' && await bg(page) === DARK_BG && await stored(page) === null, `${await theme(page)} ${await bg(page)} ${await stored(page)}`);
      const lt = page.locator('button.login-theme');
      const box = await lt.boundingBox();
      check('connexion : bouton de thème visible dans le premier écran', await lt.isVisible() && box && box.y + box.height <= vp.height && box.x + box.width <= vp.width, JSON.stringify(box));
      if (mobile) check('connexion : cible tactile ≥ 44 px', box && box.width >= 44 && box.height >= 44, JSON.stringify(box));
      check('connexion : aria-pressed="true" en sombre, nom accessible', await lt.getAttribute('aria-pressed') === 'true' && (await lt.textContent()).trim() === 'Thème sombre');
      await lt.click();
      check('connexion : un clic passe en clair et le mémorise', await theme(page) === 'light' && await stored(page) === 'light' && await lt.getAttribute('aria-pressed') === 'false' && await lt.getAttribute('title') === 'Passer au thème sombre');
      await page.reload();
      check('connexion : le choix clair survit au rechargement', await theme(page) === 'light' && await bg(page) !== DARK_BG);
      await page.fill('input[name=username]', 'admin'); await page.fill('input[name=password]', PW); await page.click('button'); await page.waitForLoadState();
      check('après connexion : toujours clair (même navigateur)', !page.url().includes('/login') && await theme(page) === 'light');
      if (!mobile) {
        const hb = page.locator('.sidebar .brand button.themetoggle'); const hbox = await hb.boundingBox();
        check('ordinateur : bouton dans l\'en-tête de la barre latérale, visible en haut', await hb.isVisible() && hbox && hbox.y < 120, JSON.stringify(hbox));
        check('ordinateur : pas de menu « Plus »', !(await page.isVisible('#navMore')));
        await hb.click();
        check('ordinateur : retour au sombre, mémorisé', await theme(page) === 'dark' && await stored(page) === 'dark' && await hb.getAttribute('aria-pressed') === 'true');
        await hb.focus(); await page.keyboard.press('Enter');
        check('ordinateur : bascule au clavier (Entrée)', await theme(page) === 'light');
        await page.keyboard.press('Space');
        check('ordinateur : bascule au clavier (Espace)', await theme(page) === 'dark');
        // tablette : barre latérale réduite aux icônes, le bouton reste dans l'en-tête
        await page.setViewportSize({ width: 900, height: 900 });
        const tbox = await hb.boundingBox();
        check('tablette (900 px) : bouton visible dans la barre latérale réduite', await hb.isVisible() && tbox && tbox.x + tbox.width <= 84 + 16 && tbox.y < 160, JSON.stringify(tbox));
        check('tablette : pas de débordement horizontal', await noOverflow(page));
        await page.setViewportSize(vp);
        // pages de détail (_page.html) et onglets JS : même thème
        for (const u of [`/issue/${did}`, `/invoice/${iid}/ecart`, `/credit/${cid}`, '/entries', `/entry/${eid}/edit`, '/?tab=billing']) {
          await page.goto(BASE + u);
          check(`${u} : thème mémorisé appliqué (sombre)`, await theme(page) === 'dark' && await bg(page) === DARK_BG && await page.locator('[data-theme-toggle]:visible').count() === 1);
        }
        // deux onglets : la bascule dans l'un s'applique à l'autre (événement « storage »)
        const other = await ctx.newPage(); watch(other, 'onglet 2'); await other.goto(BASE + '/?tab=time');
        await page.goto(BASE + '/?tab=dashboard'); await hb.click();
        await other.waitForFunction(() => document.documentElement.getAttribute('data-theme') === 'light', null, { timeout: 3000 }).catch(() => {});
        check('deux onglets : l\'autre onglet suit le choix', await theme(other) === 'light' && await other.locator('.sidebar .brand button.themetoggle').getAttribute('aria-pressed') === 'false');
        await other.close(); await hb.click();
      } else {
        check('téléphone : bouton d\'en-tête masqué (il est dans « Plus »)', !(await page.isVisible('.sidebar .brand button.themetoggle')));
        await page.click('#navMore');
        const mb = page.locator('#navMoreMenu button.themetoggle-m'); const mbox = await mb.boundingBox();
        check('téléphone : « Thème sombre » dans le menu « Plus », cible ≥ 44 px', await mb.isVisible() && mbox && mbox.height >= 44, JSON.stringify(mbox));
        check('téléphone : interrupteur éteint en clair', await mb.getAttribute('aria-pressed') === 'false');
        await mb.click();
        check('téléphone : un clic passe en sombre, le menu reste ouvert', await theme(page) === 'dark' && await stored(page) === 'dark' && await page.isVisible('#navMoreMenu') && await mb.getAttribute('aria-pressed') === 'true');
        await page.keyboard.press('Escape');
        check('téléphone : Échap ferme le menu', !(await page.isVisible('#navMoreMenu')));
        await page.goto(BASE + `/issue/${did}`); await page.click('#navMore');
        check('téléphone : bouton aussi dans « Plus » des pages de détail', await page.locator('#navMoreMenu button.themetoggle-m').isVisible());
      }
      // aucun premier rendu clair : thème déjà posé quand le parseur crée <style> et <body>
      const probe = await ctxFor(vp, 'light', mobile, () => { window.__th = {}; new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) if ((n.nodeName === 'STYLE' || n.nodeName === 'BODY') && !window.__th[n.nodeName]) window.__th[n.nodeName] = document.documentElement.getAttribute('data-theme'); }).observe(document, { childList: true, subtree: true }); });
      const pp = await probe.newPage(); await pp.goto(BASE + '/login');
      const seenL = await pp.evaluate(() => window.__th);
      check('clair mémorisé : thème clair déjà posé avant <style> et <body> (aucun flash sombre)', seenL.STYLE === 'light' && seenL.BODY === 'light', JSON.stringify(seenL));
      await pp.evaluate(() => localStorage.setItem('tb-theme', 'dark')); await pp.reload();
      const seenD = await pp.evaluate(() => window.__th);
      check('sombre mémorisé : thème sombre posé avant <style> et <body> (aucun flash clair)', seenD.STYLE === 'dark' && seenD.BODY === 'dark', JSON.stringify(seenD));
      await probe.close();
      // stockage bloqué (navigation privée stricte) : sombre par défaut, aucune erreur, bascule valable pour la page
      const blocked = await ctxFor(vp, '', mobile, () => { const deny = () => { throw new DOMException('denied', 'SecurityError'); }; Object.defineProperty(window, 'localStorage', { get: deny, configurable: true }); });
      const bp = await blocked.newPage(); const berr = []; bp.on('pageerror', e => berr.push(e.message)); await bp.goto(BASE + '/login');
      await bp.click('button.login-theme');
      check('stockage bloqué : sombre par défaut, la bascule marche, aucune erreur JS', berr.length === 0 && await theme(bp) === 'light', berr.join(' ; '));
      await blocked.close();
      await ctx.close();
    }
    // ---------- 3. CSP : en-tête inchangé, scripts signés ----------
    section = 'CSP';
    const r = await (await browser.newContext()).request.get(BASE + '/login');
    const csp = r.headers()['content-security-policy'] || '';
    check('script-src sans unsafe-inline, avec nonce', /script-src 'self' 'nonce-[\w-]{16,}'/.test(csp) && !/script-src[^;]*unsafe-inline/.test(csp), csp);
    section = 'global'; check('aucune erreur console / JS (dont refus CSP)', errs.length === 0, errs.join(' ; '));
  }
  await browser.close();
  const ko = results.filter(x => !x.ok).length; console.log(`RÉSULTAT thème : ${results.length - ko}/${results.length} OK, ${ko} KO`); process.exit(ko ? 1 : 0);
})();
