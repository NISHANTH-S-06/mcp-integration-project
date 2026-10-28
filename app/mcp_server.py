"""
FastMCP Server module for MCP Data Assistant.
Provides clean read-only tool registrations using FastMCP.
"""
from typing import Optional
from app import db_reader, dataset_reader
from app import config
from app.db_reader import _get_conn

# --- FastMCP Setup ---
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    class FastMCP:
        """Fallback FastMCP class when mcp is not installed."""
        def __init__(self, name: str):
            self.name = name
            self._tools = {}

        def tool(self, *args, **kwargs):
            def decorator(func):
                self._tools[func.__name__] = func
                return func
            return decorator

mcp = FastMCP(
    "MCP Data Assistant Server",
    host=config.MCP_SERVER_HOST,
    port=config.MCP_SERVER_PORT,
    streamable_http_path=config.MCP_SERVER_PATH,
    json_response=True,
)


# --- Custom Database Tools ---

@mcp.tool()
def get_validation_results(company: Optional[str] = None, document_type: Optional[str] = None, field_name: Optional[str] = None) -> dict:
    """Fetch validation results from SQLite database validation_results table with optional filters."""
    try:
        conn = _get_conn()
        query = "SELECT * FROM validation_results WHERE 1=1"
        params = []
        if company:
            query += " AND UPPER(company_code) = ?"
            params.append(company.upper())
        if document_type:
            query += " AND LOWER(document_type) = ?"
            params.append(document_type.lower())
        if field_name:
            query += " AND LOWER(field_name) = ?"
            params.append(field_name.lower())
        
        cur = conn.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {
            "source": "database:validation_results",
            "records": rows,
            "count": len(rows)
        }
    except Exception as exc:
        return {"error": str(exc), "records": [], "source": "database:validation_results"}


@mcp.tool()
def get_training_mappings(company: Optional[str] = None, document_type: Optional[str] = None, field_name: Optional[str] = None) -> dict:
    """Fetch training mappings from SQLite database training_mappings table with optional filters."""
    try:
        conn = _get_conn()
        query = "SELECT * FROM training_mappings WHERE 1=1"
        params = []
        if company:
            query += " AND UPPER(company_code) = ?"
            params.append(company.upper())
        if document_type:
            query += " AND LOWER(document_type) = ?"
            params.append(document_type.lower())
        if field_name:
            query += " AND LOWER(field_name) = ?"
            params.append(field_name.lower())
        
        cur = conn.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {
            "source": "database:training_mappings",
            "records": rows,
            "count": len(rows)
        }
    except Exception as exc:
        return {"error": str(exc), "records": [], "source": "database:training_mappings"}


# --- Database Standard Tools ---

@mcp.tool()
def get_database_overview() -> dict:
    """Get a high-level summary of all database tables and record counts."""
    return db_reader.get_database_overview()


@mcp.tool()
def list_tables() -> dict:
    """List all tables in the SQLite database."""
    return db_reader.list_tables()


@mcp.tool()
def get_table_schema(table_name: str) -> dict:
    """Get column schema for a specific database table."""
    return db_reader.get_table_schema(table_name)


@mcp.tool()
def search_records(table_name: str, query: str, limit: int = 10) -> dict:
    """Search records in a table by text query."""
    return db_reader.search_records(table_name, query, limit)


@mcp.tool()
def get_sample_records(table_name: str, limit: int = 5) -> dict:
    """Get sample records from a specific database table."""
    return db_reader.get_sample_records(table_name, limit)


@mcp.tool()
def search_database_all(query: str, limit: int = 20) -> dict:
    """Search for records matching the query in all text fields of all tables."""
    return db_reader.search_database_all(query, limit)


@mcp.tool()
def get_sales_summary(limit: int = 5) -> dict:
    """Get read-only sales invoice count and amount summary."""
    return db_reader.get_sales_summary(limit=limit)


# --- Dataset Tools ---

@mcp.tool()
def list_datasets() -> dict:
    """List all available JSON/CSV dataset files."""
    return dataset_reader.list_datasets()


@mcp.tool()
def search_dataset(query: str, company: Optional[str] = None, document_type: Optional[str] = None, field_name: Optional[str] = None) -> dict:
    """Search across all JSON datasets for records matching a query with optional filters."""
    res = dataset_reader.search_dataset(query, company, document_type)
    if field_name and "results" in res:
        filtered = []
        fn_lower = field_name.lower()
        for r in res["results"]:
            rec = r.get("record", {})
            f_name = rec.get("field_name") or rec.get("name")
            if f_name and fn_lower in str(f_name).lower():
                filtered.append(r)
        res["results"] = filtered
        res["count"] = len(filtered)
    return res


@mcp.tool()
def get_dataset_record(dataset_name: str, record_id: Optional[str] = None) -> dict:
    """Fetch records from a specific dataset, optionally by record ID."""
    return dataset_reader.get_dataset_record(dataset_name, record_id)


@mcp.tool()
def get_company_mapping(company: str) -> dict:
    """Look up a company entry from the company mappings registry."""
    return dataset_reader.get_company_mapping(company)


@mcp.tool()
def get_dataset_overview() -> dict:
    """Get a summary of all datasets including counts and company coverage."""
    return dataset_reader.get_dataset_overview()


@mcp.tool()
def get_real_data_status() -> dict:
    """Get connection status and overview of real databases and datasets."""
    from app.config import MCP_MODE, CONNECTED, DB_NAME, DATASETS_DIR
    try:
        db_overview = db_reader.get_database_overview()
    except Exception:
        db_overview = {}
    ds_overview = dataset_reader.get_dataset_overview()
    
    from pathlib import Path
    from app.config import BASE_DIR
    import json
    registry_path = BASE_DIR / "data" / "registry" / "import_registry.json"
    imports_count = 0
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry_data = json.load(f)
                imports_count = len(registry_data.get("imports", []))
        except Exception:
            pass

    return {
        "mcp_mode": MCP_MODE,
        "connected": CONNECTED,
        "db_file_name": DB_NAME,
        "read_only": True,
        "demo_data_active": (MCP_MODE == "demo"),
        "table_count": db_overview.get("table_count", 0) if CONNECTED else 0,
        "total_records": db_overview.get("total_records", 0) if CONNECTED else 0,
        "datasets_count": ds_overview.get("total_datasets", 0),
        "imports_count": imports_count
    }


@mcp.tool()
def get_db_profile() -> dict:
    """Fetch the database schema profile from registry (regenerates if missing)."""
    from app.config import BASE_DIR
    from app.db_profiler import profile_database
    import json
    p_path = BASE_DIR / "data" / "registry" / "db_profile.json"
    if not p_path.exists():
        return profile_database()
    try:
        with open(p_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_dataset_profile() -> dict:
    """Fetch the dataset profile from registry (regenerates if missing)."""
    from app.config import BASE_DIR
    from app.dataset_reader import generate_dataset_profile
    import json
    p_path = BASE_DIR / "data" / "registry" / "dataset_profile.json"
    if not p_path.exists():
        return generate_dataset_profile()
    try:
        with open(p_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def search_datasets_all(query: str) -> dict:
    """Search for records matching the query in all JSON/CSV datasets."""
    return dataset_reader.search_dataset(query)


@mcp.tool()
def list_active_sources() -> dict:
    """List paths and metadata of all active databases and datasets."""
    from app.config import DB_PATH, DATASETS_DIR, CONNECTED, MCP_MODE
    datasets_list = dataset_reader.list_datasets().get("datasets", [])
    return {
        "mcp_mode": MCP_MODE,
        "database": {
            "path": str(DB_PATH),
            "connected": CONNECTED
        },
        "datasets": {
            "directory": str(DATASETS_DIR),
            "files": datasets_list
        }
    }


@mcp.tool()
def list_latest_imports() -> dict:
    """Retrieve all logged entries from the imports registry."""
    from app.config import BASE_DIR
    import json
    registry_path = BASE_DIR / "data" / "registry" / "import_registry.json"
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": str(e), "imports": []}
    return {"imports": [], "message": "No imports registered yet."}


@mcp.tool()
def get_company_datasets(company: str) -> dict:
    """Get all datasets and records matching a specific company code."""
    matching_datasets = []
    from app.config import BASE_DIR
    import json
    p_path = BASE_DIR / "data" / "registry" / "dataset_profile.json"
    if p_path.exists():
        try:
            with open(p_path, "r", encoding="utf-8") as f:
                profiles = json.load(f).get("datasets", [])
                for p in profiles:
                    if p.get("company", "").upper() == company.upper():
                        matching_datasets.append(p)
        except Exception:
            pass
    return {"company": company, "datasets": matching_datasets}


@mcp.tool()
def search_business_entity(entity: str, query: Optional[str] = None, limit: int = 20) -> dict:
    """Search a real ERP business entity such as customer, invoice, supplier, or item."""
    return db_reader.search_business_entity(entity, query=query, limit=limit)


@mcp.tool()
def search_exact_value(value: str, limit: int = 20) -> dict:
    """Search exact ERP codes/numbers across profiled database tables."""
    return db_reader.search_exact_value(value, limit=limit)


# --- Backward Compatible Wrappers ---

def list_tools() -> list:
    """Retrieve standard list of tool schemas from the FastMCP server."""
    tools_list = []
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        for name, t in mcp._tool_manager._tools.items():
            tools_list.append({
                "name": name,
                "description": getattr(t, "description", "") or getattr(t, "__doc__", "") or ""
            })
    elif hasattr(mcp, "_tools"):
        for name, func in mcp._tools.items():
            tools_list.append({
                "name": name,
                "description": func.__doc__ or f"Execute tool {name}"
            })
    elif hasattr(mcp, "tools") and isinstance(mcp.tools, dict):
        for name, t in mcp.tools.items():
            tools_list.append({
                "name": name,
                "description": getattr(t, "description", "") or t.__doc__ or ""
            })
    elif hasattr(mcp, "tools") and isinstance(mcp.tools, list):
        for t in mcp.tools:
            tools_list.append({
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "")
            })
    return tools_list


def call_tool(name: str, arguments: dict) -> dict:
    """Execute a registered tool with standard MCP interface shape."""
    tool_func = None
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools") and name in mcp._tool_manager._tools:
        tool_func = mcp._tool_manager._tools[name]
    elif hasattr(mcp, "_tools") and name in mcp._tools:
        tool_func = mcp._tools[name]
    elif hasattr(mcp, "tools") and isinstance(mcp.tools, dict) and name in mcp.tools:
        tool_func = mcp.tools[name]
    elif hasattr(mcp, "tools") and isinstance(mcp.tools, list):
        for t in mcp.tools:
            if getattr(t, "name", "") == name:
                tool_func = t
                break
                
    if not tool_func:
        raise ValueError(f"Unknown tool: {name}")
        
    try:
        if hasattr(tool_func, "fn"):
            result = tool_func.fn(**arguments)
        elif callable(tool_func):
            result = tool_func(**arguments)
        else:
            result = tool_func.run(**arguments)
            
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result) if not isinstance(result, (dict, list)) else repr(result)
                }
            ],
            "raw_result": result
        }
    except Exception as exc:
        return {
            "is_error": True,
            "content": [{"type": "text", "text": f"Error executing tool '{name}': {str(exc)}"}],
            "raw_result": {"error": str(exc)}
        }


if __name__ == "__main__":
    print(f"Starting MCP server at http://{config.MCP_SERVER_HOST}:{config.MCP_SERVER_PORT}{config.MCP_SERVER_PATH}")
    mcp.run(transport="streamable-http")
