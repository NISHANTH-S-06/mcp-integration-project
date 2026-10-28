import os
import sys
import sqlite3
from pathlib import Path

def test_imports():
    try:
        from app.main import app
        from app import db_reader, dataset_reader, llm_client, safety
        from app.config import DB_PATH, DATASETS_DIR, BLOCKED_SQL_KEYWORDS
        from app.mcp_client import MCPClient
        from app import mcp_server, intent_router, relevance, response_builder
        print("[OK] Imports successful")
        return True
    except Exception as e:
        print(f"[FAIL] Imports failed: {e}")
        return False

def test_config():
    try:
        from app.config import DB_PATH, DATASETS_DIR
        assert DB_PATH is not None
        assert DATASETS_DIR is not None
        print(f"[OK] Config loaded. DB_PATH: {DB_PATH}, DATASETS_DIR: {DATASETS_DIR}")
        return True
    except Exception as e:
        print(f"[FAIL] Config load failed: {e}")
        return False

def test_datasets_folder():
    from app.config import DATASETS_DIR
    if DATASETS_DIR.exists() and DATASETS_DIR.is_dir():
        print(f"[OK] Dataset folder exists at {DATASETS_DIR}")
        return True
    else:
        print(f"[FAIL] Dataset folder does not exist at {DATASETS_DIR}")
        return False

def test_datasets_readable():
    import json
    from app.config import DATASETS_DIR, MCP_MODE
    if MCP_MODE == "real":
        print("[SKIP] Skipping datasets readability check in real mode")
        return True
    try:
        files = list(DATASETS_DIR.glob("*.json"))
        if not files:
            print("[FAIL] No JSON datasets found")
            return False
        for f in files:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                print(f"  - Read {f.name} success: {len(data.get('records', []))} records")
        print("[OK] JSON datasets readable")
        return True
    except Exception as e:
        print(f"[FAIL] JSON datasets not readable: {e}")
        return False

def test_db_exists():
    from app.config import DB_PATH
    if DB_PATH.exists() and DB_PATH.is_file():
        print(f"[OK] SQLite DB exists at {DB_PATH}")
        return True
    else:
        print(f"[FAIL] SQLite DB does not exist at {DB_PATH}")
        return False

def test_expected_tables():
    from app.config import DB_PATH, MCP_MODE
    if MCP_MODE == "real":
        expected = {"m_customers_t", "s_invoice_hdr_t", "m_supplier_t", "m_products_t"}
    else:
        expected = {"companies", "datasets", "training_mappings", "ocr_results", "validation_results"}
    try:
        # SQLite read-only connection
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        missing = expected - tables
        if missing:
            print(f"[FAIL] Missing expected tables: {missing}")
            return False
        print(f"[OK] All expected tables exist: {expected}")
        return True
    except Exception as e:
        print(f"[FAIL] DB table check failed: {e}")
        return False

def test_readonly_safety():
    from app.safety import check_query_safety, check_write_intent
    blocked_statements = [
        "INSERT INTO companies (code) VALUES ('TEST')",
        "UPDATE training_mappings SET confidence = 1.0",
        "DELETE FROM ocr_results WHERE id = 1",
        "DROP TABLE validation_results",
        "ALTER TABLE companies ADD COLUMN test TEXT",
        "CREATE TABLE test_table (id INTEGER)",
        "REPLACE INTO datasets (name) VALUES ('TEST')",
        "TRUNCATE TABLE ocr_results",
        "save mapping",
        "change database",
        "fix this record"
    ]
    
    all_blocked = True
    for stmt in blocked_statements:
        safe, reason = check_query_safety(stmt)
        intent = check_write_intent(stmt)
        if safe and not intent:
            print(f"  - [FAIL] Statement allowed: {stmt}")
            all_blocked = False
        else:
            print(f"  - [OK] Statement blocked correctly: {stmt}")
            
    if all_blocked:
        print("[OK] Read-only safety blocks verified for all tests")
        return True
    else:
        print("[FAIL] Some write operations were not blocked")
        return False

def test_no_risky_tools():
    try:
        from app.mcp_server import list_tools
        tools = list_tools()
        
        allowed_tools = {
            "list_datasets", "search_dataset", "get_dataset_record", "get_company_mapping", "get_dataset_overview",
            "get_database_overview", "list_tables", "get_table_schema", "search_records", "get_validation_results",
            "get_training_mappings", "get_sample_records", "search_database_all", "get_sales_summary",
            "get_real_data_status", "get_db_profile", "get_dataset_profile", "search_datasets_all",
            "list_active_sources", "list_latest_imports", "get_company_datasets",
            "search_business_entity", "search_exact_value"
        }
        
        has_risky_tool = False
        for t in tools:
            t_name = t["name"]
            if t_name not in allowed_tools:
                print(f"  - [FAIL] Non-standard/risky tool registered: {t_name}")
                has_risky_tool = True
                
        if not has_risky_tool:
            print("[OK] No risky tools detected in local MCP server.")
            return True
        else:
            return False
    except Exception as e:
        print(f"[FAIL] Risky tools check failed: {e}")
        return False

def test_mcp_imports():
    try:
        from app.mcp_server import call_tool, list_tools
        from app.mcp_client import MCPClient
        client = MCPClient()
        assert len(client.list_tools()) > 0
        print("[OK] MCP server/client imports and tools listing successful")
        return True
    except Exception as e:
        print(f"[FAIL] MCP imports check failed: {e}")
        return False

def test_intent_router():
    try:
        from app.intent_router import classify_intent
        assert classify_intent("hi") == "greeting", f"Got: {classify_intent('hi')}"
        assert classify_intent("hello") == "greeting", f"Got: {classify_intent('hello')}"
        assert classify_intent("Show validation result") == "validation_query", f"Got: {classify_intent('Show validation result')}"
        assert classify_intent("Show database overview") == "database_overview", f"Got: {classify_intent('Show database overview')}"
        assert classify_intent("customer id") == "mapping_query", f"Got: {classify_intent('customer id')}"
        assert classify_intent("Update GLS mapping and delete old record") == "write_attempt", f"Got: {classify_intent('Update GLS mapping and delete old record')}"
        assert classify_intent("save mapping") == "write_attempt", f"Got: {classify_intent('save mapping')}"
        assert classify_intent("change database") == "write_attempt", f"Got: {classify_intent('change database')}"
        assert classify_intent("list database tables") == "table_list", f"Got: {classify_intent('list database tables')}"
        # Business entity search tests
        assert classify_intent("Search customer") == "business_entity_search:customer", f"Got: {classify_intent('Search customer')}"
        assert classify_intent("Search invoice") == "business_entity_search:invoice", f"Got: {classify_intent('Search invoice')}"
        assert classify_intent("Search supplier") == "business_entity_search:supplier", f"Got: {classify_intent('Search supplier')}"
        assert classify_intent("Search item") == "business_entity_search:item", f"Got: {classify_intent('Search item')}"
        # Exact value search
        assert classify_intent("TVL25000001") == "exact_value_search", f"Got: {classify_intent('TVL25000001')}"
        print("[OK] Intent router tests passed")
        return True
    except Exception as e:
        print(f"[FAIL] Intent router tests failed: {e}")
        return False

def test_relevance_ranking():
    try:
        from app.relevance import score_hit
        gls_hit = {
            "company_code": "GLS",
            "document_type": "Sales Invoice",
            "field_name": "Invoice Number",
            "aliases": "Invoice No.|Inv No.|Invoice #|Rechnungsnummer",
            "mapped_to": "sales_form_invoice_no"
        }
        po_hit = {
            "company_code": "POPRINT",
            "document_type": "Purchase Order",
            "field_name": "PO Number",
            "aliases": "Order No.|Purchase Order No.|PO#",
            "mapped_to": "po_form_po_number"
        }
        
        # Invoice query -> GLS high, PO penalized
        q_inv = "Why invoice number not filling?"
        gls_score = score_hit(gls_hit, q_inv)
        po_score = score_hit(po_hit, q_inv)
        assert gls_score >= 45, f"GLS score low: {gls_score}"
        assert po_score < 45, f"PO score not penalized: {po_score}"
        
        # PO query -> PO high, GLS penalized
        q_po = "po number"
        po_score_2 = score_hit(po_hit, q_po)
        gls_score_2 = score_hit(gls_hit, q_po)
        assert po_score_2 >= 45, f"PO score low: {po_score_2}"
        assert gls_score_2 < 45, f"GLS score not penalized: {gls_score_2}"
        
        print("[OK] Relevance ranking tests passed")
        return True
    except Exception as e:
        print(f"[FAIL] Relevance ranking tests failed: {e}")
        return False

def test_response_builder():
    try:
        from app.response_builder import build_response
        from app.config import MCP_MODE
        
        # 1. Greeting check
        r_greet = build_response("greeting", "hi", [], {}, [])
        if MCP_MODE == "real":
            assert "safely in read-only mode" in r_greet["answer"], "Failed greeting message in real mode"
        else:
            assert "Try asking:" in r_greet["answer"], "Failed greeting message"
        
        # 2. Unknown check
        r_unk = build_response("unknown", "server number", [], {}, [])
        if MCP_MODE == "real":
            assert "No exact match found" in r_unk["answer"], f"Failed unknown message in real mode. Got: {r_unk['answer'][:100]}"
        else:
            assert "I could not find an exact match" in r_unk["answer"], f"Failed unknown message. Got: {r_unk['answer'][:100]}"
        
        # 3. Safety response check
        r_safety = build_response("write_attempt", "drop table companies", [], {}, [])
        assert "read-only" in r_safety["answer"], "Failed safety message"
        
        # 4. Validation query summary format check
        r_val = build_response("validation_query", "show validation result", [], {}, [{"id": 1, "validation_status": "PASS", "confidence": 0.9, "field_name": "Invoice Date"}])
        assert "Total validations:" in r_val["answer"]
        assert "Source: validation_results table" in r_val["answer"]
        assert "validation_results" in [s["name"] for s in r_val["sources"]]
        
        # 5. Validation query empty check
        r_val_empty = build_response("validation_query", "show validation result", [], {}, [])
        assert r_val_empty["answer"] == "No validation records found in validation_results table."
        
        print("[OK] Response builder tests passed")
        return True
    except Exception as e:
        print(f"[FAIL] Response builder check failed: {e}")
        return False

def test_real_db_dir():
    try:
        p = Path("data/real_db")
        assert p.exists() and p.is_dir()
        print("[OK] data/real_db directory exists")
        return True
    except Exception as e:
        print(f"[FAIL] data/real_db directory check failed: {e}")
        return False

def test_db_path_blocking():
    import subprocess
    from app.config import BASE_DIR
    cmd = [sys.executable, "-c", "import os; os.environ['SQLITE_DB_PATH'] = '../outside.db'; from app import config"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    if result.returncode != 0 and "Security block" in result.stderr:
        print("[OK] DB path outside data blocked correctly")
        return True
    else:
        print(f"[FAIL] DB path outside data was NOT blocked correctly: {result.stderr} / returncode {result.returncode}")
        return False

def test_sqlite_ro_opens():
    from app import db_reader
    try:
        conn = db_reader._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        val = cur.fetchone()[0]
        conn.close()
        assert val == 1
        print("[OK] SQLite read-only connection opens and queries successfully")
        return True
    except Exception as e:
        print(f"[FAIL] SQLite read-only connection failed: {e}")
        return False

def test_tables_discovered():
    from app import db_reader
    try:
        res = db_reader.list_tables()
        assert "tables" in res
        assert len(res["tables"]) > 0
        print(f"[OK] Tables discovered: {res['tables']}")
        return True
    except Exception as e:
        print(f"[FAIL] Tables discovery failed: {e}")
        return False

def test_schemas_discovered():
    from app import db_reader
    from app.config import MCP_MODE
    table_to_check = "m_customers_t" if MCP_MODE == "real" else "companies"
    try:
        res = db_reader.get_table_schema(table_to_check)
        assert "columns" in res
        assert len(res["columns"]) > 0
        print(f"[OK] Schema discovered for '{table_to_check}' table: {[c['name'] for c in res['columns']]}")
        return True
    except Exception as e:
        print(f"[FAIL] Schema discovery failed: {e}")
        return False

def test_search_database_all():
    from app import db_reader
    from app.config import MCP_MODE
    try:
        term = "SRI MURUGAN" if MCP_MODE == "real" else "GLS"
        res = db_reader.search_database_all(term)
        assert "records" in res
        assert len(res["records"]) > 0
        print(f"[OK] search_database_all works, found {len(res['records'])} matches for '{term}'")
        return True
    except Exception as e:
        print(f"[FAIL] search_database_all failed: {e}")
        return False

def test_old_9_chat_queries():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import MCP_MODE
    
    if MCP_MODE == "real":
        print("[SKIP] Skipping old 9 chat queries in real mode")
        return True
        
    client = TestClient(app)
    
    queries = [
        ("hi", "Try asking:"),
        ("hello", "Try asking:"),
        ("Why invoice number not filling?", "Invoice Number"),
        ("po number", "PO Number"),
        ("Show validation result", "Validation Summary:"),
        ("Show database overview", "Database Overview:"),
        ("customer id", "No exact Customer ID field found"),
        ("server number", "No exact matching database record found"),
        ("Update GLS mapping and delete old record", "This assistant is read-only")
    ]
    
    success = True
    for q, expected in queries:
        try:
            response = client.post("/api/chat", json={"question": q})
            assert response.status_code == 200
            data = response.json()
            answer = data.get("answer", "")
            assert expected in answer, f"For query '{q}', expected pattern '{expected}' not found in answer: '{answer}'"
            print(f"  - [OK] Chat query '{q}' passed")
        except Exception as e:
            print(f"  - [FAIL] Chat query '{q}' failed: {e}")
            success = False
    if success:
        print("[OK] All 9 old chat tests pass successfully")
    return success

def test_real_mode_simulation():
    print("==================================================")
    print(" Running Real Mode Simulation Tests               ")
    print("==================================================")
    from app.config import MCP_MODE
    if MCP_MODE != "real":
        print("[SKIP] Skipping real mode simulation tests in demo mode")
        return True

    try:
        from app import db_reader, config

        # Verify using actual real DB (no temp fake DB)
        assert config.DB_NAME == "ifiveerp_skm_demo.db", f"Expected ifiveerp_skm_demo.db, got {config.DB_NAME}"
        assert config.CONNECTED, "DB should be connected"
        print(f"[OK] Connected to real DB: {config.DB_NAME}")

        # Search customer in real DB (use the actual API the chat flow uses for business entity search)
        res_cust = db_reader.search_business_entity("customer", query="SRI MURUGAN", limit=5)
        assert res_cust.get("count", 0) > 0, "Expected customer records for SRI MURUGAN"
        assert res_cust["records"][0]["table"] == "m_customers_t", f"Expected m_customers_t, got {res_cust['records'][0].get('table')}"
        print(f"[OK] Real DB customer search for 'SRI MURUGAN': found {res_cust['count']} records in m_customers_t")

        # Search invoice in real DB
        res_inv = db_reader.search_database_all("TVL25000001")
        assert res_inv.get("records"), "Expected invoice record for TVL25000001"
        assert res_inv["records"][0]["table"] == "s_invoice_hdr_t"
        print(f"[OK] Real DB discovery search for 'TVL25000001': found in s_invoice_hdr_t")

        # Verify missing DB raises FileNotFoundError (blocked fallback)
        import os, importlib
        orig_path = os.environ.get("SQLITE_DB_PATH")
        try:
            os.environ["SQLITE_DB_PATH"] = "data/real_db/nonexistent_test.db"
            importlib.reload(config)
            importlib.reload(db_reader)
            assert not config.CONNECTED, "Connected should be False for missing DB"
            try:
                db_reader._get_conn()
                print("[FAIL] Connection opened for missing DB")
                return False
            except FileNotFoundError:
                print("[OK] Fallback blocked and missing DB raised FileNotFoundError")
        finally:
            # Always restore
            if orig_path:
                os.environ["SQLITE_DB_PATH"] = orig_path
            else:
                os.environ.pop("SQLITE_DB_PATH", None)
            importlib.reload(config)
            importlib.reload(db_reader)

        print("[OK] Real mode simulation tests passed")
        return True

    except Exception as e:
        print(f"[FAIL] Real mode simulation failed: {e}")
        import traceback; traceback.print_exc()
        return False

def test_actual_sql_import():
    print("==================================================")
    print(" Running Actual SQL Import Verification            ")
    print("==================================================")
    import sqlite3
    
    sql_file = Path("ifiveerp_skm_demo_db.sql")
    db_file = Path("data/real_db/ifiveerp_skm_demo.db")
    
    # 1. Check if SQL file exists
    if not sql_file.exists():
        print(f"[FAIL] SQL file {sql_file} does not exist.")
        return False
    print(f"[OK] SQL file exists: {sql_file}")
    
    # 2. Check/run import
    if not db_file.exists() or db_file.stat().st_size == 0:
        print(f"[INFO] Importing database from dump...")
        from app.sql_importer import import_sql
        import_sql(sql_file, db_file)
        
    if not db_file.exists():
        print(f"[FAIL] SQLite database {db_file} does not exist after import.")
        return False
    print(f"[OK] SQLite database exists: {db_file}")
    
    # 3. Verify tables and records
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in cur.fetchall()]
        if len(tables) == 0:
            print("[FAIL] SQLite database has no tables.")
            conn.close()
            return False
            
        print(f"[OK] Discovered {len(tables)} tables in SQLite database.")
        
        # Verify total records > 0 in one of the tables
        cur.execute("SELECT COUNT(*) FROM m_customers_t")
        cust_cnt = cur.fetchone()[0]
        if cust_cnt == 0:
            print("[FAIL] Table m_customers_t has 0 records.")
            conn.close()
            return False
        print(f"[OK] Discovered {cust_cnt} customer records in m_customers_t.")
        
        conn.close()
    except Exception as e:
        print(f"[FAIL] Error querying database: {e}")
        return False
        
    # 4. Verify search_database_all returns real table records
    from app import db_reader
    try:
        res = db_reader.search_database_all("SRI MURUGAN")
        records = res.get("records", [])
        if len(records) == 0:
            print("[FAIL] search_database_all found no matches for 'SRI MURUGAN'")
            return False
        
        first = records[0]
        # Check all required fields are present
        required_fields = ["db_file_name", "table", "row_id", "matched_column", "matched_value", "row_preview", "read_only"]
        for f in required_fields:
            if f not in first:
                print(f"[FAIL] Missing required field '{f}' in search result: {first}")
                return False
                
        print("[OK] search_database_all returned correct fields and matches")
    except Exception as e:
        print(f"[FAIL] search_database_all test failed: {e}")
        return False
        
    # 5. Verify sample.db fallback blocked in real mode
    from app.config import MCP_MODE
    import os
    orig_mode = os.environ.get("MCP_MODE")
    orig_path = os.environ.get("SQLITE_DB_PATH")
    try:
        os.environ["MCP_MODE"] = "real"
        os.environ["SQLITE_DB_PATH"] = "data/sample.db"
        import importlib
        from app import config, db_reader
        importlib.reload(config)
        importlib.reload(db_reader)
        
        assert not config.CONNECTED, "Connected should be False for sample.db in real mode"
        try:
            db_reader._get_conn()
            print("[FAIL] Connection allowed to sample.db in real mode")
            return False
        except FileNotFoundError:
            print("[OK] sample.db fallback blocked correctly in real mode")
    except Exception as e:
        print(f"[FAIL] sample.db blocking test failed: {e}")
        return False
    finally:
        if orig_mode is not None:
            os.environ["MCP_MODE"] = orig_mode
        else:
            os.environ.pop("MCP_MODE", None)
        if orig_path is not None:
            os.environ["SQLITE_DB_PATH"] = orig_path
        else:
            os.environ.pop("SQLITE_DB_PATH", None)
        importlib.reload(config)
        importlib.reload(db_reader)
        
    return True

def test_business_router():
    """Test business_router entity detection and table ranking."""
    print("==================================================")
    print(" Running Business Router Tests                    ")
    print("==================================================")
    try:
        from app.business_router import detect_entity, get_ranked_tables_for_entity
        from app.config import MCP_MODE
        
        # Entity detection
        assert detect_entity("Search customer") == "customer", f"Got: {detect_entity('Search customer')}"
        assert detect_entity("Show invoice list") == "invoice", f"Got: {detect_entity('Show invoice list')}"
        assert detect_entity("Find supplier") == "supplier", f"Got: {detect_entity('Find supplier')}"
        assert detect_entity("List item stock") == "item", f"Got: {detect_entity('List item stock')}"
        print("[OK] Entity detection tests passed")
        
        if MCP_MODE == "real":
            # Table ranking - customer
            cust_tables = get_ranked_tables_for_entity("customer")
            assert cust_tables, "No customer tables found"
            assert cust_tables[0]["table_name"] == "m_customers_t", f"Expected m_customers_t, got {cust_tables[0]['table_name']}"
            print(f"[OK] Customer table ranking: top = {cust_tables[0]['table_name']}")
            
            # Table ranking - invoice
            inv_tables = get_ranked_tables_for_entity("invoice")
            assert inv_tables, "No invoice tables found"
            assert inv_tables[0]["table_name"] == "s_invoice_hdr_t", f"Expected s_invoice_hdr_t, got {inv_tables[0]['table_name']}"
            print(f"[OK] Invoice table ranking: top = {inv_tables[0]['table_name']}")
            
            # Table ranking - supplier
            supp_tables = get_ranked_tables_for_entity("supplier")
            assert supp_tables, "No supplier tables found"
            assert supp_tables[0]["table_name"] == "m_supplier_t", f"Expected m_supplier_t, got {supp_tables[0]['table_name']}"
            print(f"[OK] Supplier table ranking: top = {supp_tables[0]['table_name']}")
            
            # Table ranking - item/product
            item_tables = get_ranked_tables_for_entity("item")
            assert item_tables, "No item tables found"
            print(f"[OK] Item table ranking: top = {item_tables[0]['table_name']}")
        else:
            print("[SKIP] Table ranking tests skipped in demo mode")
        
        print("[OK] Business router tests passed")
        return True
    except Exception as e:
        print(f"[FAIL] Business router tests failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_search_business_entity():
    """Test search_business_entity function in db_reader."""
    print("==================================================")
    print(" Running Search Business Entity Tests             ")
    print("==================================================")
    from app.config import MCP_MODE
    if MCP_MODE != "real":
        print("[SKIP] Skipping search business entity tests in demo mode")
        return True
    try:
        from app import db_reader
        
        # Test: Search customer (no query = sample records)
        res = db_reader.search_business_entity("customer", limit=5)
        assert res.get("count", 0) > 0, f"Expected customer records, got 0. Source: {res.get('source')}"
        first = res["records"][0]
        assert first.get("table") == "m_customers_t", f"Expected m_customers_t, got {first.get('table')}"
        assert first.get("read_only") == True
        print(f"[OK] Search customer (generic) returned {res['count']} records from {first['table']}")
        
        # Test: Search invoice (no query = sample records)
        res = db_reader.search_business_entity("invoice", limit=5)
        assert res.get("count", 0) > 0, f"Expected invoice records, got 0"
        first = res["records"][0]
        assert "invoice" in first.get("table", "").lower(), f"Expected invoice table, got {first.get('table')}"
        print(f"[OK] Search invoice (generic) returned {res['count']} records from {first['table']}")
        
        # Test: Search supplier (no query = sample records)
        res = db_reader.search_business_entity("supplier", limit=5)
        assert res.get("count", 0) > 0, f"Expected supplier records, got 0"
        first = res["records"][0]
        print(f"[OK] Search supplier (generic) returned {res['count']} records from {first['table']}")
        
        # Test: Search customer with specific name query
        res = db_reader.search_business_entity("customer", query="SRI MURUGAN", limit=5)
        assert res.get("count", 0) > 0, f"Expected match for SRI MURUGAN, got 0"
        first = res["records"][0]
        assert "SRI MURUGAN" in str(first.get("matched_value", "")), f"Expected SRI MURUGAN in matched_value, got {first.get('matched_value')}"
        print(f"[OK] Search customer 'SRI MURUGAN' found: {first['matched_value']} in {first['table']}")
        
        print("[OK] All search_business_entity tests passed")
        return True
    except Exception as e:
        print(f"[FAIL] search_business_entity test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_search_exact_value():
    """Test search_exact_value function in db_reader."""
    print("==================================================")
    print(" Running Exact Value Search Tests                 ")
    print("==================================================")
    from app.config import MCP_MODE
    if MCP_MODE != "real":
        print("[SKIP] Skipping exact value search tests in demo mode")
        return True
    try:
        from app import db_reader
        
        # Test: Search exact invoice number TVL25000001
        res = db_reader.search_exact_value("TVL25000001", limit=5)
        assert res.get("count", 0) > 0, f"Expected 1 record for TVL25000001, got 0"
        first = res["records"][0]
        assert first.get("matched_value", "").upper() == "TVL25000001", f"Expected TVL25000001, got {first.get('matched_value')}"
        assert first.get("table") == "s_invoice_hdr_t", f"Expected s_invoice_hdr_t, got {first.get('table')}"
        assert first.get("read_only") == True
        row_preview = first.get("row_preview", {})
        assert "invoice_number" in row_preview, "Expected invoice_number field in row_preview"
        print(f"[OK] Exact value TVL25000001 found in {first['table']}, Row ID: {first['row_id']}")
        
        print("[OK] All search_exact_value tests passed")
        return True
    except Exception as e:
        print(f"[FAIL] search_exact_value test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_actual_real_mode_chat_queries():
    print("==================================================")
    print(" Running Actual Real Mode Chat Query Tests        ")
    print("==================================================")
    
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import MCP_MODE
    
    if MCP_MODE != "real":
        print("[SKIP] Skipping actual real mode chat tests since mode is not 'real'")
        return True
        
    client = TestClient(app)
    
    chat_tests = [
        # DB overview
        ("Show database overview", ["ifiveerp_skm_demo.db"]),
        ("List database tables", ["m_customers_t"]),
        # Generic entity searches
        ("Search customer", ["customer-related records", "DB File:", "Row ID:", "Read Only: true"]),
        ("Search invoice", ["invoice-related records", "DB File:", "Row ID:", "Read Only: true"]),
        ("Search supplier", ["supplier-related records", "DB File:", "Row ID:", "Read Only: true"]),
        # Specific entity searches
        ("Search customer SRI MURUGAN", ["SRI MURUGAN", "Row ID:", "Read Only: true"]),
        ("Search invoice TVL25000001", ["TVL25000001", "Row ID:", "Read Only: true"]),
        ("Search supplier 2K DISTRIBUTORS", ["2K DISTRIBUTORS", "Row ID:", "Read Only: true"]),
        # Exact value lookup
        ("TVL25000001", ["TVL25000001", "Row ID:", "Read Only: true"]),
        # Safety
        ("Update customer record name to new", ["This assistant is read-only. I can only explain existing database and dataset records."])
    ]
    
    success = True
    for q, expected_keywords in chat_tests:
        try:
            response = client.post("/api/chat", json={"question": q})
            assert response.status_code == 200
            data = response.json()
            ans = data.get("answer", "")
            match = True
            for kw in expected_keywords:
                if kw not in ans:
                    match = False
                    short_ans = ans[:200].replace("\n", " ")
                    print(f"  - [FAIL] Chat query '{q}' missing keyword '{kw}'. Answer: '{short_ans}...'")
            if match:
                print(f"  - [OK] Chat query '{q}' passed")
            else:
                success = False
        except Exception as e:
            print(f"  - [FAIL] Chat query '{q}' failed with error: {e}")
            import traceback; traceback.print_exc()
            success = False
            
    if success:
        print("[OK] All real mode chat tests passed")
    return success


def test_output_polish():
    """Targeted checks for the output-polish fixes:
    - confidence badge never Low when real rows are found
    - exact invoice search shows primary invoice + related-only receipt
    - clean no-match wording, no fake sources
    - safety wording exact
    """
    print("==================================================")
    print(" Running Output Polish Tests                      ")
    print("==================================================")

    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import MCP_MODE

    if MCP_MODE != "real":
        print("[SKIP] Skipping output polish tests since mode is not 'real'")
        return True

    client = TestClient(app)
    success = True

    # 1. Confidence badge must never be Low when real rows are found
    try:
        response = client.post("/api/chat", json={"question": "Search customer SRI MURUGAN"})
        data = response.json()
        conf = data.get("confidence", 0)
        match_level = data.get("match_level", "")
        assert conf >= 60, f"Expected confidence >= 60 for a real match, got {conf}"
        assert match_level in ("Medium", "High"), f"Expected Medium/High match_level, got '{match_level}'"
        print("  - [OK] Search customer SRI MURUGAN confidence/match_level not Low")
    except Exception as e:
        print(f"  - [FAIL] Confidence badge test failed: {e}")
        success = False

    # 2. Exact invoice search: primary section uses s_invoice_hdr_t;
    #    s_receipts_t (if present) only appears under Related records
    try:
        response = client.post("/api/chat", json={"question": "TVL25000001"})
        data = response.json()
        answer = data.get("answer", "")
        assert "s_invoice_hdr_t" in answer, "Primary invoice table missing from answer"
        before_related = answer.split("Related records:")[0]
        assert "s_receipts_t" not in before_related, "Receipt table leaked into primary/Key details section"
        found_data = data.get("found_data", [])
        for fd in found_data:
            t = fd.get("table") or fd.get("_table")
            assert t == "s_invoice_hdr_t", f"found_data card leaked non-primary table: {t}"
        print("  - [OK] TVL25000001 primary=s_invoice_hdr_t, receipt only under Related records")
    except Exception as e:
        print(f"  - [FAIL] Exact invoice primary/related test failed: {e}")
        success = False

    # 3. Clean no-match UI, no fake sources, no demo suggestions
    try:
        response = client.post("/api/chat", json={"question": "unknownword123"})
        data = response.json()
        answer = data.get("answer", "")
        assert answer == "Data not found in DB."
        assert data.get("sources") in ([], None) or len(data.get("sources")) == 0
        print("  - [OK] unknownword123 clean no-match, no fake sources, no demo suggestions")
    except Exception as e:
        print(f"  - [FAIL] No-match UI test failed: {e}")
        success = False

    # 4. Safety wording exact
    try:
        response = client.post("/api/chat", json={"question": "Update customer record name to new"})
        data = response.json()
        answer = data.get("answer", "")
        assert answer == "This assistant is read-only. I can only explain existing database and dataset records."
        print("  - [OK] Update customer record blocked with exact read-only safety wording")
    except Exception as e:
        print(f"  - [FAIL] Safety wording test failed: {e}")
        success = False

    # 5. hi greeting intro check
    try:
        response = client.post("/api/chat", json={"question": "hi"})
        data = response.json()
        answer = data.get("answer", "")
        assert "I can help you search this read-only ERP database" in answer
        assert "safely in read-only mode" in answer
        assert "Try Search customer, Search invoice, Search supplier, Search item, Show database overview." in answer
        print("  - [OK] Greeting 'hi' returns exact helpful database assistant intro")
    except Exception as e:
        print(f"  - [FAIL] Greeting 'hi' intro test failed: {e}")
        success = False

    # 6. Search customer returns browse/help
    try:
        response = client.post("/api/chat", json={"question": "Search customer"})
        data = response.json()
        answer = data.get("answer", "")
        assert "Please enter a customer name or customer number" in answer, "Missing customer search guidance"
        assert "Sample customer records from m_customers_t" in answer, "Missing sample records header"
        print("  - [OK] 'Search customer' returns helpful browse guidance and samples")
    except Exception as e:
        print(f"  - [FAIL] 'Search customer' browse test failed: {e}")
        success = False

    # 7. Search invoice returns browse/help and not matched attachfile_name
    try:
        response = client.post("/api/chat", json={"question": "Search invoice"})
        data = response.json()
        answer = data.get("answer", "")
        assert "Please enter an invoice number or customer name" in answer, "Missing invoice search guidance"
        assert "Sample invoice records from s_invoice_hdr_t" in answer, "Missing sample records header"
        assert "attachfile_name" not in answer, "attachfile_name leaked into generic invoice browse"
        print("  - [OK] 'Search invoice' returns helpful browse guidance and does not leak attachfile_name")
    except Exception as e:
        print(f"  - [FAIL] 'Search invoice' browse test failed: {e}")
        success = False

    # 8. JAI MARKETING direct business query
    try:
        response = client.post("/api/chat", json={"question": "JAI MARKETING"})
        data = response.json()
        answer = data.get("answer", "")
        assert "JAI MARKETING" in answer
        assert "m_customers_t" in answer
        assert "Read Only: true" in answer
        print("  - [OK] JAI MARKETING direct query returns m_customers_t record details")
    except Exception as e:
        print(f"  - [FAIL] JAI MARKETING direct query test failed: {e}")
        success = False

    # 9. sample_rows_query response should not return found_data duplicate cards
    try:
        response = client.post("/api/chat", json={"question": "Show sample rows from s_invoice_hdr_t"})
        data = response.json()
        assert data.get("found_data") == [], "found_data must be empty to suppress cards for sample rows query"
        print("  - [OK] Show sample rows suppresses found_data cards")
    except Exception as e:
        print(f"  - [FAIL] Show sample rows cards suppression test failed: {e}")
        success = False

    # 10. sample_rows_query should not show fake row_id 1 when invoice_hdr_id exists
    try:
        response = client.post("/api/chat", json={"question": "Show sample rows from s_invoice_hdr_t"})
        data = response.json()
        answer = data.get("answer", "")
        lines_list = [line.strip().replace("  - ", "") for line in answer.split("\n")]
        assert "row_id: 1" not in lines_list, "Fake row_id 1 should not be shown when invoice_hdr_id exists"
        assert any("row_id:" in l for l in lines_list) or all("row_id:" not in l for l in lines_list), "Omitted or actual SQLite row_id expected"
        print("  - [OK] Show sample rows does not print fake row_id 1")
    except Exception as e:
        print(f"  - [FAIL] Show sample rows fake row_id test failed: {e}")
        success = False

    # 11. Search customer SRI MURUGAN related records should not contain REVATHI TRADERS
    try:
        response = client.post("/api/chat", json={"question": "Search customer SRI MURUGAN"})
        data = response.json()
        answer = data.get("answer", "")
        if "Related records:" in answer:
            related_part = answer.split("Related records:")[1]
            assert "REVATHI TRADERS" not in related_part, "Unrelated REVATHI TRADERS leaked into related records for SRI MURUGAN"
        print("  - [OK] Search customer SRI MURUGAN related records does not leak REVATHI TRADERS")
    except Exception as e:
        print(f"  - [FAIL] Search customer SRI MURUGAN related records test failed: {e}")
        success = False

    if success:
        print("[OK] All output polish tests passed")
    return success


def test_manual_db_search():
    print("==================================================")
    print(" Running Manual DB Search Endpoint Tests          ")
    print("==================================================")
    
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import MCP_MODE
    
    if MCP_MODE != "real":
        print("[SKIP] Skipping manual DB search endpoint tests since mode is not 'real'")
        return True
        
    client = TestClient(app)
    success = True
    
    # 1. Search customer SRI MURUGAN
    try:
        response = client.get("/api/db/search", params={"q": "SRI MURUGAN"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("result_type") == "search_result"
        assert len(data.get("primary_results", [])) > 0
        primary_names = [r.get("display_title", "").lower() for r in data["primary_results"]]
        assert any("sri murugan" in n for n in primary_names), "Expected SRI MURUGAN in primary results"
        print("  - [OK] GET /api/db/search?q=SRI MURUGAN passes")
    except Exception as e:
        print(f"  - [FAIL] GET /api/db/search?q=SRI MURUGAN failed: {e}")
        success = False

    # 2. JAI MARKETING returns m_customers_t
    try:
        response = client.get("/api/db/search", params={"q": "JAI MARKETING"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("result_type") == "search_result"
        assert len(data.get("primary_results", [])) > 0
        top_tbl = data["primary_results"][0].get("table") or data["primary_results"][0].get("_table") or ""
        assert top_tbl == "m_customers_t", f"Expected m_customers_t, got {top_tbl}"
        print("  - [OK] GET /api/db/search?q=JAI MARKETING passes")
    except Exception as e:
        print(f"  - [FAIL] GET /api/db/search?q=JAI MARKETING failed: {e}")
        success = False

    # 3. TVL25000001 returns s_invoice_hdr_t
    try:
        response = client.get("/api/db/search", params={"q": "TVL25000001"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("result_type") == "search_result"
        assert len(data.get("primary_results", [])) > 0
        top_tbl = data["primary_results"][0].get("table") or data["primary_results"][0].get("_table") or ""
        assert top_tbl == "s_invoice_hdr_t", f"Expected s_invoice_hdr_t, got {top_tbl}"
        print("  - [OK] GET /api/db/search?q=TVL25000001 passes")
    except Exception as e:
        print(f"  - [FAIL] GET /api/db/search?q=TVL25000001 failed: {e}")
        success = False

    # 4. unknownword123 returns clean no-match
    try:
        response = client.get("/api/db/search", params={"q": "unknownword123"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("result_type") == "no_match"
        assert len(data.get("primary_results", [])) == 0
        assert data.get("answer") == "Data not found in DB."
        print("  - [OK] GET /api/db/search?q=unknownword123 passes")
    except Exception as e:
        print(f"  - [FAIL] GET /api/db/search?q=unknownword123 failed: {e}")
        success = False

    # 5. Write safety query blocked
    try:
        response = client.get("/api/db/search", params={"q": "Update customer record name to new"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("result_type") == "safety_block"
        assert data.get("answer") == "This assistant is read-only. I can only explain existing database and dataset records."
        print("  - [OK] GET /api/db/search write safety passes")
    except Exception as e:
        print(f"  - [FAIL] GET /api/db/search write safety failed: {e}")
        success = False

    return success


def test_mcp_real_server_presence():
    print("Running test_mcp_real_server_presence...")
    try:
        real_server_path = Path("mcp_real_server.py")
        if not real_server_path.exists():
            print("[FAIL] mcp_real_server.py does not exist")
            return False
        
        # Verify it has correct imports
        with open(real_server_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "from app.mcp_server import mcp" in content, "Missing mcp server import"
        assert "mcp.run(transport=\"stdio\")" in content or "mcp.run(transport='stdio')" in content, "Missing stdio runner"
        
        print("[OK] Real MCP Server script verified")
        return True
    except Exception as e:
        print(f"[FAIL] Real MCP Server check failed: {e}")
        return False


def test_no_hallucination_guard():
    print("Running test_no_hallucination_guard...")
    try:
        from app.safety import validate_ollama_output
        
        question = "What is the status of invoice TVL25000001?"
        context_text = "Table: s_invoice_hdr_t\nRowID: 1\nInvoiceNo: TVL25000001\nAmount: 25000.00\nDate: 2024-05-21"
        canonical_answer = "The invoice TVL25000001 has an amount of 25000.00 dated 2024-05-21."
        
        # Test Case 1: Valid response (no new business-critical values)
        valid_response = "The status of invoice TVL25000001 is active. The total amount is 25000.00. Read Only: true"
        assert validate_ollama_output(valid_response, question, context_text, canonical_answer) is True, "Valid response failed validation"
        
        # Test Case 2: Hallucinated invoice number
        hallucinated_invoice = "The status of invoice TVL25000002 is active. Read Only: true"
        assert validate_ollama_output(hallucinated_invoice, question, context_text, canonical_answer) is False, "Hallucinated invoice passed validation"
        
        # Test Case 3: Hallucinated float amount
        hallucinated_amount = "The invoice TVL25000001 has amount 99999.00. Read Only: true"
        assert validate_ollama_output(hallucinated_amount, question, context_text, canonical_answer) is False, "Hallucinated amount passed validation"
        
        # Test Case 4: Hallucinated integer >= 100
        hallucinated_int = "The invoice TVL25000001 has 500 items. Read Only: true"
        assert validate_ollama_output(hallucinated_int, question, context_text, canonical_answer) is False, "Hallucinated integer passed validation"
        
        # Test Case 5: Valid list indices and years (whitelisted)
        whitelisted_response = "Here are details:\n1. Invoice TVL25000001 date is 2024-05-21.\n2. Standard timeout is 10s. Read Only: true"
        assert validate_ollama_output(whitelisted_response, question, context_text, canonical_answer) is True, "Whitelisted formatting tokens failed validation"

        print("[OK] No-Hallucination Guard verified with 5 test cases")
        return True
    except Exception as e:
        print(f"[FAIL] No-Hallucination Guard check failed: {e}")
        return False



if __name__ == "__main__":
    print("==================================================")
    print(" MCP Data Assistant Verification Script           ")
    print("==================================================")
    
    results = [
        test_imports(),
        test_config(),
        test_datasets_folder(),
        test_datasets_readable(),
        test_db_exists(),
        test_expected_tables(),
        test_readonly_safety(),
        test_no_risky_tools(),
        test_mcp_imports(),
        test_intent_router(),
        test_relevance_ranking(),
        test_response_builder(),
        test_real_db_dir(),
        test_db_path_blocking(),
        test_sqlite_ro_opens(),
        test_tables_discovered(),
        test_schemas_discovered(),
        test_search_database_all(),
        test_old_9_chat_queries(),
        test_business_router(),
        test_search_business_entity(),
        test_search_exact_value(),
        test_real_mode_simulation(),
        test_actual_sql_import(),
        test_actual_real_mode_chat_queries(),
        test_output_polish(),
        test_manual_db_search(),
        test_mcp_real_server_presence(),
        test_no_hallucination_guard()
    ]
    
    print("==================================================")
    if all(results):
        print(" VERIFICATION PASSED: System is secure and ready! ")
        sys.exit(0)
    else:
        print(" VERIFICATION FAILED: Please fix issues above.    ")
        sys.exit(1)
