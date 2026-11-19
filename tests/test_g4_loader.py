"""G4 / D1 (2026-10-06): the loading tool of the historical invoices (outils/charger_factures_historiques.py) and the schema checks of the registry.
Synthetic records only (the real workbook is never mounted in the test containers), on a COPY of the staging database (see test_import.py)."""
import app.app as m
from app import historical_billing, schema_checks
from outils import charger_factures_historiques as tool
from tests.test_g4 import G4


class Loader(G4):
    def recs(self, **over):
        r = dict(mandate='Mandat G4', source_file=tool.SOURCE_FILE, source_sheet='SUIVI 2026', source_cell='Q12', source_column='Facture 01.10', invoice_date='2026-10-01',
                 invoice_ref='2026-09', qty_days=8.0, amount_ht=5200.0, unit_rate=650.0, basis='amount', qty_derived=1, note='', raw=5200)
        r.update(over); return [r]

    def set_rate(self, rate):
        c = m.db()
        try: c.execute("UPDATE projects SET rate=? WHERE name='Mandat G4'", (rate,)); c.commit()
        finally: c.close()

    def run_insert(self, recs):
        c = m.db()
        try:
            ids = {x['name']: x['id'] for x in c.execute('SELECT id,name FROM projects')}
            out = tool.insert(c, recs, ids, tool.WORKBOOK_SHA256, historical_billing); c.commit(); return out
        finally: c.close()

    def test_the_tool_loads_proposed_rows_only_and_they_change_nothing(self):
        before = self.position()
        added, same = self.run_insert(self.recs())
        self.assertEqual((len(added), same), (1, []))
        self.assertEqual(self.sql('SELECT status,source_sha256,invoice_ref,qty_days,amount_ht FROM historical_invoices')[0][:], ('proposed', tool.WORKBOOK_SHA256, '2026-09', 8.0, 5200.0))
        self.assertEqual(self.position(), before)                                               # nothing counts before the user validates
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='historical_invoice_proposed'"), 1)

    def test_a_second_run_is_idempotent_and_a_different_value_stops_everything(self):
        self.run_insert(self.recs())
        added, same = self.run_insert(self.recs()); self.assertEqual((added, len(same)), ([], 1))
        with self.assertRaises(SystemExit) as e: self.run_insert(self.recs(amount_ht=5300.0))
        self.assertIn('existe déjà dans le registre avec d\'autres valeurs', str(e.exception))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 1)

    def test_the_d2_row_is_derived_with_the_rate_of_its_mandate_and_a_changed_rate_stops_everything(self):
        rec = self.recs(source_cell='M15', source_column='Facture 01.10', invoice_ref=None, qty_days=round(4550 / 600, 6), amount_ht=4550.0, unit_rate=600.0)
        self.set_rate(650)
        with self.assertRaises(SystemExit) as e: self.run_insert(rec)
        self.assertIn('fiche D2', str(e.exception)); self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 0)
        self.set_rate(600)
        added, _ = self.run_insert(rec); self.assertEqual(len(added), 1)
        self.assertEqual(self.sql('SELECT unit_rate,qty_days,amount_ht FROM historical_invoices')[0][:], (600.0, 7.583333, 4550.0))

    def test_the_decisions_d1_d2_d3_are_the_tool_s_lists(self):
        self.assertEqual(len(tool.D1), 23)
        self.assertNotIn(('SUIVI 2026', 'M15'), tool.D1); self.assertNotIn(('SUIVI 2026', 'M15'), tool.EXCLUDED)   # D2 = IMPORT_4550 (2026-10-07)
        self.assertEqual(tool.D2, {('SUIVI 2026', 'M15'): ('STC GEM Oct - DM job', 4550.0)}); self.assertEqual(tool.RATES, {('SUIVI 2026', 'M15'): 600.0})
        self.assertNotIn(('SUIVI 2025', 'H3'), tool.D1); self.assertIn(('SUIVI 2025', 'H3'), tool.EXCLUDED)        # D3 = NON
        self.assertEqual(sorted(tool.NOTES), sorted([('SUIVI 2026', 'J3'), ('SUIVI 2025', 'K7'), ('SUIVI 2025', 'M14'), ('SUIVI 2025', 'N10'), ('SUIVI 2025', 'N8'),
                                                     ('SUIVI 2026', 'M15')]))  # D4 + provenance D2
        days = sum(v if s == 'SUIVI 2025' else v / tool.RATE for (s, _), (_, v) in tool.D1.items())
        amount = sum(v * tool.RATE if s == 'SUIVI 2025' else v for (s, _), (_, v) in tool.D1.items())
        self.assertEqual((round(days, 2), round(amount, 2)), (205.63, 133659.5))
        self.assertEqual(tool.CONFIRM, 'CHARGER-24-A-VALIDER')


class RegistrySchema(G4):
    def test_the_deployment_check_sees_a_missing_trigger_or_index_of_the_registry(self):
        c = m.db()
        try:
            self.assertEqual(schema_checks.rc19_problems(c), [])
            c.execute('BEGIN'); c.execute('DROP TRIGGER historical_invoices_no_delete'); c.execute('DROP INDEX idx_historical_project')
            pb = schema_checks.rc19_problems(c)
            self.assertTrue(any('historical_invoices_no_delete' in p for p in pb), pb); self.assertTrue(any('idx_historical_project' in p for p in pb), pb)
            c.rollback()
        finally: c.close()

    def test_the_deployment_check_sees_a_broken_entry_insert_and_a_misplaced_reuse_trigger(self):
        """Revue rc19 (2026-10-08) : une insertion de saisie non compilable et un entry_id_never_reused rattaché à une autre table étaient invisibles."""
        c = m.db()
        try:
            c.execute('PRAGMA foreign_keys=OFF'); c.execute('BEGIN'); c.execute('DROP TRIGGER entry_id_never_reused')
            c.execute("CREATE TRIGGER entry_id_never_reused BEFORE INSERT ON settings BEGIN SELECT 1; END")
            pb = schema_checks.rc19_problems(c)
            self.assertTrue(any('entry_id_never_reused absent ou mal rattaché (settings)' in p for p in pb), pb)
            c.rollback(); c.execute('BEGIN')
            c.execute("CREATE TRIGGER tb_test_entry_insert BEFORE INSERT ON entries BEGIN SELECT x FROM table_absente; END")
            pb = schema_checks.rc19_problems(c)
            self.assertTrue(any("écriture non compilable (INSERT INTO entries" in p for p in pb), pb)
            c.rollback()
            self.assertEqual(schema_checks.rc19_problems(c), [])
        finally: c.close()

    def test_the_deployment_check_sees_a_missing_registry(self):
        c2 = m.db()
        try:
            c2.execute('PRAGMA foreign_keys=OFF'); c2.execute('BEGIN'); c2.execute('ALTER TABLE historical_invoices RENAME TO hi_old')
            pb = schema_checks.rc19_problems(c2)
            self.assertTrue(any('registre historical_invoices absent' in p for p in pb), pb)
            c2.rollback()
            self.assertEqual(schema_checks.rc19_problems(c2), [])                                 # rolled back: the copy is whole again
        finally: c2.close()
