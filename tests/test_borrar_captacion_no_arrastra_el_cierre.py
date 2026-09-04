"""Borrar una captación se lleva el inmueble, y con él cosas que no se pueden perder.

`captacion_delete` borra la captación **y el inmueble**, más su checklist, sus
documentos, sus propietarios, sus visitas y sus acciones. Del inmueble cuelgan además
siete tablas que no tocaba, y entre ellas están los cierres firmados y las operaciones,
que es donde vive la comisión.

Lo que pasaba, comprobado el 2026-08-22 con un piso ya vendido: la clave ajena saltaba
en mitad del borrado y salía un 500 «API error». No se perdía nada —la transacción se
deshace— pero el usuario no sabía por qué, y en Postgres un statement fallido deja la
transacción abortada y se lleva por delante el resto de la petición.

Ahora se mira antes y se dice qué hay detrás. Lo que sí cuelga del inmueble y no tiene
valor propio —compradores interesados, servicios, eventos de embudo— se va con él, que
si no queda apuntando a una vivienda que ya no existe.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

CLAVE = "Inmo1234!"
AHORA = "2026-08-22 09:00:00"


class BorrarUnaCaptacionTests(unittest.TestCase):
    def _monta(self, con_cierre):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(conn)
            except Exception:
                pass
        ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]

        def ins(tabla, datos):
            cols = {c[1] for c in conn.execute(f"pragma table_info({tabla})")}
            d = {k: v for k, v in datos.items() if k in cols}
            conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                         f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
            conn.commit()

        b = dict(created_at=AHORA, updated_at=AHORA)
        ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1, **b))
        ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
        ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                             rol="Administrador", servicio="Inmobiliaria", activo=1,
                             password_hash=S.hash_password(CLAVE), **b))
        ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1", rol="Owner", **b))
        ins("clientes", dict(id="cli1", nombre="Comprador", empresa_id="emp1", workspace_id=ws, **b))
        ins("inmuebles", dict(id="inm1", workspace_id=ws, empresa_id="emp1", estado="Vendido",
                              direccion="Calle Larios 3", tipo_operacion="venta",
                              precio_objetivo=285000, **b))
        ins("captaciones", dict(id="cap1", workspace_id=ws, empresa_id="emp1", inmueble_id="inm1",
                                etapa="Cerrada", situacion_comercial="Vendido",
                                direccion="Calle Larios 3", **b))
        ins("inmueble_compradores", dict(id="ic1", workspace_id=ws, empresa_id="emp1",
                                         inmueble_id="inm1", cliente_id="cli1",
                                         estado="Interesado", **b))
        if con_cierre:
            ins("inmueble_cierres", dict(id="ci1", workspace_id=ws, empresa_id="emp1",
                                         inmueble_id="inm1", cliente_id="cli1",
                                         fecha_cierre="2026-07-15", tipo="venta",
                                         estado="Firmado", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
        httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        return conn, ws, httpd.server_address[1]

    def _post(self, puerto, ruta, cuerpo, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=40) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _borra(self, con_cierre):
        conn, ws, puerto = self._monta(con_cierre)
        _, _, galleta = self._post(puerto, "/api/login", {"usuario": "ana", "password": CLAVE})
        estado, cuerpo, _ = self._post(puerto, "/api/captacion_delete",
                                       {"id": "cap1", "empresa_id": "emp1", "workspace_id": ws},
                                       galleta.split(";")[0])
        return conn, estado, cuerpo

    def test_con_un_cierre_firmado_se_niega_y_explica(self):
        conn, estado, cuerpo = self._borra(con_cierre=True)
        self.assertEqual(estado, 409, cuerpo)
        self.assertIn("cierres firmados", cuerpo.get("error", ""))
        self.assertEqual(cuerpo.get("retenido"), {"cierres firmados": 1})
        # Nada se ha tocado: ni el inmueble, ni el cierre, ni su vínculo.
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM inmuebles").fetchone()[0], 1)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM inmueble_cierres c "
                         "JOIN inmuebles i ON i.id = c.inmueble_id").fetchone()[0], 1)

    def test_no_revienta_con_un_500(self):
        """Antes saltaba la clave ajena a media faena: 500 «API error», y en Postgres la
        transacción abortada se llevaba por delante el resto de la petición."""
        _, estado, cuerpo = self._borra(con_cierre=True)
        self.assertNotEqual(estado, 500, cuerpo)
        self.assertNotIn("IntegrityError", json.dumps(cuerpo))

    def test_una_captacion_sin_nada_economico_si_se_borra(self):
        conn, estado, cuerpo = self._borra(con_cierre=False)
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM inmuebles").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM captaciones").fetchone()[0], 0)

    def test_y_no_deja_compradores_apuntando_a_un_piso_que_ya_no_existe(self):
        conn, estado, _ = self._borra(con_cierre=False)
        self.assertEqual(estado, 200)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM inmueble_compradores").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
