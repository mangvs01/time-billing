"""Scratch (session 412386): render page-1 PDFs with 1/2/3-line descriptions (+ a 1-line note) into /data/out for a host-side pdftotext -bbox."""
import os, unittest
from tests import test_g4

class Mesure(test_g4.G4):
    def test_render(self):
        os.makedirs('/data/out', exist_ok=True)
        three = ' '.join(['mot'] * 20)
        for tag, desc in (('1l', 'Production septembre'), ('2l', 'Production PM/DM - Mandat G4 - NP-0001 deuxième ligne de la description'), ('3l', three)):
            iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, description=desc, other_amount='120', other_label='Frais de déplacement Bruxelles')[0]
            open(f'/data/out/{tag}.pdf', 'wb').write(self.c.get(f'/invoice/{iid}.pdf').data)
            self.c.post(f'/invoice/{iid}/delete')

if __name__ == '__main__': unittest.main()
