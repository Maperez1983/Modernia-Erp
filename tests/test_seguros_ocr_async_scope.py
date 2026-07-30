"""Regresión: el OCR asíncrono de seguros no debe cruzar datos entre empresas.

Hallazgo verificado en vivo (2026-07-29): /api/seguros_ocr_async encolaba el
payload sin validar la `s3_key`. El worker procesa el job SIN sesión y
decode_seguros_payload solo comprueba la visibilidad de la key cuando hay
sesión, así que un usuario de la empresa A podía encolar el documento de la
empresa B y leer su texto OCR completo (póliza entera: NIF, dirección,
teléfono) consultando /api/ocr_job, que además devolvía cualquier job por id
sin comprobar quién lo pidió.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from web import server as S

NOW = "2026-07-29 10:00:00"
PASSWORD = "Secreto123!"
KEY_DE_B = "seguros/empB/poliza_secreta.pdf"


@unittest.skipUnless(S.S3_SCOPE_ENFORCE, "S3_SCOPE_ENFORCE desactivado en este entorno")
class SegurosOcrAsyncScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "ocr_scope.sqlite"
        cls.jobs_path = Path(cls.tmp.name) / "jobs.sqlite"
        S.ensure_tables(cls.db_path)
        S.ensure_ocr_tables(cls.jobs_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()

        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        cls._prev_ocr_db_path = getattr(S.Handler, "ocr_db_path", None)
        S.Handler.db_path = str(cls.db_path)
        S.Handler.ocr_db_path = str(cls.jobs_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.cookie_ana = cls._login("ana")
        cls.cookie_bea = cls._login("bea")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        if cls._prev_db_path is not None:
            S.Handler.db_path = cls._prev_db_path
        if cls._prev_ocr_db_path is not None:
            S.Handler.ocr_db_path = cls._prev_ocr_db_path
        cls.tmp.cleanup()

    def setUp(self):
        S.Handler.db_path = str(self.db_path)
        S.Handler.ocr_db_path = str(self.jobs_path)

    @classmethod
    def _cols(cls, table):
        return [row[1] for row in cls.conn.execute(f"pragma table_info({table})")]

    @classmethod
    def _insert(cls, table, data):
        usable = {k: v for k, v in data.items() if k in cls._cols(table)}
        cls.conn.execute(
            f"INSERT INTO {table} ({','.join(usable)}) VALUES ({','.join('?' * len(usable))})",
            list(usable.values()),
        )

    @classmethod
    def _seed(cls):
        for empresa_id, nombre in (("empA", "Empresa A SL"), ("empB", "Empresa B SL")):
            cls._insert("empresas", {"id": empresa_id, "nombre": nombre, "activo": 1,
                                     "created_at": NOW, "updated_at": NOW})
        for ws_id in ("wsA", "wsB"):
            cls._insert("workspaces", {"id": ws_id, "nombre": ws_id, "slug": ws_id.lower(),
                                       "estado": "Activo", "plan": "Enterprise",
                                       "created_at": NOW, "updated_at": NOW})
        for ws_id, empresa_id in (("wsA", "empA"), ("wsB", "empB")):
            cls._insert("workspace_empresas", {"id": f"we{ws_id}", "workspace_id": ws_id,
                                               "empresa_id": empresa_id,
                                               "created_at": NOW, "updated_at": NOW})
        for user_id, login, ws_id in (("ua", "ana", "wsA"), ("ub", "bea", "wsB")):
            cls._insert("usuarios", {"id": user_id, "nombre": login, "usuario": login,
                                     "email": f"{login}@t.test", "rol": "Miembro",
                                     "servicio": "Seguros", "activo": 1,
                                     "password_hash": S.hash_password(PASSWORD),
                                     "created_at": NOW, "updated_at": NOW})
            cls._insert("workspace_miembros", {"id": f"wm{user_id}", "workspace_id": ws_id,
                                               "usuario_id": user_id, "rol": "Miembro",
                                               "created_at": NOW, "updated_at": NOW})
        # Documento privado de la empresa B, referenciado por su póliza.
        cls._insert("clientes", {"id": "cliB", "empresa_id": "empB", "nombre": "Cliente B",
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros", {"id": "polB", "empresa_id": "empB", "cliente_id": "cliB",
                                "poliza_key": KEY_DE_B, "created_at": NOW, "updated_at": NOW})
        cls.conn.commit()

    @classmethod
    def _login(cls, usuario):
        request = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": usuario, "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json", "Origin": cls.base},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return (response.headers.get("Set-Cookie") or "").split(";")[0]

    def _post(self, path, payload, cookie):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Origin": self.base,
                     "Cookie": cookie}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def _get_job(self, job_id, cookie):
        url = self.base + "/api/ocr_job?" + urllib.parse.urlencode({"id": job_id})
        request = urllib.request.Request(url, headers={"Cookie": cookie})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_no_puede_encolar_ocr_de_un_documento_de_otra_empresa(self):
        status, body = self._post("/api/seguros_ocr_async",
                                  {"empresa_id": "empA", "workspace_id": "wsA",
                                   "s3_key": KEY_DE_B},
                                  self.cookie_ana)
        self.assertEqual(status, 403, f"se encoló un documento ajeno: {body}")
        self.assertNotIn("job_id", body)

    def test_el_resultado_del_ocr_solo_lo_ve_quien_lo_pidio(self):
        status, body = self._post("/api/seguros_ocr_async",
                                  {"empresa_id": "empA", "workspace_id": "wsA",
                                   "file_base64": "data:application/pdf;base64,JVBERi0xLjQK"},
                                  self.cookie_ana)
        self.assertEqual(status, 200, f"Ana no pudo encolar su propio OCR: {body}")
        job_id = body.get("job_id")
        self.assertTrue(job_id)

        status_bea, _ = self._get_job(job_id, self.cookie_bea)
        self.assertEqual(status_bea, 403, "otro usuario pudo leer el resultado del OCR")

        status_ana, _ = self._get_job(job_id, self.cookie_ana)
        self.assertEqual(status_ana, 200, "el dueño del job no puede consultarlo")


if __name__ == "__main__":
    unittest.main()
