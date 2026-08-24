"""Impugnar un acuerdo tiene tres reglas que se olvidan, y el CRM no sabía ninguna.

El artículo 18 de la LPH no dice sólo que un acuerdo se puede impugnar. Dice **quién**,
**hasta cuándo** y **qué pasa mientras tanto**, y las tres se fallan a menudo:

1. **Quién** (18.2). Sólo los que salvaron su voto, los ausentes y los que fueron
   privados indebidamente de votar. Quien votó a favor, no: no se puede impugnar lo que
   uno mismo ha votado. Y hay que estar al corriente de pago o haber consignado
   judicialmente lo debido — salvo que el acuerdo sea sobre el establecimiento o la
   alteración de las cuotas de participación, que ésos sí los puede impugnar un deudor.

2. **Hasta cuándo** (18.3). Tres meses… o **un año** si el acuerdo es contrario a la ley
   o a los estatutos. Son dos plazos distintos según el motivo, y para los ausentes se
   cuentan desde que se les comunicó el acuerdo, no desde la junta. Cuatro fechas
   posibles: es exactamente la clase de cuenta que sale mal a mano.

3. **Qué pasa mientras tanto** (18.4). **No suspende la ejecución.** Es lo que peor
   sale: dejar de ejecutar un acuerdo porque «está impugnado» es meterse en otro
   problema, y el CRM ahora lo dice cada vez que se anota una y lo repite en el acta.

El plazo vencido no bloquea —el hecho ocurrió y hay que poder anotarlo— pero tampoco se
traga en silencio: se dice hasta cuándo era y se pide confirmar.
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

CLAVE = "Administradora1234!"
AHORA = "2026-08-24 09:00:00"
CENSO = [("Dolores Sánchez", "1º A"), ("Manuel Ortega", "1º B"), ("Rocío Peña", "2º A"),
         ("Julián Vega", "2º B"), ("Inés Cabrera", "3º A")]


class ImpugnarUnAcuerdoTests(unittest.TestCase):
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
        # La junta fue hace un mes: dentro de los tres meses y del año.
        self._ins("workspace_fincas_juntas",
                  dict(id="j1", workspace_id=self.ws, comunidad_id="com1",
                       fecha="2026-07-24", tipo="ordinaria", estado="Celebrada",
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
        _, r, _ = self._post("/api/workspace_fincas_junta_acuerdo",
                             {"workspace_id": self.ws, "junta_id": "j1",
                              "titulo": "Cerrar la piscina todo el año",
                              "tipo_acuerdo": "ordinario", "orden": 1}, self.cookie)
        self.acuerdo = r["id"]
        # Vienen cuatro: tres a favor, Rocío en contra. Julián (v3) no viene.
        for i in (0, 1, 2, 4):
            self._post("/api/workspace_fincas_junta_asistencia",
                       {"workspace_id": self.ws, "junta_id": "j1", "vecino_id": f"v{i}",
                        "asiste": "1"}, self.cookie)
        for i, voto in ((0, "Favor"), (1, "Favor"), (4, "Favor"), (2, "Contra")):
            self._post("/api/workspace_fincas_junta_voto",
                       {"workspace_id": self.ws, "acuerdo_id": self.acuerdo,
                        "vecino_id": f"v{i}", "voto": voto}, self.cookie)

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

    def _impugna(self, vecino_id, motivo="lesivo_comunidad", **extra):
        cuerpo = {"workspace_id": self.ws, "acuerdo_id": self.acuerdo,
                  "vecino_id": vecino_id, "motivo": motivo, "fecha": "2026-08-24"}
        cuerpo.update(extra)
        return self._post("/api/workspace_fincas_junta_impugnacion", cuerpo, self.cookie)

    def _punto(self, respuesta):
        return [a for a in respuesta["recuento"]["acuerdos"] if a["id"] == self.acuerdo][0]

    def _acta(self):
        url = (f"http://127.0.0.1:{self.puerto}/api/workspace_fincas_acta?"
               + urllib.parse.urlencode({"workspace_id": self.ws, "id": "j1"}))
        rq = urllib.request.Request(url, headers={"Cookie": self.cookie})
        with urllib.request.urlopen(rq, timeout=60) as r:
            crudo = r.read()
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(crudo)).pages)

    # --- quién puede (art. 18.2) --------------------------------------------------

    def test_quien_voto_en_contra_puede_impugnar(self):
        estado, r, _ = self._impugna("v2")
        self.assertEqual(estado, 200, r)
        self.assertEqual(len(self._punto(r)["impugnaciones"]), 1)

    def test_un_ausente_tambien(self):
        estado, r, _ = self._impugna("v3")
        self.assertEqual(estado, 200, r)

    def test_pero_quien_voto_a_favor_no(self):
        """No se impugna lo que uno mismo ha votado."""
        estado, r, _ = self._impugna("v0")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "no_legitimado")
        self.assertIn("votó a favor", r.get("error", ""))
        self.assertIn("18.2", r.get("error", ""))

    def test_y_no_queda_anotada(self):
        self._impugna("v0")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM workspace_fincas_junta_impugnaciones").fetchone()[0], 0)

    # --- estar al corriente (art. 18.2, párrafo 2) --------------------------------

    def _deja_a_deber(self, vecino="v2"):
        """Emite la cuota de un mes ya vencido y la deja sin cobrar sólo para uno."""
        self._post("/api/workspace_fincas_recibos_emitir",
                   {"workspace_id": self.ws, "comunidad_id": "com1", "periodo": "2026-05",
                    "importe": 1000.0, "concepto": "Cuota mayo"}, self.cookie)
        for i in range(len(CENSO)):
            if f"v{i}" == vecino:
                continue
            rec = self.conn.execute(
                "SELECT id FROM workspace_fincas_recibos WHERE vecino_id = ?", (f"v{i}",)).fetchone()
            self._post("/api/workspace_fincas_recibo_estado",
                       {"workspace_id": self.ws, "id": dict(rec)["id"], "estado": "Cobrado"},
                       self.cookie)

    def test_un_moroso_no_impugna(self):
        self._deja_a_deber("v3")
        estado, r, _ = self._impugna("v3")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "no_esta_al_corriente")
        self.assertIn("consignar", r.get("error", ""))

    def test_salvo_si_el_acuerdo_toca_las_cuotas_de_participacion(self):
        """Ésos sí los puede impugnar quien debe: es la excepción del propio artículo."""
        self._deja_a_deber("v3")
        estado, r, _ = self._impugna("v3", afecta_cuotas="1")
        self.assertEqual(estado, 200, r)

    # --- hasta cuándo (art. 18.3) --------------------------------------------------

    def test_se_dan_los_dos_plazos_porque_dependen_del_motivo(self):
        _, r, _ = self._impugna("v2")
        plazo = self._punto(r)["plazo_impugnacion"]
        self.assertEqual(plazo["desde_la_junta"], "2026-07-24")
        self.assertEqual(plazo["vence_tres_meses"], "2026-10-24")
        self.assertEqual(plazo["vence_un_ano"], "2027-07-24")

    def test_fuera_de_plazo_se_avisa_en_vez_de_tragarlo(self):
        estado, r, _ = self._impugna("v2", fecha="2026-11-30")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "fuera_de_plazo")
        self.assertEqual(r.get("vence"), "2026-10-24")
        self.assertIn("18.3", r.get("error", ""))

    def test_pero_se_puede_anotar_confirmando(self):
        """El hecho ocurrió: no anotarlo tampoco vale."""
        estado, r, _ = self._impugna("v2", fecha="2026-11-30", confirmado=True)
        self.assertEqual(estado, 200, r)

    def test_contrario_a_la_ley_tiene_un_ano_y_no_tres_meses(self):
        """Con el plazo corto esta misma impugnación estaría fuera; con el bueno, dentro."""
        estado, r, _ = self._impugna("v2", motivo="ley_estatutos", fecha="2026-11-30")
        self.assertEqual(estado, 200, r)

    def test_sin_motivo_no_se_anota_nada(self):
        estado, r, _ = self._post("/api/workspace_fincas_junta_impugnacion",
                                  {"workspace_id": self.ws, "acuerdo_id": self.acuerdo,
                                   "vecino_id": "v2"}, self.cookie)
        self.assertEqual(estado, 400, r)
        self.assertIn("del motivo depende el plazo", r.get("error", "").replace("de él", "del motivo"))
        self.assertEqual(len(r.get("motivos") or []), 3)

    def test_para_el_ausente_el_plazo_corre_desde_que_se_le_comunica(self):
        self._post("/api/workspace_fincas_junta_notificar_acta",
                   {"workspace_id": self.ws, "junta_id": "j1", "fecha": "2026-08-01"},
                   self.cookie)
        _, r, _ = self._impugna("v3")
        plazo = self._punto(r)["plazo_impugnacion"]
        self.assertEqual(plazo["desde_la_comunicacion"], "2026-08-01")
        self.assertEqual(plazo["vence_tres_meses_ausentes"], "2026-11-01")
        # Y a él se le aplica ésa, no la de la junta: el 30/10 aún está en plazo.
        self._impugna("v3", retirar="1")
        estado, r, _ = self._impugna("v3", fecha="2026-10-30")
        self.assertEqual(estado, 200, r)

    # --- qué pasa mientras tanto (art. 18.4) --------------------------------------

    def test_se_avisa_de_que_no_suspende_la_ejecucion(self):
        """Es lo que peor sale: dejar de ejecutar un acuerdo porque está impugnado."""
        _, r, _ = self._impugna("v2")
        self.assertIn("NO suspende", r.get("aviso", ""))
        self.assertIn("18.4", r.get("aviso", ""))

    def test_el_acuerdo_sigue_aprobado(self):
        _, r, _ = self._impugna("v2")
        self.assertIs(self._punto(r)["aprobado"], True)

    # --- y queda en el acta ---------------------------------------------------------

    def test_el_acta_recoge_la_impugnacion(self):
        self._impugna("v2", notas="Presentada en el juzgado nº 3")
        acta = self._acta()
        self.assertIn("IMPUGNADO", acta)
        self.assertIn("Rocío Peña", acta)
        self.assertIn("18.1.b", acta)
        self.assertIn("juzgado", acta)

    def test_y_repite_alli_que_no_suspende(self):
        self._impugna("v2")
        self.assertIn("no suspende la ejecución", self._acta())

    def test_sin_impugnaciones_el_acta_no_dice_nada_de_esto(self):
        self.assertNotIn("IMPUGNADO", self._acta())

    # --- se puede retirar -----------------------------------------------------------

    def test_una_impugnacion_se_puede_retirar(self):
        self._impugna("v2")
        _, r, _ = self._impugna("v2", retirar="1")
        self.assertEqual(self._punto(r)["impugnaciones"], [])

    # --- y la ruta existe de verdad ---------------------------------------------------

    def test_la_ruta_esta_en_las_dos_listas(self):
        """Una sola no basta: el manejador queda escrito y no lo alcanza nadie."""
        servidor = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            servidor.count('"/api/workspace_fincas_junta_impugnacion"'), 3)


if __name__ == "__main__":
    unittest.main()
