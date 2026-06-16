import unittest

from scripts import ollama_diff_review
from scripts import system_autofix_agent


class OllamaAutomationToolsTests(unittest.TestCase):
    def test_agenda_regression_outline_targets_agenda_tests(self):
        outline = system_autofix_agent._regression_outline(
            ["agenda", "usuarios_permisos"],
            "fallo en /api/acciones con cita y usuario no admin",
        )

        self.assertEqual(outline["target_file"], "tests/test_agenda_frontend_regressions.py")
        self.assertIn("admin y no admin", outline["goal"])
        self.assertIn("tests/test_api_usuarios_scoping.py", outline["commands"][0])

    def test_safe_test_paths_skips_e2e_by_default(self):
        paths = system_autofix_agent._safe_test_paths(
            [
                "tests/test_agenda_frontend_regressions.py",
                "tests/test_inmobiliaria_e2e_playwright.py",
                "../unsafe.py",
            ]
        )

        self.assertIn("tests/test_agenda_frontend_regressions.py", paths)
        self.assertNotIn("tests/test_inmobiliaria_e2e_playwright.py", paths)
        self.assertNotIn("../unsafe.py", paths)

    def test_diff_review_flags_sensitive_frontend_without_tests(self):
        review = ollama_diff_review._heuristic_review(
            ["web/app.js", "web/index.html"],
            {"modules": {}},
        )

        self.assertEqual(review["status"], "review_required")
        titles = {item["title"] for item in review["findings"]}
        self.assertIn("Cambio sin tests modificados", titles)
        self.assertIn("Zona sensible modificada", titles)
        self.assertIn("tests/test_frontend_smoke.py", review["recommended_tests"])


if __name__ == "__main__":
    unittest.main()
