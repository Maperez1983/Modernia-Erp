"""El derecho de supresión no tenía forma de ejercerse.

Auditado el 2026-08-04: no había endpoint, ni botón, ni guion. Ni un solo
`DELETE FROM clientes` en las 96.000 líneas del servidor. Las tablas
`clientes_borrados_backup` y `clientes_empresas_borrados_backup` existían pero
nadie escribía en ellas: eran restos de limpiezas hechas a mano.

Un derecho que la aplicación no sabe cumplir es un incumplimiento, no una carencia
de producto.

La decisión de diseño
---------------------
Suprimir NO es borrar la fila. El art. 17.3 b) y e) del RGPD permite —y la Ley
General Tributaria obliga— conservar lo que sostiene una obligación legal:
facturas, asientos, pólizas. Borrar la ficha rompería esos registros, que además
hay que guardar. Lo que desaparece es la identidad: quien mire esas filas después
no puede saber de quién eran.

Las dos listas (lo que se borra y lo que se conserva) están en el servidor, en
constantes con nombre, para que un asesor pueda leerlas y corregirlas sin bucear
en el código.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")


# Las constantes se buscan con el salto de línea delante a propósito: hay otras que
# empiezan por el mismo texto —las del vecino de comunidad— y sin el ancla la prueba
# leía la lista equivocada y fallaba por columnas que sí estaban.
def manejador():
    i = SERVER.index('elif parsed.path == "/api/cliente_suprimir":')
    return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]


class LaPoliticaEstaEscritaTests(unittest.TestCase):
    def test_hay_lista_de_lo_que_se_borra(self):
        self.assertIn("RGPD_TABLAS_A_BORRAR = (", SERVER)

    def test_hay_lista_de_lo_que_se_conserva_y_por_que(self):
        self.assertIn("RGPD_TABLAS_QUE_SE_CONSERVAN = (", SERVER)
        # Cada tabla conservada lleva el motivo al lado; si no, nadie sabe por qué está.
        i = SERVER.index("\nRGPD_TABLAS_QUE_SE_CONSERVAN = (")
        bloque = SERVER[i: SERVER.index("\n)", i)]
        self.assertIn('("gestoria_facturas", "facturas emitidas")', bloque)
        self.assertIn('("hipotecas", "operaciones y comisiones")', bloque)

    def test_la_facturacion_no_se_borra(self):
        """Borrarla incumpliría la obligación de conservación, que va aparte."""
        i = SERVER.index("\nRGPD_TABLAS_A_BORRAR = (")
        a_borrar = SERVER[i: SERVER.index(")\n", i)]
        for tabla in ("gestoria_facturas", "gestoria_asientos", "gestoria_contabilidad", "hipotecas", "seguros"):
            with self.subTest(tabla=tabla):
                self.assertNotIn(f'("{tabla}"', a_borrar)


class ElEndpointTests(unittest.TestCase):
    def test_existe_y_esta_en_la_lista_blanca(self):
        self.assertIn('elif parsed.path == "/api/cliente_suprimir":', SERVER)
        i = SERVER.index("if parsed.path not in (")
        blanca = SERVER[i: SERVER.index('json_response(self, {"error": "Endpoint no valido"}', i)]
        self.assertIn('"/api/cliente_suprimir"', blanca)

    def test_exige_escritura_en_el_workspace(self):
        self.assertIn("enforce_workspace_membership(conn, session, ws_id, write=True)", manejador())

    def test_no_lo_hace_cualquiera(self):
        """Suprimir no es una edición más: hace falta ser responsable del workspace."""
        self.assertIn("workspace_actor_is_privileged(conn, session)", manejador())

    def test_no_se_puede_suprimir_una_ficha_de_otro_workspace(self):
        cuerpo = manejador()
        self.assertIn('clientes_workspace_scope_sql(conn, ws_id, alias="c")', cuerpo)
        self.assertIn("Cliente no encontrado en este workspace", cuerpo)

    def test_la_ficha_deja_de_identificar_pero_no_se_borra(self):
        cuerpo = manejador()
        self.assertIn("UPDATE clientes SET", cuerpo)
        self.assertNotIn("DELETE FROM clientes ", cuerpo)
        self.assertIn("Cliente suprimido", cuerpo)

    def test_vacia_todas_las_columnas_identificativas(self):
        cuerpo = manejador()
        self.assertIn("RGPD_COLUMNAS_IDENTIFICATIVAS", cuerpo)
        i = SERVER.index("\nRGPD_COLUMNAS_IDENTIFICATIVAS = (")
        bloque = SERVER[i: SERVER.index(")\n", i)]
        for columna in ("nif", "telefono", "movil", "email", "direccion", "fecha_nacimiento"):
            with self.subTest(columna=columna):
                self.assertIn(f'"{columna}"', bloque)

    def test_queda_constancia_de_quien_y_cuando(self):
        """El registro de la supresión es lo que demuestra que se atendió."""
        cuerpo = manejador()
        self.assertIn('"supresion_rgpd"', cuerpo)
        self.assertIn("audit_event(", cuerpo)

    def test_devuelve_que_se_borro_y_que_se_conservo(self):
        """Quien atiende la solicitud tiene que poder contestar al interesado."""
        cuerpo = manejador()
        self.assertIn('"borrado": borrados', cuerpo)
        self.assertIn('"conservado": conservados', cuerpo)


class LaPantallaTests(unittest.TestCase):
    def test_hay_boton_en_la_ficha(self):
        self.assertIn('id="clienteSuprimirBtn"', HTML)

    def test_no_basta_con_aceptar_un_aviso(self):
        """Sin vuelta atrás: hay que escribir la palabra."""
        i = APP.index("clienteSuprimirBtn")
        bloque = APP[i:]
        self.assertIn('!== "SUPRIMIR"', bloque)

    def test_el_aviso_dice_lo_que_se_conserva(self):
        i = APP.index("clienteSuprimirBtn")
        bloque = APP[i: i + 2500]
        self.assertIn("Se conservan facturas", bloque)
        self.assertIn("no se puede deshacer", bloque)

    def test_pide_motivo(self):
        i = APP.index("clienteSuprimirBtn")
        self.assertIn("Motivo (queda registrado", APP[i:])


if __name__ == "__main__":
    unittest.main()


class LaMismaPersonaEnOtraTablaTests(unittest.TestCase):
    """La supresión respondía «la ficha ya no identifica a nadie», y podía ser mentira.

    Un cliente puede ser además vecino de una comunidad, socio de una sociedad o
    firmante de un acta. En esas tablas su nombre, NIF, teléfono y hasta el IBAN están
    escritos otra vez, y no cuelgan de `clientes`: suprimir el cliente no las toca.
    Comprobado el 2026-08-21 con un cliente que era también vecino: la ficha quedaba
    anónima y la fila del vecino conservaba los cinco datos.

    No se borran a ciegas —mientras sea propietario de un piso hay base legal para
    conservarlos en la comunidad—, pero quien atiende la solicitud tiene que saber que
    quedan, y hasta ahora se le decía justo lo contrario.
    """

    CLAVE = "Supresion1234!"
    AHORA = "2026-08-21 09:00:00"

    def _monta(self, tambien_vecino):
        from web import server as S
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(conn)
            except Exception:
                pass
        ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]

        def ins(tabla, datos):
            cols = {c[1] for c in conn.execute(f"pragma table_info({tabla})")}
            d = {k: v for k, v in datos.items() if k in cols}
            conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                         f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
            conn.commit()

        b = dict(created_at=self.AHORA, updated_at=self.AHORA)
        ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1, **b))
        ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
        ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                             rol="Administrador", activo=1,
                             password_hash=S.hash_password(self.CLAVE), **b))
        ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1", rol="Owner", **b))
        ins("clientes", dict(id="cli1", nombre="Manuel Ruiz Galvez", nif="25111111A",
                             telefono="600000010", email="manuel@x.test",
                             empresa_id="emp1", workspace_id=ws, **b))
        if tambien_vecino:
            ins("workspace_fincas_comunidades", dict(id="com1", workspace_id=ws, empresa_id="emp1",
                                                     nombre="C.P Ejemplo", estado="Activa", **b))
            ins("workspace_fincas_vecinos", dict(id="v1", workspace_id=ws, comunidad_id="com1",
                                                 nombre="Manuel Ruiz Galvez", nif="25111111A",
                                                 telefono="600000010", email="manuel@x.test",
                                                 iban="ES2321000418400000000001", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
        httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        return conn, ws, httpd.server_address[1]

    def _post(self, puerto, ruta, cuerpo, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=40) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _suprime(self, tambien_vecino):
        conn, ws, puerto = self._monta(tambien_vecino)
        _, _, galleta = self._post(puerto, "/api/login", {"usuario": "ana", "password": self.CLAVE})
        cookie = galleta.split(";")[0]
        estado, cuerpo, _ = self._post(puerto, "/api/cliente_suprimir",
                                       {"cliente_id": "cli1", "empresa_id": "emp1",
                                        "workspace_id": ws, "confirm": "SUPRIMIR",
                                        "motivo": "art.17"}, cookie)
        self.assertEqual(estado, 200, cuerpo)
        return conn, cuerpo

    def test_avisa_de_la_copia_que_queda(self):
        conn, r = self._suprime(tambien_vecino=True)
        self.assertIn("workspace_fincas_vecinos", r.get("copias_que_quedan") or {})
        self.assertIn("vecinos de comunidad", r.get("aviso") or "")
        self.assertNotIn("ya no identifica a nadie. Se conservan", r.get("aviso") or "")
        # Y no ha borrado nada por su cuenta: avisar no es suprimir.
        v = conn.execute("SELECT nif FROM workspace_fincas_vecinos WHERE id='v1'").fetchone()
        self.assertEqual(dict(v)["nif"], "25111111A")

    def test_sin_copias_el_mensaje_es_el_de_siempre(self):
        _, r = self._suprime(tambien_vecino=False)
        self.assertEqual(r.get("copias_que_quedan"), {})
        self.assertIn("ya no identifica a nadie", r.get("aviso") or "")

    def test_la_ficha_del_cliente_si_queda_anonima(self):
        conn, _ = self._suprime(tambien_vecino=True)
        f = dict(conn.execute("SELECT nombre, nif, telefono, email FROM clientes WHERE id='cli1'").fetchone())
        self.assertIn("suprimido", f["nombre"].lower())
        self.assertFalse(any([f["nif"], f["telefono"], f["email"]]), f)


class ElComuneroTambienTieneDerechoTests(unittest.TestCase):
    """Un vecino de comunidad no es un `cliente`, así que `cliente_suprimir` no llegaba a
    su ficha: nombre, NIF, teléfono, correo e IBAN se quedaban enteros. No había forma de
    ejercer el art. 17 sobre él.

    Y el botón «Borrar» que sí existía hacía algo peor que no existir: un DELETE seco.
    Comprobado el 2026-08-21 con un vecino que tenía tres recibos —uno pendiente de
    240 €—: contestaba «ok», borraba la ficha y dejaba los tres apuntando al vacío. La
    comunidad se quedaba con una deuda de la que ya no se sabía de quién era.

    Ahora borrar es sólo para un alta equivocada; quien tiene contabilidad detrás se
    suprime: se le quita la identidad y los apuntes se quedan, que es lo que obliga a
    conservar la LGT y permite el art. 17.3 b). El piso y su coeficiente no son de la
    persona: se quedan en la comunidad.
    """

    CLAVE = "Fincas1234!"
    AHORA = "2026-08-21 09:00:00"

    def _monta(self, recibos=()):
        from web import server as S
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(conn)
            except Exception:
                pass
        ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]

        def ins(tabla, datos):
            cols = {c[1] for c in conn.execute(f"pragma table_info({tabla})")}
            d = {k: v for k, v in datos.items() if k in cols}
            conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                         f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
            conn.commit()

        b = dict(created_at=self.AHORA, updated_at=self.AHORA)
        ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1, **b))
        ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
        for uid, usr, rol, mrol in (("u1", "ana", "Administrador", "Owner"),
                                    ("u2", "raso", "Usuario", "Miembro")):
            ins("usuarios", dict(id=uid, nombre=usr, usuario=usr, email=f"{usr}@x.test",
                                 rol=rol, activo=1,
                                 password_hash=S.hash_password(self.CLAVE), **b))
            ins("workspace_miembros", dict(id=f"wm_{uid}", workspace_id=ws,
                                           usuario_id=uid, rol=mrol, **b))
        ins("workspace_fincas_comunidades", dict(id="com1", workspace_id=ws, empresa_id="emp1",
                                                 nombre="C.P Ejemplo", estado="Activa", **b))
        ins("workspace_fincas_vecinos", dict(id="v1", workspace_id=ws, comunidad_id="com1",
                                             nombre="Manuel Ruiz Galvez", nif="25111111A",
                                             piso="2 B", coeficiente=20.0, telefono="600000010",
                                             email="m@x.test", mandato_ref="MND-25111111A",
                                             iban="ES2321000418400000000001", **b))
        ins("workspace_fincas_portal_accesos", dict(id="pa1", workspace_id=ws, comunidad_id="com1",
                                                    vecino_id="v1", token_hash="abc", revocado=0, **b))
        for n, estado in enumerate(recibos):
            ins("workspace_fincas_recibos", dict(id=f"r{n}", workspace_id=ws, comunidad_id="com1",
                                                 vecino_id="v1", periodo=f"2026-0{n + 6}",
                                                 concepto="Cuota", importe=240.0, estado=estado,
                                                 fecha_emision=f"2026-0{n + 6}-01", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
        httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        return conn, ws, httpd.server_address[1]

    def _post(self, puerto, ruta, cuerpo, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=40) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _entra(self, puerto, usuario="ana"):
        _, _, galleta = self._post(puerto, "/api/login",
                                   {"usuario": usuario, "password": self.CLAVE})
        return galleta.split(";")[0]

    def test_borrar_a_quien_tiene_recibos_no_deja_la_contabilidad_sin_dueno(self):
        conn, ws, puerto = self._monta(recibos=("Cobrado", "Cobrado", "Pendiente"))
        estado, cuerpo, _ = self._post(puerto, "/api/workspace_fincas_vecino_delete",
                                       {"workspace_id": ws, "id": "v1"}, self._entra(puerto))
        self.assertEqual(estado, 409, cuerpo)
        self.assertIn("Suprimir datos (RGPD)", cuerpo.get("error", ""))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM workspace_fincas_recibos r "
                         "JOIN workspace_fincas_vecinos v ON v.id = r.vecino_id").fetchone()[0], 3,
            "los recibos se han quedado sin dueño")

    def test_un_alta_equivocada_si_se_borra(self):
        conn, ws, puerto = self._monta(recibos=())
        estado, cuerpo, _ = self._post(puerto, "/api/workspace_fincas_vecino_delete",
                                       {"workspace_id": ws, "id": "v1"}, self._entra(puerto))
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM workspace_fincas_vecinos").fetchone()[0], 0)

    def test_con_deuda_no_se_suprime(self):
        _, ws, puerto = self._monta(recibos=("Pendiente",))
        estado, cuerpo, _ = self._post(puerto, "/api/workspace_fincas_vecino_suprimir",
                                       {"workspace_id": ws, "vecino_id": "v1", "confirm": "SUPRIMIR"},
                                       self._entra(puerto))
        self.assertEqual(estado, 409, cuerpo)
        self.assertEqual(cuerpo.get("recibos_pendientes"), 1)

    def test_al_corriente_se_le_quita_la_identidad_y_se_queda_el_piso(self):
        conn, ws, puerto = self._monta(recibos=("Cobrado", "Cobrado"))
        estado, cuerpo, _ = self._post(puerto, "/api/workspace_fincas_vecino_suprimir",
                                       {"workspace_id": ws, "vecino_id": "v1", "confirm": "SUPRIMIR",
                                        "motivo": "art.17"}, self._entra(puerto))
        self.assertEqual(estado, 200, cuerpo)
        f = dict(conn.execute("SELECT nombre, nif, telefono, email, iban, mandato_ref, piso, "
                              "coeficiente FROM workspace_fincas_vecinos WHERE id='v1'").fetchone())
        self.assertIn("suprimido", f["nombre"].lower())
        self.assertFalse(any([f["nif"], f["telefono"], f["email"], f["iban"], f["mandato_ref"]]), f)
        # El piso y su coeficiente son de la finca, no de la persona: se quedan.
        self.assertEqual(f["piso"], "2 B")
        self.assertEqual(float(f["coeficiente"]), 20.0)
        # La contabilidad no se toca y el acceso al portal se va.
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM workspace_fincas_recibos "
                                      "WHERE vecino_id='v1'").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM workspace_fincas_portal_accesos "
                                      "WHERE vecino_id='v1'").fetchone()[0], 0)
        self.assertIn("workspace_fincas_recibos", cuerpo.get("conservado") or {})

    def test_queda_constancia_de_quien_y_cuando(self):
        conn, ws, puerto = self._monta(recibos=("Cobrado",))
        self._post(puerto, "/api/workspace_fincas_vecino_suprimir",
                   {"workspace_id": ws, "vecino_id": "v1", "confirm": "SUPRIMIR",
                    "empresa_id": "emp1", "motivo": "art.17"}, self._entra(puerto))
        filas = conn.execute("SELECT entidad, entidad_id, usuario FROM auditoria "
                             "WHERE accion = 'supresion_rgpd'").fetchall()
        self.assertEqual([dict(f) for f in filas],
                         [{"entidad": "workspace_fincas_vecino", "entidad_id": "v1", "usuario": "ana"}])

    def test_no_lo_hace_un_trabajador_cualquiera(self):
        _, ws, puerto = self._monta(recibos=("Cobrado",))
        estado, cuerpo, _ = self._post(puerto, "/api/workspace_fincas_vecino_suprimir",
                                       {"workspace_id": ws, "vecino_id": "v1", "confirm": "SUPRIMIR"},
                                       self._entra(puerto, "raso"))
        self.assertEqual(estado, 403, cuerpo)


class LaPantallaDelComuneroTests(unittest.TestCase):
    def test_hay_boton_en_el_censo(self):
        self.assertIn("data-vecino-suprimir=", APP)

    def test_no_basta_con_aceptar_un_aviso(self):
        i = APP.index("data-vecino-suprimir]")
        self.assertIn('!== "SUPRIMIR"', APP[i: i + 2500])

    def test_el_aviso_dice_lo_que_se_conserva(self):
        i = APP.index("data-vecino-suprimir]")
        bloque = APP[i: i + 2500]
        self.assertIn("Se conservan recibos, apuntes y actas", bloque)
