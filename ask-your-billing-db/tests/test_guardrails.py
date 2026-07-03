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


if __name__ == "__main__":
    unittest.main()
