"""La agenda de un workspace no la toca nadie de otro.

Hallazgo verificado en vivo (2026-08-08) auditando la agenda del CRM inmobiliario.
`/api/acciones_update` comprobaba el workspace así:

    payload_ws = str(payload.get("workspace_id") or "").strip()
    current_ws = str(current["workspace_id"] or "").strip()
    if payload_ws and current_ws and payload_ws != current_ws: -> 403

O sea, **sólo si el cliente se molestaba en mandar `workspace_id`**. Omitiendo ese
campo no se comprobaba nada. Y el endpoint está en la lista de exentos del filtro por
empresa, así que tampoco lo paraba nada por ahí. Levantando el servidor, una usuaria
que sólo pertenece al workspace A cambió el asunto de una cita del workspace B y la
base lo guardó.

Crear, borrar y listar sí devolvían 403 —el borrado, de rebote, sólo porque exige
`empresa_nombre`—; modificar era el único hueco de verdad.

De las 170 acciones de producción, 136 no tienen `workspace_id` pero todas tienen
`empresa_id`. Atar sólo por workspace habría dejado esas 136 sin guarda; denegarlas
las habría dejado inaccesibles. `enforce_accion_access` decide sobre el ámbito que la
fila tenga: workspace si lo hay, empresa si no.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Este test levanta un servidor de verdad y hace login. Si `.env` deja un
# DATABASE_URL apuntando a Postgres, el login se va allí y devuelve 401 porque el
# usuario de prueba sólo existe en el SQLite temporal. Se fuerza SQLite aquí.
os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

NOW = "2026-08-08 10:00:00"
PASSWORD = "Secreto123!"


class AgendaAislamientoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "agenda_tenant.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()

        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(cls.db_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        status, _, set_cookie = cls._post("/api/login", {"usuario": "ana", "password": PASSWORD})
        assert status == 200, f"login falló: {status}"
        cls.cookie = (set_cookie or "").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        if cls._prev_db_path is not None:
            S.Handler.db_path = cls._prev_db_path
        cls.tmp.cleanup()

    def setUp(self):
        S.Handler.db_path = str(self.db_path)
        # Cada test parte de las citas ajenas intactas.
        self.conn.execute("UPDATE acciones SET asunto = 'Visita wsB' WHERE id = 'accB'")
        self.conn.execute("UPDATE acciones SET asunto = 'Cita antigua de empB' WHERE id = 'accLegacyB'")
        self.conn.commit()

    # ---------- utilidades ----------

    @classmethod
    def _cols(cls, tabla):
        return [r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")]

    @classmethod
    def _insert(cls, tabla, datos):
        validas = set(cls._cols(tabla))
        d = {k: v for k, v in datos.items() if k in validas}
        hueco = ",".join("?" * len(d))
        cls.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({hueco})", tuple(d.values()))
        cls.conn.commit()

    @classmethod
    def _post(cls, ruta, cuerpo, cookie=None):
        req = urllib.request.Request(
            cls.base + ruta, data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode(), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), None

    def _asunto(self, accion_id):
        fila = self.conn.execute("SELECT asunto FROM acciones WHERE id = ?", (accion_id,)).fetchone()
        return fila["asunto"] if fila else None

    @classmethod
    def _seed(cls):
        for eid, nombre in (("empA", "Empresa A SL"), ("empB", "Empresa B SL")):
            cls._insert("empresas", {"id": eid, "nombre": nombre, "activo": 1,
                                     "created_at": NOW, "updated_at": NOW})
        for ws in ("wsA", "wsB"):
            cls._insert("workspaces", {"id": ws, "nombre": f"WS {ws}", "slug": ws.lower(),
                                       "estado": "Activo", "plan": "Enterprise",
                                       "created_at": NOW, "updated_at": NOW})
        for ws, eid in (("wsA", "empA"), ("wsB", "empB")):
            cls._insert("workspace_empresas", {"id": f"we-{ws}", "workspace_id": ws,
                                               "empresa_id": eid, "created_at": NOW,
                                               "updated_at": NOW})
        # Ana: miembro NO privilegiado, sólo del workspace A.
        cls._insert("usuarios", {"id": "userA", "nombre": "Ana", "usuario": "ana",
                                 "email": "ana@a.test", "rol": "Miembro",
                                 "servicio": "Inmobiliaria", "activo": 1,
                                 "password_hash": S.hash_password(PASSWORD),
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_miembros", {"id": "wm-A", "workspace_id": "wsA",
                                           "usuario_id": "userA", "rol": "Miembro",
                                           "created_at": NOW, "updated_at": NOW})
        for aid, ws, eid, asunto in (
            ("accA", "wsA", "empA", "Visita wsA"),
            ("accB", "wsB", "empB", "Visita wsB"),
            # Sin workspace: la forma que tienen 136 de las 170 citas de producción.
            ("accLegacy", None, "empA", "Cita antigua de empA"),
            ("accLegacyB", None, "empB", "Cita antigua de empB"),
        ):
            cls._insert("acciones", {"id": aid, "workspace_id": ws, "empresa_id": eid,
                                     "servicio": "inmobiliaria", "fecha": "2026-08-20",
                                     "hora": "10:00", "asunto": asunto, "tipo": "Visita",
                                     "estado": "Pendiente", "created_at": NOW,
                                     "updated_at": NOW})

    # ---------- lo que debe seguir funcionando ----------

    def test_puede_editar_una_cita_de_su_workspace(self):
        status, _, _ = self._post("/api/acciones_update",
                                  {"id": "accA", "asunto": "Movida por Ana"}, self.cookie)
        self.assertEqual(status, 200)
        self.assertEqual(self._asunto("accA"), "Movida por Ana")

    def test_puede_editar_una_cita_antigua_de_su_empresa(self):
        """Las 136 sin workspace no pueden quedarse inaccesibles al cerrar el hueco."""
        status, _, _ = self._post("/api/acciones_update",
                                  {"id": "accLegacy", "asunto": "Editada por su dueña"}, self.cookie)
        self.assertEqual(status, 200)
        self.assertEqual(self._asunto("accLegacy"), "Editada por su dueña")

    # ---------- lo que no debe poder hacer ----------

    def test_no_edita_una_cita_de_otro_workspace_aunque_omita_el_campo(self):
        status, cuerpo, _ = self._post("/api/acciones_update",
                                       {"id": "accB", "asunto": "SECUESTRADA"}, self.cookie)
        self.assertEqual(status, 403, cuerpo)
        self.assertEqual(self._asunto("accB"), "Visita wsB")

    def test_tampoco_mandando_el_workspace_ajeno(self):
        status, cuerpo, _ = self._post(
            "/api/acciones_update",
            {"id": "accB", "workspace_id": "wsB", "asunto": "SECUESTRADA"}, self.cookie)
        self.assertEqual(status, 403, cuerpo)
        self.assertEqual(self._asunto("accB"), "Visita wsB")

    def test_no_edita_una_cita_antigua_de_otra_empresa(self):
        status, cuerpo, _ = self._post("/api/acciones_update",
                                       {"id": "accLegacyB", "asunto": "SECUESTRADA"}, self.cookie)
        self.assertEqual(status, 403, cuerpo)
        self.assertEqual(self._asunto("accLegacyB"), "Cita antigua de empB")

    def test_no_borra_una_cita_ajena(self):
        for cuerpo_peticion in (
            {"id": "accB"},
            {"id": "accB", "empresa_nombre": "Empresa B SL"},
            {"id": "accLegacyB", "empresa_nombre": "Empresa B SL"},
        ):
            with self.subTest(peticion=cuerpo_peticion):
                status, cuerpo, _ = self._post("/api/acciones_delete", cuerpo_peticion, self.cookie)
                self.assertIn(status, (400, 403), cuerpo)
                queda = self.conn.execute(
                    "SELECT COUNT(*) c FROM acciones WHERE id = ?",
                    (cuerpo_peticion["id"],)).fetchone()["c"]
                self.assertEqual(queda, 1, "la cita ajena se ha borrado")

    def test_no_crea_citas_dentro_de_otro_workspace(self):
        status, cuerpo, _ = self._post("/api/acciones", {
            "empresa_nombre": "Empresa B SL", "servicio": "inmobiliaria",
            "fecha": "2026-09-01", "hora": "09:00", "asunto": "Metida desde fuera",
            "tipo": "Visita"}, self.cookie)
        self.assertEqual(status, 403, cuerpo)
        creada = self.conn.execute(
            "SELECT COUNT(*) c FROM acciones WHERE asunto = 'Metida desde fuera'").fetchone()["c"]
        self.assertEqual(creada, 0)

    def test_no_lista_la_agenda_de_otro_workspace(self):
        req = urllib.request.Request(self.base + "/api/acciones?workspace_id=wsB",
                                     headers={"Cookie": self.cookie})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_una_cita_que_no_existe_da_404_y_no_403(self):
        """Para no convertir el endpoint en un detector de ids ajenos… y al revés:
        una que existe pero no es suya da 403, no 404."""
        status, _, _ = self._post("/api/acciones_update",
                                  {"id": "no-existe", "asunto": "x"}, self.cookie)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
