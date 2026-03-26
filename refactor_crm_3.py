import json

def apply_patch(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find where to inject the deduplication function
    dedup_code = """
CRM_MERGED_MAP: dict[str, list[str]] = {}

def _crm_intelligent_deduplication(parsed: dict) -> dict:
    global CRM_MERGED_MAP
    if not isinstance(parsed, dict) or "leads" not in parsed:
        return parsed
    leads = parsed.get("leads", [])
    if not isinstance(leads, list):
        return parsed

    try:
        leads.sort(key=lambda x: int(x.get("id") or 0), reverse=True)
    except Exception:
        pass

    merged_map = {}
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        email = str(lead.get("email") or "").strip().lower()
        phone = str(lead.get("phone") or "").strip()
        phone_digits = "".join(c for c in phone if c.isdigit())
        
        match_key = email if email else (phone_digits if phone_digits else f"id_{lead.get('id')}")
        if email and email in merged_map:
            match_key = email
        elif phone_digits and phone_digits in merged_map:
            match_key = phone_digits
            
        if match_key not in merged_map:
            lead_copy = lead.copy()
            lead_copy["_merged_ids"] = [str(lead.get("id"))]
            merged_map[match_key] = lead_copy
            if email:
                merged_map[email] = lead_copy
            if phone_digits:
                merged_map[phone_digits] = lead_copy
        else:
            base_lead = merged_map[match_key]
            base_lead["signup_count"] = int(base_lead.get("signup_count") or 1) + int(lead.get("signup_count") or 1)
            lid = str(lead.get("id"))
            if lid not in base_lead["_merged_ids"]:
                base_lead["_merged_ids"].append(lid)

    unique_leads = []
    seen_ids = set()
    CRM_MERGED_MAP.clear()
    for l in merged_map.values():
        lid = str(l.get("id"))
        if lid not in seen_ids:
            seen_ids.add(lid)
            unique_leads.append(l)
            CRM_MERGED_MAP[lid] = l.get("_merged_ids", [])

    parsed["leads"] = unique_leads
    return parsed

"""
    if "def _crm_intelligent_deduplication" not in content:
        content = content.replace("CRM_ALLOWED_PROXY_PREFIXES = (\"api/crm/overview\", \"api/crm/lead/\")\n", "CRM_ALLOWED_PROXY_PREFIXES = (\"api/crm/overview\", \"api/crm/lead/\")\n" + dedup_code)

    proxy_mod = """
    try:
        body_resp, status_code, headers = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)

        # Intelligent Deduplication Intercept
        if clean == "api/crm/overview" and status_code == 200:
            parsed = json.loads(body_resp.decode("utf-8", errors="replace"))
            parsed = _crm_intelligent_deduplication(parsed)
            body_resp = json.dumps(parsed).encode("utf-8")
            if "Content-Length" in headers:
                headers["Content-Length"] = str(len(body_resp))
        elif clean.startswith("api/crm/lead/") and status_code == 200:
            lead_id_str = clean.split("/")[-1]
            absorbed_ids = CRM_MERGED_MAP.get(lead_id_str, [])
            if len(absorbed_ids) > 1:
                parsed_lead = json.loads(body_resp.decode("utf-8", errors="replace"))
                timeline = parsed_lead.get("timeline", [])
                for dup_id in absorbed_ids:
                    if dup_id == lead_id_str: continue
                    dup_req = Request(urljoin(f"{CRM_BASE_URL}/", f"api/crm/lead/{dup_id}"), method="GET", headers=_crm_auth_headers())
                    try:
                        dup_body, d_status, _ = _crm_request_with_retry(dup_req, max_attempts=3, timeout=5.0)
                        if d_status == 200:
                            dup_parsed = json.loads(dup_body.decode("utf-8", errors="replace"))
                            timeline.extend(dup_parsed.get("timeline", []))
                    except Exception:
                        pass
                timeline.sort(key=lambda x: str(x.get("event_at") or x.get("createdAt") or ""), reverse=True)
                parsed_lead["timeline"] = timeline
                body_resp = json.dumps(parsed_lead).encode("utf-8")
                if "Content-Length" in headers:
                    headers["Content-Length"] = str(len(body_resp))

        return ("""

    content = content.replace("""
    try:
        body_resp, status_code, headers = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        return (""", proxy_mod)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

apply_patch("/root/.openclaw/workspace/apps/openclaw-cockpit/app.py")
