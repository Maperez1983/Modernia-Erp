"""Fase 0 del paso a ámbito por workspace (2026-09-18): lo que ya estaba roto.

La regla nueva es que un dato es del workspace, y la empresa es solo un atributo que
puede faltar. En el registro horario eso rompía cuatro cosas a quien no tiene sociedad
(Daniel García, en Modernia sin empresa):

- Al fichar se le escribía en la ficha la primera empresa del workspace por orden
  alfabético: una sociedad inventada que se quedaba para siempre.
- Sus fichajes no salían en el listado ni en las exportaciones legales, que exigían una
  empresa del workspace.
- El detector de entradas abiertas duplicadas no comprobaba nada sin empresa.
- Un cierre de mes del workspace entero no bloqueaba los fichajes con empresa.

Y tres fallos sueltos: la memoria económica de RRHH (500 siempre, código debajo de un
`return`), vincular una hipoteca (variable usada antes de declararse) y el cierre de
sesión, que dejaba el workspace del usuario anterior en el navegador.
"""

import re
import tempfile
import unittest
from pathlib import Path

from web import server as S

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
AUTH = (RAIZ / "web" / "app-auth.js").read_text(encoding="utf-8")
AHORA = "2026-09-18 09:00:00"


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "f0.sqlite"
        S.ensure_tables(db)
        self.c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(self.c.close)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.c)
            except Exception:
                pass
        self.c.commit()
        self.c.execute("PRAGMA foreign_keys = OFF")
        self.c.execute("DELETE FROM workspace_registro_personal")
        self.ws = self.c.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self.ins("empresas", dict(id="emp1", nombre="Aaa Primera SL", nif="B29123456", activo=1))
        self.ins("workspace_empresas", dict(id="we1", workspace_id=self.ws, empresa_id="emp1"))

    def ins(self, tabla, datos):
        datos = {"created_at": AHORA, "updated_at": AHORA, **datos}
        cols = {c[1] for c in self.c.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.c.execute(
            f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()),
        )
        self.c.commit()

    def fichaje(self, fid, persona, empresa, fecha="2026-09-10", hora_fin="17:00"):
        self.ins("workspace_registro_horario", dict(
            id=fid, workspace_id=self.ws, empresa_id=empresa, persona_id=persona,
            persona_nombre=persona, fecha=fecha, hora_inicio="09:00", hora_fin=hora_fin,
        ))


class FichajesSinEmpresaSeVenTests(_Base):
    def test_el_listado_incluye_los_fichajes_sin_empresa(self):
        self.fichaje("con", "ana", "emp1")
        self.fichaje("sin", "daniel", None)
        ids = {r["id"] for r in S.fetch_workspace_time_entries(self.c, self.ws, limit=50)["rows"]}
        self.assertEqual(ids, {"con", "sin"})

    def test_filtrar_por_empresa_sigue_funcionando(self):
        self.fichaje("con", "ana", "emp1")
        self.fichaje("sin", "daniel", None)
        ids = {r["id"] for r in S.fetch_workspace_time_entries(self.c, self.ws, empresa_id="emp1", limit=50)["rows"]}
        self.assertEqual(ids, {"con"})

    def test_una_empresa_ajena_no_devuelve_nada(self):
        self.fichaje("con", "ana", "emp1")
        self.assertEqual(S.fetch_workspace_time_entries(self.c, self.ws, empresa_id="de-otro", limit=50)["rows"], [])

    def test_no_salen_fichajes_de_otro_workspace(self):
        self.fichaje("mio", "ana", "emp1")
        self.ins("workspace_registro_horario", dict(
            id="ajeno", workspace_id="otro-ws", empresa_id="emp1", persona_id="x",
            persona_nombre="x", fecha="2026-09-10", hora_inicio="09:00",
        ))
        ids = {r["id"] for r in S.fetch_workspace_time_entries(self.c, self.ws, limit=50)["rows"]}
        self.assertEqual(ids, {"mio"})


class DuplicadoAbiertoTests(_Base):
    def test_detecta_la_entrada_abierta_sin_empresa(self):
        self.fichaje("abierto", "daniel", None, hora_fin=None)
        dup = S.find_duplicate_open_time_entry(self.c, self.ws, "", "2026-09-10", persona_id="daniel")
        self.assertIsNotNone(dup)

    def test_detecta_aunque_la_empresa_sea_otra(self):
        self.fichaje("abierto", "ana", "emp1", hora_fin=None)
        dup = S.find_duplicate_open_time_entry(self.c, self.ws, "emp-otra", "2026-09-10", persona_id="ana")
        self.assertIsNotNone(dup)


class CierreDeMesTests(_Base):
    def _cierra(self, empresa):
        self.ins("workspace_registro_periodos", dict(
            id=f"p-{empresa}", workspace_id=self.ws, empresa_id=empresa, month="2026-09", locked=1,
        ))

    def test_el_cierre_del_workspace_bloquea_tambien_los_de_empresa(self):
        self._cierra(None)
        self.assertTrue(S.is_workspace_time_month_locked(self.c, self.ws, "2026-09-10", empresa_id="emp1"))
        self.assertTrue(S.is_workspace_time_month_locked(self.c, self.ws, "2026-09-10", empresa_id=""))

    def test_el_cierre_de_una_empresa_no_bloquea_a_las_demas(self):
        self._cierra("emp1")
        self.assertTrue(S.is_workspace_time_month_locked(self.c, self.ws, "2026-09-10", empresa_id="emp1"))
        self.assertFalse(S.is_workspace_time_month_locked(self.c, self.ws, "2026-09-10", empresa_id=""))
        self.assertFalse(S.is_workspace_time_month_locked(self.c, self.ws, "2026-10-01", empresa_id="emp1"))


class NoSeInventaEmpresaTests(_Base):
    def _usuario(self, uid, nombre):
        self.ins("usuarios", dict(id=uid, nombre=nombre, apellido="", usuario=uid, email=f"{uid}@x.test",
                                  rol="Inmobiliaria", servicio="Inmobiliaria", activo=1,
                                  registro_horario_activo=1, password_hash="x"))
        self.ins("workspace_miembros", dict(id=f"m-{uid}", workspace_id=self.ws, usuario_id=uid, rol="Miembro"))

    def test_la_ficha_nueva_nace_sin_empresa(self):
        self._usuario("dani", "Daniel")
        pid = S.ensure_workspace_persona_for_self(self.c, self.ws, {"user_id": "dani", "nombre": "Daniel"})
        self.assertTrue(pid)
        emp = self.c.execute("SELECT empresa_id FROM workspace_registro_personal WHERE id=?", (pid,)).fetchone()[0]
        self.assertIsNone(emp)

    def test_vincular_una_ficha_sin_empresa_no_le_pone_ninguna(self):
        self._usuario("dani", "Daniel")
        self.ins("workspace_registro_personal", dict(
            id="f-dani", workspace_id=self.ws, empresa_id=None, empresa_manual=0,
            usuario_id=None, usuario_manual=0, source="manual", nombre="Daniel",
            email="dani@x.test", activo=1,
        ))
        pid = S.ensure_workspace_persona_for_self(self.c, self.ws, {"user_id": "dani", "nombre": "Daniel", "email": "dani@x.test"})
        self.assertEqual(pid, "f-dani")
        emp = self.c.execute("SELECT empresa_id FROM workspace_registro_personal WHERE id='f-dani'").fetchone()[0]
        self.assertIsNone(emp)

    def test_fichar_no_escribe_empresa_en_la_ficha(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_horario_toggle":')
        bloque = SERVER[i : SERVER.index("elif parsed.path ==", i + 60)]
        self.assertNotIn("SET empresa_id = ?, empresa_manual = 1", bloque)
        self.assertNotIn('"empresa_id requerido"', bloque)

    def test_el_alta_manual_no_exige_empresa(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_horario":')
        bloque = SERVER[i : SERVER.index("elif parsed.path ==", i + 60)]
        self.assertNotIn("not empresa_id or not persona_nombre", bloque)
        self.assertNotIn("WHERE id = ? AND workspace_id = ? AND empresa_id = ?", bloque)


class FallosSueltosTests(unittest.TestCase):
    def test_memoria_economica_no_tiene_codigo_debajo_de_un_return(self):
        i = SERVER.index('if path == "/api/workspace_rrhh_memoria_economica":')
        bloque = SERVER[i : SERVER.index("for n in nominas:", i)]
        # Tras el `return` del "empresa_id requerido", lo siguiente vuelve al nivel del if.
        m = re.search(r'\n( +)return\n( +)year = ', bloque)
        self.assertIsNotNone(m)
        self.assertLess(len(m.group(2)), len(m.group(1)), "year = sigue debajo del return: nunca se ejecuta")

    def test_hipoteca_declara_empresa_id_antes_de_usarlo(self):
        i = APP.index("const vincularHipotecaSeleccionada = async () => {")
        bloque = APP[i : APP.index("\n};", i)]
        self.assertLess(bloque.index("const empresaId = resolveLegacyEmpresaId(empresa);"),
                        bloque.index("{ empresa_id: empresaId }"))

    def test_cerrar_sesion_olvida_el_estado_del_usuario(self):
        i = AUTH.index("async function logoutAuthSession(deps) {")
        bloque = AUTH[i : AUTH.index("\n  }\n", i)]
        self.assertIn("olvidarEstadoDelUsuario();", bloque)
        self.assertIn('window.location.replace("/")', bloque)
        self.assertIn('clave.startsWith("crm.")', AUTH)
        self.assertIn('"crm.swVersion"', AUTH)


if __name__ == "__main__":
    unittest.main()
