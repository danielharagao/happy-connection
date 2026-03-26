import json

def _crm_intelligent_deduplication(parsed: dict) -> dict:
    if not isinstance(parsed, dict) or "leads" not in parsed:
        return parsed

    leads = parsed.get("leads", [])
    if not isinstance(leads, list):
        return parsed

    # Sort leads by ID descending (so we keep the highest ID as the primary)
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
        
        match_key = None
        if email and email in merged_map:
            match_key = email
        elif phone_digits and phone_digits in merged_map:
            match_key = phone_digits
        else:
            match_key = email if email else (phone_digits if phone_digits else f"id_{lead.get('id')}")
            
        if match_key not in merged_map:
            lead_copy = lead.copy()
            lead_copy["_merged_ids"] = [lead.get("id")]
            merged_map[match_key] = lead_copy
            if email:
                merged_map[email] = lead_copy
            if phone_digits:
                merged_map[phone_digits] = lead_copy
        else:
            base_lead = merged_map[match_key]
            # Sum up signups
            base_lead["signup_count"] = int(base_lead.get("signup_count") or 1) + int(lead.get("signup_count") or 1)
            # Add to merged IDs for timeline 360 gathering
            if lead.get("id") not in base_lead["_merged_ids"]:
                base_lead["_merged_ids"].append(lead.get("id"))

    # unique primary leads
    unique_leads = []
    seen_ids = set()
    for l in merged_map.values():
        if l.get("id") not in seen_ids:
            seen_ids.add(l.get("id"))
            unique_leads.append(l)

    parsed["leads"] = unique_leads
    return parsed
