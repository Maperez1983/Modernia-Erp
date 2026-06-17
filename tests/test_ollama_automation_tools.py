import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import sys
import types

from scripts import ollama_diff_review
from scripts import ollama_json
from scripts import prod_auth_drift_audit
from scripts import prod_module_smoke
from scripts import prod_security_posture_audit
from scripts import prod_system_matrix_audit
from scripts import run_system_audit
from scripts import build_system_knowledge
from scripts import system_autofix_agent
from scripts import frontend_home_access_audit
if "PIL" not in sys.modules:
    pil_stub = types.ModuleType("PIL")
    pil_stub.Image = object()
    pil_stub.ImageDraw = object()
    pil_stub.ImageEnhance = object()
    pil_stub.ImageFilter = object()
    pil_stub.ImageFont = object()
    pil_stub.ImageOps = object()
    sys.modules["PIL"] = pil_stub

from web.server import fetch_latest_system_audit_run, store_system_audit_run


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

    def test_ollama_json_extracts_embedded_object(self):
        parsed = ollama_json.json_from_text("texto previo {\"status\":\"passed\",\"findings\":[]} texto final")
        self.assertEqual(parsed["status"], "passed")

    def test_matrix_classification_marks_expected_permission_as_non_actionable(self):
        result = prod_system_matrix_audit._classify_endpoint_result(
            {
                "status": "warning",
                "http_status": 403,
                "detail": "{'error': 'Sin permisos para este servicio'}",
            }
        )
        self.assertEqual(result["class"], "expected_permission_denied")
        self.assertFalse(result["action_required"])

    def test_matrix_classification_marks_server_error_as_actionable(self):
        result = prod_system_matrix_audit._classify_endpoint_result(
            {
                "status": "failed",
                "http_status": 500,
                "detail": "Traceback...",
            }
        )
        self.assertEqual(result["class"], "server_error")
        self.assertTrue(result["action_required"])

    def test_auth_drift_shared_user_fallbacks_to_non_admin(self):
        old_shared = os.environ.get("CRM_AUDIT_SHARED_LOGIN_USERS")
        old_inmo = os.environ.get("CRM_INMO_USER")
        try:
            os.environ.pop("CRM_AUDIT_SHARED_LOGIN_USERS", None)
            os.environ["CRM_INMO_USER"] = "SLallana"
            self.assertEqual(prod_auth_drift_audit._shared_login_users(), ["SLallana"])
        finally:
            if old_shared is None:
                os.environ.pop("CRM_AUDIT_SHARED_LOGIN_USERS", None)
            else:
                os.environ["CRM_AUDIT_SHARED_LOGIN_USERS"] = old_shared
            if old_inmo is None:
                os.environ.pop("CRM_INMO_USER", None)
            else:
                os.environ["CRM_INMO_USER"] = old_inmo

    def test_auth_drift_summary_is_compacted(self):
        summary = run_system_audit._summarize_json_output(
            json.dumps(
                {
                    "kind": "prod_auth_drift_audit",
                    "status": "failed",
                    "failed_checks": ["shared_password_login:foo"],
                    "warnings": ["no_membership:bar"],
                    "shared_policy": {"shared_login_users": ["foo"], "shared_password_configured": True},
                    "users": {"foo": {"login_with_shared_password": False}},
                    "checks": [{"name": "shared_password_login:foo", "status": "failed", "detail": "401"}],
                }
            )
        )
        self.assertEqual(summary["kind"], "prod_auth_drift_audit")
        self.assertEqual(summary["failed_checks"], ["shared_password_login:foo"])

    def test_auth_drift_alerts_are_high_signal(self):
        alerts = run_system_audit._build_alerts(
            {
                "steps": [
                    {
                        "name": "production_auth_drift",
                        "status": "failed",
                        "json_summary": {
                            "kind": "prod_auth_drift_audit",
                            "checks": [{"name": "shared_password_login:foo", "status": "failed", "detail": "401"}],
                        },
                    }
                ]
            }
        )
        self.assertTrue(any(item["type"] == "auth_drift" for item in alerts))

    def test_build_system_knowledge_includes_operational_memory(self):
        knowledge = build_system_knowledge.build_knowledge()
        memory = knowledge.get("operational_memory") or {}
        self.assertIn("expected_behaviors", memory)
        self.assertIn("recent_incidents", memory)
        self.assertIn("repair_playbooks", memory)
        self.assertIn("security_invariants", memory)

    def test_security_posture_reports_warning_for_missing_membership(self):
        old_run = prod_security_posture_audit.prod_auth_drift_audit.run
        try:
            prod_security_posture_audit.prod_auth_drift_audit.run = lambda: {
                "checks": [{"name": "backend_mode", "metrics": {"backend": "postgres"}}],
                "shared_policy": {"expected_backend": "postgres"},
                "users": {"foo": {"memberships": []}},
                "status": "passed_with_warnings",
            }
            report = prod_security_posture_audit.run()
            self.assertEqual(report["status"], "passed_with_warnings")
            self.assertIn("no-active-user-without-signal", report["warnings"])
        finally:
            prod_security_posture_audit.prod_auth_drift_audit.run = old_run

    def test_security_posture_summary_is_compacted(self):
        summary = run_system_audit._summarize_json_output(
            json.dumps(
                {
                    "kind": "prod_security_posture_audit",
                    "status": "failed",
                    "failed_checks": ["backend-postgres-production"],
                    "warnings": ["no-active-user-without-signal"],
                    "summary": {"critical": 1},
                    "findings": [{"id": "backend-postgres-production", "severity": "critical"}],
                    "auth_drift_status": "passed",
                }
            )
        )
        self.assertEqual(summary["kind"], "prod_security_posture_audit")
        self.assertEqual(summary["failed_checks"], ["backend-postgres-production"])

    def test_module_smoke_summary_is_compacted(self):
        summary = run_system_audit._summarize_json_output(
            json.dumps(
                {
                    "kind": "prod_module_smoke",
                    "status": "failed",
                    "failed_checks": ["admin:inmobiliaria"],
                    "warnings": [],
                    "results": [{"user_label": "admin", "module": "inmobiliaria", "status": "failed"}],
                }
            )
        )
        self.assertEqual(summary["kind"], "prod_module_smoke")
        self.assertEqual(summary["failed_checks"], ["admin:inmobiliaria"])

    def test_module_volume_drop_creates_alert(self):
        trend = {
            "repeated_failures": [],
            "new_failures": [],
            "recovered_failures": [],
            "consecutive_failed_runs": 0,
            "matrix": {
                "current": {"actionable_warnings_total": 0},
                "previous": {"actionable_warnings_total": 0},
                "module_row_drops": {"inmobiliaria": {"previous": 100, "current": 10, "ratio": 0.1}},
            },
            "module_alerts": {},
        }
        alerts = run_system_audit._build_trend_alerts({"status": "failed"}, trend)
        self.assertTrue(any(item["type"] == "module_volume_drop" for item in alerts))

    def test_user_module_volume_drop_creates_alert(self):
        trend = {
            "repeated_failures": [],
            "new_failures": [],
            "recovered_failures": [],
            "consecutive_failed_runs": 0,
            "matrix": {
                "current": {"actionable_warnings_total": 0},
                "previous": {"actionable_warnings_total": 0},
                "module_row_drops": {},
                "user_module_row_drops": {"non_admin:inmobiliaria": {"previous": 120, "current": 20, "ratio": 0.167, "threshold": 0.3}},
            },
            "module_alerts": {},
        }
        alerts = run_system_audit._build_trend_alerts({"status": "failed"}, trend)
        self.assertTrue(any(item["type"] == "user_module_volume_drop" for item in alerts))

    def test_module_smoke_aggregates_rows(self):
        old_run = prod_module_smoke.prod_system_matrix_audit.run
        try:
            prod_module_smoke.prod_system_matrix_audit.run = lambda: {
                "endpoint_matrix": [
                    {"user_label": "admin", "module": "inmobiliaria", "endpoint": "agenda_inmobiliaria", "status": "passed", "rows": 5, "workspace_nombre": "Verifika²"},
                    {"user_label": "admin", "module": "inmobiliaria", "endpoint": "inmuebles", "status": "passed", "rows": 2, "workspace_nombre": "Verifika²"},
                ]
            }
            report = prod_module_smoke.run()
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["results"][0]["rows_total"], 7)
        finally:
            prod_module_smoke.prod_system_matrix_audit.run = old_run

    def test_frontend_home_access_audit_passes_with_current_invariants(self):
        report = frontend_home_access_audit.run()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["actionable_warnings"], 0)

    def test_diff_text_uses_git_rev_range(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            old_root = ollama_diff_review.ROOT
            try:
                ollama_diff_review.ROOT = root
                code, _ = ollama_diff_review._run(["git", "init"], timeout=30)
                self.assertEqual(code, 0)
                ollama_diff_review._run(["git", "config", "user.email", "test@example.com"], timeout=30)
                ollama_diff_review._run(["git", "config", "user.name", "Test User"], timeout=30)
                ollama_diff_review._run(["git", "add", "tracked.txt"], timeout=30)
                ollama_diff_review._run(["git", "commit", "-m", "base"], timeout=30)
                (root / "tracked.txt").write_text("base\nchange\n", encoding="utf-8")
                files = ollama_diff_review._changed_files_for_rev_range("HEAD")
                diff = ollama_diff_review._diff_text(False, 5000, rev_range="HEAD")
                self.assertIn("tracked.txt", files)
                self.assertIn("+change", diff)
            finally:
                ollama_diff_review.ROOT = old_root

    def test_build_trend_alerts_detects_actionable_increase(self):
        trend = {
            "repeated_failures": [],
            "new_failures": [],
            "recovered_failures": [],
            "consecutive_failed_runs": 0,
            "matrix": {
                "current": {"actionable_warnings_total": 2},
                "previous": {"actionable_warnings_total": 0},
            },
        }
        alerts = run_system_audit._build_trend_alerts({"status": "failed"}, trend)
        self.assertEqual(alerts[0]["type"], "actionable_warning_increase")

    def test_load_history_reads_recent_entries(self):
        with TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "system-audit-history.jsonl"
            history_path.write_text(
                '{"run_id":"a","status":"passed"}\n{"run_id":"b","status":"failed"}\n',
                encoding="utf-8",
            )
            entries = run_system_audit._load_history(Path(tmp), limit=1)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["run_id"], "b")

    def test_materialize_regression_test_creates_missing_target(self):
        with TemporaryDirectory() as tmp:
            old_root = system_autofix_agent.ROOT
            try:
                root = Path(tmp)
                system_autofix_agent.ROOT = root
                output_dir = root / "out"
                plan = {
                    "regression_test_outline": {
                        "target_file": "tests/test_generated_regression.py",
                        "goal": "Goal",
                        "cases": ["Caso 1"],
                    }
                }
                result = system_autofix_agent._materialize_regression_test(plan, output_dir)
                self.assertTrue(result["created"])
                self.assertTrue((root / "tests/test_generated_regression.py").exists())
            finally:
                system_autofix_agent.ROOT = old_root

    def test_build_trend_data_tracks_module_alerts(self):
        report = {
            "status": "failed",
            "failed_steps": [],
            "steps": [
                {
                    "json_summary": {
                        "kind": "prod_system_matrix_audit",
                        "actionable_warnings": [{"module": "agenda"}],
                        "summary": {"actionable_warnings": 1},
                    }
                }
            ],
        }
        previous = [
            {
                "run_id": "prev",
                "status": "failed",
                "failed_steps": [],
                "steps": [
                    {
                        "json_summary": {
                            "kind": "prod_system_matrix_audit",
                            "actionable_warnings": [{"module": "agenda"}, {"module": "seguros"}],
                            "summary": {"actionable_warnings": 2},
                            "actionable_warnings_total": 2,
                        }
                    }
                ],
            }
        ]
        trend = run_system_audit._build_trend_data(report, previous)
        self.assertIn("agenda", trend["module_alerts"]["repeated_modules"])
        self.assertIn("seguros", trend["module_alerts"]["recovered_modules"])

    def test_publish_payload_compacts_report(self):
        payload = run_system_audit._build_publish_payload(
            {
                "run_id": "run-1",
                "status": "passed",
                "started_at": "2026-06-16T13:00:00Z",
                "finished_at": "2026-06-16T13:01:00Z",
                "alerts": [{"title": "x"}],
                "failed_steps": [],
                "trend": {},
                "steps": [{"name": "production_api_monitor", "status": "passed", "duration_seconds": 1.2, "json_summary": {"kind": "prod_api_monitor", "failed_checks": []}}],
            }
        )
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["alerts_total"], 1)
        self.assertEqual(payload["steps"][0]["name"], "production_api_monitor")

    def test_store_and_fetch_latest_system_audit_run(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ok = store_system_audit_run(
            conn,
            {
                "run_id": "audit-1",
                "status": "passed",
                "source": "render_cron",
                "started_at": "2026-06-16T13:00:00Z",
                "finished_at": "2026-06-16T13:01:00Z",
                "alerts_total": 2,
                "actionable_warnings_total": 1,
            },
            received_at="2026-06-16T13:01:05Z",
        )
        self.assertTrue(ok)
        latest = fetch_latest_system_audit_run(conn)
        self.assertEqual(latest["run_id"], "audit-1")
        self.assertEqual(latest["alerts_total"], 2)
        self.assertEqual(latest["actionable_warnings_total"], 1)


if __name__ == "__main__":
    unittest.main()
