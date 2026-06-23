import sqlite3
import sys
import types
import unittest

pil_stub = types.ModuleType("PIL")
pil_stub.Image = object()
pil_stub.ImageDraw = object()
pil_stub.ImageEnhance = object()
pil_stub.ImageFilter = object()
pil_stub.ImageFont = object()
pil_stub.ImageOps = object()
sys.modules.setdefault("PIL", pil_stub)

from web.server import find_reusable_hipoteca_open_record


class HipotecasDedupTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              estado TEXT,
              banco TEXT,
              oficina TEXT,
              inmobiliaria_compra TEXT,
              fecha_encargo TEXT,
              precio REAL,
              importe_hipoteca REAL,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )

    def test_finds_existing_open_record_with_same_signature(self):
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, estado, banco, oficina, inmobiliaria_compra,
              fecha_encargo, precio, importe_hipoteca, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "h1",
                "e1",
                "SEBASTIAN ANDRES LALLANA",
                "Estudio",
                "Banco Santander",
                "MALAGA OESTE",
                None,
                "2026-06-23",
                180000.0,
                180000.0,
                "2026-06-23T10:00:00",
                "2026-06-23T10:00:00",
            ),
        )
        row = find_reusable_hipoteca_open_record(
            self.conn,
            "e1",
            cliente="SEBASTIAN ANDRES LALLANA",
            fecha_encargo="2026-06-23",
            precio=180000.0,
            importe_hipoteca=180000.0,
            banco="Banco Santander",
            oficina="MALAGA OESTE",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "h1")

    def test_does_not_reuse_record_from_other_bank(self):
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, estado, banco, oficina, fecha_encargo, precio, importe_hipoteca
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("h1", "e1", "SEBASTIAN ANDRES LALLANA", "Estudio", "Banco Santander", "MALAGA OESTE", "2026-06-23", 180000.0, 180000.0),
        )
        row = find_reusable_hipoteca_open_record(
            self.conn,
            "e1",
            cliente="SEBASTIAN ANDRES LALLANA",
            fecha_encargo="2026-06-23",
            precio=180000.0,
            importe_hipoteca=180000.0,
            banco="CaixaBank",
            oficina="MALAGA OESTE",
        )
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
