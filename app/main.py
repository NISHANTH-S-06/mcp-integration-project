"""
FastAPI main application for MCP Data Assistant.
All endpoints are READ-ONLY. No data modification is possible.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import db_reader, dataset_reader, mcp_server, llm_client, safety
from app.mcp_client import MCPClient
from app import intent_router, relevance, response_builder
from app import config

def log_audit(intent: str, tool_called: str, query: str, searched: str, records_returned: int, blocked: bool = False):
    import datetime
    from pathlib import Path
    from app.config import BASE_DIR
    
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "audit.log"
    
    timestamp = datetime.datetime.utcnow().isoformat()
    log_entry = (
        f"[{timestamp}] "
        f"Intent: {intent} | "
        f"Tool: {tool_called} | "
        f"Query: {query} | "
        f"Searched: {searched} | "
        f"Returned: {records_returned} | "
        f"Blocked Write: {blocked}\n"
    )
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except OSError:
        pass

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

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MCP Data Assistant",
    description="Read-only database and dataset assistant. No data modification allowed.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

START_TIME = time.time()


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

from typing import Optional, Any

class ChatRequest(BaseModel):
    question: Optional[str] = None
    message: Optional[str] = None
    company: Optional[str] = None
    document_type: Optional[str] = None
    history: Optional[list] = None


class ChatResponse(BaseModel):
    question: str
    answer: str
    summary: Optional[str] = None
    found_data: Optional[Any] = None
    result_type: Optional[str] = None
    primary_results: Optional[Any] = None
    related_results: Optional[Any] = None
    mcp_trace: Optional[list] = None
    checked_sources: Optional[list] = None
    answer_mode: str
    sources: list
    db_record_count: int
    dataset_record_count: int
    total_matches: int
    confidence: float
    confidence_label: str
    match_level: str
    next_suggestion: str
    read_only: bool
    timestamp: str
    intent: str


# ---------------------------------------------------------------------------
# Helpers for search and filtering
# ---------------------------------------------------------------------------

def _extract_query_keywords(query: str) -> list[str]:
    # Stop words to ignore
    stop_words = {
        "show", "list", "get", "find", "what", "which", "where", "when", "how",
        "why", "is", "are", "the", "a", "an", "for", "of", "in", "on", "at",
        "to", "and", "or", "not", "all", "any", "me", "my", "can", "do", "does",
        "give", "tell", "about", "from", "with", "its", "their", "this", "that",
        "display", "fetch", "retrieve", "search", "return", "result", "results",
        "database", "dataset", "table", "record", "records", "overview", "format",
    }
    words = re.findall(r"[a-z0-9_]+", query.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 1]
    return keywords if keywords else [query.lower()]


def _calculate_relevance_score(
    hit: dict,
    query_str: str,
    keywords: list,
    q_company: Optional[str],
    q_doc_type: Optional[str],
    is_invoice_q: bool,
    is_po_q: bool,
) -> float:
    # Extract fields based on hit type
    record_company = None
    record_doc_type = None
    record_field_name = ""
    record_aliases = ""
    record_mapped_to = ""
    content_str = ""
    
    if "_table" in hit:
        # DB hit
        record_company = hit.get("company_code") or hit.get("company")
        record_doc_type = hit.get("document_type")
        record_field_name = hit.get("field_name") or hit.get("name") or ""
        record_aliases = hit.get("aliases") or ""
        record_mapped_to = hit.get("mapped_to") or ""
        content_str = json.dumps(hit).lower()
    else:
        # Dataset hit
        record_company = hit.get("company")
        record_doc_type = hit.get("document_type")
        rec_data = hit.get("record", {})
        record_field_name = rec_data.get("field_name") or rec_data.get("name") or ""
        record_aliases = rec_data.get("aliases") or ""
        if isinstance(record_aliases, list):
            record_aliases = "|".join(record_aliases)
        record_mapped_to = rec_data.get("mapped_to") or ""
        content_str = json.dumps(rec_data).lower()
        
    # Normalize fields
    record_company = str(record_company or "").upper()
    record_doc_type = str(record_doc_type or "").lower()
    record_field_name_lower = str(record_field_name).lower()
    record_aliases_lower = str(record_aliases).lower()
    record_mapped_to_lower = str(record_mapped_to).lower()
    
    # 1. Base keyword match fraction
    matched_kws = [kw for kw in keywords if kw in content_str]
    if not matched_kws:
        return 0.0
        
    kw_fraction = len(matched_kws) / len(keywords)
    if len(keywords) > 1 and kw_fraction < 0.5:
        return 0.1 * kw_fraction
        
    score = kw_fraction * 2.0
    
    # 2. Exact field name match
    if record_field_name_lower and record_field_name_lower in query_str:
        score += 15.0
        
    # 3. Exact company match
    if q_company:
        if record_company == q_company.upper():
            score += 8.0
        elif record_company and record_company != "ALL" and record_company != q_company.upper():
            score -= 12.0
            
    # 4. Exact document type match
    if q_doc_type:
        if q_doc_type.lower() in record_doc_type:
            score += 5.0
        elif record_doc_type and q_doc_type.lower() not in record_doc_type:
            score -= 8.0
            
    # 5. Alias match
    if record_aliases_lower:
        aliases_list = [a.strip().lower() for a in record_aliases_lower.split("|") if a.strip()]
        for alias in aliases_list:
            if alias in query_str:
                score += 10.0
                break
                
    # 6. Mapped to match
    if record_mapped_to_lower and record_mapped_to_lower in query_str:
        score += 8.0
        
    # 7. Cross-domain Penalties
    if is_invoice_q and not is_po_q:
        if record_company == "POPRINT" or "purchase order" in record_doc_type or "po" in record_doc_type:
            has_alias_match = False
            if record_aliases_lower:
                aliases_list = [a.strip().lower() for a in record_aliases_lower.split("|") if a.strip()]
                for alias in aliases_list:
                    if alias in query_str:
                        has_alias_match = True
            if not has_alias_match:
                return 0.0
                
    if is_po_q and not is_invoice_q:
        if record_company == "GLS" or "sales invoice" in record_doc_type or "invoice" in record_doc_type:
            has_alias_match = False
            if record_aliases_lower:
                aliases_list = [a.strip().lower() for a in record_aliases_lower.split("|") if a.strip()]
                for alias in aliases_list:
                    if alias in query_str:
                        has_alias_match = True
            if not has_alias_match:
                return 0.0
                
    return score


import re
import json

def _query_and_score(question: str, filter_company: Optional[str] = None, filter_doc_type: Optional[str] = None) -> tuple[list, list]:
    q_clean = question.lower().strip("?.!,;\"'“” ")
    keywords = _extract_query_keywords(q_clean)
    
    # Extract query features
    q_company = filter_company
    if not q_company:
        if "gls" in q_clean:
            q_company = "GLS"
        elif "poprint" in q_clean:
            q_company = "POPRINT"
        elif "turbomach" in q_clean or "turbo" in q_clean:
            q_company = "TURBOMACH"
        elif "mde" in q_clean:
            q_company = "MDE"
        elif "alphalog" in q_clean:
            q_company = "ALPHALOG"
        
    q_doc_type = filter_doc_type
    if not q_doc_type:
        if "invoice" in q_clean or "rechnung" in q_clean:
            q_doc_type = "Sales Invoice"
        elif "purchase order" in q_clean or "po number" in q_clean or "poprint po" in q_clean or "purchase" in q_clean or "po" in q_clean:
            q_doc_type = "Purchase Order"
        elif "work order" in q_clean or "wo#" in q_clean:
            q_doc_type = "Work Order"
        
    is_invoice_q = "invoice" in q_clean or "rechnung" in q_clean or "sales_form" in q_clean
    is_po_q = "po" in q_clean or "purchase" in q_clean or "poprint" in q_clean or "po_form" in q_clean or "proforma" in q_clean
    
    scored_db = []
    scored_ds = []
    
    # 1. Fetch DB candidates
    db_hits_all = []
    for table in ["training_mappings", "ocr_results", "validation_results", "companies"]:
        r = db_reader.search_records(table, "", limit=100)
        for rec in r.get("records", []):
            rec_dict = dict(rec)
            rec_dict["_table"] = table
            rec_dict["source"] = f"database:{table}:id={rec.get('id', '?')}"
            db_hits_all.append(rec_dict)
            
    # 2. Fetch Dataset candidates
    dataset_records_all = []
    datasets_list = dataset_reader.list_datasets().get("datasets", [])
    for ds in datasets_list:
        ds_name = ds["name"]
        ds_data = dataset_reader.get_dataset_record(ds_name)
        meta = ds_data.get("meta", {})
        for rec in ds_data.get("records", []):
            dataset_records_all.append({
                "dataset": ds_name,
                "company": meta.get("company"),
                "document_type": meta.get("document_type"),
                "source": f"dataset:{ds_name}:record_id={rec.get('id', '?')}",
                "record": rec
            })
            
    # Score DB hits
    for hit in db_hits_all:
        score = _calculate_relevance_score(hit, q_clean, keywords, q_company, q_doc_type, is_invoice_q, is_po_q)
        if score >= 2.0:
            scored_db.append((hit, score))
            
    # Score Dataset hits
    for hit in dataset_records_all:
        score = _calculate_relevance_score(hit, q_clean, keywords, q_company, q_doc_type, is_invoice_q, is_po_q)
        if score >= 2.0:
            scored_ds.append((hit, score))
            
    # Sort by score descending
    scored_db.sort(key=lambda x: x[1], reverse=True)
    scored_ds.sort(key=lambda x: x[1], reverse=True)
    
    return [x[0] for x in scored_db], [x[0] for x in scored_ds]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
@app.get("/api/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    uptime_seconds = int(time.time() - START_TIME)
    ollama_status = await llm_client.check_ollama_status()

    from app import config
    
    # DB stats
    try:
        db_overview = db_reader.get_database_overview()
    except Exception:
        db_overview = {}
    table_count = db_overview.get("table_count", 0) if config.CONNECTED else 0
    total_records = db_overview.get("total_records", 0) if config.CONNECTED else 0

    # Dataset status
    dataset_status = "connected"
    if not config.DATASETS_DIR.exists() or not config.DATASETS_DIR.is_dir():
        dataset_status = "not_connected"
    elif not list(config.DATASETS_DIR.glob("*.json")) and not list(config.DATASETS_DIR.glob("*.csv")):
        dataset_status = "empty"

    # Import registry status
    import_registry_path = config.BASE_DIR / "data" / "registry" / "import_registry.json"
    import_registry_status = "connected" if import_registry_path.exists() else "not_connected"

    mcp_client = MCPClient()
    mcp_tools_info = await mcp_client.list_tools_async()

    extended_ollama = dict(ollama_status)
    extended_ollama.update({
        "enabled": config.OLLAMA_ENABLED,
        "available": ollama_status.get("available", False),
        "model": config.OLLAMA_MODEL,
        "timeout_seconds": 10
    })

    return {
        "status": "ok",
        "service": "MCP Data Assistant",
        "version": "1.0.0",
        "read_only_mode": True,
        "read_only": True,
        "mcp_mode": config.MCP_MODE,
        "database_type": config.DATABASE_TYPE,
        "mcp_tools_count": len(mcp_tools_info.get("tools", [])),
        "mcp_server_url": config.MCP_SERVER_URL,
        "mcp_transport": mcp_tools_info.get("transport"),
        "uptime_seconds": uptime_seconds,
        "uptime_human": _format_uptime(uptime_seconds),
        "timestamp": datetime.utcnow().isoformat(),
        "db_file_name": config.DB_FILE_NAME,
        "connected": config.CONNECTED,
        "db_connected": config.CONNECTED,
        "demo_data_active": config.DEMO_DATA_ACTIVE,
        "table_count": table_count,
        "total_records": total_records,
        "dataset_folder_status": dataset_status,
        "import_registry_status": import_registry_status,
        "mcp_server": {
            "enabled": True,
            "transport": mcp_tools_info.get("transport"),
            "tools_count": len(mcp_tools_info.get("tools", []))
        },
        "mcp_server_enabled": True,
        "mcp_server_transport": mcp_tools_info.get("transport"),
        "mcp_server_tools_count": len(mcp_tools_info.get("tools", [])),
        "ollama_enabled": config.OLLAMA_ENABLED,
        "ollama_available": ollama_status.get("available", False),
        "ollama_model": config.OLLAMA_MODEL,
        "ollama_timeout_seconds": 10,
        "components": {
            "database": "connected" if config.CONNECTED else "error",
            "dataset_storage": "connected" if dataset_status in ("connected", "empty") else "error",
            "ollama": "connected" if ollama_status["available"] else "not_available",
            "mcp_server": "connected" if mcp_tools_info.get("transport") == "streamable_http" else "fallback",
        },
        "mcp": mcp_tools_info,
        "ollama": extended_ollama,
    }


@app.get("/api/overview", tags=["Data"])
async def get_overview():
    """Combined overview of database and datasets."""
    db_overview = db_reader.get_database_overview()
    ds_overview = dataset_reader.get_dataset_overview()
    return {
        "source": "overview",
        "database": db_overview,
        "datasets": ds_overview,
        "read_only_mode": True,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/datasets", tags=["Datasets"])
async def get_datasets():
    """List all available datasets."""
    return dataset_reader.list_datasets()


@app.get("/api/datasets/{dataset_name}", tags=["Datasets"])
async def get_dataset(dataset_name: str, record_id: Optional[str] = None):
    """Get all records from a specific dataset, or a single record by ID."""
    return dataset_reader.get_dataset_record(dataset_name, record_id)


@app.get("/api/datasets/{dataset_name}/search", tags=["Datasets"])
async def search_in_dataset(
    dataset_name: str,
    q: str = Query(..., description="Search query"),
):
    """Search within a specific dataset."""
    return dataset_reader.search_dataset(q)


@app.get("/api/company/{company_code}", tags=["Datasets"])
async def get_company(company_code: str):
    """Get company mapping record."""
    return dataset_reader.get_company_mapping(company_code)


@app.get("/api/db/tables", tags=["Database"])
async def list_db_tables():
    """List all tables in the read-only database."""
    return db_reader.list_tables()


@app.get("/api/db/tables/{table_name}/schema", tags=["Database"])
async def get_schema(table_name: str):
    """Get column schema for a table."""
    return db_reader.get_table_schema(table_name)


@app.get("/api/db/tables/{table_name}/sample", tags=["Database"])
async def get_table_sample_rows(table_name: str, limit: int = Query(10, ge=1, le=50)):
    """Read-only sample rows for the Table Explorer screen. No write/edit/delete."""
    return db_reader.get_table_sample(table_name, limit)


@app.get("/api/db/tables/{table_name}/search", tags=["Database"])
async def search_table(
    table_name: str,
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search records in a specific database table."""
    safe, reason = safety.check_query_safety(q)
    if not safe:
        raise HTTPException(status_code=400, detail=reason)
    return db_reader.search_records(table_name, q, limit)


@app.get("/api/db/tables/{table_name}/{record_id}", tags=["Database"])
async def get_db_record(table_name: str, record_id: str):
    """Fetch a specific database record by ID."""
    return db_reader.get_record_by_id(table_name, record_id)


@app.get("/api/tools", tags=["MCP"])
async def list_tools():
    """List all available MCP-style tools (live registry from app/mcp_server.py)."""
    mcp_client = MCPClient()
    tools_info = await mcp_client.list_tools_async()
    live_tools = tools_info.get("tools", [])
    return {
        "tools": live_tools,
        "count": len(live_tools),
        "read_only": True,
        "server_url": config.MCP_SERVER_URL,
        "transport": tools_info.get("transport"),
        "fallback_reason": tools_info.get("fallback_reason"),
    }


@app.get("/api/mcp/tools", tags=["MCP"])
async def list_mcp_tools():
    """List all available MCP-style tools (live registry from app/mcp_server.py) at the MCP-specific endpoint."""
    mcp_client = MCPClient()
    tools_info = await mcp_client.list_tools_async()
    live_tools = tools_info.get("tools", [])
    return {
        "tools": live_tools,
        "count": len(live_tools),
        "read_only": True,
        "server_url": config.MCP_SERVER_URL,
        "transport": tools_info.get("transport"),
        "fallback_reason": tools_info.get("fallback_reason"),
    }


@app.post("/api/chat", tags=["Chat"], response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint.
    Uses intent routing, local MCP server/client, relevance ranking, and response builder.
    """
    q_str = request.question or request.message or ""
    question = q_str.strip()

    from app.search_service import run_real_search
    res = await run_real_search(question, limit=20)

    # Count DB vs Dataset records in found_data for response counts
    db_count = sum(1 for s in res["sources"] if s.get("type") != "Dataset")
    ds_count = sum(1 for s in res["sources"] if s.get("type") == "Dataset")

    # Log successful audit
    intent = res["intent"]
    tool_called = "search_database_all"
    searched = "all"
    if intent == "invoice_issue":
        tool_called = "multiple"
        searched = "training_mappings, validation_results, datasets"
    elif intent == "po_query":
        tool_called = "multiple"
        searched = "training_mappings, validation_results, datasets"
    elif intent == "validation_query":
        tool_called = "get_validation_results"
        searched = "validation_results"
    elif intent == "mapping_query":
        tool_called = "get_training_mappings"
        searched = "training_mappings"
    elif intent == "database_overview":
        tool_called = "get_database_overview"
        searched = "database"
    elif intent == "table_list":
        tool_called = "list_tables"
        searched = "sqlite_master"
    elif intent == "dataset_overview":
        tool_called = "list_datasets"
        searched = "datasets"
    elif intent == "write_attempt":
        tool_called = "None"
        searched = "None"
        
    log_audit(intent, tool_called, question, searched, db_count + ds_count, blocked=(intent == "write_attempt"))

    return ChatResponse(
        question=question,
        answer=res["answer"],
        summary=res["summary"],
        found_data=res["found_data"],
        result_type=res.get("result_type"),
        primary_results=res.get("primary_results", []),
        related_results=res.get("related_results", []),
        mcp_trace=res.get("mcp_trace", []),
        checked_sources=res.get("checked_sources", []),
        answer_mode=res["answer_mode"],
        sources=res["sources"],
        db_record_count=db_count,
        dataset_record_count=ds_count,
        total_matches=db_count + ds_count,
        confidence=res["confidence"],
        confidence_label=res["match_level"],
        match_level=res["match_level"],
        next_suggestion=res["next_suggestion"],
        read_only=True,
        timestamp=datetime.utcnow().isoformat(),
        intent=res["intent"],
    )


@app.get("/api/db/search", tags=["Database"])
async def manual_db_search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """Query the shared search brain directly across all database tables."""
    from app.search_service import run_real_search
    res = await run_real_search(q, limit=limit)
    return res


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_uptime(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
