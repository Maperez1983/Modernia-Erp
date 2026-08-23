"""Un coeficiente del 250 % entraba sin que nada dijera nada.

Salieron probando lo que teclea una persona con prisa. Ninguna daba error; todas
quedaban guardadas y todas descuadraban algo:

  · coeficiente -25 % o 250 % en la ficha de un vecino. El coeficiente es la parte que
    le toca de la finca (art. 5 LPH) y **multiplica directamente lo que se le cobra**:
    un 250 % le pasa dos veces y media el presupuesto entero de la comunidad, y un
    negativo le devuelve dinero cada mes.
  · cuota mensual negativa en el alta de la comunidad. Eso no es una cuota.
  · gasto de -500 € en contabilidad. El signo lo pone el tipo —Gasto o Ingreso—, así que
    un gasto negativo sumaba, descuadrando el ejercicio en silencio. Un abono se anota
    como ingreso.
  · un apunte de un billón de euros. Aquí no vale bloquear: una derrama grande es
    legítima. Lo que hace falta es que pregunte.

Las tres primeras se rechazan con 400 y el motivo. La cuarta responde 409 con
`requiere_confirmacion`, y el front lo vuelve a mandar con `confirmado: true` si la
persona dice que sí. Es la red para el dedazo y para el importe pegado con formato raro,
no un tope de negocio.
"""

import json
import os
import shutil
import subprocess
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


class CifrasQueNoPuedenSerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        self.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Fincas Modernia",
                                   nif="B29123456", activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                                   rol="Administrador", servicio="Fincas", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **base))
        self._ins("workspace_fincas_comunidades",
                  dict(id="com1", workspace_id=self.ws, empresa_id="emp1",
                       nombre="Residencial El Limonar", direccion="Av. Pintor Sorolla 4",
                       cuota_mensual=1200, **base))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
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

    def _vecino(self, coeficiente):
        return self._post("/api/workspace_fincas_vecinos",
                          {"workspace_id": self.ws, "comunidad_id": "com1",
                           "nombre": "Dolores Sánchez", "piso": "3º B",
                           "coeficiente": coeficiente}, self.cookie)

    def _apunte(self, importe, **extra):
        cuerpo = {"workspace_id": self.ws, "comunidad_id": "com1", "tipo": "Gasto",
                  "concepto": "Ascensor", "fecha": "2026-08-10", "importe": importe}
        cuerpo.update(extra)
        return self._post("/api/workspace_fincas_contabilidad", cuerpo, self.cookie)

    def _comunidad(self, **campos):
        cuerpo = {"workspace_id": self.ws, "empresa_id": "emp1",
                  "nombre": "Los Naranjos", "direccion": "C/ Larios 1"}
        cuerpo.update(campos)
        return self._post("/api/workspace_fincas_comunidades", cuerpo, self.cookie)

    # --- el coeficiente ---------------------------------------------------------

    def test_un_coeficiente_negativo_no_entra(self):
        estado, r, _ = self._vecino("-25")
        self.assertEqual(estado, 400, r)
        self.assertIn("entre 0 y 100", r.get("error", ""))

    def test_un_coeficiente_del_250_por_ciento_tampoco(self):
        """Le cobraría dos veces y media el presupuesto entero de la comunidad."""
        estado, r, _ = self._vecino("250")
        self.assertEqual(estado, 400, r)

    def test_y_no_queda_guardado(self):
        self._vecino("250")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM workspace_fincas_vecinos").fetchone()[0], 0)

    def test_un_coeficiente_normal_sigue_entrando(self):
        estado, r, _ = self._vecino("6,25")
        self.assertEqual(estado, 200, r)
        fila = dict(self.conn.execute(
            "SELECT coeficiente FROM workspace_fincas_vecinos").fetchone())
        self.assertAlmostEqual(float(fila["coeficiente"]), 6.25, places=2)

    def test_los_extremos_valen(self):
        """0 y 100 son válidos: un trastero sin coeficiente, o una finca de un dueño."""
        for valor in ("0", "100"):
            with self.subTest(valor=valor):
                self.assertEqual(self._vecino(valor)[0], 200)

    # --- la cuota ---------------------------------------------------------------

    def test_una_comunidad_no_cobra_una_cuota_negativa(self):
        estado, r, _ = self._comunidad(cuota_mensual="-1200")
        self.assertEqual(estado, 400, r)
        self.assertIn("negativa", r.get("error", ""))

    def test_ni_un_honorario_negativo(self):
        self.assertEqual(self._comunidad(honorario_mensual="-90")[0], 400)

    def test_una_cuota_normal_sigue_entrando(self):
        self.assertEqual(self._comunidad(cuota_mensual="1.450,00")[0], 200)

    # --- el importe del apunte --------------------------------------------------

    def test_un_gasto_negativo_no_entra(self):
        """Sumaba en vez de restar: el signo lo pone el tipo, no el importe."""
        estado, r, _ = self._apunte(-500)
        self.assertEqual(estado, 400, r)
        self.assertIn("positivo", r.get("error", ""))

    def test_un_gasto_normal_entra(self):
        self.assertEqual(self._apunte(2450.75)[0], 200)

    def test_una_cifra_imposible_pide_confirmacion_en_vez_de_bloquear(self):
        """Una derrama grande es legítima; lo que no vale es que entre sin preguntar."""
        estado, r, _ = self._apunte(1_000_000_000_000)
        self.assertEqual(estado, 409, r)
        self.assertTrue(r.get("requiere_confirmacion"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM workspace_fincas_contabilidad").fetchone()[0],
            0)

    def test_y_confirmada_entra(self):
        estado, r, _ = self._apunte(1_000_000_000_000, confirmado=True)
        self.assertEqual(estado, 200, r)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM workspace_fincas_contabilidad").fetchone()[0],
            1)

    def test_justo_por_debajo_del_tope_no_pregunta(self):
        self.assertEqual(self._apunte(S.FINCAS_IMPORTE_QUE_PIDE_CONFIRMACION)[0], 200)

    # --- el front sabe reintentar -----------------------------------------------

    def test_todos_los_formularios_pasan_por_el_mismo_sitio(self):
        """Nadie llama al endpoint por su cuenta saltándose la confirmación."""
        app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("const guardarApunteDeComunidad", app)
        # La ruta se nombra una sola vez —dentro del ayudante— y los tres formularios
        # que guardan un apunte pasan por él.
        self.assertEqual(app.count('"/api/workspace_fincas_contabilidad"'), 1)
        self.assertEqual(app.count("guardarApunteDeComunidad("), 3)

    def test_el_front_pregunta_y_vuelve_a_mandarlo_confirmado(self):
        """Sin esto el 409 sería un callejón sin salida: no habría forma de guardarlo.

        Se ejecuta la función real de `app.js` en node, con el `fetch` y el `confirm`
        sustituidos, y se mira lo que hace en los cuatro casos que importan."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node no está disponible")
        r = subprocess.run([node, str(Path(__file__).with_name("_reintento_apunte.js"))],
                           capture_output=True, text=True, cwd=str(RAIZ))
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        salida = json.loads(r.stdout)

        # 1. Un apunte normal: una llamada y a correr.
        self.assertEqual(salida["normal"]["llamadas"], 1)
        self.assertIsNone(salida["normal"]["preguntado"])

        # 2. Cifra imposible que la persona confirma: se reintenta con `confirmado`,
        #    sin perder nada de lo que había tecleado.
        confirma = salida["confirma"]
        self.assertEqual(confirma["llamadas"], 2)
        self.assertIs(confirma["segunda"]["confirmado"], True)
        self.assertEqual(confirma["segunda"]["concepto"], "Derrama")
        self.assertIn("es mucho", confirma["preguntado"])
        self.assertEqual(confirma["devuelto"], {"ok": True, "id": "a2"})

        # 3. Dice que no: no se guarda, y sobre todo no revienta con un error que
        #    parecería un fallo del CRM.
        self.assertEqual(salida["cancela"]["llamadas"], 1)
        self.assertIsNone(salida["cancela"]["excepcion"])
        self.assertIsNone(salida["cancela"]["devuelto"])

        # 4. Un rechazo de verdad sí sube, para que el formulario lo enseñe.
        self.assertIsNone(salida["negativo"]["preguntado"])
        self.assertIn("positivo", salida["negativo"]["excepcion"])


if __name__ == "__main__":
    unittest.main()
