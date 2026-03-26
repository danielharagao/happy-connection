import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as cockpit_app


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        cockpit_app.DATA_DIR = tmp_path
        cockpit_app.CRM_INTERACTIONS_FILE = tmp_path / "crm_interactions.json"
        cockpit_app.CRM_LEAD_STATUS_FILE = tmp_path / "crm_lead_status.json"
        cockpit_app.CRM_LEAD_EVENTS_FILE = tmp_path / "crm_lead_events.json"
        cockpit_app.CRM_LEAD_NOTES_FILE = tmp_path / "crm_lead_notes.json"
        cockpit_app.CHAT_LINKS_FILE = tmp_path / "chat_links.json"
        cockpit_app.CHAT_LOG_INDEX_FILE = tmp_path / "chat_log_index.json"
        self.client = cockpit_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(cockpit_app, "_fetch_crm_overview")
    @patch.object(cockpit_app, "_chat_fetch_messages_from_baileys")
    @patch.object(cockpit_app, "_chat_build_conversations")
    @patch.object(cockpit_app, "_chat_baileys_status")
    def test_conversations_and_messages(self, mock_status, mock_convs, mock_msgs, mock_overview):
        mock_overview.return_value = ([{"id": 10, "name": "João", "phone": "+55 19 98888-7777"}], 1, None)
        mock_status.return_value = {"ok": True, "online": True, "state": "connected", "source": "baileys"}
        mock_convs.return_value = [
            {"id": "5519988887777", "name": "João", "lead": {"id": 10, "name": "João"}, "lastAtMs": 20, "lastAtLabel": "05:01", "lastMessage": "olá", "unreadCount": 0}
        ]
        mock_msgs.return_value = [
            {"id": "a", "conversationId": "5519988887777", "timestampMs": 10, "timestamp": "2026-03-14T05:00:00+00:00", "direction": "inbound", "text": "oi"},
            {"id": "b", "conversationId": "5519988887777", "timestampMs": 20, "timestamp": "2026-03-14T05:01:00+00:00", "direction": "outbound", "text": "olá"},
        ]

        resp = self.client.get("/api/chat/conversations")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(len(payload.get("items", [])), 1)
        self.assertEqual(payload["items"][0]["lead"]["id"], 10)
        self.assertTrue(payload.get("connection", {}).get("online"))

        thread = self.client.get("/api/chat/conversations/5519988887777/messages")
        self.assertEqual(thread.status_code, 200)
        t_payload = thread.get_json()
        self.assertEqual(len(t_payload.get("items", [])), 2)

    @patch.object(cockpit_app, "_fetch_crm_overview")
    @patch.object(cockpit_app, "_chat_fetch_messages_from_baileys")
    def test_messages_endpoint_uses_selected_jid(self, mock_msgs, mock_overview):
        mock_overview.return_value = ([], 0, None)
        mock_msgs.return_value = []
        resp = self.client.get("/api/chat/conversations/5511999990000%40s.whatsapp.net/messages")
        self.assertEqual(resp.status_code, 200)
        mock_msgs.assert_called_once_with("5511999990000@s.whatsapp.net", limit=500)

    @patch.object(cockpit_app, "_chat_apply_post_send_stage_transition")
    @patch.object(cockpit_app, "_baileys_request")
    def test_send_endpoint(self, mock_send, mock_post_action):
        mock_send.return_value = {"ok": True, "id": "msg-1", "to": "5519999991111@s.whatsapp.net"}
        mock_post_action.return_value = {"ok": True, "leadId": 10, "toStage": "Sem Resposta"}
        resp = self.client.post("/api/chat/send", json={"conversationId": "+55 19 99999-1111", "text": "Teste"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("conversationId"), "5519999991111@s.whatsapp.net")
        self.assertEqual(payload.get("postAction", {}).get("toStage"), "Sem Resposta")

    @patch.object(cockpit_app, "_chat_apply_post_send_stage_transition")
    @patch.object(cockpit_app, "_baileys_request")
    def test_send_endpoint_rejects_target_mismatch(self, mock_send, mock_post_action):
        mock_send.return_value = {"ok": True, "id": "msg-1", "to": "5519988404000@s.whatsapp.net"}
        resp = self.client.post("/api/chat/send", json={"conversationId": "+55 19 99999-1111", "text": "Teste"})
        self.assertEqual(resp.status_code, 502)
        payload = resp.get_json()
        self.assertIn("target_mismatch", str(payload.get("error") or ""))

    def test_chat_id_normalization_supports_jids_and_numeric(self):
        self.assertEqual(cockpit_app._chat_id_from_target("+55 (19) 99999-1111"), "5519999991111@s.whatsapp.net")
        self.assertEqual(cockpit_app._chat_id_from_target("551999991111@s.whatsapp.net"), "551999991111@s.whatsapp.net")
        self.assertEqual(cockpit_app._chat_id_from_target("123456@lid"), "123456@lid")
        self.assertEqual(cockpit_app._chat_id_from_target("12036302-123456@g.us"), "12036302-123456@g.us")

    def test_chat_match_lead_is_safe_and_no_suffix_false_positive(self):
        leads = [
            {"id": 1, "name": "A", "phone": "+55 19 99999-1111"},
            {"id": 2, "name": "B", "phone": "+55 11 88888-1111"},
        ]
        matched = cockpit_app._chat_match_lead_by_phone("5519999991111@s.whatsapp.net", leads)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.get("id"), 1)

        no_match = cockpit_app._chat_match_lead_by_phone("99991111@lid", leads)
        self.assertIsNone(no_match)

    def test_chat_target_from_item_uses_only_explicit_chat_identity(self):
        from_to_only = {"from": "5519988404000@s.whatsapp.net", "to": "5519999991111@s.whatsapp.net", "id": "ABCD"}
        self.assertEqual(cockpit_app._chat_target_from_item(from_to_only), "")

        with_chat_id = {"chatId": "5519999991111@s.whatsapp.net", "from": "5519988404000@s.whatsapp.net"}
        self.assertEqual(cockpit_app._chat_target_from_item(with_chat_id), "5519999991111@s.whatsapp.net")

        with_key_remote_jid = {"key": {"remoteJid": "123456@lid", "id": "XYZ"}}
        self.assertEqual(cockpit_app._chat_target_from_item(with_key_remote_jid), "123456@lid")

    @patch.object(cockpit_app, "_chat_baileys_status")
    def test_connection_endpoint(self, mock_status):
        mock_status.return_value = {"ok": True, "online": True, "state": "connected", "source": "baileys"}
        resp = self.client.get("/api/chat/connection")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("online"))

    @patch.object(cockpit_app, "_fetch_crm_overview")
    def test_link_lead(self, mock_overview):
        mock_overview.return_value = ([{"id": 42, "name": "Maria", "phone": "+5519999998888"}], 1, None)
        resp = self.client.post("/api/chat/link-lead", json={"conversationId": "5519999998888", "leadId": 42})
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("item", {}).get("leadId"), 42)

    @patch.object(cockpit_app, "_crm_request_with_retry")
    @patch.object(cockpit_app, "_fetch_crm_overview")
    def test_post_send_moves_to_sem_resposta_and_creates_system_note(self, mock_overview, mock_crm_update):
        mock_overview.return_value = ([{"id": 77, "name": "Andreza", "phone": "+55 19 99999-1111", "current_stage": "Novos"}], 1, None)
        out = cockpit_app._chat_apply_post_send_stage_transition("5519999991111@s.whatsapp.net", {})

        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("toStage"), "Sem Resposta")
        self.assertEqual(mock_crm_update.call_count, 1)

        notes = cockpit_app._load_crm_lead_notes()
        self.assertEqual(len(notes), 1)
        self.assertEqual(int(notes[0].get("leadId") or 0), 77)
        self.assertIn("Mudança automática de estágio", notes[0].get("content") or "")

    @patch.object(cockpit_app, "_crm_request_with_retry")
    @patch.object(cockpit_app, "_fetch_crm_overview")
    def test_post_send_does_not_override_closed_stage(self, mock_overview, mock_crm_update):
        mock_overview.return_value = ([{"id": 88, "name": "Aluno", "phone": "+55 19 98888-0000", "current_stage": "Fechado"}], 1, None)
        out = cockpit_app._chat_apply_post_send_stage_transition("5519988880000@s.whatsapp.net", {})

        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "protected_closed_stage")
        self.assertEqual(mock_crm_update.call_count, 0)
        self.assertEqual(cockpit_app._load_crm_lead_notes(), [])


if __name__ == "__main__":
    unittest.main()
