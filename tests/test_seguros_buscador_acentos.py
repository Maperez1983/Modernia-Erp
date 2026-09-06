"""Regresión: el buscador de pólizas no encontraba nombres con tilde.

Hallazgo en producción (2026-09-06): en la pantalla Pólizas del CRM de seguros,
buscar "García" (como cualquier usuario lo escribe) devolvía casi ningún
resultado, mientras que buscar "garcia" (sin tilde) sí encontraba las pólizas.

Causa: `/api/tabla` sólo hacía `LOWER(q)` contra `LOWER(columna)`, y `LOWER()`
no normaliza acentos (ni en SQLite ni en Postgres) -- "GARCÍA" en mayúsculas
sigue teniendo tilde. Como la mayoría de tomadores llegan importados/OCR SIN
tilde ("GARCIA"), quien escribe el apellido bien acentuado se queda casi sin
resultados y sin ningún aviso.

El filtro de cliente del lado del navegador ya normalizaba acentos (por eso en
producción "Buscar cliente..." sí encontraba más filas que "Buscar póliza...",
en la misma pantalla, para el mismo texto). Este test cubre el lado servidor.
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

NOW = "2026-09-06 10:00:00"
PASSWORD = "Secreto123!"


class SegurosBuscadorAcentosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "seguros_acentos.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()

        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        cls._prev_ocr_db_path = getattr(S.Handler, "ocr_db_path", None)
        cls.ocr_db_path = Path(cls.tmp.name) / "ocr.sqlite"
        S.Handler.db_path = str(cls.db_path)
        S.Handler.ocr_db_path = str(cls.ocr_db_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        status, _, set_cookie = cls._post("/api/login", {"usuario": "ana", "password": PASSWORD})
        assert status == 200, f"login fallo: {status}"
        cls.cookie = (set_cookie or "").split(";")[0]

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
        S.Handler.ocr_db_path = str(self.ocr_db_path)

    # ---------- utilidades ----------

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
        cls._insert("empresas", {"id": "empA", "nombre": "Empresa A SL", "activo": 1,
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspaces", {"id": "wsA", "nombre": "WS A", "slug": "wsa",
                                   "estado": "Activo", "plan": "Enterprise",
                                   "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_empresas", {"id": "we-wsA", "workspace_id": "wsA",
                                           "empresa_id": "empA", "created_at": NOW,
                                           "updated_at": NOW})
        cls._insert("usuarios", {"id": "userA", "nombre": "Ana", "usuario": "ana",
                                 "email": "ana@a.test", "rol": "Miembro", "servicio": "Seguros",
                                 "activo": 1, "password_hash": S.hash_password(PASSWORD),
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_miembros", {"id": "wm-A", "workspace_id": "wsA",
                                           "usuario_id": "userA", "rol": "Miembro",
                                           "created_at": NOW, "updated_at": NOW})

        # Como en producción: la mayoría de tomadores llegan SIN tilde (import/OCR),
        # sólo uno tiene la tilde puesta a mano.
        cls._insert("seguros", {"id": "pol-sin-tilde-1", "empresa_id": "empA",
                                "tomador": "DEL PUERTO INMA GARCIA FERROCARRIL",
                                "compania": "OCCIDENT", "ramo": "Hogar",
                                "poliza_numero": "NUM-1", "prima_total": 100.0,
                                "estado": "En vigor", "estado_poliza": "activa",
                                "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros", {"id": "pol-sin-tilde-2", "empresa_id": "empA",
                                "tomador": "ORTEGA GARCIA JUAN MANUEL",
                                "compania": "OCCIDENT", "ramo": "Hogar",
                                "poliza_numero": "NUM-2", "prima_total": 100.0,
                                "estado": "En vigor", "estado_poliza": "activa",
                                "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros", {"id": "pol-con-tilde", "empresa_id": "empA",
                                "tomador": "Fernandez García Daniel",
                                "compania": "PELAYO", "ramo": "Auto",
                                "poliza_numero": "NUM-3", "prima_total": 100.0,
                                "estado": "En vigor", "estado_poliza": "activa",
                                "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros", {"id": "pol-sin-relacion", "empresa_id": "empA",
                                "tomador": "Comunidad de Propietarios Calle Mayor",
                                "compania": "AXA", "ramo": "Comunidad",
                                "poliza_numero": "NUM-4", "prima_total": 100.0,
                                "estado": "En vigor", "estado_poliza": "activa",
                                "created_at": NOW, "updated_at": NOW})
        cls.conn.commit()

    @classmethod
    def _post(cls, path, payload, cookie=None):
        request = urllib.request.Request(
            cls.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Origin": cls.base,
                     **({"Cookie": cookie} if cookie else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode() or "{}"), response.headers.get("Set-Cookie")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}"), None

    def _buscar(self, q):
        params = {
            "tabla": "seguros",
            "empresa_id": "empA",
            "workspace_id": "wsA",
            "include_id": "1",
            "uploaded_only": "0",
            "q": q,
        }
        url = f"{self.base}/api/tabla?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"Cookie": self.cookie}, method="GET")
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode() or "{}")
        rows = body.get("rows", [])
        cols = body.get("columns", [])
        id_idx = cols.index("id") if "id" in cols else None
        return {row[id_idx] for row in rows} if id_idx is not None else set()

    # ---------- tests ----------

    def test_busqueda_sin_tilde_encuentra_tomadores_sin_tilde(self):
        ids = self._buscar("garcia")
        self.assertIn("pol-sin-tilde-1", ids)
        self.assertIn("pol-sin-tilde-2", ids)
        self.assertNotIn("pol-sin-relacion", ids)

    def test_busqueda_con_tilde_encuentra_tambien_los_tomadores_sin_tilde(self):
        """Antes: sólo devolvía pol-con-tilde (el único guardado con tilde),
        perdiendo silenciosamente pol-sin-tilde-1 y pol-sin-tilde-2."""
        ids = self._buscar("García")
        self.assertIn("pol-sin-tilde-1", ids)
        self.assertIn("pol-sin-tilde-2", ids)
        self.assertIn("pol-con-tilde", ids)
        self.assertNotIn("pol-sin-relacion", ids)

    def test_busqueda_sin_tilde_encuentra_tambien_el_tomador_con_tilde(self):
        ids = self._buscar("garcia")
        self.assertIn("pol-con-tilde", ids)

    def test_busqueda_no_relacionada_no_devuelve_nada(self):
        ids = self._buscar("xyz-no-existe")
        self.assertEqual(ids, set())


if __name__ == "__main__":
    unittest.main()
