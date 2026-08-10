"""Borrar un inmueble tiene que llevarse su expediente entero.

Encontrado probando en producción. Borré una ficha de pruebas por el propio endpoint
—`/api/inmueble_delete`, que respondió 200 y dejó la ficha en 404— y al comprobar la
base seguían ahí su captación, sus tres citas, su documento, su propietario y sus
cuatro líneas de checklist. Diez filas colgando de un inmueble que ya no existe.

El handler SÍ borra en cascada, y sin `try/except` que se lo trague. La causa está un
piso más abajo: **el adaptador de Postgres hace `rollback()` de toda la transacción
cuando una sentencia falla**, y luego relanza. Al final del borrado hay tres
actualizaciones «por si acaso» envueltas en `try/except: pass`, y una de ellas apunta
a `gestoria_contabilidad`, que **no tiene columna `inmueble_id`**. Falla, el
adaptador deshace los doce borrados anteriores, el `except` se traga el error, y el
`DELETE FROM inmuebles` se ejecuta ya en una transacción nueva y se commitea solo.

Respuesta 200, ficha borrada, expediente desperdigado. Y sin rastro en el log.

El arreglo no es poner otro `try`: es mirar el esquema antes de escribir, que no
lanza nunca. De ahí `desvincula_si_la_columna_existe`.

Este fichero fija las dos cosas: que la cascada se lleva todo, y que una tabla sin
esa columna no puede volver a tumbarla.
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
CLAVE = "Cascada1234!"

# Lo que cuelga de un inmueble y debe desaparecer con él.
DEPENDENCIAS = (
    ("captaciones", "inmueble_id"),
    ("acciones", "inmueble_id"),
    ("inmueble_docs", "inmueble_id"),
    ("inmueble_propietarios", "inmueble_id"),
    ("inmueble_checklist", "inmueble_id"),
    ("inmueble_compradores", "inmueble_id"),
    ("visitas", "inmueble_id"),
)


class BorradoEnCascadaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "cascada.sqlite"
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
            data=json.dumps({"usuario": "cascada", "password": CLAVE}).encode(),
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
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "we1", "workspace_id": self.ws, "empresa_id": "emp1",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("usuarios", {"id": "u1", "nombre": "Casc", "usuario": "cascada",
                               "email": "c@x.test", "rol": "Administrador",
                               "servicio": "Inmobiliaria", "activo": 1,
                               "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self._ins("clientes", {"id": "cli1", "empresa_id": "emp1", "workspace_id": self.ws,
                               "nombre": "Propietario", "nif": "11111111H",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inm1", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Cascada 1", "estado": "Encargo",
                                "tipo_inmueble": "Piso", "created_at": AHORA, "updated_at": AHORA})
        self._ins("captaciones", {"id": "cap1", "workspace_id": self.ws, "empresa_id": "emp1",
                                  "inmueble_id": "inm1", "direccion": "Calle Cascada 1",
                                  "etapa": "Encargo", "created_at": AHORA, "updated_at": AHORA})
        for i in range(3):
            self._ins("acciones", {"id": f"acc{i}", "workspace_id": self.ws, "empresa_id": "emp1",
                                   "inmueble_id": "inm1", "servicio": "inmobiliaria",
                                   "fecha": "2026-08-20", "hora": f"1{i}:00", "asunto": "Visita",
                                   "tipo": "Visita", "estado": "Pendiente",
                                   "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_docs", {"id": "doc1", "inmueble_id": "inm1", "empresa_id": "emp1",
                                    "nombre": "encargo.pdf", "url": "/uploads/x.pdf",
                                    "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_propietarios", {"id": "ip1", "inmueble_id": "inm1", "cliente_id": "cli1",
                                            "empresa_id": "emp1", "created_at": AHORA, "updated_at": AHORA})
        for i in range(4):
            self._ins("inmueble_checklist", {"id": f"chk{i}", "inmueble_id": "inm1",
                                             "empresa_id": "emp1", "etapa": "Captacion",
                                             "estado": "Pendiente", "created_at": AHORA,
                                             "updated_at": AHORA})
        self._ins("visitas", {"id": "vis1", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "fecha": "2026-08-21", "estado": "Prevista",
                              "created_at": AHORA, "updated_at": AHORA})
        self._ins("demandas", {"id": "dem1", "workspace_id": self.ws, "empresa_id": "emp1",
                               "cliente_id": "cli1", "tipo": "Piso", "estado": "Activa",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_compradores", {"id": "ic1", "empresa_id": "emp1", "inmueble_id": "inm1",
                                           "demanda_id": "dem1", "cliente_id": "cli1",
                                           "estado": "Pendiente", "created_at": AHORA,
                                           "updated_at": AHORA})

    def _cuenta(self, tabla, columna):
        return self.conn.execute(
            f"SELECT COUNT(*) c FROM {tabla} WHERE {columna} = 'inm1'").fetchone()["c"]

    def _borra(self):
        req = urllib.request.Request(
            self.base + "/api/inmueble_delete",
            data=json.dumps({"id": "inm1", "inmueble_id": "inm1", "workspace_id": self.ws}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_el_expediente_esta_completo_antes_de_borrar(self):
        """Si la siembra fallara, el test de abajo pasaría sin probar nada."""
        for tabla, columna in DEPENDENCIAS:
            with self.subTest(tabla):
                self.assertGreater(self._cuenta(tabla, columna), 0)

    def test_borrar_el_inmueble_se_lleva_todo(self):
        estado, cuerpo = self._borra()
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM inmuebles WHERE id='inm1'").fetchone()["c"], 0)
        for tabla, columna in DEPENDENCIAS:
            with self.subTest(tabla):
                self.assertEqual(self._cuenta(tabla, columna), 0,
                                 f"{tabla} se ha quedado colgando de un inmueble que ya no existe")

    def test_una_tabla_sin_esa_columna_no_tumba_el_borrado(self):
        """El caso exacto de producción: `gestoria_contabilidad` sin `inmueble_id`."""
        self.conn.execute("DROP TABLE IF EXISTS gestoria_contabilidad")
        self.conn.execute("CREATE TABLE gestoria_contabilidad (id TEXT PRIMARY KEY, concepto TEXT)")
        self.conn.commit()
        estado, cuerpo = self._borra()
        self.assertEqual(estado, 200, cuerpo)
        for tabla, columna in DEPENDENCIAS:
            with self.subTest(tabla):
                self.assertEqual(self._cuenta(tabla, columna), 0)

    # ---------- el helper ----------

    def test_el_helper_no_lanza_si_la_columna_no_existe(self):
        self.conn.execute("DROP TABLE IF EXISTS tabla_de_prueba")
        self.conn.execute("CREATE TABLE tabla_de_prueba (id TEXT PRIMARY KEY)")
        self.conn.commit()
        self.assertFalse(
            S.desvincula_si_la_columna_existe(self.conn, "tabla_de_prueba", "inmueble_id", "inm1"))

    def test_el_helper_no_lanza_si_la_tabla_no_existe(self):
        self.assertFalse(
            S.desvincula_si_la_columna_existe(self.conn, "tabla_que_no_existe", "inmueble_id", "x"))

    def test_el_helper_desvincula_cuando_puede(self):
        self._ins("operaciones_inmobiliarias", {
            "id": "op1", "workspace_id": self.ws, "empresa_id": "emp1", "inmueble_id": "inm1",
            "direccion": "Calle Cascada 1", "tipo_operacion": "compraventa",
            "created_at": AHORA, "updated_at": AHORA})
        self.assertTrue(S.desvincula_si_la_columna_existe(
            self.conn, "operaciones_inmobiliarias", "inmueble_id", "inm1", ahora=AHORA))
        self.conn.commit()
        fila = self.conn.execute(
            "SELECT inmueble_id FROM operaciones_inmobiliarias WHERE id='op1'").fetchone()
        self.assertIsNone(fila["inmueble_id"])

    def test_la_operacion_sobrevive_al_borrado_del_inmueble(self):
        """La venta no se borra: se queda sin ficha, pero el dinero sigue contando."""
        self._ins("operaciones_inmobiliarias", {
            "id": "op1", "workspace_id": self.ws, "empresa_id": "emp1", "inmueble_id": "inm1",
            "direccion": "Calle Cascada 1", "precio_escritura": 200000,
            "tipo_operacion": "compraventa", "created_at": AHORA, "updated_at": AHORA})
        self._borra()
        fila = self.conn.execute(
            "SELECT inmueble_id, precio_escritura FROM operaciones_inmobiliarias WHERE id='op1'").fetchone()
        self.assertIsNotNone(fila, "la operación no debe borrarse con el inmueble")
        self.assertIsNone(fila["inmueble_id"])


if __name__ == "__main__":
    unittest.main()
