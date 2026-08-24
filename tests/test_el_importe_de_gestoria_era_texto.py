"""Un apunte de 2.450,75 € contaba como 2,45 € al sumarlo.

El importe de un apunte de contabilidad de gestoría entraba tal cual venía del
formulario, sin pasar por el analizador de importes. La columna es `REAL`, así que un
importe tecleado **en español normal** se guardaba como texto:

    guardado: '2.450,75'

Y SQLite convierte ese texto a número cuando lo suma, quedándose con lo que hay antes
del punto:

    2.450,75 € + 100,00 €  =  102,45 €

O sea que el panel cuadraba solo, con dos mil cuatrocientos cincuenta euros convertidos
en dos euros con cuarenta y cinco. No daba error, no daba aviso, y el apunte se veía bien
en su ficha: sólo fallaba al sumar.

Es la misma familia que el importe en formato inglés que se arregló en tres analizadores
al principio de esta campaña. Éste se quedó fuera porque no analizaba nada: pasaba el
valor crudo.

Los otros dos criterios son los que ya se fijaron en fincas y se aplican igual aquí: los
negativos se rechazan —el signo lo pone el tipo de apunte, no el número— y lo absurdo se
pregunta por encima del tope. Y va en los dos caminos, alta y edición, porque cambiar el
importe de un apunte guardado entraba por la otra puerta.
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

CLAVE = "Gestora1234!"
AHORA = "2026-08-24 09:00:00"


class ElImporteDeGestoriaEraTextoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        b = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Gestoría Modernia",
                                   nif="B29123456", activo=1, **b))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **b))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                                   rol="Administrador", servicio="Gestoria", activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]
        _, _, galleta = self._post("/api/login", {"usuario": "ana", "password": CLAVE})
        self.cookie = galleta.split(";")[0]

    def _ins(self, tabla, datos):
        cols = {c[1] for c in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _post(self, ruta, cuerpo, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"},
                                    method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _apunte(self, importe, concepto="Minuta", **extra):
        cuerpo = {"workspace_id": self.ws, "empresa_id": "emp1", "fecha": "2026-08-10",
                  "concepto": concepto, "tipo": "Gasto", "importe": importe}
        cuerpo.update(extra)
        return self._post("/api/gestoria_contabilidad", cuerpo, self.cookie)

    def _guardado(self):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(
                "SELECT concepto, importe FROM gestoria_contabilidad").fetchall()]
        finally:
            c.close()

    def _suma(self):
        c = S.open_sqlite_conn(str(self.db))
        try:
            return c.execute("SELECT COALESCE(SUM(importe), 0) "
                             "FROM gestoria_contabilidad").fetchone()[0]
        finally:
            c.close()

    # --- el importe se guarda como número -------------------------------------------

    def test_un_importe_en_español_se_guarda_como_numero(self):
        estado, r, _ = self._apunte("2.450,75")
        self.assertEqual(estado, 200, r)
        self.assertIsInstance(self._guardado()[0]["importe"], float)
        self.assertAlmostEqual(self._guardado()[0]["importe"], 2450.75, places=2)

    def test_y_uno_pegado_de_un_excel_en_ingles_tambien(self):
        self._apunte("1,234.56")
        self.assertAlmostEqual(self._guardado()[0]["importe"], 1234.56, places=2)

    def test_y_entonces_la_suma_sale_bien(self):
        """Era el fallo entero: 2.450,75 + 100 daban 102,45."""
        self._apunte("2.450,75", "uno")
        self._apunte("1,234.56", "dos")
        self._apunte(100, "tres")
        self.assertAlmostEqual(self._suma(), 3785.31, places=2)

    def test_un_importe_que_no_es_un_importe_no_entra(self):
        estado, r, _ = self._apunte("dos mil")
        self.assertEqual(estado, 400, r)
        self.assertEqual(self._guardado(), [])

    # --- los criterios que ya se fijaron en fincas -------------------------------------

    def test_un_importe_negativo_no_entra(self):
        estado, r, _ = self._apunte(-500)
        self.assertEqual(estado, 400, r)
        self.assertIn("positivo", r.get("error", ""))
        self.assertEqual(self._guardado(), [])

    def test_una_cifra_absurda_se_pregunta(self):
        estado, r, _ = self._apunte(1_000_000_000_000)
        self.assertEqual(estado, 409, r)
        self.assertTrue(r.get("requiere_confirmacion"))
        self.assertEqual(self._guardado(), [])

    def test_y_confirmada_entra(self):
        self.assertEqual(self._apunte(1_000_000_000_000, confirmado=True)[0], 200)

    def test_justo_por_debajo_del_tope_no_pregunta(self):
        self.assertEqual(self._apunte(S.FINCAS_IMPORTE_QUE_PIDE_CONFIRMACION)[0], 200)

    # --- y en la edición, que es la otra puerta ----------------------------------------

    def test_editar_el_importe_pasa_por_el_mismo_control(self):
        self._apunte(100)
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        uno = dict(c.execute("SELECT id FROM gestoria_contabilidad").fetchone())
        c.close()
        estado, r, _ = self._post("/api/gestoria_contabilidad_update",
                                  {"workspace_id": self.ws, "empresa_id": "emp1",
                                   "id": uno["id"], "importe": "2.450,75"}, self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertAlmostEqual(self._guardado()[0]["importe"], 2450.75, places=2)

    def test_y_un_negativo_tampoco_entra_editando(self):
        self._apunte(100)
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        uno = dict(c.execute("SELECT id FROM gestoria_contabilidad").fetchone())
        c.close()
        estado, r, _ = self._post("/api/gestoria_contabilidad_update",
                                  {"workspace_id": self.ws, "empresa_id": "emp1",
                                   "id": uno["id"], "importe": -50}, self.cookie)
        self.assertEqual(estado, 400, r)
        self.assertAlmostEqual(self._guardado()[0]["importe"], 100.0, places=2)

    def test_editar_otra_cosa_no_toca_el_importe(self):
        self._apunte("2.450,75")
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        uno = dict(c.execute("SELECT id FROM gestoria_contabilidad").fetchone())
        c.close()
        self._post("/api/gestoria_contabilidad_update",
                   {"workspace_id": self.ws, "empresa_id": "emp1", "id": uno["id"],
                    "concepto": "Minuta rectificada"}, self.cookie)
        fila = self._guardado()[0]
        self.assertEqual(fila["concepto"], "Minuta rectificada")
        self.assertAlmostEqual(fila["importe"], 2450.75, places=2)


if __name__ == "__main__":
    unittest.main()
