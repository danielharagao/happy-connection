import os
import tempfile
import unittest
from pathlib import Path

import app as cockpit_app


class EnvironmentModeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.CRON_JOBS_FILE = tmp_path / "cron_jobs.json"
        cockpit_app.PERMISSIONS_FILE = tmp_path / "permissions_matrix.json"
        cockpit_app.OFFICE_LAYOUT_FILE = tmp_path / "office_layout.json"
        cockpit_app.AGENT_PROFILES_FILE = tmp_path / "agent_profiles.json"
        cockpit_app.KANBAN_TASKS_FILE = tmp_path / "kanban_tasks.json"
        cockpit_app.KANBAN_SYNC_HEALTH_FILE = tmp_path / "kanban_sync_health.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_environment_endpoint_returns_mode_and_data_dir(self):
        resp = self.client.get("/api/system/environment")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn(payload["environment"], {"prod", "dev", "test"})
        self.assertEqual(payload["dataDir"], str(cockpit_app.DATA_DIR))


if __name__ == "__main__":
    unittest.main()
