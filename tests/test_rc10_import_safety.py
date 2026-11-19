"""V9.2-rc10: an import can never be applied twice (double click, two open previews, two tabs, concurrent requests).
Synthetic data only, on a COPY of the staging database (see test_import.py for the run command)."""
import re, threading
from datetime import datetime

import app.app as m
from tests.test_import import Base, workbook


class DoubleImport(Base):
    def data(self):
        return workbook({'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1), (datetime(2025, 3, 4), 'b', 'Alpha', None, None, 2)]})

    def test_same_token_committed_twice_inserts_once(self):
        t = self.upload(self.data()); form = self.save(t, {'Alpha': self.p1}); self.commit(t, form)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        r = self.c.post(f'/import/review/{t}', data=dict(form, action='commit', fingerprint='0' * 64, ack='1'))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM import_batches WHERE status='COMMITTED'"), 1)

    def test_two_previews_of_the_same_file_only_one_can_commit(self):
        t1 = self.upload(self.data()); f1 = self.save(t1, {'Alpha': self.p1})
        t2 = self.upload(self.data()); f2 = self.save(t2, {'Alpha': self.p1})
        fp2 = re.search(r'name="fingerprint" value="([0-9a-f]+)"', self.review(t2)).group(1)  # approved while nothing was imported yet
        self.commit(t1, f1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        self.flashes(); r = self.c.post(f'/import/review/{t2}', data=dict(f2, action='commit', fingerprint=fp2, ack='1'))
        self.assertTrue(any('non exécuté' in x for x in self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM import_batches WHERE status='COMMITTED'"), 1)
        self.integrity()

    def test_concurrent_commits_insert_once(self):
        toks = []
        for _ in range(4):
            t = self.upload(self.data()); f = self.save(t, {'Alpha': self.p1})
            toks.append((t, f, re.search(r'name="fingerprint" value="([0-9a-f]+)"', self.review(t)).group(1)))
        res = []
        def go(t, f, fp):
            c = m.APP.test_client(); c.post('/login', data={'username': m.SEC['user'], 'password': __import__('os').environ['APP_PASSWORD']})
            res.append(c.post(f'/import/review/{t}', data=dict(f, action='commit', fingerprint=fp, ack='1')).status_code)
        th = [threading.Thread(target=go, args=x) for x in toks]
        [x.start() for x in th]; [x.join() for x in th]
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM import_batches WHERE status='COMMITTED'"), 1)
        self.integrity()

    def test_rollback_twice_and_after_manual_correction_is_safe(self):
        t = self.upload(self.data()); form = self.save(t, {'Alpha': self.p1}); self.commit(t, form)
        b = self.scalar("SELECT id FROM import_batches WHERE status='COMMITTED'")
        self.c.post(f'/imports/rollback/{b}'); self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        self.c.post(f'/imports/rollback/{b}'); self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batch_rows WHERE batch_id=?', (b,)), 2)
        self.integrity()
