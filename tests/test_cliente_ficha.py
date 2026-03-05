import sqlite3
import unittest
from datetime import datetime, timezone

from web.server import build_cliente_ficha_payload, ensure_seguro_doc_link


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
              calidad_ocr TEXT,
              campos_ocr TEXT,
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


if __name__ == "__main__":
    unittest.main()
