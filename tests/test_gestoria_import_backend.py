import sqlite3
import unittest

from web.server import (
    apply_gestoria_import_lote,
    ensure_gestoria_import_schema,
    refresh_gestoria_import_lote_totals,
    upsert_gestoria_import_document,
)


class GestoriaImportBackendTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT
            );
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT
            );
            CREATE TABLE gestoria_docs (
              id TEXT PRIMARY KEY
            );
            CREATE TABLE gestoria_terceros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              nif TEXT,
              nombre TEXT,
              tipo TEXT,
              cuenta_contable TEXT,
              created_at TEXT,
              updated_at TEXT
            );
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
              import_documento_id TEXT,
              origen_importacion TEXT,
              created_at TEXT,
              updated_at TEXT
            );
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
            );
            CREATE TABLE gestoria_asiento_lineas (
              id TEXT PRIMARY KEY,
              asiento_id TEXT,
              tercero_id TEXT,
              cuenta TEXT,
              descripcion TEXT,
              debe REAL,
              haber REAL,
              impuesto_tipo TEXT,
              impuesto_pct REAL,
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
            """
        )
        ensure_gestoria_import_schema(self.conn)
        self.conn.execute("INSERT INTO empresas (id, nombre) VALUES ('e1', 'Empresa Demo')")
        self.conn.execute("INSERT INTO clientes (id, nombre) VALUES ('c1', 'Cliente Demo')")
        self.conn.execute(
            """
            INSERT INTO gestoria_import_lotes (
              id, empresa_id, cliente_id, origen, estado, periodo, created_at, updated_at
            ) VALUES (
              'l1', 'e1', 'c1', 'test', 'nuevo', '2026-03', '2026-03-01', '2026-03-01'
            )
            """
        )
        self.now = "2026-03-26T10:00:00+00:00"

    def tearDown(self):
        self.conn.close()

    def test_upsert_documents_updates_lote_totals(self):
        upsert_gestoria_import_document(
            self.conn,
            "l1",
            "e1",
            "c1",
            {
                "archivo": "ok.pdf",
                "fecha": "2026-03-05",
                "tercero": "Proveedor Uno",
                "nif": "B12345678",
                "tipo": "compra",
                "base_imponible": 100.0,
                "cuota_iva": 21.0,
                "total": 121.0,
                "categoria_excel": "SUMINISTROS",
                "estado_revision": "OK",
            },
            self.now,
        )
        upsert_gestoria_import_document(
            self.conn,
            "l1",
            "e1",
            "c1",
            {
                "archivo": "dup.pdf",
                "fecha": "2026-03-06",
                "tercero": "Proveedor Dos",
                "total": 50.0,
                "estado_revision": "DUPLICADO",
            },
            self.now,
        )
        lote = refresh_gestoria_import_lote_totals(self.conn, "l1", self.now)
        self.assertEqual(lote["total_documentos"], 2)
        self.assertEqual(lote["total_ok"], 1)
        self.assertEqual(lote["total_duplicado"], 1)
        self.assertEqual(lote["estado"], "preparado")

    def test_apply_lote_creates_factura_asiento_and_links_document(self):
        upsert_gestoria_import_document(
            self.conn,
            "l1",
            "e1",
            "c1",
            {
                "archivo": "factura_luz.pdf",
                "fecha": "2026-03-08",
                "numero": "F-2026-88",
                "tercero": "Comercial Electrica",
                "nif": "B76543210",
                "tipo": "compra",
                "base_imponible": 200.0,
                "cuota_iva": 42.0,
                "total": 242.0,
                "categoria_excel": "SUMINISTROS",
                "descripcion": "Factura luz marzo",
                "estado_revision": "OK",
            },
            self.now,
        )
        result = apply_gestoria_import_lote(self.conn, "l1", "e1", self.now)
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["errors"]), 0)

        factura = self.conn.execute(
            """
            SELECT numero, total, origen_importacion, import_documento_id
            FROM gestoria_facturas
            LIMIT 1
            """
        ).fetchone()
        self.assertEqual(factura["numero"], "F-2026-88")
        self.assertAlmostEqual(float(factura["total"] or 0), 242.0, places=2)
        self.assertEqual(factura["origen_importacion"], "gestoria_import")
        self.assertTrue(factura["import_documento_id"])

        asiento = self.conn.execute(
            "SELECT concepto, total_debe, total_haber FROM gestoria_asientos LIMIT 1"
        ).fetchone()
        self.assertIn("SUMINISTROS", asiento["concepto"])
        self.assertAlmostEqual(float(asiento["total_debe"] or 0), 242.0, places=2)
        self.assertAlmostEqual(float(asiento["total_haber"] or 0), 242.0, places=2)

        cuentas = {
            row["cuenta"]
            for row in self.conn.execute("SELECT cuenta FROM gestoria_asiento_lineas").fetchall()
        }
        self.assertIn("628", cuentas)
        self.assertIn("472", cuentas)
        self.assertIn("400", cuentas)

        doc = self.conn.execute(
            "SELECT factura_id, tercero_id, estado_revision FROM gestoria_import_documentos LIMIT 1"
        ).fetchone()
        self.assertTrue(doc["factura_id"])
        self.assertTrue(doc["tercero_id"])
        self.assertEqual(doc["estado_revision"], "OK")

    def test_apply_lote_rejects_invalid_vat_or_type(self):
        upsert_gestoria_import_document(
            self.conn,
            "l1",
            "e1",
            "c1",
            {
                "archivo": "factura_obramat_bad.jpg",
                "fecha": "2026-01-09",
                "numero": "09",
                "tercero": "Q° ~",
                "tipo": "venta",
                "base_imponible": 9.0,
                "cuota_iva": 21.0,
                "total": 9.0,
                "categoria_excel": "SUMINISTROS",
                "estado_revision": "OK",
            },
            self.now,
        )
        result = apply_gestoria_import_lote(self.conn, "l1", "e1", self.now)
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["errors"]), 1)

        doc = self.conn.execute(
            "SELECT estado_revision, motivos_revision FROM gestoria_import_documentos LIMIT 1"
        ).fetchone()
        self.assertEqual(doc["estado_revision"], "ERROR")
        self.assertIn("error_aplicacion", doc["motivos_revision"])

        factura_count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM gestoria_facturas"
        ).fetchone()["n"]
        self.assertEqual(factura_count, 0)


if __name__ == "__main__":
    unittest.main()
