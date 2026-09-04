"""El deudor votaba en la junta, y su cuota seguía contando para la mayoría.

Salió simulando una junta entera. El CRM ya sabía la regla: la convocatoria que genera
lista a quien no está al corriente y advierte, con el artículo al lado, de que **puede
asistir y deliberar pero no tiene derecho de voto** (LPH art. 15.2). Luego llegaba el
recuento y contaba su voto como el de cualquiera.

Hay dos consecuencias, y la segunda es peor que la primera:

1. Un voto que no existe suma.
2. Su cuota se queda en el divisor. El artículo dice que las cuotas de los deudores
   **se deducen de la cuota de participación total del inmueble a efectos de alcanzar
   las mayorías**. Con un deudor del 15 %, un acuerdo apoyado por el 40 % salía como
   «40 % de coeficiente» cuando legalmente es el 47,06 % de lo que vota.

O sea que el CRM podía dar por no aprobado algo que sí lo estaba, y al revés. Y un
acuerdo mal contado es impugnable (art. 18), con el administrador firmando el acta.

Recupera el voto quien antes de empezar la junta haya pagado, impugnado judicialmente
la deuda o consignado su importe. Eso el CRM no puede saberlo, así que lo marca quien
preside con una casilla; sin marcarla, manda lo que diga la deuda.

Y el acta lo dice: quién no votó, por cuánto debe y sobre qué coeficiente se han medido
las mayorías. Sin esa lista los porcentajes no hay forma de comprobarlos, porque están
calculados sobre un denominador que el papel no enseñaba.
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
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
CLAVE = "Administradora1234!"
AHORA = "2026-08-23 09:00:00"
#: Cabezas y cuotas no van de la mano a propósito: es donde se ve el doble cómputo.
CENSO = [("Dolores Sánchez", "1º A", 40.0), ("Manuel Ortega", "1º B", 15.0),
         ("Rocío Peña", "2º A", 15.0), ("Julián Vega", "2º B", 15.0),
         ("Inés Cabrera", "3º A", 15.0)]


class ElMorosoNoVotaTests(unittest.TestCase):
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
        for i, (nombre, piso, coef) in enumerate(CENSO):
            self._ins("workspace_fincas_vecinos",
                      dict(id=f"v{i}", workspace_id=self.ws, comunidad_id="com1",
                           nombre=nombre, piso=piso, coeficiente=coef,
                           nif=f"2511111{i}A", iban="ES2321000418400000000001", **b))
        self._ins("workspace_fincas_juntas",
                  dict(id="j1", workspace_id=self.ws, comunidad_id="com1",
                       fecha="2026-09-15", tipo="ordinaria", estado="Planificada",
                       lugar="Portal del edificio", hora="18:00", **b))
        self._ins("workspace_fincas_junta_acuerdos",
                  dict(id="a1", workspace_id=self.ws, junta_id="j1", orden=1,
                       titulo="Aprobar las cuentas", mayoria_clave="mayoria_simple", **b))
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
        # Mayo ya venció. Todos pagan menos Manuel, el del 15 %.
        self._post("/api/workspace_fincas_recibos_emitir",
                   {"workspace_id": self.ws, "comunidad_id": "com1", "periodo": "2026-05",
                    "importe": 1000.0, "concepto": "Cuota mayo"}, self.cookie)
        for i in (0, 2, 3, 4):
            rec = self._fresco("SELECT id FROM workspace_fincas_recibos WHERE vecino_id = ?",
                               (f"v{i}",))[0]
            self._post("/api/workspace_fincas_recibo_estado",
                       {"workspace_id": self.ws, "id": rec["id"], "estado": "Cobrado"},
                       self.cookie)
        for i in range(len(CENSO)):
            self._asiste(f"v{i}")

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

    def _fresco(self, sql, args=()):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def _asiste(self, vecino_id, **extra):
        cuerpo = {"workspace_id": self.ws, "junta_id": "j1", "vecino_id": vecino_id,
                  "asiste": "1"}
        cuerpo.update(extra)
        return self._post("/api/workspace_fincas_junta_asistencia", cuerpo, self.cookie)

    def _vota(self, vecino_id, voto="Favor"):
        return self._post("/api/workspace_fincas_junta_voto",
                          {"workspace_id": self.ws, "acuerdo_id": "a1",
                           "vecino_id": vecino_id, "voto": voto}, self.cookie)

    def _acuerdo(self, respuesta):
        return respuesta["recuento"]["acuerdos"][0]

    def _acta(self):
        url = (f"http://127.0.0.1:{self.puerto}/api/workspace_fincas_acta?"
               + urllib.parse.urlencode({"workspace_id": self.ws, "id": "j1"}))
        rq = urllib.request.Request(url, headers={"Cookie": self.cookie})
        with urllib.request.urlopen(rq, timeout=60) as r:
            crudo = r.read()
        self.assertEqual(crudo[:4], b"%PDF")
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(crudo)).pages)

    # --- no vota ----------------------------------------------------------------

    def test_al_deudor_no_se_le_deja_votar(self):
        estado, r, _ = self._vota("v1")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "sin_derecho_de_voto")

    def test_y_se_le_dice_por_qué_y_cómo_se_recupera(self):
        """Un «no» sin salida es un fallo del CRM para quien está presidiendo."""
        _, r, _ = self._vota("v1")
        aviso = r.get("error", "")
        self.assertIn("Manuel Ortega", aviso)
        self.assertIn("15.2", aviso)
        self.assertIn("150,00", aviso)
        self.assertIn("tiene voto", aviso)
        for palabra in ("pagado", "impugnado", "consignado", "deliberar"):
            self.assertIn(palabra, aviso)

    def test_no_se_guarda_el_voto_rechazado(self):
        self._vota("v1")
        self.assertEqual(
            self._fresco("SELECT COUNT(*) AS n FROM workspace_fincas_junta_votos")[0]["n"], 0)

    def test_quien_está_al_corriente_vota_sin_problema(self):
        estado, r, _ = self._vota("v0")
        self.assertEqual(estado, 200, r)
        self.assertEqual(self._acuerdo(r)["favor"], 1)

    # --- y su cuota sale del divisor --------------------------------------------

    def test_su_cuota_se_deduce_del_total(self):
        """40 sobre 85, no 40 sobre 100: es lo que exige el art. 15.2."""
        _, r, _ = self._vota("v0")
        ac = self._acuerdo(r)
        self.assertAlmostEqual(ac["favor_coeficiente"], round(40.0 / 85.0 * 100, 4), places=2)

    def test_y_tambien_del_recuento_por_cabezas(self):
        _, r, _ = self._vota("v0")
        self.assertAlmostEqual(self._acuerdo(r)["favor_propietarios"], 25.0, places=2)

    def test_se_dice_quién_no_vota_y_por_cuánto_debe(self):
        """Un porcentaje sobre 85 % que no enseña el 15 % no lo puede comprobar nadie."""
        _, r, _ = self._vota("v0")
        privados = r["recuento"]["sin_derecho_voto"]
        self.assertEqual(len(privados), 1, privados)
        self.assertEqual(privados[0]["nombre"], "Manuel Ortega")
        self.assertAlmostEqual(float(privados[0]["coeficiente"]), 15.0, places=2)
        self.assertGreater(float(privados[0]["deuda"]), 0)
        self.assertAlmostEqual(
            float(r["recuento"]["asistencia"]["coeficiente_con_voto"]), 85.0, places=2)

    def test_la_asistencia_sigue_contando_al_deudor(self):
        """Asiste y delibera: lo que pierde es el voto, no el derecho a estar."""
        _, r, _ = self._vota("v0")
        asis = r["recuento"]["asistencia"]
        self.assertEqual(asis["asistentes"], 5)
        self.assertAlmostEqual(float(asis["asistentes_pct_coeficiente"]), 100.0, places=2)

    # --- salvo que haya pagado, impugnado o consignado ---------------------------

    def test_marcándolo_recupera_el_voto(self):
        self._asiste("v1", derecho_voto="1")
        estado, r, _ = self._vota("v1")
        self.assertEqual(estado, 200, r)
        self.assertEqual(r["recuento"]["sin_derecho_voto"], [])

    def test_y_el_divisor_vuelve_a_ser_la_comunidad_entera(self):
        self._asiste("v1", derecho_voto="1")
        self._vota("v1")
        _, r, _ = self._vota("v0")
        ac = self._acuerdo(r)
        self.assertEqual(ac["favor"], 2)
        self.assertAlmostEqual(ac["favor_coeficiente"], 55.0, places=2)

    def test_un_voto_de_antes_deja_de_contar_si_pierde_el_derecho(self):
        """Se entra en morosidad después de votar. El voto no se borra, pero no cuenta."""
        self._asiste("v1", derecho_voto="1")
        self._vota("v1")
        self._asiste("v1", derecho_voto="")
        _, r, _ = self._vota("v0")
        self.assertEqual(self._acuerdo(r)["favor"], 1)
        self.assertEqual(
            self._fresco("SELECT COUNT(*) AS n FROM workspace_fincas_junta_votos")[0]["n"], 2,
            "el voto histórico no se borra, solo deja de contar")

    # --- y queda por escrito ------------------------------------------------------

    def test_el_acta_dice_quién_no_votó(self):
        self._vota("v0")
        acta = self._acta()
        self.assertIn("sin derecho de voto", acta.lower())
        self.assertIn("Manuel Ortega", acta)
        self.assertIn("15.2", acta)

    def test_y_sobre_qué_coeficiente_se_han_medido_las_mayorías(self):
        self._vota("v0")
        self.assertIn("sobre 85,00 % de coeficiente", self._acta())

    def test_sin_deudores_el_acta_no_añade_nada(self):
        """El apartado sólo aparece cuando hay a quién relacionar."""
        rec = self._fresco("SELECT id FROM workspace_fincas_recibos WHERE vecino_id = 'v1'")[0]
        self._post("/api/workspace_fincas_recibo_estado",
                   {"workspace_id": self.ws, "id": rec["id"], "estado": "Cobrado"},
                   self.cookie)
        self._vota("v0")
        self.assertNotIn("sin derecho de voto", self._acta().lower())

    def test_el_front_no_deja_ni_intentarlo(self):
        app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("sin_derecho_voto", app)
        self.assertIn("data-habilita", app)
        self.assertIn("derecho_voto:", app)


if __name__ == "__main__":
    unittest.main()
