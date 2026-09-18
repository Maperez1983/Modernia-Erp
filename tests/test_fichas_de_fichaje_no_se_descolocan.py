"""Que no vuelva a pasar lo del 2026-09-18.

Ese día cuatro trabajadores no veían su fichaje. No se había borrado nada, pero sus
fichas se habían descolocado por tres causas encadenadas:

1. Se elegía entre varias fichas por `updated_at`, que el aviso diario de "no has
   fichado" movía cada mañana. El mismo criterio lo usaban la elección dentro de un
   workspace y la limpieza de duplicados del arranque, que podía desvincular la ficha
   con todo el historial.
2. La vinculación automática descartaba una ficha si ya tenía usuario, aunque ese
   usuario ya no existiera. Dos trabajadores de Modernia Centro, cuyo usuario se había
   recreado con otro id, nunca recuperaban su ficha.
3. Bastaba con entrar a mirar otro workspace para estrenar allí una ficha vacía, que
   luego podía ganar a la buena.

Y nadie lo veía: de ahí el diagnóstico para quien gestiona RRHH.

Todo sobre el esquema real (`ensure_tables` + tablas de workspace) en SQLite.
"""

import tempfile
import unittest
from pathlib import Path

from web import server as S

AHORA = "2026-09-18 09:00:00"


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "f.sqlite"
        S.ensure_tables(db)
        self.c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(self.c.close)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.c)
            except Exception:
                pass
        # Postgres de producción no tiene clave foránea de la ficha al usuario, y por eso
        # existían fichas apuntando a usuarios borrados. SQLite sí la tiene: la apagamos
        # para poder reproducir esas fichas tal como estaban.
        self.c.commit()  # el PRAGMA no hace nada dentro de una transacción abierta
        self.c.execute("PRAGMA foreign_keys = OFF")
        self.c.execute("DELETE FROM workspace_registro_personal")
        self.ws = self.c.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self.otro = "ws-otro"
        self.ins("workspaces", dict(id=self.otro, nombre="Verifika2", slug="verifika2", estado="Activo"))
        self.ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1))
        for w in (self.ws, self.otro):
            self.ins("workspace_empresas", dict(id=f"we-{w}", workspace_id=w, empresa_id="emp1"))

    def ins(self, tabla, datos):
        datos = {"created_at": AHORA, "updated_at": AHORA, **datos}
        cols = {c[1] for c in self.c.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.c.execute(
            f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()),
        )
        self.c.commit()

    def usuario(self, uid, nombre, apellido="", email="", activo=1, rh=1, ws=None):
        # Email único por usuario: la columna lo es, y con INSERT OR REPLACE dos vacíos
        # hacían que el segundo usuario sustituyera al primero sin avisar.
        self.ins("usuarios", dict(id=uid, nombre=nombre, apellido=apellido, usuario=uid, email=email or f"{uid}@x.test",
                                  rol="Inmobiliaria", servicio="Inmobiliaria", activo=activo,
                                  registro_horario_activo=rh, password_hash="x"))
        self.ins("workspace_miembros", dict(id=f"m-{uid}-{ws or self.ws}", workspace_id=ws or self.ws,
                                            usuario_id=uid, rol="Miembro"))

    def ficha(self, pid, nombre, usuario_id="", ws=None, creada=AHORA, modificada=AHORA, email=None):
        self.ins("workspace_registro_personal", dict(
            id=pid, workspace_id=ws or self.ws, empresa_id="emp1", empresa_manual=1,
            usuario_id=usuario_id or None, usuario_manual=1 if usuario_id else 0, source="manual",
            nombre=nombre, email=email, tipo_jornada="Completa", activo=1,
            created_at=creada, updated_at=modificada,
        ))

    def fichaje(self, pid, fecha, ws=None):
        self.ins("workspace_registro_horario", dict(
            id=f"h-{pid}-{fecha}", workspace_id=ws or self.ws, persona_id=pid,
            persona_nombre="x", fecha=fecha, hora_inicio="09:00", hora_fin="17:00",
        ))

    def usuario_de(self, pid):
        return self.c.execute("SELECT usuario_id FROM workspace_registro_personal WHERE id = ?", (pid,)).fetchone()[0]

    def sesion(self, uid, nombre, apellido="", email=""):
        return {"user_id": uid, "nombre": nombre, "apellido": apellido, "email": email}


class EleccionDentroDelWorkspaceTests(_Base):
    def test_gana_la_ficha_con_historial_aunque_la_otra_se_haya_tocado_despues(self):
        self.usuario("u1", "Ana")
        self.ficha("buena", "Ana", "u1", creada="2026-03-31 10:00:00", modificada="2026-09-18 10:04:04")
        self.ficha("vacia", "Ana", "u1", creada="2026-08-27 08:00:00", modificada="2026-09-18 10:04:05")
        self.fichaje("buena", "2026-07-20")
        self.assertEqual(S.workspace_persona_id_for_user(self.c, self.ws, "u1"), "buena")

    def test_la_limpieza_del_arranque_conserva_la_ficha_con_historial(self):
        self.usuario("u1", "Ana")
        self.ficha("buena", "Ana", "u1", creada="2026-03-31 10:00:00", modificada="2026-04-01 10:00:00")
        self.ficha("vacia", "Ana", "u1", creada="2026-08-27 08:00:00", modificada="2026-09-18 10:04:05")
        self.fichaje("buena", "2026-07-20")
        S.ensure_workspace_product_tables(self.c)
        self.assertEqual(self.usuario_de("buena"), "u1", "desvinculó la ficha con los fichajes")
        self.assertIsNone(self.usuario_de("vacia"))


class ElAvisoNoEditaLaFichaTests(_Base):
    def test_enviar_un_aviso_no_mueve_updated_at(self):
        self.usuario("u1", "Ana")
        self.ficha("p1", "Ana", "u1", modificada="2026-04-01 10:00:00")
        S._update_alert_last_sent(self.c, self.ws, "p1", {"missing_checkin": "2026-09-18"}, now="2026-09-18T10:04:04+02:00")
        row = self.c.execute("SELECT updated_at, alert_last_sent FROM workspace_registro_personal WHERE id='p1'").fetchone()
        self.assertEqual(row["updated_at"], "2026-04-01 10:00:00")
        self.assertIn("2026-09-18", row["alert_last_sent"])


class FichaHuerfanaSeRecuperaTests(_Base):
    def test_ficha_de_un_usuario_borrado_se_vincula_al_nuevo_por_nombre(self):
        # El caso de Modernia Centro: la ficha apunta al usuario antiguo, que ya no existe.
        self.usuario("nuevo", "Claudio", "Anca Georgiu")
        self.ficha("f-claudio", "Claudio Anca Georgiu", "usuario-borrado")
        pid = S.ensure_workspace_persona_for_self(self.c, self.ws, self.sesion("nuevo", "Claudio", "Anca Georgiu"))
        self.assertEqual(pid, "f-claudio")
        self.assertEqual(self.usuario_de("f-claudio"), "nuevo")
        n = self.c.execute("SELECT COUNT(*) FROM workspace_registro_personal WHERE workspace_id=?", (self.ws,)).fetchone()[0]
        self.assertEqual(n, 1, "creó una ficha nueva en vez de recuperar la suya")

    def test_ficha_de_un_usuario_desactivado_se_recupera_por_email(self):
        self.usuario("viejo", "Sergio", activo=0)
        self.usuario("nuevo", "S", "Sanchez", email="sergio@x.test")
        self.ficha("f-sergio", "SERGIO SANCHEZ GARCIA", "viejo", email="sergio@x.test")
        pid = S.ensure_workspace_persona_for_self(self.c, self.ws, self.sesion("nuevo", "S", "Sanchez", "sergio@x.test"))
        self.assertEqual(pid, "f-sergio")

    def test_la_ficha_de_otro_usuario_vivo_no_se_toca(self):
        self.usuario("ana", "Ana", "Ruiz")
        self.usuario("ana2", "Ana", "Ruiz")
        self.ficha("f-ana", "Ana Ruiz", "ana")
        S.ensure_workspace_persona_for_self(self.c, self.ws, self.sesion("ana2", "Ana", "Ruiz"))
        self.assertEqual(self.usuario_de("f-ana"), "ana")

    def test_usuario_sigue_activo(self):
        self.usuario("vivo", "A")
        self.usuario("baja", "B", activo=0)
        self.assertTrue(S.usuario_sigue_activo(self.c, "vivo"))
        self.assertFalse(S.usuario_sigue_activo(self.c, "baja"))
        self.assertFalse(S.usuario_sigue_activo(self.c, "no-existe"))
        self.assertFalse(S.usuario_sigue_activo(self.c, ""))


class NoSeFabricanFichasVaciasTests(_Base):
    def test_entrar_en_otro_workspace_no_le_crea_una_ficha_vacia(self):
        self.usuario("u1", "Miguel", "Perez")
        self.usuario("u1", "Miguel", "Perez", ws=self.otro)
        self.ficha("buena", "Miguel Perez", "u1")
        self.fichaje("buena", "2026-07-20")
        pid = S.ensure_workspace_persona_for_self(self.c, self.otro, self.sesion("u1", "Miguel", "Perez"))
        self.assertEqual(pid, "")
        n = self.c.execute("SELECT COUNT(*) FROM workspace_registro_personal WHERE workspace_id=?", (self.otro,)).fetchone()[0]
        self.assertEqual(n, 0)

    def test_con_el_fichaje_desactivado_no_se_crea_ficha_aunque_el_servicio_sea_operativo(self):
        # Los asistentes automáticos tienen todos los servicios; el atajo por servicio les
        # creaba ficha aunque el administrador hubiera desactivado su fichaje.
        self.usuario("bot", "Asistente", "IA", rh=0)
        pid = S.ensure_workspace_persona_for_self(self.c, self.ws, self.sesion("bot", "Asistente", "IA"))
        self.assertEqual(pid, "")
        n = self.c.execute("SELECT COUNT(*) FROM workspace_registro_personal").fetchone()[0]
        self.assertEqual(n, 0)

    def test_quien_no_tiene_ficha_en_ningun_sitio_si_la_estrena(self):
        self.usuario("u2", "Nuevo", "Empleado")
        pid = S.ensure_workspace_persona_for_self(self.c, self.ws, self.sesion("u2", "Nuevo", "Empleado"))
        self.assertTrue(pid)
        self.assertEqual(self.usuario_de(pid), "u2")


class DiagnosticoTests(_Base):
    def test_detecta_los_tres_casos_de_aquel_dia(self):
        self.usuario("ok", "Alicia")
        self.ficha("f-ok", "Alicia", "ok")
        self.ficha("f-huerfana", "Claudio Anca", "usuario-borrado")
        self.fichaje("f-huerfana", "2026-04-23")
        self.usuario("sin", "Sergio")
        self.usuario("varios", "Barbara")
        self.ficha("f-varios", "Barbara", "varios")
        self.ficha("f-varios-otro", "Barbara", "varios", ws=self.otro)

        d = S.diagnostico_fichas_del_workspace(self.c, self.ws)

        self.assertEqual([h["nombre"] for h in d["fichas_huerfanas"]], ["Claudio Anca"])
        self.assertEqual(d["fichas_huerfanas"][0]["motivo"], "usuario_no_existe")
        self.assertEqual(d["fichas_huerfanas"][0]["fichajes"], 1)
        self.assertEqual([u["usuario_id"] for u in d["usuarios_sin_ficha"]], ["sin"])
        self.assertEqual([v["usuario_id"] for v in d["fichas_en_varios_workspaces"]], ["varios"])
        self.assertEqual(d["fichas_en_varios_workspaces"][0]["tambien_en"], ["Verifika2"])

    def test_un_workspace_sano_no_avisa_de_nada(self):
        self.usuario("ok", "Alicia")
        self.ficha("f-ok", "Alicia", "ok")
        d = S.diagnostico_fichas_del_workspace(self.c, self.ws)
        self.assertEqual(d, {"fichas_huerfanas": [], "usuarios_sin_ficha": [], "fichas_en_varios_workspaces": []})

    def test_el_sin_ficha_dice_donde_tiene_la_suya(self):
        self.usuario("u1", "Miguel")
        self.usuario("u1", "Miguel", ws=self.otro)
        self.ficha("f", "Miguel", "u1", ws=self.otro)
        d = S.diagnostico_fichas_del_workspace(self.c, self.ws)
        self.assertEqual(d["usuarios_sin_ficha"][0]["ficha_en"], ["Verifika2"])


class RutaDelDiagnosticoTests(unittest.TestCase):
    SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
    APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    def test_solo_la_ve_quien_gestiona_el_workspace(self):
        i = self.SERVER.index('if path == "/api/workspace_registro_diagnostico":')
        bloque = self.SERVER[i : self.SERVER.index("if path ==", i + 20)]
        self.assertIn("workspace_actor_can_manage_workspace", bloque)
        self.assertIn("status=403", bloque)

    def test_el_aviso_se_pinta_solo_para_el_gestor(self):
        self.assertIn('${manager ? renderWorkspaceRrhhDiagnostico() : ""}', self.APP)

    def test_el_aviso_sale_tambien_en_la_pestana_equipo(self):
        # Equipo usa diseño a pantalla completa y oculta la barra lateral: en su primera
        # versión el aviso solo vivía allí y en Equipo, donde más falta hace, no salía.
        self.assertIn('tab === "equipo" ? `${manager ? renderWorkspaceRrhhDiagnostico() : ""}${renderEquipo()}`', self.APP)


if __name__ == "__main__":
    unittest.main()
