import os
from pathlib import Path

def add_tests():
    file_path = "/root/.openclaw/workspace/apps/openclaw-cockpit/tests/test_crm_bridge_api_unittest.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_test = """
    def test_crm_proxy_intelligent_deduplication(self):
        class _Resp:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                payload = {
                    "leads": [
                        {"id": 1, "email": "dup@example.com", "phone": "123", "signup_count": 1},
                        {"id": 2, "email": "DUP@example.com", "phone": "", "signup_count": 2},
                        {"id": 3, "email": "", "phone": "123", "signup_count": 1},
                        {"id": 4, "email": "unique@example.com", "phone": "999", "signup_count": 1}
                    ]
                }
                import json
                return json.dumps(payload).encode("utf-8")

        with patch.object(cockpit_app, "urlopen", return_value=_Resp()) as mocked_open:
            resp = self.client.get("/api/crm/bridge/proxy/api/crm/overview")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        leads = body["leads"]
        self.assertEqual(len(leads), 2)
        
        dup_lead = next(l for l in leads if l["email"].lower() == "dup@example.com")
        unique_lead = next(l for l in leads if l["email"] == "unique@example.com")
        
        self.assertEqual(dup_lead["id"], 3) # Highest ID is kept
        self.assertEqual(dup_lead["signup_count"], 4)
        
        self.assertEqual(unique_lead["id"], 4)
        self.assertEqual(unique_lead["signup_count"], 1)

    def test_crm_proxy_timeline_merge(self):
        # First request to overview populates CRM_MERGED_MAP
        class _OverviewResp:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return b'{"leads": [{"id": 10, "email": "a@a.com"}, {"id": 11, "email": "a@a.com"}]}'
        
        with patch.object(cockpit_app, "urlopen", return_value=_OverviewResp()):
            self.client.get("/api/crm/bridge/proxy/api/crm/overview")
            
        # Second request to lead/11 should trigger a sub-request to lead/10 to merge timelines
        class _LeadResp:
            status = 200
            headers = {}
            def __init__(self, target_id):
                self.target_id = target_id
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                import json
                if "11" in self.target_id:
                    return json.dumps({"id": 11, "timeline": [{"event_at": "2026-03-01", "event_type": "seen_11"}]}).encode("utf-8")
                else:
                    return json.dumps({"id": 10, "timeline": [{"event_at": "2026-03-02", "event_type": "seen_10"}]}).encode("utf-8")

        def mocked_urlopen(req, timeout=None):
            return _LeadResp(req.full_url)
            
        with patch.object(cockpit_app, "urlopen", side_effect=mocked_urlopen):
            resp = self.client.get("/api/crm/bridge/proxy/api/crm/lead/11")
            
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        timeline = body.get("timeline", [])
        self.assertEqual(len(timeline), 2)
        # Dates should be descending
        self.assertEqual(timeline[0]["event_type"], "seen_10")
        self.assertEqual(timeline[1]["event_type"], "seen_11")

"""

    content = content.replace("if __name__ == \"__main__\":", new_test + "\nif __name__ == \"__main__\":")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

add_tests()
