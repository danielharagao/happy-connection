import tempfile
import unittest
from pathlib import Path

import app as cockpit_app


class CronProviderAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.CRON_JOBS_FILE = tmp_path / "cron_jobs.json"
        cockpit_app.PERMISSIONS_FILE = tmp_path / "permissions_matrix.json"
        cockpit_app.OFFICE_LAYOUT_FILE = tmp_path / "office_layout.json"
        cockpit_app.AGENT_PROFILES_FILE = tmp_path / "agent_profiles.json"
        cockpit_app.KANBAN_TASKS_FILE = tmp_path / "kanban_tasks.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_sanitize_new_job_maps_schedule_and_policy(self):
        cockpit_app._ensure_store()
        job = cockpit_app._sanitize_new_job(
            {
                "name": "Agent ping",
                "scheduleMode": "every",
                "scheduleValue": "5m",
                "targetAgentId": "main",
                "toolsProfileId": "main",
                "message": "hello",
                "enabled": True,
            },
            [],
        )
        self.assertEqual(job["scheduleMode"], "every")
        self.assertEqual(job["scheduleValue"], "5m")
        self.assertEqual(job["schedule"], "every 5m")
        self.assertEqual(job["source"], "local")
        self.assertEqual(job["targetAgentId"], "main")
        self.assertEqual(job["effectivePolicy"]["enforcedBy"], "app-policy")

    def test_list_jobs_prioritizes_openclaw_source(self):
        self.client.post(
            "/api/cron/jobs",
            json={"name": "Local", "schedule": "* * * * *", "command": "echo hi", "enabled": True},
        )

        original = cockpit_app._load_openclaw_cron_jobs
        try:
            cockpit_app._load_openclaw_cron_jobs = lambda: ([cockpit_app._normalize_job({
                "id": "oc-1", "name": "Real job", "source": "openclaw", "schedule": "* * * * *", "enabled": True,
            })], None)
            resp = self.client.get("/api/cron/jobs")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["items"][0]["source"], "openclaw")
            self.assertEqual(body["items"][1]["source"], "local")
        finally:
            cockpit_app._load_openclaw_cron_jobs = original

    def test_list_jobs_surfaces_openclaw_error(self):
        self.client.post(
            "/api/cron/jobs",
            json={"name": "Local", "schedule": "* * * * *", "command": "echo hi", "enabled": True},
        )

        original = cockpit_app._load_openclaw_cron_jobs
        try:
            cockpit_app._load_openclaw_cron_jobs = lambda: ([], "bridge unavailable")
            resp = self.client.get("/api/cron/jobs")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(len(body["items"]), 1)
            self.assertEqual(body["items"][0]["source"], "local")
            self.assertEqual(body["sources"]["openclaw"]["error"], "bridge unavailable")
        finally:
            cockpit_app._load_openclaw_cron_jobs = original


if __name__ == "__main__":
    unittest.main()
