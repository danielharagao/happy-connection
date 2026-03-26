import tempfile
import unittest
from pathlib import Path

import app as cockpit_app


class CronApiTests(unittest.TestCase):
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

    def test_add_list_delete_job(self):
        resp = self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Test Job",
                "schedule": "*/5 * * * *",
                "command": "echo hello",
                "enabled": True,
            },
        )
        self.assertEqual(resp.status_code, 201)
        job = resp.get_json()
        self.assertEqual(job["id"], "job-1")

        resp = self.client.get("/api/cron/jobs")
        self.assertEqual(resp.status_code, 200)
        local_items = [j for j in resp.get_json()["items"] if j.get("source") == "local"]
        self.assertEqual(len(local_items), 1)

        resp = self.client.delete("/api/cron/jobs/job-1")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/cron/jobs")
        local_items = [j for j in resp.get_json()["items"] if j.get("source") == "local"]
        self.assertEqual(local_items, [])

    def test_run_job_updates_fields_and_history(self):
        self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Run Job",
                "schedule": "0 * * * *",
                "command": "echo run-ok",
                "enabled": True,
            },
        )

        run_resp = self.client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
        self.assertEqual(run_resp.status_code, 200)
        run_data = run_resp.get_json()
        self.assertEqual(run_data["exitCode"], 0)
        self.assertEqual(run_data["status"], "success")
        self.assertIn("run-ok", run_data["output"])
        self.assertIsNotNone(run_data["startedAt"])
        self.assertIsNotNone(run_data["finishedAt"])
        self.assertGreaterEqual(run_data["durationMs"], 0)

        items = self.client.get("/api/cron/jobs").get_json()["items"]
        job = next(j for j in items if j.get("id") == "job-1" and j.get("source") == "local")
        self.assertIsNotNone(job["lastRunAt"])
        self.assertEqual(job["lastExitCode"], 0)
        self.assertEqual(len(job["runHistory"]), 1)
        self.assertEqual(job["runHistory"][0]["status"], "success")

        history_resp = self.client.get("/api/cron/jobs/job-1/history?limit=5")
        self.assertEqual(history_resp.status_code, 200)
        history = history_resp.get_json()["items"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "success")

    def test_run_history_tracks_output_summary_truncation(self):
        self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Long Output",
                "schedule": "0 * * * *",
                "command": "python3 -c \"print('x'*400)\"",
                "enabled": True,
            },
        )

        run_resp = self.client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
        self.assertEqual(run_resp.status_code, 200)
        data = run_resp.get_json()
        self.assertTrue(data["outputTruncated"])

        items = self.client.get("/api/cron/jobs").get_json()["items"]
        job = next(j for j in items if j.get("id") == "job-1" and j.get("source") == "local")
        hist = job["runHistory"][0]
        self.assertTrue(hist["outputTruncated"])
        self.assertLessEqual(len(hist["outputSummary"]), cockpit_app.OUTPUT_SUMMARY_CHARS)

    def test_disable_job_blocks_manual_run(self):
        self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Disabled Job",
                "schedule": "0 * * * *",
                "command": "echo should-not-run",
                "enabled": True,
            },
        )

        patch_resp = self.client.patch("/api/cron/jobs/job-1/enabled", json={"enabled": False})
        self.assertEqual(patch_resp.status_code, 200)
        self.assertFalse(patch_resp.get_json()["enabled"])

        no_confirm_resp = self.client.post("/api/cron/jobs/job-1/run")
        self.assertEqual(no_confirm_resp.status_code, 400)
        self.assertIn("confirm=true", no_confirm_resp.get_json()["error"])

        run_resp = self.client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
        self.assertEqual(run_resp.status_code, 409)
        self.assertIn("disabled", run_resp.get_json()["error"])

    def test_remove_job_requires_typed_confirmation(self):
        self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Cleanup",
                "schedule": "0 1 * * *",
                "command": "echo cleanup",
                "enabled": True,
            },
        )

        bad = self.client.post("/api/cron/jobs/job-1/remove", json={"confirm": "wrong"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("confirm", bad.get_json()["error"])

        ok = self.client.post("/api/cron/jobs/job-1/remove", json={"confirm": "job-1"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json()["removed"], "job-1")

        items = self.client.get("/api/cron/jobs").get_json()["items"]
        local_items = [j for j in items if j.get("source") == "local"]
        self.assertEqual(local_items, [])

    def test_validate_command_preview(self):
        resp = self.client.post("/api/cron/validate-command", json={"command": "python3 scripts/run_sync.py --dry-run"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["executable"], "python3")
        self.assertEqual(data["argCount"], 3)
        self.assertEqual(data["argv"][2], "--dry-run")

    def test_run_message_job_resolves_target_agent_to_session_key(self):
        self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Message Agent",
                "schedule": "*/5 * * * *",
                "targetAgentId": "worker-a",
                "message": "ping",
                "toolsProfileId": "worker-a",
                "enabled": True,
            },
        )

        perms = cockpit_app._load_permissions()
        perms["agents"]["worker-a"] = {
            "agentId": "worker-a",
            "label": "Worker A",
            "skills": {skill: (skill == "sessions_send") for skill in perms["skills"]},
            "updatedAt": cockpit_app._utc_now_iso(),
        }
        cockpit_app._save_permissions(perms)

        original_sessions = cockpit_app._load_openclaw_sessions
        original_cli_json = cockpit_app._run_cli_json
        try:
            cockpit_app._load_openclaw_sessions = lambda: [
                {"key": "agent:main:subagent:worker-a:thread-1", "ageMs": 9000},
                {"key": "agent:main:subagent:worker-a:thread-2", "ageMs": 2000},
            ]

            calls = []

            def _fake_cli_json(args, timeout=20):
                calls.append(args)
                return {"ok": True}

            cockpit_app._run_cli_json = _fake_cli_json

            run_resp = self.client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
            self.assertEqual(run_resp.status_code, 200)
            self.assertTrue(calls)
            self.assertIn("agent:main:subagent:worker-a:thread-2", calls[0])
        finally:
            cockpit_app._load_openclaw_sessions = original_sessions
            cockpit_app._run_cli_json = original_cli_json

    def test_create_and_patch_job_include_preflight_session_ready(self):
        original_sessions = cockpit_app._load_openclaw_sessions
        try:
            cockpit_app._load_openclaw_sessions = lambda: [{"key": "agent:main:subagent:worker-a:thread-1", "ageMs": 1200}]
            create_resp = self.client.post(
                "/api/cron/jobs",
                json={
                    "name": "Message Ready",
                    "schedule": "*/5 * * * *",
                    "targetAgentId": "worker-a",
                    "message": "ping",
                    "toolsProfileId": "worker-a",
                    "enabled": True,
                },
            )
            self.assertEqual(create_resp.status_code, 201)
            created = create_resp.get_json()
            self.assertTrue(created["preflightSessionRequired"])
            self.assertTrue(created["preflightSessionReady"])
            self.assertIn("thread-1", created["preflightSessionKey"])

            cockpit_app._load_openclaw_sessions = lambda: [{"key": "agent:main", "ageMs": 1000}]
            patch_resp = self.client.patch("/api/cron/jobs/job-1", json={"targetAgentId": "worker-missing"})
            self.assertEqual(patch_resp.status_code, 200)
            patched = patch_resp.get_json()
            self.assertTrue(patched["preflightSessionRequired"])
            self.assertFalse(patched["preflightSessionReady"])
            self.assertIn("no active session", patched["preflightSessionError"])
        finally:
            cockpit_app._load_openclaw_sessions = original_sessions

    def test_run_message_job_without_matching_session_returns_409(self):
        self.client.post(
            "/api/cron/jobs",
            json={
                "name": "Message Missing Session",
                "schedule": "*/5 * * * *",
                "targetAgentId": "worker-missing",
                "message": "ping",
                "toolsProfileId": "worker-missing",
                "enabled": True,
            },
        )

        perms = cockpit_app._load_permissions()
        perms["agents"]["worker-missing"] = {
            "agentId": "worker-missing",
            "label": "Worker Missing",
            "skills": {skill: (skill == "sessions_send") for skill in perms["skills"]},
            "updatedAt": cockpit_app._utc_now_iso(),
        }
        cockpit_app._save_permissions(perms)

        original_sessions = cockpit_app._load_openclaw_sessions
        try:
            cockpit_app._load_openclaw_sessions = lambda: [{"key": "agent:main", "ageMs": 1000}]
            run_resp = self.client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
            self.assertEqual(run_resp.status_code, 409)
            self.assertIn("no active session", run_resp.get_json()["error"])
        finally:
            cockpit_app._load_openclaw_sessions = original_sessions

    def test_openclaw_job_history_passthrough(self):
        original_cli_json = cockpit_app._run_cli_json
        try:
            cockpit_app._run_cli_json = lambda args, timeout=20: {
                "entries": [
                    {"jobId": "oc-job-1", "status": "ok", "durationMs": 1500},
                    {"jobId": "oc-job-1", "status": "failed", "durationMs": 900},
                ]
            }
            resp = self.client.get("/api/cron/jobs/oc-job-1/history?source=openclaw&limit=1")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["source"], "openclaw")
            self.assertEqual(data["id"], "oc-job-1")
            self.assertEqual(len(data["items"]), 1)
            self.assertEqual(data["items"][0]["status"], "ok")
        finally:
            cockpit_app._run_cli_json = original_cli_json


if __name__ == "__main__":
    unittest.main()
