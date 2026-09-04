"""Un acuerdo salía «no aprobado» y un mes después estaba aprobado, sin que el CRM lo supiera.

Al propietario ausente debidamente citado que, informado del acuerdo, **no manifieste su
discrepancia en 30 días naturales**, se le computa el voto a favor (LPH art. 17.8). Es la
regla que hace posible la unanimidad en una comunidad donde nunca vienen todos, y el CRM
no la tenía: dictaminaba con los votos del día de la junta y ahí se quedaba.

Lo que eso provocaba, con una comunidad de cinco y uno que no viene:

    Modificar los estatutos · unanimidad · 75 % de propietarios → NO APROBADO

Cuando la verdad es que ese punto queda aprobado el día 31 si el ausente calla. El acta
salía diciendo lo contrario y nadie volvía a mirarla.

Ahora cada acuerdo lleva las dos cifras —la del día y la del cómputo—, el plazo con su
fecha de vencimiento, y un `firme` que dice si el resultado ya no puede cambiar. Tres
cosas que no se dan por supuestas:

- **El plazo arranca cuando se comunica el acta** (art. 9.1.h y 19.3), no el día de la
  junta. Sin esa fecha el plazo no ha empezado y nada es firme.
- **No se aplica a todo.** El propio artículo lo excluye cuando el coste no se puede
  repercutir a quien no votó a favor —las energías renovables del 17.1, por ejemplo—. Va
  por tipo de acuerdo y es editable, como el resto del catálogo.
- **Discrepar es de ausentes.** A quien asistió no se le anota: ya se manifestó votando.
"""

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

CLAVE = "Administradora1234!"
AHORA = "2026-08-23 09:00:00"
#: Cinco al 20 %: así «un ausente» es exactamente un quinto, y las cuentas se siguen.
CENSO = [("Dolores Sánchez", "1º A"), ("Manuel Ortega", "1º B"), ("Rocío Peña", "2º A"),
         ("Julián Vega", "2º B"), ("Inés Cabrera", "3º A")]


class ElComputoDeAusentesTests(unittest.TestCase):
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
                       cif="H29123456", estado="Activa", **b))
        for i, (nombre, piso) in enumerate(CENSO):
            self._ins("workspace_fincas_vecinos",
                      dict(id=f"v{i}", workspace_id=self.ws, comunidad_id="com1",
                           nombre=nombre, piso=piso, coeficiente=20.0,
                           nif=f"2511111{i}A", iban="ES2321000418400000000001", **b))
        self._ins("workspace_fincas_juntas",
                  dict(id="j1", workspace_id=self.ws, comunidad_id="com1",
                       fecha="2026-09-15", tipo="ordinaria", estado="Planificada",
                       lugar="Portal del edificio", hora="18:00", **b))
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
        # El punto: modificar los estatutos, que pide unanimidad.
        _, r, _ = self._post("/api/workspace_fincas_junta_acuerdo",
                             {"workspace_id": self.ws, "junta_id": "j1",
                              "titulo": "Modificar los estatutos",
                              "tipo_acuerdo": "titulo_estatutos", "orden": 1}, self.cookie)
        self.acuerdo = r["id"]
        # Vienen cuatro y votan que sí. Julián (v3) no viene ni delega.
        for i in (0, 1, 2, 4):
            self._post("/api/workspace_fincas_junta_asistencia",
                       {"workspace_id": self.ws, "junta_id": "j1", "vecino_id": f"v{i}",
                        "asiste": "1"}, self.cookie)
        for i in (0, 1, 2, 4):
            _, self.ultimo, _ = self._post(
                "/api/workspace_fincas_junta_voto",
                {"workspace_id": self.ws, "acuerdo_id": self.acuerdo,
                 "vecino_id": f"v{i}", "voto": "Favor"}, self.cookie)

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

    def _punto(self, respuesta=None, titulo="Modificar los estatutos"):
        r = respuesta if respuesta is not None else self.ultimo
        return [a for a in r["recuento"]["acuerdos"] if a["titulo"] == titulo][0]

    def _notifica(self, fecha):
        _, r, _ = self._post("/api/workspace_fincas_junta_notificar_acta",
                             {"workspace_id": self.ws, "junta_id": "j1", "fecha": fecha},
                             self.cookie)
        return r

    def _discrepa(self, vecino_id, si=True, acuerdo=None):
        return self._post("/api/workspace_fincas_junta_discrepancia",
                          {"workspace_id": self.ws, "acuerdo_id": acuerdo or self.acuerdo,
                           "vecino_id": vecino_id, "discrepa": "1" if si else "0"},
                          self.cookie)

    def _acta(self):
        url = (f"http://127.0.0.1:{self.puerto}/api/workspace_fincas_acta?"
               + urllib.parse.urlencode({"workspace_id": self.ws, "id": "j1"}))
        rq = urllib.request.Request(url, headers={"Cookie": self.cookie})
        with urllib.request.urlopen(rq, timeout=60) as r:
            crudo = r.read()
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(crudo)).pages)

    # --- el día de la junta -------------------------------------------------------

    def test_el_dia_de_la_junta_no_hay_unanimidad(self):
        p = self._punto()
        self.assertEqual(p["favor"], 4)
        self.assertAlmostEqual(p["favor_propietarios"], 80.0, places=2)
        self.assertIs(p["aprobado"], False)

    def test_pero_el_ausente_cuenta_a_favor_si_calla(self):
        p = self._punto()
        self.assertEqual(p["ausentes_pendientes"], 1)
        self.assertAlmostEqual(p["favor_con_ausentes_propietarios"], 100.0, places=2)
        self.assertAlmostEqual(p["favor_con_ausentes_coeficiente"], 100.0, places=2)
        self.assertIs(p["aprobado_con_ausentes"], True)

    def test_y_se_dice_quién_es_ese_ausente(self):
        nominales = self._punto()["ausentes_nominales"]
        self.assertEqual(len(nominales), 1, nominales)
        self.assertEqual(nominales[0]["nombre"], "Julián Vega")
        self.assertIs(nominales[0]["discrepa"], False)
        self.assertIs(nominales[0]["suma_a_favor"], True)

    def test_quien_asistió_no_es_ausente(self):
        """Ni los representados: se manifestaron votando."""
        self.assertEqual([n["vecino_id"] for n in self._punto()["ausentes_nominales"]], ["v3"])

    # --- el plazo -----------------------------------------------------------------

    def test_sin_comunicar_el_acta_el_plazo_no_ha_empezado(self):
        p = self._punto()
        self.assertEqual(p["plazo_ausentes"]["acta_notificada"], "")
        self.assertIs(p["firme"], False)

    def test_al_comunicarla_arrancan_30_dias_naturales(self):
        p = self._punto(self._notifica("2026-09-20"))
        self.assertEqual(p["plazo_ausentes"]["vence"], "2026-10-20")
        self.assertIs(p["plazo_ausentes"]["cerrado"], False)
        self.assertIs(p["firme"], False)

    def test_una_fecha_que_no_es_fecha_se_rechaza(self):
        """De ella cuelga el plazo entero: no vale tragársela."""
        estado, r, _ = self._post("/api/workspace_fincas_junta_notificar_acta",
                                  {"workspace_id": self.ws, "junta_id": "j1",
                                   "fecha": "20-09-2026"}, self.cookie)
        self.assertEqual(estado, 400, r)
        self.assertIn("17.8", r.get("error", ""))

    def test_vencido_el_plazo_el_punto_queda_firme(self):
        hace_dos_meses = (date.today() - timedelta(days=60)).isoformat()
        p = self._punto(self._notifica(hace_dos_meses))
        self.assertIs(p["plazo_ausentes"]["cerrado"], True)
        self.assertIs(p["firme"], True)
        self.assertIs(p["aprobado_con_ausentes"], True)

    # --- discrepar ------------------------------------------------------------------

    def test_si_el_ausente_discrepa_no_suma(self):
        _, r, _ = self._discrepa("v3")
        p = self._punto(r)
        self.assertEqual(p["ausentes_discrepan"], 1)
        self.assertEqual(p["ausentes_pendientes"], 0)
        self.assertIs(p["aprobado_con_ausentes"], False)

    def test_y_entonces_el_punto_ya_es_firme(self):
        """No queda nadie de quien esperar respuesta."""
        _, r, _ = self._discrepa("v3")
        self.assertIs(self._punto(r)["firme"], True)

    def test_la_discrepancia_se_puede_rectificar(self):
        self._discrepa("v3")
        _, r, _ = self._discrepa("v3", si=False)
        p = self._punto(r)
        self.assertEqual(p["ausentes_discrepan"], 0)
        self.assertEqual(p["ausentes_pendientes"], 1)

    def test_a_quien_asistió_no_se_le_anota_discrepancia(self):
        estado, r, _ = self._discrepa("v0")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "no_estaba_ausente")
        self.assertIn("ausentes", r.get("error", ""))

    # --- no se aplica a todo --------------------------------------------------------

    def test_las_energias_renovables_quedan_fuera(self):
        """El 17.8 excluye los casos en que el coste no se repercute a quien no votó a favor."""
        _, r, _ = self._post("/api/workspace_fincas_junta_acuerdo",
                             {"workspace_id": self.ws, "junta_id": "j1",
                              "titulo": "Placas solares", "tipo_acuerdo": "energias_telecom",
                              "orden": 2}, self.cookie)
        p = self._punto(r, "Placas solares")
        self.assertIs(p["computa_ausentes"], False)
        self.assertEqual(p["ausentes_pendientes"], 0)
        self.assertIs(p["firme"], True)

    def test_y_eso_es_editable_como_el_resto_del_catálogo(self):
        tipos = {t["clave"]: t for t in S.fetch_workspace_fincas_tipos_acuerdo(self.conn, self.ws)}
        self.assertEqual(tipos["energias_telecom"]["computa_ausentes"], 0)
        self.assertEqual(tipos["recarga_electrica"]["computa_ausentes"], 0)
        self.assertEqual(tipos["titulo_estatutos"]["computa_ausentes"], 1)

    def test_el_tipo_del_acuerdo_se_guarda(self):
        """Se recibía, se usaba para derivar la mayoría y se tiraba."""
        fila = self.conn.execute(
            "SELECT tipo_acuerdo FROM workspace_fincas_junta_acuerdos WHERE id = ?",
            (self.acuerdo,)).fetchone()
        self.assertEqual(dict(fila)["tipo_acuerdo"], "titulo_estatutos")

    # --- y el acta lo cuenta ---------------------------------------------------------

    def test_el_acta_avisa_de_que_el_punto_no_es_definitivo(self):
        self._notifica("2026-09-20")
        acta = self._acta()
        self.assertIn("art. 17.8", acta)
        self.assertIn("Julián Vega", acta)
        self.assertIn("2026-10-20", acta)

    def test_y_si_no_consta_la_comunicación_lo_dice(self):
        acta = self._acta()
        self.assertIn("NO CONSTA", acta)

    def test_cerrado_el_plazo_el_acta_da_el_resultado_definitivo(self):
        self._notifica((date.today() - timedelta(days=60)).isoformat())
        acta = self._acta()
        self.assertIn("Cerrado el plazo", acta)
        self.assertIn("el resultado definitivo", acta)

    def test_el_front_lo_enseña_y_deja_anotar_la_discrepancia(self):
        app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-acta-notificada", app)
        self.assertIn("data-discrepa", app)
        self.assertIn("cómputo de ausentes", app)

    def test_las_dos_rutas_nuevas_son_alcanzables(self):
        """El manejador escrito y no dado de alta ya nos costó tres botones muertos."""
        servidor = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        for ruta in ("/api/workspace_fincas_junta_notificar_acta",
                     "/api/workspace_fincas_junta_discrepancia"):
            # Una vez en la lista blanca de POST y otra en el grupo que la despacha.
            self.assertGreaterEqual(servidor.count(f'"{ruta}"'), 3, ruta)


if __name__ == "__main__":
    unittest.main()
