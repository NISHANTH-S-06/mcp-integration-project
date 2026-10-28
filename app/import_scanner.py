"""
Import Scanner for MCP Data Assistant.
Scans data/imports/inbox/ for new files, processes them, classifies them,
and logs them into data/registry/import_registry.json.
Can be run via: python -m app.import_scanner --scan
"""
import os
import sys
import json
import hashlib
import shutil
import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import BASE_DIR
from app.db_profiler import profile_database
from app.dataset_reader import generate_dataset_profile

def get_file_hash(filepath: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def detect_file_info(filepath: Path) -> tuple[str, str, str, int]:
    """Detect file type, company, document type, and record count."""
    suffix = filepath.suffix.lower()
    records_count = 0
    company = "Unknown"
    doc_type = "Unknown"
    detected_type = "unknown"

    if suffix in (".db", ".sqlite", ".sqlite3"):
        detected_type = "sqlite"
        try:
            conn = sqlite3.connect(filepath)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                records_count += cur.fetchone()[0]
            conn.close()
            company = "DB_Import"
            doc_type = "Database"
        except Exception:
            pass
    elif suffix == ".json":
        detected_type = "json"
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                company = data.get("company") or data.get("company_code") or "Unknown"
                doc_type = data.get("document_type") or "Unknown"
                records = data.get("records", [])
                if isinstance(records, list):
                    records_count = len(records)
        except Exception:
            pass
    elif suffix == ".csv":
        detected_type = "csv"
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                records_count = sum(1 for row in reader)
            name_parts = filepath.stem.split("_")
            if name_parts:
                company = name_parts[0]
                doc_type = " ".join(name_parts[1:])
        except Exception:
            pass

    return detected_type, str(company), str(doc_type), records_count

def scan_imports() -> dict:
    """Scan data/imports/inbox/ for new datasets or databases."""
    inbox_dir = BASE_DIR / "data" / "imports" / "inbox"
    processed_dir = BASE_DIR / "data" / "imports" / "processed"
    registry_dir = BASE_DIR / "data" / "registry"

    inbox_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)

    registry_path = registry_dir / "import_registry.json"

    # Load existing registry
    registry = {"imports": []}
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
                if "imports" not in registry:
                    registry["imports"] = []
        except Exception:
            pass

    existing_imports = registry["imports"]

    # Gather files in inbox
    files = list(inbox_dir.glob("*.*"))
    processed_count = 0

    for f in files:
        if f.is_dir():
            continue

        file_hash = get_file_hash(f)
        detected_type, company, doc_type, records_count = detect_file_info(f)

        # Classify the import
        classification = "new file"
        
        # Check duplicate by hash
        hash_exists = any(imp.get("hash") == file_hash for imp in existing_imports)
        if hash_exists:
            classification = "duplicate"
        else:
            # Check version or same company
            same_company_same_doc = any(
                imp.get("company") == company and imp.get("document_type") == doc_type
                for imp in existing_imports
            )
            same_company_diff_doc = any(
                imp.get("company") == company and imp.get("document_type") != doc_type
                for imp in existing_imports
            )
            same_name = any(imp.get("file_name") == f.name for imp in existing_imports)

            if same_company_same_doc or same_name:
                classification = "version"
            elif same_company_diff_doc:
                classification = "same company new document"

        # Move/copy file to processed (rename if conflict exists)
        dest_filename = f.name
        dest_path = processed_dir / dest_filename
        if dest_path.exists():
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            dest_filename = f"{f.stem}_{timestamp}{f.suffix}"
            dest_path = processed_dir / dest_filename

        shutil.move(str(f), str(dest_path))

        # Add to registry
        new_entry = {
            "file_name": dest_filename,
            "original_name": f.name,
            "import_time": datetime.utcnow().isoformat() + "Z",
            "status": "processed",
            "detected_type": detected_type,
            "company": company,
            "document_type": doc_type,
            "records_count": records_count,
            "hash": file_hash,
            "classification": classification
        }

        existing_imports.append(new_entry)
        processed_count += 1
        print(f"[OK] Processed {f.name} as {classification} -> {dest_filename}")

    if processed_count > 0:
        # Save updated registry
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)

        # Regenerate profiles
        profile_database()
        generate_dataset_profile()
        print(f"[OK] Regenerated profiles after scanning.")

    return {"processed_count": processed_count, "registry": registry}

if __name__ == "__main__":
    if "--scan" in sys.argv:
        scan_imports()
    else:
        print("Usage: python -m app.import_scanner --scan")
