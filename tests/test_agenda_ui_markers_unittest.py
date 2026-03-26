import unittest
from pathlib import Path


class AgendaUiMarkersTests(unittest.TestCase):
    def test_agenda_tab_and_layout_markers(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js = (root / "static" / "app.js").read_text(encoding="utf-8")
        css = (root / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-target="agenda"', html)
        self.assertIn('id="panel-agenda"', html)
        self.assertIn('id="agenda-mini-calendar"', html)
        self.assertIn('id="agenda-today-btn"', html)
        self.assertIn('id="agenda-list"', html)
        self.assertIn('id="agenda-create-modal"', html)
        self.assertIn('id="agenda-create-form"', html)
        self.assertIn('id="agenda-form-date"', html)
        self.assertIn('id="agenda-form-time"', html)
        self.assertIn('id="agenda-form-type"', html)
        self.assertIn('id="agenda-form-status"', html)
        self.assertIn('id="agenda-form-lead"', html)

        self.assertIn('const agendaState = {', js)
        self.assertIn('async function loadAgendaByDate', js)
        self.assertIn('/api/agenda', js)
        self.assertIn('function openLeadTrayFromAgenda', js)
        self.assertIn('function agendaOpenCreateModal()', js)
        self.assertIn('async function submitAgendaCreateForm(evt)', js)
        self.assertIn("data-action=\"close-agenda-modal\"", js)

        self.assertIn('.agenda-shell', css)
        self.assertIn('.agenda-mini-calendar', css)
        self.assertIn('.agenda-item.is-overdue', css)
        self.assertIn('.agenda-empty-state', css)
        self.assertIn('.agenda-create-form', css)
        self.assertIn('.agenda-form-grid', css)


if __name__ == "__main__":
    unittest.main()
