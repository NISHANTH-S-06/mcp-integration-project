"""
Read-only dataset reader.
Reads JSON/CSV files from the ./data/datasets directory only.
No arbitrary file access allowed.
"""
import json
import csv
import re
from pathlib import Path
from typing import Any

from app import config
from app.safety import sanitize_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allowed_path(filename: str) -> Path | None:
    """Return the full path only if it resolves inside config.DATASETS_DIR."""
    clean = sanitize_path(filename)
    # Try exact name first, then with extensions
    for candidate in [clean, f"{clean}.json", f"{clean}.csv"]:
        full = (config.DATASETS_DIR / candidate).resolve()
        try:
            full.relative_to(config.DATASETS_DIR.resolve())
            if full.exists():
                return full
        except ValueError:
            pass
    return None


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# MCP-style read-only tools
# ---------------------------------------------------------------------------

def list_datasets() -> dict:
    """List all JSON/CSV files available in the datasets directory."""
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for ext in ("*.json", "*.csv"):
        for f in config.DATASETS_DIR.glob(ext):
            stat = f.stat()
            files.append({
                "name": f.stem,
                "filename": f.name,
                "extension": f.suffix,
                "size_bytes": stat.st_size,
                "source": f"dataset:{f.stem}",
            })
    return {
        "source": "datasets_directory",
        "datasets": files,
        "count": len(files),
    }


# Stop words to ignore when extracting search keywords
_STOP_WORDS = {
    "show", "list", "get", "find", "what", "which", "where", "when", "how",
    "why", "is", "are", "the", "a", "an", "for", "of", "in", "on", "at",
    "to", "and", "or", "not", "all", "any", "me", "my", "can", "do", "does",
    "give", "tell", "about", "from", "with", "its", "their", "this", "that",
    "display", "fetch", "retrieve", "search", "return",
}


def _extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a natural language query."""
    words = re.findall(r"[a-z0-9_]+", query.lower())
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 1]
    return keywords if keywords else [query.lower()]


def search_dataset(query: str, company: str = None, document_type: str = None) -> dict:
    """
    Search across all JSON datasets for records matching the query.
    Uses keyword-based matching so natural language queries work correctly.
    Optionally filter by company code or document_type.
    """
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    keywords = _extract_keywords(query)
    results = []

    for json_file in config.DATASETS_DIR.glob("*.json"):
        try:
            data = _load_json(json_file)
        except Exception:
            continue

        # Filter by company if requested
        file_company = str(data.get("company", "")).upper()
        if company and file_company != company.upper():
            continue

        # Filter by document type if requested
        file_doc_type = str(data.get("document_type", "")).lower()
        if document_type and document_type.lower() not in file_doc_type:
            continue

        records = data.get("records", [])
        for rec in records:
            rec_str = json.dumps(rec).lower()
            # Match if ANY keyword appears in the record
            matched_keywords = [kw for kw in keywords if kw in rec_str]
            if matched_keywords:
                score = sum(rec_str.count(kw) for kw in matched_keywords) / len(keywords)
                results.append({
                    "dataset": json_file.stem,
                    "company": data.get("company"),
                    "document_type": data.get("document_type"),
                    "source": f"dataset:{json_file.stem}:record_id={rec.get('id', '?')}",
                    "record": rec,
                    "match_score": score,
                    "matched_keywords": matched_keywords,
                })
            if len(results) >= config.MAX_RESULTS:
                break

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return {
        "query": query,
        "company_filter": company,
        "document_type_filter": document_type,
        "results": results[:config.MAX_RESULTS],
        "count": len(results),
        "source": "dataset:search",
    }


def _score_match(text: str, query: str) -> float:
    """Simple relevance score: frequency of query terms found in text."""
    words = query.split()
    if not words:
        return 0.0
    return sum(text.count(w) for w in words) / len(words)


def get_dataset_record(dataset_name: str, record_id: str = None) -> dict:
    """Fetch a specific record from a named dataset, or return all records."""
    path = _allowed_path(dataset_name)
    if not path:
        return {"error": f"Dataset '{dataset_name}' not found or not allowed.", "record": None}

    try:
        data = _load_json(path)
    except Exception as exc:
        return {"error": str(exc), "record": None}

    records = data.get("records", [])
    if record_id:
        for rec in records:
            if str(rec.get("id", "")) == str(record_id):
                return {
                    "source": f"dataset:{dataset_name}:id={record_id}",
                    "dataset": dataset_name,
                    "record": rec,
                    "found": True,
                }
        return {
            "source": f"dataset:{dataset_name}",
            "dataset": dataset_name,
            "record": None,
            "found": False,
        }

    return {
        "source": f"dataset:{dataset_name}",
        "dataset": dataset_name,
        "meta": {
            "name": data.get("dataset_name"),
            "company": data.get("company"),
            "document_type": data.get("document_type"),
            "version": data.get("version"),
            "last_updated": data.get("last_updated"),
            "total_fields": data.get("total_fields"),
        },
        "records": records,
        "count": len(records),
        "found": True,
    }


def get_company_mapping(company: str) -> dict:
    """Look up a company entry from company_mappings.json."""
    path = config.DATASETS_DIR / "company_mappings.json"
    if not path.exists():
        return {"error": "company_mappings.json not found.", "company": company}

    try:
        data = _load_json(path)
    except Exception as exc:
        return {"error": str(exc), "company": company}

    records = data.get("records", [])
    company_upper = company.upper()
    for rec in records:
        if rec.get("company_code", "").upper() == company_upper:
            return {
                "source": f"dataset:company_mappings:company={company}",
                "company": company,
                "record": rec,
                "found": True,
            }

    return {
        "source": "dataset:company_mappings",
        "company": company,
        "record": None,
        "found": False,
        "available_companies": [r.get("company_code") for r in records],
    }


def get_dataset_overview() -> dict:
    """Return a high-level summary of all available datasets."""
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    datasets_summary = []
    total_records = 0
    companies = set()
    doc_types = set()
    total_mappings = 0

    for json_file in config.DATASETS_DIR.glob("*.json"):
        try:
            data = _load_json(json_file)
            records = data.get("records", [])
            cnt = len(records)
            total_records += cnt
            company = data.get("company", "")
            if company and company != "ALL":
                companies.add(company)
            doc_type = data.get("document_type", "")
            if doc_type:
                doc_types.add(doc_type)
            # Count mapping records
            for r in records:
                if "mapped_to" in r:
                    total_mappings += 1
            datasets_summary.append({
                "name": json_file.stem,
                "company": company,
                "document_type": doc_type,
                "record_count": cnt,
                "source": f"dataset:{json_file.stem}",
            })
        except Exception:
            continue

    return {
        "source": "datasets:overview",
        "total_datasets": len(datasets_summary),
        "total_records": total_records,
        "total_companies": len(companies),
        "total_document_types": len(doc_types),
        "total_mappings": total_mappings,
        "companies": sorted(companies),
        "document_types": sorted(doc_types),
        "datasets": datasets_summary,
    }


def detect_dataset_type(filename: str, company: str, doc_type: str) -> str:
    combined = f"{filename} {company} {doc_type}".lower()
    if "customer" in combined:
        return "customers"
    elif "invoice" in combined or "rechnung" in combined:
        return "invoices"
    elif "purchase" in combined or "po" in combined:
        return "purchase_orders"
    elif "validation" in combined:
        return "validations"
    elif "mapping" in combined:
        return "mappings"
    else:
        return "general"


def generate_dataset_profile() -> dict:
    """Scan the config.DATASETS_DIR, profile files and write data/registry/dataset_profile.json."""
    from app.config import BASE_DIR
    registry_dir = BASE_DIR / "data" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    profile_path = registry_dir / "dataset_profile.json"

    datasets_summary = []
    if config.DATASETS_DIR.exists() and config.DATASETS_DIR.is_dir():
        for ext in ("*.json", "*.csv"):
            for f in config.DATASETS_DIR.glob(ext):
                records = []
                fields = []
                company = "Unknown"
                doc_type = "Unknown"
                if f.suffix == ".json":
                    try:
                        with open(f, "r", encoding="utf-8") as file:
                            data = json.load(file)
                            company = data.get("company") or data.get("company_code") or "Unknown"
                            doc_type = data.get("document_type") or "Unknown"
                            records = data.get("records", [])
                            if records and isinstance(records, list):
                                if isinstance(records[0], dict):
                                    fields = list(records[0].keys())
                    except Exception:
                        pass
                elif f.suffix == ".csv":
                    try:
                        with open(f, "r", encoding="utf-8") as file:
                            reader = csv.DictReader(file)
                            fields = reader.fieldnames or []
                            records = [row for row in reader]
                            name_parts = f.stem.split("_")
                            if name_parts:
                                company = name_parts[0]
                                doc_type = " ".join(name_parts[1:])
                    except Exception:
                        pass

                datasets_summary.append({
                    "file_name": f.name,
                    "company": company,
                    "document_type": doc_type,
                    "records": len(records),
                    "fields": fields,
                    "sample_records": records[:3] if isinstance(records, list) else [],
                    "detected_type": detect_dataset_type(f.name, str(company), str(doc_type))
                })

    profile_data = {
        "datasets": datasets_summary
    }

    with open(profile_path, "w", encoding="utf-8") as file:
        json.dump(profile_data, file, indent=2)

    return profile_data


# Auto-generate dataset profile if missing on startup
try:
    from app.config import BASE_DIR
    p_path = BASE_DIR / "data" / "registry" / "dataset_profile.json"
    if not p_path.exists():
        generate_dataset_profile()
except Exception:
    pass

