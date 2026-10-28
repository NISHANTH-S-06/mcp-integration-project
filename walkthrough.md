# Walkthrough - Real MCP Server + Evidence-Gated Ollama Workflow

We have successfully implemented the Real MCP Server, wired up the Ollama Planner and Final Writer with strict evidence gating and fallback logic, polished the Frontend Dashboard with live status cards, and verified all components.

---

## 1. Files Changed

*   **[mcp_real_server.py](file:///D:/MCP%20PROJECT/mcp_real_server.py)** [NEW]: Entry point for the external Real MCP Server. Reuses the 20 registered tools from the internal registry over standard stdio transport.
*   **[app/intent_router.py](file:///D:/MCP%20PROJECT/app/intent_router.py)** [MODIFY]: Added an optional Ollama-based intent routing helper `classify_intent_with_ollama` with a 10s timeout for ambiguous intents.
*   **[app/safety.py](file:///D:/MCP%20PROJECT/app/safety.py)** [MODIFY]: Added the tokenized `validate_ollama_output` No-Hallucination Guard function to cross-examine Ollama's phrasing against database context.
*   **[app/search_service.py](file:///D:/MCP%20PROJECT/app/search_service.py)** [MODIFY]:
    *   Wired Ollama intent routing fallback.
    *   Added empty database evidence handler returning exactly `"Data not found in DB."` for DB query/search intents.
    *   Formulated strict evidence-gated Ollama final response prompt with a 10-second timeout.
    *   Integrated No-Hallucination Guard validation.
*   **[app/main.py](file:///D:/MCP%20PROJECT/app/main.py)** [MODIFY]: Safely extended the `/health` endpoint with flat and nested configurations for the Real MCP Server and Ollama LLM.
*   **[frontend/index.html](file:///D:/MCP%20PROJECT/frontend/index.html)** [MODIFY]: Added dedicated visual status cards for **Real MCP Server** and **Ollama LLM** in the right sidebar.
*   **[frontend/app.js](file:///D:/MCP%20PROJECT/frontend/app.js)** [MODIFY]: Linked frontend API calls to populate the new status cards using metrics from the `/health` endpoint.
*   **[verify.py](file:///D:/MCP%20PROJECT/verify.py)** [MODIFY]: Enhanced test suite with verification functions for `mcp_real_server.py` and the `validate_ollama_output` guard cases.

---

## 2. Key Implementations

### A. Real MCP Server (`mcp_real_server.py`)
Directly imports the FastMCP instance from the core codebase:
```python
from app.mcp_server import mcp
if __name__ == "__main__":
    mcp.run(transport="stdio")
```
This guarantees Cursor, Windsurf, or Claude Desktop can connect to the exact same 20 DB-reading tools over stdio protocol without duplicating any database logic.

### B. No-Hallucination Guard
Validates that Ollama does not hallucinate business-critical values (invoice codes, amounts, dates, quantities, supplier IDs, etc.). To prevent substring matching bugs, the guard tokenizes the context and checks:
```python
input_tokens = set(re.findall(r'\b[a-zA-Z0-9\-_./]+\b', input_pool))
# Checks exact token overlap instead of simple substring matching
```
If validation fails, the guard discards the response, prints a warning to the logs, and returns the safe, rule-based canonical response.

---

## 3. Verification Proof

The test suite was run and passed successfully:
```
==================================================
 Running Output Polish Tests                      
==================================================
  - [OK] Search customer SRI MURUGAN confidence/match_level not Low
  - [OK] TVL25000001 primary=s_invoice_hdr_t, receipt only under Related records
  - [OK] unknownword123 clean no-match, no fake sources, no demo suggestions
  - [OK] Update customer record blocked with exact read-only safety wording
  - [OK] Greeting 'hi' returns exact helpful database assistant intro
  - [OK] 'Search customer' returns helpful browse guidance and samples
  - [OK] 'Search invoice' returns helpful browse guidance and does not leak attachfile_name
  - [OK] JAI MARKETING direct query returns m_customers_t record details
  - [OK] Show sample rows suppresses found_data cards
  - [OK] Show sample rows does not print fake row_id 1
  - [OK] Search customer SRI MURUGAN related records does not leak REVATHI TRADERS
[OK] All output polish tests passed
==================================================
 Running Manual DB Search Endpoint Tests          
==================================================
  - [OK] GET /api/db/search?q=SRI MURUGAN passes
  - [OK] GET /api/db/search?q=JAI MARKETING passes
  - [OK] GET /api/db/search?q=TVL25000001 passes
  - [OK] GET /api/db/search?q=unknownword123 passes
  - [OK] GET /api/db/search write safety passes
Running test_mcp_real_server_presence...
[OK] Real MCP Server script verified
Running test_no_hallucination_guard...
[OK] No-Hallucination Guard verified with 5 test cases
==================================================
 VERIFICATION PASSED: System is secure and ready! 
```

---

## 4. How to Run & Verify

1.  **Start API Backend Server**:
    ```powershell
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
    ```
2.  **Start Web Dashboard Server**:
    ```powershell
    python -m http.server 3010 --directory frontend
    ```
3.  **Run Tests**:
    ```powershell
    .\.venv\Scripts\python verify.py
    ```

---

## 5. Remaining Risks & Mitigation

*   **Ollama Performance**: LLM execution time can vary depending on local hardware. The 10-second timeout ensures that if the local service is slow, a quick fallback to rule-based responses is triggered.
*   **External MCP stdio Connection**: Cursor/Claude Desktop must have Python in their paths or refer to the correct virtual environment executable (`.\.venv\Scripts\python mcp_real_server.py`) in their configurations.

**Final Status: READY FOR DEPLOYMENT**
