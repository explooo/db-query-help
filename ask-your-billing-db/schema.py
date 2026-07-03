from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]
    keywords: tuple[str, ...]


TABLES: dict[str, TableInfo] = {
    "accounts": TableInfo(
        name="accounts",
        description="Core billing accounts and customer lifecycle status.",
        keywords=("account", "accounts", "status", "region", "created", "customer"),
        columns=(
            ColumnInfo("acc_id", "INTEGER", "Primary account identifier."),
            ColumnInfo("external_id_equip_map", "TEXT", "External equipment mapping identifier; may contain duplicates in dirty data."),
            ColumnInfo("account_status", "TEXT", "Current account status such as active, suspended, or closed."),
            ColumnInfo("created_date", "DATE", "Account creation date."),
            ColumnInfo("region", "TEXT", "Geographic region assigned to the account."),
        ),
    ),
    "bill_invoice_detail": TableInfo(
        name="bill_invoice_detail",
        description="Invoice facts for account billing cycles.",
        keywords=("invoice", "bill", "billing", "amount", "overdue", "due", "payment"),
        columns=(
            ColumnInfo("invoice_id", "INTEGER", "Primary invoice identifier."),
            ColumnInfo("acc_id", "INTEGER", "Foreign key to accounts.acc_id."),
            ColumnInfo("invoice_date", "DATE", "Invoice issue date."),
            ColumnInfo("amount", "NUMERIC", "Invoice amount."),
            ColumnInfo("status", "TEXT", "Invoice status such as paid, open, overdue, or void."),
        ),
    ),
    "transactions": TableInfo(
        name="transactions",
        description="Account-level money movement and adjustments.",
        keywords=("transaction", "transactions", "txn", "payment", "charge", "refund", "adjustment"),
        columns=(
            ColumnInfo("txn_id", "INTEGER", "Primary transaction identifier."),
            ColumnInfo("acc_id", "INTEGER", "Foreign key to accounts.acc_id."),
            ColumnInfo("txn_date", "DATE", "Transaction date."),
            ColumnInfo("txn_type", "TEXT", "Transaction category such as payment, charge, refund, or adjustment."),
            ColumnInfo("amount", "NUMERIC", "Transaction amount."),
        ),
    ),
    "customer_pii": TableInfo(
        name="customer_pii",
        description="Sensitive customer contact information. Only compliance roles should query this table.",
        keywords=("customer", "pii", "phone", "address", "name", "personal", "contact"),
        columns=(
            ColumnInfo("acc_id", "INTEGER", "Primary key and foreign key to accounts.acc_id."),
            ColumnInfo("full_name", "TEXT", "Customer full name."),
            ColumnInfo("phone_number", "TEXT", "Customer phone number."),
            ColumnInfo("address", "TEXT", "Customer postal address."),
        ),
    ),
    "staging_dirty_accounts": TableInfo(
        name="staging_dirty_accounts",
        description="Intentionally messy staging data with text-based account identifiers and duplicates.",
        keywords=("staging", "dirty", "import", "source", "text acc", "bad data"),
        columns=(
            ColumnInfo("staging_id", "INTEGER", "Primary staging row identifier."),
            ColumnInfo("acc_id", "TEXT", "Text-based account identifier used to simulate bad upstream data."),
            ColumnInfo("external_id_equip_map", "TEXT", "Imported external mapping value."),
            ColumnInfo("source_batch", "TEXT", "Load batch identifier."),
            ColumnInfo("load_status", "TEXT", "Import status such as new, duplicate, or rejected."),
        ),
    ),
}

DEFAULT_RELEVANT_TABLES = ("accounts", "bill_invoice_detail", "transactions")
SENSITIVE_COLUMNS = {"full_name", "phone_number", "address"}


def select_relevant_tables(question: str) -> list[str]:
    lowered = question.lower()
    selected: list[str] = []

    for table_name, table in TABLES.items():
        if any(keyword in lowered for keyword in table.keywords):
            selected.append(table_name)

    if not selected:
        selected = list(DEFAULT_RELEVANT_TABLES)

    if any(word in lowered for word in ("pii", "phone", "address", "name", "contact")):
        selected.append("customer_pii")

    seen: set[str] = set()
    ordered: list[str] = []
    for table_name in selected:
        if table_name not in seen and table_name in TABLES:
            seen.add(table_name)
            ordered.append(table_name)

    return ordered


def format_schema_context(table_names: list[str]) -> str:
    lines: list[str] = []
    for table_name in table_names:
        table = TABLES[table_name]
        lines.append(f"Table: {table.name}")
        lines.append(f"Description: {table.description}")
        lines.append("Columns:")
        for column in table.columns:
            lines.append(f"- {column.name} ({column.type}): {column.description}")
        lines.append("")
    return "\n".join(lines).strip()


def all_known_tables() -> tuple[str, ...]:
    return tuple(TABLES.keys())


def all_known_columns() -> dict[str, tuple[str, ...]]:
    return {
        table_name: tuple(column.name for column in table.columns)
        for table_name, table in TABLES.items()
    }
