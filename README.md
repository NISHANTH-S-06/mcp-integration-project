# MCP Data Assistant

A local, read-only ERP chatbot that answers from the connected SQLite database through a real MCP server. The FastAPI backend calls MCP tools, the frontend renders source-backed answers, and Ollama can optionally rewrite responses using only retrieved evidence.

## Features

- Real MCP server over Streamable HTTP at `http://127.0.0.1:8020/mcp`
- FastAPI backend at `http://127.0.0.1:8010`
- ERP chat dashboard frontend at `http://127.0.0.1:3010`
- Read-only SQLite access with path restrictions, query safety checks, and timeouts
- Structured chat responses with `primary_results`, `related_results`, `mcp_trace`, and `checked_sources`
- Optional local Ollama support; no OpenAI API key required

## Quick Start

```powershell
cd "D:\MCP PROJECT"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start services in this order:

```powershell
.\run_mcp_server.bat
.\run_backend.bat
.\run_frontend.bat
```

Open:

| Service | URL |
| --- | --- |
| Chat UI | http://127.0.0.1:3010 |
| API | http://127.0.0.1:8010 |
| Health | http://127.0.0.1:8010/health |
| MCP Tools | http://127.0.0.1:8010/api/mcp/tools |
| API Docs | http://127.0.0.1:8010/docs |

## Real Data

The current `.env` is configured for:

```text
MCP_MODE=real
SQLITE_DB_PATH=./data/real_db/ifiveerp_skm_demo.db
DATASET_DIR=./data/real_datasets
MCP_SERVER_URL=http://127.0.0.1:8020/mcp
OLLAMA_ENABLED=true
```

The imported ERP database contains 676 tables and 4,451,228 rows according to `data/registry/import_registry.json` and verification output.

## Verification

```powershell
.venv\Scripts\python.exe verify.py
```

Useful smoke tests:

```powershell
Invoke-WebRequest http://127.0.0.1:8010/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8010/api/mcp/tools -UseBasicParsing
```

Chat questions to try:

- `Search customer ACME TRADERS`
- `Search invoice ABC25000001`
- `Search supplier INITECH DISTRIBUTORS`
- `GLOBEX MARKETING`
- `Show database overview`
- `Show sample rows from s_invoice_hdr_t`
- `Update customer record name to new`

## Safety

- Database opens through SQLite read-only URI mode.
- DB paths must stay inside the project `data/` directory.
- Write/destructive requests are blocked before reaching MCP tools.
- MCP exposes only read tools.
- The UI and API report source evidence and MCP trace metadata for database-backed answers.
