import json

def deduplicate_leads(parsed):
    if not isinstance(parsed, dict) or "leads" not in parsed:
        return parsed

    leads = parsed["leads"]
    if not isinstance(leads, list):
        return parsed

    # Intelligent deduplication: merge by email/phone
    # We will build a map of key -> list of leads
    
    # We assign a deduplication key based on email first, then phone.
    # To properly merge, we collect all related leads.
    
    merged_map = {}
    
    # Sort leads by id (or some logic) so the lowest or highest ID is the base.
    # The requirement doesn't specify which ID to keep, let's keep the highest ID (most recent).
    leads.sort(key=lambda x: int(x.get("id") or 0), reverse=True)
    
    for lead in leads:
        if not isinstance(lead, dict):
            continue
            
        email = str(lead.get("email") or "").strip().lower()
        phone = str(lead.get("phone") or "").strip()
        phone_digits = ''.join(c for c in phone if c.isdigit())
        
        # Determine the key. We can link by email or phone.
        # If email exists, it's the primary key. If not, phone.
        # Wait, what if Lead A has email X and phone Y, and Lead B has only phone Y?
        # A simple graph approach is best, but a greedy map is easier:
        
        match_key = None
        if email and email in merged_map:
            match_key = email
        elif phone_digits and phone_digits in merged_map:
            match_key = phone_digits
        else:
            match_key = email if email else (phone_digits if phone_digits else f"id_{lead.get('id')}")
            
        if match_key not in merged_map:
            # We keep the first one we see (which is the highest ID because we sorted reverse)
            merged_map[match_key] = lead.copy()
            # We also add its identifiers to the map so future ones match
            if email: merged_map[email] = merged_map[match_key]
            if phone_digits: merged_map[phone_digits] = merged_map[match_key]
            
            # Keep a track of merged IDs for the timeline 360
            merged_map[match_key]["_merged_ids"] = [lead.get("id")]
        else:
            base_lead = merged_map[match_key]
            # Merge signups
            base_lead["signup_count"] = int(base_lead.get("signup_count") or 1) + int(lead.get("signup_count") or 1)
            if lead.get("id") not in base_lead["_merged_ids"]:
                base_lead["_merged_ids"].append(lead.get("id"))
                
    # Return unique values
    unique_leads = []
    seen_ids = set()
    for l in merged_map.values():
        if l.get("id") not in seen_ids:
            seen_ids.add(l.get("id"))
            unique_leads.append(l)
            
    parsed["leads"] = unique_leads
    return parsed
