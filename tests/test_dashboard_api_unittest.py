import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as cockpit_app


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.CRON_JOBS_FILE = tmp_path / "cron_jobs.json"
        cockpit_app.PERMISSIONS_FILE = tmp_path / "permissions_matrix.json"
        cockpit_app.AGENT_PROFILES_FILE = tmp_path / "agent_profiles.json"
        cockpit_app.CRM_INTERACTIONS_FILE = tmp_path / "crm_interactions.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dashboard_summary_returns_team_and_crm_kpis(self):
        sessions_payload = {
            "sessions": [
                {"key": "agent/main", "isActive": True, "updatedAt": "2026-03-07T00:00:00Z"},
                {"key": "agent/ops", "isActive": False, "updatedAt": "2026-03-07T00:00:00Z"},
            ]
        }
        def fake_run(args, timeout=20):
            if args and args[0] == "sessions":
                return sessions_payload
            raise RuntimeError("unexpected call")

        with patch.object(cockpit_app, "_run_openclaw_json", side_effect=fake_run), \
             patch.object(cockpit_app, "_crm_health_probe", return_value={"ok": True, "baseUrl": "http://127.0.0.1:5000"}):
            resp = self.client.get("/api/dashboard/summary")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("team", body)
        self.assertIn("crm", body)
        self.assertGreaterEqual(body["team"]["totalAgents"], 1)
        self.assertIn("totalLeads", body["crm"])

    def test_agents_ids_endpoint_available(self):
        resp = self.client.get("/api/agents/ids")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("items", payload)


if __name__ == "__main__":
    unittest.main()
