"""Apuntar qué busca un comprador tenía 14 campos, y nadie lo hacía.

El dato lo dijo la base de producción: **2.261 clientes y 3 demandas**, y las tres
habían entrado solas desde la web el mismo día. Ninguna la había escrito una
persona. No es que la gente no pregunte por pisos; es que apuntarlo costaba más de
lo que valía en ese momento.

El formulario largo sigue estando para cuando hace falta el detalle. Encima va uno
de cinco campos con lo que se sabe nada más colgar el teléfono: quién, su teléfono,
qué busca, dónde y hasta cuánto. El servidor ya creaba el cliente a partir del
nombre, así que darlo de alta antes era otro paso que sobraba.
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
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-11 09:00:00"
CLAVE = "Demanda1234!"


class ElFormularioRapidoTests(unittest.TestCase):
    @staticmethod
    def _html():
        return (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    @staticmethod
    def _app():
        return (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    def test_existe_y_está_antes_del_largo(self):
        html = self._html()
        self.assertIn('id="demandaRapidaForm"', html)
        self.assertLess(html.index('id="demandaRapidaForm"'), html.index('id="demandaForm"'),
                        "el rápido tiene que verse primero; si no, no lo usa nadie")

    def test_pide_cinco_campos_y_no_catorce(self):
        html = self._html()
        i = html.index('id="demandaRapidaForm"')
        bloque = html[i:html.index("</form>", i)]
        campos = sorted(set(c for c in __import__("re").findall(r'name="([a-z_]+)"', bloque)))
        self.assertEqual(campos, ["cliente_nombre", "cliente_telefono", "precio_max", "tipo", "zona"])

    def test_solo_el_nombre_es_obligatorio(self):
        html = self._html()
        i = html.index('id="demandaRapidaForm"')
        bloque = html[i:html.index("</form>", i)]
        self.assertEqual(bloque.count("required"), 1)

    def test_guarda_como_activa(self):
        app = self._app()
        i = app.index("demandaRapidaForm.addEventListener")
        self.assertIn('datos.estado = "Activa"', app[i:i + 1500])

    def test_confirma_con_palabras_lo_que_ha_apuntado(self):
        """«Guardado» no dice si se apuntó lo que uno quería."""
        app = self._app()
        i = app.index("demandaRapidaForm.addEventListener")
        self.assertIn("Apuntado.", app[i:i + 1600])


class ElAltaMinimaFuncionaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "dem.sqlite"
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
            data=json.dumps({"usuario": "dem", "password": CLAVE}).encode(),
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
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia Propia", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "we1", "workspace_id": self.ws, "empresa_id": "emp1",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("usuarios", {"id": "u1", "nombre": "Dem", "usuario": "dem", "email": "d@x.test",
                               "rol": "Administrador", "servicio": "Inmobiliaria", "activo": 1,
                               "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})

    def _post(self, cuerpo):
        req = urllib.request.Request(self.base + "/api/demandas", data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, {"raw": e.read().decode()}

    def test_con_nombre_tipo_y_zona_basta(self):
        estado, d = self._post({"empresa_nombre": "Agencia Propia", "cliente_nombre": "Marta Compradora",
                                "tipo": "Piso", "zona": "Centro", "precio_max": 200000, "estado": "Activa"})
        self.assertEqual(estado, 200, d)
        fila = self.conn.execute("SELECT tipo, zona, precio_max FROM demandas").fetchone()
        self.assertEqual((fila["tipo"], fila["zona"]), ("Piso", "Centro"))

    def test_y_da_de_alta_al_cliente_solo(self):
        """Tener que crear antes la ficha del cliente era otro paso que sobraba."""
        self._post({"empresa_nombre": "Agencia Propia", "cliente_nombre": "Marta Compradora",
                    "cliente_telefono": "+34600123456", "tipo": "Piso", "estado": "Activa"})
        fila = self.conn.execute("SELECT nombre, telefono FROM clientes WHERE nombre = 'Marta Compradora'").fetchone()
        self.assertIsNotNone(fila)
        self.assertEqual(fila["telefono"], "+34600123456")

    def test_sin_nombre_no_se_guarda_una_demanda_fantasma(self):
        estado, d = self._post({"empresa_nombre": "Agencia Propia", "tipo": "Piso", "estado": "Activa"})
        self.assertNotEqual(estado, 200, d)


if __name__ == "__main__":
    unittest.main()
