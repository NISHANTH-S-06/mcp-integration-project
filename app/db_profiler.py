"""
Database Profiler for MCP Data Assistant.
Inspects database tables, columns, primary keys, record counts, and structures profile.
Can be run via: python -m app.db_profiler --profile
"""
import sys
import os
import json
import sqlite3
from pathlib import Path

from app.config import DB_PATH, DB_FILE_NAME, BASE_DIR

def detect_entity_type(table_name: str) -> str:
    """Classify SQLite tables into domain entity types."""
    name_lower = table_name.lower()
    if "customer" in name_lower:
        return "customers"
    elif "invoice" in name_lower or "rechnung" in name_lower:
        return "invoices"
    elif "purchase" in name_lower or "po" in name_lower:
        return "purchase_orders"
    elif "validation" in name_lower:
        return "validations"
    elif "mapping" in name_lower:
        return "mappings"
    else:
        return "general"

def profile_database() -> dict:
    """Analyze active SQLite database schema and generate db_profile.json."""
    registry_dir = BASE_DIR / "data" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    profile_path = registry_dir / "db_profile.json"

    if not DB_PATH.exists() or not DB_PATH.is_file():
        # Return empty profile if DB missing
        empty_profile = {
            "db_file_name": DB_FILE_NAME,
            "tables": []
        }
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(empty_profile, f, indent=2)
        print(f"[WARN] Database file not found: {DB_PATH}. Generated empty profile.")
        return empty_profile

    try:
        uri = f"file:{DB_PATH.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Fetch all user tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [row["name"] for row in cursor.fetchall()]

        profile_tables = []

        for t in tables:
            # Table Info
            cursor.execute(f'PRAGMA table_info("{t}")')
            columns_info = cursor.fetchall()
            
            columns = []
            column_types = {}
            primary_keys = []
            searchable_columns = []

            for col in columns_info:
                name = col["name"]
                c_type = col["type"]
                columns.append(name)
                column_types[name] = c_type
                if col["pk"]:
                    primary_keys.append(name)
                
                # Identify text/searchable columns
                c_type_upper = c_type.upper()
                if "TEXT" in c_type_upper or "CHAR" in c_type_upper or c_type == "":
                    searchable_columns.append(name)

            # Record Count
            try:
                cursor.execute(f'SELECT COUNT(*) FROM "{t}"')
                record_count = cursor.fetchone()[0]
            except Exception:
                record_count = 0

            # Sample Rows (Top 5)
            try:
                cursor.execute(f'SELECT * FROM "{t}" LIMIT 5')
                sample_rows = [dict(row) for row in cursor.fetchall()]
            except Exception:
                sample_rows = []

            profile_tables.append({
                "table_name": t,
                "columns": columns,
                "column_types": column_types,
                "primary_keys": primary_keys,
                "record_count": record_count,
                "sample_rows": sample_rows,
                "searchable_columns": searchable_columns,
                "detected_entity_type": detect_entity_type(t)
            })

        conn.close()

        profile_data = {
            "db_file_name": DB_FILE_NAME,
            "tables": profile_tables
        }

        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, indent=2)

        print(f"[OK] Database profiled successfully. Saved to {profile_path}")
        return profile_data

    except Exception as e:
        print(f"[ERROR] Database profiling failed: {e}")
        # Return fallback empty profile
        fallback = {
            "db_file_name": DB_FILE_NAME,
            "tables": [],
            "error": str(e)
        }
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(fallback, f, indent=2)
        return fallback

if __name__ == "__main__":
    if "--profile" in sys.argv:
        profile_database()
    else:
        print("Usage: python -m app.db_profiler --profile")
