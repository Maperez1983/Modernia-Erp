import json
import sqlite3
import sys
import types
import unittest

if "PIL" not in sys.modules:
    pil_stub = types.ModuleType("PIL")
    pil_stub.Image = object()
    pil_stub.ImageDraw = object()
    pil_stub.ImageEnhance = object()
    pil_stub.ImageFilter = object()
    pil_stub.ImageFont = object()
    pil_stub.ImageOps = object()
    sys.modules["PIL"] = pil_stub

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
              email TEXT
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
            CREATE TABLE cliente_gestoria (
              cliente_id TEXT PRIMARY KEY,
              mod_renta INTEGER,
              renta_detalles TEXT
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


if __name__ == "__main__":
    unittest.main()
