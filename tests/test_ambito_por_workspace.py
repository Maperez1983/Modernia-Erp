"""Mandar el workspace en vez de la empresa no puede hacer que te denieguen lo tuyo.

Salió recorriendo los 66 endpoints del CRM inmobiliario uno a uno. Crear una demanda
o una visita mandando `workspace_id` devolvía 403 —«cliente fuera de la empresa»,
«Inmueble fuera del scope de empresa»— mientras que la misma operación mandando
`empresa_nombre` funcionaba.

La causa es la misma que dejó el alta de compraventas devolviendo un 500: cuando la
petición trae workspace y no empresa, el despachador rellena `empresa` con la empresa
técnica de plataforma, porque hay tablas antiguas con `empresa_id NOT NULL`. Pero esa
empresa no es dueña de nada, así que comparar el cliente o el inmueble contra ella los
declara ajenos.

No estaba roto de cara al usuario —el navegador manda `empresa_nombre` en esos dos
formularios—, pero el despachador acepta `workspace_id` a propósito para estos
endpoints, así que la API prometía algo que luego denegaba.

Lo que NO puede pasar al arreglarlo es que se abra la mano: un cliente o un inmueble
de otra empresa tienen que seguir dando 403. De ahí la mitad de este fichero.
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

AHORA = "2026-08-10 09:00:00"
CLAVE = "Ambito1234!"


class AmbitoPorWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.tmp.name) / "ambito.sqlite"
        S.ensure_tables(cls.db)
        cls.conn = S.open_sqlite_conn(str(cls.db), with_row_factory=True)
        cls.ws = cls.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        cls._seed()

        cls._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(cls.db)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": "ambito", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            cls.cookie = r.headers.get("Set-Cookie").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        if cls._prev is not None:
            S.Handler.db_path = cls._prev
        cls.tmp.cleanup()

    @classmethod
    def _ins(cls, tabla, datos):
        validas = {r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        hueco = ",".join("?" * len(d))
        cls.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({hueco})", tuple(d.values()))
        cls.conn.commit()

    @classmethod
    def _seed(cls):
        # La empresa técnica de plataforma, que es la que el despachador usa de relleno.
        cls._ins("empresas", {"id": "empPlat", "nombre": "Verifika2", "activo": 1,
                              "created_at": AHORA, "updated_at": AHORA})
        cls._ins("empresas", {"id": "emp1", "nombre": "Agencia Propia", "activo": 1,
                              "created_at": AHORA, "updated_at": AHORA})
        # Y una empresa de fuera del workspace, para comprobar que se sigue denegando.
        cls._ins("empresas", {"id": "empX", "nombre": "Agencia Ajena", "activo": 1,
                              "created_at": AHORA, "updated_at": AHORA})
        for i, eid in enumerate(("empPlat", "emp1")):
            cls._ins("workspace_empresas", {"id": f"we{i}", "workspace_id": cls.ws,
                                            "empresa_id": eid, "created_at": AHORA, "updated_at": AHORA})
        cls._ins("usuarios", {"id": "u1", "nombre": "Ambito", "usuario": "ambito",
                              "email": "a@x.test", "rol": "Administrador",
                              "servicio": "Inmobiliaria", "activo": 1,
                              "password_hash": S.hash_password(CLAVE),
                              "created_at": AHORA, "updated_at": AHORA})
        cls._ins("workspace_miembros", {"id": "wm1", "workspace_id": cls.ws, "usuario_id": "u1",
                                        "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        cls._ins("clientes", {"id": "cliProp", "empresa_id": "emp1", "workspace_id": cls.ws,
                              "nombre": "Cliente Propio", "nif": "11111111H",
                              "created_at": AHORA, "updated_at": AHORA})
        cls._ins("clientes", {"id": "cliAjeno", "empresa_id": "empX",
                              "nombre": "Cliente Ajeno", "nif": "99999999R",
                              "created_at": AHORA, "updated_at": AHORA})
        comun = {"estado": "Encargo", "tipo_inmueble": "Piso", "poblacion": "Málaga",
                 "created_at": AHORA, "updated_at": AHORA}
        cls._ins("inmuebles", {"id": "inmProp", "workspace_id": cls.ws, "empresa_id": "emp1",
                               "direccion": "Calle Propia 1", **comun})
        cls._ins("inmuebles", {"id": "inmAjeno", "empresa_id": "empX",
                               "direccion": "Calle Ajena 99", **comun})

    def _post(self, ruta, cuerpo):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    # ---------- lo tuyo, dicho de las dos formas ----------

    def test_una_demanda_con_workspace_id(self):
        estado, cuerpo = self._post("/api/demandas", {
            "workspace_id": self.ws, "cliente_id": "cliProp", "tipo": "Piso", "zona": "Centro"})
        self.assertEqual(estado, 200, cuerpo)

    def test_una_demanda_con_empresa_nombre(self):
        """El camino que usa el navegador hoy: no puede romperse al arreglar el otro."""
        estado, cuerpo = self._post("/api/demandas", {
            "empresa_nombre": "Agencia Propia", "cliente_id": "cliProp", "tipo": "Piso"})
        self.assertEqual(estado, 200, cuerpo)

    def test_una_visita_con_workspace_id(self):
        estado, cuerpo = self._post("/api/visitas", {
            "workspace_id": self.ws, "inmueble_id": "inmProp", "cliente_id": "cliProp",
            "fecha": "2026-09-01", "estado": "Prevista"})
        self.assertEqual(estado, 200, cuerpo)

    def test_una_visita_con_empresa_nombre(self):
        estado, cuerpo = self._post("/api/visitas", {
            "empresa_nombre": "Agencia Propia", "inmueble_id": "inmProp",
            "fecha": "2026-09-02", "estado": "Prevista"})
        self.assertEqual(estado, 200, cuerpo)

    # ---------- lo ajeno sigue denegado ----------

    def test_no_se_cuela_un_cliente_de_otra_empresa(self):
        estado, cuerpo = self._post("/api/demandas", {
            "workspace_id": self.ws, "cliente_id": "cliAjeno", "tipo": "Piso"})
        self.assertEqual(estado, 403, cuerpo)

    def test_no_se_cuela_un_inmueble_de_otra_empresa(self):
        estado, cuerpo = self._post("/api/visitas", {
            "workspace_id": self.ws, "inmueble_id": "inmAjeno", "fecha": "2026-09-03"})
        self.assertEqual(estado, 403, cuerpo)

    # ---------- el resolutor ----------

    def test_con_workspace_el_ambito_son_sus_empresas(self):
        ambito = S.empresas_del_ambito(self.conn, self.ws, "empPlat")
        self.assertIn("emp1", ambito)
        self.assertNotIn("empX", ambito)

    def test_sin_workspace_el_ambito_es_la_empresa_dada(self):
        self.assertEqual(S.empresas_del_ambito(self.conn, "", "emp1"), ["emp1"])

    def test_sin_nada_no_hay_ambito(self):
        """Devolver [] hace que el resolutor deniegue, que es lo que debe pasar."""
        self.assertEqual(S.empresas_del_ambito(self.conn, "", ""), [])

    def test_el_resolutor_multiple_distingue_ajeno_de_inexistente(self):
        ajeno = S.resolve_scoped_record_access_multi(
            self.conn, "inmAjeno", ["emp1"], table="inmuebles",
            fetch_fn=S.fetch_inmueble_for_empresa)
        self.assertEqual(ajeno, "forbidden")
        fantasma = S.resolve_scoped_record_access_multi(
            self.conn, "no-existe", ["emp1"], table="inmuebles",
            fetch_fn=S.fetch_inmueble_for_empresa)
        self.assertEqual(fantasma, "missing")


if __name__ == "__main__":
    unittest.main()
