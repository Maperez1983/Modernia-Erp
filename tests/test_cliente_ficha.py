import json
import sqlite3
import unittest
from datetime import datetime, timezone

from web.server import (
    build_cliente_ficha_payload,
    classify_gestoria_renta_document,
    compute_gestoria_renta_dashboard,
    compute_gestoria_renta_docs_summary,
    ensure_seguro_doc_link,
)


class ClienteFichaTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              tipo_persona TEXT,
              nif TEXT,
              telefono TEXT,
              email TEXT,
              fecha_nacimiento TEXT,
              direccion TEXT,
              codigo_postal TEXT,
              poblacion TEXT,
              provincia TEXT,
              tipo TEXT,
              perfil TEXT,
              estado TEXT,
              empresa_id TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT
            );
            CREATE TABLE clientes_empresas (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              empresa_id TEXT,
              servicio TEXT,
              estado TEXT,
              fecha_inicio TEXT,
              fecha_fin TEXT,
              created_at TEXT,
              updated_at TEXT
            );
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
              produccion TEXT,
              colaborador TEXT,
              estado TEXT,
              estado_renovacion TEXT,
              renovacion_fecha TEXT,
              nueva_poliza_ref TEXT,
              poliza_key TEXT,
              poliza_url TEXT,
              fecha_baja TEXT,
              motivo_baja TEXT,
              estado_poliza TEXT,
              poliza_origen_id TEXT,
              poliza_sustituta_id TEXT,
              version_grupo TEXT,
              tipo_vigencia TEXT,
              created_at TEXT,
              updated_at TEXT
            );
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
              calidad_ocr TEXT,
              campos_ocr TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE inmuebles (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              direccion TEXT,
              referencia_catastral TEXT,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE inmueble_propietarios (
              id TEXT PRIMARY KEY,
              inmueble_id TEXT,
              cliente_id TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE inmueble_docs (
              id TEXT PRIMARY KEY,
              inmueble_id TEXT,
              nombre TEXT,
              url TEXT,
              tipo TEXT,
              estado TEXT,
              version INTEGER,
              plantilla_clave TEXT,
              origen_tipo TEXT,
              origen_id TEXT,
              payload_json TEXT,
              reviewed_at TEXT,
              reviewed_by TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE gestoria_trabajos (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tipo_trabajo TEXT,
              estado TEXT,
              fecha_inicio TEXT,
              fecha_fin TEXT,
              responsable TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            );
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
            );
            CREATE TABLE gestoria_contabilidad (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente_ids_json TEXT,
              fecha TEXT,
              concepto TEXT,
              gestion TEXT,
              tipo TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE cliente_gestoria (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              tipo_cliente TEXT,
              mod_fiscal INTEGER,
              mod_laboral INTEGER,
              mod_contable INTEGER,
              mod_renta INTEGER,
              mod_registro INTEGER,
              mod_trafico INTEGER,
              mod_puntuales INTEGER,
              renta_detalles TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO clientes (id, nombre, estado, created_at, updated_at) VALUES (?, ?, 'Activo', ?, ?)",
            ("c1", "BENABDALLAH, ADIL", now, now),
        )
        self.conn.execute("INSERT INTO empresas (id, nombre) VALUES ('e1', 'FINCAS VELAZQUEZ')")
        self.conn.execute(
            """
            INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, created_at, updated_at)
            VALUES ('ce1', 'c1', 'e1', 'seguros', 'Activo', ?, ?)
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, created_at, updated_at)
            VALUES ('ce2', 'c1', 'e1', 'inmobiliaria', 'Activo', ?, ?)
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id, fecha_efecto, tomador, compania, ramo,
              poliza_numero, prima_total, estado, poliza_key, poliza_url, created_at, updated_at
            ) VALUES (
              's1', 'e1', 'c1', '2025-01-10', 'ADIL BENABDALLAH', 'MAPFRE', 'Hogar',
              '0732439Y1847803', 450.0, 'En vigor', 'k1', 'https://x/p1.pdf', ?, ?
            )
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad
            (id, empresa_id, cliente_id, fecha, concepto, tipo, importe, created_at, updated_at)
            VALUES ('gc1', 'e1', 'c1', '2026-01-10', 'Honorarios', 'Ingreso', 1200.0, ?, ?)
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO inmuebles (id, empresa_id, direccion, referencia_catastral, estado, created_at, updated_at)
            VALUES ('i1', 'e1', 'Pasaje Augusto Besada 2 14 D', '0119101UF7601N0078RM', 'Encargo', ?, ?)
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO inmueble_propietarios (id, inmueble_id, cliente_id, created_at, updated_at)
            VALUES ('ip1', 'i1', 'c1', ?, ?)
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO inmueble_docs (
              id, inmueble_id, nombre, url, tipo, estado, version, plantilla_clave, created_at, updated_at
            ) VALUES (
              'id1', 'i1', 'Ficha Catastro · Pasaje Augusto Besada 2 14 D',
              '/uploads/inmuebles/generated/ficha_catastro_pasaje_augusto_besada.pdf',
              'Ficha Catastro', 'Vigente', 1, 'ficha_catastro', ?, ?
            )
            """,
            (now, now),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_build_cliente_ficha_payload_contains_kpis_and_services(self):
        payload = build_cliente_ficha_payload(self.conn, "c1")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["cliente"]["id"], "c1")
        self.assertIn("seguros", payload["servicios_activos"])
        self.assertEqual(len(payload["servicios"]["seguros"]), 1)
        self.assertGreater(payload["dashboard"]["primas_total"], 0)
        self.assertGreater(payload["dashboard"]["rentabilidad"]["cobrado"], 0)

    def test_ensure_seguro_doc_link_is_idempotent(self):
        now = datetime.now(timezone.utc).isoformat()
        seguro_row = self.conn.execute("SELECT * FROM seguros WHERE id='s1'").fetchone()
        first_id = ensure_seguro_doc_link(self.conn, seguro_row, now)
        second_id = ensure_seguro_doc_link(self.conn, seguro_row, now)
        self.assertTrue(first_id)
        self.assertEqual(first_id, second_id)
        count = self.conn.execute("SELECT COUNT(*) AS n FROM gestoria_docs WHERE referencia_id='s1'").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_build_cliente_ficha_payload_splits_multi_client_accounting_entry(self):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO clientes (id, nombre, estado, created_at, updated_at)
            VALUES ('c2', 'SEGUNDO CLIENTE', 'Activo', ?, ?)
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad
            (id, empresa_id, cliente_id, cliente_ids_json, fecha, concepto, tipo, importe, created_at, updated_at)
            VALUES ('gc2', 'e1', 'c1', '["c1","c2"]', '2026-02-01', 'Liquidación mensual', 'Ingreso', 200.0, ?, ?)
            """,
            (now, now),
        )
        self.conn.commit()
        payload = build_cliente_ficha_payload(self.conn, "c1")
        facturas = payload.get("facturas") or []
        liquidacion = next((row for row in facturas if row.get("id") == "gc2"), None)
        self.assertIsNotNone(liquidacion)
        self.assertAlmostEqual(float(liquidacion.get("importe_asignado") or 0), 100.0, places=2)

    def test_build_cliente_ficha_payload_backfills_inmobiliaria_docs_for_owner(self):
        payload = build_cliente_ficha_payload(self.conn, "c1")
        inmo_docs = payload.get("documentacion", {}).get("by_service", {}).get("inmobiliaria") or []
        self.assertEqual(len(inmo_docs), 1)
        self.assertEqual(inmo_docs[0]["referencia_tipo"], "inmobiliaria")
        self.assertEqual(inmo_docs[0]["referencia_id"], "id1")
        self.assertEqual(inmo_docs[0]["doc_url"], "/uploads/inmuebles/generated/ficha_catastro_pasaje_augusto_besada.pdf")
        stored = self.conn.execute(
            "SELECT COUNT(*) AS n FROM gestoria_docs WHERE cliente_id = 'c1' AND referencia_tipo = 'inmobiliaria' AND referencia_id = 'id1'"
        ).fetchone()
        self.assertEqual(stored["n"], 1)

    def test_build_cliente_ficha_payload_includes_gestoria_summary(self):
        now = datetime.now(timezone.utc).isoformat()
        renta_payload = {
            "entries": [
                {
                    "id": "renta-2025-c1",
                    "ejercicio": "2025",
                    "estado_presentacion": "Presentada",
                    "precio_servicio": 120.0,
                    "cobrada": 0,
                }
            ]
        }
        self.conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_renta, mod_registro, mod_trafico, mod_puntuales,
              renta_detalles, created_at, updated_at
            ) VALUES ('cg1', 'c1', 'Particular', 1, 0, 0, 0, ?, ?, ?)
            """,
            (json.dumps(renta_payload), now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, estado,
              doc_key, created_at, updated_at
            ) VALUES (
              'rd1', 'e1', 'c1', 'renta', 'renta-2025-c1',
              'Renta 2025 · Presentada.pdf', 'Modelo 100', 'Presentada',
              'gestoria/rentas/renta.pdf', ?, ?
            )
            """,
            (now, now),
        )
        self.conn.commit()

        payload = build_cliente_ficha_payload(self.conn, "c1")
        gestoria = payload.get("dashboard", {}).get("gestoria") or {}

        self.assertTrue(gestoria["activo"])
        self.assertEqual(gestoria["latest_renta_year"], "2025")
        self.assertEqual(gestoria["modelo100_docs_total"], 1)
        self.assertEqual(gestoria["rentas_pendientes_cobro"], 1)
        self.assertAlmostEqual(float(gestoria["importe_rentas_pendiente"]), 120.0, places=2)
        self.assertEqual(gestoria["status_global"], "Pendiente cobro")
        self.assertGreaterEqual(gestoria["checklist_total"], 1)
        self.assertTrue(any(item["key"] == "modelo100" and item["done"] for item in gestoria["checklist"]))
        self.assertTrue(any(item["target"] == "renta" for item in gestoria["next_actions"]))
        self.assertTrue(any(item["kind"] == "documento" for item in gestoria["timeline"]))

    def test_renta_dashboard_counts_modelo100_uploaded_during_campaign(self):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE clientes SET empresa_id = 'e1' WHERE id = 'c1'")
        self.conn.execute(
            """
            INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, created_at, updated_at)
            VALUES ('ce3', 'c1', 'e1', 'gestoria', 'Activo', ?, ?)
            """,
            (now, now),
        )
        renta_payload = {
            "entries": [
                {
                    "id": "camp-2025",
                    "ejercicio": "2025",
                    "estado_presentacion": "Presentada",
                    "presentacion_fecha": "2026-05-20",
                    "precio_servicio": 120,
                    "cobrada": False,
                }
            ]
        }
        self.conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_renta, mod_registro, mod_trafico, mod_puntuales,
              renta_detalles, created_at, updated_at
            ) VALUES ('cg-renta-dash', 'c1', 'Particular', 1, 0, 0, 0, ?, ?, ?)
            """,
            (json.dumps(renta_payload), now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, fecha, estado,
              notas, doc_key, created_at, updated_at
            ) VALUES (
              'rd-campaign-upload', 'e1', 'c1', 'gestoria', '',
              'IRPF presentado.pdf', 'Modelo 100', '', 'Presentada',
              '', 'gestoria/rentas/modelo100.pdf', '2026-06-01T10:00:00', '2026-06-01T10:00:00'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, fecha, estado,
              notas, doc_key, created_at, updated_at
            ) VALUES (
              'rd-aux-dni', 'e1', 'c1', 'renta', 'renta-2025-aux',
              'Renta 2025 · DNI Cliente.pdf', 'DNI', '', 'Recibido',
              '', 'gestoria/rentas/dni.pdf', '2026-06-02T11:00:00', '2026-06-02T11:00:00'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, fecha, estado,
              notas, doc_key, created_at, updated_at
            ) VALUES (
              'rd-ref-linked', 'otra-empresa', 'c1', '', 'renta-2025-camp-extra',
              'Documento fiscal validado.pdf', 'Declaracion presentada', '', 'Presentada',
              'Modelo 100 verificado', 'gestoria/rentas/modelo100-extra.pdf', '2026-06-02T10:00:00', '2026-06-02T10:00:00'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, fecha, estado,
              notas, doc_key, created_at, updated_at
            ) VALUES (
              'rd-previous-year-uploaded-in-campaign', 'e1', 'c1', 'renta', 'renta-2024-c1',
              'Renta 2024 · Cliente.pdf', 'Renta Presentada', '', 'Presentada',
              '', 'gestoria/rentas/renta-2024.pdf', '2026-06-03T10:00:00', '2026-06-03T10:00:00'
            )
            """
        )
        self.conn.commit()

        dashboard = compute_gestoria_renta_dashboard(self.conn, "e1", "2025")
        summary = compute_gestoria_renta_docs_summary(self.conn, "e1", "2025")

        self.assertEqual(dashboard["counts"]["docs_total"], 3)
        self.assertEqual(dashboard["counts"]["clientes_con_doc"], 1)
        self.assertEqual(dashboard["counts"]["modelo100_docs_total"], 2)
        self.assertEqual(dashboard["counts"]["modelo100_unicos"], 1)
        self.assertEqual(dashboard["counts"]["declaraciones_docs_total"], 2)
        self.assertEqual(dashboard["counts"]["declaraciones_unicas"], 1)
        self.assertEqual(summary["docs_total"], 3)
        self.assertEqual(summary["clientes_con_doc"], 1)
        self.assertEqual(summary["modelo100_docs_total"], 2)
        self.assertEqual(summary["modelo100_unicos"], 1)
        self.assertEqual(summary["declaraciones_docs_total"], 2)
        self.assertEqual(summary["declaraciones_unicas"], 1)

    def test_renta_document_classifier_separates_modelo100_from_auxiliary(self):
        modelo = classify_gestoria_renta_document(
            self.conn,
            cliente_id="c1",
            ejercicio="2025",
            nombre="Renta 2025 · Presentada.pdf",
            tipo="Modelo 100",
            referencia_id="renta-2025-c1",
            estado="Presentada",
        )
        dni = classify_gestoria_renta_document(
            self.conn,
            cliente_id="c1",
            ejercicio="2025",
            nombre="Renta 2025 · DNI Cliente.pdf",
            tipo="DNI",
            referencia_id="renta-2025-aux",
            estado="Recibido",
        )

        self.assertEqual(modelo["ejercicio_fiscal"], "2025")
        self.assertEqual(modelo["tipo_documento"], "modelo_100")
        self.assertEqual(modelo["estado_revision"], "ok")
        self.assertEqual(dni["ejercicio_fiscal"], "2025")
        self.assertEqual(dni["tipo_documento"], "dni")
        self.assertEqual(dni["estado_revision"], "ok")


if __name__ == "__main__":
    unittest.main()
