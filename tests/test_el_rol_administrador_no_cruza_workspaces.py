"""Con `APP_SUPERADMIN_ENFORCE=1`, un Administrador se ciñe a sus workspaces.

Hallazgo del 2026-08-09, auditando la agenda del CRM inmobiliario.
`workspace_session_is_privileged()` devuelve True para cualquier sesión cuyo rol sea
Administrador, Admin, Dirección, Control o Administración, y
`workspace_actor_is_privileged()` lo respeta mientras `APP_SUPERADMIN_ENFORCE` valga
`0`, que es su valor por defecto. Esa vía **se salta la pertenencia al workspace**.

Medido en producción: 9 de los 17 usuarios activos entran así en los 4 workspaces.
Comprobado levantando el servidor con la estructura real: D.Garcia, miembro sólo de
Modernia, modificó una cita de DEMOCASA. El control inverso descarta que sea un fallo
de la guarda: B.salazar, con rol «Inmobiliaria» y tampoco miembro, recibe 403 en la
misma operación.

Este test no cambia el valor por defecto —eso es una decisión de despliegue—, sino
que deja demostrado que con la bandera puesta el aislamiento funciona y que quien es
miembro no pierde nada.

Dos detalles de producción que hay que reproducir o el test miente:

- Las citas que tienen workspace llevan `empresa_id` = la empresa técnica de
  plataforma («Verifika2»), que el servidor pone cuando la petición no trae ninguna
  porque el esquema legacy exige `empresa_id NOT NULL`. No es una empresa de negocio.
- La exención del filtro por empresa sólo se aplica **si la petición trae
  `workspace_id`**, que es lo que manda el navegador en modo tenant.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

NOW = "2026-08-09 10:00:00"
PASSWORD = "Secreto123!"


class ElAtajoDeAdministradorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "roles.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()
        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(cls.db_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.cookies = {u: cls._login(u) for u in ("admin_a", "admin_b", "curra_a")}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        if cls._prev_db_path is not None:
            S.Handler.db_path = cls._prev_db_path
        cls.tmp.cleanup()

    def setUp(self):
        S.Handler.db_path = str(self.db_path)
        self._enforce_previo = S.APP_SUPERADMIN_ENFORCE
        self.conn.execute("UPDATE acciones SET asunto = 'Cita de B' WHERE id = 'cita-b'")
        self.conn.commit()

    def tearDown(self):
        S.APP_SUPERADMIN_ENFORCE = self._enforce_previo

    # ---------- montaje ----------

    @classmethod
    def _insert(cls, tabla, datos):
        validas = {r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas and v is not None}
        hueco = ",".join("?" * len(d))
        cls.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({hueco})", tuple(d.values()))
        cls.conn.commit()

    @classmethod
    def _seed(cls):
        # La empresa técnica que el servidor usa de relleno, y una de negocio.
        for eid, nombre in (("emp-tecnica", "Empresa Tecnica"), ("emp-negocio", "Empresa Negocio")):
            cls._insert("empresas", {"id": eid, "nombre": nombre, "activo": 1,
                                     "created_at": NOW, "updated_at": NOW})
        for wid, nombre in (("ws-a", "Workspace A"), ("ws-b", "Workspace B")):
            cls._insert("workspaces", {"id": wid, "nombre": nombre, "slug": wid,
                                       "estado": "Activo", "plan": "Enterprise",
                                       "created_at": NOW, "updated_at": NOW})
        # La de negocio cuelga sólo de A; la técnica, de ninguno (como en producción).
        cls._insert("workspace_empresas", {"id": "we-a", "workspace_id": "ws-a",
                                           "empresa_id": "emp-negocio",
                                           "created_at": NOW, "updated_at": NOW})
        # El rol del usuario y el del workspace son cosas distintas: el primero sale de
        # `usuarios.rol` (Administrador, Lectura, Inmobiliaria…) y es el que dispara el
        # atajo; el segundo vive en `workspace_miembros.rol` y en producción sólo toma
        # tres valores —Owner (9), Miembro (21) y Lectura (8)—. Poner ahí «Inmobiliaria»
        # deja al usuario sin permiso de escritura por `workspace_member_can_write`, que
        # es lo que me pasó al escribir este test.
        gente = [
            ("admin_a", "Administrador", "ws-a", "Owner"),   # administrador de A
            ("admin_b", "Administrador", "ws-b", "Owner"),   # administrador de B
            ("curra_a", "Inmobiliaria", "ws-a", "Miembro"),  # sin rol privilegiado, de A
        ]
        for usuario, rol, workspace, rol_ws in gente:
            cls._insert("usuarios", {"id": f"u-{usuario}", "nombre": usuario, "usuario": usuario,
                                     "email": f"{usuario}@t.test", "rol": rol,
                                     "servicio": "Inmobiliaria", "activo": 1,
                                     "password_hash": S.hash_password(PASSWORD),
                                     "created_at": NOW, "updated_at": NOW})
            cls._insert("workspace_miembros", {"id": f"wm-{usuario}", "workspace_id": workspace,
                                               "usuario_id": f"u-{usuario}", "rol": rol_ws,
                                               "created_at": NOW, "updated_at": NOW})
        for aid, wid in (("cita-a", "ws-a"), ("cita-b", "ws-b")):
            cls._insert("acciones", {"id": aid, "workspace_id": wid, "empresa_id": "emp-tecnica",
                                     "servicio": "inmobiliaria", "fecha": "2026-09-10",
                                     "hora": "10:00", "asunto": f"Cita de {wid[-1].upper()}",
                                     "tipo": "Visita", "responsable": "quien sea",
                                     "estado": "Pendiente", "created_at": NOW, "updated_at": NOW})

    @classmethod
    def _login(cls, usuario):
        req = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": usuario, "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return (r.headers.get("Set-Cookie") or "").split(";")[0]

    def _tocar(self, usuario, accion_id, workspace_id=None):
        """Como lo manda el navegador en modo tenant: con `workspace_id`."""
        cuerpo = {"id": accion_id, "asunto": "TOCADA"}
        if workspace_id:
            cuerpo["workspace_id"] = workspace_id
        req = urllib.request.Request(
            self.base + "/api/acciones_update", data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json", "Cookie": self.cookies[usuario]},
            method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def _asunto(self, accion_id):
        f = self.conn.execute("SELECT asunto FROM acciones WHERE id = ?", (accion_id,)).fetchone()
        return f["asunto"] if f else None

    # ---------- el atajo, tal y como está hoy ----------

    def test_hoy_un_administrador_entra_en_un_workspace_ajeno(self):
        """Documenta el comportamiento por defecto. Si algún día deja de ser así,
        conviene enterarse por aquí y no por una sorpresa."""
        S.APP_SUPERADMIN_ENFORCE = False
        self.assertEqual(self._tocar("admin_a", "cita-b", "ws-b"), 200)
        self.assertEqual(self._asunto("cita-b"), "TOCADA")

    def test_hoy_quien_no_es_administrador_no_entra(self):
        """El atajo es del rol, no un agujero de la guarda de pertenencia."""
        S.APP_SUPERADMIN_ENFORCE = False
        self.assertEqual(self._tocar("curra_a", "cita-b", "ws-b"), 403)
        self.assertEqual(self._asunto("cita-b"), "Cita de B")

    # ---------- con la bandera puesta ----------

    def test_con_la_bandera_el_administrador_ajeno_queda_fuera(self):
        S.APP_SUPERADMIN_ENFORCE = True
        self.assertEqual(self._tocar("admin_a", "cita-b", "ws-b"), 403)
        self.assertEqual(self._asunto("cita-b"), "Cita de B")

    def test_con_la_bandera_tampoco_entra_omitiendo_el_workspace(self):
        S.APP_SUPERADMIN_ENFORCE = True
        self.assertEqual(self._tocar("admin_a", "cita-b"), 403)
        self.assertEqual(self._asunto("cita-b"), "Cita de B")

    def test_con_la_bandera_cada_uno_conserva_lo_suyo(self):
        """Lo que no puede pasar es dejar a la gente sin acceso a su propio trabajo."""
        S.APP_SUPERADMIN_ENFORCE = True
        for usuario, accion, workspace in (("admin_a", "cita-a", "ws-a"),
                                           ("admin_b", "cita-b", "ws-b"),
                                           ("curra_a", "cita-a", "ws-a")):
            with self.subTest(usuario=usuario):
                self.assertEqual(self._tocar(usuario, accion, workspace), 200)


if __name__ == "__main__":
    unittest.main()
