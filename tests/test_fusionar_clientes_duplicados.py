"""Fusionar dos fichas del mismo cliente sin perder lo que colgaba de ninguna.

Los duplicados los dejó `alta_titulares_como_clientes.py`: cargaba el índice de clientes
una vez antes de decidir y no lo actualizaba al crear, así que diez pólizas del mismo
tomador salían con diez fichas. Dos tandas, el 2026-04-21 y el 2026-08-04. Aquello ya
está arreglado; esto limpia lo que dejó.

Lo que hay que proteger, por orden de gravedad:

  · **Que no se mezclen dos personas.** Dos NIF distintos son dos personas mientras
    nadie diga lo contrario. Un grupo así se deja como está, no se elige.
  · **Que no se pierda nada.** Cada póliza, hipoteca o expediente que colgaba de la
    ficha retirada tiene que acabar en la que se queda. Y las columnas se buscan en el
    esquema, no se dan por sabidas: darlas por sabidas es cómo se deja una póliza
    colgando de un id que ya no existe.
  · **Que no se pise un dato bueno.** Lo que sólo tenía la retirada se hereda; lo que
    ya tiene la que se queda, no se toca.
  · **Que no se junten dos comunidades.** La clave conserva los números: «Sierra
    Bermeja 5» y «Sierra Bermeja 7» son dos edificios.
"""

import importlib.util
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GUION = RAIZ / "scripts" / "fusiona_clientes_duplicados.py"


def modulo():
    spec = importlib.util.spec_from_file_location("fusiona", GUION)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class LaClaveDeAgrupacionTests(unittest.TestCase):
    def setUp(self):
        self.m = modulo()

    def test_el_orden_de_nombre_y_apellido_no_importa(self):
        self.assertEqual(self.m.clave_de_nombre("HUANG XIAOLING"),
                         self.m.clave_de_nombre("XIAOLING HUANG"))

    def test_ni_las_tildes_ni_las_comas(self):
        self.assertEqual(self.m.clave_de_nombre("Fernández Torres, Carmen"),
                         self.m.clave_de_nombre("FERNANDEZ TORRES CARMEN"))

    def test_pero_el_número_del_portal_sí(self):
        """Dos comunidades vecinas no son la misma."""
        self.assertNotEqual(self.m.clave_de_nombre("Sierra Bermeja 5"),
                            self.m.clave_de_nombre("Sierra Bermeja 7"))

    def test_un_nie_con_prefijo_es_el_mismo_documento(self):
        self.assertEqual(self.m.documento("NIEESX9702310J"), self.m.documento("X9702310J"))

    def test_y_dos_documentos_distintos_lo_siguen_siendo(self):
        self.assertNotEqual(self.m.documento("79380332H"), self.m.documento("B72661374"))


class FusionarDeVerdadTests(unittest.TestCase):
    def _base(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ruta = str(Path(tmp) / "fusion.sqlite")
        c = sqlite3.connect(ruta)
        c.row_factory = sqlite3.Row
        c.executescript(
            """
            CREATE TABLE clientes (id TEXT PRIMARY KEY, nombre TEXT, nif TEXT, telefono TEXT,
              email TEXT, direccion TEXT, tipo TEXT, tipo_persona TEXT, movil TEXT,
              codigo_postal TEXT, localidad TEXT, poblacion TEXT, provincia TEXT,
              fecha_nacimiento TEXT, empresa_id TEXT, estado TEXT, workspace_id TEXT,
              created_at TEXT, updated_at TEXT);
            CREATE TABLE clientes_empresas (id TEXT PRIMARY KEY, cliente_id TEXT,
              empresa_id TEXT, servicio TEXT, created_at TEXT);
            CREATE TABLE seguros (id TEXT PRIMARY KEY, cliente_id TEXT, tomador TEXT);
            CREATE TABLE cliente_gestoria (id TEXT PRIMARY KEY, cliente_id TEXT);
            CREATE TABLE gestoria_modelos (id TEXT PRIMARY KEY, cliente_id TEXT);
            CREATE TABLE hipotecas (id TEXT PRIMARY KEY, cliente_id TEXT);
            CREATE TABLE gestoria_contabilidad (id TEXT PRIMARY KEY, cliente_id TEXT,
              cliente_ids_json TEXT);
            """
        )

        def cli(cid, nombre, nif="", tel="", creado="2026-01-01"):
            c.execute("INSERT INTO clientes (id, nombre, nif, telefono, workspace_id, "
                      "estado, created_at, updated_at) VALUES (?,?,?,?,'w1','Activo',?,?)",
                      (cid, nombre, nif, tel, creado, creado))

        # el caso real: la buena con NIF (marzo) y la vacía de la importación (agosto)
        cli("bueno", "MARTIN ARAGON ANDRES", "24688799R", creado="2026-03-24")
        cli("vacio", "MARTIN ARAGON ANDRES", creado="2026-08-04")
        c.execute("INSERT INTO clientes_empresas VALUES ('ce1','bueno','e1','gestoria','2026-03-24')")
        c.execute("INSERT INTO clientes_empresas VALUES ('ce2','vacio','e1','gestoria','2026-08-04')")
        c.execute("INSERT INTO seguros VALUES ('s1','vacio','MARTIN ARAGON ANDRES')")
        c.execute("INSERT INTO cliente_gestoria VALUES ('g1','vacio')")
        c.execute("INSERT INTO gestoria_modelos VALUES ('m1','vacio')")
        # una columna que guarda una LISTA de ids, no un id pelado
        c.execute("INSERT INTO gestoria_contabilidad VALUES ('k1','','[\"vacio\"]')")

        # el que hereda: la que se queda no tiene teléfono y la que se va sí
        cli("padre", "ANA PORTERO", "11111111H", creado="2026-03-24")
        cli("hijo", "ANA PORTERO", tel="600111222", creado="2026-08-04")

        # dos personas distintas: NO se tocan
        cli("uno", "LOPEZ CONDE JOSE", "52536791F", creado="2026-01-26")
        cli("otro", "LOPEZ CONDE JOSE", "04316701S", creado="2026-06-07")

        # dos comunidades vecinas: NO son el mismo
        cli("b5", "COM PROP SIERRA BERMEJA 5", "H92134386")
        cli("b7", "Com. Prop. Sierra Bermeja 7", "H92145242")
        c.commit()
        return ruta, c

    def _corre(self, ruta, aplicar=True):
        args = ["--db", ruta, "--backend", "sqlite", "--workspace-id", "w1"]
        if aplicar:
            args += ["--apply", "--yes"]
        return modulo().main(args)

    def test_en_seco_no_escribe_nada(self):
        ruta, c = self._base()
        self.assertEqual(self._corre(ruta, aplicar=False), 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 8)

    def test_se_queda_la_que_tiene_documento(self):
        ruta, c = self._base()
        self._corre(ruta)
        q = c.execute("SELECT id, nif FROM clientes WHERE nombre='MARTIN ARAGON ANDRES'").fetchall()
        self.assertEqual([(x["id"], x["nif"]) for x in q], [("bueno", "24688799R")])

    def test_y_se_lleva_todo_lo_que_colgaba_de_la_otra(self):
        """Una póliza colgando de un id que ya no existe es peor que el duplicado."""
        ruta, c = self._base()
        self._corre(ruta)
        for tabla in ("seguros", "cliente_gestoria", "gestoria_modelos"):
            fila = c.execute(f"SELECT cliente_id FROM {tabla}").fetchone()
            self.assertEqual(fila["cliente_id"], "bueno", tabla)

    def test_no_queda_ninguna_referencia_a_una_ficha_borrada(self):
        ruta, c = self._base()
        self._corre(ruta)
        vivos = {x["id"] for x in c.execute("SELECT id FROM clientes").fetchall()}
        for tabla in ("seguros", "cliente_gestoria", "gestoria_modelos", "clientes_empresas"):
            for x in c.execute(f"SELECT cliente_id FROM {tabla}").fetchall():
                self.assertIn(x["cliente_id"], vivos, tabla)

    def test_hereda_lo_que_le_falta_a_la_que_se_queda(self):
        ruta, c = self._base()
        self._corre(ruta)
        f = c.execute("SELECT nif, telefono FROM clientes WHERE id='padre'").fetchone()
        self.assertEqual(f["telefono"], "600111222")
        self.assertEqual(f["nif"], "11111111H", "y no pisa lo que ya tenía")

    def test_dos_documentos_distintos_no_se_fusionan(self):
        """Mezclar a dos personas no se deshace mirando la base."""
        ruta, c = self._base()
        self._corre(ruta)
        n = c.execute("SELECT COUNT(*) FROM clientes WHERE nombre='LOPEZ CONDE JOSE'").fetchone()[0]
        self.assertEqual(n, 2)

    def test_dos_comunidades_vecinas_tampoco(self):
        ruta, c = self._base()
        self._corre(ruta)
        n = c.execute("SELECT COUNT(*) FROM clientes WHERE id IN ('b5','b7')").fetchone()[0]
        self.assertEqual(n, 2)

    def test_el_vínculo_repetido_con_la_misma_empresa_se_va(self):
        ruta, c = self._base()
        self._corre(ruta)
        n = c.execute("SELECT COUNT(*) FROM clientes_empresas WHERE cliente_id='bueno'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_queda_respaldo_de_lo_retirado(self):
        ruta, c = self._base()
        self._corre(ruta)
        filas = c.execute("SELECT se_queda, se_fue, ficha_json, referencias_json "
                          "FROM clientes_fusion_backup ORDER BY se_fue").fetchall()
        self.assertEqual(len(filas), 2)
        porid = {x["se_fue"]: x for x in filas}
        self.assertIn("MARTIN ARAGON ANDRES", porid["vacio"]["ficha_json"])
        self.assertIn("seguros.cliente_id", porid["vacio"]["referencias_json"])

    def test_una_columna_con_lista_de_ids_tambien_se_actualiza(self):
        """`cliente_ids_json` guarda `["abc…"]`, no el id pelado: un UPDATE de igualdad
        no la toca y deja el apunte nombrando a una ficha que ya no existe. Pasó en
        producción con tres apuntes de contabilidad."""
        ruta, c = self._base()
        self._corre(ruta)
        v = c.execute("SELECT cliente_ids_json FROM gestoria_contabilidad WHERE id='k1'").fetchone()[0]
        self.assertEqual(v, '["bueno"]')

    def test_y_sigue_siendo_json_valido(self):
        import json
        ruta, c = self._base()
        self._corre(ruta)
        v = c.execute("SELECT cliente_ids_json FROM gestoria_contabilidad WHERE id='k1'").fetchone()[0]
        self.assertEqual(json.loads(v), ["bueno"])

    def test_repetirlo_no_hace_nada(self):
        ruta, c = self._base()
        self._corre(ruta)
        antes = c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
        self._corre(ruta)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], antes)


if __name__ == "__main__":
    unittest.main()
