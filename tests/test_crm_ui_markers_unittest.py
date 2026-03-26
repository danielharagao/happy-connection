import unittest
from pathlib import Path


class CrmUiMarkersTests(unittest.TestCase):
    def test_crm_dom_and_hooks_exist(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js = (root / "static" / "app.js").read_text(encoding="utf-8")
        css = (root / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="panel-crm"', html)
        self.assertIn('id="crm-board-shell"', html)
        self.assertIn('id="crm-board-columns"', html)
        self.assertIn('data-testid="crm-leads-search-input"', html)
        self.assertIn('id="crm-leads-search-clear"', html)

        self.assertIn('async function loadCrmBridge()', js)
        self.assertIn("/api/crm/bridge", js)
        self.assertIn("crm-board-columns", js)

        self.assertIn('.crm-board-shell', css)
        self.assertIn('.crm-board-columns', css)
        self.assertIn('data-tray-tab="operational"', html)
        self.assertIn('data-tray-tab="notes"', html)
        self.assertIn('/api/crm/bridge/notes', js)
        self.assertIn('onCrmBoardDragStart', js)
        self.assertIn('addEventListener(\'drop\', onCrmBoardDrop)', js)
        self.assertIn('data-draggable-card="crm"', js)
        self.assertIn('CRM_LEADS_SEARCH_KEY', js)
        self.assertIn('function crmLeadMatchesSearchText', js)
        self.assertIn('function crmNormalizeDigits', js)
        self.assertIn('id="fluxo-toggle-stop-on-reply"', html)
        self.assertIn('id="fluxo-toggle-active"', html)
        self.assertIn('id="cadencias-list-screen"', html)
        self.assertIn('id="cadencias-detail-screen"', html)
        self.assertIn('id="cadencias-list"', html)
        self.assertIn('id="cadencia-audience-status"', html)
        self.assertIn('id="cadencia-audience-label"', html)
        self.assertIn('id="cadencia-audience-origin"', html)
        self.assertIn('data-testid="cadencia-messages-list"', html)
        self.assertIn('cadencia-validation', html)
        self.assertIn('defaultCadence', js)
        self.assertIn('/api/crm/bridge/cadences', js)
        self.assertIn('validateSelectedCadence', js)
        self.assertIn('cadencia-toggle', js)
        self.assertNotIn('Lead 360', js)


if __name__ == "__main__":
    unittest.main()
