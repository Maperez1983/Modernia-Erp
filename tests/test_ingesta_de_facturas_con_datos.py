"""Ingesta de facturas con los datos ya leídos y la sociedad a la que se lleva (2026-09-19).

Para cargar la contabilidad de Modernia Home & Investment (44 facturas emitidas hechas
en Excel, con su PDF) la ingesta solo aceptaba el PDF y fiaba número, fecha e importes
al OCR; y el cliente lo deducía del NIF del tercero, que en una venta es el comprador,
no la sociedad a la que se le lleva la contabilidad. Ahora admite los datos leídos del
Excel (mandan sobre el OCR) y el cliente explícito, que tiene que ser del workspace de
la empresa.
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
CLAVE = "clave-de-prueba-ingesta"


class IngestaConDatosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = Path(cls.tmp.name) / "ingesta.sqlite"
        S.ensure_tables(db)
        cls.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        cls.conn.execute("PRAGMA foreign_keys = OFF")
        t = {"created_at": NOW, "updated_at": NOW}
        for tabla, fila in (
            ("empresas", {"id": "empMHI", "nombre": "Modernia Home & Investment", "activo": 1, **t}),
            ("workspaces", {"id": "wsA", "nombre": "Modernia", "slug": "modernia-p", "estado": "Activo", **t}),
            ("workspaces", {"id": "wsB", "nombre": "Otro", "slug": "otro-p", "estado": "Activo", **t}),
            ("workspace_empresas", {"id": "we1", "workspace_id": "wsA", "empresa_id": "empMHI", **t}),
            ("clientes", {"id": "cliMHI", "nombre": "MODERNIA HOME INVESTMENT SL", "nif": "B70730742", "workspace_id": "wsA", **t}),
            ("clientes", {"id": "cliComprador", "nombre": "Antonia Bernal Naranjo", "nif": "24848050H", "workspace_id": "wsA", "empresa_id": "empMHI", **t}),
            ("clientes", {"id": "cliOtro", "nombre": "De otro workspace", "workspace_id": "wsB", **t}),
        ):
            validas = {r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")}
            d = {k: v for k, v in fila.items() if k in validas}
            cls.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        # Como en producción: el workspace de plataforma tiene la empresa técnica Verifika2,
        # y el disparador descarta ese workspace al deducir el de una fila.
        plataforma = cls.conn.execute("SELECT id FROM workspaces WHERE nombre = 'Verifika²' LIMIT 1").fetchone()["id"]
        cls.conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) VALUES ('empTec', 'Verifika2', 1, ?, ?)", (NOW, NOW))
        cls.conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('weT', ?, 'empTec', ?, ?)",
                         (plataforma, NOW, NOW))
        # Como en producción (fase 1): workspace_id por disparador desde la empresa.
        for tabla in ("gestoria_facturas", "gestoria_asientos"):
            S._ambito_ws_prepara_tabla_sqlite(cls.conn, tabla)
        cls.conn.commit()
        cls._prev = (getattr(S.Handler, "db_path", None), S.INGEST_API_KEY, S.s3_get_object_bytes)
        S.Handler.db_path = str(db)
        S.INGEST_API_KEY = CLAVE
        # Un "PDF" que no se puede leer: los datos tienen que venir del Excel.
        # (distinto por fichero: el CRM descarta con razón un mismo fichero subido dos veces).
        S.s3_get_object_bytes = lambda key: (b"no es un pdf legible " + key.encode(), "")
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        S.Handler.db_path, S.INGEST_API_KEY, S.s3_get_object_bytes = cls._prev
        cls.tmp.cleanup()

    def _ingesta(self, **extra):
        cuerpo = {"empresa_id": "empMHI", "s3_key": f"facturas_inbox/empMHI/emitidas/2025/{extra.pop('fichero', 'f.pdf')}", **extra}
        req = urllib.request.Request(self.base + "/api/ingest_facturas_ocr", data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json", "X-API-Key": CLAVE}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_los_datos_del_excel_mandan_y_la_factura_es_de_la_sociedad(self):
        status, data = self._ingesta(
            fichero="02.pdf", numero="02/2025", fecha="2025-01-30", nif="24848050H", tercero="Antonia Bernal Naranjo",
            descripcion="Comisión compra venta calle Gallardo nº18", base_imponible=3000, cuota_iva=630, total=3630,
            iva_pct=21, cliente_id="cliMHI",
        )
        self.assertEqual(status, 200, data)
        f = self.conn.execute("SELECT * FROM gestoria_facturas WHERE numero = '02/2025'").fetchone()
        self.assertEqual((f["cliente_id"], f["tipo"], f["fecha_emision"], float(f["total"]), float(f["base_imponible"])),
                         ("cliMHI", "venta", "2025-01-30", 3630.0, 3000.0))
        self.assertEqual(f["workspace_id"], "wsA")
        # El asiento lleva la comisión a prestación de servicios (705), no a mercaderías.
        lineas = {r["cuenta"][:3]: (float(r["debe"] or 0), float(r["haber"] or 0)) for r in self.conn.execute(
            "SELECT l.cuenta, l.debe, l.haber FROM gestoria_asiento_lineas l JOIN gestoria_asientos a ON a.id = l.asiento_id "
            "WHERE a.factura_id = ?", (f["id"],))}
        self.assertEqual(lineas["705"], (0.0, 3000.0))
        self.assertEqual(lineas["477"], (0.0, 630.0))
        self.assertEqual(lineas["430"], (3630.0, 0.0))

    def test_con_sin_ocr_no_se_llama_al_ocr(self):
        llamadas = []
        previo = (S.extract_pdf_text, S.ocr_pdf_all_pages)
        S.extract_pdf_text = lambda *a, **k: llamadas.append("pdf") or ("", "", "x")
        S.ocr_pdf_all_pages = lambda *a, **k: llamadas.append("ocr") or ("", "")
        self.addCleanup(lambda: setattr(S, "extract_pdf_text", previo[0]) or setattr(S, "ocr_pdf_all_pages", previo[1]))
        status, data = self._ingesta(fichero="t.pdf", numero="T-1", fecha="2026-02-01", tercero="Gasolinera",
                                     base_imponible=40, cuota_iva=0, total=40, cliente_id="cliMHI", sin_ocr=True)
        self.assertEqual(status, 200, data)
        self.assertEqual(llamadas, [])

    def test_un_cliente_de_otro_workspace_se_rechaza(self):
        status, data = self._ingesta(fichero="x.pdf", numero="99/2025", fecha="2025-02-01", total=121,
                                     base_imponible=100, cuota_iva=21, cliente_id="cliOtro")
        self.assertEqual(status, 400, data)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM gestoria_facturas WHERE numero = '99/2025'").fetchone())

    def test_sin_datos_y_con_un_pdf_ilegible_sigue_fallando(self):
        status, _data = self._ingesta(fichero="y.pdf")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
