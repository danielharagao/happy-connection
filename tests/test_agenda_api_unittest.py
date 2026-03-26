import tempfile
import unittest
from pathlib import Path

import app as cockpit_app


class AgendaApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.AGENDA_EVENTS_FILE = tmp_path / "agenda_events.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_get_and_patch_agenda_item(self):
        create = self.client.post(
            "/api/agenda",
            json={
                "date": "2099-03-14",
                "time": "09:30",
                "type": "call",
                "leadName": "Maria",
                "leadPhone": "+5519999998888",
            },
        )
        self.assertEqual(create.status_code, 201)
        created = create.get_json()["item"]
        self.assertEqual(created["status"], "pendente")

        get_resp = self.client.get("/api/agenda?date=2099-03-14")
        self.assertEqual(get_resp.status_code, 200)
        data = get_resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["leadName"], "Maria")

        patch_resp = self.client.patch(f"/api/agenda/{created['id']}", json={"status": "concluído", "time": "10:00"})
        self.assertEqual(patch_resp.status_code, 200)
        patched = patch_resp.get_json()["item"]
        self.assertEqual(patched["status"], "concluido")
        self.assertEqual(patched["time"], "10:00")


if __name__ == "__main__":
    unittest.main()
