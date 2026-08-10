"""Una columna de fecha no puede acabar guardando el texto «now».

El manejador de POST trabajaba con `now = "now"`: se pasaba como parámetro y se
envolvía en `datetime(?)`, que en SQLite resuelve ese literal a la hora UTC. Donde
alguien olvidó envolverlo, la columna se quedaba con las tres letras dentro.

En producción había **263 filas así**, repartidas en 18 columnas: la fecha de
conversión de captaciones, `demandas`, `inmueble_compradores`, `alquileres`,
`clientes_empresas` y 104 líneas de la bitácora de fichajes. Una fecha que dice
«now» no ordena, no entra en un filtro por rango y no resta días.

Salió tirando del hilo de otra cosa: al limpiar la ficha de pruebas de la auditoría
apareció una fila de `alquileres` con `created_at = 'now'`.

El arreglo es de raíz —`now` vale ya una marca de tiempo de verdad— y no sitio a
sitio: había 27 escrituras comprobables y otras 73 con el SQL montado a trozos que
no se pueden verificar leyendo el código. Con el valor arreglado, las que envuelven
siguen igual y las descuidadas dejan de mentir.

Este fichero comprueba las dos mitades: que un camino que guarda `now` en crudo
escribe una fecha de verdad, y que nadie devuelve la constante a su sitio.
"""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-10 09:00:00"
CLAVE = "Fechas1234!"
FORMA_DE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")


class LaConstanteTests(unittest.TestCase):
    def test_now_ya_no_es_el_texto_now(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn('\n        now = "now"\n', fuente,
                         "ha vuelto la constante que escribía «now» en las columnas de fecha")

    def test_y_se_calcula_en_utc(self):
        """Es lo que devolvía `datetime('now')` y lo que hay guardado; cambiarlo a
        hora local desplazaría dos horas todo lo nuevo respecto de lo viejo."""
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def _do_POST")
        bloque = fuente[i:i + 90000]
        m = re.search(r"^        now = (.+)$", bloque, re.M)
        self.assertIsNotNone(m, "no se encuentra la asignación de `now` en _do_POST")
        self.assertIn("timezone.utc", m.group(1))
        self.assertIn("%Y-%m-%d %H:%M:%S", m.group(1))


class LoQueSeGuardaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fechas.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self._seed()
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "fechas", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            self.cookie = r.headers.get("Set-Cookie").split(";")[0]

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
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _seed(self):
        self._ins("empresas", {"id": "empPlat", "nombre": "Verifika2", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia Propia", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        for i, eid in enumerate(("empPlat", "emp1")):
            self._ins("workspace_empresas", {"id": f"we{i}", "workspace_id": self.ws,
                                             "empresa_id": eid, "created_at": AHORA, "updated_at": AHORA})
        self._ins("usuarios", {"id": "u1", "nombre": "Fechas", "usuario": "fechas",
                               "email": "f@x.test", "rol": "Administrador",
                               "servicio": "Inmobiliaria", "activo": 1,
                               "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inm1", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Fechas 1", "estado": "Encargo",
                                "tipo_inmueble": "Piso", "precio_objetivo": 250000,
                                "created_at": AHORA, "updated_at": AHORA})
        self._ins("captaciones", {"id": "cap1", "workspace_id": self.ws, "empresa_id": "emp1",
                                  "inmueble_id": "inm1", "direccion": "Calle Fechas 1",
                                  "etapa": "Encargo", "precio_objetivo": 250000,
                                  "created_at": AHORA, "updated_at": AHORA})

    def _convertir(self, destino, **extra):
        cuerpo = {"captacion_id": "cap1", "workspace_id": self.ws, "destino": destino}
        cuerpo.update(extra)
        req = urllib.request.Request(
            self.base + "/api/captacion_convert", data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _valores(self, sql):
        return [v for fila in self.conn.execute(sql) for v in tuple(fila) if v is not None]

    def _comprueba(self, valores, donde):
        self.assertTrue(valores, f"{donde}: no hay nada que comprobar, el test no prueba nada")
        for v in valores:
            with self.subTest(donde=donde, valor=v):
                self.assertNotEqual(str(v).strip().lower(), "now",
                                    f"{donde} ha guardado el texto «now» en vez de una fecha")
                self.assertRegex(str(v), FORMA_DE_FECHA, f"{donde} no tiene forma de fecha")

    def test_la_fecha_de_conversion_es_una_fecha(self):
        """`fecha_conversion = ?` va sin envolver: es uno de los sitios afectados."""
        estado, cuerpo = self._convertir("vendido", precio_escritura=245000)
        self.assertEqual(estado, 200, cuerpo)
        self._comprueba(
            self._valores("SELECT fecha_conversion FROM captaciones WHERE id='cap1'"),
            "captaciones.fecha_conversion")

    def test_el_alquiler_que_se_crea_al_cerrar(self):
        """La fila de `alquileres` con `created_at = 'now'` fue la que destapó esto."""
        estado, cuerpo = self._convertir("alquiler", precio=1200, honorarios=1200)
        self.assertEqual(estado, 200, cuerpo)
        self._comprueba(
            self._valores("SELECT created_at, updated_at FROM alquileres"),
            "alquileres")

    def test_la_operacion_inmobiliaria(self):
        self._convertir("vendido", precio_escritura=245000, honorarios=3)
        self._comprueba(
            self._valores("SELECT created_at, updated_at FROM operaciones_inmobiliarias"),
            "operaciones_inmobiliarias")

    def test_lo_que_ya_iba_envuelto_sigue_bien(self):
        """`updated_at = datetime(?)` era el camino correcto: no puede romperse."""
        self._convertir("reservado")
        self._comprueba(
            self._valores("SELECT updated_at FROM inmuebles WHERE id='inm1'"),
            "inmuebles.updated_at")

    def test_ninguna_columna_de_fecha_acaba_diciendo_now(self):
        """La red ancha: se convierte y se barre la base entera buscando el literal."""
        self._convertir("vendido", precio_escritura=245000, honorarios=3)
        self._convertir("alquiler", precio=1200)
        sucias = []
        for (tabla,) in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            for fila in self.conn.execute(f"pragma table_info({tabla})").fetchall():
                col = fila[1]
                if not re.search(r"_at$|^fecha|_date$|fecha_", col):
                    continue
                n = self.conn.execute(
                    f"SELECT COUNT(*) c FROM {tabla} WHERE lower(trim({col})) = 'now'").fetchone()["c"]
                if n:
                    sucias.append(f"{tabla}.{col} ({n})")
        self.assertEqual(sucias, [], f"columnas de fecha con el texto «now»: {sucias}")


if __name__ == "__main__":
    unittest.main()
