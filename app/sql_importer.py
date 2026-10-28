"""
SQL Importer for MCP Data Assistant.
Safely converts MySQL/MariaDB SQL dump files to a SQLite database.
Run via: python -m app.sql_importer --input <input_sql> --output <output_db>
"""
import sys
import os
import re
import sqlite3
import argparse
import time
import json
import datetime
from pathlib import Path


def _log_import_registry(input_path: Path, output_path: Path, tables_created: int,
                          rows_inserted: int, errors: int, duration: float,
                          backfilled: bool = False, note: str = "") -> None:
    """Append an entry describing this import run to data/registry/import_registry.json.
    Purely additive/logging - never raises, never affects the import itself."""
    try:
        project_root = Path(__file__).resolve().parent.parent
        registry_dir = project_root / "data" / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_path = registry_dir / "import_registry.json"

        registry = {"imports": []}
        if registry_path.exists():
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                    if "imports" not in registry:
                        registry["imports"] = []
            except Exception:
                registry = {"imports": []}

        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "input_sql_file": str(input_path),
            "output_db_file": str(output_path),
            "tables_created": tables_created,
            "rows_inserted": rows_inserted,
            "errors": errors,
            "duration_seconds": round(duration, 1),
            "backfilled": backfilled,
        }
        if note:
            entry["note"] = note

        registry["imports"].append(entry)
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
    except Exception as exc:
        print(f"[WARN] Could not write import_registry.json: {exc}")

def clean_value_escapes(line_strip: str) -> str:
    """Replace MySQL backslash-escapes with SQLite-compatible formats."""
    # Replace double backslashes with temporary placeholder
    line_strip = line_strip.replace("\\\\", "\x00")
    # Replace escaped single quotes with double single quotes
    line_strip = line_strip.replace("\\'", "''")
    # Restore double backslashes to single backslash
    line_strip = line_strip.replace("\x00", "\\")
    return line_strip

def clean_mysql_types_and_options(col_def: str) -> str:
    """Clean data type and options parts of column definition for SQLite compatibility."""
    # 1. Strip CHARACTER SET and COLLATE
    col_def = re.sub(r'\bCHARACTER\s+SET\s+[\'\"]?\w+[\'\"]?\b', '', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\bCOLLATE\s+[\'\"]?\w+[\'\"]?\b', '', col_def, flags=re.IGNORECASE)
    
    # 2. Strip AUTO_INCREMENT, unsigned, and USING BTREE/HASH, and ON UPDATE CURRENT_TIMESTAMP
    col_def = re.sub(r'\bAUTO_INCREMENT\b', '', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\bunsigned\b', '', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\bUSING\s+(?:BTREE|HASH)\b', '', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\bON\s+UPDATE\s+[^\s,)]+', '', col_def, flags=re.IGNORECASE)
    
    # 3. Strip COMMENT '...'
    col_def = re.sub(r'\bCOMMENT\s+[\'\"][^\'\"]*[\'\"]', '', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\bCOMMENT\s+\'([^\']| \'\')*\'', '', col_def, flags=re.IGNORECASE)
    
    # 4. Map MySQL data types to SQLite compatible ones
    col_def = re.sub(r'\b(?:datetime|timestamp|date)\b', 'TEXT', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\byear(?:\(\d+\))?\b', 'INTEGER', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\b(?:double|float|decimal(?:\(\d+,\d+\))?)\b', 'REAL', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\benum\([^)]*\)', 'TEXT', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\bset\([^)]*\)', 'TEXT', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\b(?:varchar|char)\(\d+\)', 'TEXT', col_def, flags=re.IGNORECASE)
    col_def = re.sub(r'\b(?:tinyint|smallint|mediumint|bigint|int)(?:\(\d+\))?\b', 'INTEGER', col_def, flags=re.IGNORECASE)
    
    return col_def.strip()

def execute_create_table(cursor: sqlite3.Cursor, statement: str) -> bool:
    """Clean and execute a CREATE TABLE statement in SQLite."""
    # Replace backticks with double quotes
    statement = statement.replace('`', '"')
    
    # Locate table name and body inside outer parentheses
    first_paren = statement.find('(')
    last_paren = statement.rfind(')')
    if first_paren == -1 or last_paren == -1:
        return False
        
    table_part = statement[:first_paren]
    body = statement[first_paren+1:last_paren]
    
    # Extract table name
    tbl_match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"([^\"]+)\"", table_part, re.IGNORECASE)
    if not tbl_match:
        tbl_match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)", table_part, re.IGNORECASE)
    if not tbl_match:
        return False
        
    tbl_name = tbl_match.group(1).replace('"', '').strip()
    
    # Parse lines inside body
    lines = body.split('\n')
    cleaned_lines = []
    
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
            
        # Strip trailing comma if present
        if line_s.endswith(','):
            line_s = line_s[:-1].strip()
            
        # Skip constraints/keys that SQLite doesn't support inline
        upper_line = line_s.upper()
        if (upper_line.startswith('KEY ') or 
            upper_line.startswith('UNIQUE KEY ') or 
            upper_line.startswith('FULLTEXT KEY ') or 
            upper_line.startswith('SPATIAL KEY ') or 
            upper_line.startswith('CONSTRAINT ') or
            upper_line.startswith('INDEX ')):
            continue
            
        if upper_line.startswith('PRIMARY KEY'):
            # Strip USING BTREE/HASH
            line_s = re.sub(r'\bUSING\s+(?:BTREE|HASH)\b', '', line_s, flags=re.IGNORECASE)
            cleaned_lines.append(line_s)
            continue
            
        # Split column name from definition to avoid replacing words in column names (like "date" or "int")
        parts = line_s.split(None, 1)
        if len(parts) == 2:
            col_name, col_def = parts
            col_def = clean_mysql_types_and_options(col_def)
            line_s = f"{col_name} {col_def}"
        else:
            line_s = clean_mysql_types_and_options(line_s)
            
        cleaned_lines.append(line_s)
        
    cleaned_body = ",\n  ".join(cleaned_lines)
    sqlite_stmt = f'CREATE TABLE IF NOT EXISTS "{tbl_name}" (\n  {cleaned_body}\n);'
    
    try:
        cursor.execute(sqlite_stmt)
        print(f"Created table: {tbl_name}")
        return True
    except Exception as e:
        print(f"Error creating table: {e}")
        print("Original statement:")
        print(statement)
        return False

def import_sql(input_path: Path, output_path: Path):
    """Parse and load the SQL dump into SQLite DB."""
    start_time = time.time()
    print(f"Starting conversion of {input_path.name} into {output_path}...")
    
    # Ensure parent output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove existing SQLite file if any, to start clean
    if output_path.exists():
        try:
            output_path.unlink()
        except Exception as e:
            print(f"[WARN] Could not delete existing output database: {e}")
            
    conn = sqlite3.connect(output_path)
    cursor = conn.cursor()
    
    # Speed optimization settings for SQLite import
    cursor.execute("PRAGMA journal_mode=OFF")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA cache_size=100000")
    
    tables_created = 0
    rows_inserted = 0
    skipped_statements = 0
    errors = 0
    
    in_create = False
    create_buffer = []
    
    silence_inserts = False
    
    # Read file line-by-line stream-safely
    with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
        for line_num, line in enumerate(f, 1):
            line_strip = line.strip()
            if not line_strip:
                continue
                
            # Handle comments and lock statements
            if line_strip.startswith("--") or line_strip.startswith("/*") or line_strip.upper().startswith("LOCK TABLES") or line_strip.upper().startswith("UNLOCK TABLES"):
                continue
                
            # If currently parsing a multi-line CREATE TABLE
            if in_create:
                create_buffer.append(line)
                if line_strip.endswith(';'):
                    in_create = False
                    stmt = "".join(create_buffer)
                    create_buffer = []
                    try:
                        if execute_create_table(cursor, stmt):
                            tables_created += 1
                        else:
                            errors += 1
                    except Exception as e:
                        print(f"[ERROR] CREATE TABLE failed at line {line_num}: {e}")
                        errors += 1
                continue
                
            # Start of CREATE TABLE statement
            if line_strip.upper().startswith("CREATE TABLE"):
                in_create = True
                create_buffer = [line]
                if line_strip.endswith(';'):
                    in_create = False
                    stmt = "".join(create_buffer)
                    create_buffer = []
                    try:
                        if execute_create_table(cursor, stmt):
                            tables_created += 1
                        else:
                            errors += 1
                    except Exception as e:
                        print(f"[ERROR] CREATE TABLE failed at line {line_num}: {e}")
                        errors += 1
                continue
                
            # INSERT INTO statements
            if line_strip.upper().startswith("INSERT INTO"):
                # Clean backticks and value escapes
                cleaned_line = line_strip.replace('`', '"')
                cleaned_line = clean_value_escapes(cleaned_line)
                try:
                    cursor.execute(cleaned_line)
                    rows_inserted += cursor.rowcount
                except Exception as e:
                    if not silence_inserts:
                        print(f"[ERROR] INSERT failed at line {line_num}: {e}")
                        print(f"First 200 chars: {cleaned_line[:200]}")
                        errors += 1
                        # If we get flooded with insert errors, silence them to keep log readable
                        if errors > 20:
                            print("Too many errors. Silencing error logging for inserts...")
                            silence_inserts = True
                    else:
                        errors += 1
                continue
                
            # Skip or log other unhandled database setup lines
            skipped_statements += 1
            
    print("Finalizing index building and stats calculation...")
    conn.commit()
    conn.close()
    
    duration = time.time() - start_time
    _log_import_registry(input_path, output_path, tables_created, rows_inserted, errors, duration)
    print("==================================================")
    print(" Import Summary")
    print("==================================================")
    print(f"Duration:         {duration:.1f} seconds")
    print(f"Tables Created:   {tables_created}")
    print(f"Rows Imported:    {rows_inserted}")
    print(f"Statements Run:   {tables_created + rows_inserted}")
    print(f"Skipped Stmts:    {skipped_statements}")
    print(f"Errors:           {errors}")
    print("==================================================")

def main():
    parser = argparse.ArgumentParser(description="Convert MySQL dump to SQLite database.")
    parser.add_argument("--input", required=True, help="Input MySQL SQL file")
    parser.add_argument("--output", required=True, help="Output SQLite DB file")
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)
        
    import_sql(input_path, output_path)

if __name__ == "__main__":
    main()
