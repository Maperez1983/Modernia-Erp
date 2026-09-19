"""Lector de facturas con IA (2026-09-19).

El OCR de siempre leía mal los gastos de GAPP (IVA a 0, sin proveedor ni NIF, sin
distinguir tique de factura) y hubo que leerlos a mano. El lector con IA devuelve los
datos y su confianza, y la regla factura/tique decide qué IVA se deduce: solo la factura
completa a nombre de la empresa; el tique, el justificante o la factura a nombre de otro
van enteros al gasto y con alerta de revisión.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

NOW = "2026-09-19 10:00:00"
CLAVE = "clave-de-prueba-lector"
NIF = "B23902240"


def lee(data, tipo="compra"):
    return S.interpretar_lectura_factura_ia(data, tipo_factura=tipo, empresa_nif=NIF)


class ReglaFacturaTiqueTests(unittest.TestCase):
    def test_factura_a_nombre_de_la_empresa_deduce_iva(self):
        parsed, motivos = lee({"tipo": "factura", "fecha": "2026-02-12", "numero": "329090181",
                               "emisor_nombre": "Petroprix", "emisor_nif": "B-93.000.001", "destinatario_nif": "b23902240",
                               "base_imponible": 7.89, "cuota_iva": 1.66, "iva_pct": 21, "total": 9.55, "confianza": "alta"})
        self.assertEqual((parsed["base_imponible"], parsed["cuota_iva"], parsed["total"]), (7.89, 1.66, 9.55))
        self.assertEqual(parsed["nif"], "B93000001")
        self.assertEqual(motivos, [])

    def test_tique_va_entero_al_gasto(self):
        parsed, motivos = lee({"tipo": "ticket", "base_imponible": 11.45, "cuota_iva": 1.15, "total": 12.6, "confianza": "alta"})
        self.assertEqual((parsed["base_imponible"], parsed["cuota_iva"], parsed["total"]), (12.6, 0.0, 12.6))
        self.assertIn("tique: IVA no deducible, comprobar que es gasto de la empresa", motivos)

    def test_factura_a_nombre_de_otro(self):
        parsed, motivos = lee({"tipo": "factura", "destinatario_nif": "74881982P", "base_imponible": 49.57,
                               "cuota_iva": 10.41, "total": 59.98, "confianza": "alta"})
        self.assertEqual(parsed["cuota_iva"], 0.0)
        self.assertIn("factura a nombre de otra persona: IVA no deducible", motivos)

    def test_abono_en_negativo_y_proforma(self):
        parsed, motivos = lee({"tipo": "abono", "destinatario_nif": NIF, "base_imponible": 20.72, "cuota_iva": 4.35,
                               "total": 25.07, "confianza": "alta"})
        self.assertEqual((parsed["base_imponible"], parsed["cuota_iva"], parsed["total"]), (-20.72, -4.35, -25.07))
        self.assertIn("abono o rectificativa", motivos)
        _p, motivos = lee({"tipo": "proforma", "total": 10.5, "confianza": "alta"})
        self.assertIn("proforma o pretique: no es factura, no debería contabilizarse", motivos)

    def test_emitida_toma_al_cliente_como_tercero(self):
        parsed, motivos = lee({"tipo": "factura", "emisor_nif": NIF, "destinatario_nombre": "KONE ELEVADORES S.A.",
                               "destinatario_nif": "A28791069", "base_imponible": 1375, "cuota_iva": 288.75, "total": 1663.75,
                               "confianza": "alta"}, tipo="venta")
        self.assertEqual((parsed["tercero"], parsed["nif"], parsed["cuota_iva"]), ("KONE ELEVADORES S.A.", "A28791069", 288.75))
        self.assertEqual(motivos, [])

    def test_confianza_baja_pide_revision(self):
        _p, motivos = lee({"tipo": "factura", "destinatario_nif": NIF, "total": 358.4, "base_imponible": 325.82,
                           "cuota_iva": 32.58, "confianza": "baja", "notas": "foto desenfocada"})
        self.assertIn("lectura dudosa: documento poco legible, pedir copia", motivos)
        self.assertIn("nota del lector: foto desenfocada", motivos)


class AltaConLectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = Path(cls.tmp.name) / "lector.sqlite"
        S.ensure_tables(db)
        cls.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        cls.conn.execute("PRAGMA foreign_keys = OFF")
        t = {"created_at": NOW, "updated_at": NOW}
        plataforma = cls.conn.execute("SELECT id FROM workspaces WHERE nombre = 'Verifika²' LIMIT 1").fetchone()["id"]
        for tabla, fila in (
            ("empresas", {"id": "empTec", "nombre": "Verifika2", "activo": 1, **t}),
            ("workspace_empresas", {"id": "weT", "workspace_id": plataforma, "empresa_id": "empTec", **t}),
            ("empresas", {"id": "empG", "nombre": "GAPP", "nif": NIF, "activo": 1, **t}),
            ("workspaces", {"id": "wsA", "nombre": "Modernia", "slug": "modernia-lec", "estado": "Activo", **t}),
            ("workspace_empresas", {"id": "we1", "workspace_id": "wsA", "empresa_id": "empG", **t}),
            ("clientes", {"id": "cliG", "nombre": "GAPP SL", "workspace_id": "wsA", **t}),
        ):
            validas = {r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")}
            d = {k: v for k, v in fila.items() if k in validas}
            cls.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        for tabla in ("gestoria_facturas", "gestoria_asientos"):
            S._ambito_ws_prepara_tabla_sqlite(cls.conn, tabla)
        cls.conn.commit()
        cls._prev = (getattr(S.Handler, "db_path", None), S.INGEST_API_KEY, S.s3_get_object_bytes,
                     S.factura_ia_disponible, S.call_openai_extract_factura_vision,
                     S.external_ocr_available, S.docai_available, S.ocr_image_file)
        S.Handler.db_path = str(db)
        S.INGEST_API_KEY = CLAVE
        S.s3_get_object_bytes = lambda key: (b"\xff\xd8foto " + key.encode(), "")
        S.factura_ia_disponible = lambda: True
        S.external_ocr_available = lambda: False
        S.docai_available = lambda: False
        S.ocr_image_file = lambda *a, **k: ("", "sin tesseract en la prueba")
        cls.respuesta_ia = {}
        S.call_openai_extract_factura_vision = lambda *a, **k: (cls.respuesta_ia, "" if cls.respuesta_ia else "sin IA")
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        (S.Handler.db_path, S.INGEST_API_KEY, S.s3_get_object_bytes, S.factura_ia_disponible,
         S.call_openai_extract_factura_vision, S.external_ocr_available, S.docai_available, S.ocr_image_file) = cls._prev
        cls.tmp.cleanup()

    def _alta(self, fichero):
        req = urllib.request.Request(self.base + "/api/ingest_facturas_ocr", data=json.dumps({
            "empresa_id": "empG", "s3_key": f"facturas_inbox/empG/recibidas/2026/{fichero}", "tipo": "RECIBIDAS",
            "cliente_id": "cliG"}).encode(), headers={"Content-Type": "application/json", "X-API-Key": CLAVE}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_un_tique_leido_por_la_ia(self):
        type(self).respuesta_ia = {"tipo": "ticket", "fecha": "2026-02-23", "numero": "FS 2601A01/0015497",
                                   "emisor_nombre": "F1 Puerto Banús", "emisor_nif": "B11111111",
                                   "base_imponible": 11.45, "cuota_iva": 1.15, "iva_pct": 10, "total": 12.6,
                                   "concepto": "Consumición de bebidas", "confianza": "alta"}
        status, data = self._alta("bebida.jpeg")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["ocr_method"], "ia_vision")
        self.assertIn("tique: IVA no deducible, comprobar que es gasto de la empresa", data["revision_motivos"])
        f = self.conn.execute("SELECT * FROM gestoria_facturas WHERE id = ?", (data["factura_id"],)).fetchone()
        self.assertEqual((float(f["base_imponible"]), float(f["cuota_iva"]), float(f["total"]), f["revision_estado"]),
                         (12.6, 0.0, 12.6, "pendiente"))
        cuentas = {r["cuenta"] for r in self.conn.execute(
            "SELECT l.cuenta FROM gestoria_asiento_lineas l JOIN gestoria_asientos a ON a.id = l.asiento_id WHERE a.factura_id = ?",
            (data["factura_id"],))}
        self.assertNotIn("472", cuentas)

    def test_si_la_ia_falla_se_avisa(self):
        type(self).respuesta_ia = {}
        status, data = self._alta("ilegible.jpeg")
        # Sin IA y sin texto de OCR no hay datos: se rechaza como antes.
        self.assertEqual(status, 400, data)


if __name__ == "__main__":
    unittest.main()
