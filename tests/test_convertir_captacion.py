"""Marcar un inmueble como vendido, alquilado o cerrado no funcionaba. Nunca.

Salió revisando las ocho consultas con `WHERE id = ? AND empresa_id = ?`. Siete eran
correctas —usan la empresa del propio registro, o ya tienen su rama de workspace— y la
octava, en `/api/captacion_convert`, destapó algo bastante peor que lo que buscaba.

El endpoint hace:

    destino = normalize_lookup_text(payload.get("destino") or "")
    destino_map = {"vendido": "Vendido", "alquiler": "Alquiler", ...}
    destino_label = destino_map.get(destino)
    if not destino_label: -> 400

`normalize_lookup_text` devuelve **MAYÚSCULAS**. Las claves están en minúsculas. La
búsqueda no acertaba con ningún valor, así que el endpoint devolvía 400 siempre:
convertir una captación —cerrar una venta, un alquiler, o darla por perdida— no
funcionaba desde ninguna parte. Comprobado en producción sobre una ficha real con los
cinco destinos que usa la interfaz.

Es el mismo despiste que hacía que todos los anuncios del portal se generaran como
venta, incluidos los alquileres: comparar la salida de `normalize_lookup_text` contra
literales en minúsculas.

Y al arreglarlo apareció un segundo fallo, escondido detrás del primero: la rama de
«Encargo» llamaba a `.get()` sobre filas de la base. Con SQLite son `sqlite3.Row`, que
no tiene `.get()`. Esa rama **nunca se había podido ejecutar**, así que el
AttributeError llevaba ahí desde el principio sin que nadie pudiera verlo.

De ahí que este fichero recorra los quince destinos del mapa, y no sólo uno.
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
CLAVE = "Convert1234!"

# Los quince del mapa, con el estado que debe quedar.
DESTINOS = (
    ("noticia", "Noticia"),
    ("inmueble", "Inmueble"),
    ("valoracion", "Valoración"),
    ("adquisicion", "Adquisición"),
    ("encargo", "Encargo"),
    ("propuesta", "Propuesta"),
    ("reservado", "Reservado"),
    ("arras", "Contrato de arras"),
    ("compraventa", "Vendido"),
    ("vendido", "Vendido"),
    ("venta", "Vendido"),
    ("cerradonegativamente", "Cerrado negativamente"),
    ("cerrado_negativamente", "Cerrado negativamente"),
    ("cerrado negativamente", "Cerrado negativamente"),
    ("alquiler", "Alquiler"),
)


class ConvertirCaptacionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "convert.sqlite"
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
            data=json.dumps({"usuario": "conv", "password": CLAVE}).encode(),
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
        self._ins("usuarios", {"id": "u1", "nombre": "Conv", "usuario": "conv", "email": "c@x.test",
                               "rol": "Administrador", "servicio": "Inmobiliaria", "activo": 1,
                               "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inm1", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Convert 1", "estado": "Encargo",
                                "tipo_inmueble": "Piso", "precio_objetivo": 250000,
                                "created_at": AHORA, "updated_at": AHORA})
        self._ins("captaciones", {"id": "cap1", "workspace_id": self.ws, "empresa_id": "emp1",
                                  "inmueble_id": "inm1", "direccion": "Calle Convert 1",
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

    def _estado(self):
        return self.conn.execute("SELECT estado FROM inmuebles WHERE id='inm1'").fetchone()["estado"]

    # ---------- el mapa ----------

    def test_los_quince_destinos_funcionan(self):
        for destino, esperado in DESTINOS:
            with self.subTest(destino=destino):
                estado, cuerpo = self._convertir(
                    destino, precio_encargo=260000, honorarios=3, precio_escritura=245000)
                self.assertEqual(estado, 200, f"{destino}: {cuerpo}")
                self.assertEqual(json.loads(cuerpo).get("destino"), esperado)

    def test_da_igual_como_se_escriba(self):
        """La entrada se normaliza; las claves del mapa también."""
        for escrito in ("vendido", "Vendido", "VENDIDO", " vendido "):
            with self.subTest(escrito=escrito):
                estado, cuerpo = self._convertir(escrito, precio_escritura=245000)
                self.assertEqual(estado, 200, cuerpo)
                self.assertEqual(json.loads(cuerpo).get("destino"), "Vendido")

    def test_un_destino_inventado_se_rechaza(self):
        estado, cuerpo = self._convertir("teletransportado")
        self.assertEqual(estado, 400, cuerpo)

    def test_el_estado_del_inmueble_cambia_de_verdad(self):
        """Que devuelva 200 no basta: hay que ver el cambio en la base."""
        self._convertir("vendido", precio_escritura=245000)
        self.assertEqual(self._estado(), "Vendido")
        self._convertir("alquiler", precio=1200)
        self.assertEqual(self._estado(), "Alquiler")

    # ---------- la rama que nunca se había ejecutado ----------

    def test_pasar_a_encargo_no_revienta(self):
        """Llamaba a `.get()` sobre un `sqlite3.Row`, que no lo tiene."""
        estado, cuerpo = self._convertir("encargo", precio_encargo=260000, honorarios=3)
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._estado(), "Encargo")

    def test_pasar_a_encargo_rellena_los_precios_vacios(self):
        self.conn.execute("UPDATE inmuebles SET precio_objetivo = 0, precio_valoracion = 0 WHERE id='inm1'")
        self.conn.execute("UPDATE captaciones SET precio_objetivo = 0, precio_valoracion = 0 WHERE id='cap1'")
        self.conn.commit()
        estado, cuerpo = self._convertir("encargo", precio_encargo=260000)
        self.assertEqual(estado, 200, cuerpo)
        fila = self.conn.execute(
            "SELECT precio_encargo, precio_objetivo FROM inmuebles WHERE id='inm1'").fetchone()
        self.assertEqual(fila["precio_encargo"], 260000)
        self.assertEqual(fila["precio_objetivo"], 260000)

    # ---------- el ámbito ----------

    def test_funciona_mandando_el_workspace(self):
        """Se buscaba la captación filtrando por la empresa técnica de plataforma."""
        estado, cuerpo = self._convertir("reservado")
        self.assertEqual(estado, 200, cuerpo)

    def test_funciona_mandando_la_empresa(self):
        cuerpo_peticion = {"captacion_id": "cap1", "empresa_nombre": "Agencia Propia",
                           "destino": "reservado"}
        req = urllib.request.Request(
            self.base + "/api/captacion_convert", data=json.dumps(cuerpo_peticion).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)

    def test_una_captacion_de_otra_empresa_sigue_denegada(self):
        # La empresa ajena tiene que colgar de OTRO workspace. Si se deja suelta y en
        # la base sólo hay un workspace, salta un respaldo heredado que lo trata como
        # contenedor implícito y concede el acceso. En producción hay cuatro
        # workspaces y ese respaldo no aplica; el banco tiene que parecerse a eso o
        # el test comprueba una situación que no existe.
        self._ins("empresas", {"id": "empX", "nombre": "Ajena", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspaces", {"id": "wsAjeno", "nombre": "WS Ajeno", "slug": "ws-ajeno",
                                 "estado": "Activo", "plan": "Enterprise",
                                 "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "weX", "workspace_id": "wsAjeno",
                                         "empresa_id": "empX", "created_at": AHORA,
                                         "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inmX", "workspace_id": "wsAjeno", "empresa_id": "empX",
                                "direccion": "Ajena 1", "estado": "Encargo",
                                "created_at": AHORA, "updated_at": AHORA})
        self._ins("captaciones", {"id": "capX", "workspace_id": "wsAjeno", "empresa_id": "empX",
                                  "inmueble_id": "inmX", "direccion": "Ajena 1",
                                  "etapa": "Encargo", "created_at": AHORA, "updated_at": AHORA})
        cuerpo_peticion = {"captacion_id": "capX", "workspace_id": self.ws, "destino": "vendido"}
        req = urllib.request.Request(
            self.base + "/api/captacion_convert", data=json.dumps(cuerpo_peticion).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                self.fail(f"debería denegar y devolvió {r.status}")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))


class SqlQueSoloFallaEnPostgresTests(unittest.TestCase):
    """`SELECT DISTINCT` ordenando por una columna que no está en la selección.

    SQLite lo acepta. Postgres lo rechaza:

        for SELECT DISTINCT, ORDER BY expressions must appear in select list

    Convertir una captación a Vendido o Alquiler pasaba por una consulta así y
    devolvía 500 **sólo en producción**: la suite entera, que corre sobre SQLite, la
    daba por buena. Apareció verificando el arreglo del mapa de destinos contra la
    base de verdad.

    Este test no puede ejecutar Postgres, así que revisa la forma del SQL. Es una red
    más floja que una prueba real, pero coge exactamente el error que costó encontrar.
    """

    @staticmethod
    def _consultas_invalidas():
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        # Las listas de columnas que se interpolan por variable se resuelven antes,
        # o darían falsos positivos: `cliente_list_cols` contiene `c.nombre`.
        variables = dict(re.findall(r'(\w+_cols)\s*=\s*"""(.*?)"""', fuente, re.S))
        malas = []
        for m in re.finditer(r'"""(.*?)"""', fuente, re.S):
            sql = m.group(1)
            if "SELECT DISTINCT" not in sql.upper():
                continue
            for nombre, valor in variables.items():
                sql = sql.replace("{" + nombre + "}", valor)
            sel = re.search(r"SELECT\s+DISTINCT\s+(.*?)\s+FROM\s", sql, re.S | re.I)
            orden = re.search(r"ORDER BY\s+(.+?)(?:\s+LIMIT|\s*$)", sql, re.S | re.I)
            if not sel or not orden:
                continue
            for expr in [e.strip() for e in orden.group(1).split(",")]:
                col = expr.split()[0] if expr.split() else ""
                if not re.match(r"^[a-z_]+\.[a-z_]+$", col, re.I):
                    continue
                alias = col.split(".")[1]
                if col in sel.group(1) or re.search(rf"\bAS\s+{alias}\b", sel.group(1), re.I):
                    continue
                malas.append((fuente[:m.start()].count("\n") + 1, col))
        return malas

    def test_no_queda_ninguna(self):
        malas = self._consultas_invalidas()
        self.assertEqual(malas, [], f"consultas que Postgres rechazará: {malas}")

    def test_la_del_candidato_a_comprador_agrupa(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def resolve_inmobiliaria_contact_candidate")
        bloque = fuente[i:i + 4000]
        self.assertIn("MAX(v.created_at) AS ultima_visita", bloque)
        self.assertIn("GROUP BY d.cliente_id", bloque)


class LasOtrasSieteConsultasTests(unittest.TestCase):
    """Las otras siete estaban bien, y conviene dejar dicho por qué.

    Se revisaron una a una en vez de cambiarlas en bloque:

    * `fetch_inmueble_for_empresa` y `fetch_demanda_for_empresa` reciben la empresa del
      llamante; con el resolutor múltiple se les pasa el ámbito correcto.
    * `ensure_captacion_for_inmueble` también la recibe (y ahora se le pasa la del
      inmueble, no la técnica).
    * `/api/inmueble_compradores`, `/api/inmueble_visita_pdf` y
      `/api/inmueble_visita_docs` comparan contra `inmueble["empresa_id"]`: la empresa
      del propio registro, que es exactamente lo que hay que comprobar.
    * `/api/inmueble_delete` ya tenía su rama de workspace y sólo cae al filtro por
      empresa cuando no viene workspace.
    """

    def test_el_borrado_de_inmuebles_tiene_rama_de_workspace(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index('elif parsed.path == "/api/inmueble_delete"')
        bloque = fuente[i:i + 3000]
        self.assertIn("fetch_workspace_company_ids(conn, workspace_id)", bloque)

    def test_las_visitas_comparan_contra_la_empresa_del_inmueble(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('(demanda_id, inmueble["empresa_id"])', fuente)


if __name__ == "__main__":
    unittest.main()
