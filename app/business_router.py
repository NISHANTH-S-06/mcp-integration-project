"""
Smart Business Query Router for MCP Data Assistant.
Parses db_profile.json to identify and rank relevant database tables for business entities.
"""
import json
import re
from pathlib import Path
from app import config
ENTITY_KEYWORDS = {
    "customer": [
        "customer", "cust", "client", "party", "buyer", "patient",
        # Business name suffixes that almost always mean a customer
        "agency", "agencies", "traders", "trader", "stores", "store",
        "enterprises", "enterprise", "industries", "industry",
        "distributors", "distributor", "wholesaler", "wholesalers",
        "mart", "shop", "pharmacy", "pharmaceuticals", "ayurvedic",
        "medical", "medicals", "corporation", "corp", "co"
    ],
    "invoice": ["invoice", "inv", "bill", "sales invoice"],
    "supplier": ["supplier", "vendor"],
    "item": ["item", "product", "material", "stock"],
    "purchase": ["purchase", "po", "purchase order"],
    "payment": ["payment", "paid", "balance", "receipt"],
    "sales": ["sales", "sale"],
    "company": ["company", "companies", "our company", "my company", "organization"]
}

PRIMARY_ENTITY_KEYWORDS = {
    "customer": ["customer", "cust", "client", "party", "buyer", "patient"],
    "invoice": ["invoice", "inv", "bill", "sales invoice"],
    "supplier": ["supplier", "vendor"],
    "item": ["item", "product", "material", "stock"],
    "purchase": ["purchase", "po", "purchase order"],
    "payment": ["payment", "paid", "balance", "receipt"],
    "sales": ["sales", "sale"],
    "company": ["company", "companies", "our company", "my company", "organization"]
}

# pyrefly: ignore [invalid-annotation]
def detect_entity(query: str) -> str or None:
    """Detect if query mentions any known business entity."""
    q_lower = query.lower().strip("?.!,;\"'“” ")
    
    # 1. First check primary keywords (exact word match)
    matched_primary = []
    for entity, keywords in PRIMARY_ENTITY_KEYWORDS.items():
        for kw in keywords:
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, q_lower):
                matched_primary.append((entity, len(kw)))
                
    if matched_primary:
        matched_primary.sort(key=lambda x: x[1], reverse=True)
        return matched_primary[0][0]
        
    # 2. Check all keywords including suffixes (exact word match)
    matched_entities = []
    for entity, keywords in ENTITY_KEYWORDS.items():
        for kw in keywords:
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, q_lower):
                matched_entities.append((entity, len(kw)))
                
    if matched_entities:
        matched_entities.sort(key=lambda x: x[1], reverse=True)
        return matched_entities[0][0]
        
    # 3. Substring fallback for primary keywords
    for entity, keywords in PRIMARY_ENTITY_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                return entity
                
    # 4. Substring fallback for all keywords
    for entity, keywords in ENTITY_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                return entity
                
    return None

def get_ranked_tables_for_entity(entity: str) -> list:
    """Load db_profile.json, match and rank tables for the given entity."""
    profile_path = config.BASE_DIR / "data" / "registry" / "db_profile.json"
    if not profile_path.exists():
        return []
        
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return []
        
    tables = profile.get("tables", [])
    keywords = ENTITY_KEYWORDS.get(entity, [])
    
    ranked_tables = []
    for t in tables:
        table_name = t.get("table_name", "")
        columns = t.get("columns", [])
        record_count = t.get("record_count", 0)
        
        table_name_lower = table_name.lower()
        
        # Calculate Score
        score = 0.0
        
        # 1. Table name match
        # Exact table match to keyword or plural of keyword
        exact_match = False
        for kw in keywords:
            if table_name_lower == kw or table_name_lower == kw + "s":
                exact_match = True
                break
        
        if exact_match:
            score += 100.0
            
        # Parse ERP prefixes and suffixes to find base table name
        base_name = table_name_lower
        for prefix in ["m_", "s_", "t_", "p_", "f_", "i_", "hr_"]:
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
                break
        for suffix in ["_hdr_t", "_dtl_t", "_upload_t", "_hdr", "_dtl", "_temp", "_t"]:
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)]
                break
                
        # Base name exact match
        base_exact = False
        for kw in keywords:
            if base_name == kw or base_name == kw + "s":
                base_exact = True
                break
                
        if base_exact:
            score += 80.0
        else:
            # Contains keyword as substring
            contains_kw = False
            for kw in keywords:
                if kw in table_name_lower:
                    contains_kw = True
                    break
            if contains_kw:
                score += 40.0
                
        # 2. Column name match
        col_score = 0.0
        for col in columns:
            col_lower = col.lower()
            col_exact = False
            for kw in keywords:
                if col_lower == kw or col_lower == kw + "_id" or col_lower == kw + "_name" or col_lower == kw + "_code" or col_lower == kw + "_number" or col_lower == kw + "_no":
                    col_exact = True
                    break
            if col_exact:
                col_score += 15.0
            else:
                col_contains = False
                for kw in keywords:
                    if kw in col_lower:
                        col_contains = True
                        break
                if col_contains:
                    col_score += 8.0
        # Cap column match score at 30 points
        score += min(col_score, 30.0)
        
        # 3. Row count > 0
        if record_count > 0:
            score += 25.0
            
        # 4. Known ERP prefix/suffix
        has_prefix = any(table_name_lower.startswith(p) for p in ["m_", "s_", "t_", "p_", "f_", "i_", "hr_"])
        has_suffix = any(table_name_lower.endswith(s) for s in ["_t", "_hdr", "_dtl", "_temp"])
        if has_prefix or has_suffix:
            score += 10.0
            
        # 5. Header / Detail preference
        is_hdr = any(x in table_name_lower for x in ["hdr", "header"])
        is_dtl = any(x in table_name_lower for x in ["dtl", "detail", "line"])
        is_master = table_name_lower.startswith("m_") or "master" in table_name_lower
        
        if entity in ["invoice", "purchase", "payment", "sales"]:
            if is_hdr:
                score += 30.0
            elif is_dtl:
                score -= 20.0

        # 6. Sales vs Purchase invoice preference
        # When user says "invoice" (not "purchase invoice"), prefer sales tables (s_ prefix)
        # over purchase/payable tables (p_ prefix)
        if entity == "invoice":
            if table_name_lower.startswith("s_"):
                score += 80.0   # Strong boost for sales tables
            elif table_name_lower.startswith("p_"):
                score -= 60.0   # Heavy penalty for purchase tables
        elif entity in ["customer", "supplier"]:
            if is_master:
                score += 15.0
            if is_dtl:
                score -= 20.0
        elif entity == "item":
            if is_master:
                score += 15.0
                
        if score > 0:
            ranked_tables.append({
                "table_name": table_name,
                "record_count": record_count,
                "score": score,
                "columns": columns,
                "searchable_columns": t.get("searchable_columns", []),
                "primary_keys": t.get("primary_keys", [])
            })
            
    # Sort tables by score descending, and record count descending
    ranked_tables.sort(key=lambda x: (x["score"], x["record_count"]), reverse=True)
    return ranked_tables
