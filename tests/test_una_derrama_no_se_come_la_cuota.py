"""La comunidad no podía pasar una derrama sin dejar de cobrar la cuota de ese mes.

Salió simulando el año de una administradora de fincas fuera del mes normal. La junta
aprueba arreglar el ascensor y hay que repartir 12.000 € en agosto. Agosto ya tiene su
cuota ordinaria de 1.200 €, y emitir la derrama contestaba:

    409 · Ya hay recibos emitidos de 2026-08. Marca «reemitir» si quieres rehacerlos.

Debajo, el índice único de la tabla era `(comunidad, vecino, periodo)`: dos recibos en el
mismo mes no cabían ni en el esquema. Y «reemitir» —la única puerta que ofrecía el aviso,
y la que ofrecía el botón— **borraba los recibos pendientes del mes**. Quien seguía esa
instrucción emitía la derrama, veía «4 recibos por 12.000 €» y se quedaba sin cobrar los
1.200 € de la cuota ordinaria. Con 200 OK y sin nada que lo dijera.

Lo que identifica un cargo dentro de un mes es su **concepto**, no el mes. Repetir el
mismo cargo sigue pidiendo confirmación y rehace sólo ése; un concepto distinto es un
cargo aparte, se avisa de lo que ya hay y se suma si se confirma. Que es lo que pasa de
verdad: en un mes puede haber la cuota, una derrama y una liquidación.
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

RAIZ = Path(__file__).resolve().parents[1]
CLAVE = "Administradora1234!"
AHORA = "2026-08-23 09:00:00"
CENSO = [("Dolores Sánchez", "1º A", 30.0), ("Manuel Ortega", "1º B", 25.0),
         ("Rocío Peña", "2º A", 25.0), ("Julián Vega", "2º B", 20.0)]
CUOTA = 1200.0
DERRAMA = 12000.0


class UnaDerramaNoSeComeLaCuotaTests(unittest.TestCase):
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
        self._ins("empresas", dict(id="emp1", nombre="Fincas Modernia", nif="B29123456",
                                   activo=1, administra_fincas=1, **b))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **b))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                                   rol="Administrador", servicio="Fincas", activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **b))
        self._ins("workspace_fincas_comunidades",
                  dict(id="com1", workspace_id=self.ws, empresa_id="emp1",
                       nombre="C.P Los Naranjos", direccion="Avenida Europa 110",
                       estado="Activa", **b))
        for i, (nombre, piso, coef) in enumerate(CENSO):
            self._ins("workspace_fincas_vecinos",
                      dict(id=f"v{i}", workspace_id=self.ws, comunidad_id="com1",
                           nombre=nombre, piso=piso, coeficiente=coef,
                           nif=f"2511111{i}A", iban="ES2321000418400000000001", **b))
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
        estado, r, _ = self._emite(CUOTA, "Cuota ordinaria agosto")
        self.assertEqual(estado, 200, r)

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

    def _emite(self, importe, concepto, periodo="2026-08", **extra):
        cuerpo = {"workspace_id": self.ws, "comunidad_id": "com1", "periodo": periodo,
                  "importe": importe, "concepto": concepto}
        cuerpo.update(extra)
        return self._post("/api/workspace_fincas_recibos_emitir", cuerpo, self.cookie)

    def _cargos(self, periodo="2026-08"):
        """Lo que se le cobra a la comunidad ese mes, por concepto."""
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return {str(f["concepto"]): (int(f["n"]), round(float(f["suma"]), 2))
                    for f in c.execute(
                        "SELECT concepto, COUNT(*) AS n, SUM(importe) AS suma "
                        "FROM workspace_fincas_recibos WHERE periodo = ? GROUP BY concepto",
                        (periodo,)).fetchall()}
        finally:
            c.close()

    # --- la derrama -------------------------------------------------------------

    def test_avisa_de_que_ya_hay_otro_cargo_ese_mes(self):
        estado, r, _ = self._emite(DERRAMA, "Derrama ascensor")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "otro_cargo_en_el_mes")

    def test_y_el_aviso_dice_qué_hay_y_qué_se_puede_hacer(self):
        """Antes decía «marca reemitir», que era justo lo que borraba la cuota."""
        _, r, _ = self._emite(DERRAMA, "Derrama ascensor")
        aviso = r.get("error", "")
        self.assertIn("Cuota ordinaria agosto", aviso)
        self.assertIn("1.200,00", aviso)
        self.assertIn("aparte", aviso)
        self.assertNotIn("reemitir", aviso)

    def test_confirmada_conviven_la_cuota_y_la_derrama(self):
        estado, r, _ = self._emite(DERRAMA, "Derrama ascensor", confirmado=True)
        self.assertEqual(estado, 200, r)
        self.assertEqual(self._cargos(), {"Cuota ordinaria agosto": (4, CUOTA),
                                          "Derrama ascensor": (4, DERRAMA)})

    def test_y_cada_propietario_paga_su_parte_de_las_dos(self):
        self._emite(DERRAMA, "Derrama ascensor", confirmado=True)
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            filas = [dict(x) for x in c.execute(
                "SELECT v.nombre, v.coeficiente, r.concepto, r.importe "
                "FROM workspace_fincas_recibos r "
                "JOIN workspace_fincas_vecinos v ON v.id = r.vecino_id").fetchall()]
        finally:
            c.close()
        self.assertEqual(len(filas), 8)
        for f in filas:
            base = DERRAMA if "Derrama" in f["concepto"] else CUOTA
            self.assertAlmostEqual(float(f["importe"]),
                                   round(base * float(f["coeficiente"]) / 100.0, 2),
                                   places=2, msg=f)

    # --- y lo que ya protegía sigue protegiendo ---------------------------------

    def test_repetir_el_mismo_cargo_sigue_pidiendo_confirmacion(self):
        """Es la forma más rápida de cobrar dos veces, y no ha dejado de serlo."""
        estado, r, _ = self._emite(CUOTA, "Cuota ordinaria agosto")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "ya_emitido")
        self.assertIn("reemitir", r.get("error", ""))

    def test_y_confirmarlo_no_duplica_el_cobro(self):
        estado, r, _ = self._emite(1500.0, "Cuota ordinaria agosto", reemitir="1")
        self.assertEqual(estado, 200, r)
        self.assertEqual(self._cargos(), {"Cuota ordinaria agosto": (4, 1500.0)})

    def test_rehacer_la_cuota_no_se_lleva_la_derrama_por_delante(self):
        """El borrado de «reemitir» se ciñe al cargo que se rehace."""
        self._emite(DERRAMA, "Derrama ascensor", confirmado=True)
        self._emite(1500.0, "Cuota ordinaria agosto", reemitir="1")
        self.assertEqual(self._cargos(), {"Cuota ordinaria agosto": (4, 1500.0),
                                          "Derrama ascensor": (4, DERRAMA)})

    def test_un_cargo_ya_cobrado_no_se_rehace(self):
        """«Reemitir» sólo toca lo pendiente: lo cobrado no se puede deshacer así."""
        # El de Dolores, que tiene el 30 %: sin decir cuál, el que sale depende del
        # orden que le apetezca a la base y la prueba falla un día de cada cuatro.
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        uno = dict(c.execute(
            "SELECT id FROM workspace_fincas_recibos WHERE vecino_id = 'v0'").fetchone())
        c.close()
        self._post("/api/workspace_fincas_recibo_estado",
                   {"workspace_id": self.ws, "id": uno["id"], "estado": "Cobrado"},
                   self.cookie)
        self._emite(1500.0, "Cuota ordinaria agosto", reemitir="1")
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            cobrados = [dict(x) for x in c.execute(
                "SELECT importe FROM workspace_fincas_recibos WHERE estado = 'Cobrado'").fetchall()]
        finally:
            c.close()
        self.assertEqual(len(cobrados), 1)
        self.assertAlmostEqual(float(cobrados[0]["importe"]), 360.0, places=2)

    def test_el_esquema_deja_sitio_a_los_dos_cargos(self):
        """El índice único era (comunidad, vecino, periodo): no cabían ni en la tabla."""
        c = S.open_sqlite_conn(str(self.db))
        try:
            indices = {r[1]: r[0] for r in c.execute(
                "SELECT sql, name FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'workspace_fincas_recibos'").fetchall()}
        finally:
            c.close()
        self.assertNotIn("idx_fincas_recibos_unico", indices)
        self.assertIn("concepto", indices.get("idx_fincas_recibos_unico_cargo", ""))

    def test_el_front_ofrece_las_dos_salidas(self):
        """Con una sola pregunta, decir que sí a la derrama borraba la cuota."""
        app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        ini = app.index('res = await postJsonWithDbRetry("/api/workspace_fincas_recibos_emitir", cuerpo);')
        trozo = app[ini:ini + 1200]
        self.assertIn("reemitir", trozo)
        self.assertIn("cargo aparte", trozo)
        self.assertIn("confirmado: true", trozo)


if __name__ == "__main__":
    unittest.main()
