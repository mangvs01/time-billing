"""BILL-FA1FT : correction des trois défauts F_A1, F_T1, F_T2 de la revue rc40 par des migrations ADDITIVES et RÉVERSIBLES. Données synthétiques uniquement.

F_A1  deux adresses de facturation d'un même client qui ne diffèrent que par la casse : index unique (client_key, label COLLATE NOCASE) + contrôle applicatif (casse Unicode complète) ;
      l'index n'est PAS créé si des doublons existent déjà (note d'audit, rapport schema_checks, démarrage non bloqué, aucune donnée touchée).
F_T1  une ligne de brouillon ne peut pas être rattachée par UPDATE à une facture émise ou figée (déclencheur invoice_line_no_move_to_issued, app/line_guards.py).
F_T2  les gardes d'insertion des lignes d'avoir existent aussi en BEFORE UPDATE (credit_line_upd_*), et une ligne ne peut pas être rattachée à une note émise.
Pour chacun : empreinte métier identique avant/après migration, idempotence, retour arrière."""
import hashlib, json, sqlite3, unittest

import app.app as m
from app import address_service, credit_lines, line_guards, restore_service, schema_checks
from tests import test_credit_lines as tcl


class Base(tcl.Base):
    def fingerprint(self, skip=()):
        """Empreinte du CONTENU métier : toutes les tables (hors tables internes de SQLite) et leurs lignes, rien du schéma."""
        c = sqlite3.connect(self.db); h = hashlib.sha256()
        try:
            for t in sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")):
                if t in skip: continue
                h.update(t.encode())
                for r in c.execute('SELECT * FROM "%s" ORDER BY 1' % t): h.update(repr(tuple(r)).encode())
            return h.hexdigest()
        finally: c.close()

    def master(self, kind, name):
        return self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type=? AND name=?", (kind, name))

    def sqlw(self, *qs):
        c = sqlite3.connect(self.db)
        try:
            for q in qs: c.execute(q)
            c.commit()
        finally: c.close()


# ===================================================================================================================================================
class F_A1(Base):
    IDX = address_service.LABEL_INDEX

    def add(self, label, key='*', address='Rue 2'):
        self.flashes(); self.c.post('/adresses/ajouter', data={'client_key': key, 'label': label, 'contact': '', 'address': address}); return ' '.join(self.flashes())

    def count(self, key='*'): return self.scalar("SELECT COUNT(*) FROM billing_addresses WHERE client_key=?", (key,))

    def setUp(self):
        super().setUp(); self.mandate(name='Mandat adresse', legal_id='CHE-000.000.077')
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','EGG FR','Rue 1','2026-10-27T10:00:00')")

    def test_the_index_exists_on_a_fresh_database_and_the_database_itself_refuses_a_case_variant(self):
        self.assertEqual(self.master('index', self.IDX), 1)
        msg = self.raw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','egg fr','Rue 3','2026-10-27T10:00:00')")
        self.assertIsNotNone(msg); self.assertIn('UNIQUE', msg)

    def test_the_application_refuses_ascii_and_accented_case_variants_with_a_clear_message(self):
        for lab in ('egg fr', 'Egg Fr', '  EGG   fr '):
            self.assertIn('existe déjà', self.add(lab), lab)
        self.assertEqual(self.count(), 1)
        self.assertIn('ajoutée', self.add('Écu'))
        self.assertIn('existe déjà', self.add('écu')); self.assertEqual(self.count(), 2)          # É/é : above the ASCII folding of the index, caught by the application

    def test_the_same_label_for_another_client_or_another_label_is_still_fine(self):
        self.assertIn('ajoutée', self.add('EGG BE')); self.assertEqual(self.count(), 2)
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('NOM:autre','egg fr','Rue 9','2026-10-27T10:00:00')")      # another client: independent

    def test_renaming_an_address_to_a_case_variant_of_another_is_refused_but_its_own_case_can_change(self):
        self.add('EGG BE'); a, b = [r['id'] for r in self.sql("SELECT id FROM billing_addresses WHERE client_key='*' ORDER BY id")]
        self.flashes(); self.c.post(f'/adresses/{b}', data={'label': 'egg fr', 'contact': '', 'address': 'Rue 2'}); self.assertIn('non modifiée', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT label FROM billing_addresses WHERE id=?', (b,)), 'EGG BE')
        self.flashes(); self.c.post(f'/adresses/{b}', data={'label': 'egg be', 'contact': '', 'address': 'Rue 2'}); self.assertIn('enregistrée', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT label FROM billing_addresses WHERE id=?', (b,)), 'egg be')

    def test_an_existing_database_is_migrated_without_loss_idempotent_and_reversible(self):
        c = sqlite3.connect(self.db); address_service.drop_label_index(c); c.commit()                              # a database as it was before BILL-FA1FT
        self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name=?", (self.IDX,)).fetchone()[0], 0); c.close()
        before = self.fingerprint(); m.init()
        self.assertEqual(self.master('index', self.IDX), 1); self.assertEqual(self.fingerprint(), before)           # business fingerprint identical (index only)
        m.init(); self.assertEqual(self.master('index', self.IDX), 1); self.assertEqual(self.fingerprint(), before)  # idempotent
        c = sqlite3.connect(self.db); address_service.drop_label_index(c); c.commit(); c.close()                    # documented rollback
        self.assertEqual(self.master('index', self.IDX), 0); self.assertEqual(self.fingerprint(), before)
        self.assertIsNone(self.raw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','egg fr','Rue 3','2026-10-27T10:00:00')"))   # the defect is back, as before

    def test_existing_duplicates_prevent_the_index_nothing_is_touched_and_the_start_is_not_blocked(self):
        c = sqlite3.connect(self.db); address_service.drop_label_index(c)
        c.execute("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','egg fr','Rue 3','2026-10-27T10:00:00')"); c.commit(); c.close()
        before = self.fingerprint(skip=('audit',)); n_audit = self.scalar('SELECT COUNT(*) FROM audit')
        m.init(); m.init()                                                                                          # no exception, twice
        self.assertEqual(self.master('index', self.IDX), 0)                                                         # NOT created
        self.assertEqual(self.fingerprint(skip=('audit',)), before)                                                  # no row touched
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped'"), 1)   # noted once only
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM audit'), n_audit + 1)
        c = sqlite3.connect(self.db)
        try:
            self.assertEqual(address_service.label_duplicates(c), [('*', 'EGG FR | egg fr')])
            self.assertTrue(any('libellés d\'adresse' in p and 'EGG FR | egg fr' in p for p in schema_checks.rc19_problems(c)), schema_checks.rc19_problems(c))
        finally: c.close()
        self.assertIn('existe déjà', self.add('EGG FR'))                                                             # the application still refuses new ones
        self.assertIn('existe déjà', self.add('Egg fR'))
        self.sqlw("DELETE FROM billing_addresses WHERE label='egg fr'"); m.init()                                    # the owner fixed the data (here: by SQL): the next start creates it
        self.assertEqual(self.master('index', self.IDX), 1)

    def test_the_seeding_of_the_global_list_does_not_crash_on_a_case_variant(self):
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('NOM:bsci','egg fr','Rue X','2026-10-27T10:00:00')")      # seeded for the first client, already a variant globally
        m.init(); m.init()                                                                                           # make_global used to hit the unique index here
        self.assertEqual(self.scalar("SELECT client_key FROM billing_addresses WHERE label='egg fr'"), 'NOM:bsci')   # not moved: the global one already exists (case-insensitively)

    def test_a_backup_holding_a_case_variant_is_blocked_before_the_restore_starts(self):
        data = json.loads(self.c.get('/backup').data)
        self.assertEqual(restore_service.address_label_conflicts(data), [])
        rows = data['tables']['billing_addresses']; extra = dict(rows[0]); extra.update(id=max(r['id'] for r in rows) + 1, label=rows[0]['label'].lower()); rows.append(extra)
        out = restore_service.address_label_conflicts(data); self.assertEqual(len(out), 1); self.assertIn('majuscules et minuscules', out[0])
        c = m.db()
        try:
            data['meta']['row_counts']['billing_addresses'] = len(rows); self.assertTrue(any('majuscules et minuscules' in b for b in restore_service.preview(c, restore_service.validate(c, json.dumps(data)))['blocking']))
        finally: c.close()


# ===================================================================================================================================================
class F_T1(Base):
    def setUp(self):
        super().setUp()
        self.iid = self.issued_with(); self.l1, self.l2 = self.line_ids(self.iid)
        self.d = self.draft_with(lines=(('Ligne mobile', '1', '5', 'flat', 'soumis'),), period=('2026-10-01', '2026-10-31')); (self.ld,) = self.line_ids(self.d)
        self.d2 = self.draft_with(lines=(), period=('2026-11-01', '2026-11-30'))

    def move(self, lid, to, pos=9): return self.raw("UPDATE invoice_lines SET invoice_id=%d, position=%d WHERE id=%d" % (to, pos, lid))

    def test_a_draft_line_cannot_be_moved_under_an_issued_invoice(self):
        msg = self.move(self.ld, self.iid); self.assertIsNotNone(msg); self.assertIn('immutable', msg)
        self.assertEqual(self.scalar('SELECT invoice_id FROM invoice_lines WHERE id=?', (self.ld,)), self.d)

    def test_a_draft_line_cannot_be_moved_under_a_frozen_invoice_even_if_its_status_was_not_issued(self):
        self.sqlw("UPDATE invoices SET status='draft' WHERE 0")      # (no-op, keeps the intent readable)
        iid2 = self.d2
        c = sqlite3.connect(self.db)
        try:
            c.execute("INSERT INTO invoice_snapshots(invoice_id,number,frozen_at,frozen_by,header_json,annex_json,pdf,pdf_sha256) VALUES(?,?,?,?,?,?,?,?)", (iid2, 'X-1', '2026-11-30', 't', '{}', '[]', b'x', 'x'))
            c.commit()
            with self.assertRaises(sqlite3.DatabaseError) as cm: c.execute("UPDATE invoice_lines SET invoice_id=?, position=9 WHERE id=?", (iid2, self.ld))
            self.assertIn('immutable', str(cm.exception))
        finally: c.close()

    def test_legitimate_updates_of_a_draft_line_are_still_possible(self):
        self.assertIsNone(self.raw("UPDATE invoice_lines SET description='Texte modifié', qty=2 WHERE id=%d" % self.ld))
        self.assertIsNone(self.move(self.ld, self.d2))                                                               # draft → another draft
        self.assertEqual(self.scalar('SELECT invoice_id FROM invoice_lines WHERE id=?', (self.ld,)), self.d2)
        self.assertIsNone(self.raw("UPDATE invoice_lines SET invoice_id=invoice_id WHERE id=%d" % self.ld))          # same value written back
        self.assertIsNotNone(self.raw("UPDATE invoice_lines SET description='x' WHERE id=%d" % self.l1))             # the lines of an issued invoice stay immutable (existing guard)

    def test_the_interface_still_edits_a_draft_with_lines(self):
        r, fl = self.save(self.d2, [tcl.line('Ligne 1', '1', '10', uid='ua'), tcl.line('Ligne 2', '2', '20', uid='ub')], period_from='2026-11-01', period_to='2026-11-30')
        self.assertIn('Brouillon modifié.', fl); self.assertEqual(len(self.line_ids(self.d2)), 2)

    def test_an_existing_database_is_migrated_without_loss_idempotent_and_reversible(self):
        c = sqlite3.connect(self.db); line_guards.rollback(c); c.commit()                                             # a database as it was before BILL-FA1FT
        self.assertFalse(line_guards.is_present(c)); c.close()
        before = self.fingerprint(); m.init()
        c = sqlite3.connect(self.db)
        try:
            self.assertTrue(line_guards.is_present(c)); self.assertEqual(self.fingerprint(), before); self.assertFalse(line_guards.migrate(c))              # idempotent
            line_guards.rollback(c); self.assertFalse(line_guards.is_present(c)); c.commit()                           # documented rollback
        finally: c.close()
        self.assertEqual(self.fingerprint(), before); m.init()
        self.assertIsNotNone(self.move(self.ld, self.iid))                                                           # guarded again after the next start
        c = sqlite3.connect(self.db); line_guards.rollback(c); c.commit(); c.close()
        self.assertIsNone(self.move(self.ld, self.iid))                                                              # without the trigger the defect is back, exactly as before (proves the rollback)


# ===================================================================================================================================================
class F_T2(Base):
    def setUp(self):
        super().setUp()
        self.iid = self.issued_with(); self.l1, self.l2 = self.line_ids(self.iid)           # l1 = 100 soumis ; l2 = 50 hors_tva
        self.cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{self.l2}': '10'}); self.assertIsNotNone(self.cid, fl)
        self.d = self.draft_with(lines=(('Autre facture', '1', '500', 'flat', 'hors_tva'),), period=('2026-10-01', '2026-10-31')); (self.ld,) = self.line_ids(self.d)

    def upd(self, sets, cid=None): return self.raw("UPDATE credit_note_lines SET %s WHERE credit_note_id=%d" % (sets, cid or self.cid))

    def test_a_credited_line_row_cannot_be_redirected_to_a_line_of_another_invoice(self):
        msg = self.upd("invoice_line_id=%d" % self.ld); self.assertIsNotNone(msg); self.assertIn('belongs to the invoice', msg)

    def test_a_credited_line_row_keeps_the_vat_regime_of_its_invoice_line(self):
        msg = self.upd("vat_mode='soumis'"); self.assertIsNotNone(msg); self.assertIn('VAT regime', msg)
        msg = self.upd("invoice_line_id=%d" % self.l1); self.assertIsNotNone(msg); self.assertIn('VAT regime', msg)      # l1 is « soumis », the row says « hors_tva »

    def test_a_credited_line_row_cannot_exceed_the_amount_of_its_invoice_line(self):
        msg = self.upd("amount=50.01"); self.assertIsNotNone(msg); self.assertIn('cannot exceed', msg)
        msg = self.upd("amount=5000"); self.assertIsNotNone(msg); self.assertIn('cannot exceed', msg)
        self.assertIsNone(self.upd("amount=50")); self.assertIsNone(self.upd("amount=0.5"))                               # the row itself is not counted twice (10 → 50 is allowed)

    def test_the_cap_counts_the_other_notes_of_the_line(self):
        self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l2}': '30'})
        msg = self.upd("amount=21"); self.assertIsNotNone(msg); self.assertIn('cannot exceed', msg)                       # 30 issued + 21 > 50
        self.assertIsNone(self.upd("amount=20"))

    def test_the_half_cent_rounding_of_the_insert_guard_is_the_same_on_update(self):
        i2 = self.issued_with(lines=(('Demi-cent', '1.5', '0.15', 'flat', 'soumis'),), period=('2026-08-01', '2026-08-31')); (lh,) = self.line_ids(i2)
        cid, fl = self.credit(i2, scope='partial', **{f'cl_{lh}': '0.10'}); self.assertIsNotNone(cid, fl)
        self.assertIsNone(self.upd("amount=0.23", cid)); self.assertIsNotNone(self.upd("amount=0.24", cid))

    def test_a_row_cannot_be_moved_under_an_issued_note_and_the_rows_of_an_issued_note_stay_immutable(self):
        cid2 = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '20'})
        msg = self.upd("credit_note_id=%d" % cid2); self.assertIsNotNone(msg); self.assertIn('immutable', msg)
        msg = self.upd("amount=1", cid2); self.assertIsNotNone(msg); self.assertIn('immutable', msg)

    def test_free_columns_stay_writable_and_the_interface_still_edits_a_draft_note(self):
        self.assertIsNone(self.upd("description='Texte corrigé', position=1"))
        iid = self.issued_with(lines=(tcl.L1, tcl.L2), period=('2026-08-01', '2026-08-31')); a, b = self.line_ids(iid)
        cid, fl = self.credit(iid, scope='partial', **{f'cl_{a}': '10', f'cl_{b}': '5'}); self.assertIsNotNone(cid, fl)
        self.assertEqual(self.rows_of(cid)[0][4], 10.0)
        self.flashes(); self.c.post(f'/credit/{cid}/delete'); self.issued_cn(iid, scope='total')                         # a draft is deleted then the total credit is made: no guard in the way

    def test_an_existing_database_is_migrated_without_loss_idempotent_and_reversible(self):
        c = sqlite3.connect(self.db); credit_lines.rollback_update_guards(c); c.commit()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'credit_line_upd_%'").fetchone()[0], 0); c.close()
        self.assertIsNone(self.upd("amount=5000")); self.sqlw("UPDATE credit_note_lines SET amount=10 WHERE credit_note_id=%d" % self.cid)             # the defect, then put back
        before = self.fingerprint(); m.init()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'credit_line_upd_%'"), len(credit_lines.UPDATE_GUARD_NAMES))
        self.assertEqual(self.fingerprint(), before); m.init(); self.assertEqual(self.fingerprint(), before)                                          # idempotent
        self.assertIsNotNone(self.upd("amount=5000"))
        c = sqlite3.connect(self.db); credit_lines.rollback_update_guards(c); c.commit(); c.close()                                                    # documented rollback
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'credit_line_upd_%'"), 0); self.assertEqual(self.fingerprint(), before)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('credit_lines_same_invoice','credit_lines_same_vat_mode','credit_lines_within_line','credit_lines_no_update_issued')"), 4)   # the insert guards are untouched

    def test_the_insert_trigger_text_is_unchanged_by_the_refactoring_of_the_cap(self):
        c = sqlite3.connect(self.db)
        try: self.assertTrue(credit_lines.within_line_is_current(c)); self.assertFalse(credit_lines.migrate(c))
        finally: c.close()


if __name__ == '__main__':
    unittest.main()
