"""La ficha de un inmueble no la lee nadie de otro workspace.

Hallazgo verificado en local (2026-08-09) auditando los endpoints de lectura del CRM
inmobiliario. Había puerta de sesión global —sin cookie, 401— pero **cinco** GET
resolvían por `inmueble_id` sin comprobar a quién pertenece la ficha:

    /api/inmueble             devuelve `propietarios` con nombre, NIF, teléfono y email
    /api/inmueble_compradores devuelve el nombre del interesado y las notas privadas
    /api/inmueble_matching    devuelve las demandas que encajan, con el cliente de cada una
    /api/inmueble_timeline    devuelve citas, visitas, documentos y notas del expediente
    /api/inmueble_checklist   devuelve el estado documental del expediente

Con una sesión cualquiera y un id ajeno se leía todo eso. Tres de los cinco se
comprobaron devolviendo datos de otro workspace de verdad, no por inspección del
código. Los ids son hex de 32 caracteres, así que no se adivinan a ciegas; pero se
reparten en URLs, correos y PDF, y el modelo de este CRM es multiagencia: el
propietario y su NIF son justo lo que una agencia no puede ver de otra.

Peor que la lectura: `/api/inmueble` acepta también el id de una **captación**, y si
esa captación no tenía ficha todavía, la **creaba**. O sea que un id ajeno no sólo
leía: provocaba un alta dentro de otra empresa. Por eso la guarda de ese camino va
antes del INSERT, sobre la tabla `captaciones`.

La guarda es la que ya existía, `enforce_inmueble_access`, que decide el ámbito por
la fila: workspace si lo tiene, empresa si no. Eso importa porque 81 de los 86
inmuebles de producción son anteriores al campo `workspace_id`: atar sólo por
workspace los habría dejado inaccesibles a sus propios dueños. El test cubre
explícitamente ese caso —`inmLeg`— porque es el que se rompe si alguien «endurece»
la guarda sin mirar los datos.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Con un DATABASE_URL de Postgres en `.env`, el login se iría a producción y
# devolvería 401 porque la usuaria de prueba sólo existe en el SQLite temporal.
os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

NOW = "2026-08-09 10:00:00"
PASSWORD = "Secreto123!"

# Cadenas que sólo existen en los datos del workspace B. Si alguna aparece en una
# respuesta a Ana, hay fuga.
PISTAS_AJENAS = (
    "Calle Ajena 99",
    "Comprador Ajeno",
    "87654321X",
    "600999888",
    "Nota confidencial B",
)


class FichaInmuebleAislamientoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "ficha_tenant.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()

        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(cls.db_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        req = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": "ana", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            assert r.status == 200
            cls.cookie = r.headers.get("Set-Cookie").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        if cls._prev_db_path is not None:
            S.Handler.db_path = cls._prev_db_path
        cls.tmp.cleanup()

    def setUp(self):
        S.Handler.db_path = str(self.db_path)

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

    def _get(self, ruta, con_cookie=True):
        req = urllib.request.Request(self.base + ruta)
        if con_cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

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
        # Ana: miembro no privilegiado, sólo del workspace A.
        cls._insert("usuarios", {"id": "userA", "nombre": "Ana", "usuario": "ana",
                                 "email": "ana@a.test", "rol": "Miembro",
                                 "servicio": "Inmobiliaria", "activo": 1,
                                 "password_hash": S.hash_password(PASSWORD),
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_miembros", {"id": "wm-A", "workspace_id": "wsA",
                                           "usuario_id": "userA", "rol": "Miembro",
                                           "created_at": NOW, "updated_at": NOW})

        comun = {"estado": "Captado", "tipo_inmueble": "Piso", "poblacion": "Sevilla",
                 "created_at": NOW, "updated_at": NOW}
        cls._insert("inmuebles", {"id": "inmA", "workspace_id": "wsA", "empresa_id": "empA",
                                  "direccion": "Calle Propia 1", **comun})
        cls._insert("inmuebles", {"id": "inmB", "workspace_id": "wsB", "empresa_id": "empB",
                                  "direccion": "Calle Ajena 99", **comun})
        # Sin workspace_id: la forma que tienen 81 de los 86 inmuebles de producción.
        cls._insert("inmuebles", {"id": "inmLeg", "empresa_id": "empA",
                                  "direccion": "Calle Antigua 5", **comun})

        cls._insert("clientes", {"id": "cliB", "empresa_id": "empB", "workspace_id": "wsB",
                                 "nombre": "Comprador Ajeno", "nif": "87654321X",
                                 "telefono": "600999888", "email": "ajeno@b.test",
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("inmueble_propietarios", {"id": "ipB", "inmueble_id": "inmB",
                                              "cliente_id": "cliB", "empresa_id": "empB",
                                              "created_at": NOW, "updated_at": NOW})
        cls._insert("demandas", {"id": "demB", "empresa_id": "empB", "workspace_id": "wsB",
                                 "cliente_id": "cliB", "tipo": "Piso", "zona": "Sevilla",
                                 "fase": "Activa", "estado": "Activa",
                                 "presupuesto_max": 300000, "created_at": NOW, "updated_at": NOW})
        cls._insert("inmueble_compradores", {"id": "icB", "empresa_id": "empB",
                                             "inmueble_id": "inmB", "demanda_id": "demB",
                                             "cliente_id": "cliB", "estado": "Pendiente",
                                             "notas": "Nota confidencial B",
                                             "created_at": NOW, "updated_at": NOW})
        # Captación ajena sin ficha: el camino que llegaba a crearla.
        cls._insert("captaciones", {"id": "capB", "empresa_id": "empB", "workspace_id": "wsB",
                                    "direccion": "Captacion Ajena", "created_at": NOW,
                                    "updated_at": NOW})

    # ---------- lo que debe seguir funcionando ----------

    def test_ve_lo_suyo(self):
        for etiqueta, ruta in (
            ("ficha", "/api/inmueble?id=inmA"),
            ("cronología", "/api/inmueble_timeline?inmueble_id=inmA"),
            ("checklist", "/api/inmueble_checklist?inmueble_id=inmA"),
            ("cruce de demandas", "/api/inmueble_matching?inmueble_id=inmA"),
            ("interesados", "/api/inmueble_compradores?inmueble_id=inmA"),
        ):
            with self.subTest(etiqueta):
                status, cuerpo = self._get(ruta)
                self.assertEqual(status, 200, cuerpo)

    def test_ve_las_fichas_antiguas_de_su_empresa(self):
        """81 de los 86 inmuebles de producción no tienen workspace_id.

        Si la guarda exigiera workspace, sus propios dueños dejarían de verlos.
        """
        status, cuerpo = self._get("/api/inmueble?id=inmLeg")
        self.assertEqual(status, 200, cuerpo)
        self.assertIn("Calle Antigua 5", cuerpo)

    # ---------- lo que no debe poder leer ----------

    def test_no_lee_nada_de_otro_workspace(self):
        for etiqueta, ruta in (
            ("ficha con propietario y NIF", "/api/inmueble?id=inmB"),
            ("cronología del expediente", "/api/inmueble_timeline?inmueble_id=inmB"),
            ("checklist documental", "/api/inmueble_checklist?inmueble_id=inmB"),
            ("cruce con su cartera de demanda", "/api/inmueble_matching?inmueble_id=inmB"),
            ("interesados y notas privadas", "/api/inmueble_compradores?inmueble_id=inmB"),
        ):
            with self.subTest(etiqueta):
                status, cuerpo = self._get(ruta)
                self.assertEqual(status, 403, f"{etiqueta}: {cuerpo}")
                for pista in PISTAS_AJENAS:
                    self.assertNotIn(pista, cuerpo, f"{etiqueta} filtra «{pista}»")

    def test_un_id_de_captacion_ajena_ni_se_lee_ni_crea_ficha(self):
        antes = self.conn.execute("SELECT COUNT(*) c FROM inmuebles").fetchone()["c"]
        status, cuerpo = self._get("/api/inmueble?id=capB")
        self.assertEqual(status, 403, cuerpo)
        despues = self.conn.execute("SELECT COUNT(*) c FROM inmuebles").fetchone()["c"]
        self.assertEqual(despues, antes, "la captación ajena ha creado una ficha")

    def test_sin_sesion_no_se_lee_nada(self):
        for ruta in ("/api/inmueble?id=inmA", "/api/inmueble_timeline?inmueble_id=inmA",
                     "/api/inmueble_compradores?inmueble_id=inmA"):
            with self.subTest(ruta):
                status, _ = self._get(ruta, con_cookie=False)
                self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
