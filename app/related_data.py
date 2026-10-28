"""
Related Data Fetcher for MCP Data Assistant.

When a primary entity (customer/invoice/supplier) is found, this module
does follow-up SQL queries to pull cross-table related data:

- Customer → linked invoices, sales orders, receipts/payments, sites
- Invoice  → linked line items (products), customer details, dispatch status
- Supplier → linked purchase orders, payments

All queries are READ-ONLY (SELECT only).
"""

import sqlite3
import logging
from typing import Any, Dict, List, Optional
from app import config

logger = logging.getLogger(__name__)

_BAD = {"", "0", "0.0", "none", "null", "-"}


def _safe(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in _BAD else s


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_num(val: Any, decimals: int = 2) -> str:
    try:
        return f"{float(val or 0):,.{decimals}f}"
    except Exception:
        return str(val or 0)


# ──────────────────────────────────────────────────────────────────────────────
# CUSTOMER ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def get_customer_full_analysis(customer_id: int, customer_name: str) -> Dict[str, Any]:
    """
    Given a customer_id and name, pull all related data:
    - Invoice summary (count, total, paid, balance, last invoice)
    - Recent invoices list (last 5)
    - Sales order count
    - Receipt / payment summary
    """
    result = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "invoice_summary": {},
        "recent_invoices": [],
        "sales_order_summary": {},
        "receipt_summary": {},
        "analysis_text": "",
    }

    try:
        conn = _connect()

        # ── 1. Invoice summary via ship_to_customer_id ──
        try:
            cur = conn.execute("""
                SELECT
                    COUNT(*) as total_invoices,
                    SUM(invoice_grand_total) as total_value,
                    SUM(paid_amount) as total_paid,
                    SUM(balance_amount) as total_balance,
                    MAX(invoice_date) as last_invoice_date,
                    MIN(invoice_date) as first_invoice_date,
                    SUM(CASE WHEN UPPER(invoice_status)='APPROVED' THEN 1 ELSE 0 END) as approved_count,
                    SUM(CASE WHEN UPPER(invoice_status)='SAVE' THEN 1 ELSE 0 END) as pending_count
                FROM s_invoice_hdr_t
                WHERE ship_to_customer_id = ?
            """, (customer_id,))
            row = cur.fetchone()
            if row and row["total_invoices"]:
                result["invoice_summary"] = {
                    "total_invoices": int(row["total_invoices"] or 0),
                    "total_value": _fmt_num(row["total_value"]),
                    "total_paid": _fmt_num(row["total_paid"]),
                    "total_balance": _fmt_num(row["total_balance"]),
                    "last_invoice_date": _safe(row["last_invoice_date"]),
                    "first_invoice_date": _safe(row["first_invoice_date"]),
                    "approved_count": int(row["approved_count"] or 0),
                    "pending_count": int(row["pending_count"] or 0),
                }
        except Exception as e:
            logger.warning(f"Invoice summary error: {e}")

        # ── 2. Recent invoices ──
        try:
            cur2 = conn.execute("""
                SELECT invoice_number, invoice_date, invoice_grand_total,
                       paid_amount, balance_amount, invoice_status, approve_status
                FROM s_invoice_hdr_t
                WHERE ship_to_customer_id = ?
                ORDER BY invoice_date DESC
                LIMIT 5
            """, (customer_id,))
            for r in cur2.fetchall():
                result["recent_invoices"].append({
                    "invoice_number": _safe(r["invoice_number"]),
                    "date": _safe(r["invoice_date"]),
                    "total": _fmt_num(r["invoice_grand_total"]),
                    "paid": _fmt_num(r["paid_amount"]),
                    "balance": _fmt_num(r["balance_amount"]),
                    "status": _safe(r["invoice_status"] or r["approve_status"]),
                })
        except Exception as e:
            logger.warning(f"Recent invoices error: {e}")

        # ── 3. Sales order summary ──
        try:
            cur3 = conn.execute("""
                SELECT COUNT(*) as total_orders,
                       SUM(order_total) as total_value,
                       MAX(sales_order_date) as last_order_date
                FROM s_salesorder_hdr_t
                WHERE ship_to_customer_id = ?
            """, (customer_id,))
            row3 = cur3.fetchone()
            if row3 and row3["total_orders"]:
                result["sales_order_summary"] = {
                    "total_orders": int(row3["total_orders"] or 0),
                    "total_value": _fmt_num(row3["total_value"]),
                    "last_order_date": _safe(row3["last_order_date"]),
                }
        except Exception as e:
            logger.warning(f"Sales order summary error: {e}")

        # ── 4. Receipt / payment summary ──
        try:
            cur4 = conn.execute("""
                SELECT COUNT(*) as total_receipts,
                       SUM(batch_total_amount) as total_received,
                       MAX(receipt_date) as last_receipt_date
                FROM s_receipts_hdr_t
                WHERE customer_id = ?
            """, (customer_id,))
            row4 = cur4.fetchone()
            if row4 and row4["total_receipts"]:
                result["receipt_summary"] = {
                    "total_receipts": int(row4["total_receipts"] or 0),
                    "total_received": _fmt_num(row4["total_received"]),
                    "last_receipt_date": _safe(row4["last_receipt_date"]),
                }
        except Exception as e:
            logger.warning(f"Receipt summary error: {e}")

        conn.close()

    except Exception as e:
        logger.error(f"Customer full analysis error: {e}")

    # ── Build analysis text ──
    lines = []
    inv = result["invoice_summary"]
    if inv:
        lines.append("📊 Invoice Summary:")
        lines.append(f"  • Total Invoices : {inv.get('total_invoices', 0)}")
        lines.append(f"  • Total Value    : ₹{inv.get('total_value', '0.00')}")
        lines.append(f"  • Total Paid     : ₹{inv.get('total_paid', '0.00')}")
        lines.append(f"  • Balance Due    : ₹{inv.get('total_balance', '0.00')}")
        lines.append(f"  • Approved       : {inv.get('approved_count', 0)}  |  Pending: {inv.get('pending_count', 0)}")
        if inv.get("first_invoice_date"):
            lines.append(f"  • Date Range     : {inv['first_invoice_date']} → {inv.get('last_invoice_date', '-')}")
    else:
        lines.append("📊 Invoice Summary: No invoices found for this customer.")

    if result["recent_invoices"]:
        lines.append("")
        lines.append("🧾 Recent Invoices (last 5):")
        for inv_r in result["recent_invoices"]:
            lines.append(
                f"  • {inv_r['invoice_number']} | {inv_r['date']} | "
                f"Total: ₹{inv_r['total']} | Balance: ₹{inv_r['balance']} | {inv_r['status']}"
            )

    so = result["sales_order_summary"]
    if so:
        lines.append("")
        lines.append("📦 Sales Orders:")
        lines.append(f"  • Total Orders   : {so.get('total_orders', 0)}")
        lines.append(f"  • Total Value    : ₹{so.get('total_value', '0.00')}")
        lines.append(f"  • Last Order     : {so.get('last_order_date', '-')}")

    rec = result["receipt_summary"]
    if rec:
        lines.append("")
        lines.append("💳 Receipts / Payments:")
        lines.append(f"  • Total Receipts : {rec.get('total_receipts', 0)}")
        lines.append(f"  • Total Received : ₹{rec.get('total_received', '0.00')}")
        lines.append(f"  • Last Receipt   : {rec.get('last_receipt_date', '-')}")

    result["analysis_text"] = "\n".join(lines)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# INVOICE ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def get_invoice_full_analysis(invoice_hdr_id: int, invoice_number: str) -> Dict[str, Any]:
    """
    Given an invoice_hdr_id, pull:
    - Invoice line items (products, qty, price, total)
    - Customer details (name, contact)
    - Dispatch / delivery status
    - Payment / receipt status
    """
    result = {
        "invoice_hdr_id": invoice_hdr_id,
        "invoice_number": invoice_number,
        "line_items": [],
        "customer_info": {},
        "dispatch_info": {},
        "analysis_text": "",
    }

    try:
        conn = _connect()

        # ── 1. Invoice line items ──
        try:
            cur = conn.execute("""
                SELECT il.line_no, il.qty, il.unit_price, il.discount_percentage,
                       il.line_total, il.hsn_code, il.tax_amount, il.product_id,
                       p.product_alternate_name, p.product_code, p.concatenated_product
                FROM s_invoice_lines_t il
                LEFT JOIN m_products_t p ON il.product_id = p.product_id
                WHERE il.invoice_hdr_id = ?
                ORDER BY il.line_no
                LIMIT 20
            """, (invoice_hdr_id,))
            for r in cur.fetchall():
                product = (
                    _safe(r["product_alternate_name"])
                    or _safe(r["concatenated_product"])
                    or _safe(r["product_code"])
                    or f"Product ID #{r['product_id']}"
                )
                result["line_items"].append({
                    "line_no": r["line_no"],
                    "product": product,
                    "qty": _safe(r["qty"]),
                    "unit_price": _fmt_num(r["unit_price"]),
                    "discount": _safe(r["discount_percentage"]),
                    "tax": _fmt_num(r["tax_amount"]),
                    "line_total": _fmt_num(r["line_total"]),
                    "hsn_code": _safe(r["hsn_code"]),
                })
        except Exception as e:
            logger.warning(f"Invoice lines error: {e}")

        # ── 2. Customer info via ship_to_customer_id ──
        try:
            cur2 = conn.execute("""
                SELECT c.customer_name, c.customer_number, c.contact_person,
                       c.contact_number, c.billing_address, c.status
                FROM s_invoice_hdr_t ih
                JOIN m_customers_t c ON ih.ship_to_customer_id = c.customer_id
                WHERE ih.invoice_hdr_id = ?
            """, (invoice_hdr_id,))
            row2 = cur2.fetchone()
            if row2:
                result["customer_info"] = {
                    "name": _safe(row2["customer_name"]),
                    "number": _safe(row2["customer_number"]),
                    "contact_person": _safe(row2["contact_person"]),
                    "contact_number": _safe(row2["contact_number"]),
                    "billing_address": _safe(row2["billing_address"]),
                }
        except Exception as e:
            logger.warning(f"Customer join error: {e}")

        # ── 3. Dispatch info (via ship_to_customer_id from the invoice) ──
        try:
            cur3 = conn.execute("""
                SELECT COUNT(DISTINCT d.so_dispatch_hdr_id) as dispatch_count,
                       MAX(d.dispatch_date) as last_dispatch_date
                FROM s_dispatch_hdr_t d
                JOIN s_invoice_hdr_t ih ON d.ship_to_customer_id = ih.ship_to_customer_id
                WHERE ih.invoice_hdr_id = ?
            """, (invoice_hdr_id,))
            row3 = cur3.fetchone()
            if row3 and row3["dispatch_count"]:
                result["dispatch_info"] = {
                    "dispatch_count": int(row3["dispatch_count"] or 0),
                    "last_dispatch_date": _safe(row3["last_dispatch_date"]),
                }
        except Exception as e:
            logger.warning(f"Dispatch info error: {e}")

        conn.close()

    except Exception as e:
        logger.error(f"Invoice full analysis error: {e}")

    # ── Build analysis text ──
    lines = []

    cust = result["customer_info"]
    if cust:
        lines.append("👤 Customer Details:")
        lines.append(f"  • Name    : {cust.get('name', '?')}")
        lines.append(f"  • No      : {cust.get('number', '?')}")
        if cust.get("contact_person"):
            lines.append(f"  • Contact : {cust['contact_person']} | {cust.get('contact_number', '')}")
        if cust.get("billing_address"):
            addr = cust["billing_address"]
            if len(addr) > 80:
                addr = addr[:77] + "..."
            lines.append(f"  • Address : {addr}")

    if result["line_items"]:
        lines.append("")
        lines.append(f"📋 Invoice Line Items ({len(result['line_items'])} items):")
        for li in result["line_items"]:
            lines.append(
                f"  • Line {li['line_no']}: {li['product']} | "
                f"Qty: {li['qty']} | Price: ₹{li['unit_price']} | "
                f"Total: ₹{li['line_total']}"
            )
    else:
        lines.append("")
        lines.append("📋 Line Items: Not found.")

    disp = result["dispatch_info"]
    if disp and disp.get("dispatch_count"):
        lines.append("")
        lines.append("🚚 Dispatch:")
        lines.append(f"  • Dispatches     : {disp['dispatch_count']}")
        lines.append(f"  • Last Dispatched: {disp.get('last_dispatch_date', '-')}")

    result["analysis_text"] = "\n".join(lines)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# SUPPLIER ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def get_supplier_full_analysis(supplier_id: int, supplier_name: str) -> Dict[str, Any]:
    """
    Given a supplier_id, pull:
    - Purchase order summary
    - Recent purchase invoices / bills
    - Payment summary
    """
    result = {
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "po_summary": {},
        "recent_bills": [],
        "payment_summary": {},
        "analysis_text": "",
    }

    try:
        conn = _connect()

        # ── 1. PO summary ──
        try:
            cur = conn.execute("""
                SELECT COUNT(*) as total_po,
                       SUM(po_grand_total) as total_value,
                       MAX(po_date) as last_po_date
                FROM p_po_hdr_t
                WHERE supplier_id = ?
            """, (supplier_id,))
            row = cur.fetchone()
            if row and row["total_po"]:
                result["po_summary"] = {
                    "total_po": int(row["total_po"] or 0),
                    "total_value": _fmt_num(row["total_value"]),
                    "last_po_date": _safe(row["last_po_date"]),
                }
        except Exception as e:
            logger.warning(f"PO summary error: {e}")

        # ── 2. Recent purchase bills ──
        try:
            cur2 = conn.execute("""
                SELECT bill_number, bill_date, net_amount, approve_status
                FROM p_po_invoice_hdr_t
                WHERE supplier_id = ?
                ORDER BY bill_date DESC
                LIMIT 5
            """, (supplier_id,))
            for r in cur2.fetchall():
                result["recent_bills"].append({
                    "bill_number": _safe(r["bill_number"]),
                    "date": _safe(r["bill_date"]),
                    "amount": _fmt_num(r["net_amount"]),
                    "status": _safe(r["approve_status"]),
                })
        except Exception as e:
            logger.warning(f"Recent bills error: {e}")

        # ── 3. Payment summary ──
        try:
            cur3 = conn.execute("""
                SELECT COUNT(*) as total_payments,
                       SUM(payment_amount) as total_paid,
                       MAX(payment_date) as last_payment_date
                FROM p_payments_hdr_t
                WHERE supplier_id = ?
            """, (supplier_id,))
            row3 = cur3.fetchone()
            if row3 and row3["total_payments"]:
                result["payment_summary"] = {
                    "total_payments": int(row3["total_payments"] or 0),
                    "total_paid": _fmt_num(row3["total_paid"]),
                    "last_payment_date": _safe(row3["last_payment_date"]),
                }
        except Exception as e:
            logger.warning(f"Payment summary error: {e}")

        conn.close()

    except Exception as e:
        logger.error(f"Supplier full analysis error: {e}")

    # ── Build analysis text ──
    lines = []

    po = result["po_summary"]
    if po:
        lines.append("📦 Purchase Order Summary:")
        lines.append(f"  • Total POs    : {po.get('total_po', 0)}")
        lines.append(f"  • Total Value  : ₹{po.get('total_value', '0.00')}")
        lines.append(f"  • Last PO Date : {po.get('last_po_date', '-')}")

    if result["recent_bills"]:
        lines.append("")
        lines.append("🧾 Recent Purchase Bills:")
        for b in result["recent_bills"]:
            lines.append(f"  • {b['bill_number']} | {b['date']} | ₹{b['amount']} | {b['status']}")

    pay = result["payment_summary"]
    if pay:
        lines.append("")
        lines.append("💳 Payments to Supplier:")
        lines.append(f"  • Total Payments : {pay.get('total_payments', 0)}")
        lines.append(f"  • Total Paid     : ₹{pay.get('total_paid', '0.00')}")
        lines.append(f"  • Last Payment   : {pay.get('last_payment_date', '-')}")

    if not lines:
        lines.append("No related purchase data found for this supplier.")

    result["analysis_text"] = "\n".join(lines)
    return result
