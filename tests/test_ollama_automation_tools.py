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
from scripts import auto_quarantine_guard
from scripts import safe_auto_remediation
from scripts import render_env_sync
from scripts import prod_multi_crm_browser_smoke
from scripts import prod_system_matrix_audit
from scripts import system_business_reconciliation
from scripts import prod_process_smoke
from scripts import system_improvement_advisor
from scripts import run_system_audit
from scripts import build_system_knowledge
from scripts import system_autofix_agent
from scripts import frontend_home_access_audit
from scripts import system_supervisor
try:
    import PIL  # noqa: F401
except Exception:
    if "PIL" not in sys.modules:
        pil_stub = types.ModuleType("PIL")
        pil_stub.Image = object()
        pil_stub.ImageDraw = object()
        pil_stub.ImageEnhance = object()
        pil_stub.ImageFilter = object()
        pil_stub.ImageFont = object()
        pil_stub.ImageOps = object()
        sys.modules["PIL"] = pil_stub

from web.server import (
    _choose_ollama_model_name,
    _normalize_legal_llm_enrichment,
    build_legal_copilot_ollama_analysis,
    build_legal_radar_digest_prompt,
    copilot_web_answer,
    fetch_latest_system_audit_run,
    store_system_audit_run,
)


class OllamaAutomationToolsTests(unittest.TestCase):
    def test_choose_ollama_model_name_falls_back_to_available(self):
        old_fallback = os.environ.get("OLLAMA_FALLBACK_MODEL")
        try:
            os.environ["OLLAMA_FALLBACK_MODEL"] = "llama3.2:1b"
            chosen = _choose_ollama_model_name("qwen2.5-coder:7b", ["llama3.2:1b", "mistral:7b"])
            self.assertEqual(chosen, "llama3.2:1b")
        finally:
            if old_fallback is None:
                os.environ.pop("OLLAMA_FALLBACK_MODEL", None)
            else:
                os.environ["OLLAMA_FALLBACK_MODEL"] = old_fallback

    def test_legal_llm_enrichment_normalizes_topic_lists_and_confidence(self):
        enriched = _normalize_legal_llm_enrichment(
            "inmobiliaria",
            {"topic_key": "visitas", "impacto": "Medio", "summary": "base"},
            {
                "topic_key": "no_valido",
                "impacto": "alto",
                "summary": "Cambio operativo",
                "accion_recomendada": "Actualizar plantilla",
                "affected_documents": ["Contrato", "Contrato", "Hoja de visita"],
                "affected_workflows": "captacion;captacion;visitas",
                "affected_clauses": ["preaviso"],
                "llm_impact_summary": "Afecta al circuito comercial.",
                "llm_actions_json": "revisar checklist;actualizar dashboard",
                "llm_confidence": "1.3",
                "llm_review_needed": "true",
            },
        )

        self.assertEqual(enriched["topic_key"], "visitas")
        self.assertEqual(enriched["impacto"], "Alto")
        self.assertEqual(enriched["affected_documents"], ["Contrato", "Hoja de visita"])
        self.assertEqual(enriched["affected_workflows"], ["captacion", "visitas"])
        self.assertEqual(enriched["llm_actions_json"], ["revisar checklist", "actualizar dashboard"])
        self.assertEqual(enriched["llm_confidence"], 1.0)
        self.assertEqual(enriched["llm_review_needed"], 1)

    def test_legal_radar_digest_prompt_includes_llm_fields(self):
        prompt = build_legal_radar_digest_prompt(
            {
                "area": "rrhh",
                "estado": "pendiente",
                "rows": [
                    {
                        "titulo": "Nueva obligación",
                        "fecha_publicacion": "2026-06-17",
                        "fuente": "BOE",
                        "referencia": "BOE-A-2026-1",
                        "topic_key": "vacaciones_convenio",
                        "impacto": "Alto",
                        "url": "https://boe.es/test",
                        "resumen": "Resumen base",
                        "accion_recomendada": "Acción base",
                        "llm_impact_summary": "Impacto CRM",
                        "llm_actions_json": ["Actualizar export", "Revisar plantilla"],
                        "llm_confidence": 0.82,
                        "llm_review_needed": 1,
                        "library_text": "Texto legal",
                    }
                ],
            }
        )

        self.assertIn("Resumen LLM: Impacto CRM", prompt)
        self.assertIn("Acciones LLM: Actualizar export, Revisar plantilla", prompt)
        self.assertIn("Confianza LLM: 0.82", prompt)
        self.assertIn("Revisión manual LLM: sí", prompt)

    def test_copilot_web_answer_falls_back_to_ollama(self):
        import web.server as server

        old_fetch = server.copilot_web_fetch_url
        old_openai = server.openai_available
        old_ollama = server.ollama_available
        old_call_ollama = server.call_ollama
        try:
            server.copilot_web_fetch_url = lambda *_args, **_kwargs: {
                "ok": True,
                "url": "https://ejemplo.test",
                "title": "Norma",
                "text": "Contenido legal de prueba.",
                "fetched_at": "2026-06-17T00:00:00Z",
            }
            server.openai_available = lambda: False
            server.ollama_available = lambda: True
            server.call_ollama = lambda *args, **kwargs: ("Respuesta Ollama", "")

            result = copilot_web_answer("¿Qué cambia?", "https://ejemplo.test")
            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "ollama")
            self.assertEqual(result["answer"], "Respuesta Ollama")
        finally:
            server.copilot_web_fetch_url = old_fetch
            server.openai_available = old_openai
            server.ollama_available = old_ollama
            server.call_ollama = old_call_ollama

    def test_legal_copilot_ollama_analysis_falls_back_to_text(self):
        import web.server as server

        old_available = server.ollama_available
        old_json = server.call_ollama_json
        old_call = server.call_ollama
        try:
            server.ollama_available = lambda: True
            server.call_ollama_json = lambda *args, **kwargs: ({}, "json inválido")
            server.call_ollama = lambda *args, **kwargs: ("Revisar plantilla y flujo de firma.", "")
            analysis = build_legal_copilot_ollama_analysis(
                "inmobiliaria",
                "visitas",
                {"title": "Hoja de visita", "summary": "Base", "mandatory_docs": [], "workflow_checkpoints": [], "review_recommendations": [], "recent_updates": []},
                "¿Qué cambia?",
            )
            self.assertEqual(analysis["crm_impact"], "Revisar plantilla y flujo de firma.")
            self.assertTrue(analysis["review_needed"])
        finally:
            server.ollama_available = old_available
            server.call_ollama_json = old_json
            server.call_ollama = old_call

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
        old_policy = os.environ.get("CRM_AUDIT_IDENTITY_POLICY_PATH")
        try:
            os.environ.pop("CRM_AUDIT_SHARED_LOGIN_USERS", None)
            os.environ["CRM_AUDIT_IDENTITY_POLICY_PATH"] = str(Path("missing-policy.json"))
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
            if old_policy is None:
                os.environ.pop("CRM_AUDIT_IDENTITY_POLICY_PATH", None)
            else:
                os.environ["CRM_AUDIT_IDENTITY_POLICY_PATH"] = old_policy

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
        self.assertIn("process_catalog", memory)
        self.assertIn("business_rules", memory)
        self.assertIn("change_impact_map", memory)
        self.assertIn("canonical_scenarios", memory)
        self.assertIn("improvement_opportunities", memory)

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
        old_path = os.environ.get("RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH")
        try:
            with TemporaryDirectory() as tmp:
                cfg = Path(tmp) / "module_expectations.json"
                cfg.write_text(json.dumps({"defaults": {"min_rows_total": 1}, "by_user_module": {"admin:inmobiliaria": {"min_rows_total": 1}}}), encoding="utf-8")
                os.environ["RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH"] = str(cfg)
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
            if old_path is None:
                os.environ.pop("RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH", None)
            else:
                os.environ["RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH"] = old_path

    def test_module_smoke_warns_when_below_expectation(self):
        old_run = prod_module_smoke.prod_system_matrix_audit.run
        old_path = os.environ.get("RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH")
        try:
            with TemporaryDirectory() as tmp:
                cfg = Path(tmp) / "module_expectations.json"
                cfg.write_text(json.dumps({"defaults": {"min_rows_total": 10}}), encoding="utf-8")
                os.environ["RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH"] = str(cfg)
                prod_module_smoke.prod_system_matrix_audit.run = lambda: {
                    "endpoint_matrix": [
                        {"user_label": "admin", "module": "core", "endpoint": "workspace_health", "status": "passed", "rows": 1, "workspace_nombre": "Verifika²"},
                    ]
                }
                report = prod_module_smoke.run()
                self.assertEqual(report["status"], "passed_with_warnings")
        finally:
            prod_module_smoke.prod_system_matrix_audit.run = old_run
            if old_path is None:
                os.environ.pop("RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH", None)
            else:
                os.environ["RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH"] = old_path

    def test_module_smoke_skips_non_actionable_permission_warnings(self):
        old_run = prod_module_smoke.prod_system_matrix_audit.run
        try:
            prod_module_smoke.prod_system_matrix_audit.run = lambda: {
                "endpoint_matrix": [
                    {
                        "user_label": "non_admin",
                        "module": "fincas",
                        "endpoint": "fincas_comunidades",
                        "status": "warning",
                        "class": "expected_permission_denied",
                        "rows": 0,
                        "workspace_nombre": "Modernia",
                    }
                ]
            }
            report = prod_module_smoke.run()
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["results"][0]["status"], "skipped")
        finally:
            prod_module_smoke.prod_system_matrix_audit.run = old_run

    def test_auto_quarantine_guard_triggers_on_critical_alert(self):
        with TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps({"alerts": [{"type": "auth_drift", "title": "drift", "severity": "high"}]}), encoding="utf-8")
            old_update = auto_quarantine_guard._render_env_update
            try:
                auto_quarantine_guard._render_env_update = lambda api_key, service_id, pairs: {"ok": True, "pairs": pairs}
                os.environ["RENDER_API_KEY"] = "x"
                os.environ["RENDER_WEB_SERVICE_ID"] = "srv"
                result = auto_quarantine_guard.run(report_path)
                self.assertTrue(result["quarantined"])
                self.assertEqual(result["mode"], "quarantine")
            finally:
                auto_quarantine_guard._render_env_update = old_update

    def test_auto_quarantine_guard_uses_read_only_for_browser_smoke(self):
        decision = auto_quarantine_guard._quarantine_decision(
            {"alerts": [{"type": "browser_smoke", "title": "rrhh", "severity": "medium", "module": "rrhh"}]}
        )
        self.assertEqual(decision["mode"], "read_only")
        self.assertEqual(decision["scope"], "rrhh")

    def test_auto_quarantine_guard_does_not_global_quarantine_orphan_memberships(self):
        decision = auto_quarantine_guard._quarantine_decision(
            {
                "alerts": [
                    {
                        "type": "security_posture",
                        "id": "no-active-user-without-signal",
                        "title": "Usuarios activos sin membership",
                        "severity": "medium",
                    }
                ]
            }
        )
        self.assertEqual(decision["mode"], "read_only")
        self.assertEqual(decision["scope"], "workspace_admin")

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
                "steps": [
                    {"name": "production_api_monitor", "status": "passed", "duration_seconds": 1.2, "json_summary": {"kind": "prod_api_monitor", "failed_checks": []}},
                    {"name": "safe_auto_remediation", "status": "passed", "json_summary": {"kind": "safe_auto_remediation", "actions_total": 1, "actions": [{"id": "x"}]}},
                ],
            }
        )
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["alerts_total"], 1)
        self.assertEqual(payload["steps"][0]["name"], "production_api_monitor")
        self.assertEqual(payload["remediation"]["actions_total"], 1)

    def test_safe_auto_remediation_collects_auth_and_browser_actions(self):
        with TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "steps": [
                            {"json_summary": {"kind": "prod_auth_drift_audit", "checks": [{"name": "shared_password_login:foo", "status": "failed", "detail": "401"}]}},
                            {"json_summary": {"kind": "prod_multi_crm_browser_smoke", "results": [{"user_label": "admin", "module": "rrhh", "status": "failed", "route": "/?view=rrhh"}]}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = safe_auto_remediation.run(report_path)
            self.assertEqual(result["status"], "passed_with_actions")
            self.assertGreaterEqual(result["actions_total"], 2)

    def test_safe_auto_remediation_collects_business_and_process_actions(self):
        with TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "steps": [
                            {"json_summary": {"kind": "system_business_reconciliation", "results": [{"id": "seguros_dashboard_consistency", "module": "seguros", "status": "failed", "failed_subchecks": ["prima_total_non_negative"]}]}},
                            {"json_summary": {"kind": "prod_process_smoke", "results": [{"process_id": "gestoria_rentas_import", "module": "gestoria", "status": "failed", "reasons": ["business_reconciliation"]}]}}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = safe_auto_remediation.run(report_path)
            ids = {item["id"] for item in result["actions"]}
            self.assertIn("business-seguros_dashboard_consistency", ids)
            self.assertIn("process-gestoria_rentas_import", ids)

    def test_browser_smoke_route_for_workspace(self):
        route = prod_multi_crm_browser_smoke._route_for("verifika", "rrhh")
        self.assertIn("workspace=verifika", route)
        self.assertIn("view=rrhh", route)

    def test_system_supervisor_impacts_critical_processes(self):
        snapshot = system_supervisor.impacted_processes(["web/server.py", "scripts/gestoria_renta_import.py"])
        process_ids = {item["process"]["id"] for item in snapshot["processes"]}
        self.assertIn("gestoria_rentas_import", process_ids)
        self.assertIn("gestoria_facturas_accounting", process_ids)

    def test_system_supervisor_snapshot_counts_canonical_scenarios(self):
        snapshot = system_supervisor.build_snapshot()
        self.assertGreaterEqual(snapshot["canonical_scenarios_total"], 1)

    def test_system_supervisor_health_marks_module_alerts(self):
        report = {
            "alerts": [{"type": "browser_smoke", "title": "rrhh roto", "module": "rrhh"}],
            "failed_steps": [],
        }
        health = system_supervisor.process_health_from_report(report)
        rows = {item["process_id"]: item for item in health["processes"]}
        self.assertEqual(rows["rrhh_people_documents_time"]["status"], "warning")

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

    def test_render_env_sync_merges_without_dropping_existing(self):
        merged = render_env_sync._merge_env_vars(
            [{"key": "A", "value": "1"}, {"key": "B", "value": "2"}],
            {"B": "3", "C": "4"},
        )
        by_key = {item["key"]: item["value"] for item in merged}
        self.assertEqual(by_key, {"A": "1", "B": "3", "C": "4"})

    def test_render_env_sync_normalizes_render_api_shape(self):
        rows = render_env_sync._normalize_env_list(
            [
                {"envVar": {"key": "A", "value": "1"}, "cursor": "x"},
                {"envVar": {"key": "B", "previewValue": "2"}, "cursor": "y"},
            ]
        )
        self.assertEqual(rows, [{"key": "A", "value": "1"}, {"key": "B", "value": "2"}])

    def test_business_reconciliation_summary_is_compacted(self):
        summary = run_system_audit._summarize_json_output(
            json.dumps(
                {
                    "kind": "system_business_reconciliation",
                    "status": "failed",
                    "failed_checks": ["seguros_dashboard_consistency"],
                    "workspace": {"slug": "verifika"},
                    "results": [{"id": "seguros_dashboard_consistency", "status": "failed"}],
                }
            )
        )
        self.assertEqual(summary["kind"], "system_business_reconciliation")
        self.assertEqual(summary["failed_checks"], ["seguros_dashboard_consistency"])

    def test_process_smoke_summary_is_compacted(self):
        summary = run_system_audit._summarize_json_output(
            json.dumps(
                {
                    "kind": "prod_process_smoke",
                    "status": "failed",
                    "failed_checks": ["gestoria_rentas_import"],
                    "warnings": [],
                    "results": [{"process_id": "gestoria_rentas_import", "status": "failed"}],
                    "sources": {"module_smoke_status": "passed"},
                }
            )
        )
        self.assertEqual(summary["kind"], "prod_process_smoke")
        self.assertEqual(summary["failed_checks"], ["gestoria_rentas_import"])

    def test_business_reconciliation_alerts_are_high_signal(self):
        alerts = run_system_audit._build_alerts(
            {
                "steps": [
                    {
                        "name": "system_business_reconciliation",
                        "status": "failed",
                        "json_summary": {
                            "kind": "system_business_reconciliation",
                            "results": [{"module": "seguros", "status": "failed", "failed_subchecks": ["prima_total_non_negative"]}],
                        },
                    }
                ]
            }
        )
        self.assertTrue(any(item["type"] == "business_reconciliation" for item in alerts))

    def test_process_smoke_alerts_are_high_signal(self):
        alerts = run_system_audit._build_alerts(
            {
                "steps": [
                    {
                        "name": "production_process_smoke",
                        "status": "failed",
                        "json_summary": {
                            "kind": "prod_process_smoke",
                            "results": [{"process_id": "gestoria_rentas_import", "module": "gestoria", "status": "failed", "reasons": ["module_smoke"]}],
                        },
                    }
                ]
            }
        )
        self.assertTrue(any(item["type"] == "process_smoke" for item in alerts))

    def test_improvement_advisor_summary_is_compacted(self):
        summary = run_system_audit._summarize_json_output(
            json.dumps(
                {
                    "kind": "system_improvement_advisor",
                    "status": "passed",
                    "proposals_total": 2,
                    "appended_total": 1,
                    "proposals": [{"title": "X"}],
                }
            )
        )
        self.assertEqual(summary["kind"], "system_improvement_advisor")
        self.assertEqual(summary["proposals_total"], 2)

    def test_improvement_advisor_alert_is_low_signal(self):
        alerts = run_system_audit._build_alerts(
            {
                "steps": [
                    {
                        "name": "system_improvement_advisor",
                        "status": "passed",
                        "json_summary": {"kind": "system_improvement_advisor", "proposals_total": 3},
                    }
                ]
            }
        )
        self.assertTrue(any(item["type"] == "improvement_advisor" for item in alerts))

    def test_business_reconciliation_runner_flags_negative_prima(self):
        old_admin = system_business_reconciliation._admin_session
        old_workspace = system_business_reconciliation._pick_workspace
        old_get = system_business_reconciliation._get_json
        try:
            system_business_reconciliation._admin_session = lambda: ("session", {}, "")
            system_business_reconciliation._pick_workspace = lambda session: {"id": "w1", "slug": "verifika"}
            def fake_get(session, path):
                if path.startswith("/api/workspace_seguros_overview"):
                    return 200, {"counts": {"total": 5, "en_vigor": 3, "renovaciones_30d": 1, "prima_total": -10}}
                if path.startswith("/api/seguros_recibos_summary"):
                    return 200, {"summary": {"total": 2}}
                if path.startswith("/api/workspace_gestoria_overview"):
                    return 200, {"counts": {"rentas_pendientes_presentar": 2}}
                if path.startswith("/api/gestoria_dashboard"):
                    return 200, {"counts": {"rentas_total_ejercicio": 5, "rentas_pendientes_presentar": 2, "modelos_mes": 1}}
                if path.startswith("/api/gestoria_contabilidad"):
                    return 200, {"summary": {"ingresos": 10, "gastos": 4, "resultado": 6}, "total_rows": 1}
                if path.startswith("/api/workspace_fin_overview"):
                    return 200, {"counts": {"total": 2, "firmadas": 1, "comision_total": 10}}
                return 404, {}
            system_business_reconciliation._get_json = fake_get
            report = system_business_reconciliation.run()
            self.assertEqual(report["status"], "failed")
            self.assertIn("seguros_dashboard_consistency", report["failed_checks"])
        finally:
            system_business_reconciliation._admin_session = old_admin
            system_business_reconciliation._pick_workspace = old_workspace
            system_business_reconciliation._get_json = old_get

    def test_process_smoke_fails_when_business_reconciliation_fails(self):
        old_module = prod_process_smoke.prod_module_smoke.run
        old_browser = prod_process_smoke.prod_multi_crm_browser_smoke.run
        old_recon = prod_process_smoke.system_business_reconciliation.run
        try:
            prod_process_smoke.prod_module_smoke.run = lambda: {"status": "passed", "results": [{"module": "gestoria", "status": "passed"}]}
            prod_process_smoke.prod_multi_crm_browser_smoke.run = lambda: {"status": "passed", "results": [{"module": "gestoria", "status": "passed"}]}
            prod_process_smoke.system_business_reconciliation.run = lambda: {"status": "failed", "results": [{"id": "gestoria_rentas_import", "module": "gestoria", "status": "failed"}]}
            report = prod_process_smoke.run()
            self.assertEqual(report["status"], "failed")
            self.assertIn("gestoria_rentas_import", report["failed_checks"])
        finally:
            prod_process_smoke.prod_module_smoke.run = old_module
            prod_process_smoke.prod_multi_crm_browser_smoke.run = old_browser
            prod_process_smoke.system_business_reconciliation.run = old_recon

    def test_improvement_advisor_builds_proposals_from_repeated_modules(self):
        memory = system_supervisor.load_supervisor_memory()
        report = {
            "trend": {"module_alerts": {"repeated_modules": ["gestoria"]}},
            "steps": [],
        }
        proposals = system_improvement_advisor._build_proposals(report, memory, [], [], [])
        self.assertTrue(any("gestoria" in str(item.get("title") or "").lower() for item in proposals))

    def test_publish_payload_includes_improvements(self):
        payload = run_system_audit._build_publish_payload(
            {
                "run_id": "run-2",
                "status": "passed",
                "started_at": "2026-06-17T20:00:00Z",
                "finished_at": "2026-06-17T20:01:00Z",
                "alerts": [],
                "failed_steps": [],
                "trend": {},
                "steps": [
                    {"name": "system_improvement_advisor", "status": "passed", "json_summary": {"kind": "system_improvement_advisor", "proposals_total": 1, "proposals": [{"title": "Mejora"}]}}
                ],
            }
        )
        self.assertEqual(payload["improvements"]["proposals_total"], 1)


if __name__ == "__main__":
    unittest.main()
