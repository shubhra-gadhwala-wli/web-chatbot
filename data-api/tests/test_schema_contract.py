"""Static contract tests runnable once Alembic/SQLAlchemy are installed.

Run: python -m unittest data-api/tests/test_schema_contract.py
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class SchemaContractTests(unittest.TestCase):
    def test_scope_constraints_and_safe_deletion_are_declared(self):
        migration = (ROOT / "alembic/versions/20260925_0001_initial_scoped_schema.py").read_text()
        for expected in (
            'ForeignKeyConstraint(["account_id", "document_id"]',
            'ForeignKeyConstraint(["account_id", "conversation_id"]',
            'ForeignKeyConstraint(["account_id", "chunk_id"]',
            'ondelete="CASCADE"',
            'ck_documents_status',
            'ck_documents_size',
        ):
            self.assertIn(expected, migration)

    def test_retrieval_contract_requires_filter_before_top_k_and_sqlite_recheck(self):
        contract = (ROOT / "repository-contract.md").read_text()
        self.assertIn("before** `limit`", contract)
        self.assertIn("rechecks SQLite", contract)
        self.assertIn("cross_account_denied", contract)

    def test_openapi_exposes_indistinguishable_foreign_id_404_and_pagination(self):
        spec = (ROOT / "openapi.yaml").read_text()
        self.assertIn("Missing or foreign resource (intentionally indistinguishable)", spec)
        self.assertIn("nextCursor", spec)
        self.assertIn("Idempotency-Key", spec)


if __name__ == "__main__":
    unittest.main()
