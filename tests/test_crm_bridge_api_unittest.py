import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as cockpit_app


class CrmBridgeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.CRON_JOBS_FILE = tmp_path / "cron_jobs.json"
        cockpit_app.PERMISSIONS_FILE = tmp_path / "permissions_matrix.json"
        cockpit_app.AGENT_PROFILES_FILE = tmp_path / "agent_profiles.json"
        cockpit_app.CRM_INTERACTIONS_FILE = tmp_path / "crm_interactions.json"
        cockpit_app.CRM_LEAD_STATUS_FILE = tmp_path / "crm_lead_status.json"
        cockpit_app.CRM_LEAD_EVENTS_FILE = tmp_path / "crm_lead_events.json"
        cockpit_app.CRM_LEAD_NOTES_FILE = tmp_path / "crm_lead_notes.json"
        cockpit_app.CRM_FLOW_FILE = tmp_path / "crm_flow.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_crm_bridge_metadata_endpoint(self):
        with patch.object(cockpit_app, "_crm_health_probe", return_value={"ok": True, "baseUrl": "http://127.0.0.1:5000"}):
            resp = self.client.get("/api/crm/bridge")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("crm", payload)

    def test_crm_proxy_blocks_disallowed_paths(self):
        resp = self.client.get("/api/crm/bridge/proxy/api/crm/private")
        self.assertIn(resp.status_code, (400, 403))

    def test_lead_operational_status_roundtrip(self):
        create = self.client.post(
            "/api/crm/bridge/lead-operational/123",
            json={"inGroup": True, "emailOpened": False, "actor": "test"},
        )
        self.assertEqual(create.status_code, 200)

        read_back = self.client.get("/api/crm/bridge/lead-operational/123")
        self.assertEqual(read_back.status_code, 200)
        payload = read_back.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("status", {}).get("inGroup"), True)
        self.assertEqual(payload.get("status", {}).get("emailOpened"), False)

    def test_lead_notes_roundtrip_and_sorting(self):
        create_a = self.client.post("/api/crm/bridge/notes", json={"leadId": 123, "content": "Primeira"})
        self.assertEqual(create_a.status_code, 201)
        create_b = self.client.post("/api/crm/bridge/notes", json={"leadId": 123, "content": "Segunda"})
        self.assertEqual(create_b.status_code, 201)

        read_back = self.client.get("/api/crm/bridge/notes/123")
        self.assertEqual(read_back.status_code, 200)
        payload = read_back.get_json()
        self.assertTrue(payload.get("ok"))
        items = payload.get("items", [])
        self.assertGreaterEqual(len(items), 2)
        self.assertEqual(items[0].get("content"), "Segunda")
        self.assertEqual(items[1].get("content"), "Primeira")

    def test_lead_notes_validation_and_mission_control_prefix(self):
        invalid = self.client.post("/api/crm/bridge/notes", json={"leadId": 123, "content": "   "})
        self.assertEqual(invalid.status_code, 400)

        create = self.client.post("/mission-control/api/crm/bridge/notes", json={"leadId": 321, "content": "Teste MC"})
        self.assertEqual(create.status_code, 201)

        read_back = self.client.get("/mission-control/api/crm/bridge/notes/321")
        self.assertEqual(read_back.status_code, 200)
        payload = read_back.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("items", [])[0].get("content"), "Teste MC")

    def test_lead_update_accepts_stage_fields(self):
        captured = {}

        def fake_request_with_retry(req, max_attempts=3, timeout=5.0):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["body"] = json.loads((req.data or b"{}").decode("utf-8"))
            return io.BytesIO(b'{"ok":true}').read(), 200, {"Content-Type": "application/json"}

        with patch.object(cockpit_app, "_crm_request_with_retry", side_effect=fake_request_with_retry):
            resp = self.client.post(
                "/api/crm/bridge/lead-update",
                json={"id": 77, "current_stage": "Interessado", "status": "Interessado"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get("method"), "POST")
        self.assertIn("api/crm/lead-update", captured.get("url", ""))
        self.assertEqual(captured.get("body", {}).get("id"), 77)
        self.assertEqual(captured.get("body", {}).get("current_stage"), "Interessado")
        self.assertEqual(captured.get("body", {}).get("status"), "Interessado")

    def test_flow_defaults_are_returned_when_file_missing(self):
        resp = self.client.get("/api/crm/bridge/flow")
        self.assertEqual(resp.status_code, 200)
        flow = resp.get_json().get("flow", {})
        self.assertEqual(flow.get("stopOnReply"), True)
        self.assertEqual(flow.get("isActive"), False)
        self.assertEqual(flow.get("autoEnrollNewLeads"), False)

    def test_flow_new_toggles_roundtrip_and_retrocompatibility(self):
        save_resp = self.client.post(
            "/api/crm/bridge/flow",
            json={
                "flow": {
                    "name": "Fluxo Teste",
                    "stopOnReply": False,
                    "isActive": True,
                    "autoEnrollNewLeads": True,
                    "steps": [
                        {"id": "s1", "message": "Oi", "intervalValue": 5, "intervalUnit": "minutes"}
                    ],
                }
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        saved_flow = save_resp.get_json().get("flow", {})
        self.assertEqual(saved_flow.get("stopOnReply"), False)
        self.assertEqual(saved_flow.get("isActive"), True)
        self.assertEqual(saved_flow.get("autoEnrollNewLeads"), True)

        cockpit_app.CRM_FLOW_FILE.write_text(
            json.dumps({"name": "Legado", "steps": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        legacy_resp = self.client.get("/api/crm/bridge/flow")
        legacy_flow = legacy_resp.get_json().get("flow", {})
        self.assertEqual(legacy_flow.get("stopOnReply"), True)
        self.assertEqual(legacy_flow.get("isActive"), False)
        self.assertEqual(legacy_flow.get("autoEnrollNewLeads"), False)


if __name__ == "__main__":
    unittest.main()
