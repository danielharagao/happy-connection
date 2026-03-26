import os

file_path = "/root/.openclaw/workspace/apps/openclaw-cockpit/tests/test_crm_bridge_api_unittest.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("self.assertEqual(len(leads), 2)", "self.assertEqual(len(leads), 2)") # wait, it was 2!

test_func = """    def test_crm_proxy_intelligent_deduplication(self):
        class _Resp:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                payload = {
                    "leads": [
                        {"id": 1, "email": "dup@example.com", "phone": "123", "signup_count": 1},
                        {"id": 2, "email": "DUP@example.com", "phone": "555", "signup_count": 2},
                        {"id": 3, "email": "other@example.com", "phone": "123", "signup_count": 1},
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
        
        dup_email = next((l for l in leads if l["email"].lower() == "dup@example.com"), None)
        unique_lead = next((l for l in leads if l["email"] == "unique@example.com"), None)
        
        self.assertEqual(dup_email["id"], 2) # 2 merged with 1
        self.assertEqual(dup_email["signup_count"], 4) # 1 merged with 3, but wait!
"""

# Let's write the test accurately instead of regex replaces.
import re
new_test = """    def test_crm_proxy_intelligent_deduplication(self):
        class _Resp:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                payload = {
                    "leads": [
                        {"id": 1, "email": "dup@example.com", "phone": "123", "signup_count": 1},
                        {"id": 2, "email": "DUP@example.com", "phone": "555", "signup_count": 2},
                        {"id": 3, "email": "other@example.com", "phone": "123", "signup_count": 1},
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
        
        self.assertEqual(dup_lead["id"], 3) # Wait, it sorts descending. ID 4 is first, then 3, then 2, then 1.
        self.assertEqual(dup_lead["signup_count"], 4)
        
        self.assertEqual(unique_lead["id"], 4)
        self.assertEqual(unique_lead["signup_count"], 1)"""

with open(file_path, "w", encoding="utf-8") as f:
    # Just replace the whole method body with correct expectations
    pass
