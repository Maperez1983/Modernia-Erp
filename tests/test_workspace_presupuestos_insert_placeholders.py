import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkspacePresupuestosInsertPlaceholdersTests(unittest.TestCase):
    def test_insert_workspace_presupuestos_has_25_placeholders(self):
        """
        Regression: `/api/workspace_presupuestos` insert must pass the same number of
        params as SQL placeholders, otherwise SQLite raises:
        "the query has N placeholders but M parameters were passed".
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn(
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))",
            server_py,
        )


if __name__ == "__main__":
    unittest.main()

