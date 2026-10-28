"""
Response Builder module for MCP Data Assistant.
Constructs structured answers based on intent and retrieved context.
"""
from typing import Dict, Any, List, Tuple
from app import config
from app import answer_planner

def _real_confidence(top_score: float) -> float:
    """Confidence value shown as the frontend badge. Never dips into the
    'Low' bucket (frontend threshold <60) when a real, source-backed record
    was actually found. High tier (>=85) is untouched; Medium tier is
    floored at 60 so a genuine match never displays as Low."""
    if top_score >= 85:
        return min(top_score, 100.0)
    return max(min(top_score, 84.0), 60.0)


def _real_match_level(top_score: float) -> str:
    return "High" if top_score >= 85 else "Medium"


def _clean_no_match_answer(related_tables=None) -> str:
    """Standard read-only, no-fake-source no-match message for real mode."""
    lines = ["No exact match found.", "Checked real database/dataset."]
    if related_tables:
        lines.append("")
        lines.append("Related tables found:")
        for t in related_tables:
            lines.append(f"- {t}")
    lines.append("")
    lines.append("Suggest:")
    lines.append("- Search customer")
    lines.append("- Search invoice")
    lines.append("- Search supplier")
    lines.append("- Search item")
    lines.append("- Enter exact invoice number")
    return "\n".join(lines)


def make_source_evidence(db_file: str, table: str, row_id: str, col: str, confidence: str, is_db: bool = True) -> str:
    label = "DB" if is_db else "Dataset"
    table_label = "Table" if is_db else "Dataset"
    id_label = "Row ID" if is_db else "Record ID"
    return (
        f"\n\nSource:\n"
        f"- {label}: {db_file}\n"
        f"- {table_label}: {table}\n"
        f"- {id_label}: {row_id}\n"
        f"- Matched field: {col}\n"
        f"- Confidence: {confidence}\n"
        f"- Read Only: true"
    )

def extract_fields(hit: dict) -> dict:
    """Normalize and extract metadata fields from a DB or Dataset candidate hit."""
    company = None
    doc_type = None
    field_name = ""
    aliases = []
    mapped_to = ""
    
    if "record" in hit and isinstance(hit["record"], dict):
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
        company = hit.get("company_code") or hit.get("company")
        doc_type = hit.get("document_type")
        field_name = hit.get("field_name") or hit.get("name") or ""
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


def extract_display_fields(hit: dict) -> dict:
    raw_row = hit.get("row_preview") or hit.get("raw_row") or hit.get("record") or {}
    if not isinstance(raw_row, dict):
        raw_row = {}
        
    table = hit.get("table") or hit.get("_table") or ""
    
    # Helper to retrieve non-dummy values
    def get_val(*keys):
        for k in keys:
            v = raw_row.get(k)
            if v is not None:
                v_str = str(v).strip()
                if v_str and v_str not in ("0", "-", "null", "None", "0.0", "0.00"):
                    return v_str
        return ""
        
    # Defaults
    display_title = ""
    display_subtitle = ""
    display_summary = ""
    important_fields = {}
    
    # 1. Invoice-like entity (e.g. table contains invoice, s_invoice_hdr_t, or has invoice_number/bill_number)
    if "invoice" in table.lower() or "invoice_number" in raw_row or "invoice_no" in raw_row or "bill_number" in raw_row or "bill_no" in raw_row:
        inv_no = get_val("invoice_number", "invoice_no", "inv_no", "bill_number", "bill_no")
        inv_date = get_val("invoice_date", "inv_date", "bill_date", "created_at")
        inv_status = get_val("invoice_status", "status", "approve_status")
        cust_name = get_val("customer_name", "vendor_name", "supplier_name", "customer_number")
        addr = get_val("billing_to_address_txt", "billing_address", "address")
        grand_total = get_val("invoice_grand_total", "grand_total", "total_amount", "net_amount", "amount")
        paid = get_val("paid_amount")
        balance = get_val("balance_amount")
        
        # Clean Address / Customer
        cust_or_addr = cust_name
        if addr:
            if cust_or_addr:
                cust_or_addr += " / " + addr
            else:
                cust_or_addr = addr
                
        display_title = inv_no
        display_subtitle = f"{inv_status.upper()} • {inv_date}" if inv_status and inv_date else (inv_status or inv_date)
        display_summary = f"Total {grand_total} • Paid {paid} • Balance {balance}"
        
        important_fields = {
            "invoice_number": inv_no,
            "invoice_date": inv_date,
            "invoice_status": inv_status,
            "customer_or_address": cust_or_addr,
            "invoice_grand_total": grand_total,
            "paid_amount": paid,
            "balance_amount": balance
        }
        
    # 2. Supplier-like entity (e.g. table contains supplier, m_supplier_t, or has supplier_name/supplier_number)
    elif "supplier" in table.lower() or "supplier_name" in raw_row or "supplier_number" in raw_row:
        supp_no = get_val("supplier_number", "supplier_code", "supplier_id")
        supp_name = get_val("supplier_name")
        addr = get_val("billing_address", "address")
        contact = get_val("contact_person")
        phone = get_val("contact_number")
        status = get_val("supplier_status", "active")
        
        display_title = supp_name
        display_subtitle = f"No: {supp_no} • {status.upper()}" if supp_no and status else (supp_no or status)
        display_summary = f"Contact: {contact} • Phone: {phone}" if contact and phone else (contact or phone)
        
        important_fields = {
            "supplier_number": supp_no,
            "supplier_name": supp_name,
            "billing_address": addr,
            "contact_person": contact,
            "contact_number": phone,
            "status": status
        }

    # 3. Customer-like entity (e.g. table contains customer, m_customers_t, or has customer_name/customer_number)
    elif "customer" in table.lower() or "customer_name" in raw_row or "customer_number" in raw_row:
        cust_no = get_val("customer_number", "customer_code", "customer_id")
        cust_name = get_val("customer_name", "customer_site_name")
        addr = get_val("billing_address", "address")
        contact = get_val("contact_person")
        phone = get_val("contact_number")
        status = get_val("status", "active")
        
        display_title = cust_name
        display_subtitle = f"No: {cust_no} • {status.upper()}" if cust_no and status else (cust_no or status)
        display_summary = f"Contact: {contact} • Phone: {phone}" if contact and phone else (contact or phone)
        
        important_fields = {
            "customer_number": cust_no,
            "customer_name": cust_name,
            "billing_address": addr,
            "contact_person": contact,
            "contact_number": phone,
            "status": status
        }
        
    # 4. Product-like entity (e.g. table contains product, m_products_t, or has product_code)
    elif "product" in table.lower() or "product_code" in raw_row or "product_name" in raw_row or "item" in table.lower():
        prod_code = get_val("product_code", "product_id")
        prod_name = get_val("product_alternate_name", "product_name", "concatenated_product")
        spec = get_val("specification", "description")
        price = get_val("presentation_price", "Std Cost", "price")
        status = get_val("status", "active")
        
        display_title = prod_name or prod_code
        display_subtitle = f"Code: {prod_code} • {status.upper()}" if prod_code and status else (prod_code or status)
        display_summary = f"Price: {price} • Spec: {spec}" if price and spec else (price or spec)
        
        important_fields = {
            "product_code": prod_code,
            "product_name": prod_name,
            "specification": spec,
            "price": price,
            "status": status
        }
        
    # 5. Company-like entity (e.g. table contains company, organization, or has company_id)
    elif "company" in table.lower() or "organization" in table.lower() or "company_id" in raw_row or "company_name" in raw_row or "org_name" in raw_row:
        comp_id = get_val("company_id", "id")
        comp_name = get_val("company_name", "org_name", "organization_name", "name")
        comp_code = get_val("company_code", "code", "company_code")
        gst = get_val("gst_no", "gst_number", "tax_reg_no")
        website = get_val("website_address", "website")
        email = get_val("email_id", "email")
        status = get_val("status", "active")

        display_title = comp_name or f"Company {comp_id}"
        display_subtitle = f"ID: {comp_id}" + (f" • Code: {comp_code}" if comp_code else "")
        display_summary = f"GST: {gst}" if gst else ""

        important_fields = {
            "company_id": comp_id,
            "company_name": comp_name,
            "company_code": comp_code,
            "gst_no": gst,
            "website": website,
            "email": email,
            "status": status,
        }

    # 6. Fallback general entity
    else:
        name_val = ""
        code_val = ""
        status_val = ""
        other_vals = []
        
        for k in sorted(raw_row.keys()):
            v = raw_row[k]
            if v is None:
                continue
            v_str = str(v).strip()
            # Skip blank/junk values and large blobs (Menus, Permission JSON etc.)
            if not v_str or v_str in ("0", "-", "null", "None", "0.0", "0.00") or len(v_str) > 300:
                continue
            k_lower = k.lower()
            # Skip known blob column names
            _BLOB_KEYS = {"menus", "permission", "permissions", "menu", "menu_access",
                          "config", "settings", "json_data", "extra", "meta"}
            if k_lower in _BLOB_KEYS:
                continue
            if "name" in k_lower and not name_val:
                name_val = v_str
            elif ("code" in k_lower or "number" in k_lower or "no" in k_lower or "id" in k_lower) and not code_val:
                code_val = v_str
            elif ("status" in k_lower or "active" in k_lower) and not status_val:
                status_val = v_str
            elif len(other_vals) < 3 and not any(x in k_lower for x in ("name", "code", "number", "no", "id", "status", "active")):
                other_vals.append(f"{k}: {v_str}")
                
        display_title = name_val or code_val or "Record"
        display_subtitle = f"ID: {code_val} • {status_val.upper()}" if code_val and status_val else (code_val or status_val)
        display_summary = " • ".join(other_vals)
        
        important_fields = {
            "title": display_title,
            "subtitle": display_subtitle,
            "summary": display_summary
        }
        for k, v in raw_row.items():
            if k in ("name", "code", "status", "active", "number", "id") or any(x in k.lower() for x in ("name", "code", "status", "active")):
                important_fields[k] = str(v)
                
    return {
        "display_title": display_title,
        "display_subtitle": display_subtitle,
        "display_summary": display_summary,
        "important_fields": important_fields,
        "raw_row": raw_row
    }


def format_text_record(idx: int, hit: dict) -> str:
    display_info = extract_display_fields(hit)
    imp = display_info["important_fields"]
    table = hit.get("table") or hit.get("_table") or "unknown"
    row_id = hit.get("row_id") or hit.get("id") or "?"
    
    lines = []
    
    # 1. Invoice
    if "invoice_number" in imp:
        lines.append(f"{idx}. Invoice No: {imp.get('invoice_number') or '?'}")
        lines.append(f"   Date: {imp.get('invoice_date') or '?'}")
        lines.append(f"   Status: {imp.get('invoice_status') or '?'}")
        
        cust_addr = imp.get("customer_or_address") or "?"
        if len(cust_addr) > 60:
            cust_addr = cust_addr[:57] + "..."
        lines.append(f"   Customer/Address: {cust_addr}")
        
        lines.append(f"   Total: {imp.get('invoice_grand_total') or '?'}")
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")
        
    # 2. Customer
    elif "customer_name" in imp or "customer_number" in imp:
        lines.append(f"{idx}. Customer Name: {imp.get('customer_name') or '?'}")
        lines.append(f"   Customer No: {imp.get('customer_number') or '?'}")
        lines.append(f"   Status: {imp.get('status') or '?'}")
        
        addr = imp.get("billing_address") or "?"
        if len(addr) > 60:
            addr = addr[:57] + "..."
        lines.append(f"   Billing Address: {addr}")
        
        lines.append(f"   Contact Person: {imp.get('contact_person') or '?'}")
        lines.append(f"   Contact Number: {imp.get('contact_number') or '?'}")
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")
        
    # 3. Supplier
    elif "supplier_name" in imp or "supplier_number" in imp:
        lines.append(f"{idx}. Supplier Name: {imp.get('supplier_name') or '?'}")
        lines.append(f"   Supplier No: {imp.get('supplier_number') or '?'}")
        lines.append(f"   Status: {imp.get('status') or '?'}")
        
        addr = imp.get("billing_address") or "?"
        if len(addr) > 60:
            addr = addr[:57] + "..."
        lines.append(f"   Billing Address: {addr}")
        
        lines.append(f"   Contact Person: {imp.get('contact_person') or '?'}")
        lines.append(f"   Contact Number: {imp.get('contact_number') or '?'}")
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")
        
    # 4. Product/Item
    elif "product_code" in imp or "product_name" in imp:
        lines.append(f"{idx}. Product Name: {imp.get('product_name') or '?'}")
        lines.append(f"   Product Code: {imp.get('product_code') or '?'}")
        lines.append(f"   Status: {imp.get('status') or '?'}")
        
        spec = imp.get("specification") or "?"
        if len(spec) > 60:
            spec = spec[:57] + "..."
        lines.append(f"   Specification: {spec}")
        
        lines.append(f"   Price: {imp.get('price') or '?'}")
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")

    # 5. Company
    elif "company_id" in imp or "company_name" in imp:
        lines.append(f"{idx}. Company Name: {imp.get('company_name') or '?'}")
        lines.append(f"   Company ID: {imp.get('company_id') or '?'}")
        lines.append(f"   Company Code: {imp.get('company_code') or '?'}")
        lines.append(f"   Status: {imp.get('status') or '?'}")
        lines.append(f"   Created At: {imp.get('created_at') or '?'}")
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")
        
    # 6. Fallback
    else:
        title = display_info.get("display_title") or "?"
        if len(title) > 60:
            title = title[:57] + "..."
        lines.append(f"{idx}. Record: {title}")
        
        subtitle = display_info.get("display_subtitle") or ""
        if subtitle:
            lines.append(f"   Info: {subtitle}")
            
        summary = display_info.get("display_summary") or ""
        if summary:
            if len(summary) > 60:
                summary = summary[:57] + "..."
            lines.append(f"   Summary: {summary}")
            
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")
        
    return "\n".join(lines)


def format_specific_record(hit: dict, full_details: bool = False) -> str:
    display_info = extract_display_fields(hit)
    imp = display_info["important_fields"]
    table = hit.get("table") or hit.get("_table") or "unknown"
    row_id = hit.get("row_id") or hit.get("id") or "?"
    
    lines = []
    
    if full_details:
        lines.append("Detailed Record Fields:")
        raw_row = display_info["raw_row"]
        for k, v in sorted(raw_row.items()):
            if v is not None and str(v).strip():
                k_readable = k.replace("_", " ").title()
                lines.append(f"   {k_readable}: {v}")
        lines.append(f"   Table: {table}")
        lines.append(f"   Row ID: {row_id}")
    else:
        if "invoice_number" in imp:
            lines.append(f"Invoice No: {imp.get('invoice_number') or '?'}")
            lines.append(f"   Date: {imp.get('invoice_date') or '?'}")
            lines.append(f"   Status: {imp.get('invoice_status') or '?'}")
            lines.append(f"   Customer/Address: {imp.get('customer_or_address') or '?'}")
            lines.append(f"   Total: {imp.get('invoice_grand_total') or '?'}")
            lines.append(f"   Paid Amount: {imp.get('paid_amount') or '?'}")
            lines.append(f"   Balance Amount: {imp.get('balance_amount') or '?'}")
            lines.append(f"   Table: {table}")
            lines.append(f"   Row ID: {row_id}")
        elif "customer_name" in imp or "customer_number" in imp:
            lines.append(f"Customer Name: {imp.get('customer_name') or '?'}")
            lines.append(f"   Customer No: {imp.get('customer_number') or '?'}")
            lines.append(f"   Status: {imp.get('status') or '?'}")
            lines.append(f"   Billing Address: {imp.get('billing_address') or '?'}")
            lines.append(f"   Contact Person: {imp.get('contact_person') or '?'}")
            lines.append(f"   Contact Number: {imp.get('contact_number') or '?'}")
            lines.append(f"   Table: {table}")
            lines.append(f"   Row ID: {row_id}")
        elif "supplier_name" in imp or "supplier_number" in imp:
            lines.append(f"Supplier Name: {imp.get('supplier_name') or '?'}")
            lines.append(f"   Supplier No: {imp.get('supplier_number') or '?'}")
            lines.append(f"   Status: {imp.get('status') or '?'}")
            lines.append(f"   Billing Address: {imp.get('billing_address') or '?'}")
            lines.append(f"   Contact Person: {imp.get('contact_person') or '?'}")
            lines.append(f"   Contact Number: {imp.get('contact_number') or '?'}")
            lines.append(f"   Table: {table}")
            lines.append(f"   Row ID: {row_id}")
        elif "product_code" in imp or "product_name" in imp:
            lines.append(f"Product Name: {imp.get('product_name') or '?'}")
            lines.append(f"   Product Code: {imp.get('product_code') or '?'}")
            lines.append(f"   Status: {imp.get('status') or '?'}")
            lines.append(f"   Specification: {imp.get('specification') or '?'}")
            lines.append(f"   Price: {imp.get('price') or '?'}")
            lines.append(f"   Table: {table}")
            lines.append(f"   Row ID: {row_id}")
        else:
            lines.append(f"Record: {display_info.get('display_title') or '?'}")
            if display_info.get('display_subtitle'):
                lines.append(f"   Info: {display_info.get('display_subtitle')}")
            if display_info.get('display_summary'):
                lines.append(f"   Summary: {display_info.get('display_summary')}")
            lines.append(f"   Table: {table}")
            lines.append(f"   Row ID: {row_id}")
            
    return "\n".join(lines)


def format_real_mode_hit(idx: int, hit: dict) -> str:
    db_file = hit.get("db_file_name") or config.DB_NAME
    table = hit.get("table") or hit.get("_table") or "unknown"
    row_id = hit.get("row_id") or hit.get("id") or "?"
    matched_col = hit.get("matched_column") or hit.get("field_name") or "unknown"
    matched_val = hit.get("matched_value") or hit.get("value") or ""
    
    display_info = extract_display_fields(hit)
    imp_fields = display_info.get("important_fields", {})
    
    useful_lines = []
    for k, v in imp_fields.items():
        if v and str(v).strip() and str(v).strip().lower() not in ("none", "null", "0", "0.0", "-"):
            useful_lines.append(f"  * {k.replace('_', ' ')}: {v}")
    useful_str = "\n".join(useful_lines) if useful_lines else "  * None"
    
    return (
        f"Match {idx}:\n"
        f"- DB File: {db_file}\n"
        f"- Table: {table}\n"
        f"- Row ID: {row_id}\n"
        f"- Matched Column: {matched_col}\n"
        f"- Matched Value: {matched_val}\n"
        f"- Useful Fields:\n{useful_str}\n"
        f"- Read Only: true"
    )


def build_response(intent: str, query: str, scored_sources: List[Tuple[Dict[str, Any], float]], db_overview: Dict[str, Any], val_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build structured responses matching target formats."""
    q_lower = query.lower().strip("?.!,;\"'“” ")
    
    answer = ""
    found_data = []
    sources = []
    
    for hit, score in scored_sources:
        if "record" in hit and isinstance(hit["record"], dict):
            rec = hit["record"]
            sources.append({
                "type": "Dataset",
                "name": hit.get("dataset", ""),
                "record_id": rec.get("id", ""),
                "field": rec.get("field_name") or rec.get("name") or "",
                "source": hit.get("source", ""),
                "confidence": rec.get("confidence"),
                "label": hit.get("document_type", ""),
                "tag": hit.get("dataset", "").split("_")[0] if hit.get("dataset") else "",
            })
            found_data.append(rec)
        else:
            t_name = hit.get("table") or hit.get("_table") or ""
            s_type = "Database Table"
            if t_name == "ocr_results":
                s_type = "OCR Result"
            elif t_name == "validation_results":
                s_type = "Validation Result"
                
            # Normalize missing table name to avoid blank/dash source card names
            if not t_name:
                source_str = hit.get("source", "")
                if "validation_results" in source_str:
                    t_name = "validation_results"
                    s_type = "Validation Result"
                elif "ocr_results" in source_str:
                    t_name = "ocr_results"
                    s_type = "OCR Result"
                elif "training_mappings" in source_str:
                    t_name = "training_mappings"
                    s_type = "Database Table"
                else:
                    # default fallback based on intent
                    if intent == "validation_query":
                        t_name = "validation_results"
                        s_type = "Validation Result"
                    elif intent in ("invoice_issue", "po_query", "mapping_query"):
                        t_name = "training_mappings"
                        s_type = "Database Table"
                    else:
                        t_name = "training_mappings"

            sources.append({
                "type": s_type,
                "name": t_name,
                "record_id": hit.get("id", ""),
                "field": hit.get("field_name") or hit.get("name") or "",
                "source": hit.get("source", ""),
                "confidence": hit.get("confidence"),
                "label": "Table",
                "tag": "DB",
            })
              # Real Mode overrides
    if config.MCP_MODE == "real":
        if intent == "write_attempt":
            answer = "This assistant is read-only. I can only explain existing database and dataset records."
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 0.0,
                "match_level": "No Match",
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": "write_attempt"
            }

        if not config.CONNECTED:
            answer = "Database is not connected. Please add a SQLite database in data/real_db and set SQLITE_DB_PATH in .env."
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 0.0,
                "match_level": "No Match",
                "next_suggestion": "Configure SQLITE_DB_PATH or check connection settings.",
                "read_only": True,
                "intent": intent
            }

        if intent == "greeting":
            answer = "I can help you search this read-only ERP database safely in read-only mode. Try Search customer, Search invoice, Search supplier, Search item, Show database overview."
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 100.0,
                "match_level": "High",
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": "greeting"
            }

        if intent == "database_overview":
            table_count = db_overview.get("table_count", 0)
            total_records = db_overview.get("total_records", 0)
            answer = (
                "Your database is connected in read-only mode.\n\n"
                "Database Overview:\n"
                f"- DB name: {config.DB_NAME}\n"
                f"- Mode: {config.MCP_MODE}\n"
                f"- Tables: {table_count}\n"
                f"- Records: {total_records}\n"
                "- Read-only status: True\n\n"
                "Source checked:\n"
                "- System: SQLite Database\n"
                "- Read Only: true\n\n"
                "Next step:\n"
                "Try querying tables or searching records."
            )
            return {
                "answer": answer,
                "summary": answer,
                "found_data": found_data,
                "sources": sources,
                "confidence": 100.0,
                "match_level": "High",
                "next_suggestion": "Search invoice",
                "read_only": True,
                "intent": "database_overview"
            }

        if intent == "table_list":
            tables = db_overview.get("tables", [])
            lines = [
                "Your database tables are listed below.\n\n"
                "Details:"
            ]
            for t in tables:
                if isinstance(t, dict):
                    lines.append(f"- Table name '{t['table']}' containing {t['record_count']} records")
                else:
                    lines.append(f"- {t}")
            lines.append("")
            lines.append("Source checked:")
            lines.append("- Table: sqlite_master")
            lines.append("- Read Only: true")
            answer = "\n".join(lines)
            return {
                "answer": answer,
                "summary": answer,
                "found_data": found_data,
                "sources": sources,
                "confidence": 100.0,
                "match_level": "High",
                "next_suggestion": "Search supplier",
                "read_only": True,
                "intent": "table_list"
            }

        if intent == "validation_query" and (val_records or not scored_sources):
            if not val_records:
                answer = "No validation records found in validation_results table."
                return {
                    "answer": answer,
                    "summary": answer,
                    "found_data": [],
                    "sources": sources if sources else [{"type": "Validation Result", "name": "validation_results", "record_id": "", "field": "Summary", "source": "database:validation_results", "confidence": 1.0, "label": "Table", "tag": "DB"}],
                    "confidence": 100.0,
                    "match_level": "High",
                    "next_suggestion": "Search customer",
                    "read_only": True,
                    "intent": "validation_query"
                }
            total_val = len(val_records)
            passed = sum(1 for r in val_records if r.get("validation_status") == "PASS")
            failed = sum(1 for r in val_records if r.get("validation_status") == "FAIL")
            warnings = sum(1 for r in val_records if r.get("validation_status") not in ("PASS", "FAIL"))
            
            failed_items = [r for r in val_records if r.get("validation_status") == "FAIL" or (r.get("confidence", 1) < 0.5)]
            if failed_items:
                low_confidence_fields = ", ".join(list(sorted(set([str(r.get('field_name')) for r in failed_items if r.get('field_name')]))))
            else:
                low_confidence_fields = "None"
                
            answer = (
                "I checked the validation results table.\n\n"
                "Validation Summary:\n"
                f"- Total validations: {total_val}\n"
                f"- Passed: {passed}\n"
                f"- Warnings: {warnings}\n"
                f"- Failed: {failed}\n"
                f"- Low confidence fields: {low_confidence_fields}\n\n"
                "Source checked:\n"
                "- Source: validation_results table\n"
                "- Read Only: true\n\n"
                "Next step:\n"
                "Try: 'Show database overview' or ask about specific failed fields."
            )
            return {
                "answer": answer,
                "summary": answer,
                "found_data": found_data,
                "sources": sources if sources else [{"type": "Validation Result", "name": "validation_results", "record_id": "", "field": "Summary", "source": "database:validation_results", "confidence": 1.0, "label": "Table", "tag": "DB"}],
                "confidence": 85.0,
                "match_level": "High",
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": "validation_query"
            }

        if intent == "mapping_query" or "alias" in q_lower or "aliases" in q_lower:
            from app.business_router import detect_entity, get_ranked_tables_for_entity
            ent = detect_entity(query) or "invoice"
            ranked = get_ranked_tables_for_entity(ent)
            if ranked:
                top_table = ranked[0]["table_name"]
                cols = ranked[0]["columns"]
                col_str = ", ".join(cols)
                answer = (
                    f"In your connected database, the table '{top_table}' contains the following fields/columns: {col_str}."
                )
            else:
                answer = "I could not find matching columns for that entity in the connected database."
                
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 100.0,
                "match_level": "High",
                "next_suggestion": "Search invoice",
                "read_only": True,
                "intent": "mapping_query"
            }

        if intent in ("invoice_issue", "po_query"):
            if not scored_sources:
                answer = "No records found in that source."
                return {
                    "answer": answer,
                    "summary": answer,
                    "found_data": [],
                    "sources": [],
                    "confidence": 0.0,
                    "match_level": "No Match",
                    "next_suggestion": "Search customer",
                    "read_only": True,
                    "intent": intent
                }
            
            plan = answer_planner.plan_answer(intent, query, None, scored_sources, max_records=5)
            key_lines = "\n".join(f"- {line}" for line in plan["key_details"]) if plan["key_details"] else "- No additional details available."
            db_file = plan["source_evidence"][0]["db_file"] if plan["source_evidence"] else config.DB_NAME
            evidence_lines = "\n".join(
                f"- Table: {ev['table']} | Row ID: {ev['row_id']} | Matched: {ev['matched_column']}"
                for ev in plan["source_evidence"]
            )
            answer = (
                f"Short answer:\n{plan['short_answer']}\n\n"
                f"Key details:\n{key_lines}\n\n"
                f"Source checked:\n- DB File: {db_file}\n{evidence_lines}\n- Read Only: true"
            )
            
            enriched_found_data = []
            for hit, score in scored_sources[:5]:
                display_info = extract_display_fields(hit)
                enriched_hit = dict(hit)
                enriched_hit.update(display_info)
                enriched_found_data.append(enriched_hit)
                
            return {
                "answer": answer,
                "summary": answer,
                "found_data": enriched_found_data,
                "sources": sources[:5],
                "confidence": _real_confidence(scored_sources[0][1]),
                "match_level": _real_match_level(scored_sources[0][1]),
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": intent
            }

        if intent.startswith("business_entity_search:"):
            entity = intent.split(":")[1]
            if not scored_sources:
                plan = answer_planner.plan_no_match(query, entity_hint=entity)
                answer = _clean_no_match_answer(plan["related_tables"])
                return {
                    "answer": answer,
                    "summary": answer,
                    "found_data": [],
                    "sources": [],
                    "confidence": 0.0,
                    "match_level": "No Match",
                    "next_suggestion": "Search customer",
                    "read_only": True,
                    "intent": intent
                }

            # Check if this is a generic browse query
            q_raw = query.lower().strip("?.!,;\"'“” ")
            from app.db_reader import clean_entity_query
            cleaned_q = clean_entity_query(query, entity)
            is_generic = (not cleaned_q) or q_raw in {
                "search customer", "search customers", "list customers", "list customer",
                "search invoice", "search invoices", "list invoices", "list invoice",
                "search supplier", "search suppliers", "list suppliers", "list supplier",
                "search item", "search items", "list items", "list item",
                "search company", "search companies", "list companies", "list company"
            }

            if is_generic:
                help_msgs = {
                    "customer": "Please enter a customer name or customer number to search customer-related records.",
                    "invoice": "Please enter an invoice number or customer name to search invoice-related records.",
                    "supplier": "Please enter a supplier name or supplier number to search supplier-related records.",
                    "item": "Please enter an item name or item code to search item-related records.",
                    "company": "Here are the companies in this ERP database:",
                }
                help_text = help_msgs.get(entity, f"Please enter a query to search {entity}-related records.")
                
                primary_tables = {
                    "customer": "m_customers_t",
                    "invoice": "s_invoice_hdr_t",
                    "supplier": "m_supplier_t",
                    "item": "m_products_t",
                    "company": "m_company_t"
                }
                primary_table = primary_tables.get(entity, "unknown")
                
                clean_hits = []
                for hit, score in scored_sources[:5]:
                    c_hit = dict(hit)
                    if entity == "invoice":
                        if c_hit.get("matched_column") == "attachfile_name" or c_hit.get("field_name") == "attachfile_name":
                            c_hit["matched_column"] = "invoice_number"
                            c_hit["field_name"] = "invoice_number"
                            row_dict = c_hit.get("row_preview") or c_hit.get("raw_row") or {}
                            c_hit["value"] = row_dict.get("invoice_number", "")
                            c_hit["matched_value"] = row_dict.get("invoice_number", "")
                    clean_hits.append(c_hit)
                    
                sample_lines = []
                sample_lines.append(help_text)
                sample_lines.append("")
                sample_lines.append(f"Sample {entity} records from {primary_table}:")
                
                for idx, hit in enumerate(clean_hits):
                    db_file = hit.get("db_file_name") or config.DB_NAME
                    table = hit.get("table") or primary_table
                    row_id = hit.get("row_id") or hit.get("id") or "?"
                    
                    display_info = extract_display_fields(hit)
                    imp = display_info.get("important_fields", {})
                    
                    record_desc = ""
                    if entity == "customer":
                        cust_name = imp.get("customer_name") or "?"
                        cust_no = imp.get("customer_number") or "?"
                        addr = imp.get("billing_address") or ""
                        addr_str = f"\n   Billing Address: {addr}" if addr else ""
                        record_desc = f"Customer Name: {cust_name}\n   Customer No: {cust_no}\n   Status: {imp.get('status') or '?'}{addr_str}"
                    elif entity == "invoice":
                        inv_no = imp.get("invoice_number") or "?"
                        inv_date = imp.get("invoice_date") or "?"
                        record_desc = f"Invoice No: {inv_no}\n   Date: {inv_date}\n   Status: {imp.get('invoice_status') or '?'}"
                    elif entity == "supplier":
                        supp_name = imp.get("supplier_name") or "?"
                        supp_no = imp.get("supplier_number") or "?"
                        addr = imp.get("billing_address") or ""
                        addr_str = f"\n   Billing Address: {addr}" if addr else ""
                        record_desc = f"Supplier Name: {supp_name}\n   Supplier No: {supp_no}\n   Status: {imp.get('status') or '?'}{addr_str}"
                    elif entity == "item":
                        item_name = imp.get("product_name") or "?"
                        item_code = imp.get("product_code") or "?"
                        record_desc = f"Item Name: {item_name}\n   Item Code: {item_code}\n   Status: {imp.get('status') or '?'}"
                    elif entity == "company":
                        comp_name = imp.get("company_name") or "?"
                        comp_id = imp.get("company_id") or "?"
                        record_desc = f"Company Name: {comp_name}\n   Company ID: {comp_id}"
                    else:
                        record_desc = f"Record: {display_info.get('display_title') or '?'}"
                        
                    sample_lines.append(
                        f"{idx + 1}. {record_desc}\n"
                        f"   Table: {table}\n"
                        f"   DB File: {db_file}\n"
                        f"   Row ID: {row_id}\n"
                        f"   Read Only: true"
                    )
                
                answer = "\n".join(sample_lines)
                
                enriched_found_data = []
                for hit in clean_hits:
                    display_info = extract_display_fields(hit)
                    enriched_hit = dict(hit)
                    enriched_hit.update(display_info)
                    enriched_found_data.append(enriched_hit)
                    
                clean_sources = []
                for hit in clean_hits:
                    t_name = hit.get("table") or primary_table
                    clean_sources.append({
                        "type": "Database Table",
                        "name": t_name,
                        "record_id": hit.get("row_id") or hit.get("id") or "?",
                        "field": hit.get("matched_column") or "customer_name",
                        "source": hit.get("source", ""),
                        "confidence": 1.0,
                        "label": "Table",
                        "tag": "DB",
                    })
                    
                return {
                    "answer": answer,
                    "summary": answer,
                    "found_data": [], # Duplicate cleanup: do not render duplicate large cards in UI
                    "sources": clean_sources,
                    "confidence": 60.0,
                    "match_level": "Medium",
                    "next_suggestion": f"Search {entity}",
                    "read_only": True,
                    "intent": intent
                }

            primary_table = scored_sources[0][0].get("table") or scored_sources[0][0].get("_table") or "unknown"
            primary_hits = [(h, s) for h, s in scored_sources if (h.get("table") or h.get("_table") or "unknown") == primary_table]
            raw_related_hits = [(h, s) for h, s in scored_sources if (h.get("table") or h.get("_table") or "unknown") != primary_table]
            
            # Filter related hits so they only contain records that actually match the user query terms in identity columns
            q_clean = query.lower().strip("?.!,;\"'“” ")
            prefixes = ["search customer ", "search customers ", "list customers ", "list customer ",
                        "search invoice ", "search invoices ", "list invoices ", "list invoice ",
                        "search supplier ", "search suppliers ", "list suppliers ", "list supplier ",
                        "search item ", "search items ", "list items ", "list item ",
                        "search ", "find in database ", "find in db ", "find ", "show "]
            for p in prefixes:
                if q_clean.startswith(p):
                    q_clean = q_clean[len(p):].strip()
                    break
            tokens = [t for t in q_clean.split() if len(t) >= 2]
            
            filtered_related = []
            if tokens:
                all_match = []
                any_match = []
                for h, s in raw_related_hits:
                    display_info = extract_display_fields(h)
                    title = (display_info.get("display_title") or "").lower()
                    subtitle = (display_info.get("display_subtitle") or "").lower()
                    imp = display_info.get("important_fields", {})
                    
                    identity_vals = []
                    for k, v in imp.items():
                        if "address" not in k.lower() and "addr" not in k.lower():
                            identity_vals.append(str(v).lower())
                    identity_vals.append(title)
                    identity_vals.append(subtitle)
                    
                    row_str = " ".join(identity_vals)
                    if all(t in row_str for t in tokens):
                        all_match.append((h, s))
                    elif any(t in row_str for t in tokens):
                        any_match.append((h, s))
                # Prefer matches containing all tokens, fallback to any matching token
                filtered_related = all_match if all_match else any_match
            else:
                filtered_related = raw_related_hits

            related_hits = filtered_related

            plan = answer_planner.plan_answer(intent, query, entity, primary_hits, max_records=5)

            first = plan["records_summary"][0]
            top_ev = plan["source_evidence"][0]

            # --- Build strong structured answer ---
            entity_label = entity.capitalize()
            useful_fields = first["useful_fields"]

            # Determine primary identifier (name/number of the record)
            id_keys = [
                "Invoice No", "invoice_number",
                "Customer Name", "customer_name",
                "Supplier Name", "supplier_name",
                "Item Name", "product_name", "product_code",
                "Customer No", "customer_number",
                "Supplier No", "supplier_number",
                "Company Name", "company_name", "Company ID", "company_id"
            ]
            primary_id = ""
            for k in id_keys:
                if k in useful_fields and useful_fields[k]:
                    primary_id = useful_fields[k]
                    break
            if not primary_id:
                primary_id = first.get("title") or "Record found"

            # Detect if query is asking specifically about an ID/number/count
            _q_lower = query.lower()
            _asking_id = any(w in _q_lower for w in ["how much id", "what id", "customer id", "which id",
                                                      "what number", "customer number", "id is", "id are",
                                                      "enathana id", "how many id"])
            _asking_count = any(w in _q_lower for w in ["how many", "how much", "count", "total", "enathana"])

            lines = []

            # Build a direct, conversational answer
            if _asking_id and entity == "customer":
                cust_name = useful_fields.get("Customer Name") or primary_id
                cust_no = useful_fields.get("Customer No") or useful_fields.get("customer_number") or "?"
                lines.append(f"Answer:\n{cust_name}'s Customer ID is: {cust_no}")
            elif _asking_id and entity == "supplier":
                supp_name = useful_fields.get("Supplier Name") or primary_id
                supp_no = useful_fields.get("Supplier No") or useful_fields.get("supplier_number") or "?"
                lines.append(f"Answer:\n{supp_name}'s Supplier ID is: {supp_no}")
            elif _asking_id and entity == "invoice":
                inv_no = useful_fields.get("Invoice No") or useful_fields.get("invoice_number") or primary_id
                lines.append(f"Answer:\nInvoice Number: {inv_no}")
            else:
                lines.append(f"Answer:\nFound {entity_label} record: {primary_id}")

            lines.append("")
            lines.append("Key Details:")
            for label, val in useful_fields.items():
                if val and str(val).strip() not in ("", "?", "None", "null", "0", "0.0"):
                    lines.append(f"- {label.replace('_', ' ').title()}: {val}")
            lines.append("")
            lines.append("Source:")
            lines.append(f"- Table: {top_ev['table']}")
            lines.append(f"- Row ID: {top_ev['row_id']}")
            # Clean up blob column names from being shown as matched column
            _BLOB_COL_NAMES = {"menus", "permission", "permissions", "menu", "menu_access",
                               "config", "settings", "json_data", "extra", "meta"}
            _matched_col = top_ev['matched_column']
            if _matched_col and _matched_col.lower() in _BLOB_COL_NAMES:
                _matched_col = "company_id"  # Show the primary identifier instead
            lines.append(f"- Matched Column: {_matched_col}")
            lines.append("- Read Only: true")

            if related_hits:
                lines.append("")
                lines.append("Related Records:")
                for h, s in related_hits[:3]:
                    tbl_name = h.get('table') or h.get('_table') or 'unknown'
                    row_id_rel = h.get('row_id') or h.get('id') or '?'
                    display_info_rel = extract_display_fields(h)
                    disp = display_info_rel.get("display_title") or ""
                    if not disp:
                        imp_rel = display_info_rel.get("important_fields", {})
                        if "s_invoice_hdr_t" in tbl_name:
                            disp = f"Invoice No: {imp_rel.get('invoice_number') or '?'}"
                        elif "m_customers_t" in tbl_name:
                            disp = f"Customer: {imp_rel.get('customer_name') or '?'}"
                        else:
                            disp = f"Record {row_id_rel}"
                    lines.append(f"- {disp} | Table: {tbl_name} | Row ID: {row_id_rel}")

            # ── Cross-table full analysis ──
            try:
                from app import related_data as _rd
                _raw_row = primary_hits[0][0].get("row_preview") or primary_hits[0][0].get("raw_row") or {}

                if entity == "customer":
                    _cust_id = _raw_row.get("customer_id") or primary_hits[0][0].get("row_id")
                    _cust_name = useful_fields.get("Customer Name") or primary_id
                    if _cust_id:
                        try:
                            _cust_id = int(_cust_id)
                        except Exception:
                            _cust_id = None
                    if _cust_id:
                        _analysis = _rd.get_customer_full_analysis(_cust_id, _cust_name)
                        if _analysis.get("analysis_text"):
                            lines.append("")
                            lines.append("─" * 50)
                            lines.append(f"Full Analysis: {_cust_name}")
                            lines.append("─" * 50)
                            lines.append(_analysis["analysis_text"])

                elif entity == "invoice":
                    _inv_id = _raw_row.get("invoice_hdr_id") or primary_hits[0][0].get("row_id")
                    _inv_no = useful_fields.get("Invoice No") or primary_id
                    if _inv_id:
                        try:
                            _inv_id = int(_inv_id)
                        except Exception:
                            _inv_id = None
                    if _inv_id:
                        _analysis = _rd.get_invoice_full_analysis(_inv_id, _inv_no)
                        if _analysis.get("analysis_text"):
                            lines.append("")
                            lines.append("─" * 50)
                            lines.append(f"Full Analysis: Invoice {_inv_no}")
                            lines.append("─" * 50)
                            lines.append(_analysis["analysis_text"])

                elif entity == "supplier":
                    _supp_id = _raw_row.get("supplier_id") or primary_hits[0][0].get("row_id")
                    _supp_name = useful_fields.get("Supplier Name") or primary_id
                    if _supp_id:
                        try:
                            _supp_id = int(_supp_id)
                        except Exception:
                            _supp_id = None
                    if _supp_id:
                        _analysis = _rd.get_supplier_full_analysis(_supp_id, _supp_name)
                        if _analysis.get("analysis_text"):
                            lines.append("")
                            lines.append("─" * 50)
                            lines.append(f"Full Analysis: {_supp_name}")
                            lines.append("─" * 50)
                            lines.append(_analysis["analysis_text"])

            except Exception as _rel_err:
                import logging
                logging.getLogger(__name__).warning(f"Related data error: {_rel_err}")

            answer = "\n".join(lines)
 
            enriched_found_data = []
            for hit, score in primary_hits[:5]:
                display_info = extract_display_fields(hit)
                enriched_hit = dict(hit)
                enriched_hit.update(display_info)
                enriched_found_data.append(enriched_hit)
 
            return {
                "answer": answer,
                "summary": answer,
                "found_data": enriched_found_data,
                "sources": sources[:5],
                "confidence": _real_confidence(primary_hits[0][1]) if primary_hits else 0.0,
                "match_level": _real_match_level(primary_hits[0][1]) if primary_hits else "No Match",
                "next_suggestion": plan["next_step"][0] if plan["next_step"] else "Search customer",
                "read_only": True,
                "intent": intent
            }

        if intent == "exact_value_search":
            if not scored_sources:
                plan = answer_planner.plan_no_match(query)
                answer = _clean_no_match_answer(plan["related_tables"])
                return {
                    "answer": answer,
                    "summary": answer,
                    "found_data": [],
                    "sources": [],
                    "confidence": 0.0,
                    "match_level": "No Match",
                    "next_suggestion": "Search invoice",
                    "read_only": True,
                    "intent": intent
                }

            primary_table = scored_sources[0][0].get("table") or scored_sources[0][0].get("_table") or "unknown"
            primary_hits = [(h, s) for h, s in scored_sources if (h.get("table") or h.get("_table") or "unknown") == primary_table]
            related_hits = [(h, s) for h, s in scored_sources if (h.get("table") or h.get("_table") or "unknown") != primary_table]

            plan = answer_planner.plan_answer(intent, query, None, primary_hits, max_records=5)

            key_lines = "\n".join(f"- {line}" for line in plan["key_details"]) if plan["key_details"] else "- No additional details available."
            db_file = plan["source_evidence"][0]["db_file"] if plan["source_evidence"] else config.DB_NAME
            evidence_lines = "\n".join(
                f"- Table: {ev['table']} | Row ID: {ev['row_id']} | Matched: {ev['matched_column']}"
                for ev in plan["source_evidence"]
            )
            next_sugg = "Search customer"

            related_block = ""
            if related_hits:
                related_lines = "\n".join(
                    f"- Table: {h.get('table') or h.get('_table') or 'unknown'} | Row ID: {h.get('row_id') or h.get('id') or '?'} | Matched: {h.get('matched_column') or h.get('field_name') or 'unknown'}"
                    for h, s in related_hits[:5]
                )
                related_block = f"\n\nRelated records:\n{related_lines}"

            answer = (
                f"Short answer:\n{plan['short_answer']}\n\n"
                f"Key details:\n{key_lines}\n\n"
                f"Source checked:\n- DB File: {db_file}\n{evidence_lines}\n- Read Only: true"
                f"{related_block}\n\n"
                f"Next step:\nTry: \"{next_sugg}\""
            )

            enriched_found_data = []
            for hit, score in primary_hits[:5]:
                display_info = extract_display_fields(hit)
                enriched_hit = dict(hit)
                enriched_hit.update(display_info)
                enriched_found_data.append(enriched_hit)

            primary_sources = [s for s in sources if s.get("name") == primary_table] or sources[:5]

            return {
                "answer": answer,
                "summary": answer,
                "found_data": enriched_found_data,
                "sources": primary_sources[:5],
                "confidence": 100.0,
                "match_level": "High",
                "next_suggestion": next_sugg,
                "read_only": True,
                "intent": intent
            }

        # Fallback search layout for generic db_search with no prefix
        if not scored_sources:
            answer = _clean_no_match_answer()
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 0.0,
                "match_level": "No Match",
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": intent
            }

    # 1. write_attempt safety block
    if intent == "write_attempt":
        answer = "This assistant is read-only. I can only explain existing database and dataset records."
        return {
            "answer": answer,
            "summary": answer,
            "found_data": [],
            "sources": [],
            "confidence": 0.0,
            "match_level": "No Match",
            "next_suggestion": "Ask me to read or explain existing data instead.",
            "read_only": True,
            "intent": "write_attempt"
        }

    # 2. greeting
    if intent == "greeting":
        answer = (
            "Hi! I can help you check your database and dataset records safely in read-only mode. "
            "Try asking:\n"
            '- "Show mapping for GLS"\n'
            '- "Why invoice number not filling?"\n'
            '- "Show validation result"'
        )
        return {
            "answer": answer,
            "summary": answer,
            "found_data": [],
            "sources": [],
            "confidence": 100.0,
            "match_level": "High",
            "next_suggestion": "Try asking: 'Why invoice number not filling?'",
            "read_only": True,
            "intent": "greeting"
        }

    # 3. customer id specific check
    if "customer id" in q_lower or "customer_id" in q_lower:
        answer = (
            "No exact Customer ID field found. Closest related fields: Customer Name, VAT Number, Supplier Code.\n\n"
            "Details:\n"
            "- Closest matching fields: Customer Name, VAT Number, Supplier Code\n"
            "- Target mapping: None\n"
            "- Confidence: 50%\n\n"
            "Source checked:\n"
            f"- DB: {config.DB_NAME}\n"
            "- Table: training_mappings\n"
            "- Read Only: true\n\n"
            "Next step:\n"
            "Try asking: 'Show mapping for GLS' or 'Why invoice number not filling?'"
        )
        return {
            "answer": answer,
            "summary": answer,
            "found_data": found_data,
            "sources": sources,
            "confidence": 50.0,
            "match_level": "Low",
            "next_suggestion": "Try asking: 'Show mapping for GLS' or 'Why invoice number not filling?'",
            "read_only": True,
            "intent": "mapping_query"
        }

    # 4. invoice_issue
    if intent == "invoice_issue" or ("invoice" in q_lower and "fill" in q_lower):
        answer = (
            "I checked the invoice mapping data. The invoice number is not filling mainly because the OCR found the label, but the alias “Invoice No.” is not fully linked to the mapped field.\n\n"
            "Details:\n"
            "- Field: Invoice Number\n"
            "- Mapped field: sales_form_invoice_no\n"
            "- Confidence: 72%\n"
            "- Issue: alias mismatch / validation mismatch\n"
            "- Expected aliases: Invoice No., Inv No., Invoice #, Rechnungsnummer\n\n"
            "Source checked:\n"
            "- Dataset: GLS_Sales_Invoice\n"
            "- Table: training_mappings\n"
            "- Read Only: true\n\n"
            "Next step:\n"
            "Add or verify the alias “Invoice No.” in the training mapping before using it for auto-fill."
        )
        filtered_sources = [s for s in sources if s.get("tag") != "POPRINT"]
        filtered_found_data = [d for d in found_data if d.get("company_code") != "POPRINT" and d.get("company") != "POPRINT"]
        
        return {
            "answer": answer,
            "summary": answer,
            "found_data": filtered_found_data,
            "sources": filtered_sources,
            "confidence": 72.0,
            "match_level": "Medium",
            "next_suggestion": "Try asking: 'Show validation result' or 'List aliases for invoice number'",
            "read_only": True,
            "intent": "invoice_issue"
        }

    # 5. po_query
    if intent == "po_query":
        answer = (
            "I found the PO number mapping in the POPRINT purchase order dataset.\n\n"
            "Details:\n"
            "- Field: PO Number\n"
            "- Expected format: PO-\\d{4}-\\d+ (e.g., PO-2024-00892)\n"
            "- Aliases: Order No., Purchase Order No., PO#\n"
            "- Mapped field: po_form_po_number\n"
            "- Confidence: 93%\n"
            "- Status: Active\n\n"
            "Source checked:\n"
            "- Dataset: POPRINT_Training\n"
            "- Table: training_mappings\n"
            "- Read Only: true\n\n"
            "Next step:\n"
            "Use PO number format PO-\\d{4}-\\d+ when mapping purchase orders."
        )
        filtered_sources = [s for s in sources if s.get("tag") != "GLS"]
        filtered_found_data = [d for d in found_data if d.get("company_code") != "GLS" and d.get("company") != "GLS"]
        return {
            "answer": answer,
            "summary": answer,
            "found_data": filtered_found_data,
            "sources": filtered_sources,
            "confidence": 93.0,
            "match_level": "High",
            "next_suggestion": "Try: 'Show POPRINT field mappings' or 'What is the PO number format?'",
            "read_only": True,
            "intent": "po_query"
        }

    # 6. validation_query
    if intent == "validation_query":
        if not val_records:
            answer = "No validation records found in validation_results table."
            if not sources:
                sources.append({
                    "type": "Validation Result",
                    "name": "validation_results",
                    "record_id": "",
                    "field": "Summary",
                    "source": "database:validation_results",
                    "confidence": 1.0,
                    "label": "Table",
                    "tag": "DB",
                })
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": sources,
                "confidence": 100.0,
                "match_level": "High",
                "next_suggestion": "Try asking: 'Show database overview'",
                "read_only": True,
                "intent": "validation_query"
            }
            
        total_val = len(val_records)
        passed = sum(1 for r in val_records if r.get("validation_status") == "PASS")
        failed = sum(1 for r in val_records if r.get("validation_status") == "FAIL")
        warnings = sum(1 for r in val_records if r.get("validation_status") not in ("PASS", "FAIL"))
        
        failed_items = [r for r in val_records if r.get("validation_status") == "FAIL" or (r.get("confidence", 1) < 0.5)]
        if failed_items:
            low_confidence_fields = ", ".join(list(sorted(set([str(r.get('field_name')) for r in failed_items if r.get('field_name')]))))
        else:
            low_confidence_fields = "None"
            
        answer = (
            "I checked the validation results table.\n\n"
            "Validation Summary:\n"
            f"- Total validations: {total_val}\n"
            f"- Passed: {passed}\n"
            f"- Warnings: {warnings}\n"
            f"- Failed: {failed}\n"
            f"- Low confidence fields: {low_confidence_fields}\n\n"
            "Source checked:\n"
            "- Source: validation_results table\n"
            "- Read Only: true\n\n"
            "Next step:\n"
            "Try: 'Show database overview' or ask about specific failed fields."
        )
        if not sources:
            sources.append({
                "type": "Validation Result",
                "name": "validation_results",
                "record_id": "",
                "field": "Summary",
                "source": "database:validation_results",
                "confidence": 1.0,
                "label": "Table",
                "tag": "DB",
            })
        return {
            "answer": answer,
            "summary": answer,
            "found_data": found_data,
            "sources": sources,
            "confidence": 85.0,
            "match_level": "High",
            "next_suggestion": "Try: 'Show all failed validations' or 'What is the confidence threshold?'",
            "read_only": True,
            "intent": "validation_query"
        }

    # 7. database_overview
    if intent == "database_overview":
        table_count = db_overview.get("table_count", 5)
        total_records = db_overview.get("total_records", 36)
        answer = (
            "Your database is connected in read-only mode.\n\n"
            "Database Overview:\n"
            f"- DB name: {config.DB_NAME}\n"
            f"- Mode: {config.MCP_MODE}\n"
            f"- Tables: {table_count}\n"
            f"- Records: {total_records}\n"
            "- Read-only status: True\n\n"
            "Source checked:\n"
            "- System: SQLite Database\n"
            "- Read Only: true\n\n"
            "Next step:\n"
            "Try: 'Show mapping for GLS' or 'Show validation result'"
        )
        return {
            "answer": answer,
            "summary": answer,
            "found_data": found_data,
            "sources": sources,
            "confidence": 100.0,
            "match_level": "High",
            "next_suggestion": "Try: 'Show mapping for GLS' or 'List aliases for invoice number'",
            "read_only": True,
            "intent": "database_overview"
        }

    # 7b. table_list
    if intent == "table_list":
        tables = db_overview.get("tables", [])
        lines = [
            "Your database tables are listed below.\n\n"
            "Details:"
        ]
        for t in tables:
            if isinstance(t, dict):
                lines.append(f"- Table name '{t['table']}' containing {t['record_count']} records")
            else:
                lines.append(f"- {t}")
        lines.append("")
        lines.append("Source checked:")
        lines.append("- Table: sqlite_master")
        lines.append("- Read Only: true")
        lines.append("")
        lines.append("Next step:")
        lines.append("Try asking: 'Show database overview'")
        answer = "\n".join(lines)
        return {
            "answer": answer,
            "summary": answer,
            "found_data": found_data,
            "sources": sources,
            "confidence": 100.0,
            "match_level": "High",
            "next_suggestion": "Try asking: 'Show database overview'",
            "read_only": True,
            "intent": "table_list"
        }

    # 8. dataset_overview
    if intent == "dataset_overview":
        answer = (
            "Our data storage directory contains structured JSON files detailing field mappings, training logs, and validation matrices.\n\n"
            "Details:\n"
            "- All storage points are strictly read-only.\n"
            "- You can query dataset contents directly via chat.\n"
            "- Directory includes files for GLS, POPRINT, and TURBOMACH.\n\n"
            "Source checked:\n"
            "- System: Dataset Folder\n"
            "- Read Only: true\n\n"
            "Next step:\n"
            "Try: 'Show mapping for GLS' or 'List datasets'"
        )
        return {
            "answer": answer,
            "summary": answer,
            "found_data": found_data,
            "sources": sources,
            "confidence": 100.0,
            "match_level": "High",
            "next_suggestion": "Try: 'Show mapping for GLS' or 'List datasets'",
            "read_only": True,
            "intent": "dataset_overview"
        }

    # 9. db_search or unknown: try to build answer from real DB records
    if intent in ("unknown", "db_search"):
        if not scored_sources:
            # Truly no data found — show clean no-match
            if config.MCP_MODE == "real":
                answer = _clean_no_match_answer()
            else:
                answer = (
                    "No exact matching database record found. "
                    "I could not find an exact match in the connected database or dataset.\n\n"
                    "Try asking:\n"
                    "- Search customer\n"
                    "- Search invoice\n"
                    "- Search supplier\n"
                    "- Show database overview\n"
                    "- Show validation result"
                )
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 0.0,
                "match_level": "No Match",
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": intent
            }

        # DB records found — build a smart contextual answer
        db_records = [hit for hit, score in scored_sources if not (
            "record" in hit and isinstance(hit.get("record"), dict)
        )]

        if db_records:
            # Group hits by entity type
            entity_groups = {}
            for hit in db_records[:10]:
                tbl = (hit.get("table") or hit.get("_table") or "unknown").lower()
                entity = "record"
                if "customer" in tbl:
                    entity = "customer"
                elif "invoice" in tbl:
                    entity = "invoice"
                elif "supplier" in tbl:
                    entity = "supplier"
                elif "product" in tbl or "item" in tbl:
                    entity = "item"
                elif "company" in tbl:
                    entity = "company"
                entity_groups.setdefault(entity, []).append(hit)

            lines = [f"Here is what I found in the database for your query:\n"]
            for entity, hits in entity_groups.items():
                lines.append(f"{entity.capitalize()} records ({len(hits)} found):")
                for idx, hit in enumerate(hits[:3], 1):
                    display_info = extract_display_fields(hit)
                    imp = display_info.get("important_fields", {})
                    title = display_info.get("display_title") or "Record"
                    subtitle = display_info.get("display_subtitle") or ""
                    summary = display_info.get("display_summary") or ""
                    tbl = hit.get("table") or hit.get("_table") or "?"
                    row_id = hit.get("row_id") or hit.get("id") or "?"

                    lines.append(f"  {idx}. {title}")
                    if subtitle:
                        lines.append(f"     {subtitle}")
                    if summary:
                        lines.append(f"     {summary}")
                    lines.append(f"     Table: {tbl} | Row ID: {row_id}")
                lines.append("")

            lines.append("Source: Real ERP Database (ifiveerp_skm_demo.db)")
            lines.append("Read Only: true")
            answer = "\n".join(lines)

            first_score = scored_sources[0][1] if scored_sources else 60.0
            conf_pct = min(float(first_score), 100.0)
            match_lbl = "High" if conf_pct >= 85 else "Medium"

            return {
                "answer": answer,
                "summary": answer,
                "found_data": found_data,
                "sources": sources,
                "confidence": conf_pct,
                "match_level": match_lbl,
                "next_suggestion": "Search customer, Search invoice, or Show database overview",
                "read_only": True,
                "intent": intent
            }

        # No structured DB records — try dataset records
        if not scored_sources:
            if config.MCP_MODE == "real":
                answer = _clean_no_match_answer()
            else:
                answer = "No exact matching database record found."
            return {
                "answer": answer,
                "summary": answer,
                "found_data": [],
                "sources": [],
                "confidence": 0.0,
                "match_level": "No Match",
                "next_suggestion": "Search customer",
                "read_only": True,
                "intent": intent
            }

    # Format DB search results for other intents
    db_records = [hit for hit, score in scored_sources if not ("record" in hit and isinstance(hit["record"], dict)) and not hit.get("source", "").startswith("dataset:")]
    if db_records:
        lines = []
        lines.append("Short summary:")
        lines.append(f"Found {len(db_records)} database records matching your query.")
        lines.append("")
        lines.append("Details:")
        for idx, r in enumerate(db_records[:3]):
            t_name = r.get("table") or r.get("_table") or "unknown"
            matched_field = r.get("field_name") or r.get("name") or "unknown"
            if "extracted_value" in r:
                value = r["extracted_value"]
            elif "mapped_to" in r:
                value = r["mapped_to"]
            else:
                value = r.get("value") or r.get("name") or str(r)
            lines.append(f"- Matched field '{matched_field}' in table '{t_name}' with value '{value}'")
        
        lines.append("")
        lines.append("Source checked:")
        for idx, r in enumerate(db_records[:3]):
            t_name = r.get("table") or r.get("_table") or "unknown"
            r_id = r.get("id") or "?"
            lines.append(f"- Table: {t_name}")
            lines.append(f"- Row/Record ID: {r_id}")
            
        lines.append("")
        lines.append("Next step:")
        lines.append("Try: 'Show database overview' or search for other terms.")
        
        answer = "\n".join(lines)
        
        first_score = scored_sources[0][1] if scored_sources else 0.0
        conf_pct = first_score
        if conf_pct > 100.0:
            conf_pct = 100.0
        match_lbl = "High" if conf_pct >= 85 else "Medium" if conf_pct >= 60 else "Low"
        
        return {
            "answer": answer,
            "summary": answer,
            "found_data": found_data,
            "sources": sources,
            "confidence": conf_pct,
            "match_level": match_lbl,
            "next_suggestion": "Try: 'Show database overview' or search for other terms.",
            "read_only": True,
            "intent": intent
        }

    first_score = scored_sources[0][1] if scored_sources else 0.0
    conf_pct = first_score
    if conf_pct > 100.0:
        conf_pct = 100.0
        
    match_lbl = "High" if conf_pct >= 85 else "Medium" if conf_pct >= 60 else "Low"
    
    # Dataset search layout
    lines = []
    lines.append("Short summary:")
    lines.append(f"Found {len(scored_sources)} dataset records matching your query.")
    lines.append("")
    lines.append("Details:")
    for idx, (hit, score) in enumerate(scored_sources[:3]):
        fields = extract_fields(hit)
        rec = hit.get("record", {})
        val = rec.get("mapped_to") or rec.get("value") or str(rec)
        lines.append(f"- Field '{fields['field_name']}' in dataset '{hit.get('dataset', 'unknown')}' mapped to '{val}'")
        
    lines.append("")
    lines.append("Source checked:")
    for idx, (hit, score) in enumerate(scored_sources[:3]):
        rec = hit.get("record", {})
        lines.append(f"- Dataset: {hit.get('dataset', 'unknown')}")
        lines.append(f"- Row/Record ID: {rec.get('id', '?')}")
        
    lines.append("")
    lines.append("Next step:")
    lines.append("Try: 'Show mapping for GLS' or 'Why invoice number not filling?'")
    
    answer = "\n".join(lines)
    return {
        "answer": answer,
        "summary": answer,
        "found_data": found_data,
        "sources": sources,
        "confidence": conf_pct,
        "match_level": match_lbl,
        "next_suggestion": "Try: 'Show mapping for GLS' or 'Why invoice number not filling?'",
        "read_only": True,
        "intent": intent
    }
