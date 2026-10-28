# MCP PROJECT - Port Specifications & Allocation

This document outlines the standardized port configuration for **MCP PROJECT**, ensuring non-conflicting simultaneous operation alongside OCR Platform, AGENT ALINE X, and AUTO QA.

---

## 1. Port Allocations

| Service | Host | Port | Protocol / Endpoint | Environment Variable |
| :--- | :--- | :--- | :--- | :--- |
| **Backend API** | `127.0.0.1` | `8200` | HTTP (`/api/health`, `/api/*`) | `BACKEND_PORT=8200` |
| **Frontend UI** | `127.0.0.1` | `3200` | HTTP (`/`) | `FRONTEND_PORT=3200` |

---

## 2. Multi-Service Suite Port Matrix

To allow all ecosystem components to run simultaneously without port conflicts, ports are assigned in matching 100-block ranges:

| System / Project | Backend Port | Frontend Port | Health Check URL |
| :--- | :--- | :--- | :--- |
| **OCR Platform** | `8000` | `3000` | `http://127.0.0.1:8000/health` |
| **AGENT ALINE X** | `8100` | `3100` | `http://127.0.0.1:8100/health` |
| **MCP PROJECT** | **`8200`** | **`3200`** | **`http://127.0.0.1:8200/api/health`** |
| **AUTO QA** | `8300` | `3300` | `http://127.0.0.1:8300/health` |

---

## 3. Environment Variables Configuration

The `.env` file at the root of the project specifies port configuration:

```env
# Backend and Frontend server settings
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8200
FRONTEND_PORT=3200
```

---

## 4. Health Check Endpoint

- **Endpoint Path:** `/api/health` (also accessible at `/health`)
- **HTTP Method:** `GET`
- **Success Status:** `HTTP 200 OK`
- **Example Response:**
  ```json
  {
    "status": "ok",
    "service": "MCP Data Assistant",
    "version": "1.0.0",
    "read_only_mode": true,
    "read_only": true,
    "mcp_mode": "real",
    "database_type": "sqlite",
    "uptime_seconds": 120,
    "uptime_human": "2m 0s",
    "timestamp": "2026-08-07T15:30:00.000000"
  }
  ```

---

## 5. Service Management Scripts

Four PowerShell management scripts are provided at the project root for automated lifecycle control:

- **`.\start.ps1`**: Reads `.env`, checks for port availability, launches Backend (8200) and Frontend (3200) in hidden background processes, and polls `/api/health` until ready.
- **`.\stop.ps1`**: Finds and terminates processes listening on ports `8200` and `3200`.
- **`.\restart.ps1`**: Invokes `stop.ps1` followed by `start.ps1`.
- **`.\health_check.ps1`**: Queries `http://127.0.0.1:8200/api/health` and `http://127.0.0.1:3200` and displays status diagnostics.

---

## 6. Verification Commands

```powershell
# 1. Start Services
.\start.ps1

# 2. Perform Health Diagnostic
.\health_check.ps1

# 3. Stop Services
.\stop.ps1
```
