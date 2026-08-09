"""Registrar una compraventa con un propietario nuevo no puede devolver un 500.

Regresión de un fallo que me pertenece. Al cerrar el agujero de los clientes que
nacían sin `workspace_id` —2014 filas en la tabla y 0 devueltas en las listas del
CRM— se puso una barrera: `insert_cliente_scoped` se niega a crear un cliente sin
ámbito. La barrera está bien; lo que faltó fue darle el ámbito a quien lo necesitaba.

`resolve_workspace_id_for_empresa` deduce el workspace a partir de la empresa y, si
la empresa cuelga de varios, devuelve '' antes que adivinar —adivinar sería mezclar
tenants—. El detalle que no se vio: en producción **todas** las empresas cuelgan de
dos workspaces, porque el de plataforma («Verifika²») las contiene todas además del
workspace del cliente. Así que la deducción no resolvía ninguna de las 9 empresas
reales, y las ocho llamadas que no pasaban el dato acababan en

    500  {"error": "compraventas_error: ValueError: No se puede crear el cliente sin
          workspace: ni la petición trae workspace_id ni se deduce de la empresa ..."}

Efecto real: alta de compraventa, alta de captación y alta de propietario en la
ficha reventaban **siempre que el propietario o el comprador no estuviera ya en la
base**. Con gente ya fichada no fallaba, que es por lo que podía pasar desapercibido.

La salida no es adivinar mejor: es usar el ámbito de la petición y, cuando no venga,
cruzar los workspaces de la empresa con los de quien firma. Diez de los diecisiete
usuarios activos pertenecen a un único workspace, así que para ellos el cruce es
único y no hay nada que suponer; si sigue siendo ambiguo se pide el dato con un 400
que se entiende, no con un 500 con un rastro de Python dentro.

El banco de pruebas replica la forma de producción a propósito —empresa técnica en el
workspace de plataforma, empresa real en los dos, usuaria en uno— porque con una
empresa en un solo workspace el fallo no se reproduce.
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


class AltaDeClienteDesdeInmobiliariaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "altas.sqlite"
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

    def _post(self, ruta, cuerpo):
        req = urllib.request.Request(
            self.base + ruta, data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _workspace_del_cliente(self, nif):
        fila = self.conn.execute(
            "SELECT workspace_id FROM clientes WHERE REPLACE(UPPER(COALESCE(nif,'')),' ','') = ? LIMIT 1",
            (nif.upper(),),
        ).fetchone()
        return str(fila["workspace_id"] or "").strip() if fila else None

    @classmethod
    def _seed(cls):
        # `ensure_tables` ya siembra el workspace de plataforma.
        cls.ws_plataforma = cls.conn.execute(
            "SELECT id FROM workspaces WHERE nombre = 'Verifika²' LIMIT 1"
        ).fetchone()["id"]

        cls._insert("empresas", {"id": "empPlat", "nombre": "Verifika2", "activo": 1,
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("empresas", {"id": "empA", "nombre": "Grupo Modernia", "activo": 1,
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspaces", {"id": "wsA", "nombre": "Modernia", "slug": "modernia",
                                   "estado": "Activo", "plan": "Enterprise",
                                   "created_at": NOW, "updated_at": NOW})
        # La forma exacta de producción: la empresa real cuelga de DOS workspaces.
        for wid, (ws, eid) in enumerate((
            (cls.ws_plataforma, "empPlat"),
            (cls.ws_plataforma, "empA"),
            ("wsA", "empA"),
        )):
            cls._insert("workspace_empresas", {"id": f"we{wid}", "workspace_id": ws,
                                               "empresa_id": eid, "created_at": NOW,
                                               "updated_at": NOW})
        cls._insert("usuarios", {"id": "userA", "nombre": "Ana", "usuario": "ana",
                                 "email": "ana@a.test", "rol": "Miembro",
                                 "servicio": "Inmobiliaria", "activo": 1,
                                 "password_hash": S.hash_password(PASSWORD),
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_miembros", {"id": "wm-A", "workspace_id": "wsA",
                                           "usuario_id": "userA", "rol": "Miembro",
                                           "created_at": NOW, "updated_at": NOW})

    # ---------- el fallo ----------

    def test_la_empresa_cuelga_de_dos_workspaces(self):
        """Si esto deja de ser cierto, el resto del fichero no prueba lo que dice."""
        n = self.conn.execute(
            "SELECT COUNT(*) c FROM workspace_empresas WHERE empresa_id = 'empA'"
        ).fetchone()["c"]
        self.assertEqual(n, 2)
        self.assertEqual(S.resolve_workspace_id_for_empresa(self.conn, "empA"), "",
                         "la deducción por empresa no debería resolver: es lo que provocaba el 500")

    def test_compraventa_con_propietario_nuevo(self):
        status, cuerpo = self._post("/api/compraventas", {
            "empresa_nombre": "Grupo Modernia",
            "direccion": "Calle del Alta 1",
            "precio_escritura": 300000,
            "propietario1_nombre": "Persona Recien Fichada",
            "propietario1_nif": "11111111H",
        })
        self.assertEqual(status, 200, cuerpo)
        self.assertEqual(self._workspace_del_cliente("11111111H"), "wsA")

    def test_compraventa_con_comprador_nuevo(self):
        status, cuerpo = self._post("/api/compraventas", {
            "empresa_nombre": "Grupo Modernia",
            "direccion": "Calle del Alta 2",
            "precio_escritura": 250000,
            "propietario1_nombre": "Vendedora Nueva",
            "propietario1_nif": "22222222J",
            "contraparte1_nombre": "Compradora Nueva",
            "contraparte1_nif": "33333333P",
        })
        self.assertEqual(status, 200, cuerpo)
        self.assertEqual(self._workspace_del_cliente("33333333P"), "wsA")

    def test_captacion_con_propietario_nuevo(self):
        status, cuerpo = self._post("/api/captaciones", {
            "empresa_nombre": "Grupo Modernia",
            "direccion": "Calle del Alta 3",
            "propietario": "Propietaria Nueva",
            "propietario_nif": "44444444A",
        })
        self.assertEqual(status, 200, cuerpo)
        self.assertEqual(self._workspace_del_cliente("44444444A"), "wsA")

    def test_captacion_mandando_el_workspace(self):
        """Cuando la petición trae el ámbito, manda ese y no se deduce nada."""
        status, cuerpo = self._post("/api/captaciones", {
            "workspace_id": "wsA",
            "direccion": "Calle del Alta 4",
            "propietario": "Otro Propietario",
            "propietario_nif": "55555555K",
        })
        self.assertEqual(status, 200, cuerpo)
        self.assertEqual(self._workspace_del_cliente("55555555K"), "wsA")

    def test_ningun_cliente_nace_sin_ambito(self):
        """La razón de ser de toda la barrera: sin workspace no lo ve nadie."""
        huerfanos = self.conn.execute(
            "SELECT COUNT(*) c FROM clientes WHERE COALESCE(TRIM(workspace_id), '') = ''"
        ).fetchone()["c"]
        self.assertEqual(huerfanos, 0)

    # ---------- el resolutor, por separado ----------

    def test_el_resolutor_prefiere_lo_que_trae_la_peticion(self):
        sesion = {"user_id": "userA"}
        self.assertEqual(
            S.workspace_para_alta_de_cliente(self.conn, sesion, "empA", "wsA"), "wsA")

    def test_el_resolutor_cruza_empresa_y_firmante(self):
        sesion = {"user_id": "userA"}
        self.assertEqual(
            S.workspace_para_alta_de_cliente(self.conn, sesion, "empA", ""), "wsA",
            "Ana sólo pertenece a wsA: el cruce es único y no hay que suponer nada")

    def test_el_resolutor_no_inventa_cuando_no_puede_saberlo(self):
        # Una sesión sin usuario no permite cruzar nada, y la empresa cuelga de dos.
        self.assertEqual(S.workspace_para_alta_de_cliente(self.conn, {}, "empA", ""), "")


if __name__ == "__main__":
    unittest.main()
