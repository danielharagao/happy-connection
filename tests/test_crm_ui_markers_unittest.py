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

    def test_funnel_analytics_dom_and_hooks_exist(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js = (root / "static" / "app.js").read_text(encoding="utf-8")
        css = (root / "static" / "styles.css").read_text(encoding="utf-8")

        for marker in (
            'data-target="analytics"',
            'id="panel-analytics"',
            'id="analytics-filter-from"',
            'id="analytics-filter-to"',
            'id="analytics-filter-source"',
            'id="analytics-filter-campaign"',
            'id="analytics-filter-offer"',
            'id="analytics-funnel-map"',
            'tabindex="0"',
            'aria-describedby="analytics-funnel-scroll-hint"',
            'id="analytics-funnel-scroll-hint"',
            'role="note"',
            'id="analytics-traffic-breakdown"',
            'id="analytics-pages-breakdown"',
            'id="analytics-data-quality"',
            'Dados próprios do CRM',
            'até 500 eventos mais recentes',
            'pode incluir acessos de QA e testes',
            '<script src="/static/funnel-analytics.js?v=20260729-funnel3"></script>',
        ):
            self.assertIn(marker, html)

        self.assertIn('<link rel="stylesheet" href="/static/styles.css?v=20260729-funnel3" />', html)
        self.assertIn('<script src="/static/app.js?v=20260729-funnel3"></script>', html)
        self.assertIn("if (edge.dataMissing) return 'Não medido';", js)
        self.assertIn("if (tabKey === 'analytics') loadFunnelAnalytics()", js)
        self.assertIn("/api/crm/bridge/proxy/api/crm/funnel-events?limit=500", js)
        self.assertIn("/api/crm/bridge/proxy/api/crm/commercial", js)
        self.assertIn("FunnelAnalytics.buildFunnelModel", js)
        self.assertIn("function renderFunnelMap", js)
        self.assertIn("function applyAnalyticsFilters", js)
        self.assertIn("analytics-refresh-btn", js)

        self.assertIn('.funnel-map', css)
        self.assertIn('.funnel-node', css)
        self.assertIn('.funnel-connector', css)
        self.assertIn('.funnel-connector.aggregate-only', css)
        self.assertIn('.funnel-connector.data-missing', css)
        self.assertIn('.funnel-connector.data-missing span { max-width:64px;', css)
        self.assertIn('.funnel-map:focus-visible', css)
        self.assertIn('.sr-only', css)
        self.assertIn('.analytics-data-quality', css)


if __name__ == "__main__":
    unittest.main()
