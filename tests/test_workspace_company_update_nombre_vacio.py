"""`/api/workspace_company_create` exige `nombre` no vacío, pero
`/api/workspace_company_update` no comprobaba nada: aceptaba `nombre=""` y lo
grababa tal cual en `workspace_companies` y, si había `legacy_empresa_id`,
también en la tabla legacy `empresas`. El campo `nombre` del formulario de
edición además va `disabled` en el HTML, así que un guardado con ese campo
vacío en el DOM se cuela sin que nadie lo pida a propósito. El resultado es
una empresa que sigue operativa (CIF, logo, empresas vinculadas...) pero sin
ningún texto que la identifique en "Empresas operativas".
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
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-15 09:00:00"
CLAVE = "Contrasena1!"


class ElNombreDeLaEmpresaNoPuedeQuedarVacioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "g.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("usuarios", dict(id="u-admin", nombre="Admin", usuario="admin_ws",
                                    email="admin@x.test", rol="Gestor", servicio="Gestoría",
                                    activo=1, password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm-admin", workspace_id=self.ws,
                                              usuario_id="u-admin", rol="Owner", **base))
        self.company_id = "wc-1"
        self._ins("workspace_companies", dict(
            id=self.company_id, workspace_id=self.ws, legacy_empresa_id="",
            nombre="Estudio Velazquez 2012 SL", nif="B93227643", direccion="",
            logo_url="", primary_color="", accent_color="", activo=1, **base))

        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._login("admin_ws")

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()))
        self.conn.commit()

    def _login(self, usuario):
        return self._lanza(urllib.request.Request(
            self.base + "/api/login", method="POST",
            data=json.dumps({"usuario": usuario, "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}))["cookie"]

    def _post(self, ruta, cuerpo):
        req = urllib.request.Request(self.base + ruta, method="POST",
                                      data=json.dumps(cuerpo).encode(),
                                      headers={"Content-Type": "application/json"})
        req.add_header("Cookie", self.cookie)
        return self._lanza(req)

    def _lanza(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo, galleta = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "json": self._json(cuerpo),
                        "cookie": galleta.split(";")[0] if galleta else None}
        except urllib.error.HTTPError as e:
            return {"estado": e.code, "json": self._json(e.read())}

    @staticmethod
    def _json(cuerpo):
        try:
            return json.loads(cuerpo.decode() or "{}")
        except Exception:
            return {}

    def _nombre_actual(self):
        row = self.conn.execute(
            "SELECT nombre FROM workspace_companies WHERE id = ?", (self.company_id,)
        ).fetchone()
        return row["nombre"]

    def test_nombre_vacio_se_rechaza(self):
        resp = self._post("/api/workspace_company_update", {
            "workspace_id": self.ws, "id": self.company_id, "nombre": "",
        })
        self.assertEqual(resp["estado"], 400)
        self.assertIn("nombre", (resp["json"].get("error") or "").lower())
        self.assertEqual(self._nombre_actual(), "Estudio Velazquez 2012 SL")

    def test_nombre_solo_espacios_se_rechaza(self):
        resp = self._post("/api/workspace_company_update", {
            "workspace_id": self.ws, "id": self.company_id, "nombre": "   ",
        })
        self.assertEqual(resp["estado"], 400)
        self.assertEqual(self._nombre_actual(), "Estudio Velazquez 2012 SL")

    def test_nombre_valido_sigue_funcionando(self):
        resp = self._post("/api/workspace_company_update", {
            "workspace_id": self.ws, "id": self.company_id, "nombre": "Nuevo Nombre SL",
        })
        self.assertEqual(resp["estado"], 200)
        self.assertEqual(self._nombre_actual(), "Nuevo Nombre SL")

    def test_actualizar_otro_campo_sin_tocar_nombre_no_se_bloquea(self):
        resp = self._post("/api/workspace_company_update", {
            "workspace_id": self.ws, "id": self.company_id, "nif": "B00000000",
        })
        self.assertEqual(resp["estado"], 200)
        self.assertEqual(self._nombre_actual(), "Estudio Velazquez 2012 SL")


if __name__ == "__main__":
    unittest.main()
