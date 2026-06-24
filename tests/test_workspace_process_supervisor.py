import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from base64 import b64encode
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

try:
    import PIL  # noqa: F401
    from PIL import Image
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
    Image = None

import web.server as server


class WorkspaceProcessSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE workspace_empresas (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              empresa_id TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_process_supervisor (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT,
              servicio TEXT NOT NULL,
              process_type TEXT NOT NULL,
              entity_type TEXT,
              entity_id TEXT,
              actor_user_id TEXT,
              actor_label TEXT,
              status TEXT NOT NULL,
              severity TEXT NOT NULL DEFAULT 'warning',
              title TEXT NOT NULL,
              summary TEXT,
              anomaly_json TEXT,
              actions_json TEXT,
              llm_payload TEXT,
              dedupe_key TEXT,
              acknowledged INTEGER NOT NULL DEFAULT 0,
              acknowledged_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_process_supervisor_history (
              id TEXT PRIMARY KEY,
              event_id TEXT,
              workspace_id TEXT,
              empresa_id TEXT,
              servicio TEXT,
              process_type TEXT,
              entity_type TEXT,
              entity_id TEXT,
              actor_user_id TEXT,
              actor_label TEXT,
              status TEXT,
              severity TEXT,
              title TEXT,
              summary TEXT,
              anomaly_json TEXT,
              actions_json TEXT,
              llm_payload TEXT,
              created_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              nif TEXT,
              email TEXT,
              telefono TEXT,
              direccion TEXT,
              fecha_nacimiento TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE clientes_empresas (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              empresa_id TEXT,
              servicio TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE cliente_gestoria (
              id TEXT,
              cliente_id TEXT PRIMARY KEY,
              tipo_cliente TEXT,
              mod_fiscal INTEGER,
              mod_laboral INTEGER,
              mod_contable INTEGER,
              mod_renta INTEGER,
              mod_registro INTEGER,
              mod_trafico INTEGER,
              mod_puntuales INTEGER,
              renta_detalles TEXT
              ,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE gestoria_docs (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              referencia_tipo TEXT,
              referencia_id TEXT,
              nombre TEXT,
              tipo TEXT,
              fecha TEXT,
              estado TEXT,
              notas TEXT,
              doc_key TEXT,
              doc_url TEXT,
              archivo_hash TEXT,
              ejercicio_fiscal TEXT,
              tipo_documento TEXT,
              estado_revision TEXT,
              duplicate_of TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              mes_creacion TEXT,
              fecha_efecto TEXT,
              fecha_vencimiento TEXT,
              tomador TEXT,
              compania TEXT,
              ramo TEXT,
              poliza_numero TEXT,
              prima_neta REAL,
              prima_total REAL,
              comision REAL,
              produccion REAL,
              colaborador TEXT,
              estado TEXT,
              estado_renovacion TEXT,
              renovacion_fecha TEXT,
              nueva_poliza_ref TEXT,
              poliza_key TEXT,
              poliza_url TEXT,
              estado_poliza TEXT,
              version_grupo TEXT,
              tipo_vigencia TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE acciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              servicio TEXT,
              cliente_id TEXT,
              inmueble_id TEXT,
              cliente_nombre TEXT,
              fecha TEXT,
              hora TEXT,
              tipo TEXT,
              responsable TEXT,
              estado TEXT,
              notas TEXT,
              recordatorio_min INTEGER,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE gestoria_contabilidad (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente_ids_json TEXT,
              seguro_id TEXT,
              hipoteca_id TEXT,
              poliza_numero TEXT,
              fecha TEXT,
              concepto TEXT,
              gestion TEXT,
              tipo TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE gestoria_facturas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tercero_id TEXT,
              tipo TEXT,
              numero TEXT,
              fecha_emision TEXT,
              descripcion TEXT,
              base_imponible REAL,
              cuota_iva REAL,
              cuota_irpf REAL,
              total REAL,
              iva_pct REAL,
              estado_ocr TEXT,
              doc_key TEXT,
              raw_text TEXT,
              archivo_hash TEXT,
              dedupe_key TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE gestoria_asientos (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              factura_id TEXT,
              fecha TEXT,
              concepto TEXT,
              diario TEXT,
              referencia TEXT,
              total_debe REAL,
              total_haber REAL,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_fincas_comunidades (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              empresa_id TEXT,
              nombre TEXT,
              referencia_catastral TEXT,
              cif TEXT,
              direccion TEXT,
              foto_edificio_key TEXT,
              presidente TEXT,
              secretario TEXT,
              estado TEXT,
              num_vecinos INTEGER,
              num_locales INTEGER,
              num_trasteros INTEGER,
              num_aparcamientos INTEGER,
              cuota_sugerida REAL,
              cuota_mensual REAL,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_registro_personal (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              nombre TEXT,
              email TEXT,
              empresa_nombre TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_fincas_contabilidad (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              comunidad_id TEXT,
              fecha TEXT,
              estado TEXT,
              tipo TEXT,
              concepto TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_rrhh_documentos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              empresa_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              nombre TEXT,
              doc_key TEXT,
              doc_url TEXT,
              fecha_emision TEXT,
              fecha_caducidad TEXT,
              permanente INTEGER,
              estado TEXT,
              notas TEXT,
              nomina_ocr_status TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_rrhh_ausencias (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              empresa_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              fecha_inicio TEXT,
              fecha_fin TEXT,
              estado TEXT,
              motivo TEXT,
              comentario TEXT,
              aprobado_por TEXT,
              aprobado_at TEXT,
              rechazado_at TEXT,
              cancelado_at TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_rrhh_gastos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              empresa_id TEXT,
              persona_id TEXT,
              fecha TEXT,
              categoria TEXT,
              proveedor TEXT,
              concepto TEXT,
              importe REAL,
              estado TEXT,
              doc_key TEXT,
              doc_url TEXT,
              notas TEXT,
              aprobado_por TEXT,
              aprobado_at TEXT,
              rechazado_at TEXT,
              pagado_at TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_fincas_incidencias (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              comunidad_id TEXT,
              titulo TEXT,
              descripcion TEXT,
              prioridad TEXT,
              estado TEXT,
              proveedor TEXT,
              proveedor_id TEXT,
              responsable TEXT,
              fecha_apertura TEXT,
              fecha_cierre TEXT,
              coste_estimado REAL,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_fincas_proveedores (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              comunidad_id TEXT,
              empresa_id TEXT,
              nombre TEXT,
              tipo_servicio TEXT,
              telefono TEXT,
              email TEXT,
              estado TEXT,
              tarifa_mensual REAL,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE workspace_fincas_juntas (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              comunidad_id TEXT,
              fecha TEXT,
              tipo TEXT,
              estado TEXT,
              orden_dia TEXT,
              acuerdos TEXT,
              proxima_fecha TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE seguros_recibos (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              seguro_id TEXT,
              cliente_id TEXT,
              referencia TEXT,
              poliza_numero TEXT,
              compania TEXT,
              ramo TEXT,
              fecha_emision TEXT,
              fecha_vencimiento TEXT,
              fecha_cobro TEXT,
              estado TEXT,
              prima_total REAL,
              comision REAL,
              comision_pct REAL,
              importe_liquidacion REAL,
              notas TEXT,
              doc_key TEXT,
              doc_url TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE seguros_siniestros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              seguro_id TEXT,
              cliente_id TEXT,
              numero_expediente TEXT,
              compania TEXT,
              ramo TEXT,
              fecha_siniestro TEXT,
              fecha_apertura TEXT,
              fecha_cierre TEXT,
              estado TEXT,
              tipo TEXT,
              descripcion TEXT,
              importe_reserva REAL,
              importe_pagado REAL,
              gestor TEXT,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_renta_supervisor_persists_warning_and_acknowledges_it(self):
        self.conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('we1', 'ws1', 'e1', 'now', 'now')"
        )
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email) VALUES ('c1', 'Cliente Uno', '12345678A', 'uno@test.local')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email) VALUES ('c2', 'Cliente Duplicado', '12345678A', 'otro@test.local')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce1', 'c1', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce2', 'c2', 'e1', 'gestoria')")
        renta_payload = {
            "entries": [
                {
                    "id": "entry1",
                    "ejercicio": "2025",
                    "estado_presentacion": "Presentada",
                }
            ]
        }
        self.conn.execute(
            "INSERT INTO cliente_gestoria (cliente_id, mod_renta, renta_detalles) VALUES (?, ?, ?)",
            ("c1", 0, json.dumps(renta_payload, ensure_ascii=False)),
        )
        old_ollama_available = server.ollama_available
        try:
            server.ollama_available = lambda: False
            result = server.run_workspace_process_supervision(
                self.conn,
                process_type="renta_attach",
                servicio="gestoria",
                empresa_id="e1",
                workspace_id="ws1",
                entity_type="cliente",
                entity_id="c1",
                context={"ejercicio": "2025"},
                now="2026-06-18T10:00:00Z",
            )
        finally:
            server.ollama_available = old_ollama_available
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any(item["code"] == "renta_document_missing" for item in result["anomalies"]))
        self.assertTrue(any(item["code"] == "duplicate_client_nif" for item in result["anomalies"]))
        feed = server.fetch_workspace_process_supervisor_events(self.conn, "ws1", limit=10, only_open=True)
        self.assertEqual(len(feed["rows"]), 1)
        self.assertIn("priority", feed["rows"][0])
        self.assertIn("action_items", feed["rows"][0])
        history = server.fetch_workspace_process_supervisor_history(self.conn, "ws1", limit=10)
        self.assertEqual(len(history["rows"]), 1)
        self.assertTrue(server.acknowledge_workspace_process_supervisor_event(self.conn, "ws1", feed["rows"][0]["id"], actor="QA"))
        feed_after = server.fetch_workspace_process_supervisor_events(self.conn, "ws1", limit=10, only_open=True)
        self.assertEqual(feed_after["rows"], [])

    def test_infer_workspace_id_from_empresa_uses_workspace_empresas(self):
        self.conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('we2', 'ws-demo', 'empresa-demo', 'now', 'now')"
        )
        self.assertEqual(server.infer_workspace_id_from_empresa(self.conn, "empresa-demo"), "ws-demo")

    def test_accounting_supervisor_detects_possible_duplicate(self):
        self.conn.execute(
            "INSERT INTO gestoria_contabilidad (id, empresa_id, cliente_id, fecha, concepto, tipo, importe, created_at, updated_at) VALUES ('g1', 'e1', 'c1', '2026-06-18', 'Factura proveedor', 'gasto', 120.0, 'now', 'now')"
        )
        self.conn.execute(
            "INSERT INTO gestoria_contabilidad (id, empresa_id, cliente_id, fecha, concepto, tipo, importe, created_at, updated_at) VALUES ('g2', 'e1', 'c1', '2026-06-18', 'Factura proveedor', 'gasto', 120.0, 'now', 'now')"
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="gestoria_accounting",
            servicio="gestoria",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="gestoria_contabilidad",
            entity_id="g2",
            context={},
            now="2026-06-18T10:10:00Z",
        )
        self.assertEqual(result["status"], "ok_with_warnings")
        self.assertTrue(any(item["code"] == "accounting_possible_duplicate" for item in result["anomalies"]))

    def test_fincas_supervisor_flags_missing_fee(self):
        self.conn.execute(
            """
            INSERT INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, cif, direccion, estado,
              num_vecinos, num_locales, num_trasteros, num_aparcamientos,
              cuota_sugerida, cuota_mensual, created_at, updated_at
            ) VALUES (
              'fc1', 'ws1', 'e1', 'Comunidad Sol', '', '', 'Activa',
              10, 2, 1, 4, 0, 0, 'now', 'now'
            )
            """
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="fincas_community",
            servicio="fincas",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="fincas_comunidad",
            entity_id="fc1",
            context={},
            now="2026-06-18T10:20:00Z",
        )
        self.assertTrue(any(item["code"] == "fincas_monthly_fee_missing" for item in result["anomalies"]))

    def test_rrhh_gasto_supervisor_flags_missing_receipt(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_gastos (
              id, workspace_id, empresa_id, persona_id, fecha, categoria, concepto, importe, estado, doc_key, doc_url, created_at, updated_at
            ) VALUES (
              'gasto1', 'ws1', 'e1', 'p1', '2026-06-18', 'Dieta', 'Taxi aeropuerto', 34.5, 'Pendiente', '', '', 'now', 'now'
            )
            """
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="rrhh_gasto",
            servicio="rrhh",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="rrhh_gasto",
            entity_id="gasto1",
            context={},
            now="2026-06-18T10:30:00Z",
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any(item["code"] == "rrhh_gasto_attachment_missing" for item in result["anomalies"]))

    def test_seguro_recibo_supervisor_flags_missing_linked_entities(self):
        self.conn.execute(
            """
            INSERT INTO seguros_recibos (
              id, empresa_id, seguro_id, cliente_id, referencia, fecha_emision, estado, created_at, updated_at
            ) VALUES (
              'rec1', 'e1', '', '', 'REC-001', '2026-06-18', 'pendiente', 'now', 'now'
            )
            """
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="seguro_recibo",
            servicio="seguros",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="seguros_recibo",
            entity_id="rec1",
            context={},
            now="2026-06-18T10:40:00Z",
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any(item["code"] == "seguro_receipt_without_cliente" for item in result["anomalies"]))

    def test_fincas_provider_supervisor_flags_missing_contact_data(self):
        self.conn.execute(
            """
            INSERT INTO workspace_fincas_proveedores (
              id, workspace_id, comunidad_id, empresa_id, nombre, estado, tarifa_mensual, telefono, email, created_at, updated_at
            ) VALUES (
              'prov1', 'ws1', 'com1', 'e1', 'Proveedor Limpieza', 'Activo', 0, '', '', 'now', 'now'
            )
            """
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="fincas_provider",
            servicio="fincas",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="fincas_proveedor",
            entity_id="prov1",
            context={},
            now="2026-06-18T10:50:00Z",
        )
        self.assertEqual(result["status"], "ok_with_warnings")
        self.assertTrue(any(item["code"] == "fincas_provider_contact_missing" for item in result["anomalies"]))

    def test_gestoria_factura_supervisor_flags_missing_doc_and_entry(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, total, doc_key, created_at, updated_at
            ) VALUES (
              'fac1', 'e1', 'c1', 'compra', 'F-001', '2026-06-18', 250.0, '', 'now', 'now'
            )
            """
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="gestoria_factura",
            servicio="gestoria",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="gestoria_factura",
            entity_id="fac1",
            context={},
            now="2026-06-18T11:00:00Z",
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any(item["code"] == "gestoria_invoice_document_missing" for item in result["anomalies"]))
        self.assertTrue(any(item["code"] == "gestoria_invoice_entry_missing" for item in result["anomalies"]))

    def test_fincas_contabilidad_supervisor_flags_missing_community(self):
        self.conn.execute(
            """
            INSERT INTO workspace_fincas_contabilidad (
              id, workspace_id, comunidad_id, fecha, estado, tipo, concepto, importe, created_at, updated_at
            ) VALUES (
              'fcm1', 'ws1', '', '2026-06-18', 'Manual', 'Gasto', 'Reparación portal', 120.0, 'now', 'now'
            )
            """
        )
        result = server.run_workspace_process_supervision(
            self.conn,
            process_type="fincas_contabilidad",
            servicio="fincas",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="fincas_contabilidad",
            entity_id="fcm1",
            context={},
            now="2026-06-18T11:10:00Z",
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any(item["code"] == "fincas_accounting_community_missing" for item in result["anomalies"]))

    def test_process_action_returns_dashboard_route(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt1', 'ws1', 'e1', 'gestoria', 'gestoria_dashboard', 'gestoria_dashboard', 'ws1', '',
              '', 'ok_with_warnings', 'warning', 'Dashboard', 'Resumen', '[]', '[]', '{}',
              'd1', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt1",
            "reload_dashboard",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T11:20:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertIn("/api/gestoria_dashboard", result["route"])

    def test_internal_copilot_incident_uses_open_events(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, descripcion, total, estado_ocr, doc_key, created_at, updated_at
            ) VALUES (
              's1', 'e1', 'c1', 'emitida', 'F-2026-001', 'Factura duplicada', 121.5, 'warning', 'docs/f1.pdf', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt2', 'ws1', 'e1', 'gestoria', 'gestoria_factura', 'gestoria_factura', 's1', '',
              '', 'incomplete', 'warning', 'Factura incompleta', 'Falta asiento contable', '[]', '[]', '{}',
              'd2', 0, NULL, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "por qué no se creó bien la factura",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "incident")
        self.assertIn("Factura incompleta", reply["answer"])
        self.assertTrue(reply["cards"])
        self.assertEqual(reply["cards"][0]["entity"]["cliente_id"], "c1")
        self.assertEqual(reply["cards"][0]["event_id"], "evt2")

    def test_internal_copilot_tutorial_uses_process_catalog(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "como cargo una renta",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "tutorial")
        self.assertTrue(reply["cards"])

    def test_internal_copilot_platform_reply_exposes_blueprint(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "quiero ver la arquitectura de la inteligencia verifika2",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria", "copilot_mode": "operator"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "platform_blueprint")
        self.assertTrue(any(str(card.get("title") or "") == "Verifika2 Intelligence Layer" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "copilot_work_center" for action in (reply.get("actions") or [])))

    def test_internal_copilot_action_work_center_returns_domain_tooling(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c1', 'Juan Cliente', '12345678Z', 'juan@test.local', 'now', 'now')")
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "copilot_work_center",
            {"current_crm": "gestoria", "copilot_mode": "operator", "current_client_id": "c1"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T11:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("action_id"), "copilot_work_center")
        self.assertTrue(any(str(card.get("title") or "") == "Herramientas disponibles" for card in (result.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Contexto visible" for card in (result.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Entidad actual" for card in (result.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "diagnose_current_entity" for action in (result.get("actions") or [])))

    def test_internal_copilot_action_diagnose_current_entity_uses_open_client_context(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('cdiag1', 'Cliente Visible', '55555555L', 'visible@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload, dedupe_key,
              acknowledged, created_at, updated_at
            ) VALUES (
              'wps-visible-1', 'ws1', 'e1', 'gestoria', 'renta_attach', 'cliente', 'cdiag1', 'u1',
              'QA', 'open', 'warning', 'Renta pendiente', 'Hay que revisar la renta del cliente visible',
              '[]', '[]', '{}', 'dup-visible-1', 0, '2026-06-21T09:00:00Z', '2026-06-21T09:00:00Z'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "diagnose_current_entity",
            {"current_crm": "gestoria", "current_client_id": "cdiag1"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T11:10:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertIn("ficha actual", str(result.get("message") or "").lower())
        self.assertTrue(any(str(card.get("title") or "") == "Entidad actual" for card in (result.get("cards") or [])))
        self.assertTrue(any("Renta pendiente" == str(card.get("title") or "") for card in (result.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "revalidate_current_entity" for action in (result.get("actions") or [])))

    def test_internal_copilot_run_operator_sequence_prioritizes_current_entity(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('cop-entity-1', 'Cliente Prioritario', '88888888T', 'prio@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload, dedupe_key,
              acknowledged, created_at, updated_at
            ) VALUES (
              'wps-priority-1', 'ws1', 'e1', 'gestoria', 'renta_attach', 'cliente', 'cop-entity-1', 'u1',
              'QA', 'open', 'warning', 'Cliente prioritario', 'Hay una renta pendiente ligada a la ficha visible',
              '[]', '[]', '{}', 'dup-priority-1', 0, '2026-06-21T09:30:00Z', '2026-06-21T09:30:00Z'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_operator_sequence",
            {"crm": "gestoria", "current_crm": "gestoria", "current_client_id": "cop-entity-1", "copilot_mode": "operator"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T11:20:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "operator")
        self.assertEqual(result.get("decision_source"), "current_entity_priority")
        self.assertIn("He priorizado la ficha actual", str(result.get("message") or ""))
        self.assertTrue(any(str(card.get("title") or "") == "Plan operativo elegido" for card in (result.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_operator_sequence" for action in (result.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") in {"revalidate_current_entity", "run_current_entity_microflow"} for action in (result.get("actions") or [])))

    def test_internal_copilot_action_run_current_entity_microflow(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-entity-1', 'e1', 'Cliente Hipoteca', 'c1', 'BBVA', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload, dedupe_key,
              acknowledged, created_at, updated_at
            ) VALUES (
              'wps-entity-micro-1', 'ws1', 'e1', 'financiaciones', 'hipoteca_update', 'hipoteca', 'hip-entity-1', 'u1',
              'QA', 'open', 'warning', 'Hipoteca incompleta', 'Faltan importes base en la ficha visible',
              '[]', '[]', '{}', 'dup-entity-micro-1', 0, '2026-06-21T09:00:00Z', '2026-06-21T09:00:00Z'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_current_entity_microflow",
            {"current_crm": "fin", "crm": "fin", "current_hipoteca_id": "hip-entity-1", "copilot_mode": "operator"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T11:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("action_id"), "run_current_entity_microflow")
        self.assertTrue(any(str(action.get("id") or "") == "run_operator_sequence" for action in (result.get("actions") or [])))
        self.assertTrue(result.get("microflow_type"))
        self.assertIn("microflujo de la ficha actual", str(result.get("message") or "").lower())

    def test_supervisor_action_rerun_ocr_for_rrhh_document_returns_endpoint(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, nomina_ocr_status, created_at, updated_at
            ) VALUES (
              'doc1', 'ws1', 'e1', 'p1', 'Nómina', 'Nomina mayo.pdf', 'rrhh/doc1.pdf', 'error', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt3', 'ws1', 'e1', 'rrhh', 'rrhh_document', 'rrhh_documento', 'doc1', '',
              '', 'incomplete', 'warning', 'Nómina OCR pendiente', 'El OCR de la nómina falló', '[]', '[]', '{}',
              'd3', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt3",
            "rerun_ocr",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T11:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["post_endpoint"], "/api/workspace_rrhh_nomina_ocr")
        self.assertEqual(result["payload"]["id"], "doc1")

    def test_supervisor_open_record_returns_cliente_navigation_when_available(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, descripcion, total, estado_ocr, doc_key, created_at, updated_at
            ) VALUES (
              'gf1', 'e1', 'c1', 'emitida', 'F-2026-002', 'Factura test', 99.95, 'ok', 'docs/f2.pdf', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt4', 'ws1', 'e1', 'gestoria', 'gestoria_factura', 'gestoria_factura', 'gf1', '',
              '', 'incomplete', 'warning', 'Factura sin asiento', 'Falta asiento contable', '[]', '[]', '{}',
              'd4', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt4",
            "open_record",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T11:40:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "cliente")
        self.assertEqual(result["navigation"]["cliente_id"], "c1")

    def test_supervisor_reload_dashboard_block_maps_gestoria_documents(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt5', 'ws1', 'e1', 'gestoria', 'gestoria_dashboard', 'gestoria_dashboard', 'ws1', '',
              '', 'failed', 'warning', 'Dashboard gestoría incoherente', 'Docs descuadrados', '[{\"code\":\"gestoria_dashboard_docs_mismatch\"}]', '[]', '{}',
              'd5', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt5",
            "reload_dashboard_block",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T11:50:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["dashboard"], "gestoria")
        self.assertEqual(result["dashboard_block"], "documentos")

    def test_supervisor_reload_records_maps_rrhh_docs_endpoint(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt6', 'ws1', 'e1', 'rrhh', 'rrhh_document', 'rrhh_documento', 'doc1', '',
              '', 'warning', 'warning', 'Documento RRHH pendiente', 'Falta validación', '[]', '[]', '{}',
              'd6', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt6",
            "reload_records",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T12:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertIn("/api/workspace_rrhh_documentos", result["route"])
        self.assertEqual(result["refresh_target"], "rrhh_docs")

    def test_seguro_open_record_returns_cliente_navigation(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seguros (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              poliza_numero TEXT,
              compania TEXT,
              ramo TEXT,
              estado TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO seguros (id, cliente_id, poliza_numero, compania, ramo, estado)
            VALUES ('seg1', 'c1', 'POL-1', 'Zurich', 'Hogar', 'Activa')
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt7', 'ws1', 'e1', 'seguros', 'seguro_update', 'seguro', 'seg1', '',
              '', 'warning', 'warning', 'Póliza incompleta', 'Falta vínculo', '[]', '[]', '{}',
              'd7', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt7",
            "open_record",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T12:05:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "cliente")
        self.assertEqual(result["navigation"]["cliente_id"], "c1")

    def test_refresh_client_summary_returns_cliente_navigation(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, descripcion, total, estado_ocr, doc_key, created_at, updated_at
            ) VALUES (
              'gf2', 'e1', 'c1', 'emitida', 'F-2026-003', 'Factura refresh', 80.0, 'ok', 'docs/f3.pdf', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt8', 'ws1', 'e1', 'gestoria', 'gestoria_factura', 'gestoria_factura', 'gf2', '',
              '', 'warning', 'warning', 'Factura a revisar', 'Falta asiento', '[]', '[]', '{}',
              'd8', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            "evt8",
            "refresh_client_summary",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T12:10:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "cliente")
        self.assertEqual(result["navigation"]["cliente_id"], "c1")

    def test_revalidate_process_resolves_rrhh_document_after_data_fix(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, doc_url, nomina_ocr_status, created_at, updated_at
            ) VALUES (
              'doc2', 'ws1', 'e1', 'p1', 'Contrato', 'Contrato.pdf', '', '', 'ok', 'now', 'now'
            )
            """
        )
        first = server.run_workspace_process_supervision(
            self.conn,
            process_type="rrhh_document",
            servicio="rrhh",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="rrhh_documento",
            entity_id="doc2",
            actor={"user_id": "u1", "usuario": "QA"},
            context={"operation": "create"},
            now="2026-06-18T12:12:00Z",
        )
        self.assertNotEqual(first["status"], "ok")
        self.conn.execute(
            """
            UPDATE workspace_rrhh_documentos
            SET doc_key = 'rrhh/ok.pdf', updated_at = 'later'
            WHERE id = 'doc2'
            """
        )
        result = server.perform_workspace_process_supervisor_action(
            self.conn,
            "ws1",
            str(first.get("event_id") or ""),
            "revalidate_process",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T12:13:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["resolved"])
        self.assertEqual(result["process_supervision"]["status"], "ok")

    def test_internal_copilot_review_reply_filters_today_rentas(self):
        today = "2026-06-18T12:20:00Z"
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt9', 'ws1', 'e1', 'gestoria', 'renta_attach', 'renta_attach', 'c1', '',
              '', 'warning', 'warning', 'Renta incompleta', 'Falta documento', '[]', '[]', '{}',
              'd9', 0, NULL, ?, ?
            )
            """,
            (today, today),
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "revisa todas las rentas de hoy",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "incident")
        self.assertIn("He encontrado 1 incidencia", reply["answer"])
        self.assertTrue(reply["cards"])

    def test_internal_copilot_duplicate_review_promotes_concrete_fix(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email) VALUES ('c10', 'Cliente Uno', '12345678A', 'uno@test.local')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email) VALUES ('c11', 'Cliente Dos', '12345678A', 'dos@test.local')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce10', 'c10', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce11', 'c11', 'e1', 'gestoria')")
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt10', 'ws1', 'e1', 'gestoria', 'renta_attach', 'renta_attach', 'c10', '',
              '', 'warning', 'warning', 'Renta duplicada', 'Posible duplicado de cliente',
              '[{\"code\":\"duplicate_client_nif\",\"related_rows\":[{\"id\":\"c11\",\"nombre\":\"Cliente Dos\",\"nif\":\"12345678A\"}]}]', '[]', '{}',
              'd10', 0, NULL, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué clientes están duplicados",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["cards"])
        self.assertEqual(reply["cards"][0]["title"], "Posible corrección de duplicado")

    def test_internal_copilot_uses_current_client_context(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email) VALUES ('c20', 'Cliente Contexto', '11111111A', 'ctx@test.local')")
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué le falta a este cliente",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
            context={"current_client_id": "c20"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("Cliente Contexto", reply["answer"])
        self.assertTrue(reply["cards"])

    def test_internal_copilot_uses_current_community_context(self):
        self.conn.execute(
            """
            INSERT INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, direccion, estado, cuota_mensual, created_at, updated_at
            ) VALUES (
              'com1', 'ws1', 'e1', 'Comunidad Centro', 'Calle Mayor 1', 'Activa', 120.0, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué pasa con esta comunidad",
            empresa_id="e1",
            service_hint="fincas",
            actor={"user_id": "u1", "usuario": "QA"},
            context={"current_community_id": "com1"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("Comunidad Centro", reply["answer"])
        self.assertTrue(reply["cards"])

    def test_internal_copilot_builds_open_client_action(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c30', 'Juan Perez', '22222222B', 'juan@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce30', 'c30', 'e1', 'gestoria')")
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "ábreme la ficha del cliente Juan Perez",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertTrue(reply["actions"])
        self.assertEqual(reply["actions"][0]["id"], "open_client")

    def test_internal_copilot_action_updates_client_basic_fields(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, telefono, created_at, updated_at) VALUES ('c31', 'Maria Lopez', '33333333C', '', '', 'now', 'now')")
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_client_basic",
            {"cliente_id": "c31", "patch": {"email": "maria@test.local", "telefono": "+34600111222"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T12:00:00Z",
        )
        row = self.conn.execute("SELECT email, telefono FROM clientes WHERE id = 'c31'").fetchone()
        self.assertTrue(result["ok"])
        self.assertEqual(row["email"], "maria@test.local")
        self.assertEqual(row["telefono"], "+34600111222")

    def test_internal_copilot_action_attaches_renta(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, telefono, created_at, updated_at) VALUES ('c32', 'Cliente Renta', '44444444D', 'renta@test.local', '+34600111333', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce32', 'c32', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO empresas (id, nombre, created_at, updated_at) VALUES ('e1', 'Empresa Demo', 'now', 'now')")
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "attach_renta",
            {"cliente_id": "c32", "ejercicio": "2025", "doc_key": "rentas/doc1.pdf", "estado_presentacion": "Presentada"},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T12:05:00Z",
        )
        cg = self.conn.execute("SELECT renta_detalles FROM cliente_gestoria WHERE cliente_id = 'c32'").fetchone()
        docs = self.conn.execute("SELECT COUNT(*) AS total FROM gestoria_docs WHERE cliente_id = 'c32'").fetchone()
        self.assertTrue(result["ok"])
        self.assertIsNotNone(cg)
        self.assertGreaterEqual(int(docs["total"] or 0), 1)

    def test_internal_copilot_uses_current_client_for_implicit_renta_action(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, telefono, created_at, updated_at) VALUES ('c40', 'Cliente Actual', '55555555E', 'actual@test.local', '+34600111444', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce40', 'c40', 'e1', 'gestoria')")
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "carga esta renta 2025",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
            context={"current_client_id": "c40", "attachments": [{"key": "rentas/doc40.pdf", "public_url": "", "filename": "renta.pdf", "content_type": "application/pdf"}]},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertTrue(reply["actions"])
        self.assertEqual(reply["actions"][0]["id"], "attach_renta")

    def test_internal_copilot_offers_candidate_confirmation_for_seguro(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c50', 'Ana Seguro', '66666666F', 'ana1@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c51', 'Ana Segura', '77777777G', 'ana2@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce50', 'c50', 'e1', 'seguros')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce51', 'c51', 'e1', 'seguros')")
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "mete una póliza de Mapfre para Ana",
            empresa_id="e1",
            service_hint="seguros",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertTrue(reply["actions"])
        self.assertEqual(reply["actions"][0]["id"], "create_seguro")

    def test_internal_copilot_review_reply_includes_bulk_revalidate_action(self):
        today_iso = f"{date.today().isoformat()}T09:00:00Z"
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-bulk', 'ws1', 'e1', 'gestoria', 'renta_attach', 'cliente', 'c40', '',
              '', 'warning', 'warning', 'Renta incompleta', 'Falta documento',
              '[{\"code\":\"renta_document_missing\"}]', '[]', '{}',
              'dbulk', 0, NULL, ?, ?
            )
            """,
            (today_iso, today_iso),
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "revisa todas las rentas de hoy",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["actions"])
        self.assertEqual(reply["actions"][0]["id"], "bulk_revalidate_processes")

    def test_internal_copilot_action_updates_current_seguro(self):
        self.conn.execute("INSERT INTO empresas (id, nombre, created_at, updated_at) VALUES ('e1', 'Empresa Demo', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c60', 'Cliente Seguro', '88888888H', 'seg@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO seguros (id, empresa_id, cliente_id, tomador, compania, poliza_numero, estado, created_at, updated_at) VALUES ('s60', 'e1', 'c60', 'Cliente Seguro', 'Mapfre', 'P-60', 'Presupuesto', 'now', 'now')")
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_seguro",
            {"seguro_id": "s60", "patch": {"compania": "Allianz", "estado": "Contratada"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:00:00Z",
        )
        row = self.conn.execute("SELECT compania, estado FROM seguros WHERE id = 's60'").fetchone()
        self.assertTrue(result["ok"])
        self.assertEqual(row["compania"], "Allianz")
        self.assertEqual(row["estado"], "Contratada")

    def test_internal_copilot_action_bulk_revalidates(self):
        self.conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('we-bulk', 'ws1', 'e1', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c61', 'Cliente Bulk', '99999999J', 'bulk@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce61', 'c61', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO cliente_gestoria (id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at) VALUES ('cg61', 'c61', 'Particular', 0, 0, 0, 1, 0, 0, 0, '{\"entries\":[]}', 'now', 'now')")
        server.run_workspace_process_supervision(
            self.conn,
            process_type="renta_attach",
            servicio="gestoria",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="cliente",
            entity_id="c61",
            context={"ejercicio": "2025"},
            now="2026-06-18T10:00:00Z",
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_revalidate_processes",
            {"process_types": ["renta_attach"], "dates": ["2026-06-18"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:05:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(int(result["updated"] or 0), 1)

    def test_internal_copilot_action_updates_current_hipoteca(self):
        self.conn.execute("INSERT INTO empresas (id, nombre, created_at, updated_at) VALUES ('e1', 'Empresa Demo', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c70', 'Cliente Hipoteca', '10101010A', 'hip@test.local', 'now', 'now')")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'h70', 'e1', 'Cliente Hipoteca', 'c70', 'Sabadell', 250000, 180000, 'Estudio', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_hipoteca",
            {"hipoteca_id": "h70", "patch": {"banco": "CaixaBank", "importe_hipoteca": 190000, "estado": "Encargo"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:10:00Z",
        )
        row = self.conn.execute("SELECT banco, importe_hipoteca, estado FROM hipotecas WHERE id = 'h70'").fetchone()
        self.assertTrue(result["ok"])
        self.assertEqual(row["banco"], "CaixaBank")
        self.assertEqual(row["importe_hipoteca"], 190000)
        self.assertEqual(row["estado"], "Encargo")

    def test_internal_copilot_action_updates_current_factura(self):
        self.conn.execute("INSERT INTO empresas (id, nombre, created_at, updated_at) VALUES ('e1', 'Empresa Demo', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c71', 'Cliente Factura', '20202020B', 'fact@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, total, created_at, updated_at
            ) VALUES (
              'f71', 'e1', 'c71', 'compra', 'F-71', '2026-06-01', 1200, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_factura",
            {"factura_id": "f71", "patch": {"numero": "F-71B", "total": 1500, "fecha_emision": "2026-06-02"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:15:00Z",
        )
        row = self.conn.execute("SELECT numero, total, fecha_emision FROM gestoria_facturas WHERE id = 'f71'").fetchone()
        self.assertTrue(result["ok"])
        self.assertEqual(row["numero"], "F-71B")
        self.assertEqual(row["total"], 1500)
        self.assertEqual(row["fecha_emision"], "2026-06-02")

    def test_internal_copilot_action_bulk_rerun_ocr(self):
        self.conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('we-rerun', 'ws1', 'e1', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c72', 'Cliente OCR', '30303030C', 'ocr@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce72', 'c72', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO cliente_gestoria (id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at) VALUES ('cg72', 'c72', 'Particular', 0, 0, 0, 1, 0, 0, 0, '{\"entries\":[]}', 'now', 'now')")
        server.run_workspace_process_supervision(
            self.conn,
            process_type="renta_attach",
            servicio="gestoria",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="cliente",
            entity_id="c72",
            context={"ejercicio": "2025"},
            now="2026-06-18T10:30:00Z",
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_rerun_ocr",
            {"process_types": ["renta_attach"], "dates": ["2026-06-18"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:20:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["post_actions"])
        self.assertEqual(result["post_actions"][0]["post_endpoint"], "/api/renta_entry_ocr_reprocess")

    def test_internal_copilot_action_updates_current_rrhh_document(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, doc_url, fecha_emision, fecha_caducidad, permanente, estado, notas, created_at, updated_at
            ) VALUES (
              'rd1', 'ws1', 'e1', 'p1', 'Nómina', 'nomina.pdf', 'rrhh/old.pdf', 'https://example.test/old.pdf', '2026-05-01', '', 0, 'Activo', '', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_rrhh_document",
            {"documento_id": "rd1", "persona_id": "p1", "patch": {"nombre": "nomina-junio.pdf", "doc_key": "rrhh/new.pdf", "estado": "Activo"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["post_actions"])
        self.assertEqual(result["post_actions"][0]["post_endpoint"], "/api/workspace_rrhh_documento")

    def test_internal_copilot_action_updates_current_community(self):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, direccion, estado, presidente, secretario, cuota_mensual, created_at, updated_at
            ) VALUES (
              'fc1', 'ws1', 'e1', 'Comunidad Sol', 'Calle Mayor 1', 'Activa', 'Pedro', 'Ana', 100, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_community",
            {"comunidad_id": "fc1", "patch": {"cuota_mensual": 125.0, "presidente": "Laura"}} ,
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:35:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["post_actions"])
        self.assertEqual(result["post_actions"][0]["post_endpoint"], "/api/workspace_fincas_comunidades")

    def test_internal_copilot_action_bulk_safe_repair(self):
        self.conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('we-safe', 'ws1', 'e1', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c73', 'Cliente Safe', '40404040D', 'safe@test.local', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ce73', 'c73', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO cliente_gestoria (id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at) VALUES ('cg73', 'c73', 'Particular', 0, 0, 0, 1, 0, 0, 0, '{\"entries\":[]}', 'now', 'now')")
        server.run_workspace_process_supervision(
            self.conn,
            process_type="renta_attach",
            servicio="gestoria",
            empresa_id="e1",
            workspace_id="ws1",
            entity_type="cliente",
            entity_id="c73",
            context={"ejercicio": "2025"},
            now="2026-06-18T11:00:00Z",
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_safe_repair",
            {"process_types": ["renta_attach"], "dates": ["2026-06-18"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:40:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["post_actions"])
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_updates_current_factura_validate(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, total, created_at, updated_at
            ) VALUES (
              'f72', 'e1', 'c71', 'compra', 'F-72', '2026-06-03', 800, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_factura_validate",
            {"factura_id": "f72", "patch": {"numero": "F-72X", "total": 900}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:45:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "update_current_factura_validate")

    def test_internal_copilot_action_updates_current_community_refresh(self):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, direccion, estado, presidente, secretario, cuota_mensual, created_at, updated_at
            ) VALUES (
              'fc2', 'ws1', 'e1', 'Comunidad Luna', 'Calle Sol 2', 'Activa', 'Maria', 'Luis', 90, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "update_current_community_refresh",
            {"comunidad_id": "fc2", "patch": {"cuota_mensual": 95}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T13:50:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "update_current_community_refresh")
        self.assertEqual(result["navigation"]["tab"], "comunidad_ficha")

    def test_internal_copilot_operational_query_rrhh_docs_expired(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, fecha_caducidad, permanente, estado, created_at, updated_at
            ) VALUES (
              'rd-exp', 'ws1', 'e1', 'p1', 'Documento', 'dni.pdf', 'rrhh/dni.pdf', '2025-01-01', 0, 'Activo', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "revisa documentos rrhh caducados",
            empresa_id="e1",
            service_hint="rrhh",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("documento", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "workspace_rrhh_documentos")
        self.assertEqual(reply["actions"][0]["id"], "open_module")
        self.assertEqual(reply["actions"][1]["id"], "start_review_queue")

    def test_internal_copilot_operational_query_communities_quota_mismatch(self):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, direccion, estado, cuota_mensual, cuota_sugerida, created_at, updated_at
            ) VALUES (
              'fc-mis', 'ws1', 'e1', 'Comunidad Delta', 'Calle Real 9', 'Activa', 90, 120, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "revisa comunidades con cuota incoherente",
            empresa_id="e1",
            service_hint="fincas",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("comunidad", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "workspace_fincas_comunidades")
        self.assertEqual(reply["actions"][0]["id"], "open_module")
        self.assertEqual(reply["actions"][1]["id"], "start_review_queue")

    def test_internal_copilot_operational_query_invoices_without_asiento(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, total, created_at, updated_at
            ) VALUES (
              'f73', 'e1', 'c71', 'compra', 'F-73', '2026-06-04', 300, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que facturas siguen sin asiento",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("factura", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "gestoria_facturas")

    def test_internal_copilot_operational_query_policies_without_pdf(self):
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id, tomador, compania, poliza_numero, estado, created_at, updated_at
            ) VALUES (
              's-no-pdf', 'e1', 'c71', 'Cliente Factura', 'Mapfre', 'P-999', 'Contratada', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que polizas estan sin pdf",
            empresa_id="e1",
            service_hint="seguros",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("póliza", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "seguros")
        self.assertEqual(reply["actions"][0]["id"], "open_module")
        self.assertEqual(reply["actions"][1]["id"], "start_review_queue")

    def test_internal_copilot_operational_query_hipotecas_missing_amounts(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'h-miss', 'e1', 'Cliente Hipoteca', 'c70', 'Bankia', 0, 0, 'Estudio', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que hipotecas estan sin importes base",
            empresa_id="e1",
            service_hint="financiaciones",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("hipoteca", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "hipotecas")
        self.assertEqual(reply["actions"][0]["id"], "bulk_revalidate_missing_hipotecas")
        self.assertEqual(reply["actions"][1]["id"], "resolve_domain_safe")
        self.assertEqual(reply["actions"][2]["id"], "start_review_queue")

    def test_internal_copilot_operational_query_rentas_missing_document(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c74', 'Cliente Renta', '50505050E', 'renta@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at
            ) VALUES (
              'cg74', 'c74', 'Particular', 0, 0, 0, 1, 0, 0, 0, '{"entries":[{"id":"r1","ejercicio":"2025","estado_presentacion":"Borrador"}]}', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que rentas estan sin documento",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("renta", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "cliente_gestoria")
        self.assertEqual(reply["actions"][0]["id"], "bulk_revalidate_rentas_missing_document")
        self.assertEqual(reply["actions"][1]["id"], "resolve_domain_safe")
        self.assertEqual(reply["actions"][2]["id"], "start_review_queue")

    def test_internal_copilot_operational_query_dashboard_mismatch(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-dash-op', 'ws1', 'e1', 'seguros', 'seguros_dashboard', 'seguros_dashboard', 'ws1', '',
              '', 'failed', 'warning', 'Dashboard seguros incoherente', 'Totales no cuadran contra detalle', '[]', '[]', '{}',
              'ddash-op', 0, NULL, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que dashboards no cuadran contra el detalle real",
            empresa_id="e1",
            service_hint="seguros",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertIn("dashboard", reply["answer"].lower())
        self.assertEqual(reply["sources"][0], "workspace_process_supervisor")
        self.assertEqual(reply["actions"][0]["id"], "bulk_refresh_mismatched_dashboards")
        self.assertEqual(reply["actions"][1]["id"], "resolve_domain_safe")

    def test_internal_copilot_operational_query_facturas_without_asiento_includes_action(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, total, created_at, updated_at
            ) VALUES (
              'f-op1', 'e1', 'c1', 'compra', 'F-OP1', '2026-06-10', 450, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que facturas siguen sin asiento",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["actions"][0]["id"], "bulk_revalidate_facturas_without_asiento")
        self.assertEqual(reply["actions"][1]["id"], "bulk_rerun_facturas_ocr")
        self.assertEqual(reply["actions"][2]["id"], "resolve_domain_safe")
        self.assertEqual(reply["actions"][3]["id"], "start_review_queue")

    def test_internal_copilot_action_bulk_revalidate_missing_hipotecas(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'h-op1', 'e1', 'Cliente Hipoteca', 'c70', 'Openbank', 0, 0, 'Estudio', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_revalidate_missing_hipotecas",
            {"hipoteca_ids": ["h-op1"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:10:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["updated"] or 0), 1)
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_bulk_revalidate_rentas_missing_document(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('c74b', 'Cliente Renta 2', '60606060F', 'renta2@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at
            ) VALUES (
              'cg74b', 'c74b', 'Particular', 0, 0, 0, 1, 0, 0, 0, '{"entries":[{"id":"r2","ejercicio":"2025","estado_presentacion":"Borrador"}]}', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_revalidate_rentas_missing_document",
            {"items": [{"cliente_id": "c74b", "entry_id": "r2", "ejercicio": "2025"}]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:15:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["updated"] or 0), 1)
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_bulk_refresh_mismatched_dashboards(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-dash-refresh', 'ws1', 'e1', 'gestoria', 'gestoria_dashboard', 'gestoria_dashboard', 'ws1', '',
              '', 'failed', 'warning', 'Dashboard gestoría incoherente', 'Totales no cuadran contra detalle', '[{"code":"gestoria_dashboard_docs_mismatch"}]', '[]', '{}',
              'ddash-refresh', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_refresh_mismatched_dashboards",
            {"event_ids": ["evt-dash-refresh"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:20:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["updated"] or 0), 1)
        self.assertTrue(result["refresh_supervisor"])
        self.assertIn("revalidado", result["message"].lower())

    def test_internal_copilot_action_bulk_revalidate_facturas_without_asiento(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, total, created_at, updated_at
            ) VALUES (
              'f-op2', 'e1', 'c1', 'compra', 'F-OP2', '2026-06-11', 700, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_revalidate_facturas_without_asiento",
            {"factura_ids": ["f-op2"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:25:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["updated"] or 0), 1)
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_bulk_rerun_facturas_ocr(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "bulk_rerun_facturas_ocr",
            {"facturas": [{"factura_id": "f-op3", "cliente_id": "c1", "doc_key": "docs/f-op3.pdf", "tipo": "compra"}]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["post_actions"][0]["post_endpoint"], "/api/gestoria_factura_ocr")
        self.assertEqual(result["post_actions"][0]["payload"]["s3_key"], "docs/f-op3.pdf")

    def test_internal_copilot_action_resolve_domain_safe_rentas(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_domain_safe",
            {"domain": "rentas_missing_document", "items": [{"cliente_id": "c74b", "entry_id": "r2", "ejercicio": "2025"}]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:32:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["post_actions"][0]["post_endpoint"], "/api/renta_entry_ocr_reprocess")
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_resolve_domain_safe_facturas(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_domain_safe",
            {"domain": "facturas_without_asiento", "facturas": [{"factura_id": "f-op3", "cliente_id": "c1", "doc_key": "docs/f-op3.pdf", "tipo": "compra"}]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:33:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["post_actions"][0]["post_endpoint"], "/api/gestoria_factura_ocr")
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_resolve_domain_safe_hipotecas(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'h-op1', 'e1', 'Cliente Hipoteca', 'c70', 'Openbank', 0, 0, 'Estudio', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_domain_safe",
            {"domain": "hipotecas_missing_base", "hipoteca_ids": ["h-op1"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:34:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["updated"] or 0), 1)
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_resolve_domain_safe_dashboards(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-dash-safe', 'ws1', 'e1', 'seguros', 'seguros_dashboard', 'seguros_dashboard', 'ws1', '',
              '', 'failed', 'warning', 'Dashboard seguros incoherente', 'Totales no cuadran contra detalle', '[]', '[]', '{}',
              'ddash-safe', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_domain_safe",
            {"domain": "dashboard_mismatch", "event_ids": ["evt-dash-safe"]},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:35:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["updated"] or 0), 1)
        self.assertTrue(result["refresh_supervisor"])

    def test_internal_copilot_action_review_queue_returns_next_action(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "start_review_queue",
            {
                "queue_type": "seguros_missing_pdf",
                "items": [
                    {"seguro_id": "s1", "cliente_id": "c1", "title": "P-1", "summary": "Mapfre · Contratada"},
                    {"seguro_id": "s2", "cliente_id": "c2", "title": "P-2", "summary": "Allianz · Contratada"},
                ],
            },
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:35:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "cliente")
        self.assertEqual(result["navigation"]["cliente_id"], "c1")
        self.assertTrue(result["cards"])
        self.assertEqual(result["actions"][0]["id"], "revalidate_current_and_continue")
        self.assertEqual(result["actions"][1]["id"], "continue_review_queue")

    def test_internal_copilot_action_review_queue_rentas_uses_cliente_navigation(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "start_review_queue",
            {
                "queue_type": "gestoria_rentas_missing_document",
                "items": [
                    {"cliente_id": "c74", "entry_id": "r1", "ejercicio": "2025", "title": "Renta 2025", "summary": "Cliente · estado Borrador"},
                ],
            },
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:36:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "cliente")
        self.assertEqual(result["navigation"]["cliente_id"], "c74")

    def test_internal_copilot_action_revalidate_current_and_continue(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "revalidate_current_and_continue",
            {
                "queue_type": "gestoria_rentas_missing_document",
                "current_item": {"cliente_id": "c74", "entry_id": "r1", "ejercicio": "2025", "title": "Renta 2025"},
                "items": [{"cliente_id": "c74b", "entry_id": "r2", "ejercicio": "2025", "title": "Renta 2025 B", "summary": "Cliente 2"}],
                "route": "/?holding=1&mode=tenant&workspace=ws1&crm=gestoria",
            },
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:37:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "revalidate_current_and_continue")
        self.assertTrue(result["refresh_supervisor"])
        self.assertIn("revalidado", result["message"].lower())
        self.assertEqual(result["navigation"]["cliente_id"], "c74b")

    def test_internal_copilot_action_review_queue_rrhh_navigation(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "start_review_queue",
            {
                "queue_type": "rrhh_docs_expired",
                "items": [{"documento_id": "rd-exp", "persona_id": "p1", "title": "dni.pdf", "summary": "Documento · caduca 2025-01-01"}],
            },
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:38:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "workspace_view")
        self.assertEqual(result["navigation"]["view"], "rrhh")

    def test_internal_copilot_action_review_queue_fincas_navigation(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "start_review_queue",
            {
                "queue_type": "fincas_communities_quota",
                "items": [{"comunidad_id": "fc-mis", "title": "Comunidad Delta", "summary": "cuota 90 · sugerida 120"}],
            },
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:39:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"]["kind"], "workspace_view")
        self.assertEqual(result["navigation"]["view"], "fincas")

    def test_internal_copilot_action_autorreview_domain_rrhh(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, fecha_caducidad, permanente, estado, created_at, updated_at
            ) VALUES (
              'rd-exp-2', 'ws1', 'e1', 'p1', 'Documento', 'pasaporte.pdf', 'rrhh/pass.pdf', '2025-01-01', 0, 'Activo', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "autorreview_domain",
            {"domain": "rrhh"},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:40:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["cards"])
        self.assertTrue(result["actions"])

    def test_internal_copilot_action_autorreview_domain_fincas(self):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, direccion, estado, cuota_mensual, cuota_sugerida, created_at, updated_at
            ) VALUES (
              'fc-mis-2', 'ws1', 'e1', 'Comunidad Sigma', 'Calle Nueva 3', 'Activa', 80, 120, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "autorreview_domain",
            {"domain": "fincas"},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:41:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["cards"])
        self.assertTrue(result["actions"])

    def test_internal_copilot_reply_offers_unified_inbox(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "que es lo mas urgente hoy",
            empresa_id="e1",
            service_hint="core",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["actions"][0]["id"], "autorreview_global")

    def test_internal_copilot_reply_offers_daily_review_agenda(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "prepara la agenda diaria de revision",
            empresa_id="e1",
            service_hint="core",
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["actions"][0]["id"], "daily_review_agenda")

    def test_internal_copilot_action_autorreview_global(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-urgent', 'ws1', 'e1', 'gestoria', 'gestoria_factura', 'gestoria_factura', 'f-op2', '',
              '', 'failed', 'error', 'Factura sin asiento', 'Impacto económico alto', '[]', '[]', '{}',
              'urgent-1', 0, NULL, 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, fecha_caducidad, permanente, estado, created_at, updated_at
            ) VALUES (
              'rd-exp-3', 'ws1', 'e1', 'p1', 'Documento', 'carnet.pdf', 'rrhh/carnet.pdf', '2025-01-01', 0, 'Activo', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "autorreview_global",
            {"scope": "today"},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:42:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["cards"])
        self.assertTrue(result["actions"])
        self.assertIn("workspace_process_supervisor", result["sources"])

    def test_internal_copilot_action_daily_review_agenda(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-urgent-2', 'ws1', 'e1', 'rrhh', 'rrhh_document', 'rrhh_documento', 'rd-exp-2', '',
              '', 'failed', 'error', 'Documento RRHH vencido', 'Impacto laboral alto', '[]', '[]', '{}',
              'urgent-2', 0, NULL, 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, fecha_caducidad, permanente, estado, created_at, updated_at
            ) VALUES (
              'rd-exp-4', 'ws1', 'e1', 'p1', 'Documento', 'permiso.pdf', 'rrhh/permiso.pdf', '2025-01-01', 0, 'Activo', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "daily_review_agenda",
            {"scope": "today"},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-18T14:43:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["cards"])
        self.assertIn("Urgente hoy", " ".join(str(card.get("title") or "") for card in result["cards"]))

    def test_internal_copilot_memory_reply_and_action_tables(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "recuerda que mañana tengo que revisar la comunidad norte",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "memory")
        rows = self.conn.execute("SELECT * FROM workspace_internal_copilot_memory WHERE workspace_id = 'ws1'").fetchall()
        self.assertTrue(rows)

    def test_internal_copilot_task_reply_and_complete_action(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "crea una tarea para revisar las pólizas sin pdf mañana",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "task_planner")
        action = next((item for item in reply.get("actions") or [] if item.get("id") == "complete_task"), None)
        self.assertIsNotNone(action)
        task_row = self.conn.execute("SELECT * FROM workspace_internal_copilot_tasks WHERE workspace_id = 'ws1' ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIsNotNone(task_row)
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "complete_task",
            {"task_id": task_row["id"]},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T12:00:00Z",
        )
        self.assertTrue(result["ok"])
        done_row = self.conn.execute("SELECT status FROM workspace_internal_copilot_tasks WHERE id = ?", (task_row["id"],)).fetchone()
        self.assertEqual(done_row["status"], "done")

    def test_internal_copilot_semantic_search_reply(self):
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id, tomador, compania, poliza_numero, created_at, updated_at
            ) VALUES (
              'seg-sem-1', 'e1', 'c1', 'Juan Cliente', 'Mapfre', 'POL-7788', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "busca la póliza mapfre 7788",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "semantic_search")
        self.assertTrue(reply["cards"])

    def test_internal_copilot_specialist_search_fiscal_reply(self):
        server.ensure_column(self.conn, "gestoria_facturas", "estado_asiento", "estado_asiento TEXT")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gestoria_modelos (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              modelo TEXT,
              proxima_fecha TEXT,
              estado TEXT,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, numero, fecha_emision, total, estado_asiento, created_at, updated_at
            ) VALUES (
              'fac-spec-1', 'e1', 'c1', 'F-900', '2026-06-19', 220.0, 'pendiente', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_modelos (
              id, cliente_id, modelo, proxima_fecha, estado, created_at, updated_at
            ) VALUES (
              'mod-spec-1', 'c1', '303', '2026-06-30', 'Pendiente', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "busca facturas sin asiento",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={"copilot_mode": "fiscal"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "specialist_search")
        self.assertEqual(reply["mode"], "fiscal")
        self.assertIn("gestoria_facturas", reply["sources"])
        self.assertTrue(any(str(card.get("title") or "") == "Evidencia experta fiscal" for card in (reply.get("cards") or [])))

    def test_internal_copilot_specialist_search_laboral_reply(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, fecha_emision, fecha_caducidad, permanente, estado, notas, created_at, updated_at
            ) VALUES (
              'doc-spec-1', 'ws1', 'e1', 'p1', 'DNI', 'dni-juan.pdf', '2026-01-01', '2026-06-01', 0, 'Activo', '', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_ausencias (
              id, workspace_id, empresa_id, persona_id, tipo, fecha_inicio, fecha_fin, estado, created_at, updated_at
            ) VALUES (
              'aus-spec-1', 'ws1', 'e1', 'p1', 'Vacaciones', '2026-06-20', '2026-06-22', 'Pendiente', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "busca ausencias abiertas",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={"copilot_mode": "laboral"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "specialist_search")
        self.assertEqual(reply["mode"], "laboral")
        self.assertIn("workspace_rrhh_ausencias", reply["sources"])
        self.assertTrue(any(str(card.get("title") or "") == "Evidencia experta laboral" for card in (reply.get("cards") or [])))

    def test_internal_copilot_specialist_search_legal_reply(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_library_documents (
              id TEXT PRIMARY KEY,
              area TEXT,
              topic_key TEXT,
              title TEXT,
              url TEXT,
              source TEXT,
              fetched_at TEXT,
              updated_at TEXT,
              content_text TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_radar_items (
              id TEXT PRIMARY KEY,
              area TEXT,
              topic_key TEXT,
              titulo TEXT,
              url TEXT,
              resumen TEXT,
              accion_recomendada TEXT,
              affected_documents TEXT,
              affected_workflows TEXT,
              impacto TEXT,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO legal_library_documents (
              id, area, topic_key, title, url, source, fetched_at, updated_at, content_text
            ) VALUES (
              'lib-spec-1', 'gestoria', 'modelos_tributarios', 'Checklist modelo 303', 'https://ejemplo.local/303', 'interno', 'now', 'now', 'Checklist fiscal del modelo 303 y vencimientos.'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO legal_radar_items (
              id, area, topic_key, titulo, url, resumen, accion_recomendada, affected_documents, affected_workflows, impacto, estado, created_at, updated_at
            ) VALUES (
              'rad-spec-1', 'gestoria', 'modelos_tributarios', 'Cambio en modelo 303', 'https://ejemplo.local/radar-303', 'Nuevo criterio sobre presentación del 303', 'Revisar checklist fiscal', '["Checklist fiscal"]', '["Campañas fiscales"]', 'alto', 'pendiente', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "busca novedades del modelo 303",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={"copilot_mode": "legal", "current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "specialist_search")
        self.assertEqual(reply["mode"], "legal")
        self.assertIn("legal_library_documents", reply["sources"])
        self.assertIn("legal_radar_items", reply["sources"])
        self.assertTrue(any(str(card.get("title") or "") == "Evidencia experta legal" for card in (reply.get("cards") or [])))

    def test_internal_copilot_document_reply_from_attachment(self):
        server._workspace_internal_copilot_preview_factura = lambda conn, attachment, actor=None: {
            "numero": "FAC-1",
            "fecha_emision": "2026-06-19",
            "total": 121.0,
            "cliente_nombre": "Juan Cliente",
        }
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "revisa este documento factura pdf",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={"attachments": [{"filename": "factura.pdf", "key": "facturas/f1.pdf"}]},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "document")
        self.assertIn("FAC-1", reply["answer"])

    def test_internal_copilot_image_reply_from_attachment(self):
        if Image is None:
            self.skipTest("Pillow no disponible")
        buffer = BytesIO()
        Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
        data = "data:image/png;base64," + b64encode(buffer.getvalue()).decode("ascii")
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "mejora esta imagen para OCR",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={"attachments": [{"filename": "scan.png", "content_type": "image/png", "data": data}]},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "image_edit")
        self.assertEqual(reply["actions"][0]["id"], "edit_attached_image")

    def test_internal_copilot_action_edit_attached_image(self):
        if Image is None:
            self.skipTest("Pillow no disponible")
        buffer = BytesIO()
        Image.new("RGB", (160, 100), "white").save(buffer, format="PNG")
        data = "data:image/png;base64," + b64encode(buffer.getvalue()).decode("ascii")
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(server, "UPLOADS", Path(tmpdir) / "uploads"):
            server.UPLOADS.mkdir(parents=True, exist_ok=True)
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "edit_attached_image",
                {
                    "attachment": {"filename": "scan.png", "content_type": "image/png", "data": data},
                    "plan": {"operations": [{"op": "enhance_ocr"}, {"op": "grayscale"}]},
                },
                empresa_id="e1",
                actor={"id": "u1", "usuario": "QA"},
                now="2026-06-24T10:00:00Z",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["action_id"], "edit_attached_image")
            self.assertTrue(str(result["image_edit"]["url"]).startswith("/uploads/copilot_image_edits/"))
            saved_path = (server.UPLOADS.parent / str(result["image_edit"]["url"]).lstrip("/")).resolve()
            self.assertTrue(saved_path.exists())

    def test_internal_copilot_reconciliation_and_simulation_reply(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-mismatch-1', 'ws1', 'e1', 'seguros', 'seguros_dashboard', 'seguro', 'seg-1', '',
              '', 'failed', 'warning', 'Dashboard descuadrado', 'El resumen no coincide con el detalle', '[{\"code\":\"dashboard_mismatch\",\"message\":\"Descuadre\"}]', '[]', '{}',
              'mismatch-1', 0, NULL, 'now', 'now'
            )
            """
        )
        reconciliation = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué dashboard no cuadra contra el detalle real",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(reconciliation["ok"])
        self.assertEqual(reconciliation["intent"], "reconciliation")
        simulation = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "simula qué pasa si recalculo este dashboard de seguros",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(simulation["ok"])
        self.assertEqual(simulation["intent"], "simulation")

    def test_internal_copilot_briefing_reply(self):
        server._workspace_internal_copilot_create_task(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            title="Revisar pólizas sin PDF",
            detail="Bloque de trabajo de seguros",
            priority="alta",
            due_at="2026-06-19",
            source="test",
            now="2026-06-19T09:00:00Z",
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-brief-1', 'e1', 'Juan Cliente', 'c1', 'BBVA', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué hago ahora",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "briefing")
        self.assertTrue(reply["cards"])
        self.assertTrue(any(str(action.get("id") or "") == "resolve_global_safe" for action in (reply.get("actions") or [])))

    def test_internal_copilot_continue_reply_uses_recent_memory(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="user_note",
            title="Pendiente de hoy",
            content="Retomar las rentas incompletas de la mañana",
            priority="alta",
            meta={"source": "test"},
            now="2026-06-19T08:00:00Z",
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "continúa con lo de esta mañana",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "continue_context")
        self.assertTrue(reply["cards"])
        self.assertIn("contexto", " ".join(str(card.get("impact_area") or "") for card in (reply.get("cards") or [])))

    def test_internal_copilot_action_resolve_global_safe(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-safe-1', 'e1', 'Juan Cliente', 'c1', 'Caixa', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_global_safe",
            {"scope": "today"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T12:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(int(result.get("updated") or 0), 1)
        self.assertTrue(result.get("refresh_supervisor"))

    def test_internal_copilot_prime_operator_console_mode(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decision financiaciones",
            content="Microflujo cerrado",
            priority="media",
            meta={
                "domain": "financiaciones",
                "safe_action_id": "bulk_revalidate_missing_hipotecas",
                "resolved": 2,
                "updated": 2,
            },
            now="2026-06-19T09:00:00Z",
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-prime-1', 'e1', 'Juan Cliente', 'c1', 'BBVA', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload, dedupe_key,
              acknowledged, created_at, updated_at
            ) VALUES (
              'wps-prime-hip-1', 'ws1', 'e1', 'financiaciones', 'hipoteca_update', 'hipoteca', 'hip-prime-1', 'u1',
              'QA', 'open', 'warning', 'Hipoteca incompleta', 'Faltan importes base en la ficha abierta',
              '[]', '[]', '{}', 'dup-hip-prime-1', 0, '2026-06-19T10:00:00Z', '2026-06-19T10:00:00Z'
            )
            """
        )
        reply = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prime_operator_console",
            {"current_workspace_view": "fin", "current_crm": "fin", "copilot_mode": "operator", "current_hipoteca_id": "hip-prime-1"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA", "rol": "Administrador", "servicio": "Administración"},
            now="2026-06-19T12:10:00Z",
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["action_id"], "prime_operator_console")
        self.assertEqual(reply["mode"], "operator")
        self.assertTrue(reply["actions"])
        self.assertTrue(any(str(card.get("title") or "") == "Microflujo de la ficha actual" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_current_entity_microflow" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Prioridad de la ficha actual" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Entidad actual" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "diagnose_current_entity" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_catalog_process" for action in (reply.get("actions") or [])))
        run_catalog = next((action for action in (reply.get("actions") or []) if str(action.get("id") or "") == "run_catalog_process"), {})
        process_context = ((run_catalog.get("payload") or {}).get("context") or {}) if isinstance(run_catalog.get("payload"), dict) else {}
        self.assertEqual(str(process_context.get("current_hipoteca_id") or ""), "hip-prime-1")
        self.assertTrue(any(str(action.get("id") or "") == "run_domain_microflow" for action in (reply.get("actions") or [])))
        self.assertTrue(any("Siguiente microflujo" in str(card.get("title") or "") for card in (reply.get("cards") or [])))
        self.assertTrue(any("Siguiente registro recomendado" == str(card.get("title") or "") for card in (reply.get("cards") or [])))
        self.assertTrue(any("Perfil de foco" == str(card.get("title") or "") for card in (reply.get("cards") or [])))
        self.assertTrue(any("Procesos ejecutables" == str(card.get("title") or "") for card in (reply.get("cards") or [])))

    def test_internal_copilot_process_capability_reply_lists_domain_processes(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué procesos puedes ejecutar",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "process_capabilities")
        self.assertTrue(any(str(card.get("title") or "") == "Procesos ejecutables" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_catalog_process" for action in (reply.get("actions") or [])))

    def test_internal_copilot_run_catalog_process_executes_renta_attach(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, telefono, created_at, updated_at) VALUES ('cproc1', 'Cliente Proceso', '90909090Z', 'proc@test.local', '+34600999000', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio) VALUES ('ceproc1', 'cproc1', 'e1', 'gestoria')")
        self.conn.execute("INSERT INTO empresas (id, nombre, created_at, updated_at) VALUES ('e1', 'Empresa Demo', 'now', 'now')")
        original_preview = server._workspace_internal_copilot_preview_renta
        server._workspace_internal_copilot_preview_renta = lambda conn, attachment, actor=None: {"ejercicio": "2025"}
        try:
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "run_catalog_process",
                {
                    "process_id": "renta_attach",
                    "context": {
                        "current_client_id": "cproc1",
                        "attachments": [{"key": "rentas/proc1.pdf", "public_url": "", "filename": "renta-2025.pdf", "content_type": "application/pdf"}],
                    },
                },
                empresa_id="e1",
                actor={"user_id": "u1", "usuario": "QA"},
                now="2026-06-21T09:00:00Z",
            )
        finally:
            server._workspace_internal_copilot_preview_renta = original_preview
        cg = self.conn.execute("SELECT renta_detalles FROM cliente_gestoria WHERE cliente_id = 'cproc1'").fetchone()
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "run_catalog_process")
        self.assertEqual(result["executed_process"], "renta_attach")
        self.assertIsNotNone(cg)

    def test_internal_copilot_run_catalog_process_guides_when_context_missing(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_catalog_process",
            {"process_id": "renta_attach", "context": {}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-21T09:05:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "run_catalog_process")
        self.assertEqual(result["executed_process"], "renta_attach")
        self.assertIn("cliente", str(result.get("message") or "").lower())

    def test_internal_copilot_run_catalog_process_executes_domain_microflow(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-cat-1', 'e1', 'Juan Cliente', 'c1', 'Santander', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_catalog_process",
            {"process_id": "hipoteca_revalidate", "context": {"current_crm": "financiaciones"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-21T09:10:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "run_catalog_process")
        self.assertEqual(result["executed_process"], "hipoteca_revalidate")
        self.assertEqual(result["delegated_action"], "run_domain_microflow")

    def test_internal_copilot_work_center_includes_catalog_process_actions(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "copilot_work_center",
            {"current_crm": "gestoria", "current_client_id": "c1"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T09:15:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(any(str(action.get("id") or "") == "run_catalog_process" for action in (result.get("actions") or [])))

    def test_internal_copilot_prepare_catalog_process_autofills_open_seguro(self):
        self.conn.execute("INSERT INTO empresas (id, nombre, created_at, updated_at) VALUES ('e1', 'Empresa Demo', 'now', 'now')")
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('csegctx', 'Cliente Seguro', '12121212A', 'segctx@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id, tomador, compania, poliza_numero, ramo, estado, created_at, updated_at
            ) VALUES (
              'segctx1', 'e1', 'csegctx', 'Cliente Seguro', 'Mapfre', 'PX-1', 'Hogar', 'Presupuesto', 'now', 'now'
            )
            """
        )
        result = server._workspace_internal_copilot_prepare_catalog_process(
            self.conn,
            "ws1",
            "e1",
            "seguro_create",
            {"context": {"current_seguro_id": "segctx1", "current_crm": "seguros"}},
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "create_seguro")
        self.assertEqual(str(result["action_payload"].get("cliente_id") or ""), "csegctx")
        self.assertEqual(str(result["action_payload"].get("compania") or ""), "Mapfre")
        self.assertEqual(str(result["action_payload"].get("poliza_numero") or ""), "PX-1")

    def test_internal_copilot_run_catalog_process_autofills_open_rrhh_document(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, fecha_caducidad, estado, created_at, updated_at
            ) VALUES (
              'rd-auto-1', 'ws1', 'e1', 'p1', 'DNI', 'dni.pdf', '2026-12-31', 'Activo', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_catalog_process",
            {
                "process_id": "rrhh_document_update",
                "context": {
                    "current_rrhh_document_id": "rd-auto-1",
                    "current_persona_id": "p1",
                    "current_crm": "rrhh",
                    "attachments": [{"key": "rrhh/new-dni.pdf", "public_url": "", "filename": "dni-nuevo.pdf", "content_type": "application/pdf"}],
                },
            },
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-21T09:25:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["delegated_action"], "update_current_rrhh_document")
        post_actions = result.get("post_actions") or []
        self.assertTrue(post_actions)
        self.assertEqual(post_actions[0]["post_endpoint"], "/api/workspace_rrhh_documento")

    def test_internal_copilot_run_catalog_process_autofills_open_community(self):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO workspace_fincas_comunidades (
              id, workspace_id, empresa_id, nombre, direccion, estado, presidente, secretario, cuota_sugerida, cuota_mensual, created_at, updated_at
            ) VALUES (
              'fc-auto-1', 'ws1', 'e1', 'Comunidad Auto', 'Calle Auto 1', 'Activa', 'Pedro', 'Ana', 145, 120, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_catalog_process",
            {"process_id": "community_update", "context": {"current_community_id": "fc-auto-1", "current_crm": "fincas"}},
            empresa_id="e1",
            actor={"user_id": "u1", "usuario": "QA"},
            now="2026-06-21T09:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["delegated_action"], "update_current_community")

    def test_internal_copilot_prepare_catalog_process_autofills_open_renta_entry(self):
        self.conn.execute("INSERT INTO clientes (id, nombre, nif, email, created_at, updated_at) VALUES ('crenta1', 'Cliente Renta Visible', '23232323A', 'crenta@test.local', 'now', 'now')")
        self.conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at
            ) VALUES (
              'cgrenta1', 'crenta1', 'Particular', 0, 0, 0, 1, 0, 0, 0,
              '{"entries":[{"id":"rent-entry-1","ejercicio":"2024","doc_key":"rentas/existente.pdf","estado_presentacion":"Borrador"}]}',
              'now', 'now'
            )
            """
        )
        result = server._workspace_internal_copilot_prepare_catalog_process(
            self.conn,
            "ws1",
            "e1",
            "renta_attach",
            {"context": {"current_client_id": "crenta1", "current_renta_entry_id": "rent-entry-1", "current_crm": "gestoria"}},
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "update_current_renta")
        self.assertEqual(str(result["action_payload"].get("entry_id") or ""), "rent-entry-1")
        self.assertEqual(str(result["action_payload"].get("ejercicio") or ""), "2024")

    def test_internal_copilot_prepare_catalog_process_autofills_open_factura(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tipo, numero, fecha_emision, base_imponible, total, doc_key, created_at, updated_at
            ) VALUES (
              'f-auto-1', 'e1', 'c71', 'compra', 'F-AUTO-1', '2026-06-10', 100, 121, 'facturas/existente.pdf', 'now', 'now'
            )
            """
        )
        result = server._workspace_internal_copilot_prepare_catalog_process(
            self.conn,
            "ws1",
            "e1",
            "factura_ocr",
            {"context": {"current_factura_id": "f-auto-1", "current_crm": "gestoria"}},
            actor={"user_id": "u1", "usuario": "QA"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action_id"], "update_current_factura_validate")
        self.assertEqual(str((result["action_payload"].get("patch") or {}).get("numero") or ""), "F-AUTO-1")

    def test_internal_copilot_close_loop_safe_stores_memory(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-loop-1', 'e1', 'Juan Cliente', 'c1', 'Santander', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "close_loop_safe",
            {"scope": "today", "crm": "fin", "copilot_mode": "operator"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T12:30:00Z",
        )
        self.assertTrue(result["ok"])
        rows = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_memory WHERE workspace_id = 'ws1' AND memory_type = 'close_loop' ORDER BY created_at DESC LIMIT 1"
        ).fetchall()
        self.assertTrue(rows)
        self.assertIn("Ciclo cerrado", str(rows[0]["content"] or ""))

    def test_internal_copilot_reply_mode_legal(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué hago ahora en legal",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA", "rol": "Lectura", "servicio": "Seguros"},
            context={"copilot_mode": "legal", "current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["mode"], "legal")
        self.assertTrue(any(str(card.get("title") or "") == "Legal senior" for card in (reply.get("cards") or [])))

    def test_internal_copilot_reply_mode_fiscal(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gestoria_facturas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              numero TEXT,
              fecha_emision TEXT,
              total REAL,
              cliente_id TEXT,
              estado_asiento TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gestoria_modelos (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              modelo TEXT,
              periodicidad TEXT,
              proxima_fecha TEXT,
              responsable TEXT,
              estado TEXT,
              notas TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute("INSERT INTO gestoria_facturas (id, empresa_id, numero, fecha_emision, total, cliente_id, created_at, updated_at) VALUES ('fac-fiscal-1','e1','F-10','2026-06-19',1200,'c1','now','now')")
        self.conn.execute("INSERT INTO gestoria_modelos (id, cliente_id, modelo, periodicidad, proxima_fecha, responsable, estado, notas, created_at, updated_at) VALUES ('mod-fiscal-1','c1','111','trimestral','2026-06-30','QA','Pendiente','', 'now','now')")
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué hago ahora con fiscal y contabilidad",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA", "rol": "Fiscalista", "servicio": "Gestoría"},
            context={"copilot_mode": "fiscal", "current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["mode"], "fiscal")
        self.assertTrue(any(str(card.get("title") or "") == "Fiscal-contable" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Criterio experto" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Riesgo y recomendación" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Fiscal-contable" for card in (reply.get("cards") or [])))

    def test_internal_copilot_reply_mode_laboral(self):
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, fecha_emision, fecha_caducidad, permanente, estado, notas, created_at, updated_at
            ) VALUES (
              'doc-lab-1', 'ws1', 'e1', 'p1', 'Contrato', 'Contrato base', '2026-01-01', '2026-06-01', 0, 'Activo', '', 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué hago ahora con rrhh y laboral",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA", "rol": "RRHH", "servicio": "RRHH"},
            context={"copilot_mode": "laboral", "current_crm": "rrhh"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["mode"], "laboral")
        self.assertTrue(any(str(card.get("title") or "") == "Laboral/RRHH" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Criterio experto" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Riesgo y recomendación" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Laboral/RRHH" for card in (reply.get("cards") or [])))

    def test_internal_copilot_agent_mode_appendix_exposes_expert_rules(self):
        legal_text = server._workspace_internal_copilot_agent_mode_appendix("legal", "gestoria")
        fiscal_text = server._workspace_internal_copilot_agent_mode_appendix("fiscal", "gestoria")
        laboral_text = server._workspace_internal_copilot_agent_mode_appendix("laboral", "rrhh")
        self.assertIn("Legal senior", legal_text)
        self.assertIn("Fiscal-contable", fiscal_text)
        self.assertIn("Laboral/RRHH", laboral_text)

    def test_internal_copilot_expert_actions(self):
        fiscal = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "review_fiscal_expert",
            {"copilot_mode": "fiscal", "crm": "gestoria"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:47:00Z",
        )
        laboral = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "review_laboral_expert",
            {"copilot_mode": "laboral", "crm": "rrhh"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:48:00Z",
        )
        legal = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "review_legal_expert",
            {"copilot_mode": "legal", "crm": "gestoria"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:49:00Z",
        )
        self.assertTrue(fiscal["ok"])
        self.assertEqual(fiscal["mode"], "fiscal")
        self.assertTrue(any(str(card.get("title") or "") == "Riesgo y recomendación" for card in (fiscal.get("cards") or [])))
        self.assertTrue(laboral["ok"])
        self.assertEqual(laboral["mode"], "laboral")
        self.assertTrue(any(str(card.get("title") or "") == "Riesgo y recomendación" for card in (laboral.get("cards") or [])))
        self.assertTrue(legal["ok"])
        self.assertEqual(legal["mode"], "legal")
        self.assertTrue(any(str(card.get("title") or "") == "Riesgo y recomendación" for card in (legal.get("cards") or [])))

    def test_internal_copilot_create_specialist_tasks(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gestoria_facturas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              numero TEXT,
              fecha_emision TEXT,
              total REAL,
              cliente_id TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute("INSERT INTO gestoria_facturas (id, empresa_id, numero, fecha_emision, total, cliente_id, created_at, updated_at) VALUES ('fac-task-1','e1','F-20','2026-06-19',200,'c1','now','now')")
        self.conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, fecha_emision, fecha_caducidad, permanente, estado, notas, created_at, updated_at
            ) VALUES (
              'doc-task-1', 'ws1', 'e1', 'p1', 'Contrato', 'Contrato base', '2026-01-01', '2026-06-01', 0, 'Activo', '', 'now', 'now'
            )
            """
        )
        fiscal = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "create_fiscal_expert_tasks",
            {"copilot_mode": "fiscal"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:50:00Z",
        )
        laboral = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "create_laboral_expert_tasks",
            {"copilot_mode": "laboral"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:51:00Z",
        )
        self.assertTrue(fiscal["ok"])
        self.assertGreaterEqual(int(fiscal.get("created") or 0), 0)
        self.assertTrue(laboral["ok"])
        self.assertGreaterEqual(int(laboral.get("created") or 0), 1)

    def test_internal_copilot_run_operator_sequence(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-op-1', 'e1', 'Juan Cliente', 'c1', 'BBVA', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_operator_sequence",
            {"crm": "fin", "copilot_mode": "operator"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "operator")
        self.assertIn("Secuencia operativa ejecutada", result["message"])
        self.assertTrue(any(str(item.get("id") or "") in {"start_review_queue", "close_loop_safe"} for item in (result.get("actions") or [])))
        self.assertIsNotNone(result.get("navigation"))
        self.assertTrue(any(str(card.get("title") or "") == "Plan operativo elegido" for card in (result.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_domain_microflow" for action in (result.get("actions") or [])))
        decision_rows = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_memory WHERE workspace_id = 'ws1' AND memory_type = 'decision' ORDER BY created_at DESC LIMIT 1"
        ).fetchall()
        self.assertTrue(decision_rows)
        self.assertIn("Decisión operativa", str(decision_rows[0]["title"] or ""))

    def test_internal_copilot_director_briefing_action(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gestoria_facturas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              numero TEXT,
              fecha_emision TEXT,
              total REAL,
              cliente_id TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tomador TEXT,
              compania TEXT,
              poliza_numero TEXT,
              comision REAL,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              comision REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute("INSERT INTO gestoria_facturas (id, empresa_id, numero, fecha_emision, total, cliente_id, created_at, updated_at) VALUES ('fac-dir-1','e1','F-1','2026-06-19',1200,'c1','now','now')")
        self.conn.execute("INSERT INTO seguros (id, empresa_id, cliente_id, tomador, compania, poliza_numero, comision, created_at, updated_at) VALUES ('seg-dir-1','e1','c1','Juan','Mapfre','P-1',250,'now','now')")
        self.conn.execute("INSERT INTO hipotecas (id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, comision, estado, created_at, updated_at) VALUES ('hip-dir-1','e1','Juan','c1','BBVA',100000,80000,900,'Pendiente','now','now')")
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-dir-1', 'ws1', 'e1', 'gestoria', 'gestoria_factura', 'gestoria_factura', 'fac-dir-1', '',
              '', 'failed', 'error', 'Factura sin asiento', 'Impacto económico alto', '[]', '[]', '{}',
              'dir-1', 0, NULL, 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "director_morning_briefing",
            {"copilot_mode": "direccion", "crm": "gestoria"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA", "rol": "Dirección"},
            now="2026-06-19T08:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "direccion")
        self.assertTrue(result["cards"])
        self.assertTrue(any("Pulso económico" == str(card.get("title") or "") for card in (result.get("cards") or [])))
        self.assertTrue(any("Asistente hoy" == str(card.get("title") or "") for card in (result.get("cards") or [])))
        self.assertTrue(any("Aprendizaje del asistente" == str(card.get("title") or "") for card in (result.get("cards") or [])))
        self.assertTrue(any("Estrategias dominantes" == str(card.get("title") or "") for card in (result.get("cards") or [])))

    def test_internal_copilot_set_copilot_mode_accepts_fiscal_and_laboral(self):
        fiscal = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "set_copilot_mode",
            {"mode": "fiscal", "domain": "gestoria"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:45:00Z",
        )
        laboral = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "set_copilot_mode",
            {"mode": "laboral", "domain": "rrhh"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T08:46:00Z",
        )
        self.assertEqual((fiscal.get("mode_switch") or {}).get("mode"), "fiscal")
        self.assertEqual((laboral.get("mode_switch") or {}).get("mode"), "laboral")

    def test_internal_copilot_promote_legal_updates_to_tasks(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_radar_items (
              id TEXT PRIMARY KEY,
              area TEXT,
              fuente TEXT,
              referencia TEXT,
              titulo TEXT,
              fecha_publicacion TEXT,
              estado TEXT,
              impacto TEXT,
              topic_key TEXT,
              url TEXT,
              resumen TEXT,
              accion_recomendada TEXT,
              affected_documents TEXT,
              affected_workflows TEXT,
              affected_clauses TEXT,
              impact_score REAL,
              llm_impact_summary TEXT,
              llm_actions_json TEXT,
              llm_confidence REAL,
              llm_review_needed INTEGER,
              reviewed_at TEXT,
              reviewed_by TEXT,
              applied_at TEXT,
              source_key TEXT,
              matched_keywords TEXT,
              auto_detected INTEGER,
              knowledge_synced_at TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO legal_radar_items (
              id, area, fuente, referencia, titulo, fecha_publicacion, estado, impacto,
              topic_key, url, resumen, accion_recomendada, affected_documents, affected_workflows,
              affected_clauses, impact_score, llm_impact_summary, llm_actions_json,
              llm_confidence, llm_review_needed, reviewed_at, reviewed_by,
              applied_at, source_key, matched_keywords, auto_detected, knowledge_synced_at,
              created_at, updated_at
            ) VALUES (
              'lr-1', 'gestoria', 'BOE', 'REF-1', 'Cambio fiscal relevante', '2026-06-19', 'Pendiente', 'Alto',
              'consultas_hacienda', 'https://example.com', 'Resumen fiscal', 'Revisar plantillas', '["Checklist fiscal"]', '["Revisión de modelos"]',
              '[]', 0.9, 'Afecta a flujos de gestoría', '[]',
              0.8, 0, NULL, NULL,
              NULL, 'boe', '[]', 1, NULL,
              'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "promote_legal_updates_to_tasks",
            {"area": "gestoria", "copilot_mode": "legal"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T09:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "legal")
        tasks = self.conn.execute("SELECT * FROM workspace_internal_copilot_tasks WHERE source = 'legal_radar'").fetchall()
        self.assertTrue(tasks)
        self.assertTrue(any("Plantillas:" in str(card.get("summary") or "") for card in (result.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "open_module" for action in (result.get("actions") or [])))

    def test_internal_copilot_reply_exposes_clone_profile_without_ollama(self):
        old_ollama_available = server.ollama_available
        try:
            server.ollama_available = lambda: False
            reply = server.build_workspace_internal_copilot_reply(
                self.conn,
                "ws1",
                "qué hago ahora",
                empresa_id="e1",
                actor={"id": "u1", "usuario": "QA"},
                context={},
            )
        finally:
            server.ollama_available = old_ollama_available
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["assistant_profile"], "codex_clone_v1")
        self.assertEqual(reply["assistant_style"], "pragmatic_operator")
        self.assertFalse(reply["llm_refined"])

    def test_internal_copilot_reply_refines_with_ollama_plan_and_autonomy(self):
        old_ollama_available = server.ollama_available
        old_call_ollama_json = server.call_ollama_json
        try:
            server.ollama_available = lambda: True

            def fake_call_ollama_json(prompt, **kwargs):
                if "Refina la respuesta operativa de un asistente interno del CRM" in prompt:
                    return (
                        {
                            "answer": "Empieza por las hipotecas incompletas y luego cierra el bloque seguro pendiente.",
                            "plan": ["Revisar hipotecas sin importes base", "Lanzar cierre seguro", "Verificar el estado restante"],
                            "suggestions": ["Operar ahora", "Cerrar ciclo", "Bandeja unificada"],
                            "risk_flags": ["Si faltan importes base, no cierres el expediente sin revisar ficha"],
                            "autonomy_level": "revisar_lote",
                        },
                        "",
                    )
                return ({}, "sin respuesta")

            server.call_ollama_json = fake_call_ollama_json
            reply = server.build_workspace_internal_copilot_reply(
                self.conn,
                "ws1",
                "qué hago ahora",
                empresa_id="e1",
                actor={"id": "u1", "usuario": "QA"},
                context={"current_crm": "fin"},
            )
        finally:
            server.ollama_available = old_ollama_available
            server.call_ollama_json = old_call_ollama_json
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["llm_refined"])
        self.assertEqual(reply["assistant_profile"], "codex_clone_v1")
        self.assertEqual(reply["autonomy_level"], "revisar_lote")
        self.assertTrue(any(str(card.get("title") or "") == "Plan corto" for card in (reply.get("cards") or [])))
        self.assertIn("Operar ahora", list(reply.get("suggestions") or []))
        self.assertTrue(reply.get("risk_flags"))

    def test_internal_copilot_choose_operator_actions_uses_ollama_choice(self):
        old_ollama_available = server.ollama_available
        old_call_ollama_json = server.call_ollama_json
        try:
            server.ollama_available = lambda: True

            def fake_call_ollama_json(prompt, **kwargs):
                if "Elige la mejor secuencia operativa para un asistente interno del CRM" in prompt:
                    return (
                        {
                            "safe_action_id": "bulk_revalidate_missing_hipotecas",
                            "guided_action_id": "start_review_queue",
                            "followup_action_id": "autorreview_domain",
                            "rationale": "Primero cierro lo seguro del dominio y luego paso a revisión guiada.",
                        },
                        "",
                    )
                return ({}, "sin respuesta")

            server.call_ollama_json = fake_call_ollama_json
            decision = server._workspace_internal_copilot_choose_operator_actions(
                self.conn,
                "ws1",
                domain="fin",
                cards=[{"title": "Hipotecas incompletas", "priority": "alta", "impact_area": "financiaciones"}],
                actions=[
                    {"id": "resolve_domain_safe", "label": "Resolver dominio"},
                    {"id": "bulk_revalidate_missing_hipotecas", "label": "Revalidar hipotecas"},
                    {"id": "start_review_queue", "label": "Revisión guiada"},
                    {"id": "autorreview_domain", "label": "Revisar dominio"},
                ],
                actor={"id": "u1", "usuario": "QA"},
                context={"current_crm": "fin"},
            )
        finally:
            server.ollama_available = old_ollama_available
            server.call_ollama_json = old_call_ollama_json
        self.assertEqual(str((decision.get("safe_action") or {}).get("id") or ""), "bulk_revalidate_missing_hipotecas")
        self.assertEqual(str((decision.get("guided_action") or {}).get("id") or ""), "start_review_queue")
        self.assertEqual(str((decision.get("followup_action") or {}).get("id") or ""), "autorreview_domain")
        self.assertEqual(decision.get("source"), "ollama")

    def test_internal_copilot_choose_operator_actions_uses_user_success_history(self):
        now = "2026-06-19T10:00:00Z"
        server._workspace_internal_copilot_log_event(
            self.conn,
            "ws1",
            "bulk_revalidate_missing_hipotecas",
            actor={"id": "u1", "usuario": "QA"},
            payload={"domain": "fin"},
            result={"updated": 2, "resolved": 2},
            now=now,
        )
        server._workspace_internal_copilot_log_event(
            self.conn,
            "ws1",
            "bulk_revalidate_missing_hipotecas",
            actor={"id": "u1", "usuario": "QA"},
            payload={"domain": "fin"},
            result={"updated": 1, "resolved": 1},
            now=now,
        )
        decision = server._workspace_internal_copilot_choose_operator_actions(
            self.conn,
            "ws1",
            domain="fin",
            cards=[{"title": "Hipotecas incompletas", "priority": "alta", "impact_area": "financiaciones"}],
            actions=[
                {"id": "resolve_domain_safe", "label": "Resolver dominio"},
                {"id": "bulk_revalidate_missing_hipotecas", "label": "Revalidar hipotecas"},
                {"id": "start_review_queue", "label": "Revisión guiada"},
            ],
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "fin"},
        )
        self.assertEqual(str((decision.get("safe_action") or {}).get("id") or ""), "bulk_revalidate_missing_hipotecas")
        self.assertTrue(len(list(decision.get("safe_queue") or [])) >= 1)

    def test_internal_copilot_action_run_domain_microflow_financiaciones(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, estado, created_at, updated_at
            ) VALUES (
              'hip-micro-1', 'e1', 'Juan Cliente', 'c1', 'BBVA', 0, 0, 'Pendiente', 'now', 'now'
            )
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_domain_microflow",
            {"domain": "financiaciones", "microflow_type": "hipotecas_incompletas"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:15:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "operator")
        self.assertEqual(result["microflow_type"], "hipotecas_incompletas")
        self.assertTrue(result.get("refresh_supervisor"))
        rows = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_memory WHERE workspace_id = 'ws1' AND title = 'Microflujo hipotecas_incompletas' ORDER BY created_at DESC LIMIT 1"
        ).fetchall()
        self.assertTrue(rows)

    def test_internal_copilot_operational_query_rrhh_docs_expired_includes_safe_resolution(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_rrhh_documentos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              nombre TEXT,
              fecha_caducidad TEXT,
              estado TEXT,
              permanente INTEGER
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspace_rrhh_documentos (id, workspace_id, persona_id, tipo, nombre, fecha_caducidad, estado, permanente) VALUES ('doc-safe-1','ws1','p1','DNI','DNI Juan','2026-01-01','caducado',0)"
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "revisa documentos rrhh caducados",
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            context={},
        )
        self.assertTrue(any(str(action.get("id") or "") == "resolve_domain_safe" for action in (reply.get("actions") or [])))

    def test_internal_copilot_action_resolve_domain_safe_rrhh(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_domain_safe",
            {"domain": "rrhh_docs_expired", "documento_ids": ["doc-rrhh-1"]},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:20:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], 1)

    def test_internal_copilot_action_resolve_domain_safe_fincas(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "resolve_domain_safe",
            {"domain": "fincas_communities_quota", "comunidad_ids": ["com-1"]},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:25:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], 1)

    def test_internal_copilot_action_run_domain_microflow_rrhh_autoreviews(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_rrhh_documentos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              nombre TEXT,
              fecha_caducidad TEXT,
              estado TEXT,
              permanente INTEGER
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspace_rrhh_documentos (id, workspace_id, persona_id, tipo, nombre, fecha_caducidad, estado, permanente) VALUES ('doc-micro-1','ws1','p1','DNI','DNI Juan','2026-01-01','caducado',0)"
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_domain_microflow",
            {"domain": "rrhh", "microflow_type": "documentos_rrhh_caducados"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:30:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["microflow_type"], "documentos_rrhh_caducados")
        self.assertTrue(result.get("refresh_supervisor"))
        self.assertTrue(any(str(card.get("title") or "") == "Microflujo ejecutado" for card in (result.get("cards") or [])))
        self.assertEqual(result.get("impact_area"), "laboral")
        self.assertTrue(str(result.get("task_id") or "").strip())
        rows = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchall()
        self.assertTrue(rows)

    def test_internal_copilot_action_run_domain_microflow_autocloses_when_clean(self):
        old_collect = server._workspace_internal_copilot_collect_domain_pending
        try:
            def fake_collect(conn, workspace_id, **kwargs):
                return [], [], ["fake_domain"]

            server._workspace_internal_copilot_collect_domain_pending = fake_collect
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "run_domain_microflow",
                {"domain": "rrhh", "microflow_type": "documentos_rrhh_caducados"},
                empresa_id="e1",
                actor={"id": "u1", "usuario": "QA"},
                now="2026-06-19T13:40:00Z",
            )
        finally:
            server._workspace_internal_copilot_collect_domain_pending = old_collect
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("auto_closed"))

    def test_internal_copilot_microflow_checklist_returns_steps(self):
        checklist = server._workspace_internal_copilot_microflow_checklist("hipotecas_incompletas")
        self.assertTrue(checklist)
        self.assertIn("Revisar hipotecas sin importes base", checklist[0])

    def test_internal_copilot_repeated_playbook_builds_card(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Microflujo hipotecas_incompletas",
            content="Primera pasada",
            meta={"microflow_type": "hipotecas_incompletas", "domain": "financiaciones"},
            now="2026-06-19T08:00:00Z",
        )
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Microflujo hipotecas_incompletas",
            content="Segunda pasada",
            meta={"microflow_type": "hipotecas_incompletas", "domain": "financiaciones"},
            now="2026-06-19T09:00:00Z",
        )
        cards = server._workspace_internal_copilot_repeated_playbook(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            limit=2,
        )
        self.assertTrue(cards)
        self.assertIn("Playbook vivo", str(cards[0]["title"]))

    def test_internal_copilot_microflow_detects_stuck_and_suggests_escalation(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Primera pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T08:00:00Z",
        )
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Segunda pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T09:00:00Z",
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_rrhh_documentos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              nombre TEXT,
              fecha_caducidad TEXT,
              estado TEXT,
              permanente INTEGER
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspace_rrhh_documentos (id, workspace_id, persona_id, tipo, nombre, fecha_caducidad, estado, permanente) VALUES ('doc-stuck-1','ws1','p1','DNI','DNI Juan','2026-01-01','caducado',0)"
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_domain_microflow",
            {"domain": "rrhh", "microflow_type": "documentos_rrhh_caducados"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:50:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("stuck_signal", {}).get("stuck"))
        self.assertTrue(any("Escalar a legal" == str(action.get("label") or "") for action in (result.get("actions") or [])))

    def test_internal_copilot_strategy_ranking_prioritizes_best_domain(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa gestoria",
            content="Resolución de facturas",
            meta={"domain": "gestoria", "resolved": 3, "updated": 3, "safe_action_id": "bulk_revalidate_facturas_without_asiento"},
            now="2026-06-19T08:00:00Z",
        )
        server._workspace_internal_copilot_log_event(
            self.conn,
            "ws1",
            "bulk_revalidate_facturas_without_asiento",
            actor={"id": "u1", "usuario": "QA"},
            payload={"domain": "gestoria"},
            result={"updated": 3, "resolved": 3},
            now="2026-06-19T08:05:00Z",
        )
        ranked = server._workspace_internal_copilot_strategy_ranking(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            limit=3,
        )
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["domain"], "gestoria")
        self.assertEqual(ranked[0]["best_action_id"], "bulk_revalidate_facturas_without_asiento")

    def test_internal_copilot_prime_operator_console_suggests_mode_switch_when_stuck(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Primera pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T08:00:00Z",
        )
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Segunda pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T09:00:00Z",
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_rrhh_documentos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              nombre TEXT,
              fecha_caducidad TEXT,
              estado TEXT,
              permanente INTEGER
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspace_rrhh_documentos (id, workspace_id, persona_id, tipo, nombre, fecha_caducidad, estado, permanente) VALUES ('doc-prime-rrhh-1','ws1','p1','DNI','DNI Juan','2026-01-01','caducado',0)"
        )
        reply = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prime_operator_console",
            {"current_crm": "rrhh", "service_hint": "rrhh", "copilot_mode": "operator"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T13:55:00Z",
        )
        self.assertTrue(reply["ok"])
        self.assertTrue(any(str(action.get("id") or "") == "set_copilot_mode" for action in (reply.get("actions") or [])))

    def test_internal_copilot_action_set_copilot_mode_returns_mode_switch(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "set_copilot_mode",
            {"mode": "legal", "domain": "rrhh", "reason": "Atasco sostenido en rrhh."},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T14:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("mode_switch", {}).get("mode"), "legal")
        self.assertEqual(result["action_id"], "set_copilot_mode")

    def test_internal_copilot_microflow_auto_switches_mode_on_high_impact_stuck(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Primera pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T07:00:00Z",
        )
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Segunda pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T08:00:00Z",
        )
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="decision",
            title="Decisión operativa rrhh",
            content="Tercera pasada sin resolución",
            meta={"domain": "rrhh", "resolved": 0},
            now="2026-06-19T09:00:00Z",
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_rrhh_documentos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT,
              tipo TEXT,
              nombre TEXT,
              fecha_caducidad TEXT,
              estado TEXT,
              permanente INTEGER
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspace_rrhh_documentos (id, workspace_id, persona_id, tipo, nombre, fecha_caducidad, estado, permanente) VALUES ('doc-auto-switch-1','ws1','p1','DNI','DNI Juan','2026-01-01','caducado',0)"
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "run_domain_microflow",
            {"domain": "rrhh", "microflow_type": "documentos_rrhh_caducados"},
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-19T14:10:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual((result.get("mode_switch") or {}).get("mode"), "legal")
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(meta.get("assigned_mode"), "legal")

    def test_internal_copilot_codefix_reply_prepares_plan(self):
        self.conn.execute(
            """
            INSERT INTO workspace_process_supervisor (
              id, workspace_id, empresa_id, servicio, process_type, entity_type, entity_id, actor_user_id,
              actor_label, status, severity, title, summary, anomaly_json, actions_json, llm_payload,
              dedupe_key, acknowledged, acknowledged_at, created_at, updated_at
            ) VALUES (
              'evt-code-1', 'ws1', 'e1', 'gestoria', 'gestoria_factura', 'gestoria_factura', 'fac-1', '',
              '', 'failed', 'error', 'Factura sin asiento', 'Impacto económico alto', '[]', '[]', '{}',
              'code-1', 0, NULL, 'now', 'now'
            )
            """
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "arregla el código de gestoría y prepara un parche",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "code_autofix")
        self.assertTrue(any(str(action.get("id") or "") == "prepare_code_autofix_task" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "prepare_code_autofix_bundle" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "validate_code_autofix_bundle" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "materialize_code_autofix_bundle" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "apply_code_autofix_bundle" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Diff propuesto" for card in (reply.get("cards") or [])))

    def test_internal_copilot_implementation_reply_prepares_options(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "implementa una mejora en gestoría para que el flujo de facturas sea más consistente",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "implementation_plan")
        self.assertTrue(any(str(action.get("id") or "") == "prepare_implementation_task" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "prepare_architecture_decision" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_implementation_session" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Enfoque recomendado" for card in (reply.get("cards") or [])))

    def test_internal_copilot_architecture_reply_prepares_decision(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué enfoque de arquitectura conviene para mejorar gestoría sin abrir demasiado alcance",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "architecture_decision")
        self.assertTrue(any(str(action.get("id") or "") == "prepare_architecture_decision" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Decisión técnica recomendada" for card in (reply.get("cards") or [])))

    def test_internal_copilot_cross_layer_reply_prepares_transversal_review(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "tenemos un cambio complejo en gestoría que afecta backend y frontend y varias capas",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "cross_layer_review")
        self.assertTrue(any(str(action.get("id") or "") == "prepare_cross_layer_decision" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "prepare_delivery_review" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "run_implementation_session" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Capas afectadas" for card in (reply.get("cards") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Checklist de cierre" for card in (reply.get("cards") or [])))

    def test_internal_copilot_discovery_reply_prepares_ambiguous_change_review(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "esto esta mal planteado en gestoria, investiga el problema raro y reorganiza el flujo",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "discovery_review")
        self.assertTrue(any(str(action.get("id") or "") == "prepare_discovery_review" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "prepare_cross_layer_decision" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Evidencia mínima" for card in (reply.get("cards") or [])))

    def test_internal_copilot_strategy_reply_compares_fix_containment_and_redesign(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué estrategia conviene en gestoría, parche o rediseño",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "strategy_review")
        self.assertTrue(any(str(action.get("id") or "") == "prepare_strategy_review" for action in (reply.get("actions") or [])))
        self.assertTrue(any(str(card.get("title") or "") == "Estrategia recomendada" for card in (reply.get("cards") or [])))

    def test_internal_copilot_strategy_reply_uses_learning_when_available(self):
        server._workspace_internal_copilot_store_memory_note(
            self.conn,
            "ws1",
            actor={"id": "u1", "usuario": "QA"},
            memory_type="implementation_session",
            title="Sesion previa",
            content="Cambio cerrado",
            priority="media",
            meta={
                "domain": "gestoria",
                "status": "passed",
                "strategy_id": "safe_containment",
                "inspection": {"status": "clean"},
            },
            now="2026-06-21T09:00:00Z",
        )
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "qué estrategia conviene en gestoría, parche o rediseño",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "strategy_review")
        self.assertTrue(any(str(card.get("title") or "") == "Aprendizaje aplicado" for card in (reply.get("cards") or [])))

    def test_internal_copilot_action_prepare_code_autofix_task_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_code_autofix_task",
            {
                "plan": {
                    "domain": "gestoria",
                    "assigned_mode": "supervisor",
                    "risk_level": "high",
                    "diagnosis": "Fallo en flujo de factura sin asiento.",
                    "patch_outline": ["corregir handler", "añadir test de regresión"],
                    "probable_files": ["web/server.py", "web/app.js"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:00:00Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertEqual(meta.get("assigned_mode"), "supervisor")
        self.assertIn("*** Begin Patch", str(meta.get("proposed_diff") or ""))
        self.assertIn("Ficheros probables", str(meta.get("patch_prompt") or ""))
        self.assertTrue(list(meta.get("validation_commands") or []))

    def test_internal_copilot_action_prepare_implementation_task_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_implementation_task",
            {
                "plan": {
                    "domain": "gestoria",
                    "assigned_mode": "supervisor",
                    "diagnosis": "Implementar mejora de consistencia en gestoría.",
                    "patch_outline": ["corregir flujo", "añadir test"],
                    "probable_files": ["web/server.py", "web/app.js"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                    "implementation_options": [{"id": "balanced", "title": "Implementación equilibrada"}],
                    "recommended_option": {"id": "balanced", "title": "Implementación equilibrada"},
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:02:00Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(task["source"], "implementation_plan")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertTrue(list(meta.get("implementation_options") or []))

    def test_internal_copilot_action_prepare_architecture_decision_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_architecture_decision",
            {
                "plan": {
                    "domain": "gestoria",
                    "decision": "Usar una implementación equilibrada para no abrir demasiado alcance.",
                    "alternatives": [{"id": "minimal", "title": "Ajuste mínimo"}],
                    "recommended_option": {"id": "balanced", "title": "Implementación equilibrada"},
                    "risks": ["tocar demasiadas capas a la vez"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:03:00Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(task["source"], "architecture_review")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertTrue(list(meta.get("alternatives") or []))

    def test_internal_copilot_action_prepare_cross_layer_decision_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_cross_layer_decision",
            {
                "plan": {
                    "domain": "gestoria",
                    "decision": "Cambio transversal en gestoría con backend, frontend y tests.",
                    "layers": [{"id": "backend", "title": "Backend"}, {"id": "frontend", "title": "Frontend"}],
                    "recommended_order": ["Backend", "Frontend", "Tests"],
                    "probable_files": ["web/server.py", "web/app.js"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                    "risks": ["abrir demasiado alcance"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:03:30Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(task["source"], "cross_layer_review")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertTrue(list(meta.get("layers") or []))
        self.assertTrue(list(meta.get("recommended_order") or []))

    def test_internal_copilot_action_prepare_delivery_review_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_delivery_review",
            {
                "plan": {
                    "domain": "gestoria",
                    "decision": "Cambio transversal en gestoría con cierre dirigido.",
                    "dimensions": [{"id": "product", "title": "Producto"}, {"id": "ux", "title": "UX"}],
                    "delivery_checklist": ["validar backend", "revisar pantalla", "ejecutar tests"],
                    "cross_layer": True,
                    "probable_files": ["web/server.py"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:03:40Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(task["source"], "delivery_review")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertTrue(list(meta.get("delivery_checklist") or []))
        self.assertTrue(list(meta.get("dimensions") or []))

    def test_internal_copilot_action_prepare_discovery_review_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_discovery_review",
            {
                "plan": {
                    "domain": "gestoria",
                    "decision": "Discovery técnico antes de abrir un cambio amplio.",
                    "hypotheses": [{"id": "scope_mismatch", "title": "Alcance mal delimitado"}],
                    "evidence": ["localizar flujo", "acotar backend y frontend"],
                    "execution_path": ["descubrir origen", "decidir enfoque", "preparar bundle"],
                    "probable_files": ["web/server.py"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:03:45Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(task["source"], "discovery_review")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertTrue(list(meta.get("hypotheses") or []))
        self.assertTrue(list(meta.get("evidence") or []))
        self.assertTrue(list(meta.get("execution_path") or []))

    def test_internal_copilot_action_prepare_strategy_review_creates_task(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_strategy_review",
            {
                "plan": {
                    "domain": "gestoria",
                    "decision": "Conviene empezar por arreglo dirigido.",
                    "strategy_options": [{"id": "targeted_fix", "title": "Arreglo dirigido"}],
                    "recommended_strategy": {"id": "targeted_fix", "title": "Arreglo dirigido"},
                    "probable_files": ["web/server.py"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:03:47Z",
        )
        self.assertTrue(result["ok"])
        task = self.conn.execute(
            "SELECT * FROM workspace_internal_copilot_tasks WHERE id = ?",
            (str(result.get("task_id") or "").strip(),),
        ).fetchone()
        self.assertIsNotNone(task)
        meta = server._safe_json_object(task["meta_json"] or "{}")
        self.assertEqual(task["source"], "strategy_review")
        self.assertEqual(meta.get("domain"), "gestoria")
        self.assertTrue(list(meta.get("strategy_options") or []))
        self.assertEqual((meta.get("recommended_strategy") or {}).get("id"), "targeted_fix")
        self.assertEqual(meta.get("recommended_strategy_id"), "targeted_fix")

    def test_internal_copilot_action_run_implementation_session(self):
        old_root = server._workspace_internal_copilot_codefix_root
        old_generate = server._workspace_internal_copilot_generate_codefix_edits
        old_validate = server._workspace_internal_copilot_run_validation_bundle
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                target = root / "sample_module.py"
                target.write_text("value = 1\n", encoding="utf-8")
                server._workspace_internal_copilot_codefix_root = lambda: root
                server._workspace_internal_copilot_generate_codefix_edits = lambda bundle: {
                    "status": "ready",
                    "summary": "Cambio exacto listo.",
                    "edits": [{"file": "sample_module.py", "find": "value = 1", "replace": "value = 2", "reason": "Ajuste"}],
                }
                server._workspace_internal_copilot_run_validation_bundle = lambda bundle: {
                    "status": "passed",
                    "steps": [{"command": "python3 -m py_compile sample_module.py", "status": "passed"}],
                }
                result = server.perform_workspace_internal_copilot_action(
                    self.conn,
                    "ws1",
                    "run_implementation_session",
                    {
                        "plan": {
                            "domain": "gestoria",
                            "assigned_mode": "supervisor",
                            "diagnosis": "Implementar mejora de consistencia en gestoría.",
                            "patch_outline": ["corregir valor"],
                            "probable_files": ["sample_module.py"],
                            "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                            "dimensions": [{"id": "product", "title": "Producto"}, {"id": "ux", "title": "UX"}],
                            "delivery_checklist": ["validar backend", "revisar pantalla", "ejecutar tests"],
                        }
                    },
                    empresa_id="e1",
                    actor={"id": "u1", "usuario": "QA"},
                    now="2026-06-21T10:04:00Z",
                )
                self.assertTrue(result["ok"])
                self.assertEqual((result.get("apply_result") or {}).get("status"), "passed")
                self.assertTrue(Path(str((result.get("apply_result") or {}).get("session_summary_path") or "")).exists())
                self.assertTrue(any(str(card.get("title") or "") == "Impacto de entrega" for card in (result.get("cards") or [])))
                self.assertTrue(any(str(card.get("title") or "") == "Siguiente validación de cierre" for card in (result.get("cards") or [])))
                self.assertTrue(any(str(card.get("title") or "") == "Inspección posterior" for card in (result.get("cards") or [])))
                self.assertTrue(any(str(card.get("title") or "") == "Siguiente paso exacto" for card in (result.get("cards") or [])))
                self.assertTrue(any(str(action.get("id") or "") == "autorreview_domain" for action in (result.get("actions") or [])))
                self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")
        finally:
            server._workspace_internal_copilot_codefix_root = old_root
            server._workspace_internal_copilot_generate_codefix_edits = old_generate
            server._workspace_internal_copilot_run_validation_bundle = old_validate

    def test_internal_copilot_action_run_implementation_session_opens_discovery_on_failed_validation(self):
        old_root = server._workspace_internal_copilot_codefix_root
        old_generate = server._workspace_internal_copilot_generate_codefix_edits
        old_validate = server._workspace_internal_copilot_run_validation_bundle
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                target = root / "sample_module.py"
                target.write_text("value = 1\n", encoding="utf-8")
                server._workspace_internal_copilot_codefix_root = lambda: root
                server._workspace_internal_copilot_generate_codefix_edits = lambda bundle: {
                    "status": "ready",
                    "summary": "Cambio exacto listo.",
                    "edits": [{"file": "sample_module.py", "find": "value = 1", "replace": "value = 2", "reason": "Ajuste"}],
                }
                server._workspace_internal_copilot_run_validation_bundle = lambda bundle: {
                    "status": "failed",
                    "steps": [{"command": "python3 -m py_compile sample_module.py", "status": "failed", "detail": "syntax error"}],
                }
                result = server.perform_workspace_internal_copilot_action(
                    self.conn,
                    "ws1",
                    "run_implementation_session",
                    {
                        "plan": {
                            "domain": "gestoria",
                            "assigned_mode": "supervisor",
                            "diagnosis": "Implementar mejora compleja en gestoría.",
                            "patch_outline": ["corregir valor"],
                            "probable_files": ["sample_module.py"],
                            "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                        }
                    },
                    empresa_id="e1",
                    actor={"id": "u1", "usuario": "QA"},
                    now="2026-06-21T10:04:30Z",
                )
                self.assertTrue(result["ok"])
                self.assertEqual((result.get("apply_result") or {}).get("status"), "failed")
                self.assertTrue(any(str(card.get("title") or "") == "Inspección posterior" for card in (result.get("cards") or [])))
                self.assertTrue(any(str(card.get("title") or "") == "Siguiente paso exacto" for card in (result.get("cards") or [])))
                self.assertTrue(any(str(action.get("id") or "") == "prepare_discovery_review" for action in (result.get("actions") or [])))
        finally:
            server._workspace_internal_copilot_codefix_root = old_root
            server._workspace_internal_copilot_generate_codefix_edits = old_generate
            server._workspace_internal_copilot_run_validation_bundle = old_validate

    def test_internal_copilot_action_prepare_code_autofix_bundle_returns_commands(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "prepare_code_autofix_bundle",
            {
                "plan": {
                    "domain": "gestoria",
                    "assigned_mode": "supervisor",
                    "diagnosis": "Fallo en flujo de factura sin asiento.",
                    "patch_outline": ["corregir handler", "añadir test de regresión"],
                    "probable_files": ["web/server.py", "web/app.js"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py", "tests/test_frontend_smoke.py"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:05:00Z",
        )
        self.assertTrue(result["ok"])
        bundle = result.get("bundle") or {}
        self.assertIn("copilot-fix/gestoria-", str(bundle.get("branch_name") or ""))
        self.assertTrue(list(bundle.get("validation_commands") or []))
        self.assertIn("*** Begin Patch", str(bundle.get("proposed_diff") or ""))
        self.assertTrue(list(bundle.get("code_context") or []))
        self.assertIsInstance(bundle.get("code_targets"), list)
        self.assertTrue(list(bundle.get("validation_focus") or []))

    def test_internal_copilot_action_validate_code_autofix_bundle_reports_status(self):
        old_runner = server._workspace_internal_copilot_run_validation_bundle
        try:
            server._workspace_internal_copilot_run_validation_bundle = lambda bundle: {
                "status": "passed",
                "steps": [{"command": "python3 -m py_compile web/server.py", "status": "passed"}],
            }
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "validate_code_autofix_bundle",
                {
                    "plan": {
                        "domain": "gestoria",
                        "assigned_mode": "supervisor",
                        "diagnosis": "Fallo en flujo de factura sin asiento.",
                        "patch_outline": ["corregir handler"],
                        "probable_files": ["web/server.py"],
                        "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                    }
                },
                empresa_id="e1",
                actor={"id": "u1", "usuario": "QA"},
                now="2026-06-21T10:10:00Z",
            )
        finally:
            server._workspace_internal_copilot_run_validation_bundle = old_runner
        self.assertTrue(result["ok"])
        self.assertEqual((result.get("validation") or {}).get("status"), "passed")

    def test_internal_copilot_action_materialize_code_autofix_bundle_writes_artifacts(self):
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "materialize_code_autofix_bundle",
            {
                "plan": {
                    "domain": "gestoria",
                    "assigned_mode": "supervisor",
                    "diagnosis": "Fallo en flujo de factura sin asiento.",
                    "patch_outline": ["corregir handler", "añadir test de regresión"],
                    "probable_files": ["web/server.py", "web/app.js"],
                    "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                }
            },
            empresa_id="e1",
            actor={"id": "u1", "usuario": "QA"},
            now="2026-06-21T10:15:00Z",
        )
        self.assertTrue(result["ok"])
        artifacts = result.get("artifacts") or {}
        self.assertTrue(str(artifacts.get("artifact_dir") or "").strip())
        self.assertTrue(Path(str(artifacts.get("bundle_path") or "")).exists())
        self.assertTrue(Path(str(artifacts.get("context_path") or "")).exists())
        self.assertTrue(Path(str(artifacts.get("targets_path") or "")).exists())

    def test_internal_copilot_action_apply_code_autofix_bundle_updates_file_and_validates(self):
        old_root = server._workspace_internal_copilot_codefix_root
        old_generate = server._workspace_internal_copilot_generate_codefix_edits
        old_validate = server._workspace_internal_copilot_run_validation_bundle
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                target = root / "sample_module.py"
                target.write_text("value = 1\n", encoding="utf-8")
                server._workspace_internal_copilot_codefix_root = lambda: root
                server._workspace_internal_copilot_generate_codefix_edits = lambda bundle: {
                    "status": "ready",
                    "summary": "Cambio exacto listo.",
                    "edits": [
                        {
                            "file": "sample_module.py",
                            "find": "value = 1",
                            "replace": "value = 2",
                            "reason": "Ajustar valor de prueba",
                        }
                    ],
                }
                server._workspace_internal_copilot_run_validation_bundle = lambda bundle: {
                    "status": "passed",
                    "steps": [{"command": "python3 -m py_compile sample_module.py", "status": "passed"}],
                }
                result = server.perform_workspace_internal_copilot_action(
                    self.conn,
                    "ws1",
                    "apply_code_autofix_bundle",
                    {
                        "plan": {
                            "domain": "gestoria",
                            "assigned_mode": "supervisor",
                            "diagnosis": "Fallo en flujo de factura sin asiento.",
                            "patch_outline": ["corregir valor"],
                            "probable_files": ["sample_module.py"],
                            "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                        }
                    },
                    empresa_id="e1",
                    actor={"id": "u1", "usuario": "QA"},
                    now="2026-06-21T10:20:00Z",
                )
                self.assertTrue(result["ok"])
                self.assertEqual((result.get("apply_result") or {}).get("status"), "passed")
                self.assertEqual((result.get("apply_result") or {}).get("attempts_count"), 1)
                self.assertEqual((result.get("apply_result") or {}).get("validation_bundle", {}).get("probable_files"), ["sample_module.py"])
                self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")
                self.assertTrue(Path(str((result.get("apply_result") or {}).get("session_summary_path") or "")).exists())
        finally:
            server._workspace_internal_copilot_codefix_root = old_root
            server._workspace_internal_copilot_generate_codefix_edits = old_generate
            server._workspace_internal_copilot_run_validation_bundle = old_validate

    def test_internal_copilot_action_apply_code_autofix_bundle_retries_after_failed_validation(self):
        old_root = server._workspace_internal_copilot_codefix_root
        old_generate = server._workspace_internal_copilot_generate_codefix_edits
        old_validate = server._workspace_internal_copilot_run_validation_bundle
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                target = root / "sample_module.py"
                target.write_text("value = 1\n", encoding="utf-8")
                server._workspace_internal_copilot_codefix_root = lambda: root
                edits_queue = [
                    {
                        "status": "ready",
                        "summary": "Primer intento.",
                        "edits": [{"file": "sample_module.py", "find": "value = 1", "replace": "value = 3", "reason": "Primer ajuste"}],
                    },
                    {
                        "status": "ready",
                        "summary": "Segundo intento.",
                        "edits": [{"file": "sample_module.py", "find": "value = 1", "replace": "value = 2", "reason": "Segundo ajuste"}],
                    },
                ]
                validation_queue = [
                    {"status": "failed", "steps": [{"command": "python3 -m py_compile sample_module.py", "status": "failed", "detail": "AssertionError"}]},
                    {"status": "passed", "steps": [{"command": "python3 -m py_compile sample_module.py", "status": "passed"}]},
                ]
                server._workspace_internal_copilot_generate_codefix_edits = lambda bundle: edits_queue.pop(0)
                server._workspace_internal_copilot_run_validation_bundle = lambda bundle: validation_queue.pop(0)
                result = server.perform_workspace_internal_copilot_action(
                    self.conn,
                    "ws1",
                    "apply_code_autofix_bundle",
                    {
                        "plan": {
                            "domain": "gestoria",
                            "assigned_mode": "supervisor",
                            "diagnosis": "Fallo en flujo de factura sin asiento.",
                            "patch_outline": ["corregir valor"],
                            "probable_files": ["sample_module.py"],
                            "probable_tests": ["tests/test_workspace_process_supervisor.py"],
                        }
                    },
                    empresa_id="e1",
                    actor={"id": "u1", "usuario": "QA"},
                    now="2026-06-21T10:25:00Z",
                )
                self.assertTrue(result["ok"])
                self.assertEqual((result.get("apply_result") or {}).get("status"), "passed")
                self.assertEqual((result.get("apply_result") or {}).get("validation_bundle", {}).get("probable_files"), ["sample_module.py"])
                self.assertEqual((result.get("apply_result") or {}).get("attempts_count"), 2)
                self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")
        finally:
            server._workspace_internal_copilot_codefix_root = old_root
            server._workspace_internal_copilot_generate_codefix_edits = old_generate
            server._workspace_internal_copilot_run_validation_bundle = old_validate

    def test_internal_copilot_build_action_reply_detects_user_access_issue(self):
        reply = server._workspace_internal_copilot_build_action_reply(
            self.conn,
            "ws1",
            "revisa acceso de acceso.user",
            empresa_id="e1",
            service_hint="gestoria",
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertEqual((reply.get("actions") or [])[0]["id"], "review_user_access")
        self.assertEqual((((reply.get("actions") or [])[0]).get("payload") or {}).get("login"), "acceso.user")

    def test_internal_copilot_review_user_access_suggests_membership_repair(self):
        server.ensure_usuarios_schema(self.conn)
        server.ensure_workspace_core_tables(self.conn)
        self.conn.execute("DELETE FROM usuarios WHERE usuario = 'acceso.user'")
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            ("u_access", "Acceso", "User", "acceso.user", "acceso@example.com", "Gestoría", "Lectura", "pbkdf2_sha256$abc"),
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "review_user_access",
            {"login": "acceso.user"},
            empresa_id="e1",
            actor={"id": "admin", "usuario": "Admin"},
            now="2026-06-22T09:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertIn("missing_all_memberships", list(result.get("issues") or []))
        self.assertTrue(any(str(action.get("id") or "") == "repair_user_membership" for action in (result.get("actions") or [])))

    def test_internal_copilot_repair_user_membership_and_revalidate_access(self):
        server.ensure_usuarios_schema(self.conn)
        server.ensure_workspace_core_tables(self.conn)
        self.conn.execute("DELETE FROM usuarios WHERE usuario = 'access.fix'")
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            ("u_fix", "Access", "Fix", "access.fix", "fix@example.com", "Gestoría", "Lectura", "pbkdf2_sha256$abc"),
        )
        repair = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "repair_user_membership",
            {"user_id": "u_fix", "login": "access.fix", "role": "Miembro"},
            empresa_id="e1",
            actor={"id": "admin", "usuario": "Admin"},
            now="2026-06-22T09:05:00Z",
        )
        self.assertTrue(repair["ok"])
        membership = self.conn.execute(
            "SELECT rol FROM workspace_miembros WHERE workspace_id = ? AND usuario_id = ?",
            ("ws1", "u_fix"),
        ).fetchone()
        self.assertIsNotNone(membership)
        revalidated = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "revalidate_user_access",
            {"login": "access.fix"},
            empresa_id="e1",
            actor={"id": "admin", "usuario": "Admin"},
            now="2026-06-22T09:06:00Z",
        )
        self.assertTrue(revalidated["ok"])
        self.assertEqual(revalidated.get("status"), "clean")
        self.assertFalse([issue for issue in (revalidated.get("issues") or []) if issue in {"missing_all_memberships", "missing_workspace_membership"}])

    def test_internal_copilot_activate_user_access_marks_user_active(self):
        server.ensure_usuarios_schema(self.conn)
        self.conn.execute("DELETE FROM usuarios WHERE usuario = 'disabled.user'")
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, datetime('now'), datetime('now'))
            """,
            ("u_disabled", "Disabled", "User", "disabled.user", "disabled@example.com", "Gestoría", "Lectura", "pbkdf2_sha256$abc"),
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "activate_user_access",
            {"user_id": "u_disabled", "login": "disabled.user"},
            empresa_id="e1",
            actor={"id": "admin", "usuario": "Admin"},
            now="2026-06-22T09:10:00Z",
        )
        self.assertTrue(result["ok"])
        row = self.conn.execute("SELECT activo FROM usuarios WHERE id = ?", ("u_disabled",)).fetchone()
        self.assertEqual(int(row["activo"] or 0), 1)

    def test_internal_copilot_force_reset_user_access_returns_invite_url(self):
        server.ensure_usuarios_schema(self.conn)
        server.ensure_auth_invites_table(self.conn)
        self.conn.execute("DELETE FROM usuarios WHERE usuario = 'reset.user'")
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            ("u_reset", "Reset", "User", "reset.user", "reset@example.com", "Gestoría", "Lectura", "pbkdf2_sha256$abc"),
        )
        old_base = os.environ.get("APP_BASE_URL")
        try:
            os.environ["APP_BASE_URL"] = "https://crm.example.test"
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "force_reset_user_access",
                {"login": "reset.user"},
                empresa_id="e1",
                actor={"id": "admin", "usuario": "Admin"},
                now="2026-06-22T09:15:00Z",
            )
        finally:
            if old_base is None:
                os.environ.pop("APP_BASE_URL", None)
            else:
                os.environ["APP_BASE_URL"] = old_base
        self.assertTrue(result["ok"])
        self.assertIn("/?activar_token=", str(result.get("invite_url") or ""))
        user_row = self.conn.execute("SELECT password_hash FROM usuarios WHERE id = ?", ("u_reset",)).fetchone()
        self.assertFalse(str(user_row["password_hash"] or "").strip())

    def test_internal_copilot_action_inspect_current_problem_uses_visible_error_and_recent_api_errors(self):
        original_ring = list(getattr(server.Handler, "_api_err_ring", []) or [])
        try:
            server.Handler._api_err_ring = [
                {
                    "at": "2026-06-22T10:00:00Z",
                    "path": "/api/gestoria_dashboard:segmentacion_trabajos",
                    "type": "ProgrammingError",
                    "message": "placeholder mismatch",
                }
            ]
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "inspect_current_problem",
                {
                    "current_crm": "gestoria",
                    "current_workspace_view": "operations",
                    "current_page": "cliente",
                    "current_module": "clientes",
                    "current_url": "https://crm.example.test/?holding=1&mode=tenant&workspace=ws1&crm=gestoria",
                    "ui_error_title": "Error cargando dashboard",
                    "ui_error_detail": "La segmentación de trabajos ha fallado.",
                    "current_client_id": "c1",
                },
                empresa_id="e1",
                actor={"id": "u1", "usuario": "QA"},
                now="2026-06-22T10:05:00Z",
            )
        finally:
            server.Handler._api_err_ring = original_ring
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("action_id"), "inspect_current_problem")
        self.assertTrue(any(str(card.get("title") or "") == "Lugar actual del problema" for card in (result.get("cards") or [])))
        self.assertTrue(any("segmentacion_trabajos" in str(card.get("summary") or "") for card in (result.get("cards") or [])))
        self.assertTrue(any(str(action.get("id") or "") == "prepare_code_autofix_task" for action in (result.get("actions") or [])))

    def test_internal_copilot_build_action_reply_can_investigate_current_problem(self):
        reply = server.build_workspace_internal_copilot_reply(
            self.conn,
            "ws1",
            "soluciona este error",
            empresa_id="e1",
            service_hint="gestoria",
            actor={"id": "u1", "usuario": "QA"},
            context={"current_crm": "gestoria", "ui_error_title": "Error visible", "ui_error_detail": "fallo en dashboard"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply.get("intent"), "action")
        self.assertTrue(any(str(action.get("id") or "") == "inspect_current_problem" for action in (reply.get("actions") or [])))

    def test_internal_copilot_build_action_reply_can_impersonate_user(self):
        reply = server._workspace_internal_copilot_build_action_reply(
            self.conn,
            "ws1",
            "entra como slallana",
            empresa_id="e1",
            service_hint="gestoria",
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertEqual((reply.get("actions") or [])[0]["id"], "impersonate_user_session")
        self.assertEqual((((reply.get("actions") or [])[0]).get("payload") or {}).get("login"), "slallana")

    def test_internal_copilot_review_impersonated_session_reports_clean_access(self):
        server.ensure_workspace_core_tables(self.conn)
        server.ensure_usuarios_schema(self.conn)
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, created_at, updated_at)
            VALUES ('ws1', 'Workspace 1', 'workspace-1', 'Activo', 'Pro', datetime('now'), datetime('now'))
            """
        )
        self.conn.execute(
            """
            INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, created_at, updated_at)
            VALUES ('m1', 'ws1', 'u_imp', 'Miembro', datetime('now'), datetime('now'))
            """
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "review_impersonated_session",
            {},
            empresa_id="e1",
            actor={
                "user_id": "u_imp",
                "usuario": "slallana",
                "email": "slallana@example.com",
                "servicio": "Gestoría",
                "rol": "Lectura",
                "impersonating": 1,
                "impersonated_by_usuario": "admin.user",
            },
            now="2026-06-22T12:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("status"), "clean")
        self.assertIn("sano", str(result.get("message") or "").lower())
        self.assertTrue(any(str(card.get("title") or "") == "Sesión impersonada revisada" for card in (result.get("cards") or [])))

    def test_internal_copilot_impersonate_user_session_sets_post_reload_review(self):
        server.ensure_workspace_core_tables(self.conn)
        server.ensure_usuarios_schema(self.conn)
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            ("u_imp_target", "S", "Lallana", "slallana", "slallana@example.com", "Gestoría", "Lectura", "pbkdf2_sha256$abc"),
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "impersonate_user_session",
            {"login": "slallana", "reason": "QA"},
            empresa_id="e1",
            actor={
                "token": "orig-token",
                "user_id": "admin-1",
                "usuario": "admin.user",
                "email": "admin@example.com",
                "servicio": "Gestoría",
                "rol": "Administrador",
            },
            now="2026-06-22T12:05:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(bool(result.get("reload_after_session_switch")))
        self.assertEqual(((result.get("post_reload_action") or {}).get("action_id") or "").strip(), "review_impersonated_session")
        self.assertTrue(str(result.get("session_cookie_token") or "").strip())

    def test_internal_copilot_build_action_reply_can_review_user_agenda_by_impersonation(self):
        reply = server._workspace_internal_copilot_build_action_reply(
            self.conn,
            "ws1",
            "entra como slallana y comprueba que se ve todas las citas de la agenda",
            empresa_id="e1",
            service_hint="gestoria",
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertEqual((reply.get("actions") or [])[0]["id"], "impersonate_user_session")
        self.assertEqual((((reply.get("actions") or [])[0]).get("payload") or {}).get("post_review_action"), "review_impersonated_agenda")

    def test_internal_copilot_build_action_reply_can_review_user_experience_by_impersonation(self):
        reply = server._workspace_internal_copilot_build_action_reply(
            self.conn,
            "ws1",
            "que ve exactamente slallana en el sistema",
            empresa_id="e1",
            service_hint="gestoria",
            context={},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertEqual((reply.get("actions") or [])[0]["id"], "impersonate_user_session")
        self.assertEqual((((reply.get("actions") or [])[0]).get("payload") or {}).get("post_review_action"), "review_impersonated_session")

    def test_internal_copilot_build_action_reply_can_review_browser_experience(self):
        reply = server._workspace_internal_copilot_build_action_reply(
            self.conn,
            "ws1",
            "entra como slallana y revisa en navegador esta pantalla",
            empresa_id="e1",
            service_hint="gestoria",
            context={"current_route": "/?holding=1&mode=tenant&workspace=ws1&crm=fin", "current_crm": "fin", "current_page": "dashboard"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertEqual((reply.get("actions") or [])[0]["id"], "review_browser_experience")
        self.assertEqual((((reply.get("actions") or [])[0]).get("payload") or {}).get("login"), "slallana")

    def test_internal_copilot_build_action_reply_can_search_internet(self):
        reply = server._workspace_internal_copilot_build_action_reply(
            self.conn,
            "ws1",
            "busca en internet obligaciones de alquiler turistico en boe",
            empresa_id="e1",
            service_hint="gestoria",
            context={"current_workspace_id": "ws1", "current_crm": "gestoria"},
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["intent"], "action")
        self.assertEqual((reply.get("actions") or [])[0]["id"], "search_internet")
        self.assertIn("alquiler turistico", (((reply.get("actions") or [])[0]).get("payload") or {}).get("query", ""))

    def test_internal_copilot_action_search_internet_prefers_browser_results(self):
        old_browser = server.run_ollana_browser_review
        old_fallback = server.copilot_web_search
        try:
            server.run_ollana_browser_review = lambda payload=None: {
                "ok": True,
                "status": "passed",
                "search": {
                    "ok": True,
                    "query": "obligaciones boe",
                    "results": [
                        {"title": "BOE", "url": "https://boe.es/test", "snippet": "Resumen", "domain": "boe.es", "allowed_fetch": True}
                    ],
                },
            }
            server.copilot_web_search = lambda *args, **kwargs: {"error": "no debería usarse"}
            result = server.perform_workspace_internal_copilot_action(
                self.conn,
                "ws1",
                "search_internet",
                {"query": "obligaciones boe"},
                actor={"usuario": "admin"},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["sources"][0], "browser_search")
            self.assertEqual((result.get("cards") or [])[0]["title"], "BOE")
        finally:
            server.run_ollana_browser_review = old_browser
            server.copilot_web_search = old_fallback

    def test_internal_copilot_review_impersonated_agenda_reports_visible_items(self):
        server.ensure_workspace_core_tables(self.conn)
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, created_at, updated_at)
            VALUES ('ws1', 'Workspace 1', 'workspace-1', 'Activo', 'Pro', datetime('now'), datetime('now'))
            """
        )
        self.conn.execute(
            """
            INSERT INTO acciones (
              id, empresa_id, servicio, cliente_nombre, fecha, hora, tipo, responsable, estado, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("a_ag1", "e1", "Gestoría", "Cliente Agenda", "2026-06-23", "10:00", "Cita revisión", "SLallana", "Pendiente"),
        )
        result = server.perform_workspace_internal_copilot_action(
            self.conn,
            "ws1",
            "review_impersonated_agenda",
            {},
            empresa_id="e1",
            actor={
                "user_id": "u_imp",
                "usuario": "slallana",
                "email": "slallana@example.com",
                "servicio": "Gestoría",
                "rol": "Lectura",
                "impersonating": 1,
                "impersonated_by_usuario": "admin.user",
            },
            now="2026-06-22T12:10:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertIn("ve 1 cita", str(result.get("message") or "").lower())
        self.assertTrue(any("Cliente Agenda" in str(card.get("summary") or "") for card in (result.get("cards") or [])))


if __name__ == "__main__":
    unittest.main()
