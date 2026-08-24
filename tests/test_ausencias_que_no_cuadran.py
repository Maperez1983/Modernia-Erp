"""Unas vacaciones del 20 al 10 entraban, y gastaban cero días.

Salió simulando cómo se piden las ausencias de verdad: a mano, y a mano se teclea mal.

**La ausencia que acaba antes de empezar.** No era sólo feo. El contador de vacaciones
cuenta los días de `fecha_inicio` a `fecha_fin`, así que una del 20 al 10 sale en
negativo y se guarda como **cero días consumidos**. El trabajador se va quince días y el
resumen dice que no ha gastado ninguno: los vuelve a tener disponibles en diciembre.

**Dos ausencias encima del mismo día.** Se guardaban las dos sin decir nada, y el cómputo
contaba los días dos veces. Aquí no vale bloquear, porque el caso más común es legítimo:
una baja médica que cae dentro de unas vacaciones aprobadas. La ley dice que esos días de
vacaciones **se recuperan** (ET art. 38.3), así que hay que poder registrarlo. Lo que no
vale es que entre sin que nadie se entere, así que se avisa de con qué se solapa y se
pide confirmar — el mismo criterio que con los importes absurdos y con la derrama.

Lo que ya estaba bien y se deja fijado aquí para no perderlo: un trabajador puede pedir
su ausencia pero **no aprobársela**; cerrar el mes no borra lo que está sin resolver; y
el resumen de vacaciones descuenta los días aprobados.
"""

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

CLAVE = "Responsable1234!"
AHORA = "2026-08-24 09:00:00"


class AusenciasQueNoCuadranTests(unittest.TestCase):
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
        self._ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456",
                                   activo=1, **b))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **b))
        self._ins("usuarios", dict(id="jefa", nombre="Ana", usuario="ana", email="a@x.test",
                                   rol="Administrador", servicio="RRHH", activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="jefa", rol="Owner", **b))
        self._ins("usuarios", dict(id="curro", nombre="Curro", usuario="curro",
                                   email="c@x.test", rol="Inmobiliaria",
                                   servicio="Inmobiliaria", activo=1,
                                   registro_horario_activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm2", workspace_id=self.ws,
                                             usuario_id="curro", rol="Miembro", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]
        self.cookie = None
        self._entra("ana")
        self._post("/api/workspace_registro_personal", {
            "workspace_id": self.ws, "empresa_id": "emp1", "nombre": "Curro Jiménez",
            "nif": "25111111A", "usuario_id": "curro", "email": "c@x.test",
            "jornada_semanal": 40, "activo": 1})
        self.persona = self._fresco(
            "SELECT id FROM workspace_registro_personal LIMIT 1")[0]["id"]

    def _ins(self, tabla, datos):
        cols = {c[1] for c in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _post(self, ruta, cuerpo):
        rq = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"},
                                    method="POST")
        if self.cookie:
            rq.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _entra(self, usuario):
        self.cookie = None
        _, _, galleta = self._post("/api/login", {"usuario": usuario, "password": CLAVE})
        self.cookie = galleta.split(";")[0]

    def _fresco(self, sql, args=()):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def _ausencia(self, inicio, fin, tipo="Vacaciones", **extra):
        cuerpo = {"workspace_id": self.ws, "persona_id": self.persona, "tipo": tipo,
                  "fecha_inicio": inicio, "fecha_fin": fin}
        cuerpo.update(extra)
        return self._post("/api/workspace_rrhh_ausencia", cuerpo)

    def _cuantas(self):
        return len(self._fresco("SELECT id FROM workspace_rrhh_ausencias"))

    def _resumen(self):
        url = (f"http://127.0.0.1:{self.puerto}/api/workspace_rrhh_vacaciones_summary?"
               + urllib.parse.urlencode({"workspace_id": self.ws, "year": 2026}))
        rq = urllib.request.Request(url, headers={"Cookie": self.cookie})
        with urllib.request.urlopen(rq, timeout=60) as r:
            return (json.loads(r.read() or b"{}").get("rows") or [{}])[0]

    # --- fechas al revés -----------------------------------------------------------

    def test_una_ausencia_que_acaba_antes_de_empezar_no_entra(self):
        estado, r, _ = self._ausencia("2026-09-20", "2026-09-10")
        self.assertEqual(estado, 400, r)
        self.assertIn("acaba antes de empezar", r.get("error", ""))
        self.assertEqual(self._cuantas(), 0)

    def test_y_por_eso_el_contador_no_se_queda_a_cero(self):
        """Era la consecuencia cara: quince días fuera y cero días gastados."""
        self._ausencia("2026-09-20", "2026-09-10")
        self._ausencia("2026-09-01", "2026-09-15")
        uno = self._fresco("SELECT id FROM workspace_rrhh_ausencias")[0]["id"]
        self._post("/api/workspace_rrhh_ausencia_estado",
                   {"workspace_id": self.ws, "id": uno, "action": "aprobar"})
        self.assertGreater(float(self._resumen().get("dias_usados") or 0), 0)

    def test_una_fecha_que_no_es_fecha_tampoco(self):
        estado, r, _ = self._ausencia("20/09/2026", "2026-09-25")
        self.assertEqual(estado, 400, r)
        self.assertEqual(self._cuantas(), 0)

    def test_un_solo_dia_sí_vale(self):
        """Inicio y fin el mismo día es un permiso de una jornada, no un error."""
        self.assertEqual(self._ausencia("2026-09-10", "2026-09-10",
                                        tipo="Asuntos propios")[0], 200)

    # --- solapamiento ---------------------------------------------------------------

    def test_dos_ausencias_encima_del_mismo_dia_avisan(self):
        self._ausencia("2026-09-01", "2026-09-15")
        estado, r, _ = self._ausencia("2026-09-10", "2026-09-20", tipo="Baja médica")
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "ausencias_solapadas")
        self.assertEqual(self._cuantas(), 1)

    def test_el_aviso_dice_con_qué_se_solapa(self):
        self._ausencia("2026-09-01", "2026-09-15")
        _, r, _ = self._ausencia("2026-09-10", "2026-09-20", tipo="Baja médica")
        aviso = r.get("error", "")
        self.assertIn("Vacaciones", aviso)
        self.assertIn("2026-09-01", aviso)
        self.assertIn("38.3", aviso)
        self.assertEqual(len(r.get("solapa_con") or []), 1)

    def test_una_baja_dentro_de_las_vacaciones_se_puede_registrar(self):
        """Es el caso común y legítimo: esos días de vacaciones se recuperan."""
        self._ausencia("2026-09-01", "2026-09-15")
        estado, r, _ = self._ausencia("2026-09-10", "2026-09-20", tipo="Baja médica",
                                      confirmado=True)
        self.assertEqual(estado, 200, r)
        self.assertEqual(self._cuantas(), 2)

    def test_dos_ausencias_que_no_se_tocan_no_molestan(self):
        self._ausencia("2026-09-01", "2026-09-10")
        self.assertEqual(self._ausencia("2026-09-11", "2026-09-20")[0], 200)

    def test_una_ausencia_cancelada_no_estorba(self):
        self._ausencia("2026-09-01", "2026-09-15")
        uno = self._fresco("SELECT id FROM workspace_rrhh_ausencias")[0]["id"]
        self._post("/api/workspace_rrhh_ausencia_estado",
                   {"workspace_id": self.ws, "id": uno, "action": "cancelar"})
        self.assertEqual(self._ausencia("2026-09-10", "2026-09-20")[0], 200)

    def test_editar_una_ausencia_no_se_solapa_consigo_misma(self):
        self._ausencia("2026-09-01", "2026-09-15")
        uno = self._fresco("SELECT id FROM workspace_rrhh_ausencias")[0]["id"]
        estado, r, _ = self._ausencia("2026-09-02", "2026-09-16", id=uno)
        self.assertEqual(estado, 200, r)

    # --- lo que ya estaba bien --------------------------------------------------------

    def test_un_trabajador_pide_pero_no_se_aprueba(self):
        self._entra("curro")
        estado, r, _ = self._ausencia("2026-10-01", "2026-10-05", tipo="Asuntos propios")
        self.assertEqual(estado, 200, r)
        mia = self._fresco("SELECT id FROM workspace_rrhh_ausencias")[0]["id"]
        estado, r, _ = self._post("/api/workspace_rrhh_ausencia_estado",
                                  {"workspace_id": self.ws, "id": mia, "action": "aprobar"})
        self.assertEqual(estado, 403, r)
        self.assertEqual(
            self._fresco("SELECT estado FROM workspace_rrhh_ausencias")[0]["estado"],
            "Solicitada")

    def test_cerrar_el_mes_no_borra_lo_que_está_sin_resolver(self):
        self._ausencia("2026-09-01", "2026-09-15")
        antes = self._cuantas()
        self._post("/api/workspace_registro_periodo_lock",
                   {"workspace_id": self.ws, "empresa_id": "emp1", "month": "2026-09",
                    "locked": True})
        self.assertEqual(self._cuantas(), antes)


if __name__ == "__main__":
    unittest.main()
