import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from app import db_reader, dataset_reader, llm_client, safety
from app.mcp_client import MCPClient
from app import intent_router, relevance, response_builder
from app import config

def get_actual_row_id(row: dict, table_name: str) -> Optional[int]:
    tbl = table_name.lower()
    if tbl == "s_invoice_hdr_t":
        if "invoice_hdr_id" in row and row["invoice_hdr_id"] is not None:
            return row["invoice_hdr_id"]
    elif tbl == "m_customers_t":
        if "customer_id" in row and row["customer_id"] is not None:
            return row["customer_id"]
    elif tbl == "m_supplier_t":
        if "supplier_id" in row and row["supplier_id"] is not None:
            return row["supplier_id"]
    elif tbl == "m_products_t":
        if "product_id" in row and row["product_id"] is not None:
            return row["product_id"]
            
    for k in ["rowid", "row_id", "id"]:
        if k in row and row[k] is not None:
            return row[k]
            
    return None

def enrich_hit(hit: dict) -> dict:
    display_info = response_builder.extract_display_fields(hit)
    enriched = dict(hit)
    enriched.update(display_info)
    return enriched

async def run_real_search(query: str, limit: int = 20) -> Dict[str, Any]:
    question = query.strip()
    
    # 1. Intent routing
    intent = intent_router.classify_intent(question)
    
    # 2. Safety check (including write attempts)
    if intent == "write_attempt" or safety.check_write_intent(question) or not safety.check_query_safety(question)[0]:
        return {
            "query": query,
            "intent": "write_attempt",
            "result_type": "safety_block",
            "primary_results": [],
            "related_results": [],
            "found_data": [],
            "answer": safety.READ_ONLY_RESPONSE,
            "confidence": 0.0,
            "match_level": "No Match",
            "read_only": True,
            "sources": [],
            "next_suggestion": "Ask me to read or explain existing data instead.",
            "answer_mode": "safety_block",
            "summary": safety.READ_ONLY_RESPONSE,
            "mcp_trace": [],
            "checked_sources": []
        }
        
    # 2.4 Ollama Intent planning for ambiguous intent cases
    if intent in ("unknown", "db_search") and config.OLLAMA_ENABLED:
        status = await llm_client.check_ollama_status()
        if status.get("available"):
            planned_intent = await intent_router.classify_intent_with_ollama(question)
            if planned_intent and planned_intent != "unknown":
                intent = planned_intent

    # 2.5 DB existence check for database related requests
    if intent not in ("greeting", "dataset_overview") and (not config.DB_PATH.exists() or not config.CONNECTED or ("sample.db" in config.DB_PATH.name and config.MCP_MODE == "real")):
        if config.MCP_MODE == "real":
            safe_msg = "Database is not connected. Please add a SQLite database in data/real_db and set SQLITE_DB_PATH in .env."
        else:
            safe_msg = f"Database file is missing. Please place a SQLite database at: ./data/real_db/{config.DB_NAME}"
        return {
            "query": query,
            "intent": intent,
            "result_type": "error",
            "primary_results": [],
            "related_results": [],
            "found_data": [],
            "answer": safe_msg,
            "confidence": 0.0,
            "match_level": "No Match",
            "read_only": True,
            "sources": [],
            "next_suggestion": "Configure config.MCP_MODE or check SQLITE_DB_PATH settings.",
            "answer_mode": "error",
            "summary": safe_msg,
            "mcp_trace": [],
            "checked_sources": []
        }

    mcp = MCPClient()
    mcp_traces: List[dict] = []

    def remember_tool(res: dict) -> dict:
        trace = res.get("mcp_trace")
        if trace:
            mcp_traces.append(trace)
        return res

    # 2.8 Early returns for schema_query and sample_rows_query
    if intent == "schema_query":
        table_name = None
        tables_res = remember_tool(await mcp.call_tool_async("list_tables", {}))
        all_tbls = tables_res.get("raw_result", {}).get("tables", [])
        for t in all_tbls:
            if t.lower() in question.lower():
                table_name = t
                break
        if not table_name:
            table_name = "m_customers_t" if "m_customers_t" in all_tbls else (all_tbls[0] if all_tbls else "m_customers_t")
            
        schema_res = remember_tool(await mcp.call_tool_async("get_table_schema", {"table_name": table_name}))
        schema_info = schema_res.get("raw_result", {})
        cols = schema_info.get("columns", [])
        total_cols = len(cols)
        display_cols = cols[:25]
        
        col_lines = []
        for c in display_cols:
            pk_str = " (Primary Key)" if c.get("pk") else ""
            nn_str = " NOT NULL" if c.get("notnull") else ""
            col_lines.append(f"- `{c['name']}`: {c['type']}{pk_str}{nn_str}")
        col_str = "\n".join(col_lines) if col_lines else "- No columns discovered."
        
        cap_note = ""
        if total_cols > 25:
            cap_note = f"\nShowing first 25 columns. Use table explorer for full schema."
            
        answer = (
            f"Table Schema for `{table_name}`:\n\n"
            f"{col_str}\n"
            f"{cap_note}\n\n"
            f"Source checked:\n"
            f"- Table: sqlite_master / PRAGMA\n"
            f"- Read Only: true"
        )
        return {
            "query": query,
            "intent": "schema_query",
            "result_type": "schema",
            "primary_results": [],
            "related_results": [],
            "found_data": [],
            "answer": answer,
            "confidence": 100.0,
            "match_level": "High",
            "read_only": True,
            "sources": [{"type": "Database Table", "name": table_name, "record_id": "", "field": "Schema", "source": f"database:{table_name}", "confidence": 1.0, "label": "Table", "tag": "DB"}],
            "next_suggestion": "Show database overview",
            "answer_mode": "mcp_tools",
            "summary": answer,
            "mcp_trace": mcp_traces,
            "checked_sources": [f"database:{table_name}:schema"]
        }

    if intent == "sample_rows_query":
        table_name = None
        tables_res = remember_tool(await mcp.call_tool_async("list_tables", {}))
        all_tbls = tables_res.get("raw_result", {}).get("tables", [])
        for t in all_tbls:
            if t.lower() in question.lower():
                table_name = t
                break
        if not table_name:
            table_name = "s_invoice_hdr_t" if "s_invoice_hdr_t" in all_tbls else (all_tbls[0] if all_tbls else "s_invoice_hdr_t")
            
        sample_res = remember_tool(await mcp.call_tool_async("get_sample_records", {"table_name": table_name, "limit": 5}))
        sample_info = sample_res.get("raw_result", {})
        records = sample_info.get("records", [])
        
        KEY_COLUMNS_MAP = {
            "s_invoice_hdr_t": ["invoice_number", "invoice_date", "invoice_status", "invoice_grand_total", "paid_amount", "balance_amount", "customer_name", "billing_address", "billing_to_address_txt"],
            "m_customers_t": ["customer_name", "customer_number", "status", "active", "billing_address", "contact_person", "contact_number"],
            "m_supplier_t": ["supplier_name", "supplier_number", "status", "active", "billing_address", "contact_person", "contact_number"],
            "m_products_t": ["product_name", "product_code", "status", "active", "presentation_price", "description"]
        }
        
        tbl_lower = table_name.lower()
        key_cols = KEY_COLUMNS_MAP.get(tbl_lower)
        
        lines = []
        lines.append(f"Sample rows from `{table_name}`:")
        lines.append("")
        for idx, r in enumerate(records):
            lines.append(f"Row {idx + 1}:")
            row_id_val = get_actual_row_id(r, table_name)
            if row_id_val is not None:
                lines.append(f"  - row_id: {row_id_val}")
            
            printed = 0
            if key_cols:
                for k in key_cols:
                    if k in r:
                        v = r[k]
                        if v is not None and str(v).strip() != "":
                            lines.append(f"  - {k}: {v}")
                            printed += 1
            else:
                for k, v in r.items():
                    if k in ("rowid", "row_id", "id"):
                        continue
                    if v is not None and str(v).strip() != "":
                        lines.append(f"  - {k}: {v}")
                        printed += 1
                        if printed >= 8:
                            break
            lines.append("")
            
        lines.append("Source checked:")
        lines.append(f"- Table: {table_name}")
        lines.append("- Read Only: true")
        answer = "\n".join(lines)
        return {
            "query": query,
            "intent": "sample_rows_query",
            "result_type": "sample_rows",
            "primary_results": [],
            "related_results": [],
            "found_data": [],
            "answer": answer,
            "confidence": 100.0,
            "match_level": "High",
            "read_only": True,
            "sources": [{"type": "Database Table", "name": table_name, "record_id": "", "field": "Sample Rows", "source": f"database:{table_name}", "confidence": 1.0, "label": "Table", "tag": "DB"}],
            "next_suggestion": "Show database overview",
            "answer_mode": "mcp_tools",
            "summary": answer,
            "mcp_trace": mcp_traces,
            "checked_sources": [f"database:{table_name}:sample"]
        }

    # 2.9 Determine if query is a generic entity browse query
    is_generic = False
    if intent.startswith("business_entity_search:"):
        entity = intent.split(":")[1]
        q_raw = question.lower().strip("?.!,;\"'“” ")
        from app.db_reader import clean_entity_query
        cleaned_q = clean_entity_query(question, entity)
        is_generic = (not cleaned_q) or q_raw in {
            "search customer", "search customers", "list customers", "list customer",
            "search invoice", "search invoices", "list invoices", "list invoice",
            "search supplier", "search suppliers", "list suppliers", "list supplier",
            "search item", "search items", "list items", "list item",
            "search company", "search companies", "list companies", "list company"
        }

    if intent.startswith("aggregate_query:"):
        from app import aggregates
        agg_res = aggregates.run_aggregate_query(intent, question)
        agg_res["query"] = query
        agg_res["mcp_trace"] = mcp_traces
        return agg_res

    if intent == "sales_summary":
        sales_res = remember_tool(await mcp.call_tool_async("get_sales_summary", {"limit": 5}))
        raw = sales_res.get("raw_result", {}) if not sales_res.get("is_error") else {}
        summary = raw.get("summary") or {}
        records = raw.get("records") or []
        table_name = raw.get("table") or "s_invoice_hdr_t"
        db_file = raw.get("database") or config.DB_NAME

        def fmt_number(value: Any, decimals: int = 2) -> str:
            try:
                return f"{float(value or 0):,.{decimals}f}"
            except Exception:
                return str(value or 0)

        invoice_count = int(summary.get("invoice_count") or raw.get("count") or 0)
        approved_count = int(summary.get("approved_count") or 0)
        total_sales = fmt_number(summary.get("total_sales_amount"))
        total_paid = fmt_number(summary.get("total_paid_amount"))
        total_balance = fmt_number(summary.get("total_balance_amount"))
        first_date = summary.get("first_invoice_date") or "-"
        latest_date = summary.get("latest_invoice_date") or "-"

        lines = [
            "Sales summary:",
            f"- Total sales invoices: {invoice_count:,}",
            f"- Approved invoices: {approved_count:,}",
            f"- Total sales amount: {total_sales}",
            f"- Total paid amount: {total_paid}",
            f"- Total balance amount: {total_balance}",
            f"- Date range: {first_date} to {latest_date}",
            "",
            "Latest invoice samples:",
        ]
        if records:
            for r in records[:5]:
                row = r.get("row_preview") or {}
                inv_no = row.get("invoice_number") or r.get("value") or "?"
                inv_date = row.get("invoice_date") or "?"
                status = row.get("invoice_status") or "?"
                amount = fmt_number(row.get("invoice_grand_total"))
                lines.append(f"- {inv_no} | {inv_date} | {status} | {amount}")
        else:
            lines.append("- No sample invoices returned.")

        lines.extend([
            "",
            "Source checked:",
            f"- DB File: {db_file}",
            f"- Table: {table_name}",
            "- Read Only: true",
        ])
        answer = "\n".join(lines)
        enriched_records = [enrich_hit(r) for r in records[:5]]
        source = {
            "type": "Database Table",
            "name": table_name,
            "record_id": "",
            "field": "Sales Summary",
            "source": raw.get("source") or f"database:{table_name}:sales_summary",
            "confidence": 1.0,
            "label": "Table",
            "tag": "DB",
        }
        return {
            "query": query,
            "intent": intent,
            "result_type": "aggregate",
            "primary_results": enriched_records,
            "related_results": [],
            "found_data": enriched_records,
            "answer": answer,
            "confidence": 100.0 if invoice_count else 0.0,
            "match_level": "High" if invoice_count else "No Match",
            "read_only": True,
            "sources": [source],
            "next_suggestion": "Search invoice",
            "answer_mode": "mcp_tools",
            "summary": answer,
            "mcp_trace": mcp_traces,
            "checked_sources": [source["source"]],
        }

    # 3. Call MCP client tools based on intent
    candidates = []

    if config.MCP_MODE == "real" and intent not in ("greeting", "database_overview", "table_list", "dataset_overview", "write_attempt"):
        if intent.startswith("business_entity_search:"):
            entity = intent.split(":")[1]
            if is_generic:
                db_res = remember_tool(await mcp.call_tool_async("search_business_entity", {"entity": entity, "query": None, "limit": 5}))
                candidates.extend(db_res.get("raw_result", {}).get("records", []))
            else:
                q_clean = question.lower()
                from app.business_router import ENTITY_KEYWORDS
                keywords = ENTITY_KEYWORDS.get(entity, [])
                sub_query = question
                prefixes = ["search for ", "search ", "find in database ", "find in db ", "find ", "show "]
                for p in prefixes:
                    if q_clean.startswith(p):
                        sub_query = sub_query[len(p):].strip()
                        q_clean = q_clean[len(p):].strip()
                        break
                for kw in keywords:
                    if q_clean.startswith(kw):
                        sub_query = sub_query[len(kw):].strip()
                        break
                if not sub_query.strip():
                    sub_query = None
                else:
                    sub_query = sub_query.strip()
                db_res = remember_tool(await mcp.call_tool_async("search_business_entity", {"entity": entity, "query": sub_query, "limit": limit}))
                candidates.extend(db_res.get("raw_result", {}).get("records", []))
        elif intent == "exact_value_search":
            from app.intent_router import detect_exact_value
            val = detect_exact_value(question)
            db_res = remember_tool(await mcp.call_tool_async("search_exact_value", {"value": val, "limit": limit}))
            candidates.extend(db_res.get("raw_result", {}).get("records", []))
        else:
            db_res = remember_tool(await mcp.call_tool_async("search_database_all", {"query": question, "limit": limit}))
            if not db_res.get("is_error"):
                candidates.extend(db_res["raw_result"].get("records", []))
            ds_res = remember_tool(await mcp.call_tool_async("search_datasets_all", {"query": question}))
            if not ds_res.get("is_error"):
                candidates.extend(ds_res["raw_result"].get("results", []))
    else:
        if intent == "invoice_issue":
            ds_res = remember_tool(await mcp.call_tool_async("search_dataset", {"query": "invoice number"}))
            if not ds_res.get("is_error"):
                candidates.extend(ds_res["raw_result"].get("results", []))
            tm_res = remember_tool(await mcp.call_tool_async("get_training_mappings", {"field_name": "Invoice Number"}))
            if not tm_res.get("is_error"):
                for r in tm_res["raw_result"].get("records", []):
                    r_dict = dict(r)
                    r_dict["_table"] = "training_mappings"
                    r_dict["source"] = f"database:training_mappings:id={r.get('id', '?')}"
                    candidates.append(r_dict)
            vr_res = remember_tool(await mcp.call_tool_async("get_validation_results", {"field_name": "Invoice Number"}))
            if not vr_res.get("is_error"):
                for r in vr_res["raw_result"].get("records", []):
                    r_dict = dict(r)
                    r_dict["_table"] = "validation_results"
                    r_dict["source"] = f"database:validation_results:id={r.get('id', '?')}"
                    candidates.append(r_dict)
        elif intent == "po_query":
            ds_res = remember_tool(await mcp.call_tool_async("search_dataset", {"query": "po number"}))
            if not ds_res.get("is_error"):
                candidates.extend(ds_res["raw_result"].get("results", []))
            tm_res = remember_tool(await mcp.call_tool_async("get_training_mappings", {"field_name": "PO Number"}))
            if not tm_res.get("is_error"):
                for r in tm_res["raw_result"].get("records", []):
                    r_dict = dict(r)
                    r_dict["_table"] = "training_mappings"
                    r_dict["source"] = f"database:training_mappings:id={r.get('id', '?')}"
                    candidates.append(r_dict)
            vr_res = remember_tool(await mcp.call_tool_async("get_validation_results", {"field_name": "PO Number"}))
            if not vr_res.get("is_error"):
                for r in vr_res["raw_result"].get("records", []):
                    r_dict = dict(r)
                    r_dict["_table"] = "validation_results"
                    r_dict["source"] = f"database:validation_results:id={r.get('id', '?')}"
                    candidates.append(r_dict)
        elif intent == "validation_query":
            vr_res = remember_tool(await mcp.call_tool_async("get_validation_results", {}))
            if not vr_res.get("is_error"):
                for r in vr_res["raw_result"].get("records", []):
                    r_dict = dict(r)
                    r_dict["_table"] = "validation_results"
                    r_dict["source"] = f"database:validation_results:id={r.get('id', '?')}"
                    candidates.append(r_dict)
        elif intent == "mapping_query":
            tm_res = remember_tool(await mcp.call_tool_async("get_training_mappings", {}))
            if not tm_res.get("is_error"):
                for r in tm_res["raw_result"].get("records", []):
                    r_dict = dict(r)
                    r_dict["_table"] = "training_mappings"
                    r_dict["source"] = f"database:training_mappings:id={r.get('id', '?')}"
                    candidates.append(r_dict)
            ds_res = remember_tool(await mcp.call_tool_async("search_dataset", {"query": question}))
            if not ds_res.get("is_error"):
                candidates.extend(ds_res["raw_result"].get("results", []))
        elif intent == "db_search":
            db_res = remember_tool(await mcp.call_tool_async("search_database_all", {"query": question, "limit": limit}))
            if not db_res.get("is_error"):
                candidates.extend(db_res["raw_result"].get("records", []))
        elif intent in ("database_overview", "table_list", "dataset_overview", "greeting"):
            pass
        else:
            ds_res = remember_tool(await mcp.call_tool_async("search_dataset", {"query": question}))
            if not ds_res.get("is_error"):
                candidates.extend(ds_res["raw_result"].get("results", []))
            db_res = remember_tool(await mcp.call_tool_async("search_database_all", {"query": question, "limit": limit}))
            if not db_res.get("is_error"):
                candidates.extend(db_res["raw_result"].get("records", []))

    # 4. Relevance ranking
    if intent == "exact_value_search":
        scored_sources = [(hit, float(hit.get("score") or 100.0)) for hit in candidates]
    elif is_generic:
        scored_sources = [(hit, 100.0) for hit in candidates]
    else:
        scored_sources = relevance.rank_and_filter(candidates, question)

    if not scored_sources and intent not in ("greeting", "database_overview", "table_list", "dataset_overview", "validation_query") and not is_generic:
        intent = "unknown"

    if config.MCP_MODE == "real" and intent in ("unknown", "db_search") and scored_sources:
        top_hit = scored_sources[0][0]
        tbl = (top_hit.get("table") or top_hit.get("_table") or "").lower()
        if "customer" in tbl:
            intent = "business_entity_search:customer"
        elif "supplier" in tbl:
            intent = "business_entity_search:supplier"
        elif "invoice" in tbl:
            intent = "business_entity_search:invoice"
        elif "product" in tbl or "item" in tbl:
            intent = "business_entity_search:item"

    # 4.5 Empty evidence check for database and search queries
    evidence_intents = {
        "exact_value_search", "db_search", "invoice_issue", "po_query",
        "validation_query", "sales_summary"
    }
    is_business_search = intent.startswith("business_entity_search:")
    is_aggregate_search = intent.startswith("aggregate_query:")
    
    if (intent in evidence_intents or is_business_search or is_aggregate_search) and not is_generic and not scored_sources:
        return {
            "query": query,
            "intent": intent,
            "result_type": "no_match",
            "primary_results": [],
            "related_results": [],
            "found_data": [],
            "answer": "Data not found in DB.",
            "confidence": 0.0,
            "match_level": "No Match",
            "read_only": True,
            "sources": [],
            "next_suggestion": "Try another search or check the spelling.",
            "answer_mode": "no_match",
            "summary": "Data not found in DB.",
            "mcp_trace": mcp_traces,
            "checked_sources": []
        }

    # 5. Fetch helper context for building response
    db_overview = {}
    if intent == "database_overview":
        db_res = remember_tool(await mcp.call_tool_async("get_database_overview", {}))
        if not db_res.get("is_error"):
            db_overview = db_res["raw_result"]
    elif intent == "table_list":
        db_res = remember_tool(await mcp.call_tool_async("list_tables", {}))
        if not db_res.get("is_error"):
            db_overview = db_res["raw_result"]

    val_records = []
    if intent in ("validation_query", "invoice_issue"):
        val_res = remember_tool(await mcp.call_tool_async("get_validation_results", {}))
        if not val_res.get("is_error"):
            val_records = val_res["raw_result"].get("records", [])

    # 6. Response Builder
    res_data = response_builder.build_response(intent, question, scored_sources, db_overview, val_records)

    # 7. Optional Ollama integration
    answer_mode = "rule_based" if intent in ("greeting", "unknown", "database_overview", "table_list", "dataset_overview", "schema_query", "sample_rows_query") or is_generic else "mcp_tools"
    if config.OLLAMA_ENABLED:
        status = await llm_client.check_ollama_status()
        if status.get("available"):
            OLLAMA_SKIP_INTENTS = {
                "greeting", "write_attempt", "safety_block", "database_overview",
                "table_list", "dataset_overview", "schema_query", "sample_rows_query"
            }
            if intent not in OLLAMA_SKIP_INTENTS and not is_generic:
                import json
                context_parts = []
                for hit, score in scored_sources[:8]:
                    if "record" in hit and isinstance(hit["record"], dict):
                        rec = hit["record"]
                        clean_rec = {k: v for k, v in rec.items() if v is not None and str(v).strip() not in ("", "0", "null", "None", "0.0", "0.00")}
                        context_parts.append(f"[Dataset: {hit.get('dataset','?')} | DocType: {hit.get('document_type','?')}]\n{json.dumps(clean_rec, indent=2)}")
                    else:
                        row = hit.get("row_preview") or hit.get("raw_row") or {}
                        if not isinstance(row, dict):
                            row = {}
                        clean_row = {k: v for k, v in row.items() if v is not None and str(v).strip() not in ("", "0", "null", "None", "0.0", "0.00")}
                        table = hit.get("table") or hit.get("_table") or "DB"
                        row_id = hit.get("row_id") or hit.get("id") or "?"
                        if clean_row:
                            context_parts.append(f"[Table: {table} | RowID: {row_id}]\n{json.dumps(clean_row, indent=2)}")
                
                canonical_answer = res_data.get("answer", "")
                if not context_parts:
                    # In case context_parts is empty but scored_sources was not caught earlier
                    res_data["answer"] = "Data not found in DB."
                    res_data["summary"] = "Data not found in DB."
                    res_data["confidence"] = 0.0
                    res_data["match_level"] = "No Match"
                else:
                    context_text = "\n\n".join(context_parts)
                    sources_info = []
                    for src in res_data.get("sources", []):
                        sources_info.append(f"Type: {src.get('type')}, Name: {src.get('name')}, Row/Record ID: {src.get('record_id')}")
                    sources_text = "\n".join(sources_info) if sources_info else "No sources."

                    prompt = (
                        "You are a professional ERP data assistant with read-only access to a live database.\n"
                        "Your job is to rewrite the safe, canonical answer into a natural, conversational response.\n\n"
                        "CRITICAL RULES:\n"
                        "1. Use ONLY the database evidence provided below. Do NOT use outside knowledge or imagination.\n"
                        "2. Do NOT invent invoice numbers, PO/SO numbers, customer/supplier names, IDs, GST numbers, dates, quantities, status values, or amounts.\n"
                        "3. Do NOT change any values under any circumstances.\n"
                        "4. If the database evidence is empty, your response MUST be exactly: 'Data not found in DB.'\n"
                        "5. Ensure the answer remains read-only. Never suggest write/create/update/delete actions.\n"
                        "6. Always end your response with exactly: 'Read Only: true'\n\n"
                        f"User Question: {question}\n\n"
                        f"Safe Canonical Answer:\n{canonical_answer}\n\n"
                        f"Database Evidence:\n{context_text}\n\n"
                        f"Sources:\n{sources_text}\n\n"
                        "Rewrite natural response:"
                    )
                    # 10s strict timeout
                    ollama_ans = await llm_client._query_ollama(prompt, timeout=10)
                    if ollama_ans:
                        is_valid = safety.validate_ollama_output(
                            ollama_ans,
                            question,
                            context_text,
                            canonical_answer
                        )
                        if is_valid:
                            if "Read Only" not in ollama_ans:
                                ollama_ans += "\n\nRead Only: true"
                            res_data["answer"] = ollama_ans
                            res_data["summary"] = ollama_ans
                            answer_mode = f"ollama:{status.get('active_model')}"
                        else:
                            import logging
                            logging.warning(
                                f"Ollama response validation failed (hallucinated business-critical data). "
                                f"Discarding Ollama response. Question: '{question}', Response: '{ollama_ans}'"
                            )
                            # Bypasses LLM rewrite and retains canonical response

    # 8. Segregate primary and related results
    primary_results = []
    related_results = []
    
    if scored_sources and intent in ("business_entity_search:customer", "business_entity_search:supplier", "business_entity_search:invoice", "business_entity_search:item", "exact_value_search"):
        top_hit = scored_sources[0][0]
        primary_table = top_hit.get("table") or top_hit.get("_table") or "unknown"
        
        primary_hits = [h for h, s in scored_sources if (h.get("table") or h.get("_table") or "unknown") == primary_table]
        raw_related_hits = [h for h, s in scored_sources if (h.get("table") or h.get("_table") or "unknown") != primary_table]
        
        q_clean = question.lower().strip("?.!,;\"'“” ")
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
            for h in raw_related_hits:
                display_info = response_builder.extract_display_fields(h)
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
                    all_match.append(h)
                elif any(t in row_str for t in tokens):
                    any_match.append(h)
            filtered_related = all_match if all_match else any_match
        else:
            filtered_related = raw_related_hits
            
        primary_results = [enrich_hit(h) for h in primary_hits[:5]]
        related_results = [enrich_hit(h) for h in filtered_related[:5]]
    else:
        if not is_generic and candidates:
            primary_results = [enrich_hit(h) for h in candidates[:5]]

    result_type = "search_result"
    if intent == "write_attempt":
        result_type = "safety_block"
    elif intent == "greeting":
        result_type = "greeting"
    elif intent in ("database_overview", "table_list", "dataset_overview"):
        result_type = "metadata"
    elif intent in ("schema_query", "sample_rows_query"):
        result_type = intent.split("_")[0]
    elif not scored_sources and intent == "unknown":
        result_type = "no_match"

    checked_sources = []
    for source in res_data.get("sources", []) or []:
        src = source.get("source") or source.get("name") or source.get("type")
        if src:
            checked_sources.append(src)
    for hit in primary_results + related_results:
        src = hit.get("source") or hit.get("table") or hit.get("_table")
        if src:
            checked_sources.append(src)
    checked_sources = list(dict.fromkeys(checked_sources))

    return {
        "query": query,
        "intent": intent,
        "result_type": result_type,
        "primary_results": primary_results,
        "related_results": related_results,
        "found_data": res_data.get("found_data", []),
        "answer": res_data.get("answer", ""),
        "confidence": res_data.get("confidence", 0.0),
        "match_level": res_data.get("match_level", "No Match"),
        "read_only": True,
        "sources": res_data.get("sources", []),
        "next_suggestion": res_data.get("next_suggestion", "Show database overview"),
        "answer_mode": answer_mode,
        "summary": res_data.get("summary", res_data.get("answer", "")),
        "mcp_trace": mcp_traces,
        "checked_sources": checked_sources
    }
