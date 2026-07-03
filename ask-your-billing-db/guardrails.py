from __future__ import annotations

from dataclasses import dataclass
import re

from schema import SENSITIVE_COLUMNS, all_known_tables


WRITE_OR_DESTRUCTIVE_PATTERNS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|replace|create|grant|revoke|attach|detach|vacuum|pragma)\b",
    re.IGNORECASE,
)
COMMENT_PATTERNS = re.compile(r"--|/\*|\*/")
TABLE_PATTERN = re.compile(r"\b(from|join)\s+([a-zA-Z_][\w]*)", re.IGNORECASE)
SINGLE_SELECT_PATTERN = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
DOMAIN_HINTS = (
    "account",
    "invoice",
    "billing",
    "bill",
    "transaction",
    "payment",
    "customer",
    "region",
    "status",
    "phone",
    "address",
    "name",
)


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str
    matched_tables: tuple[str, ...] = ()


def classify_intent(question: str) -> str:
    lowered = question.lower().strip()
    if not lowered:
        return "out_of_scope"
    if WRITE_OR_DESTRUCTIVE_PATTERNS.search(lowered):
        return "write_or_destructive"
    if any(word in lowered for word in DOMAIN_HINTS):
        return "read_query"
    return "out_of_scope"


def extract_tables(sql: str) -> tuple[str, ...]:
    tables = []
    for _, table_name in TABLE_PATTERN.findall(sql):
        if table_name not in tables:
            tables.append(table_name)
    return tuple(tables)


def validate_sql(sql: str, role: str = "analyst") -> GuardrailVerdict:
    normalized = " ".join(sql.strip().split())
    if not normalized:
        return GuardrailVerdict(False, "Empty SQL was returned by the model.")
    if normalized.upper() == "NO_VALID_QUERY":
        return GuardrailVerdict(False, "The model declined to produce a valid query.")
    if not SINGLE_SELECT_PATTERN.match(normalized):
        return GuardrailVerdict(False, "Only SELECT statements are allowed.")
    if COMMENT_PATTERNS.search(normalized):
        return GuardrailVerdict(False, "SQL comments are not allowed.")
    if ";" in normalized:
        return GuardrailVerdict(False, "Multiple statements are not allowed.")
    if WRITE_OR_DESTRUCTIVE_PATTERNS.search(normalized):
        return GuardrailVerdict(False, "Destructive or write SQL was detected.")

    matched_tables = extract_tables(normalized)
    known_tables = set(all_known_tables())
    unknown_tables = [table_name for table_name in matched_tables if table_name not in known_tables]
    if unknown_tables:
        return GuardrailVerdict(False, f"Unknown table reference(s): {', '.join(unknown_tables)}.", matched_tables)

    if role != "compliance_officer" and (
        "customer_pii" in matched_tables
        or any(re.search(rf"\b{column}\b", normalized, re.IGNORECASE) for column in SENSITIVE_COLUMNS)
    ):
        return GuardrailVerdict(False, "PII access is restricted to compliance_officer.", matched_tables)

    return GuardrailVerdict(True, "SQL passed static validation.", matched_tables)


def enforce_row_limit(sql: str, limit: int = 100) -> str:
    base_sql = sql.strip().rstrip(";")
    return f"SELECT * FROM ({base_sql}) AS limited_result LIMIT {limit}"


def is_domain_query(question: str) -> bool:
    return classify_intent(question) == "read_query"
