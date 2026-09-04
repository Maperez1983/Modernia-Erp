"""La base de clientes enseñaba 120 de 2.262 y no había forma de saberlo.

Salió al sembrar la base con los clientes que tiene producción —2.262— y abrir la
pantalla. La lista de clientes del workspace pide 120 al servidor y pinta 120. Con una
gestoría pequeña eso ES la lista completa; con la de verdad son los 120 primeros por
orden alfabético y **nada en la pantalla lo distingue**. El pie decía «CRM 360
cargado.» y la lista, nada.

No es que no se pueda llegar a los demás: el buscador de arriba manda la búsqueda al
servidor y encuentra al último del abecedario sin problema —comprobado—. El fallo es
que hay que saber que hay más para buscarlos. Quien no lo sabe da la lista por completa.

Es la clase de fallo que sólo aparece con datos de verdad: con tres clientes de prueba
la pantalla es correcta.

El arreglo tiene dos mitades:

  · El servidor dice cuántos hay. Sólo cuenta cuando la lista viene llena —si devuelve
    menos filas que el tope, el total ya lo sabe— para no pagar un COUNT en cada
    tecleo.
  · La lista lo dice: «120 de 2.262 clientes · busca … para llegar al resto».

Y el recuento va guardado en `state`, no pasado por parámetro: hay **seis sitios** que
repintan esa lista y cinco de ellos no tienen el total a mano. Pasarlo por parámetro
funcionaba al cargar y se perdía en cuanto abrías una ficha, que es exactamente lo que
pasó la primera vez.
"""

import os
import re
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def base_con(cuantos_clientes, caso):
    """Un workspace, una empresa y N clientes.

    En fichero y no en `:memory:`: `ensure_tables` abre su propia conexión, y dos
    conexiones a `:memory:` son dos bases distintas — el esquema se crearía en una y
    los clientes se insertarían en la otra.
    """
    tmp = tempfile.mkdtemp()
    caso.addCleanup(shutil.rmtree, tmp, True)
    ruta = Path(tmp) / "volumen.sqlite"
    conn = S.get_db(ruta)
    S.ensure_tables(str(ruta))
    for crear in (S.ensure_workspace_core_tables, S.ensure_workspace_product_tables):
        crear(conn)
    ahora = "2026-08-25T10:00:00"
    conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) "
                 "VALUES ('e1', 'Volumen S.L.', 1, ?, ?)", (ahora, ahora))
    conn.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) "
                 "VALUES ('w1', 'Volumen', 'volumen', ?, ?)", (ahora, ahora))
    conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, "
                 "updated_at) VALUES ('we1', 'w1', 'e1', ?, ?)", (ahora, ahora))
    for i in range(cuantos_clientes):
        cid = uuid.uuid4().hex
        # Repartidos por el abecedario: si fueran todos «A», el corte por orden
        # alfabético no se notaría.
        conn.execute("INSERT INTO clientes (id, nombre, nif, workspace_id, empresa_id, "
                     "created_at, updated_at) VALUES (?, ?, ?, 'w1', 'e1', ?, ?)",
                     (cid, f"{chr(65 + i % 26)}{i:05d} Cliente", f"{10000000 + i}Z",
                      ahora, ahora))
        conn.execute("INSERT INTO clientes_empresas (id, cliente_id, empresa_id, "
                     "workspace_id, servicio, created_at, updated_at) "
                     "VALUES (?, ?, 'e1', 'w1', 'gestoria', ?, ?)",
                     (uuid.uuid4().hex, cid, ahora, ahora))
    conn.commit()
    return conn


class ElServidorDiceCuantosHayTests(unittest.TestCase):
    def test_una_lista_llena_trae_el_total_de_verdad(self):
        conn = base_con(300, self)
        self.addCleanup(conn.close)
        r = S.fetch_workspace_clientes(conn, "w1", limit=120)
        self.assertEqual(len(r["rows"]), 120)
        self.assertEqual(r["total"], 300)
        self.assertEqual(r["limite"], 120)

    def test_y_si_caben_todos_el_total_son_ellos(self):
        conn = base_con(17, self)
        self.addCleanup(conn.close)
        r = S.fetch_workspace_clientes(conn, "w1", limit=120)
        self.assertEqual(len(r["rows"]), 17)
        self.assertEqual(r["total"], 17)

    def test_justo_en_el_tope_no_miente(self):
        """120 de 120 no puede decir «120 de 2.262», ni al revés."""
        conn = base_con(120, self)
        self.addCleanup(conn.close)
        r = S.fetch_workspace_clientes(conn, "w1", limit=120)
        self.assertEqual(len(r["rows"]), 120)
        self.assertEqual(r["total"], 120)

    def test_buscando_el_total_es_el_de_las_coincidencias(self):
        """No el de la base entera: si no, «4 de 2.262» al buscar sería mentira."""
        conn = base_con(300, self)
        self.addCleanup(conn.close)
        r = S.fetch_workspace_clientes(conn, "w1", q="A00000", limit=120)
        self.assertLess(len(r["rows"]), 120)
        self.assertEqual(r["total"], len(r["rows"]))

    def test_el_buscador_llega_más_allá_del_corte(self):
        """Es lo que hace que el corte sea tolerable: si esto falla, el corte es un muro."""
        conn = base_con(300, self)
        self.addCleanup(conn.close)
        ultimo = conn.execute(
            "SELECT nombre FROM clientes ORDER BY nombre DESC LIMIT 1").fetchone()[0]
        cortada = S.fetch_workspace_clientes(conn, "w1", limit=120)
        self.assertNotIn(ultimo, [f["nombre"] for f in cortada["rows"]])
        buscado = S.fetch_workspace_clientes(conn, "w1", q=ultimo, limit=120)
        self.assertEqual([f["nombre"] for f in buscado["rows"]], [ultimo])

    def test_un_workspace_sin_empresas_no_revienta(self):
        conn = base_con(3, self)
        self.addCleanup(conn.close)
        r = S.fetch_workspace_clientes(conn, "w-que-no-existe", limit=120)
        self.assertEqual(r["rows"], [])


class LaPantallaLoDiceTests(unittest.TestCase):
    """El servidor puede contar bien y la pantalla seguir callándose."""

    def test_la_lista_pinta_el_recuento(self):
        self.assertIn("workspace-client-count", APP)
        i = APP.index("const renderWorkspaceClientBase")
        cuerpo = APP[i:i + 2200]
        self.assertIn("de ${Number(total).toLocaleString(\"es-ES\")} clientes", cuerpo)
        self.assertIn("para llegar al resto", cuerpo)

    def test_y_dice_el_número_llano_cuando_están_todos(self):
        i = APP.index("const renderWorkspaceClientBase")
        cuerpo = APP[i:i + 2200]
        self.assertIn("items.length === 1", cuerpo)

    def test_el_total_vive_en_state_y_no_en_un_parámetro(self):
        """Seis sitios repintan la lista; cinco no tendrían el total a mano.

        Pasarlo por parámetro funcionaba al cargar y se perdía al abrir una ficha:
        `openWorkspaceClient360` repinta con `state.currentWorkspaceClients` y nada más.
        """
        i = APP.index("const renderWorkspaceClientBase")
        firma = APP[i:i + 120]
        self.assertIn("(rows = [])", firma)
        cuerpo = APP[i:i + 600]
        self.assertIn("state.currentWorkspaceClientsTotal", cuerpo)
        self.assertGreaterEqual(len(re.findall(r"renderWorkspaceClientBase\(", APP)), 5)

    def test_y_lo_rellenan_las_dos_cargas(self):
        """La del arranque del workspace (60) y la del buscador (120)."""
        self.assertEqual(len(re.findall(r"state\.currentWorkspaceClientsTotal\s*=", APP)), 2)

    def test_una_búsqueda_sin_resultados_no_se_queda_muda(self):
        i = APP.index("const renderWorkspaceClientBase")
        cuerpo = APP[i:i + 900]
        self.assertIn("Ningún cliente coincide con", cuerpo)

    def test_el_estilo_del_recuento_existe(self):
        css = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".workspace-client-count", css)


if __name__ == "__main__":
    unittest.main()
