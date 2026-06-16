import unittest
from unittest.mock import patch

from scripts import prod_api_monitor


class ProdApiMonitorTests(unittest.TestCase):
    @patch("scripts.prod_api_monitor._check_agenda")
    @patch("scripts.prod_api_monitor._check_workspaces")
    @patch("scripts.prod_api_monitor._login")
    @patch("scripts.prod_api_monitor._check_health")
    @patch("scripts.prod_api_monitor._user_specs")
    def test_admin_failure_becomes_warning_if_non_admin_path_passes(
        self,
        mock_user_specs,
        mock_health,
        mock_login,
        mock_workspaces,
        mock_agenda,
    ):
        mock_user_specs.return_value = [
            ("admin", "Mperez", "x"),
            ("non_admin", "Slallana", "y"),
        ]
        mock_health.return_value = prod_api_monitor.CheckResult("health", "passed")
        mock_login.side_effect = [
            (object(), {}, prod_api_monitor.CheckResult("login:Mperez", "failed", detail="401")),
            (object(), {"user": {"usuario": "Slallana"}}, prod_api_monitor.CheckResult("login:Slallana", "passed")),
        ]
        mock_workspaces.return_value = (
            {"id": "ws1", "nombre": "Verifika"},
            prod_api_monitor.CheckResult("workspaces:non_admin", "passed"),
        )
        mock_agenda.return_value = prod_api_monitor.CheckResult("agenda:non_admin", "passed", metrics={"rows": 3})

        report = prod_api_monitor.run()

        self.assertEqual(report["status"], "passed_with_warnings")
        self.assertEqual(report["warnings"], ["login:Mperez"])
        self.assertEqual(report["critical_failures"], [])


if __name__ == "__main__":
    unittest.main()
