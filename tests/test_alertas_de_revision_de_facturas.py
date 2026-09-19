"""Alertas de revisión de facturas (2026-09-19).

Petición del usuario al cargar los gastos de GAPP: ante un tique, una factura que no se
lee bien o unos importes que no cuadran, el CRM tiene que avisar para que alguien la
revise y anote el apunte manual, en vez de contabilizarla a ciegas. La factura nace
"pendiente" con sus motivos; se lista en Validación y en el inicio de gestoría; y solo
se marca revisada con una nota que diga qué se comprobó o corrigió.
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
PASSWORD = "Secreto123!"
CLAVE = "clave-de-prueba-alertas"


class MotivosTests(unittest.TestCase):
    def _motivos(self, **kw):
        base = dict(payload={}, parsed={}, tipo_factura="compra", method="tesseract", text="", empresa_id="x")
        base.update(kw)
        return S.motivos_revision_factura(None, **base)

    def test_una_factura_limpia_no_tiene_motivos(self):
        self.assertEqual(self._motivos(
            method="datos_aportados",
            parsed={"numero": "1", "fecha": "2026-01-01", "nif": "B11111111", "base_imponible": 100, "cuota_iva": 21, "total": 121},
        ), [])

    def test_lo_que_el_ocr_no_pudo_leer(self):
        self.assertIn("lectura dudosa: el documento no tiene texto legible", self._motivos(parsed={"nif": "B1"}))
        motivos = self._motivos(text="algo", parsed={"nif": "B1", "total": 10})
        self.assertIn("lectura dudosa: no se pudo leer número, fecha", motivos)

    def test_importes_que_no_cuadran_y_sin_nif(self):
        motivos = self._motivos(method="datos_aportados", parsed={
            "numero": "1", "fecha": "2026-01-01", "base_imponible": 480, "cuota_iva": 100.8, "total": 580})
        self.assertTrue(any(m.startswith("importes que no cuadran") for m in motivos))
        self.assertIn("sin NIF del proveedor", motivos)

    def test_los_motivos_de_la_carga_se_suman_sin_repetirse(self):
        motivos = self._motivos(
            method="datos_aportados",
            payload={"revision_motivos": ["tique: IVA no deducible", "tique: IVA no deducible"]},
            parsed={"numero": "1", "fecha": "2026-01-01", "total": 5, "base_imponible": 5},
        )
        self.assertEqual(motivos.count("tique: IVA no deducible"), 1)


class AlertasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = Path(cls.tmp.name) / "alertas.sqlite"
        S.ensure_tables(db)
        cls.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        cls.conn.execute("PRAGMA foreign_keys = OFF")
        t = {"created_at": NOW, "updated_at": NOW}
        plataforma = cls.conn.execute("SELECT id FROM workspaces WHERE nombre = 'Verifika²' LIMIT 1").fetchone()["id"]
        for tabla, fila in (
            ("empresas", {"id": "empTec", "nombre": "Verifika2", "activo": 1, **t}),
            ("workspace_empresas", {"id": "weT", "workspace_id": plataforma, "empresa_id": "empTec", **t}),
            ("empresas", {"id": "empG", "nombre": "GAPP", "nif": "B23902240", "activo": 1, **t}),
            ("empresas", {"id": "empO", "nombre": "Otra", "activo": 1, **t}),
            ("workspaces", {"id": "wsA", "nombre": "Modernia", "slug": "modernia-al", "estado": "Activo", **t}),
            ("workspaces", {"id": "wsB", "nombre": "Otro", "slug": "otro-al", "estado": "Activo", **t}),
            ("workspace_empresas", {"id": "we1", "workspace_id": "wsA", "empresa_id": "empG", **t}),
            ("workspace_empresas", {"id": "we2", "workspace_id": "wsB", "empresa_id": "empO", **t}),
            ("clientes", {"id": "cliG", "nombre": "GAPP SL", "workspace_id": "wsA", **t}),
            ("usuarios", {"id": "u1", "nombre": "Gestor", "usuario": "gestor", "email": "g@a.test", "rol": "Administrador",
                          "servicio": "Todos", "activo": 1, "password_hash": S.hash_password(PASSWORD), **t}),
            ("workspace_miembros", {"id": "wm1", "workspace_id": "wsA", "usuario_id": "u1", "rol": "Administrador", **t}),
        ):
            validas = {r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")}
            d = {k: v for k, v in fila.items() if k in validas}
            cls.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        for tabla in ("gestoria_facturas", "gestoria_asientos"):
            S._ambito_ws_prepara_tabla_sqlite(cls.conn, tabla)
        cls.conn.commit()
        cls._prev = (getattr(S.Handler, "db_path", None), S.INGEST_API_KEY, S.s3_get_object_bytes)
        S.Handler.db_path = str(db)
        S.INGEST_API_KEY = CLAVE
        S.s3_get_object_bytes = lambda key: (b"tique " + key.encode(), "")
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(cls.base + "/api/login", data=json.dumps({"usuario": "gestor", "password": PASSWORD}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            cls.cookie = r.headers.get("Set-Cookie").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        S.Handler.db_path, S.INGEST_API_KEY, S.s3_get_object_bytes = cls._prev
        cls.tmp.cleanup()

    def _pide(self, ruta, cuerpo=None, *, clave=False):
        cab = {"Content-Type": "application/json"}
        if clave:
            cab["X-API-Key"] = CLAVE
        else:
            cab["Cookie"] = self.cookie
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                     headers=cab, method="POST" if cuerpo is not None else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _alta(self, numero, **extra):
        return self._pide("/api/ingest_facturas_ocr", {
            "empresa_id": "empG", "s3_key": f"facturas_inbox/empG/recibidas/2026/{numero}.jpeg", "tipo": "RECIBIDAS",
            "cliente_id": "cliG", "numero": numero, "fecha": "2026-02-23", "tercero": "Bar", "descripcion": "Bebidas",
            "base_imponible": 12.6, "cuota_iva": 0, "total": 12.6, "sin_ocr": True, **extra,
        }, clave=True)

    def test_un_tique_nace_pendiente_y_se_revisa_con_nota(self):
        status, data = self._alta("T-100", nif="B99999999", revision_motivos=["tique: IVA no deducible"])
        self.assertEqual(status, 200, data)
        self.assertEqual(data["revision_motivos"], ["tique: IVA no deducible"])
        fid = data["factura_id"]
        status, lista = self._pide("/api/gestoria_facturas_revision?workspace_id=wsA")
        self.assertEqual(status, 200, lista)
        fila = next(r for r in lista["rows"] if r["id"] == fid)
        self.assertEqual(fila["revision_estado"], "pendiente")
        self.assertEqual(fila["revision_motivos"], ["tique: IVA no deducible"])
        self.assertTrue(fila["asiento_id"])
        self.assertEqual(lista["por_cliente"][0]["cliente_nombre"], "GAPP SL")
        # Sin nota no se da por revisada.
        status, err = self._pide("/api/gestoria_factura_revision", {"factura_id": fid, "workspace_id": "wsA"})
        self.assertEqual(status, 400, err)
        status, ok = self._pide("/api/gestoria_factura_revision",
                                {"factura_id": fid, "workspace_id": "wsA", "nota": "Consumición del equipo en obra"})
        self.assertEqual(status, 200, ok)
        fila = self.conn.execute("SELECT * FROM gestoria_facturas WHERE id = ?", (fid,)).fetchone()
        self.assertEqual((fila["revision_estado"], fila["revision_nota"], fila["revision_por"]),
                         ("revisada", "Consumición del equipo en obra", "gestor"))
        status, lista = self._pide("/api/gestoria_facturas_revision?workspace_id=wsA")
        self.assertNotIn(fid, [r["id"] for r in lista["rows"]])

    def test_una_factura_limpia_no_genera_alerta(self):
        status, data = self._alta("F-200", nif="B99999999", base_imponible=100, cuota_iva=21, total=121)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["revision_motivos"], [])
        fila = self.conn.execute("SELECT revision_estado FROM gestoria_facturas WHERE id = ?", (data["factura_id"],)).fetchone()
        self.assertIsNone(fila["revision_estado"])

    def test_no_se_toca_la_factura_de_otro_workspace(self):
        status, data = self._alta("T-300", revision_motivos=["tique: IVA no deducible"])
        status, err = self._pide("/api/gestoria_factura_revision",
                                 {"factura_id": data["factura_id"], "workspace_id": "wsB", "nota": "x"})
        self.assertIn(status, (403, 404), err)
        status, err = self._pide("/api/gestoria_facturas_revision?workspace_id=wsB")
        self.assertEqual(status, 403, err)


if __name__ == "__main__":
    unittest.main()
