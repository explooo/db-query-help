from __future__ import annotations

import unittest

from guardrails import classify_intent, validate_sql


class GuardrailTests(unittest.TestCase):
    def test_blocks_drop_table(self) -> None:
        verdict = validate_sql("DROP TABLE accounts")
        self.assertFalse(verdict.allowed)

    def test_blocks_pii_for_analyst(self) -> None:
        verdict = validate_sql("SELECT full_name, phone_number FROM customer_pii", role="analyst")
        self.assertFalse(verdict.allowed)

    def test_allows_pii_for_compliance_officer(self) -> None:
        verdict = validate_sql("SELECT full_name, phone_number FROM customer_pii", role="compliance_officer")
        self.assertTrue(verdict.allowed)

    def test_classifies_out_of_scope(self) -> None:
        self.assertEqual(classify_intent("What is the weather today?"), "out_of_scope")

    def test_blocks_insert_statement(self) -> None:
        verdict = validate_sql("INSERT INTO accounts (acc_id, account_status) VALUES (1, 'active')")
        self.assertFalse(verdict.allowed)

    def test_blocks_update_statement(self) -> None:
        verdict = validate_sql("UPDATE accounts SET account_status = 'closed' WHERE acc_id = 1")
        self.assertFalse(verdict.allowed)

    def test_blocks_multiple_statements(self) -> None:
        verdict = validate_sql("SELECT * FROM accounts; DELETE FROM accounts;")
        self.assertFalse(verdict.allowed)

    def test_blocks_sql_comments(self) -> None:
        verdict = validate_sql("SELECT * FROM accounts -- comment")
        self.assertFalse(verdict.allowed)

    def test_blocks_unknown_table(self) -> None:
        verdict = validate_sql("SELECT * FROM nonexistent_table")
        self.assertFalse(verdict.allowed)
        self.assertIn("Unknown table", verdict.reason)

    def test_allows_safe_select(self) -> None:
        verdict = validate_sql("SELECT acc_id, account_status FROM accounts WHERE region = 'north'")
        self.assertTrue(verdict.allowed)

    def test_classifies_read_query(self) -> None:
        self.assertEqual(classify_intent("Show me all invoices"), "read_query")

    def test_classifies_write_query(self) -> None:
        self.assertEqual(classify_intent("DELETE all old records"), "write_or_destructive")


if __name__ == "__main__":
    unittest.main()
