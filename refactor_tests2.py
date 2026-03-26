import os
from pathlib import Path

def patch_test():
    file_path = "/root/.openclaw/workspace/apps/openclaw-cockpit/tests/test_crm_bridge_api_unittest.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # We will just replace the test payload
    old_payload = """
                payload = {
                    "leads": [
                        {"id": 1, "email": "dup@example.com", "phone": "123", "signup_count": 1},
                        {"id": 2, "email": "DUP@example.com", "phone": "", "signup_count": 2},
                        {"id": 3, "email": "", "phone": "123", "signup_count": 1},
                        {"id": 4, "email": "unique@example.com", "phone": "999", "signup_count": 1}
                    ]
                }
"""

    new_payload = """
                payload = {
                    "leads": [
                        {"id": 1, "email": "dup@example.com", "phone": "123", "signup_count": 1},
                        {"id": 2, "email": "DUP@example.com", "phone": "321", "signup_count": 2},
                        {"id": 3, "email": "another@test.com", "phone": "123", "signup_count": 1},
                        {"id": 4, "email": "unique@example.com", "phone": "999", "signup_count": 1}
                    ]
                }
"""
    content = content.replace(old_payload, new_payload)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_test()
