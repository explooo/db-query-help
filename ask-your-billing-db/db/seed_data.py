from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).with_name("billing.sqlite")


FIRST_NAMES = (
    "Ava",
    "Maya",
    "Noah",
    "Liam",
    "Zara",
    "Ethan",
    "Priya",
    "Olivia",
    "Mateo",
    "Grace",
    "Amir",
    "Hana",
    "Leo",
    "Iris",
    "Sofia",
    "Owen",
)
LAST_NAMES = (
    "Patel",
    "Nguyen",
    "Carter",
    "Kim",
    "Bennett",
    "Singh",
    "Ortiz",
    "Cooper",
    "Hughes",
    "Lopez",
    "Foster",
    "Ramirez",
    "Walker",
    "Ali",
    "Reed",
    "Taylor",
)
STREETS = (
    "Maple",
    "Oak",
    "Cedar",
    "Pine",
    "Sunset",
    "Riverside",
    "Lakeview",
    "Highland",
    "Summit",
    "Willow",
)
CITIES = (
    "Austin",
    "Seattle",
    "Denver",
    "Chicago",
    "Atlanta",
    "Phoenix",
    "Boston",
    "Portland",
    "Raleigh",
    "Nashville",
)
REGIONS = ("north", "south", "east", "west", "central")
ACCOUNT_STATUSES = ("active", "active", "active", "suspended", "closed")
INVOICE_STATUSES = ("paid", "paid", "paid", "open", "overdue", "void")
TXN_TYPES = ("payment", "charge", "adjustment", "refund")


def _random_date(rng: random.Random, start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=rng.randint(0, delta_days))


def _generate_phone(rng: random.Random) -> str:
    area = rng.choice((201, 202, 303, 408, 415, 503, 617, 646, 704, 786, 917))
    return f"+1-{area}-{rng.randint(200, 999):03d}-{rng.randint(1000, 9999):04d}"


def _generate_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _generate_address(rng: random.Random) -> str:
    return f"{rng.randint(10, 9999)} {rng.choice(STREETS)} St, {rng.choice(CITIES)}, US"


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        DROP TABLE IF EXISTS audit_log;
        DROP TABLE IF EXISTS staging_dirty_accounts;
        DROP TABLE IF EXISTS customer_pii;
        DROP TABLE IF EXISTS transactions;
        DROP TABLE IF EXISTS bill_invoice_detail;
        DROP TABLE IF EXISTS accounts;

        CREATE TABLE accounts (
            acc_id INTEGER PRIMARY KEY,
            external_id_equip_map TEXT,
            account_status TEXT,
            created_date DATE,
            region TEXT
        );

        CREATE TABLE bill_invoice_detail (
            invoice_id INTEGER PRIMARY KEY,
            acc_id INTEGER,
            invoice_date DATE,
            amount NUMERIC,
            status TEXT,
            FOREIGN KEY (acc_id) REFERENCES accounts(acc_id)
        );

        CREATE TABLE transactions (
            txn_id INTEGER PRIMARY KEY,
            acc_id INTEGER,
            txn_date DATE,
            txn_type TEXT,
            amount NUMERIC,
            FOREIGN KEY (acc_id) REFERENCES accounts(acc_id)
        );

        CREATE TABLE customer_pii (
            acc_id INTEGER PRIMARY KEY,
            full_name TEXT,
            phone_number TEXT,
            address TEXT,
            FOREIGN KEY (acc_id) REFERENCES accounts(acc_id)
        );

        CREATE TABLE staging_dirty_accounts (
            staging_id INTEGER PRIMARY KEY,
            acc_id TEXT,
            external_id_equip_map TEXT,
            source_batch TEXT,
            load_status TEXT
        );

        CREATE TABLE audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL,
            user_question TEXT NOT NULL,
            intent TEXT NOT NULL,
            generated_sql TEXT,
            guardrail_allowed INTEGER NOT NULL,
            guardrail_reason TEXT NOT NULL,
            matched_tables TEXT,
            result_preview TEXT
        );
        """
    )
    connection.commit()


def populate_data(connection: sqlite3.Connection, *, seed: int = 42) -> dict[str, int]:
    rng = random.Random(seed)
    accounts: list[tuple[int, str, str, str, str]] = []
    pii_rows: list[tuple[int, str, str, str]] = []
    invoice_rows: list[tuple[int, int, str, float, str]] = []
    transaction_rows: list[tuple[int, int, str, str, float]] = []
    staging_rows: list[tuple[int, str, str, str, str]] = []

    start_date = date(2021, 1, 1)
    end_date = date(2026, 7, 1)
    invoice_id = 1
    txn_id = 1
    duplicate_external_ids: list[str] = []

    for acc_id in range(1, 81):
        if acc_id <= 10:
            external_id = f"EXT-{1000 + acc_id}"
            duplicate_external_ids.append(external_id)
        elif acc_id % 11 == 0:
            external_id = rng.choice(duplicate_external_ids)
        else:
            external_id = f"EXT-{1000 + acc_id + rng.randint(0, 150)}"

        created = _random_date(rng, start_date, end_date)
        status = rng.choice(ACCOUNT_STATUSES)
        region = rng.choice(REGIONS)
        accounts.append((acc_id, external_id, status, created.isoformat(), region))

        pii_rows.append((acc_id, _generate_name(rng), _generate_phone(rng), _generate_address(rng)))

        invoice_count = rng.randint(1, 3)
        for _ in range(invoice_count):
            invoice_date = _random_date(rng, created, end_date)
            amount = round(rng.uniform(18.0, 420.0), 2)
            invoice_status = rng.choice(INVOICE_STATUSES)
            invoice_rows.append((invoice_id, acc_id, invoice_date.isoformat(), amount, invoice_status))
            invoice_id += 1

        txn_count = rng.randint(1, 4)
        for _ in range(txn_count):
            txn_date = _random_date(rng, created, end_date)
            txn_type = rng.choice(TXN_TYPES)
            if txn_type == "payment":
                amount = round(rng.uniform(25.0, 300.0), 2)
            elif txn_type == "charge":
                amount = round(rng.uniform(10.0, 180.0), 2)
            elif txn_type == "refund":
                amount = round(rng.uniform(5.0, 120.0), 2)
            else:
                amount = round(rng.uniform(1.0, 45.0), 2)
            transaction_rows.append((txn_id, acc_id, txn_date.isoformat(), txn_type, amount))
            txn_id += 1

    for idx, external_id in enumerate(duplicate_external_ids[:5], start=1):
        staging_rows.append((idx, f"A-{idx:04d}", external_id, f"batch-{idx}", "duplicate"))
    staging_rows.extend(
        [
            (6, "ABC-0099", "EXT-1999", "batch-6", "rejected"),
            (7, "N/A", "EXT-2001", "batch-6", "rejected"),
            (8, "TX-12X", "EXT-2002", "batch-7", "new"),
            (9, "1001", duplicate_external_ids[0], "batch-7", "duplicate"),
            (10, "customer-13", "EXT-3001", "batch-8", "new"),
        ]
    )

    connection.executemany(
        "INSERT INTO accounts (acc_id, external_id_equip_map, account_status, created_date, region) VALUES (?, ?, ?, ?, ?)",
        accounts,
    )
    connection.executemany(
        "INSERT INTO customer_pii (acc_id, full_name, phone_number, address) VALUES (?, ?, ?, ?)",
        pii_rows,
    )
    connection.executemany(
        "INSERT INTO bill_invoice_detail (invoice_id, acc_id, invoice_date, amount, status) VALUES (?, ?, ?, ?, ?)",
        invoice_rows,
    )
    connection.executemany(
        "INSERT INTO transactions (txn_id, acc_id, txn_date, txn_type, amount) VALUES (?, ?, ?, ?, ?)",
        transaction_rows,
    )
    connection.executemany(
        "INSERT INTO staging_dirty_accounts (staging_id, acc_id, external_id_equip_map, source_batch, load_status) VALUES (?, ?, ?, ?, ?)",
        staging_rows,
    )
    connection.commit()

    return {
        "accounts": len(accounts),
        "customer_pii": len(pii_rows),
        "bill_invoice_detail": len(invoice_rows),
        "transactions": len(transaction_rows),
        "staging_dirty_accounts": len(staging_rows),
    }


def initialize_database(db_path: str | Path = DEFAULT_DB_PATH, *, seed: int = 42, overwrite: bool = True) -> dict[str, int]:
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and database_path.exists():
        database_path.unlink()

    with sqlite3.connect(database_path) as connection:
        create_schema(connection)
        return populate_data(connection, seed=seed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and seed the billing SQLite database.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to the SQLite database file.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed used for deterministic sample data.")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not delete an existing database file.")
    args = parser.parse_args()

    counts = initialize_database(args.db_path, seed=args.seed, overwrite=not args.no_overwrite)
    print(f"Seeded database at {args.db_path}")
    for table_name, count in counts.items():
        print(f"- {table_name}: {count} rows")


if __name__ == "__main__":
    main()
