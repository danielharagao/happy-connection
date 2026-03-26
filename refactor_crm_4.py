import re

with open("app.py", "r") as f:
    content = f.read()

new_retry_methods = """
def _crm_request_with_retry(req: Request, max_attempts: int = 3, timeout: float = 5.0) -> tuple[bytes, int, dict[str, str]]:
    import time
    last_exc = None
    for attempt in range(max_attempts):
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                headers = {k: v for k, v in resp.headers.items()}
                return body, int(getattr(resp, "status", 200)), headers
        except HTTPError as exc:
            code = int(getattr(exc, "code", 500))
            if code < 500 and code != 429:
                raise exc
            last_exc = exc
        except URLError as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc

        if attempt < max_attempts - 1:
            time.sleep(0.5 * (2 ** attempt))

    raise last_exc
"""

# Insert before _fetch_crm_overview
content = content.replace("def _fetch_crm_overview", new_retry_methods + "\n\ndef _fetch_crm_overview")

# Refactor _fetch_crm_overview
old_fetch = """def _fetch_crm_overview() -> tuple[list[dict[str, Any]], str | None]:
    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/overview")
    req = Request(upstream_url, method="GET", headers=_crm_auth_headers())
    try:
        with urlopen(req, timeout=5) as resp:
            parsed = json.loads((resp.read() or b"{}").decode("utf-8", errors="replace"))
    except Exception as exc:
        return [], str(exc)"""

new_fetch = """def _fetch_crm_overview() -> tuple[list[dict[str, Any]], str | None]:
    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/overview")
    req = Request(upstream_url, method="GET", headers=_crm_auth_headers())
    try:
        body, status, _ = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        parsed = json.loads((body or b"{}").decode("utf-8", errors="replace"))
    except Exception as exc:
        return [], str(exc)"""

content = content.replace(old_fetch, new_fetch)

# Add failed queue endpoints
failed_queue_endpoints = """
@app.get("/api/crm/bridge/failed-events")
def api_crm_failed_events_list():
    items = _load_crm_failed_events()
    return jsonify({"ok": True, "items": items})

@app.post("/api/crm/bridge/failed-events/<event_id>/retry")
def api_crm_failed_events_retry(event_id: str):
    items = _load_crm_failed_events()
    event = next((i for i in items if i["id"] == event_id), None)
    if not event:
        return jsonify({"error": "event not found"}), 404

    req = Request(event["path"], method=event["method"], headers=_crm_auth_headers())
    if event["payload"]:
        req.data = json.dumps(event["payload"]).encode("utf-8")
        req.headers["Content-Type"] = "application/json"

    try:
        _crm_request_with_retry(req, max_attempts=1, timeout=5.0)
        items = [i for i in items if i["id"] != event_id]
        _save_crm_failed_events(items)
        return jsonify({"ok": True})
    except Exception as exc:
        event["retries"] += 1
        event["error"] = str(exc)
        _save_crm_failed_events(items)
        return jsonify({"error": str(exc)}), 500
"""

# Append endpoints before `def _fetch_crm_overview` since they are api routes
content = content.replace("def _fetch_crm_overview", failed_queue_endpoints + "\n\ndef _fetch_crm_overview")


with open("app.py", "w") as f:
    f.write(content)

print("Done refactor retry + queue endpoints")
