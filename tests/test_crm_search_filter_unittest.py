import unittest
from pathlib import Path


class CrmSearchFilterTests(unittest.TestCase):
    def test_search_filter_normalizes_phone_and_combines_with_quick_filter(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function crmNormalizeDigits", js)
        self.assertIn("replace(/\\D/g, '')", js)
        self.assertIn("function crmLeadMatchesSearchText", js)
        self.assertIn("name.includes(q)", js)
        self.assertIn("phoneDigits.includes(qDigits)", js)
        self.assertIn("crmLeadMatchesQuickFilterIsBa(lead) && crmLeadMatchesSearchText(lead, query)", js)

    def test_search_term_persists_in_local_storage(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("CRM_LEADS_SEARCH_KEY", js)
        self.assertIn("crmReadLeadsSearchTextFromStorage", js)
        self.assertIn("crmPersistLeadsSearchText", js)
        self.assertIn("localStorage.getItem(CRM_LEADS_SEARCH_KEY)", js)
        self.assertIn("localStorage.setItem(CRM_LEADS_SEARCH_KEY", js)


if __name__ == "__main__":
    unittest.main()
