"""
Read-only SQLite database reader.
Provides MCP-style tools for safe database access.
Run as __main__ to initialise the demo database.
"""
import sqlite3
import json
import re
import sys
import logging
import time
from pathlib import Path
from typing import Any

from app import config
from app.safety import check_query_safety, sanitize_table_name

logger = logging.getLogger("mcp_data_assistant.db_reader")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return a *read-only* connection to the SQLite database."""
    
    if config.MCP_MODE == "real" and "sample.db" in config.DB_NAME:
        raise FileNotFoundError("sample.db fallback blocked in real mode")
    if not config.DB_PATH.exists() or not config.DB_PATH.is_file():
        raise FileNotFoundError(f"Database file not found: {config.DB_NAME}")
    uri = f"file:{config.DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    # Safety: abort any single query that runs longer than QUERY_TIMEOUT_SECONDS
    # (protects the large real-mode DB from pathological/unbounded scans).
    _start = time.monotonic()
    def _abort_if_slow():
        return 1 if (time.monotonic() - _start) > config.QUERY_TIMEOUT_SECONDS else 0
    conn.set_progress_handler(_abort_if_slow, 100000)

    return conn


def _enrich_address(table_name: str, row_dict: dict, conn: sqlite3.Connection) -> dict:
    tbl = table_name.lower()
    if tbl == "m_customers_t":
        cust_id = row_dict.get("customer_id")
        if cust_id and (not row_dict.get("billing_address") or str(row_dict.get("billing_address")).strip() in ("0", "")):
            try:
                cur = conn.execute(
                    'SELECT address FROM m_customer_sites_t WHERE customer_id=? AND address IS NOT NULL AND address != "" AND address != "0" LIMIT 1',
                    (cust_id,)
                )
                r = cur.fetchone()
                if r and r[0]:
                    row_dict["billing_address"] = r[0]
            except Exception:
                pass
    elif tbl == "m_supplier_t":
        supp_id = row_dict.get("supplier_id")
        if supp_id and (not row_dict.get("billing_address") or str(row_dict.get("billing_address")).strip() in ("0", "")):
            try:
                cur = conn.execute(
                    'SELECT address FROM m_supplier_sites_t WHERE supplier_id=? AND address IS NOT NULL AND address != "" AND address != "0" LIMIT 1',
                    (supp_id,)
                )
                r = cur.fetchone()
                if r and r[0]:
                    row_dict["billing_address"] = r[0]
            except Exception:
                pass
    return row_dict


# ---------------------------------------------------------------------------
# MCP-style read-only tools
# ---------------------------------------------------------------------------

def list_tables() -> dict:
    """List all user tables in the database."""
    try:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [row["name"] for row in cur.fetchall()]
        conn.close()
        return {
            "source": "database:sqlite_master",
            "tables": tables,
            "count": len(tables),
        }
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "tables": [], "count": 0}


def get_table_schema(table_name: str) -> dict:
    """Return column info for a specific table."""
    table_name = sanitize_table_name(table_name)
    try:
        conn = _get_conn()
        cur = conn.execute(f"PRAGMA table_info({table_name})")
        cols = [
            {
                "cid": row["cid"],
                "name": row["name"],
                "type": row["type"],
                "notnull": bool(row["notnull"]),
                "pk": bool(row["pk"]),
            }
            for row in cur.fetchall()
        ]
        conn.close()
        return {
            "source": f"database:{table_name}",
            "table": table_name,
            "columns": cols,
            "column_count": len(cols),
        }
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "table": table_name, "columns": []}


def get_sample_records(table_name: str, limit: int = 5) -> dict:
    """Get sample records from a table."""
    table_name = sanitize_table_name(table_name)
    limit = min(limit, config.MAX_RESULTS)
    try:
        conn = _get_conn()
        cur = conn.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {
            "source": f"database:{table_name}",
            "table": table_name,
            "records": rows,
            "count": len(rows),
        }
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "records": [], "source": f"database:{table_name}"}


def discover_searchable_columns(table_name: str) -> list:
    """Discover text columns suitable for full-text search."""
    table_name = sanitize_table_name(table_name)
    try:
        conn = _get_conn()
        cur = conn.execute(f"PRAGMA table_info({table_name})")
        cols_info = cur.fetchall()
        conn.close()
        text_cols = [
            row["name"]
            for row in cols_info
            if "TEXT" in row["type"].upper() or "CHAR" in row["type"].upper() or row["type"] == ""
        ]
        return text_cols
    except Exception:
        return []


def search_records(table_name: str, query: str, limit: int = 10) -> dict:
    """Full-text search across all TEXT columns in a table."""
    table_name = sanitize_table_name(table_name)
    limit = min(limit, config.MAX_RESULTS)

    # Safety check on the search query itself
    safe, reason = check_query_safety(query)
    if not safe:
        return {"error": reason, "records": [], "source": f"database:{table_name}"}

    try:
        conn = _get_conn()
        # Discover text-ish columns
        cur = conn.execute(f"PRAGMA table_info({table_name})")
        cols_info = cur.fetchall()
        text_cols = [
            row["name"]
            for row in cols_info
            if "TEXT" in row["type"].upper() or "CHAR" in row["type"].upper()
            or row["type"] == ""
        ]
        all_cols = [row["name"] for row in cols_info]

        if not text_cols:
            # Fall back to fetching first `limit` rows
            cur = conn.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,))
        else:
            conditions = " OR ".join(
                [f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for c in text_cols]
            )
            params = [f"%{query.lower()}%"] * len(text_cols) + [limit]
            cur = conn.execute(
                f"SELECT * FROM {table_name} WHERE {conditions} LIMIT ?", params
            )

        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {
            "source": f"database:{table_name}",
            "table": table_name,
            "query": query,
            "records": rows,
            "count": len(rows),
        }
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "records": [], "source": f"database:{table_name}"}


# ---------------------------------------------------------------------------
# Exact-value lookup helpers (used by search_database_all)
# ---------------------------------------------------------------------------

# Keywords used to widen the table candidate set for exact-value lookups
# (invoice numbers, PO numbers, customer/supplier codes, etc.) without
# ever scanning all tables for ordinary/generic keyword searches.
_EXACT_VALUE_PRIORITY_KEYWORDS = [
    "invoice", "receipt", "reference", "number", "no", "code", "customer", "supplier"
]


def _is_exact_value_like(query: str) -> bool:
    """Heuristic: detect single-token alphanumeric codes like
    TVL25000001, ARM25000001, PO12345, CUST001 (no spaces, has a digit).
    """
    q = (query or "").strip()
    if not q or " " in q:
        return False
    if len(q) < 4:
        return False
    if not re.match("^[A-Za-z0-9_-]+" + chr(36), q):
        return False
    return any(ch.isdigit() for ch in q)


def _get_exact_value_candidate_tables(all_tables: list, max_candidates: int = 80) -> list:
    """For exact-value-like queries, widen the scan beyond the first
    MAX_TABLES_SCAN alphabetical tables by ranking tables (from
    db_profile.json, same source business_router/search_exact_value use)
    whose columns look like they'd hold codes/numbers/references. Falls
    back to the plain table list (still capped) if no profile exists.
    """
    profile_path = config.BASE_DIR / "data" / "registry" / "db_profile.json"
    if not profile_path.exists():
        return all_tables[:max_candidates]

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return all_tables[:max_candidates]

    all_tables_set = set(all_tables)
    profile_tables = profile.get("tables", [])

    # Primary-entity table names (invoice/customer/supplier/product/item)
    # rank above secondary tables like receipts/references, mirroring the
    # existing, already-correct priority used by search_exact_value().
    _PRIMARY_NAME_HINTS = ["invoice", "customer", "supplier", "product", "item"]

    scored = []
    for t in profile_tables:
        table_name = t.get("table_name", "")
        if table_name not in all_tables_set:
            continue
        cols = [c.lower() for c in (t.get("searchable_columns") or t.get("columns") or [])]
        record_count = t.get("record_count", 0)
        if record_count <= 0:
            continue
        kw_hits = sum(1 for kw in _EXACT_VALUE_PRIORITY_KEYWORDS if any(kw in c for c in cols))
        if kw_hits == 0:
            continue
        name_lower = table_name.lower()
        is_primary = any(hint in name_lower for hint in _PRIMARY_NAME_HINTS)
        primary_rank = 1 if is_primary else 0
        scored.append((primary_rank, kw_hits, record_count, table_name))

    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    ranked = [name for _, _, _, name in scored]

    # Keep remaining tables available (in original order) after the
    # ranked/priority ones, still bounded by max_candidates.
    remaining = [t for t in all_tables if t not in ranked]
    combined = ranked + remaining
    return combined[:max_candidates]


def search_database_all(query: str, limit: int = 20) -> dict:
    """Search for records matching the query in all text fields of all tables."""
    limit = min(limit, config.MAX_RESULTS)
    original_query = query
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

    # Strip question-style noise words so "vigenesh agencies how much id have show it"
    # becomes "vigenesh agencies" for a proper LIKE search.
    _NOISE_WORDS = {
        "how", "much", "many", "have", "show", "tell", "give", "what", "get",
        "find", "list", "search", "ids", "it", "its", "is", "are", "the", "a",
        "an", "and", "or", "for", "of", "in", "on", "at", "to", "by", "do",
        "does", "can", "check", "please", "me", "my", "us", "our", "you",
        "your", "we", "they", "them", "about", "with", "from", "like",
        "over", "out", "up", "down", "this", "that", "these", "those",
        "count", "total", "num", "all", "any",
        "there", "their", "whose", "his", "her", "here", "who", "whom", 
        "where", "why", "when", "print", "view", "display",
        "info", "information", "details", "detail", "record", "records", "data",
        "database", "db", "code", "codes", "name", "names", "id", "number", "numbers", "no", "nos"
    }
    _tokens_raw = query.lower().split()
    _meaningful_tokens = [t for t in _tokens_raw if t not in _NOISE_WORDS and len(t) >= 3 and not t.isdigit()]
    if _meaningful_tokens:
        query = " ".join(_meaningful_tokens)


    safe, reason = check_query_safety(query)
    if not safe:
        return {"error": reason, "records": [], "source": "database:all"}

    try:
        conn = _get_conn()
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [row["name"] for row in cur.fetchall()]

        # Performance guard (real mode): never scan every table for a
        # generic query. Tables whose name matches the search term are
        # tried first, then the list is capped at config.MAX_TABLES_SCAN.
        def _clean_str_pre(s: str) -> str:
            return "".join(ch for ch in s.lower() if ch.isalnum())
        _q_clean_pre = _clean_str_pre(query)
        _name_matches = [t for t in tables if _q_clean_pre in _clean_str_pre(t) or _clean_str_pre(t) in _q_clean_pre]
        _other_tables = [t for t in tables if t not in _name_matches]

        priority_tables = ["m_customers_t", "m_supplier_t", "s_invoice_hdr_t", "m_products_t"]
        _seen = set()
        _combined_priority = []
        for t in priority_tables:
            if t in tables and t not in _seen:
                _seen.add(t)
                _combined_priority.append(t)
        for t in _other_tables:
            if t not in _seen:
                _seen.add(t)
                _combined_priority.append(t)

        if _is_exact_value_like(query):
            # Exact-value lookups (invoice/PO/customer/supplier codes, etc.)
            # get a wider, profile-ranked candidate set instead of being
            # limited to the first MAX_TABLES_SCAN alphabetical tables.
            _widened = _get_exact_value_candidate_tables(tables, max_candidates=max(config.MAX_TABLES_SCAN, 80))
            # Always keep direct name-matches first, then widened ranked candidates.
            _seen_exact = set()
            _combined_exact = []
            for t in (_name_matches + _widened):
                if t not in _seen_exact:
                    _seen_exact.add(t)
                    _combined_exact.append(t)
            tables = _combined_exact
        else:
            tables = (_name_matches + [t for t in _combined_priority if t not in _name_matches])[:config.MAX_TABLES_SCAN]

        results = []
        for table in tables:
            cur = conn.execute(f'PRAGMA table_info("{table}")')
            cols_info = cur.fetchall()
            all_cols = [row["name"] for row in cols_info]
            text_cols = [
                row["name"]
                for row in cols_info
                if "TEXT" in row["type"].upper() or "CHAR" in row["type"].upper() or row["type"] == ""
            ]

            if not text_cols:
                text_cols = all_cols

            if not text_cols:
                continue

            # Clean/normalize strings for schema comparison
            def clean_str(s: str) -> str:
                return "".join(char for char in s.lower() if char.isalnum())
            
            q_clean = clean_str(query)
            query_in_table_or_cols = (
                q_clean in clean_str(table)
                or clean_str(table) in q_clean
                or any(q_clean in clean_str(c) or clean_str(c) in q_clean for c in all_cols)
            )

            words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 1]
            if not words:
                words = [query.lower()]

            col_clauses = []
            col_params = []
            for c in text_cols:
                word_clauses = [f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for _ in words]
                col_clauses.append("(" + " AND ".join(word_clauses) + ")")
                col_params.extend([f"%{w}%" for w in words])

            conditions = " OR ".join(col_clauses)
            params = col_params

            try:
                has_rowid = True
                if query_in_table_or_cols:
                    cur = conn.execute(f'SELECT rowid, * FROM "{table}" LIMIT ?', [limit])
                    rows = cur.fetchall()
                else:
                    cur = conn.execute(f'SELECT rowid, * FROM "{table}" WHERE {conditions} LIMIT ?', params + [limit])
                    rows = cur.fetchall()
                    if not rows and len(words) > 1:
                        # Fallback Layer 2: Match ANY word (OR search)
                        or_clauses = []
                        or_params = []
                        for c in text_cols:
                            word_or_clauses = [f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for _ in words]
                            or_clauses.append("(" + " OR ".join(word_or_clauses) + ")")
                            or_params.extend([f"%{w}%" for w in words])
                        cur = conn.execute(f'SELECT rowid, * FROM "{table}" WHERE {" OR ".join(or_clauses)} LIMIT ?', or_params + [limit])
                        rows = cur.fetchall()
                    if not rows and words:
                        # Fallback Layer 3: Longest word only
                        longest_w = max(words, key=len)
                        single_clauses = [f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for c in text_cols]
                        single_params = [f"%{longest_w}%"] * len(text_cols)
                        cur = conn.execute(f'SELECT rowid, * FROM "{table}" WHERE {" OR ".join(single_clauses)} LIMIT ?', single_params + [limit])
                        rows = cur.fetchall()
            except sqlite3.OperationalError:
                has_rowid = False
                if query_in_table_or_cols:
                    cur = conn.execute(f'SELECT * FROM "{table}" LIMIT ?', [limit])
                    rows = cur.fetchall()
                else:
                    cur = conn.execute(f'SELECT * FROM "{table}" WHERE {conditions} LIMIT ?', params + [limit])
                    rows = cur.fetchall()
                    if not rows and len(words) > 1:
                        # Fallback Layer 2: Match ANY word (OR search)
                        or_clauses = []
                        or_params = []
                        for c in text_cols:
                            word_or_clauses = [f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for _ in words]
                            or_clauses.append("(" + " OR ".join(word_or_clauses) + ")")
                            or_params.extend([f"%{w}%" for w in words])
                        cur = conn.execute(f'SELECT * FROM "{table}" WHERE {" OR ".join(or_clauses)} LIMIT ?', or_params + [limit])
                        rows = cur.fetchall()
                    if not rows and words:
                        # Fallback Layer 3: Longest word only
                        longest_w = max(words, key=len)
                        single_clauses = [f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for c in text_cols]
                        single_params = [f"%{longest_w}%"] * len(text_cols)
                        cur = conn.execute(f'SELECT * FROM "{table}" WHERE {" OR ".join(single_clauses)} LIMIT ?', single_params + [limit])
                        rows = cur.fetchall()

            for row in rows:
                row_dict = _enrich_address(table, dict(row), conn)
                row_id = "?"
                if has_rowid:
                    row_id = row[0]
                elif "id" in row_dict:
                    row_id = row_dict["id"]
                elif "rowid" in row_dict:
                    row_id = row_dict["rowid"]

                matched_col = None
                matched_val = None
                
                # Step 1: Look for column with ALL words
                for c in text_cols:
                    val = row_dict.get(c)
                    if val and all(w in str(val).lower() for w in words):
                        matched_col = c
                        matched_val = str(val)
                        break

                # Step 2: Fallback to column with ANY matched word
                if not matched_col:
                    for c in text_cols:
                        val = row_dict.get(c)
                        if val and any(w in str(val).lower() for w in words):
                            matched_col = c
                            matched_val = str(val)
                            break

                # Step 3: Check all cols as fallback
                if not matched_col and all_cols:
                    for c in all_cols:
                        val = row_dict.get(c)
                        if val and any(w in str(val).lower() for w in words):
                            matched_col = c
                            matched_val = str(val)
                            break

                if not matched_col:
                    # Prefer entity primary columns if available
                    _PREF_COLS = ["customer_name", "supplier_name", "invoice_number", "bill_number", "product_name", "product_alternate_name", "company_name"]
                    for pref in _PREF_COLS:
                        if pref in row_dict and row_dict.get(pref):
                            matched_col = pref
                            matched_val = str(row_dict[pref])
                            break
                if not matched_col:
                    matched_col = text_cols[0] if text_cols else (all_cols[0] if all_cols else "unknown")
                    matched_val = str(row_dict.get(matched_col, ""))

                # Score calculation
                score = 30.0
                if matched_val:
                    mv_lower = matched_val.lower()
                    q_clean_space = " ".join(words)
                    if q_clean_space == mv_lower or query.lower() == mv_lower:
                        score += 50.0
                    elif q_clean_space in mv_lower or all(w in mv_lower for w in words):
                        score += 30.0
                    else:
                        overlap = sum(1 for w in words if w in mv_lower)
                        score += overlap * 10.0

                # Score boost for table name matching query intent
                table_boost = 0.0
                orig_query_lower = original_query.lower()
                tbl_lower = table.lower()
                if "customer" in orig_query_lower and "customer" in tbl_lower:
                    table_boost += 100.0
                elif "invoice" in orig_query_lower and "invoice" in tbl_lower:
                    table_boost += 100.0
                elif "supplier" in orig_query_lower and "supplier" in tbl_lower:
                    table_boost += 100.0
                elif "item" in orig_query_lower or "product" in orig_query_lower:
                    if "product" in tbl_lower or "item" in tbl_lower:
                        table_boost += 100.0
                
                score += table_boost

                record_hit = {
                    "db_file_name": config.DB_NAME,
                    "table": table,
                    "id": row_id,
                    "row_id": row_id,
                    "field_name": matched_col,
                    "matched_column": matched_col,
                    "value": matched_val,
                    "matched_value": matched_val,
                    "row_preview": row_dict,
                    "score": score,
                    "read_only": True,
                    "source": f"database:{table}:id={row_id}",
                    "database": config.DB_NAME,
                    "company_code": row_dict.get("company_code") or row_dict.get("company"),
                    "document_type": row_dict.get("document_type"),
                    "aliases": row_dict.get("aliases") or "",
                    "mapped_to": row_dict.get("mapped_to") or "",
                    "raw_row": row_dict
                }
                results.append(record_hit)

        conn.close()
        # Sort all collected hits by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return {
            "source": "database:all",
            "query": query,
            "records": results[:limit],
            "count": len(results[:limit])
        }
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "records": [], "source": "database:all"}


def get_record_by_id(table_name: str, record_id: Any) -> dict:
    """Fetch a single record by primary key (assumed column: id)."""
    table_name = sanitize_table_name(table_name)
    try:
        conn = _get_conn()
        cur = conn.execute(
            f"SELECT * FROM {table_name} WHERE id = ? LIMIT 1", (record_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "source": f"database:{table_name}:id={record_id}",
                "table": table_name,
                "record": dict(row),
                "found": True,
            }
        return {
            "source": f"database:{table_name}",
            "table": table_name,
            "record": None,
            "found": False,
        }
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "found": False}


_OVERVIEW_CACHE = None
_OVERVIEW_CACHE_TIME = 0

def get_database_overview() -> dict:
    """Return a high-level summary of the database."""
    global _OVERVIEW_CACHE, _OVERVIEW_CACHE_TIME
    now = time.time()
    if _OVERVIEW_CACHE is not None and (now - _OVERVIEW_CACHE_TIME) < 60:
        return _OVERVIEW_CACHE

    try:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [row["name"] for row in cur.fetchall()]
        overview = []
        total_records = 0
        for t in tables[:30]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
            except Exception:
                cnt = 0
            total_records += cnt
            overview.append({"table": t, "record_count": cnt})
        conn.close()
        res = {
            "source": "database:overview",
            "database_path": config.DB_NAME,
            "database_type": "SQLite (Read-Only)",
            "table_count": len(tables),
            "total_records": total_records,
            "tables": overview,
        }
        _OVERVIEW_CACHE = res
        _OVERVIEW_CACHE_TIME = now
        return res
    except Exception as exc:
        logger.error("db_reader error in %s: %s", __name__, exc)
        return {"error": str(exc), "database_path": config.DB_NAME}


def get_sales_summary(limit: int = 5) -> dict:
    """Return read-only sales invoice count and amount summary."""
    table_name = "s_invoice_hdr_t"
    limit = max(1, min(limit, config.MAX_RESULTS))
    try:
        conn = _get_conn()
        cur = conn.execute(
            f'''
            SELECT
                COUNT(*) AS invoice_count,
                SUM(COALESCE(invoice_grand_total, 0)) AS total_sales_amount,
                SUM(COALESCE(paid_amount, 0)) AS total_paid_amount,
                SUM(COALESCE(balance_amount, 0)) AS total_balance_amount,
                SUM(CASE WHEN UPPER(COALESCE(invoice_status, '')) = 'APPROVED' THEN 1 ELSE 0 END) AS approved_count,
                MIN(invoice_date) AS first_invoice_date,
                MAX(invoice_date) AS latest_invoice_date
            FROM "{table_name}"
            '''
        )
        summary = dict(cur.fetchone())

        sample_rows = conn.execute(
            f'''
            SELECT
                rowid,
                invoice_hdr_id,
                invoice_number,
                invoice_date,
                invoice_status,
                invoice_grand_total,
                paid_amount,
                balance_amount,
                billing_to_address_txt,
                customer_name
            FROM "{table_name}"
            ORDER BY invoice_date DESC, invoice_hdr_id DESC
            LIMIT ?
            ''',
            [limit],
        ).fetchall()
        conn.close()

        samples = []
        for row in sample_rows:
            row_dict = dict(row)
            row_id = row_dict.get("invoice_hdr_id") or row_dict.get("rowid")
            samples.append({
                "db_file_name": config.DB_NAME,
                "table": table_name,
                "id": row_id,
                "row_id": row_id,
                "field_name": "invoice_number",
                "matched_column": "invoice_number",
                "value": row_dict.get("invoice_number"),
                "matched_value": row_dict.get("invoice_number"),
                "row_preview": row_dict,
                "score": 100.0,
                "read_only": True,
                "source": f"database:{table_name}:id={row_id}",
                "database": config.DB_NAME,
                "document_type": "Sales Invoice",
                "raw_row": row_dict,
            })

        return {
            "source": f"database:{table_name}:sales_summary",
            "database": config.DB_NAME,
            "table": table_name,
            "summary": summary,
            "records": samples,
            "count": int(summary.get("invoice_count") or 0),
        }
    except Exception as exc:
        logger.error("db_reader error in get_sales_summary: %s", exc)
        return {"error": str(exc), "source": f"database:{table_name}:sales_summary", "records": [], "count": 0}


def clean_entity_query(query: str, entity: str) -> str:
    """Strip noise/stop words from a query to extract the actual search term."""
    if not query:
        return query
        
    q = query.lower().strip("?.!,;\"'\u201c\u201d ")
    
    # Remove common starting prefixes
    prefixes = [
        "search for ", "search ", "find in database ", "find in db ", "find ", "show ",
        "list of ", "list ", "get ", "details of ", "detail of ", "lookup ", "look up "
    ]
    changed = True
    while changed:
        changed = False
        for p in prefixes:
            if q.startswith(p):
                q = q[len(p):].strip()
                changed = True
                break
                
    # -----------------------------------------------------------------------
    # Comprehensive stop words — includes question-style noise words so that
    # queries like "vigenesh agencies how much id have show it" correctly
    # reduce to just "vigenesh agencies".
    # -----------------------------------------------------------------------
    stop_words = {
        # Question words & helpers
        "show", "list", "get", "find", "what", "which", "where", "when", "how",
        "why", "is", "are", "the", "a", "an", "for", "of", "in", "on", "at",
        "to", "and", "or", "not", "all", "any", "me", "my", "can", "do", "does",
        "give", "tell", "about", "from", "with", "its", "their", "this", "that",
        "display", "fetch", "retrieve", "search", "return", "result", "results",
        "database", "dataset", "table", "record", "records", "overview", "format",
        "you", "have", "has", "had", "we", "our", "us", "your", "they", "them",
        "please", "could", "would", "should", "like", "under", "by",
        # Quantity/count question words
        "how", "much", "many", "count", "total", "number", "num",
        # Filler / interrogative
        "it", "its", "id", "ids", "detail", "details", "info",
        # Action words in questions
        "bring", "pull", "out", "up", "down", "over", "check", "see",
    }

    # Noise phrases to strip from the query to find the actual search term
    noise_phrases = [
        # Customer terms
        "customer names", "customer name", "customer details", "customer detail",
        "customer info", "customer profile", "customer address list", "customer address", "customer addresses", "customers", "customer",
        # Supplier terms
        "supplier names", "supplier name", "supplier details", "supplier detail",
        "supplier info", "supplier address list", "supplier address", "supplier addresses", "suppliers", "supplier", "vendor names", "vendor name",
        "vendor details", "vendor detail", "vendors", "vendor",
        # Invoice terms
        "invoice numbers", "invoice number", "invoice details", "invoice detail",
        "invoice info", "invoices", "invoice", "bill numbers", "bill number",
        "bill details", "bill detail", "bills", "bill",
        # Item terms
        "product names", "product name", "product details", "product detail",
        "product info", "products", "product", "item names", "item name",
        "item details", "item detail", "items", "item", "material", "stock",
        # General noise
        "address list", "address", "addresses", "details", "detail", "names", "name", "numbers", "codes", "code",
        "information", "data",
    ]
    
    for phrase in noise_phrases:
        pattern = rf"\b{re.escape(phrase)}\b"
        q = re.sub(pattern, " ", q)
        
    for sw in stop_words:
        pattern = rf"\b{re.escape(sw)}\b"
        q = re.sub(pattern, " ", q)
        
    # Remove preposition/connector words at boundaries
    q = q.strip()
    connectors = ["of", "for", "under", "like", "with", "by", "at", "in", "to", "about"]
    changed = True
    while changed:
        changed = False
        for conn in connectors:
            if q.startswith(conn + " "):
                q = q[len(conn):].strip()
                changed = True
            if q.endswith(" " + conn):
                q = q[:-len(conn)].strip()
                changed = True
                
    q = re.sub(r"\s+", " ", q).strip()
    
    return q


def search_business_entity(entity: str, query: str = None, limit: int = 20) -> dict:
    """Search for records of a specific business entity (customer, invoice, etc.).
    
    Uses 3-layer smart search:
    1. Full cleaned query LIKE search
    2. Token-by-token OR search (each word separately)
    3. Longest-token fallback (most specific single word)
    """
    from app.business_router import get_ranked_tables_for_entity
    limit = min(limit, config.MAX_RESULTS)
    
    original_query = query  # keep for token-based fallback
    if query:
        query = clean_entity_query(query, entity)
        logger.info("search_business_entity: cleaned query for %s is '%s'", entity, query)
        
    ranked_tables = get_ranked_tables_for_entity(entity)
    if not ranked_tables:
        return {"records": [], "count": 0, "source": f"business_entity:{entity}"}
        
    results = []
    conn = _get_conn()
    cursor = conn.cursor()
    
    if not query:
        # Generic entity search: return sample records from the top ranked table that has rows
        target_table = None
        for t in ranked_tables:
            if t["record_count"] > 0:
                target_table = t
                break
        if not target_table:
            target_table = ranked_tables[0]
            
        table_name = target_table["table_name"]
        
        try:
            cursor.execute(f'SELECT rowid, * FROM "{table_name}" LIMIT ?', [limit])
            rows = cursor.fetchall()
            has_rowid = True
        except sqlite3.OperationalError:
            try:
                cursor.execute(f'SELECT * FROM "{table_name}" LIMIT ?', [limit])
                rows = cursor.fetchall()
                has_rowid = False
            except Exception as e:
                conn.close()
                return {"error": str(e), "records": [], "count": 0}
                
        for row in rows:
            row_dict = _enrich_address(table_name, dict(row), conn)
            row_id = "?"
            if has_rowid:
                row_id = row[0]
            elif "id" in row_dict:
                row_id = row_dict["id"]
                
            matched_col = None
            # Prefer entity-specific primary columns first
            _PRIMARY_COL_PRIORITY = [
                "supplier_name", "supplier_number",    # supplier
                "customer_name", "customer_number",    # customer
                "invoice_number", "invoice_no",        # invoice
                "bill_number", "bill_no",              # purchase invoice
                "product_name", "product_code",        # product
                "company_name",                        # company
            ]
            for pref_col in _PRIMARY_COL_PRIORITY:
                if pref_col in row_dict and row_dict.get(pref_col):
                    v = str(row_dict[pref_col]).strip()
                    if v and v.lower() not in ("no", "none", "null", "0", ""):
                        matched_col = pref_col
                        break
            if not matched_col:
                for key_term in ["name", "number", "code", "no", "id"]:
                    for col in row_dict.keys():
                        if key_term in col.lower() and col.lower() not in ("customer_name",):
                            matched_col = col
                            break
                    if matched_col:
                        break
            if not matched_col:
                matched_col = list(row_dict.keys())[0] if row_dict.keys() else "unknown"
            matched_val = str(row_dict.get(matched_col, ""))
            
            hit = {
                "db_file_name": config.DB_NAME,
                "table": table_name,
                "id": row_id,
                "row_id": row_id,
                "field_name": matched_col,
                "matched_column": matched_col,
                "value": matched_val,
                "matched_value": matched_val,
                "row_preview": row_dict,
                "score": 100.0,
                "read_only": True,
                "source": f"database:{table_name}:id={row_id}",
                "database": config.DB_NAME,
                "company_code": row_dict.get("company_code") or row_dict.get("company"),
                "document_type": row_dict.get("document_type") or entity.title(),
                "aliases": row_dict.get("aliases") or "",
                "mapped_to": row_dict.get("mapped_to") or "",
                "raw_row": row_dict
            }
            results.append(hit)
            
        conn.close()
        return {
            "source": f"business_entity:{entity}",
            "entity": entity,
            "query": query,
            "records": results,
            "count": len(results)
        }
    else:
        # Search with query inside top-ranked tables
        search_tables = [t for t in ranked_tables if t["record_count"] > 0][:5]
        if not search_tables:
            search_tables = ranked_tables[:3]
            
        safe, reason = check_query_safety(query)
        if not safe:
            conn.close()
            return {"error": reason, "records": [], "count": 0}

        # Build token list for fallback searches (≥3 char, not pure digits)
        _QUERY_STOP = {"how", "much", "many", "have", "show", "tell", "give", "what",
                       "get", "find", "list", "search", "id", "ids", "it", "is",
                       "are", "the", "a", "an", "and", "or", "for", "of", "in",
                       "on", "at", "to", "by", "do", "does", "can", "check", "please"}
        raw_tokens = [
            t for t in (original_query or query).lower().split()
            if len(t) >= 3 and t not in _QUERY_STOP and not t.isdigit()
        ]
        # Sort tokens by length descending (most specific first)
        raw_tokens = sorted(set(raw_tokens), key=len, reverse=True)
            
        for t in search_tables:
            table_name = t["table_name"]
            table_score = t["score"]
            search_cols = t.get("searchable_columns", [])
            if not search_cols:
                search_cols = t.get("columns", [])
            if not search_cols:
                continue

            def _run_query(qstr, params_list):
                """Try rowid first, fallback without."""
                try:
                    cursor.execute(
                        f'SELECT rowid, * FROM "{table_name}" WHERE {qstr} LIMIT ?',
                        params_list + [limit]
                    )
                    return cursor.fetchall(), True
                except sqlite3.OperationalError:
                    try:
                        cursor.execute(
                            f'SELECT * FROM "{table_name}" WHERE {qstr} LIMIT ?',
                            params_list + [limit]
                        )
                        return cursor.fetchall(), False
                    except Exception:
                        return [], False

            def _make_hit(row, has_rowid, score_base, matched_q):
                row_dict = _enrich_address(table_name, dict(row), conn)
                row_id = row[0] if has_rowid else (row_dict.get("id") or "?")
                matched_col = None
                matched_val = None
                for col in search_cols:
                    val = row_dict.get(col)
                    if val and matched_q.lower() in str(val).lower():
                        matched_col = col
                        matched_val = str(val)
                        break
                if not matched_col:
                    for col in row_dict.keys():
                        val = row_dict.get(col)
                        if val and matched_q.lower() in str(val).lower():
                            matched_col = col
                            matched_val = str(val)
                            break
                if not matched_col:
                    matched_col = search_cols[0] if search_cols else "unknown"
                    matched_val = str(row_dict.get(matched_col, ""))
                # Score boost: exact or contains
                score = score_base
                if matched_val:
                    mv = matched_val.lower()
                    q_ = matched_q.lower()
                    if q_ == mv:
                        score += 50.0
                    elif q_ in mv:
                        score += 30.0
                    else:
                        # partial word overlap bonus
                        overlap = sum(1 for w in q_.split() if len(w) >= 3 and w in mv)
                        score += overlap * 10.0
                return {
                    "db_file_name": config.DB_NAME,
                    "table": table_name,
                    "id": row_id,
                    "row_id": row_id,
                    "field_name": matched_col,
                    "matched_column": matched_col,
                    "value": matched_val,
                    "matched_value": matched_val,
                    "row_preview": row_dict,
                    "score": score,
                    "read_only": True,
                    "source": f"database:{table_name}:id={row_id}",
                    "database": config.DB_NAME,
                    "company_code": row_dict.get("company_code") or row_dict.get("company"),
                    "document_type": row_dict.get("document_type") or entity.title(),
                    "aliases": row_dict.get("aliases") or "",
                    "mapped_to": row_dict.get("mapped_to") or "",
                    "raw_row": row_dict
                }

            # -----------------------------------------------------------
            # Layer 1: Full cleaned query LIKE search
            # -----------------------------------------------------------
            cond1 = " OR ".join([f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for c in search_cols])
            p1 = [f"%{query.lower()}%"] * len(search_cols)
            rows1, has_rid1 = _run_query(cond1, p1)
            for row in rows1:
                results.append(_make_hit(row, has_rid1, table_score + 30.0, query))

            if not rows1 and raw_tokens:
                # -----------------------------------------------------------
                # Layer 2: Token-by-token OR search
                # Each meaningful word searched independently across all cols
                # -----------------------------------------------------------
                seen_row_ids = set()
                for tok in raw_tokens:
                    cond2 = " OR ".join([f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for c in search_cols])
                    p2 = [f"%{tok}%"] * len(search_cols)
                    rows2, has_rid2 = _run_query(cond2, p2)
                    for row in rows2:
                        row_dict = dict(row)
                        row_id = row[0] if has_rid2 else (row_dict.get("id") or "?")
                        if row_id not in seen_row_ids:
                            seen_row_ids.add(row_id)
                            results.append(_make_hit(row, has_rid2, table_score + 15.0, tok))

                if not results and len(raw_tokens) > 0:
                    # -----------------------------------------------------------
                    # Layer 3: Longest single token fallback
                    # Use the longest (most specific) token as a last resort
                    # -----------------------------------------------------------
                    longest_tok = raw_tokens[0]  # already sorted by length desc
                    cond3 = " OR ".join([f'LOWER(CAST("{c}" AS TEXT)) LIKE ?' for c in search_cols])
                    p3 = [f"%{longest_tok}%"] * len(search_cols)
                    rows3, has_rid3 = _run_query(cond3, p3)
                    for row in rows3:
                        results.append(_make_hit(row, has_rid3, table_score + 5.0, longest_tok))
                        
        conn.close()
        results.sort(key=lambda x: x["score"], reverse=True)
        # Deduplicate by (table, row_id)
        seen = set()
        deduped = []
        for r in results:
            key = (r.get("table"), r.get("row_id"))
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return {
            "source": f"business_entity:{entity}",
            "entity": entity,
            "query": query,
            "records": deduped[:limit],
            "count": len(deduped[:limit])
        }


def search_exact_value(value: Any, limit: int = 20) -> dict:
    """Search for exact match of value in all searchable columns of non-empty tables."""
    limit = min(limit, config.MAX_RESULTS)
    val_lower = str(value).strip().lower()
    if not val_lower:
        return {"records": [], "count": 0, "source": "database:exact"}
        
    profile_path = config.BASE_DIR / "data" / "registry" / "db_profile.json"
    if not profile_path.exists():
        return {"records": [], "count": 0, "source": "database:exact"}
        
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return {"records": [], "count": 0, "source": "database:exact"}
        
    tables = profile.get("tables", [])
    results = []
    
    def table_priority(t):
        name = t["table_name"].lower()
        if "invoice" in name or "customer" in name or "supplier" in name or "product" in name or "item" in name:
            return 0
        return 1
        
    sorted_tables = sorted([t for t in tables if t.get("record_count", 0) > 0], key=table_priority)
    
    conn = _get_conn()
    cursor = conn.cursor()
    
    for t in sorted_tables:
        table_name = t["table_name"]
        search_cols = t.get("searchable_columns", [])
        if not search_cols:
            search_cols = t.get("columns", [])
        if not search_cols:
            continue
            
        conditions = []
        params = []
        for col in search_cols:
            conditions.append(f'LOWER(CAST("{col}" AS TEXT)) = ?')
            params.append(val_lower)
            
        query_str = f'SELECT rowid, * FROM "{table_name}" WHERE {" OR ".join(conditions)} LIMIT ?'
        
        try:
            cursor.execute(query_str, params + [limit - len(results)])
            rows = cursor.fetchall()
            has_rowid = True
        except sqlite3.OperationalError:
            query_str = f'SELECT * FROM "{table_name}" WHERE {" OR ".join(conditions)} LIMIT ?'
            try:
                cursor.execute(query_str, params + [limit - len(results)])
                rows = cursor.fetchall()
                has_rowid = False
            except Exception:
                continue
        except Exception:
            continue
            
        for row in rows:
            row_dict = dict(row)
            row_id = "?"
            if has_rowid:
                row_id = row[0]
            elif "id" in row_dict:
                row_id = row_dict["id"]
                
            matched_col = None
            matched_val = None
            for col in search_cols:
                v = row_dict.get(col)
                if v is not None and str(v).strip().lower() == val_lower:
                    matched_col = col
                    matched_val = str(v)
                    break
            if not matched_col:
                matched_col = search_cols[0] if search_cols else "unknown"
                matched_val = str(row_dict.get(matched_col, ""))
                
            hit = {
                "db_file_name": config.DB_NAME,
                "table": table_name,
                "id": row_id,
                "row_id": row_id,
                "field_name": matched_col,
                "matched_column": matched_col,
                "value": matched_val,
                "matched_value": matched_val,
                "row_preview": row_dict,
                "score": 100.0,
                "read_only": True,
                "source": f"database:{table_name}:id={row_id}",
                "database": config.DB_NAME,
                "company_code": row_dict.get("company_code") or row_dict.get("company"),
                "document_type": row_dict.get("document_type") or "Record",
                "aliases": row_dict.get("aliases") or "",
                "mapped_to": row_dict.get("mapped_to") or "",
                "raw_row": row_dict
            }
            results.append(hit)
            
        if len(results) >= limit:
            break
            
    conn.close()
    return {
        "source": "database:exact",
        "records": results[:limit],
        "count": len(results[:limit])
    }


def get_table_sample(table_name: str, limit: int = 10) -> dict:
    """Return sample records from the specified table name."""
    return get_sample_records(table_name, limit)


# ---------------------------------------------------------------------------
# Demo database initialisation
# ---------------------------------------------------------------------------

def init_demo_db():
    """Create and populate the demo SQLite database."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Use a *writable* connection just for setup
    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.cursor()

    # ---- companies ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            country TEXT,
            industry TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    companies = [
        ("GLS", "GLS Group (Germany)", "DE", "Logistics"),
        ("POPRINT", "PO Print Supplies Ltd", "GB", "Printing & Stationery"),
        ("TURBOMACH", "TurboMach Industrial", "US", "Manufacturing"),
        ("MDE", "MDE ERP Solutions", "IN", "Software / ERP"),
        ("ALPHALOG", "AlphaLog Freight", "NL", "Freight & Logistics"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO companies (code, name, country, industry) VALUES (?,?,?,?)",
        companies,
    )

    # ---- datasets ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            company_code TEXT,
            document_type TEXT,
            file_path TEXT,
            record_count INTEGER DEFAULT 0,
            last_updated TEXT DEFAULT (datetime('now'))
        )
    """)
    datasets = [
        ("GLS_Sales_Invoice", "GLS", "Sales Invoice", "data/datasets/GLS_Sales_Invoice.json", 12),
        ("POPRINT_Training", "POPRINT", "Purchase Order", "data/datasets/POPRINT_Training.json", 8),
        ("company_mappings", "ALL", "Mapping", "data/datasets/company_mappings.json", 5),
        ("TURBOMACH_Forms", "TURBOMACH", "Work Order", None, 6),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO datasets (name, company_code, document_type, file_path, record_count) VALUES (?,?,?,?,?)",
        datasets,
    )

    # ---- training_mappings ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT NOT NULL,
            document_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            aliases TEXT,
            mapped_to TEXT,
            confidence REAL DEFAULT 0.0,
            status TEXT DEFAULT 'active',
            notes TEXT
        )
    """)
    mappings = [
        # GLS Sales Invoice
        ("GLS","Sales Invoice","Invoice Number","Invoice No.|Inv No.|Invoice #|Rechnungsnummer","sales_form_invoice_no",0.72,"active","Common alias mismatch: 'Invoice No.' not yet linked"),
        ("GLS","Sales Invoice","Invoice Date","Date|Inv Date|Rechnungsdatum","sales_form_invoice_date",0.91,"active","High confidence"),
        ("GLS","Sales Invoice","Vendor Name","Supplier|Lieferant|From","sales_form_vendor_name",0.85,"active",""),
        ("GLS","Sales Invoice","Total Amount","Grand Total|Betrag|Amount Due|Gesamtbetrag","sales_form_total_amount",0.88,"active",""),
        ("GLS","Sales Invoice","VAT Number","USt-IdNr.|Tax No.|VAT ID","sales_form_vat_number",0.65,"active","May be missing in older docs"),
        ("GLS","Sales Invoice","PO Reference","PO Number|Purchase Order|Bestellnummer","sales_form_po_reference",0.78,"active",""),
        # POPRINT Purchase Order
        ("POPRINT","Purchase Order","PO Number","Order No.|Purchase Order No.|PO#","po_form_po_number",0.93,"active","High confidence"),
        ("POPRINT","Purchase Order","Supplier Code","Vendor Code|Supplier ID","po_form_supplier_code",0.80,"active",""),
        ("POPRINT","Purchase Order","Line Items","Items|Products|Order Lines","po_form_line_items",0.70,"active","Tabular extraction needed"),
        ("POPRINT","Purchase Order","Delivery Date","Expected Delivery|Ship Date|ETA","po_form_delivery_date",0.82,"active",""),
        # TURBOMACH Work Order
        ("TURBOMACH","Work Order","Work Order No.","WO#|Job No.|Job Number","wf_work_order_no",0.89,"active",""),
        ("TURBOMACH","Work Order","Part Number","Part No.|PN|Bauteilnummer","wf_part_number",0.84,"active",""),
        ("TURBOMACH","Work Order","Technician","Tech|Engineer|Assigned To","wf_technician",0.76,"active",""),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO training_mappings "
        "(company_code,document_type,field_name,aliases,mapped_to,confidence,status,notes) "
        "VALUES (?,?,?,?,?,?,?,?)",
        mappings,
    )

    # ---- ocr_results ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ocr_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id TEXT NOT NULL,
            company_code TEXT,
            document_type TEXT,
            field_name TEXT,
            extracted_value TEXT,
            confidence REAL,
            page_number INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            processed_at TEXT DEFAULT (datetime('now'))
        )
    """)
    ocr_rows = [
        ("upload_2024052101","GLS","Sales Invoice","Invoice Number","INV-2024-00421",0.324,1,"low_confidence"),
        ("upload_2024052101","GLS","Sales Invoice","Invoice Date","21.05.2024",0.961,1,"ok"),
        ("upload_2024052101","GLS","Sales Invoice","Total Amount","EUR 4,812.50",0.918,1,"ok"),
        ("upload_2024052101","GLS","Sales Invoice","Vendor Name","GLS Germany GmbH",0.894,1,"ok"),
        ("upload_2024052101","GLS","Sales Invoice","VAT Number","DE812345678",0.711,1,"ok"),
        ("upload_2024052102","POPRINT","Purchase Order","PO Number","PO-2024-00892",0.978,1,"ok"),
        ("upload_2024052102","POPRINT","Purchase Order","Supplier Code","SUP-441",0.855,1,"ok"),
        ("upload_2024052102","POPRINT","Purchase Order","Delivery Date","2024-06-10",0.830,1,"ok"),
        ("upload_2024052103","TURBOMACH","Work Order","Work Order No.","WO-TM-20240519",0.921,1,"ok"),
        ("upload_2024052103","TURBOMACH","Work Order","Part Number","TM-SHAFT-0042",0.876,1,"ok"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO ocr_results "
        "(upload_id,company_code,document_type,field_name,extracted_value,confidence,page_number,status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ocr_rows,
    )

    # ---- validation_results ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS validation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id TEXT NOT NULL,
            company_code TEXT,
            document_type TEXT,
            field_name TEXT,
            extracted_value TEXT,
            expected_pattern TEXT,
            validation_status TEXT,
            confidence REAL,
            failure_reason TEXT,
            validated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    val_rows = [
        ("upload_2024052101","GLS","Sales Invoice","Invoice Number","INV-2024-00421",r"INV-\d{4}-\d+","FAIL",0.324,"Alias 'Invoice No.' not mapped; low OCR confidence 32.4%"),
        ("upload_2024052101","GLS","Sales Invoice","Invoice Date","21.05.2024",r"\d{2}\.\d{2}\.\d{4}","PASS",0.961,""),
        ("upload_2024052101","GLS","Sales Invoice","Total Amount","EUR 4,812.50",r"[A-Z]{3}\s[\d,\.]+","PASS",0.918,""),
        ("upload_2024052102","POPRINT","Purchase Order","PO Number","PO-2024-00892",r"PO-\d{4}-\d+","PASS",0.978,""),
        ("upload_2024052102","POPRINT","Purchase Order","Delivery Date","2024-06-10",r"\d{4}-\d{2}-\d{2}","PASS",0.830,""),
        ("upload_2024052103","TURBOMACH","Work Order","Work Order No.","WO-TM-20240519",r"WO-[A-Z]+-\d+","PASS",0.921,""),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO validation_results "
        "(upload_id,company_code,document_type,field_name,extracted_value,expected_pattern,validation_status,confidence,failure_reason) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        val_rows,
    )

    conn.commit()
    conn.close()
    print(f"[OK] Demo database initialised at: {config.DB_PATH}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--init-demo-db" in sys.argv:
        init_demo_db()
    else:
        print("Usage: python -m app.db_reader --init-demo-db")
