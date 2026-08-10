"""Dos fallos que sólo se ven contra Postgres o integrando de verdad.

**1. `Decimal` sin serializar.** Desde que el dinero se guarda en `numeric`, Postgres
devuelve `Decimal`. `json_response` ya lo contemplaba, pero hay 103 `json.dumps` más
en el fichero que serializan filas directamente, y uno de ellos guarda el payload de
los documentos generados. Resultado: **el expediente completo devolvía 500 en las 13
fichas en Encargo de producción**, con `TypeError: Object of type Decimal is not JSON
serializable` en el cuerpo de la respuesta.

En SQLite no se ve: los importes vuelven como float y todo pasa. Por eso apareció
probando en producción y no en la suite.

**2. Una lista de textos donde se esperaban objetos.** `/api/inmueble_checklist_generate`
comprobaba que `tareas` fuera una lista y luego hacía `tarea.get(...)` sobre cada
elemento. Mandando `["Nota simple", "Certificado energético"]` —lo primero que escribe
cualquiera que integre contra esta API— lanzaba `AttributeError` y el cliente recibía
un 500 con el rastro de Python dentro. El navegador manda diccionarios, así que no
estaba roto en la interfaz; pero un 500 con una excepción dentro nunca es la respuesta
a una petición mal formada.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-10 09:00:00"
CLAVE = "Decimal1234!"


class ElCodificadorSeguroTests(unittest.TestCase):
    def test_un_decimal_entero_sale_como_entero(self):
        self.assertEqual(json.loads(S.json_dumps_seguro({"p": Decimal("245000")}))["p"], 245000)

    def test_un_decimal_con_céntimos_conserva_el_valor(self):
        self.assertAlmostEqual(json.loads(S.json_dumps_seguro({"p": Decimal("1234.56")}))["p"], 1234.56)

    def test_las_fechas_salen_en_iso(self):
        salida = json.loads(S.json_dumps_seguro({"f": date(2026, 8, 10), "t": datetime(2026, 8, 10, 9, 0)}))
        self.assertEqual(salida["f"], "2026-08-10")
        self.assertTrue(salida["t"].startswith("2026-08-10T09:00"))

    def test_lo_que_no_sabe_serializar_no_revienta(self):
        class Raro:
            def __repr__(self):
                return "<raro>"
        self.assertEqual(json.loads(S.json_dumps_seguro({"x": Raro()}))["x"], "<raro>")

    def test_el_dumps_estandar_si_reventaria(self):
        """Deja claro que el problema es real y no una precaución teórica."""
        with self.assertRaises(TypeError):
            json.dumps({"p": Decimal("245000")})

    def test_el_payload_de_los_documentos_usa_el_seguro(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def persist_generated_inmueble_pdf(")
        bloque = fuente[i:i + 4000]
        self.assertIn("json_dumps_seguro(payload_json)", bloque)


class ElChecklistAceptaTextosYObjetosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "chk.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self._seed()
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "chk", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            self.cookie = r.headers.get("Set-Cookie").split(";")[0]

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _seed(self):
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "we1", "workspace_id": self.ws, "empresa_id": "emp1",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("usuarios", {"id": "u1", "nombre": "Chk", "usuario": "chk", "email": "c@x.test",
                               "rol": "Administrador", "servicio": "Inmobiliaria", "activo": 1,
                               "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inm1", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Checklist 1", "estado": "Encargo",
                                "created_at": AHORA, "updated_at": AHORA})

    def _generar(self, tareas):
        req = urllib.request.Request(
            self.base + "/api/inmueble_checklist_generate",
            data=json.dumps({"inmueble_id": "inm1", "workspace_id": self.ws,
                             "etapa": "Captacion", "tareas": tareas}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _tareas_guardadas(self):
        return [r["tarea"] for r in self.conn.execute(
            "SELECT tarea FROM inmueble_checklist WHERE inmueble_id='inm1' ORDER BY tarea")]

    def test_con_objetos_sigue_funcionando(self):
        """Lo que manda el navegador hoy: no puede romperse."""
        estado, cuerpo = self._generar([{"tarea": "Nota simple", "estado": "Pendiente"}])
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._tareas_guardadas(), ["Nota simple"])

    def test_con_textos_ya_no_revienta(self):
        estado, cuerpo = self._generar(["Nota simple", "Certificado energético"])
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._tareas_guardadas(), ["Certificado energético", "Nota simple"])

    def test_mezclando_las_dos_formas(self):
        estado, cuerpo = self._generar(["Nota simple", {"tarea": "Cédula", "estado": "Hecho"}])
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._tareas_guardadas(), ["Cédula", "Nota simple"])

    def test_lo_que_no_es_ni_texto_ni_objeto_se_rechaza_con_400(self):
        """Con un 400 que explica qué pasa, no con un 500 y una excepción dentro."""
        estado, cuerpo = self._generar([123])
        self.assertEqual(estado, 400, cuerpo)
        self.assertIn("tarea", cuerpo)

    def test_los_textos_vacios_se_ignoran(self):
        estado, cuerpo = self._generar(["  ", "Nota simple"])
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._tareas_guardadas(), ["Nota simple"])


if __name__ == "__main__":
    unittest.main()
