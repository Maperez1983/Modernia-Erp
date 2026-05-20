import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FincasBudgetEditModalRegressionTests(unittest.TestCase):
    def test_fincas_budget_edit_opens_modal_not_engine(self):
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("openFincasBudgetEditModal(row);", app_js)
        self.assertIn('modal.id = "fincasBudgetEditModal"', app_js)


if __name__ == "__main__":
    unittest.main()

