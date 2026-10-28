"""
Intent Router module for MCP Data Assistant.
Classifies user queries into discrete semantic categories including write attempts.
"""
import re

ALIAS_MAP = {
    "customer id": ["customer_id", "customer_code", "client_id", "party_code", "buyer_code"],
    "invoice no": ["invoice_number", "inv_no", "bill_no", "document_no", "invoice number"],
    "po no": ["po_number", "purchase_order_no", "order_no", "po number"],
    "supplier code": ["supplier_code", "vendor_code"],
    "company name": ["company", "company_name", "customer_name", "supplier_name"]
}

def expand_query_with_aliases(q: str) -> str:
    expanded = q.lower()
    for standard, aliases in ALIAS_MAP.items():
        for alias in aliases:
            if alias in expanded:
                expanded += " " + standard + " " + " ".join(aliases)
                break
    return expanded

def is_exact_code(word: str) -> bool:
    word = word.strip().upper()
    if not (4 <= len(word) <= 30):
        return False
    if not any(c.isdigit() for c in word):
        return False
    if not re.match(r'^[A-Z0-9\-_./]+$', word):
        return False
    if re.match(r'^\d{4}-\d{2}-\d{2}$', word): # YYYY-MM-DD
        return False
    return True

def detect_exact_value(q: str) -> str or None:
    q_clean = q.lower().strip("?.!,;\"'“” ")
    # Strip prefixes
    prefixes = [
        "search for ", "search ", "find in database ", "find in db ", "find ", "show ",
        "exact invoice number ", "exact invoice ", "invoice number ", "invoice ",
        "supplier ", "customer ", "item "
    ]
    for p in prefixes:
        if q_clean.startswith(p):
            q_clean = q_clean[len(p):].strip()
            break
    if is_exact_code(q_clean):
        return q_clean.upper()

    # Natural-language detail requests can include an ERP code inside a
    # sentence, for example: "ARM25000003 tell the detail".
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-./]{3,29}", q):
        if is_exact_code(token):
            return token.strip().upper()
    return None

def classify_intent(query: str) -> str:
    """Classify query string into a predefined intent category."""
    q_raw = query.lower().strip("?.!,;\"'“” ")
    q_raw = q_raw.replace("data base", "database").replace("data-base", "database")
    
    # 1. write_attempt check first
    write_keywords = ["update", "delete", "insert", "create", "drop", "alter", "replace", "truncate", "edit", "modify", "save new", "remove"]
    if any(kw in q_raw for kw in write_keywords):
        return "write_attempt"
        
    write_patterns = [
        r"\b(update|delete|edit|insert|create|drop|alter|replace|truncate|modify|remove)\b",
        r"save mapping",
        r"change database",
        r"fix this record",
        r"save new"
    ]
    for pattern in write_patterns:
        if re.search(pattern, q_raw):
            return "write_attempt"
            
    # 2. greeting
    greetings = {"hi", "hello", "hey", "good morning", "good evening", "help"}
    if q_raw in greetings:
        return "greeting"
        

    # 4. Schema / Sample queries
    if any(kw in q_raw for kw in ["schema of", "schema for", "show schema", "describe table", "table schema", "show table"]):
        return "schema_query"
    if any(kw in q_raw for kw in ["sample rows from", "sample rows", "sample records from", "sample records"]):
        return "sample_rows_query"

    q = expand_query_with_aliases(q_raw)
        
    # 5. mapping_query
    if "mapping" in q or "alias" in q or "aliases" in q or "mapped" in q or q in ("customer id", "customer_id"):
        return "mapping_query"
        
    # 6. validation_query
    if (
        "validation" in q 
        or "validated" in q 
        or "low confidence" in q 
        or "failed validations" in q 
        or "failed fields" in q 
        or "failed field" in q
        or "show failed fields" in q
    ):
        return "validation_query"
        
    # 7. table_list
    if any(kw in q for kw in [
        "list database tables", "list tables", "show tables", "database tables", "db tables",
        "what tables", "which tables", "tables do you have", "tables you have",
        "show me tables", "list all tables"
    ]):
        return "table_list"
        
    # 8. database_overview
    q_overview = q_raw
    for w in ["show", "the", "a", "an", "what", "is", "of", "about", "your", "our", "my", "tell", "me", "view", "display", "print"]:
        q_overview = re.sub(rf"\b{w}\b", "", q_overview).strip()
    q_overview = re.sub(r"\s+", " ", q_overview)

    if (
        "database overview" in q 
        or "db overview" in q 
        or "database status" in q
        or "db status" in q
        or "table count" in q 
        or "records count" in q
        or "database summary" in q
        or "db summary" in q
        or "show database" in q
        or "show db" in q
        or "how many tables" in q
        or q == "db"
        or q == "database"
        or q_overview in ("database", "db", "database status", "db status", "database overview", "db overview", "database summary", "db summary")
    ):
        return "database_overview"
        
    # 9. dataset_overview
    if (
        "show datasets" in q 
        or "dataset count" in q 
        or "recent datasets" in q 
        or "dataset overview" in q
        or "datasets overview" in q
        or "list datasets" in q
        or q == "datasets"
        or q == "dataset"
    ):
        return "dataset_overview"
        
    # 10. Business entity search
    from app.business_router import detect_entity
    detected_ent = detect_entity(query)
    exact_code = detect_exact_value(query)

    aggregate_words = ["how many", "count", "total", "sum", "value", "amount", "overall", "how much", "average", "avg"]
    if detected_ent in ("invoice", "customer", "supplier", "sales") and any(w in q_raw for w in aggregate_words):
        return f"aggregate_query:{detected_ent}"

    if detected_ent == "sales" and any(w in q for w in aggregate_words):
        return "sales_summary"

    if detected_ent:
        return f"business_entity_search:{detected_ent}"
        
    # 11. Exact value search
    if exact_code:
        return "exact_value_search"
        
    # 12. invoice_issue (legacy demo check)
    if "invoice" in q and any(kw in q for kw in ["not fill", "filling", "issue", "no not mapping", "not mapping", "missing"]):
        return "invoice_issue"
        
    # 13. po_query (legacy demo check)
    if re.search(r"\bpo\b", q) or "purchase order" in q or "poprint" in q:
        return "po_query"
        
    # 14. db_search (explicit)
    if any(kw in q for kw in ["search database", "search db", "search for", "find in database", "find in db"]):
        return "db_search"

    # 15. Smart fallback: strip stop/noise words and re-check entity detection
    #     Handles natural language questions like:
    #     "what are the company you have?", "how many customers do we have?",
    #     "list the customer names", "total sales amount", etc.
    STOP_WORDS = {
        "what", "are", "the", "is", "a", "an", "do", "does", "did", "have", "has",
        "had", "our", "we", "us", "you", "your", "they", "them", "their", "this",
        "that", "how", "many", "much", "can", "tell", "me", "show", "give", "please",
        "any", "all", "new", "my", "i", "which", "there", "about", "for", "of", "in",
        "on", "at", "to", "and", "or", "not", "so", "by", "with", "from", "like",
        "get", "list", "find", "fetch", "display", "print", "bring",
        # Quantity / interrogative extras
        "id", "ids", "it", "its", "count", "total", "num", "number",
        "see", "check", "pull", "out", "up", "over", "down",
    }
    cleaned_tokens = [t for t in q_raw.split() if t not in STOP_WORDS and len(t) >= 3]
    cleaned_for_retry = " ".join(cleaned_tokens)
    if cleaned_for_retry:
        retry_ent = detect_entity(cleaned_for_retry)
        if retry_ent:
            return f"business_entity_search:{retry_ent}"

    # 15b. If cleaned tokens look like a proper business name / search term
    #      (≥2 meaningful tokens, none of which are stop-words), route to
    #      db_search so search_database_all can find it using token fallback.
    if len(cleaned_tokens) >= 2:
        return "db_search"

    # 16. Final fallback: treat any unrecognized question as a full-text DB search
    #     so the database is always searched and a real answer is returned.
    if len(q_raw.split()) >= 2:
        return "db_search"

    return "unknown"


async def classify_intent_with_ollama(query: str) -> str:
    """Use Ollama to refine ambiguous intents."""
    from app import llm_client
    
    prompt = (
        "You are an ERP database routing assistant.\n"
        "Analyze the user query below and classify it into exactly one of these categories:\n"
        "- 'business_entity_search:customer' (searching or checking customer info)\n"
        "- 'business_entity_search:invoice' (searching or checking invoice info)\n"
        "- 'business_entity_search:supplier' (searching or checking supplier/vendor info)\n"
        "- 'business_entity_search:item' (searching or checking product/item info)\n"
        "- 'database_overview' (summary of tables/records in DB)\n"
        "- 'table_list' (listing tables)\n"
        "- 'unknown' (none of the above apply)\n\n"
        "Rules:\n"
        "1. Return ONLY the category name. Do not explain your choice. Do not include quotes.\n"
        "2. If it is ambiguous, return 'unknown'.\n\n"
        f"Query: \"{query}\"\n\n"
        "Category:"
    )
    try:
        # Call Ollama with 10 seconds timeout
        category = await llm_client._query_ollama(prompt, timeout=10)
        if category:
            category = category.strip().strip("'\"").lower()
            valid_categories = {
                "business_entity_search:customer",
                "business_entity_search:invoice",
                "business_entity_search:supplier",
                "business_entity_search:item",
                "database_overview",
                "table_list",
                "unknown"
            }
            if category in valid_categories:
                return category
    except Exception:
        pass
    return "unknown"

