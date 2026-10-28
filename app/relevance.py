"""
Relevance Ranking module for MCP Data Assistant.
Evaluates query-record match scores with domain penalties and filters.
"""
import re
import json
from typing import Dict, Any, List, Tuple

MIN_THRESHOLD = 45.0

ALIAS_MAP = {
    "customer id": ["customer_id", "customer_code", "client_id", "party_code", "buyer_code"],
    "invoice no": ["invoice_number", "inv_no", "bill_no", "document_no", "invoice number"],
    "po no": ["po_number", "purchase_order_no", "order_no", "po number"],
    "supplier code": ["supplier_code", "vendor_code"],
    "company name": ["company", "company_name", "customer_name", "supplier_name"]
}

def expand_query_with_aliases(q: str) -> str:
    expanded = q.lower()
    for standard, aliases in ALIAS_MAP.items():
        for alias in aliases:
            if alias in expanded:
                expanded += " " + standard + " " + " ".join(aliases)
                break
    return expanded

def extract_fields(hit: dict) -> dict:
    """Normalize and extract metadata fields from a DB or Dataset candidate hit."""
    company = None
    doc_type = None
    field_name = ""
    aliases = []
    mapped_to = ""
    
    if "record" in hit and isinstance(hit["record"], dict):
        # Dataset hit shape
        company = hit.get("company")
        doc_type = hit.get("document_type")
        rec = hit["record"]
        field_name = rec.get("field_name") or rec.get("name") or ""
        raw_aliases = rec.get("aliases") or []
        if isinstance(raw_aliases, str):
            aliases = [a.strip() for a in raw_aliases.split("|") if a.strip()]
        elif isinstance(raw_aliases, list):
            aliases = raw_aliases
        mapped_to = rec.get("mapped_to") or ""
    else:
        # Database hit shape
        company = hit.get("company_code") or hit.get("company") or hit.get("code")
        doc_type = hit.get("document_type")
        field_name = hit.get("field_name") or hit.get("name") or hit.get("matched_column") or ""
        raw_aliases = hit.get("aliases") or ""
        if isinstance(raw_aliases, str):
            aliases = [a.strip() for a in raw_aliases.split("|") if a.strip()]
        elif isinstance(raw_aliases, list):
            aliases = raw_aliases
        mapped_to = hit.get("mapped_to") or ""

    return {
        "company": str(company or "").strip(),
        "document_type": str(doc_type or "").strip(),
        "field_name": str(field_name).strip(),
        "aliases": aliases,
        "mapped_to": str(mapped_to).strip()
    }


def score_hit(hit: dict, query: str) -> float:
    """Calculate the relevance score for a single hit against a query."""
    # Clean natural language prefixes to isolate search terms
    clean_query = query.lower()
    prefixes = [
        "search customer ", "search invoice ", "search supplier ", "search item ",
        "search for customer ", "search for invoice ", "search for supplier ", "search for item ",
        "search database for ", "search records for ", "search for ", "find ", "show "
    ]
    for p in prefixes:
        if clean_query.startswith(p):
            query = query[len(p):].strip()
            break

    fields = extract_fields(hit)
    q = expand_query_with_aliases(query.lower().strip())
    score = 0.0
    
    # Helper to clean strings for normalized comparison (removing spaces, underscores, dashes)
    def clean(s: str) -> str:
        return "".join(c for c in s.lower() if c.isalnum())

    q_clean = clean(q)
    f_name_lower = fields["field_name"].lower()
    
    # 1. exact column/field match: +50 (Exact field name string appears in the query)
    if f_name_lower and (f_name_lower in q or clean(f_name_lower) in q_clean):
        score += 50.0
        
    # 2. alias exact match: +40 (Any alias string appears in the query)
    for alias in fields["aliases"]:
        a_lower = alias.lower()
        if a_lower and (a_lower in q or clean(a_lower) in q_clean):
            score += 40.0
            break

    # 3. table match: +30
    t_name = (hit.get("table") or hit.get("_table") or "").lower()
    if t_name:
        if t_name in q or clean(t_name) in q_clean or q_clean in clean(t_name):
            score += 30.0
        else:
            words = re.findall(r"[a-z0-9]+", t_name)
            if any(w in q or clean(w) in q_clean or q_clean in clean(w) or (len(w) > 4 and w[:4] in q) for w in words if len(w) > 2):
                score += 30.0

    # 4. company/doc match: +25
    c_upper = fields["company"].upper()
    if c_upper and c_upper != "ALL" and c_upper.lower() in q:
        score += 25.0
        
    dt_lower = fields["document_type"].lower()
    if dt_lower and dt_lower in q:
        score += 25.0
    elif "invoice" in q and "invoice" in dt_lower:
        score += 25.0
    elif ("po" in q or "purchase" in q) and ("purchase order" in dt_lower or "po" in dt_lower):
        score += 25.0

    # 5. generic word overlap only: max 20
    q_words = set(re.findall(r"[a-z0-9_]+", q))
    hit_str = json.dumps(hit).lower() if isinstance(hit, dict) else str(hit).lower()
    hit_words = set(re.findall(r"[a-z0-9_]+", hit_str))
    common = q_words.intersection(hit_words)
    stop_words = {
        "show", "list", "get", "find", "what", "which", "where", "when", "how",
        "why", "is", "are", "the", "a", "an", "for", "of", "in", "on", "at",
        "to", "and", "or", "not", "me", "my", "can", "do", "does"
    }
    meaningful = common - stop_words
    if meaningful:
        overlap_score = len(meaningful) * 5.0
        score += min(overlap_score, 20.0)
            
    # 6. unrelated company/document type wrong domain penalty:
    is_invoice_query = "invoice" in q or "rechnung" in q
    is_po_query = "po" in q or "purchase" in q or "poprint" in q
    
    if is_invoice_query and not is_po_query:
        if c_upper == "POPRINT" or "purchase" in dt_lower or "po" in dt_lower:
            score -= 30.0
            
    if is_po_query and not is_invoice_query:
        if c_upper == "GLS" or "invoice" in dt_lower or "rechnung" in dt_lower:
            score -= 30.0

    # 7. Value match boost (ensure that records containing the search query in their actual data columns are not hidden)
    # Strip common noise words and suffixes from the search query for value matching
    _RELEVANCE_NOISE_WORDS = {
        "how", "much", "many", "have", "show", "tell", "give", "what", "get",
        "find", "list", "search", "ids", "id", "it", "its", "is", "are", "the", "a",
        "an", "and", "or", "for", "of", "in", "on", "at", "to", "by", "do",
        "does", "can", "check", "please", "me", "my", "us", "our", "you",
        "your", "we", "they", "them", "about", "with", "from", "like",
        "over", "out", "up", "down", "this", "that", "these", "those",
        "count", "total", "num", "all", "any", "names", "name", "details", "detail",
        "codes", "code", "numbers", "number", "no", "nos",
        "there", "their", "whose", "his", "her", "here", "who", "whom", 
        "where", "why", "when", "print", "view", "display",
        "info", "information", "record", "records", "data", "database", "db"
    }
    q_words = [w for w in q.split() if w not in _RELEVANCE_NOISE_WORDS]
    q_cleaned = " ".join(q_words) if q_words else q

    val_matched = False
    # Check if any meaningful query word is contained in the record values
    for field in ["value", "extracted_value"]:
        val = hit.get(field)
        if val:
            val_str = str(val).lower()
            if q_cleaned in val_str or val_str in q_cleaned or any(w in val_str for w in q_words if len(w) >= 3):
                val_matched = True
                break
            
    if not val_matched and "record" in hit and isinstance(hit["record"], dict):
        for val in hit["record"].values():
            if val:
                val_str = str(val).lower()
                if q_cleaned in val_str or val_str in q_cleaned or any(w in val_str for w in q_words if len(w) >= 3):
                    val_matched = True
                    break

    if val_matched:
        score += 45.0
            
    return score


def rank_and_filter(hits: List[dict], query: str) -> List[Tuple[dict, float]]:
    """Rank hits, apply scoring rules, and filter out those below the minimum threshold."""
    ranked = []
    for hit in hits:
        score = score_hit(hit, query)
        if score >= MIN_THRESHOLD:
            ranked.append((hit, score))
    # Sort by score descending
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked
