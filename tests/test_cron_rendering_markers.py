import unittest
from pathlib import Path


class CronRenderingMarkersTests(unittest.TestCase):
    def test_template_contains_source_target_and_profile_markers(self):
        template = Path(__file__).resolve().parent.parent / "templates" / "index.html"
        html = template.read_text(encoding="utf-8")
        self.assertIn("ID/Source", html)
        self.assertIn("Target Agent", html)
        self.assertIn("Effective Tools Profile", html)
        self.assertIn("cron-target-agent-select", html)
        self.assertIn("cron-tools-profile-select", html)


if __name__ == "__main__":
    unittest.main()
