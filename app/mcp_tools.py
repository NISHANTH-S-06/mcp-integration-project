"""
MCP-style tool registry.
Provides a unified interface to call all read-only data tools.
"""
from app import db_reader, dataset_reader


TOOL_REGISTRY = {
    # Database tools
    "list_tables": db_reader.list_tables,
    "get_table_schema": db_reader.get_table_schema,
    "search_records": db_reader.search_records,
    "get_record_by_id": db_reader.get_record_by_id,
    "get_database_overview": db_reader.get_database_overview,
    # Dataset tools
    "list_datasets": dataset_reader.list_datasets,
    "search_dataset": dataset_reader.search_dataset,
    "get_dataset_record": dataset_reader.get_dataset_record,
    "get_company_mapping": dataset_reader.get_company_mapping,
    "get_dataset_overview": dataset_reader.get_dataset_overview,
}


def run_tool(tool_name: str, **kwargs) -> dict:
    """Execute a registered tool by name with keyword arguments."""
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_name}", "available_tools": list(TOOL_REGISTRY.keys())}
    try:
        return TOOL_REGISTRY[tool_name](**kwargs)
    except Exception as exc:
        return {"error": f"Tool '{tool_name}' failed: {str(exc)}"}


def get_tool_descriptions() -> list[dict]:
    """Return metadata about available tools."""
    return [
        {
            "name": "list_tables",
            "category": "database",
            "description": "List all tables in the SQLite database.",
            "parameters": [],
        },
        {
            "name": "get_table_schema",
            "category": "database",
            "description": "Get column schema for a specific database table.",
            "parameters": ["table_name"],
        },
        {
            "name": "search_records",
            "category": "database",
            "description": "Search records in a table by text query.",
            "parameters": ["table_name", "query", "limit"],
        },
        {
            "name": "get_record_by_id",
            "category": "database",
            "description": "Fetch a single database record by its ID.",
            "parameters": ["table_name", "id"],
        },
        {
            "name": "get_database_overview",
            "category": "database",
            "description": "Get a high-level summary of all database tables and record counts.",
            "parameters": [],
        },
        {
            "name": "list_datasets",
            "category": "dataset",
            "description": "List all available JSON/CSV dataset files.",
            "parameters": [],
        },
        {
            "name": "search_dataset",
            "category": "dataset",
            "description": "Search across all datasets for records matching a query.",
            "parameters": ["query", "company (optional)", "document_type (optional)"],
        },
        {
            "name": "get_dataset_record",
            "category": "dataset",
            "description": "Fetch records from a specific dataset, optionally by record ID.",
            "parameters": ["dataset_name", "record_id (optional)"],
        },
        {
            "name": "get_company_mapping",
            "category": "dataset",
            "description": "Look up a company entry from the company mappings registry.",
            "parameters": ["company"],
        },
        {
            "name": "get_dataset_overview",
            "category": "dataset",
            "description": "Get a summary of all datasets including counts and company coverage.",
            "parameters": [],
        },
    ]
