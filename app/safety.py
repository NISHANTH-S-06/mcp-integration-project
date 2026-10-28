"""
Safety module — blocks any write/destructive SQL operations.
All user inputs must pass through these checks first.
"""
import re
from app.config import BLOCKED_SQL_KEYWORDS

READ_ONLY_RESPONSE = (
    "This assistant is read-only. I can only explain existing "
    "database and dataset records."
)

WRITE_INTENT_PATTERNS = [
    r"\b(update|delete|remove|edit|change|modify|insert|add|create|drop|alter"
    r"|write|save|set|replace|truncate|reset|clear|wipe|fix|save mapping|change database|fix this record)\b",
]

def check_query_safety(text: str) -> tuple[bool, str]:
    """
    Returns (is_safe, reason).
    is_safe=False means the request should be blocked.
    """
    upper = text.upper()
    for kw in BLOCKED_SQL_KEYWORDS:
        # word-boundary match
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Blocked SQL keyword detected: {kw}"
    return True, "ok"


def check_write_intent(text: str) -> bool:
    """
    Returns True if the user is asking to write/modify/delete data.
    """
    lower = text.lower()
    for pattern in WRITE_INTENT_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def sanitize_table_name(name: str) -> str:
    """Allow only alphanumeric and underscores."""
    return re.sub(r"[^\w]", "", name)


def sanitize_path(path: str) -> str:
    """Strip any directory traversal attempts."""
    # Remove any .. or / or \ sequences
    return re.sub(r"[/\\.]", "", path)


def validate_ollama_output(response: str, question: str, context_text: str, canonical_answer: str) -> bool:
    """
    Returns True if the Ollama response does not contain any hallucinated business-critical data.
    """
    # Extract all alphanumeric/numeric/decimal words from the input context pool
    input_pool = (question + "\n" + context_text + "\n" + canonical_answer).lower()
    input_tokens = set(re.findall(r'\b[a-zA-Z0-9\-_./]+\b', input_pool))
    
    # Support sub-token lookup for decimals and separators
    for word in list(input_tokens):
        if "." in word:
            parts = word.split(".")
            input_tokens.add(parts[0])
            if len(parts) > 1:
                input_tokens.add(parts[1])
        if "/" in word:
            input_tokens.update(word.split("/"))
        if "-" in word:
            input_tokens.update(word.split("-"))
        if "_" in word:
            input_tokens.update(word.split("_"))

    # 1. Extract alphanumeric codes of length >= 4 containing at least one digit (e.g. invoice/PO/SO/GST codes)
    codes = re.findall(r'\b[A-Za-z0-9\-_./]{4,}\b', response)
    for code in codes:
        code_lower = code.lower()
        # Whitelist table/field names or known boilerplate
        if "read_only" in code_lower or "read-only" in code_lower or "rowid" in code_lower or "row_id" in code_lower:
            continue
        # If the code contains at least one digit, it's business critical (invoice, ID, PO, etc.)
        if any(c.isdigit() for c in code):
            if code_lower not in input_tokens:
                # If there are hyphens, letters, or underscores, it is a business code
                if any(c.isalpha() for c in code) or "-" in code or "_" in code:
                    return False
    
    # 2. Extract decimal float amounts (e.g. 125000.00)
    amounts = re.findall(r'\b\d+\.\d{2,}\b', response)
    for amt in amounts:
        if amt not in input_tokens:
            int_part = amt.split(".")[0]
            if int_part not in input_tokens:
                return False

    # 3. Extract dates (e.g. YYYY-MM-DD or DD/MM/YYYY or DD-MM-YYYY)
    date_patterns = [
        r'\b\d{4}[-/]\d{2}[-/]\d{2}\b',
        r'\b\d{2}[-/]\d{2}[-/]\d{4}\b',
    ]
    for pattern in date_patterns:
        dates = re.findall(pattern, response)
        for d in dates:
            if d.lower() not in input_tokens:
                return False

    # 4. Extract integer values >= 100 (ignoring years 2000-2030)
    integers = re.findall(r'\b\d{3,}\b', response)
    for val in integers:
        val_int = int(val)
        if 2000 <= val_int <= 2030:
            continue
        if val not in input_tokens:
            return False

    return True

