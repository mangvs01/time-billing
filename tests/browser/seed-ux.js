// Données fictives pour l'audit UX (conteneur jetable). Usage: node seed.js
const { chromium } = require('/root/node_modules/playwright'); const fs = require('fs'), path = require('path');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8190', D = __dirname, PW = fs.readFileSync(path.join(D, 'pw.txt'), 'utf8').trim();
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ locale: 'fr-CH' }); const p = await ctx.newPage();
  await p.goto(BASE + '/login'); await p.fill('input[name=username]', 'admin'); await p.fill('input[name=password]', PW); await p.click('button'); await p.waitForLoadState();
  const post = (u, form) => p.request.post(BASE + u, { form });
  await post('/settings', { issuer_name: 'Bureau Fictif Recette Sàrl', issuer_address: 'Chemin de la Recette 7\n1000 Ville-Fictive', account_holder: 'Bureau Fictif Recette Sàrl', iban: 'CH00 0000 0000 0000 0000 0', payment_terms: 'Paiement à 30 jours sur le compte:', issuer_vat_number: 'CHE-000.000.000 TVA (fictif)' });
  for (const [n, rate] of [['Mandat Alpha — Mission AMO', '900'], ['Mandat Beta — Étude de faisabilité', '650']])
    await post('/project', { name: n, client: 'Société Fictive SA', po: 'PO-FICTIF-' + rate, rate, day_hours: '8', vat: '8.1', ordered_days: '20', start_date: '2026-01-01', duration_months: '12', billing_address: 'Société Fictive SA\nRue de l\'Exemple 12\n9999 Nulle-Part', client_legal_name: 'Société Fictive SA', client_legal_id: 'che000001234' });
  const descs = ['Réunion de coordination', 'Visite de chantier', 'Rédaction du rapport', 'Atelier client', 'Analyse documentaire', 'Suivi de projet'];
  for (let i = 0; i < 70; i++) {
    const d = new Date(Date.UTC(2026, 6, 1 + (i % 28), 12)); d.setUTCMonth(6 + Math.floor(i / 28));
    const iso = d.toISOString().slice(0, 10);
    const clock = i % 3 === 0;
    await post('/entry', Object.assign({ work_date: iso, project_id: String(1 + (i % 2)), entry_mode: clock ? 'clock' : 'duration', description: descs[i % 6] + ' (fictif)' }, clock ? { start_time: '09:00', end_time: i % 2 ? '12:20' : '11:45' } : { manual_hours: String(1 + (i % 7) * 0.5) }));
  }
  await b.close(); console.log('seed ok');
})();
