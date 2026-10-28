"""
Answer Planner for MCP Data Assistant (Real Mode).

Turns raw, already-matched database hits into an analyst-style plan
(short_answer, key_details, records_summary, source_evidence,
next_step) BEFORE response_builder renders the final chat text.

Hard rule: every fact returned here comes directly from the row_preview
of an actual matched database row. Nothing is invented. If there is no
evidence, the plan says so explicitly (clean no-match, no fake confidence).
"""
from typing import Any, Dict, List, Tuple, Optional

from app import config

BAD_VALUES = {"", "0", "-", "null", "none", "0.0", "0.00", "nan"}

# Entity -> (title candidate columns, [(label, candidate columns), ...])
ENTITY_FIELD_MAP = {
    "invoice": {
        "title": ["invoice_number", "invoice_no", "inv_no", "bill_no", "bill_number"],
        "fields": [
            ("Invoice No", ["invoice_number", "invoice_no", "inv_no", "bill_no", "bill_number"]),
            ("Date", ["invoice_date", "inv_date", "bill_date", "created_at"]),
            ("Status", ["invoice_status", "status", "approve_status"]),
            ("Customer / Vendor", ["customer_name", "vendor_name", "supplier_name"]),
            ("Address", ["billing_to_address_txt", "billing_address", "address"]),
            ("Grand Total", ["invoice_grand_total", "grand_total", "total_amount", "amount", "net_amount"]),
            ("Paid Amount", ["paid_amount"]),
            ("Balance Amount", ["balance_amount"]),
            ("GST No", ["gst_number", "gst_no"]),
            ("Due Date", ["due_date"]),
        ],
    },
    "customer": {
        "title": ["customer_name"],
        "fields": [
            ("Customer Name", ["customer_name"]),
            ("Customer No", ["customer_number", "customer_code", "customer_id"]),
            ("Status", ["status", "active"]),
            ("Billing Address", ["billing_address", "address"]),
            ("Contact Person", ["contact_person"]),
            ("Mobile", ["contact_number"]),
            ("GST/PAN", ["gst_number", "gst_no", "PAN", "pan_no"]),
        ],
    },
    "supplier": {
        "title": ["supplier_name"],
        "fields": [
            ("Supplier Name", ["supplier_name"]),
            ("Supplier No", ["supplier_number", "supplier_code", "supplier_id"]),
            ("Status", ["supplier_status", "status", "active"]),
            ("Billing Address", ["billing_address", "address"]),
            ("Contact Person", ["contact_person"]),
            ("Mobile", ["contact_number"]),
            ("GST No", ["gst_no", "gst_number"]),
        ],
    },
    "item": {
        "title": ["product_alternate_name", "product_name", "concatenated_product", "product_code"],
        "fields": [
            ("Item Name", ["product_alternate_name", "product_name", "concatenated_product"]),
            ("Item Code", ["product_code"]),
            ("Status", ["status", "active"]),
            ("Rate", ["presentation_price", "Std Cost", "price"]),
            ("HSN Code", ["hsn_code"]),
            ("Specification", ["specification", "description"]),
        ],
    },
    "company": {
        "title": ["company_name", "org_name", "organization_name", "name", "company_id"],
        "fields": [
            ("Company Name", ["company_name", "org_name", "organization_name", "name"]),
            ("Company ID", ["company_id", "id"]),
            ("Company Code", ["company_code", "code"]),
            ("Status", ["status", "active"]),
            ("Created At", ["created_at", "created_date"]),
        ],
    },
}


def _get_val(row: dict, keys: List[str]) -> str:
    """Return the first non-empty, non-junk value for the given candidate columns."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            s = str(v).strip()
            if s and s.lower() not in BAD_VALUES:
                return s
    return ""


def _entity_for_table(table: str, entity_hint: Optional[str] = None) -> str:
    if entity_hint and entity_hint in ENTITY_FIELD_MAP:
        return entity_hint
    t = (table or "").lower()
    if "invoice" in t:
        return "invoice"
    if "customer" in t:
        return "customer"
    if "supplier" in t:
        return "supplier"
    if "product" in t or "item" in t:
        return "item"
    if "company" in t or "organization" in t or "org" in t:
        return "company"
    return "generic"


def build_record_summary(hit: dict, entity_hint: Optional[str] = None) -> Dict[str, Any]:
    """Build a compact, evidence-only summary of one matched row. No hallucination."""
    row = hit.get("row_preview") or hit.get("raw_row") or {}
    table = hit.get("table") or hit.get("_table") or "unknown"
    entity = _entity_for_table(table, entity_hint)
    spec = ENTITY_FIELD_MAP.get(entity)

    title = ""
    useful: Dict[str, str] = {}

    if spec:
        title = _get_val(row, spec["title"])
        for label, keys in spec["fields"]:
            val = _get_val(row, keys)
            if val:
                useful[label] = val
    else:
        # Generic fallback: pick a handful of non-empty fields straight from the row.
        # Skip large blob-like fields (JSON menus, permissions, etc.) > 300 chars.
        _BLOB_KEYS = {"menus", "permission", "permissions", "menu", "menu_access",
                     "config", "settings", "json_data", "data", "extra", "meta"}
        for k in sorted(row.keys()):
            v = row.get(k)
            if v is None:
                continue
            s = str(v).strip()
            k_lower = k.lower()
            # Skip known blob columns or values longer than 300 chars
            if k_lower in _BLOB_KEYS or len(s) > 300:
                continue
            if s and s.lower() not in BAD_VALUES and len(useful) < 6:
                useful[k.replace("_", " ").title()] = s
        if not title:
            title = next(iter(useful.values()), "")

    return {
        "entity": entity,
        "table": table,
        "row_id": hit.get("row_id") or hit.get("id") or "?",
        "title": title or "Record",
        "useful_fields": useful,
        "matched_column": hit.get("matched_column") or hit.get("field_name") or "unknown",
        "matched_value": hit.get("matched_value") or hit.get("value") or "",
        "db_file": hit.get("db_file_name") or config.DB_NAME,
    }


def plan_answer(
    intent: str,
    query: str,
    entity_hint: Optional[str],
    hits: List[Tuple[dict, float]],
    max_records: int = 5,
) -> Dict[str, Any]:
    """
    Build an analyst-style answer plan from real, already-matched search hits.
    No hallucination: every value comes from an actual matched row.
    Returns: short_answer, key_details, records_summary, source_evidence, next_step, match_count.
    """
    top_hits = hits[:max_records]
    record_summaries = [build_record_summary(h, entity_hint) for h, _ in top_hits]

    if not record_summaries:
        return {
            "short_answer": "No matching records found in the connected database.",
            "key_details": [],
            "records_summary": [],
            "source_evidence": [],
            "next_step": [],
            "match_count": 0,
        }

    first = record_summaries[0]
    entity = first["entity"]

    if len(record_summaries) == 1:
        short_answer = f"Found 1 matching {entity} record: {first['title']}."
    else:
        short_answer = (
            f"Found {len(record_summaries)} {entity}-related records in the connected database. "
            f"Top match: {first['title']}."
        )

    key_details = [f"{label}: {val}" for label, val in first["useful_fields"].items()]

    source_evidence = [
        {
            "db_file": rs["db_file"],
            "table": rs["table"],
            "row_id": rs["row_id"],
            "matched_column": rs["matched_column"],
            "read_only": True,
        }
        for rs in record_summaries
    ]

    if entity == "invoice":
        next_step = ["Search customer", "Search supplier", "Show database overview"]
    elif entity == "customer":
        next_step = ["Search invoice", "Search supplier", "Show database overview"]
    elif entity == "supplier":
        next_step = ["Search invoice", "Search customer", "Show database overview"]
    elif entity == "item":
        next_step = ["Search invoice", "Search supplier", "Show database overview"]
    else:
        next_step = ["Search customer", "Search invoice", "Search supplier"]

    return {
        "short_answer": short_answer,
        "key_details": key_details,
        "records_summary": record_summaries,
        "source_evidence": source_evidence,
        "next_step": next_step,
        "match_count": len(record_summaries),
    }


def plan_no_match(query: str, entity_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a clean no-match plan (no fake confidence, no invented data).
    When an entity can be detected from the query, suggest related tables
    from the fast db_profile.json registry instead of scanning all tables again.
    """
    related_tables: List[str] = []
    try:
        from app.business_router import detect_entity, get_ranked_tables_for_entity
        entity = entity_hint or detect_entity(query)
        if entity:
            ranked = get_ranked_tables_for_entity(entity)
            related_tables = [t["table_name"] for t in ranked[:5] if t.get("record_count", 0) > 0]
    except Exception:
        related_tables = []

    return {
        "short_answer": "I could not find an exact match in the connected database or dataset.",
        "related_tables": related_tables,
        "next_step": ["Search customer", "Search invoice", "Search supplier"],
    }
