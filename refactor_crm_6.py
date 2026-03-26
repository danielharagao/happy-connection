file_path = "/root/.openclaw/workspace/apps/openclaw-cockpit/app.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

import re

# In app.py:
match = re.search(r'def _sanitize_kanban_task_payload.*?return \{', content, re.DOTALL)
if match:
    old_code = match.group(0)
    # Re-write the validation block properly
    # Check if there's already our added block
    if "raise ValueError" in old_code:
        # It's already there, replace the whole function
        pass
    else:
        # Not there, shouldn't happen
        pass

# Let's just find _sanitize_kanban_task_payload entirely and rewrite it
func_match = re.search(r'def _sanitize_kanban_task_payload\(.*?\).*?return \{', content, re.DOTALL)
if func_match:
    old = func_match.group(0)
    new_code = '''def _sanitize_kanban_task_payload(payload: dict[str, Any], existing_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_id = str(payload.get("id") or "").strip()
    if not task_id:
        idx = len(existing_tasks) + 1
        task_id = f"task-{idx}"

    title = str(payload.get("title") or "").strip()
    assignee = str(payload.get("assigneeAgentId") or "").strip()

    if not payload.get("id"):
        if not title:
            raise ValueError("title is required")
        if not assignee:
            raise ValueError("assigneeAgentId is required")

    if assignee and not AGENT_ID_RE.match(assignee):
        raise ValueError("invalid assigneeAgentId format")

    status = str(payload.get("status") or "").strip()
    if status not in KANBAN_STATUSES:
        status = "To do"

    priority = str(payload.get("priority") or "").strip()
    if priority not in ["P0", "P1", "P2"]:
        priority = "P1"

    now = datetime.now(timezone.utc).isoformat()
    return {'''
    content = content.replace(old, new_code)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

