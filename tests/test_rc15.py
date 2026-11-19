"""V9.2-rc15: resumed session — mandate positions beside the time-entry form, placeholder contrast (synthetic data, COPY of the staging database)."""
import re

from tests.test_credit_settlement import Settlement
import app.app as m
from tests._app_facts import declared_version


class TimeTabPositions(Settlement):
    def page(self): return self.c.get('/').get_data(as_text=True)

    def test_position_panel_is_shared_by_time_mandates_and_billing_tabs(self):
        panels = re.findall(r'<section class="panel p-balances" data-panel="([^"]+)"', self.page())
        self.assertEqual(len(panels), 1)
        self.assertEqual(set(panels[0].split()), {'mandates', 'billing', 'time'})

    def test_time_tab_highlights_the_selected_project_and_hides_creation_link(self):
        t = self.page()
        self.assertIn('#entryForm select[name=project_id]', t)
        css = t[t.index('<style>'):t.index('</style>')]
        self.assertIn('body[data-tab=time] .bal.tsel', css)
        self.assertIn('body[data-tab=time] .p-balances .only-mandates{display:none}', css)

    def test_placeholder_color_meets_contrast_aa(self):
        t = self.page()
        col = re.findall(r'input::placeholder,textarea::placeholder\{color:#([0-9a-f]{6})', t)[-1]  # the design system loads last and wins
        lin = lambda v: (v / 12.92) if v <= .03928 else ((v + .055) / 1.055) ** 2.4
        r, g, b = (lin(int(col[i:i + 2], 16) / 255) for i in (0, 2, 4))
        lum = .2126 * r + .7152 * g + .0722 * b
        self.assertGreaterEqual(1.05 / (lum + .05), 4.5)

    def test_version(self):
        self.assertEqual(m.VERSION, declared_version())
