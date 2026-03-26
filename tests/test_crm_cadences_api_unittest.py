import json
import tempfile
import unittest
from pathlib import Path

import app as cockpit_app


class CrmCadencesApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.CRM_FLOW_FILE = tmp_path / "crm_flow.json"
        cockpit_app.CRM_CADENCES_FILE = tmp_path / "crm_cadences.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def _valid_cadence(self):
        return {
            "id": "cad-1",
            "name": "Cadência Teste",
            "isActive": True,
            "stopWhenReply": True,
            "audience": {"status": "Interessado", "label": "VIP", "origin": "LP"},
            "messages": [
                {"id": "m1", "message": "Olá", "intervalValue": 1, "intervalUnit": "hours"}
            ],
        }

    def test_create_requires_audience_and_message(self):
        invalid = {
            "cadence": {
                "name": "Inválida",
                "audience": {"status": "", "label": "", "origin": ""},
                "messages": [],
            }
        }
        resp = self.client.post("/api/crm/bridge/cadences", json=invalid)
        self.assertEqual(resp.status_code, 400)
        payload = resp.get_json()
        self.assertEqual(payload.get("error"), "validation_error")
        self.assertGreaterEqual(len(payload.get("errors", [])), 2)

    def test_crud_roundtrip(self):
        create = self.client.post("/api/crm/bridge/cadences", json={"cadence": self._valid_cadence()})
        self.assertEqual(create.status_code, 201)

        got = self.client.get("/api/crm/bridge/cadences")
        self.assertEqual(got.status_code, 200)
        items = got.get_json().get("cadences", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].get("name"), "Cadência Teste")

        update_payload = self._valid_cadence()
        update_payload["name"] = "Cadência Editada"
        update = self.client.put("/api/crm/bridge/cadences/cad-1", json={"cadence": update_payload})
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.get_json().get("cadence", {}).get("name"), "Cadência Editada")

        delete = self.client.delete("/api/crm/bridge/cadences/cad-1")
        self.assertEqual(delete.status_code, 200)
        remaining = delete.get_json().get("cadences", [])
        self.assertEqual(len(remaining), 0)

    def test_runtime_migration_from_legacy_single_flow(self):
        cockpit_app.CRM_FLOW_FILE.write_text(
            json.dumps(
                {
                    "name": "Fluxo Legado",
                    "isActive": True,
                    "stopOnReply": False,
                    "steps": [
                        {"id": "s1", "message": "Mensagem antiga", "intervalValue": 5, "intervalUnit": "minutes"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        resp = self.client.get("/api/crm/bridge/cadences")
        self.assertEqual(resp.status_code, 200)
        cadences = resp.get_json().get("cadences", [])
        self.assertEqual(len(cadences), 1)
        self.assertEqual(cadences[0].get("name"), "Fluxo Legado")
        self.assertEqual(cadences[0].get("isActive"), True)
        self.assertEqual(cadences[0].get("stopWhenReply"), False)
        self.assertEqual(len(cadences[0].get("messages", [])), 1)


if __name__ == "__main__":
    unittest.main()
