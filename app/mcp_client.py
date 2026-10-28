"""
Local MCP Client module for MCP Data Assistant.
Provides client-side access to the local FastMCP Server tools.
"""
import ast
import asyncio
import json
from typing import Optional, Dict, Any
import httpx
import app.mcp_server
from app import config
from app.config import DB_PATH, DB_NAME

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # pragma: no cover - exercised only before dependencies are installed
    ClientSession = None
    streamable_http_client = None

def log_tool_audit(tool_name: str, arguments: dict, records_count: int):
    import datetime
    from pathlib import Path
    from app.config import BASE_DIR
    
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "audit.log"
    
    timestamp = datetime.datetime.utcnow().isoformat()
    searched = arguments.get("table_name") or arguments.get("dataset_name") or "all"
    query_val = arguments.get("query") or arguments.get("field_name") or "None"
    
    log_entry = (
        f"[{timestamp}] "
        f"Tool: {tool_name} | "
        f"Query: {query_val} | "
        f"Searched: {searched} | "
        f"Returned: {records_count} | "
        f"Blocked Write: False\n"
    )
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except OSError:
        pass

class MCPClient:
    """Client adapter for the real Streamable HTTP MCP server.

    The in-process path remains as a development fallback so existing tests and
    local scripts can still run when the separate MCP server is not started.
    Chat search code uses the async HTTP path and records the transport in
    mcp_trace.
    """
    
    def __init__(self, server_url: Optional[str] = None):
        self.server_url = server_url or config.MCP_SERVER_URL

    def _normalize_result(self, name: str, arguments: dict, result: Any, transport: str) -> dict:
        records_count = 0
        if result is not None:
            if isinstance(result, dict):
                if "records" in result:
                    records_count = len(result["records"])
                elif "results" in result:
                    records_count = len(result["results"])
                elif "tables" in result:
                    records_count = len(result["tables"])
            elif isinstance(result, list):
                records_count = len(result)
        log_tool_audit(name, arguments, records_count)
        return {
            "content": [{"type": "text", "text": str(result) if not isinstance(result, (dict, list)) else repr(result)}],
            "raw_result": result,
            "mcp_trace": {
                "tool": name,
                "arguments": arguments,
                "transport": transport,
                "server_url": self.server_url if transport == "streamable_http" else "in_process",
                "records_returned": records_count,
            },
        }

    def _extract_call_result(self, call_result: Any) -> Any:
        structured = getattr(call_result, "structuredContent", None)
        if structured is not None:
            if isinstance(structured, dict) and "result" in structured and len(structured) == 1:
                return structured["result"]
            return structured

        content = getattr(call_result, "content", None) or []
        if content:
            text = getattr(content[0], "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except Exception:
                    try:
                        return ast.literal_eval(text)
                    except Exception:
                        return text
        return None

    def _call_tool_in_process(self, name: str, arguments: Optional[dict] = None) -> dict:
        if arguments is None:
            arguments = {}

        db_tools = {
            "get_validation_results", "get_training_mappings",
            "get_database_overview", "list_tables",
            "get_table_schema", "search_records",
            "get_sample_records", "search_database_all",
            "search_business_entity", "search_exact_value",
            "get_sales_summary"
        }
        if name in db_tools and not DB_PATH.exists():
            safe_msg = f"Database file is missing. Please place a SQLite database at: ./data/real_db/{DB_NAME}"
            return {
                "is_error": True,
                "content": [{"type": "text", "text": safe_msg}],
                "raw_result": {"error": "Database file missing", "setup_required": True}
            }

        tool_func = None
        if (
            hasattr(app.mcp_server.mcp, "_tool_manager")
            and hasattr(app.mcp_server.mcp._tool_manager, "_tools")
            and name in app.mcp_server.mcp._tool_manager._tools
        ):
            tool_func = app.mcp_server.mcp._tool_manager._tools[name]
        elif hasattr(app.mcp_server.mcp, "_tools") and name in app.mcp_server.mcp._tools:
            tool_func = app.mcp_server.mcp._tools[name]
        elif hasattr(app.mcp_server.mcp, "tools") and isinstance(app.mcp_server.mcp.tools, dict) and name in app.mcp_server.mcp.tools:
            tool_func = app.mcp_server.mcp.tools[name]
        elif hasattr(app.mcp_server.mcp, "tools") and isinstance(app.mcp_server.mcp.tools, list):
            # Real FastMCP tool list mapping
            for t in app.mcp_server.mcp.tools:
                if getattr(t, "name", "") == name:
                    # If callable, assign it
                    tool_func = t
                    break
        
        if not tool_func:
            raise ValueError(f"Tool '{name}' not found on FastMCP server")
            
        try:
            # If the tool is a class wrapper or function, invoke it
            if hasattr(tool_func, "fn"):
                result = tool_func.fn(**arguments)
            elif callable(tool_func):
                result = tool_func(**arguments)
            else:
                # Fallback invocation
                result = tool_func.run(**arguments)
                
            return self._normalize_result(name, arguments, result, "in_process_fallback")
        except Exception as exc:
            return {
                "is_error": True,
                "content": [{"type": "text", "text": f"Error executing tool '{name}': {str(exc)}"}],
                "raw_result": {"error": str(exc)},
                "mcp_trace": {
                    "tool": name,
                    "arguments": arguments,
                    "transport": "in_process_fallback",
                    "server_url": "in_process",
                    "error": str(exc),
                },
            }

    async def call_tool_async(self, name: str, arguments: Optional[dict] = None) -> dict:
        """Invoke a tool through the real MCP Streamable HTTP server."""
        if arguments is None:
            arguments = {}

        if ClientSession is None or streamable_http_client is None:
            fallback = self._call_tool_in_process(name, arguments)
            fallback.setdefault("mcp_trace", {})["fallback_reason"] = "mcp package unavailable"
            return fallback

        try:
            async with httpx.AsyncClient(timeout=config.MCP_HTTP_TIMEOUT_SECONDS) as http_client:
                async with streamable_http_client(
                    self.server_url,
                    http_client=http_client,
                ) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        if getattr(result, "isError", False):
                            text = result.content[0].text if result.content else f"MCP tool '{name}' failed"
                            raise RuntimeError(text)
                        raw = self._extract_call_result(result)
                        return self._normalize_result(name, arguments, raw, "streamable_http")
        except Exception as exc:
            fallback = self._call_tool_in_process(name, arguments)
            fallback.setdefault("mcp_trace", {})["fallback_reason"] = str(exc)
            return fallback

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """Synchronous compatibility wrapper."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.call_tool_async(name, arguments))
        return self._call_tool_in_process(name, arguments)

    def list_tools(self) -> list:
        """Retrieve standard list of tool schemas from the FastMCP server."""
        tools_list = []
        if hasattr(app.mcp_server.mcp, "_tool_manager") and hasattr(app.mcp_server.mcp._tool_manager, "_tools"):
            for name, t in app.mcp_server.mcp._tool_manager._tools.items():
                tools_list.append({
                    "name": name,
                    "description": getattr(t, "description", "") or getattr(t, "__doc__", "") or ""
                })
        elif hasattr(app.mcp_server.mcp, "_tools"):
            for name, func in app.mcp_server.mcp._tools.items():
                tools_list.append({
                    "name": name,
                    "description": func.__doc__ or f"Execute tool {name}"
                })
        elif hasattr(app.mcp_server.mcp, "tools") and isinstance(app.mcp_server.mcp.tools, dict):
            for name, t in app.mcp_server.mcp.tools.items():
                tools_list.append({
                    "name": name,
                    "description": getattr(t, "description", "") or t.__doc__ or ""
                })
        elif hasattr(app.mcp_server.mcp, "tools") and isinstance(app.mcp_server.mcp.tools, list):
            for t in app.mcp_server.mcp.tools:
                tools_list.append({
                    "name": getattr(t, "name", ""),
                    "description": getattr(t, "description", "")
                })
        return tools_list

    async def list_tools_async(self) -> dict:
        if ClientSession is None or streamable_http_client is None:
            return {"tools": self.list_tools(), "transport": "in_process_fallback"}
        try:
            async def _connect():
                async with httpx.AsyncClient(timeout=0.5) as http_client:
                    async with streamable_http_client(
                        self.server_url,
                        http_client=http_client,
                    ) as (read_stream, write_stream, _get_session_id):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            result = await session.list_tools()
                            tools = [
                                {"name": t.name, "description": getattr(t, "description", "") or ""}
                                for t in result.tools
                            ]
                            return {"tools": tools, "transport": "streamable_http", "server_url": self.server_url}
            return await asyncio.wait_for(_connect(), timeout=0.5)
        except Exception as exc:
            return {
                "tools": self.list_tools(),
                "transport": "in_process_fallback",
                "server_url": self.server_url,
                "fallback_reason": str(exc),
            }

    def search_database_all(self, query: str, limit: int = 20) -> dict:
        """Call the search_database_all tool to search all tables in the DB."""
        return self.call_tool("search_database_all", {"query": query, "limit": limit})

    def list_tables(self) -> dict:
        """Call the list_tables tool to list all user tables."""
        return self.call_tool("list_tables", {})

    def get_database_overview(self) -> dict:
        """Call the get_database_overview tool to get overview of the database."""
        return self.call_tool("get_database_overview", {})

    def get_real_data_status(self) -> dict:
        """Call the get_real_data_status tool."""
        return self.call_tool("get_real_data_status", {})

    def get_db_profile(self) -> dict:
        """Call the get_db_profile tool."""
        return self.call_tool("get_db_profile", {})

    def get_dataset_profile(self) -> dict:
        """Call the get_dataset_profile tool."""
        return self.call_tool("get_dataset_profile", {})

    def search_datasets_all(self, query: str) -> dict:
        """Call the search_datasets_all tool."""
        return self.call_tool("search_datasets_all", {"query": query})

    def list_active_sources(self) -> dict:
        """Call the list_active_sources tool."""
        return self.call_tool("list_active_sources", {})

    def list_latest_imports(self) -> dict:
        """Call the list_latest_imports tool."""
        return self.call_tool("list_latest_imports", {})

    def get_company_datasets(self, company: str) -> dict:
        """Call the get_company_datasets tool."""
        return self.call_tool("get_company_datasets", {"company": company})

    async def search_business_entity_async(self, entity: str, query: Optional[str] = None, limit: int = 20) -> dict:
        """Call the search_business_entity MCP tool."""
        return await self.call_tool_async("search_business_entity", {"entity": entity, "query": query, "limit": limit})

    async def search_exact_value_async(self, value: str, limit: int = 20) -> dict:
        """Call the search_exact_value MCP tool."""
        return await self.call_tool_async("search_exact_value", {"value": value, "limit": limit})

    async def search_database_all_async(self, query: str, limit: int = 20) -> dict:
        """Call the search_database_all MCP tool."""
        return await self.call_tool_async("search_database_all", {"query": query, "limit": limit})


