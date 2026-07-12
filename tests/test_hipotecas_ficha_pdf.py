import json
import sqlite3
import unittest
from io import BytesIO

from web import server


class HipotecasFichaPdfTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              nif TEXT,
              direccion TEXT,
              telefono TEXT,
              email TEXT,
              created_at TEXT
            );
            CREATE TABLE hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              porcentaje REAL,
              entrada REAL,
              comision REAL,
              oficina TEXT,
              fecha_encargo TEXT,
              encargo TEXT,
              tipo_hipoteca TEXT,
              fecha_firma TEXT,
              cesion REAL,
              comision_juan REAL,
              comision_modernia REAL,
              inmobiliaria_compra TEXT,
              asesor TEXT,
              estado TEXT,
              anio INTEGER,
              cliente_inmueble_json TEXT,
              hipoteca_detalle_json TEXT,
              liquidacion_json TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )
        self.conn.execute(
            """
            INSERT INTO clientes (
              id, nombre, nif, direccion, telefono, email, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "c1",
                "Ana López",
                "12345678A",
                "Calle Test 1",
                "600000000",
                "ana@example.com",
                "2026-06-20",
            ),
        )
        cliente_inmueble = {
            "inmueble": {
                "direccion": "Calle Test 1",
                "localidad": "Málaga",
                "provincia": "Málaga",
            },
            "intervinientes": [{"rol": "Avalista", "nombre": "Juan Pérez", "nif": "87654321B"}],
            "comprador": {
                "c1": {
                    "nombre": "Ana López",
                    "nif": "12345678A",
                    "email": "ana@example.com",
                    "telefono": "600000000",
                    "domicilio": "Calle Test 1",
                },
                "c2": {
                    "nombre": "Luis López",
                    "nif": "22345678B",
                    "email": "luis@example.com",
                    "telefono": "611111111",
                    "domicilio": "Calle Test 2",
                    "mismo_domicilio": "No",
                },
            },
            "prestataria": {
                "p1": {"source": "c1", "nombre": "Ana López", "nif": "12345678A"},
                "p2": {"source": "manual", "nombre": "Luis López", "nif": "22345678B"},
            },
        }
        hipoteca_detalle = {
            "condiciones": {"interes": 3.05, "cuota": 850},
            "preferencias": {
                "plazo_anos": 30,
                "tipo_interes": "Fijo",
                "garantia_vivienda_habitual": "Sí",
                "comision_apertura_max": 1.0,
                "otras": "Sin carencia",
            },
            "precontractual": {"registro": "BDE-123", "seguro_rc": "Seguro RC Profesional"},
            "comentarios": "Revisar tasación",
        }
        liquidacion = {
            "comprador": {
                "cliente": "Ana López",
                "vivienda": "Calle Test 1",
                "localidad": "Málaga",
                "provincia": "Málaga",
                "precio_compra": 250000,
                "escriturado": 250000,
                "gastos_compraventa": {"notaria": 1200, "registro": 700, "itp": 17500, "gestoria": 500},
                "hipoteca": {
                    "notaria_impuestos_gestoria": 1400,
                    "comision_apertura": 500,
                    "cuota_socio": 250,
                    "comision_cheques": 60,
                    "seguro_proteccion_pago": 0,
                    "seguro_hogar": 0,
                    "seguro_vida": 0,
                },
                "entregas": {
                    "senal": 10000,
                    "transf_modernia": 5000,
                    "ingresar_banco": 30000,
                    "prestamo_concedido": 200000,
                },
                "gestion_inmobiliaria": 1000,
                "gestion_financiacion": 750,
            },
            "vendedor": {
                "cliente": "Ana López",
                "direccion": "Calle Test 1",
                "localidad": "Málaga",
                "precio_vivienda": 250000,
                "deducciones": {
                    "senal": 10000,
                    "cancelacion_economica": 0,
                    "cancelacion_registral": 0,
                    "deuda_ibi": 0,
                    "plusvalia": 0,
                    "retencion_no_residente": 0,
                    "gestion_no_residente": 0,
                },
                "vendedores": {"v1": {"nombre": "Ana López", "nif": "12345678A"}},
            },
            "cuadre": {
                "cheque1": {"beneficiario": "OMF Ana", "importe": 50000},
                "cheque2": {"beneficiario": "OMF Luis", "importe": 30000},
                "seguros": 0,
            },
            "notaria": {
                "nombre": "Notaría Centro",
                "contacto": "José",
                "atencion": "Dpto Hipotecas",
                "entidad": "CaixaBank",
                "op_referencia": "OP-1",
                "fecha_hora_firma": "20/06/2026 10:00",
                "forma_pago": "Transferencia",
                "observaciones": "Sin incidencias",
            },
            "prestamo": {
                "tipo_salida": "Euribor",
                "revision": 12,
                "interes": 3.05,
                "plazo_anos": 30,
                "numero_cuotas": 360,
                "cuota_inicial": 850,
                "apertura": 1.0,
                "cancelacion_parcial": 0.25,
                "cancelacion": 0.25,
            },
        }
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "h1",
                "e1",
                "Ana López",
                "c1",
                "CaixaBank",
                250000,
                200000,
                80,
                50000,
                3000,
                "Modernia Centro",
                "2026-06-12",
                "Sí",
                "Compra",
                "2026-06-20",
                600,
                600,
                1800,
                "Inmo Sur",
                "María",
                "Firmada",
                2026,
                json.dumps(cliente_inmueble, ensure_ascii=False),
                json.dumps(hipoteca_detalle, ensure_ascii=False),
                json.dumps(liquidacion, ensure_ascii=False),
                "2026-06-20",
                "2026-06-20",
            ),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_build_hipoteca_ficha_pdf_generates_full_and_sectioned_docs(self):
        row = self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone()
        payload = server.build_hipoteca_ficha_payload(self.conn, row)

        full_pdf = server.build_hipoteca_ficha_pdf(payload)
        comprador_pdf = server.build_hipoteca_ficha_pdf(payload, section="comprador")
        full_filename = server.build_hipoteca_ficha_pdf_filename(payload)
        comprador_filename = server.build_hipoteca_ficha_pdf_filename(payload, section="comprador")

        self.assertTrue(full_pdf.startswith(b"%PDF"))
        self.assertTrue(comprador_pdf.startswith(b"%PDF"))
        self.assertGreater(len(full_pdf), len(comprador_pdf))
        self.assertTrue(full_filename.startswith("ficha_hipoteca_"))
        self.assertTrue(full_filename.endswith(".pdf"))
        self.assertIn("comprador", comprador_filename)
        self.assertIn("liquidacion_print", payload)
        self.assertIn("liq", payload["liquidacion_print"])
        self.assertGreater(payload["liquidacion_print"]["liq"]["comprador"]["suma_total_necesaria"], 0)

        if server.PdfReader is not None:
            reader = server.PdfReader(BytesIO(full_pdf))
            self.assertGreaterEqual(len(reader.pages), 1)

    def test_resolve_hipoteca_bank_brand_uses_local_assets(self):
        brand = server.resolve_hipoteca_bank_brand("Banco Santander S.A.")
        fallback = server.resolve_hipoteca_bank_brand("Entidad sin identificar")

        self.assertEqual(brand["name"], "Banco Santander")
        self.assertEqual(brand["logo"], "/assets/logos/santander.svg")
        self.assertTrue(brand["logo_on_dark"])
        self.assertEqual(fallback["logo"], "")
        self.assertEqual(fallback["short"], "ES")

    def test_build_hipoteca_ficha_pdf_passes_bank_logo_metadata(self):
        row = self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone()
        payload = server.build_hipoteca_ficha_payload(self.conn, row)
        captured = {}

        original = server.build_modernia_branded_document_pdf

        def fake_build(title, subtitle, sections, footer_lines=None, company=None, brand_logo_url=None):
            captured["title"] = title
            captured["subtitle"] = subtitle
            captured["sections"] = sections
            captured["brand_logo_url"] = brand_logo_url
            return b"%PDF-1.4\n%%EOF\n"

        try:
            server.build_modernia_branded_document_pdf = fake_build
            pdf_bytes = server.build_hipoteca_ficha_pdf(payload)
        finally:
            server.build_modernia_branded_document_pdf = original

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        hero_card = captured["sections"][0][1]
        self.assertEqual(hero_card["logo_url"], "/assets/logos/caixabank.svg")
        self.assertEqual(hero_card["logo_initials"], "CaixaBank")
        self.assertEqual(hero_card["logo_color"], "#0079c1")
        self.assertFalse(hero_card["logo_on_dark"])

    def test_collect_hipoteca_bdt_filter_options_derives_years_and_states(self):
        rows = [
            {"anio": "", "fecha_firma": "2026-06-20", "fecha_encargo": "2026-06-12", "estado": "Firmada"},
            {"anio": "2025", "fecha_firma": "", "fecha_encargo": "2025-03-03", "estado": "Pendiente"},
            {"anio": None, "fecha_firma": "2026-01-15", "fecha_encargo": "", "estado": "firmada"},
        ]

        filters = server.collect_hipoteca_bdt_filter_options(rows)

        self.assertEqual(filters["years"], ["2026", "2025"])
        self.assertEqual(filters["states"], ["Pendiente", "Firmada"])

    def test_build_hipotecas_fichas_pdf_merges_multiple_reports(self):
        row = self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone()
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "h2",
                "e1",
                "Luis López",
                "c1",
                "BBVA",
                220000,
                175000,
                79.54,
                45000,
                2800,
                "Modernia Norte",
                "2026-06-10",
                "Sí",
                "Compra",
                "2026-06-19",
                550,
                550,
                1600,
                "Inmo Norte",
                "María",
                "Firmada",
                2026,
                row["cliente_inmueble_json"],
                row["hipoteca_detalle_json"],
                row["liquidacion_json"],
                "2026-06-19",
                "2026-06-19",
            ),
        )
        self.conn.commit()

        rows = [
            self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone(),
            self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h2'").fetchone(),
        ]
        batch_pdf = server.build_hipotecas_fichas_pdf(self.conn, rows)

        self.assertTrue(batch_pdf.startswith(b"%PDF"))
        if server.PdfReader is not None:
            reader = server.PdfReader(BytesIO(batch_pdf))
            self.assertGreaterEqual(len(reader.pages), 2)

    def test_hipotecas_firmadas_pdf_filters_2025_and_signed_rows(self):
        row = self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone()
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "h2",
                "e1",
                "Luis López",
                "c1",
                "BBVA",
                220000,
                175000,
                79.54,
                45000,
                2800,
                "Modernia Norte",
                "2025-03-10",
                "Sí",
                "Compra",
                "2025-04-19",
                550,
                550,
                1600,
                "Inmo Norte",
                "María",
                "Firmada",
                2025,
                row["cliente_inmueble_json"],
                row["hipoteca_detalle_json"],
                row["liquidacion_json"],
                "2026-06-19",
                "2026-06-19",
            ),
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "h3",
                "e1",
                "No Firmada",
                "c1",
                "Sabadell",
                210000,
                165000,
                78.57,
                45000,
                2600,
                "Modernia Este",
                "2025-02-01",
                "Sí",
                "Compra",
                "2025-02-18",
                500,
                500,
                1500,
                "Inmo Este",
                "María",
                "Estudio",
                2025,
                row["cliente_inmueble_json"],
                row["hipoteca_detalle_json"],
                row["liquidacion_json"],
                "2026-06-19",
                "2026-06-19",
            ),
        )
        self.conn.commit()

        rows_2025 = server.collect_hipotecas_firmadas_rows(self.conn, "e1", "2025")
        self.assertEqual([row["id"] for row in rows_2025], ["h2"])
        self.assertEqual(server.build_hipotecas_firmadas_pdf_filename("2025", count=len(rows_2025)), "hipotecas_firmadas_2025_1.pdf")

        pdf_bytes = server.build_hipotecas_fichas_pdf(self.conn, rows_2025, filters={"year": "2025", "estado": "Firmada"})
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        if server.PdfReader is not None:
            reader = server.PdfReader(BytesIO(pdf_bytes))
            self.assertGreaterEqual(len(reader.pages), 1)

    def test_hipotecas_listado_pdf_generates_compact_list_download(self):
        row = self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone()
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "h2",
                "e1",
                "Luis López",
                "c1",
                "BBVA",
                220000,
                175000,
                79.54,
                45000,
                2800,
                "Modernia Norte",
                "2025-03-10",
                "Sí",
                "Compra",
                "2025-04-19",
                550,
                550,
                1600,
                "Inmo Norte",
                "María",
                "Firmada",
                2025,
                row["cliente_inmueble_json"],
                row["hipoteca_detalle_json"],
                row["liquidacion_json"],
                "2026-06-19",
                "2026-06-19",
            ),
        )
        self.conn.commit()

        rows = [
            self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone(),
            self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h2'").fetchone(),
        ]
        filters = {"year": "2025", "estado": "Firmada"}
        card_items = server.build_hipotecas_bdt_listado_card_items(server.build_hipoteca_export_row(self.conn, rows[0]))
        self.assertEqual(
            [item["label"] for item in card_items],
            [
                "Nombre y apellidos cliente",
                "Banco",
                "Fecha de encargo",
                "Fecha de firma",
                "Valor compra inmueble",
                "Entrada",
                "Hipoteca",
                "Comisión cobrada",
            ],
        )
        pdf_bytes = server.build_hipotecas_bdt_listado_pdf(self.conn, rows, filters=filters)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertEqual(
            server.build_hipotecas_bdt_listado_pdf_filename(filters, count=len(rows)),
            "hipotecas_listado_2025_firmada_2.pdf",
        )
        if server.PdfReader is not None:
            reader = server.PdfReader(BytesIO(pdf_bytes))
            self.assertGreaterEqual(len(reader.pages), 1)
