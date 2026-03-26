import os

file_path = "/root/.openclaw/workspace/apps/openclaw-cockpit/app.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

import re

# Find the function
match = re.search(r'def _sanitize_kanban_task_payload.*?return \{', content, re.DOTALL)
if match:
    old_code = match.group(0)
    new_code = old_code.replace('return {', '''
    title = str(payload.get("title") or "").strip()
    assignee = str(payload.get("assigneeAgentId") or "").strip()
    
    # We only raise ValueError if it's a new task (id was generated) 
    # OR if we explicitly enforce it for updates too.
    # The test calls POST /api/kanban/tasks, which does not pass an id usually.
    if not payload.get("id"):
        if not title:
            raise ValueError("title is required")
        if not assignee:
            raise ValueError("assigneeAgentId is required")

    return {''')

    content = content.replace(old_code, new_code)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
