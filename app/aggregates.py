"""
Aggregate & Analytics Queries for MCP Data Assistant.

Resolves aggregate questions (e.g. total count, overall sum, average balance)
directly using SQLite aggregates (SUM, COUNT, AVG) instead of returning
single record details.
"""

import sqlite3
import logging
import re
from typing import Dict, Any, Optional
from app import config

logger = logging.getLogger(__name__)

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def _fmt_num(val: Any, decimals: int = 2) -> str:
    try:
        return f"{float(val or 0):,.{decimals}f}"
    except Exception:
        return str(val or 0)

def find_matching_customer(query_str: str, conn: sqlite3.Connection) -> Optional[tuple]:
    """Find a customer ID and Name matching words in the query."""
    q_clean = re.sub(r"[^a-zA-Z0-9\s]", " ", query_str.lower())
    
    # Fetch all customers whose name is a substring of the query
    cur = conn.execute(
        "SELECT customer_id, customer_name FROM m_customers_t WHERE ? LIKE '%' || LOWER(customer_name) || '%'",
        (q_clean,)
    )
    rows = cur.fetchall()
    if rows:
        # Return the longest matching name (most specific match)
        best = max(rows, key=lambda r: len(r["customer_name"]))
        return best["customer_id"], best["customer_name"]
        
    # Fallback to token-based matching if no full name match
    _STOP = {"total", "invoice", "count", "amount", "of", "customer", "sum", "overall", "how", "much", "many", "value", "sales", "average"}
    words = [w for w in q_clean.split() if w not in _STOP and len(w) >= 3]
    if not words:
        return None
    
    for w in sorted(words, key=len, reverse=True):
        cur = conn.execute(
            "SELECT customer_id, customer_name FROM m_customers_t WHERE LOWER(customer_name) LIKE ? LIMIT 1",
            (f"%{w}%",)
        )
        row = cur.fetchone()
        if row:
            return row["customer_id"], row["customer_name"]
    return None

def find_matching_supplier(query_str: str, conn: sqlite3.Connection) -> Optional[tuple]:
    """Find a supplier ID and Name matching words in the query."""
    q_clean = re.sub(r"[^a-zA-Z0-9\s]", " ", query_str.lower())
    
    cur = conn.execute(
        "SELECT supplier_id, supplier_name FROM m_supplier_t WHERE ? LIKE '%' || LOWER(supplier_name) || '%'",
        (q_clean,)
    )
    rows = cur.fetchall()
    if rows:
        best = max(rows, key=lambda r: len(r["supplier_name"]))
        return best["supplier_id"], best["supplier_name"]

    _STOP = {"total", "invoice", "count", "amount", "of", "supplier", "sum", "overall", "how", "much", "many", "value", "vendor", "average"}
    words = [w for w in q_clean.split() if w not in _STOP and len(w) >= 3]
    if not words:
        return None

    for w in sorted(words, key=len, reverse=True):
        cur = conn.execute(
            "SELECT supplier_id, supplier_name FROM m_supplier_t WHERE LOWER(supplier_name) LIKE ? LIMIT 1",
            (f"%{w}%",)
        )
        row = cur.fetchone()
        if row:
            return row["supplier_id"], row["supplier_name"]
    return None

def run_aggregate_query(intent: str, query: str) -> Dict[str, Any]:
    """
    Parses and executes an aggregate query.
    Returns standard result dict containing direct answer text.
    """
    entity = intent.split(":")[1] if ":" in intent else "invoice"
    q_lower = query.lower()

    # Determine metric / operation using exact word boundaries
    is_count = any(re.search(rf"\b{re.escape(w)}\b", q_lower) for w in ["count", "how many", "number of"])
    is_average = any(re.search(rf"\b{re.escape(w)}\b", q_lower) for w in ["average", "avg", "mean"])
    
    # Determine value type for sum/avg
    col_name = "invoice_grand_total"
    val_label = "Grand Total"
    if "balance" in q_lower:
        col_name = "balance_amount"
        val_label = "Outstanding Balance"
    elif "paid" in q_lower or "payment" in q_lower:
        col_name = "paid_amount"
        val_label = "Paid Amount"

    # Default result structure
    result = {
        "query": query,
        "intent": intent,
        "result_type": "aggregate",
        "primary_results": [],
        "related_results": [],
        "found_data": [],
        "answer": "Could not compute aggregate.",
        "confidence": 90.0,
        "match_level": "High",
        "read_only": True,
        "sources": [],
        "next_suggestion": "Search customer",
        "summary": "",
        "answer_mode": "rule_based",
        "checked_sources": []
    }

    try:
        conn = _connect()

        # ─── CASE A: INVOICE OR SALES AGGREGATES ───
        if entity in ("invoice", "sales"):
            cust_match = find_matching_customer(query, conn)
            
            if cust_match:
                cust_id, cust_name = cust_match
                # Customer specific aggregate
                if is_count:
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM s_invoice_hdr_t WHERE ship_to_customer_id = ?",
                        (cust_id,)
                    )
                    count_val = cur.fetchone()[0]
                    ans = f"Answer:\nTotal Sales Invoices count for {cust_name} is: {count_val}"
                elif is_average:
                    cur = conn.execute(
                        f"SELECT AVG({col_name}) FROM s_invoice_hdr_t WHERE ship_to_customer_id = ?",
                        (cust_id,)
                    )
                    avg_val = cur.fetchone()[0] or 0.0
                    ans = f"Answer:\nAverage Invoice {val_label} for {cust_name} is: ₹{_fmt_num(avg_val)}"
                else:
                    cur = conn.execute(
                        f"SELECT SUM({col_name}) FROM s_invoice_hdr_t WHERE ship_to_customer_id = ?",
                        (cust_id,)
                    )
                    sum_val = cur.fetchone()[0] or 0.0
                    ans = f"Answer:\nTotal Invoice {val_label} for {cust_name} is: ₹{_fmt_num(sum_val)}"

                result["sources"].append({
                    "type": "Database Table", "name": "s_invoice_hdr_t", "record_id": "",
                    "field": "ship_to_customer_id", "source": f"database:s_invoice_hdr_t:cust_id={cust_id}",
                    "confidence": 1.0, "label": "Table", "tag": "DB"
                })
            else:
                # Overall/Global invoice aggregates
                if is_count:
                    cur = conn.execute("SELECT COUNT(*) FROM s_invoice_hdr_t")
                    count_val = cur.fetchone()[0]
                    ans = f"Answer:\nOverall Sales Invoices count is: {count_val}"
                elif is_average:
                    cur = conn.execute(f"SELECT AVG({col_name}) FROM s_invoice_hdr_t")
                    avg_val = cur.fetchone()[0] or 0.0
                    ans = f"Answer:\nOverall Average Sales Invoice {val_label} is: ₹{_fmt_num(avg_val)}"
                else:
                    cur = conn.execute(f"SELECT SUM({col_name}) FROM s_invoice_hdr_t")
                    sum_val = cur.fetchone()[0] or 0.0
                    ans = f"Answer:\nOverall Sales Invoice {val_label} is: ₹{_fmt_num(sum_val)}"

                result["sources"].append({
                    "type": "Database Table", "name": "s_invoice_hdr_t", "record_id": "",
                    "field": col_name if not is_count else "*", "source": "database:s_invoice_hdr_t:overall",
                    "confidence": 1.0, "label": "Table", "tag": "DB"
                })

            result["answer"] = ans
            result["summary"] = ans

        # ─── CASE B: SUPPLIER / PURCHASE AGGREGATES ───
        elif entity == "supplier":
            supp_match = find_matching_supplier(query, conn)
            
            # Purchase invoices use bill_number / net_amount in p_po_invoice_hdr_t
            po_col_name = "net_amount"
            po_val_label = "Net Amount"
            if "balance" in q_lower:
                po_col_name = "balance_amount"
                po_val_label = "Balance Amount"
                
            if supp_match:
                supp_id, supp_name = supp_match
                if is_count:
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM p_po_invoice_hdr_t WHERE supplier_id = ?",
                        (supp_id,)
                    )
                    count_val = cur.fetchone()[0]
                    ans = f"Answer:\nTotal Purchase Bills count for {supp_name} is: {count_val}"
                else:
                    cur = conn.execute(
                        f"SELECT SUM({po_col_name}) FROM p_po_invoice_hdr_t WHERE supplier_id = ?",
                        (supp_id,)
                    )
                    sum_val = cur.fetchone()[0] or 0.0
                    ans = f"Answer:\nTotal Purchase Bills {po_val_label} for {supp_name} is: ₹{_fmt_num(sum_val)}"

                result["sources"].append({
                    "type": "Database Table", "name": "p_po_invoice_hdr_t", "record_id": "",
                    "field": "supplier_id", "source": f"database:p_po_invoice_hdr_t:supplier_id={supp_id}",
                    "confidence": 1.0, "label": "Table", "tag": "DB"
                })
            else:
                if is_count:
                    cur = conn.execute("SELECT COUNT(*) FROM p_po_invoice_hdr_t")
                    count_val = cur.fetchone()[0]
                    ans = f"Answer:\nOverall Purchase Bills count is: {count_val}"
                else:
                    cur = conn.execute(f"SELECT SUM({po_col_name}) FROM p_po_invoice_hdr_t")
                    sum_val = cur.fetchone()[0] or 0.0
                    ans = f"Answer:\nOverall Purchase Bills {po_val_label} is: ₹{_fmt_num(sum_val)}"

                result["sources"].append({
                    "type": "Database Table", "name": "p_po_invoice_hdr_t", "record_id": "",
                    "field": po_col_name, "source": "database:p_po_invoice_hdr_t:overall",
                    "confidence": 1.0, "label": "Table", "tag": "DB"
                })

            result["answer"] = ans
            result["summary"] = ans

        # ─── CASE C: CUSTOMER REGISTRY AGGREGATES ───
        elif entity == "customer":
            if is_count:
                cur = conn.execute("SELECT COUNT(*) FROM m_customers_t")
                count_val = cur.fetchone()[0]
                ans = f"Answer:\nOverall Customers count in registry is: {count_val}"
            else:
                ans = "Please search customer details or query invoice amount aggregates."

            result["answer"] = ans
            result["summary"] = ans
            result["sources"].append({
                "type": "Database Table", "name": "m_customers_t", "record_id": "",
                "field": "*", "source": "database:m_customers_t:count",
                "confidence": 1.0, "label": "Table", "tag": "DB"
            })

        conn.close()

    except Exception as e:
        logger.error(f"Error executing aggregate query: {e}")
        result["answer"] = f"Error executing aggregate query: {str(e)}"
        result["summary"] = result["answer"]

    return result
