# Implementation Plan - Real MCP Server + Evidence-Gated Ollama Workflow

We will implement the Real MCP Server, wire up the Ollama Planner and Final Writer with strict evidence gating and fallback logic, and polish the Frontend Dashboard's components.

## User Review Required

> [!IMPORTANT]
> - **Ollama model**: The system currently uses `llama3` by default as configured in `.env`. Please ensure Ollama is running locally and has the `llama3` (or configured) model downloaded (`ollama run llama3`).
> - **Rule-based fallback**: If Ollama is offline or slow (exceeds 10s timeout), the system will seamlessly fall back to deterministic, rule-based responses to guarantee system availability.
> - **No-Hallucination Guard**: A strict validator will cross-examine Ollama's response. If Ollama generates any invoice codes, quantities, or amounts not present in the database context, the system will discard the response and fall back to the safe, rule-based data sheet.

---

## Proposed Changes

### 1. Real MCP Server Layer

#### [NEW] [mcp_real_server.py](file:///D:/MCP%20PROJECT/mcp_real_server.py)
Exposes the existing 20 MCP tools registered in `app/mcp_server.py` to external clients (e.g., Cursor, Windsurf, Claude Desktop) over `stdio` transport.
- Imports `mcp` from `app.mcp_server`.
- Invokes `mcp.run(transport="stdio")` inside `__main__`.
- Guarantees no duplication of tool definitions or database logic.

---

### 2. Ollama Planner + Evidence-Gated Final Writer

#### [MODIFY] [intent_router.py](file:///D:/MCP%20PROJECT/app/intent_router.py)
Adds an optional async Ollama classification fallback `classify_intent_with_ollama` when rule-based intent classification is ambiguous (returns `"unknown"` or `"db_search"`).
- Uses a concise prompt to classify the user question into one of the core entity/query intents.
- Falls back to the rule-based intent category if Ollama is unreachable.

#### [MODIFY] [search_service.py](file:///D:/MCP%20PROJECT/app/search_service.py)
Redesigns the search orchestration flow to wire the Ollama Final Answer Writer:
- Removes `exact_value_search`, `business_entity_search`, and other database query intents from `OLLAMA_SKIP_INTENTS` to enable natural wording rewrite.
- Only skips greetings, write attempts, and structural/meta queries (`database_overview`, `table_list`, `dataset_overview`, `schema_query`, `sample_rows_query`).
- If `scored_sources` is empty for any search/entity/exact query: bypasses Ollama and directly returns `"Data not found in DB."`.
- Constructs a strict, evidence-gated prompt enforcing:
  1. Use only given evidence in the database context.
  2. Do not invent any values, invoice numbers, amounts, or customer names.
  3. If context is empty, reply exactly: `"Data not found in DB."`.
  4. End answer with `"Read Only: true"`.
- Calls Ollama with a strict **10-second timeout**.
- Implements a **No-Hallucination Guard** that scans Ollama's response for any numeric or alphanumeric codes (like invoice numbers or float values) and matches them against the database context. If any unrecognized token is found, it blocks the response and falls back to the safe, rule-based response.

---

### 3. Frontend Polish

#### [MODIFY] [index.html](file:///D:/MCP%20PROJECT/frontend/index.html)
Polishes the sidebar-right elements by adding separate information status cards:
- **Real MCP Server Card (`#mcpCard`)**: Displays Server URL, Transport type, Registered tools count, and Connection status.
- **Ollama LLM Card (`#ollamaCard`)**: Displays Model name, Active model status, and the list of available local models.

#### [MODIFY] [app.js](file:///D:/MCP%20PROJECT/frontend/app.js)
Integrates the new status cards into the API loading flow:
- Reads `mcp_server_url`, `mcp_transport`, `mcp_tools_count`, and `ollama` object properties from the backend `/health` endpoint.
- Renders the details dynamically inside `#mcpCard` and `#ollamaCard`.
- Enforces smooth loading skeleton states and clear badge classifications.

---

### 4. Verification & Testing

#### [MODIFY] [verify.py](file:///D:/MCP%20PROJECT/verify.py)
Enhances the validation suite:
- Adds a test to check if `mcp_real_server.py` is present and successfully imports `mcp`.
- Adds tests to verify the no-hallucination guard behavior by feeding fake/correct evidence to the validator.

---

## Verification Plan

### Automated Tests
Run the test suite using `verify.py`:
```powershell
python verify.py
```

### Manual Verification
1. Launch backend and frontend servers:
   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
   python -m http.server 3010 --directory frontend
   ```
2. Open `http://127.0.0.1:3010` in the browser.
3. Check the right sidebar: verify the **Real MCP Server** and **Ollama LLM** cards populate successfully from the `/health` endpoint.
4. Run chat query `ABC25000001` with Ollama enabled: verify the invoice details are formatted in a clean natural phrasing based on database evidence, and ends with `Read Only: true`.
5. Run chat query `DELETE FROM tblinvoice_master`: verify the query is blocked immediately by the safety layer without calling Ollama.
6. Verify fallback: Stop Ollama and ask `ABC25000001` again. Verify it falls back to the rule-based response.
7. External client test: Connect an external client (e.g. Cursor) to `python mcp_real_server.py` and list tools to verify all 20 live tools are visible.
