"""El alta de titulares vale para hipotecas y para seguros.

Cada CRM guarda el nombre del titular en una columna distinta —`cliente` en
hipotecas, `tomador` en seguros— pero el resto del procedimiento es idéntico:
buscar una ficha existente por nombre normalizado, no elegir si hay varias
candidatas, y crear solo cuando no hay ninguna. Copiar el guion habría dejado dos
versiones que se separan con el primer arreglo que se haga en una sola.

Lo que este test protege de verdad es el `--rollback`: la tabla de respaldo es
compartida, así que cada anotación guarda de qué tabla salió. Sin eso, deshacer un
alta de seguros habría vaciado el `cliente_id` de una hipoteca con el mismo id.
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GUION = (RAIZ / "scripts" / "alta_titulares_como_clientes.py").read_text(encoding="utf-8")


class LosModulosEstanDeclaradosTests(unittest.TestCase):
    def test_hay_configuracion_para_los_dos_crm(self):
        self.assertIn('"hipotecas": {', GUION)
        self.assertIn('"seguros": {', GUION)

    def test_cada_uno_dice_su_columna_de_titular(self):
        self.assertIn('"columna_nombre": "cliente"', GUION)
        self.assertIn('"columna_nombre": "tomador"', GUION)

    def test_cada_uno_dice_su_servicio(self):
        self.assertIn('"servicio": "financiaciones"', GUION)
        self.assertIn('"servicio": "seguros"', GUION)

    def test_el_vinculo_usa_el_servicio_del_modulo(self):
        """Un titular de seguros no puede quedar vinculado como financiaciones."""
        self.assertIn('cfg["servicio"]', GUION)
        self.assertNotIn("SERVICIO,", GUION)


class ElRollbackSabeDondeDeshacerTests(unittest.TestCase):
    def test_el_respaldo_guarda_la_tabla_de_origen(self):
        self.assertIn("tabla_origen", GUION)
        self.assertIn("ADD COLUMN tabla_origen TEXT", GUION)

    def test_las_anotaciones_viejas_se_dan_por_de_hipotecas(self):
        """Las 45 que ya existían son todas de hipotecas."""
        self.assertIn("SET tabla_origen = 'hipotecas'", GUION)

    def test_no_deshace_sobre_una_tabla_fija(self):
        i = GUION.index("if args.rollback:")
        bloque = GUION[i: i + 1200]
        self.assertNotIn('"UPDATE hipotecas SET cliente_id', bloque)
        self.assertIn("f\"UPDATE {origen} SET cliente_id", bloque)

    def test_no_deshace_sobre_una_tabla_desconocida(self):
        """`tabla_origen` sale de la base: no puede entrar tal cual en un SQL."""
        i = GUION.index("if args.rollback:")
        self.assertIn('if origen not in {cfg["tabla"] for cfg in MODULOS.values()}', GUION[i: i + 1200])


class NoEligeCuandoHayDudaTests(unittest.TestCase):
    def test_las_ambiguas_se_dejan_como_estan(self):
        """Unir a dos personas distintas no se deshace solo, así que no se elige.

        Con más de una ficha candidata la hipoteca o la póliza se queda sin enlazar y
        se informa: en seguros salieron 3, una de ellas el propio usuario con dos
        fichas a su nombre.
        """
        self.assertIn("elif len(candidatos) > 1:", GUION)
        self.assertIn("ambiguas.append((fila, candidatos))", GUION)
        # Y solo se enlaza cuando la candidata es única.
        self.assertIn("if len(candidatos) == 1:", GUION)


if __name__ == "__main__":
    unittest.main()


class UnaFichaPorTitularNoUnaPorExpedienteTests(unittest.TestCase):
    """Diez pólizas del mismo tomador tienen que dejar UNA ficha, no diez.

    Esto no es hipotético: el 2026-08-04 esta pasada dejó **49 fichas de más** en
    producción —GARCISA MASAE diez veces, JUAN RAMOS ocho, JOSE LUIS TORRES seis—,
    cada una con exactamente una póliza colgando. El índice de clientes se carga una
    vez, antes de decidir, y el bucle que crea no lo actualizaba: las diez filas
    consultaban el mismo índice vacío y las diez concluían «no existe ficha».

    Las pruebas de arriba miran el código; ésta ejecuta el guion, que es lo único que
    habría cazado esto.
    """

    TOMADORES = ["GARCISA MASAE"] * 10 + ["JUAN RAMOS"] * 3 + ["ANA PORTERO"]

    def _base(self):
        import shutil
        import sqlite3
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ruta = str(Path(tmp) / "alta.sqlite")
        c = sqlite3.connect(ruta)
        c.row_factory = sqlite3.Row
        c.executescript(
            """
            CREATE TABLE clientes (id TEXT PRIMARY KEY, empresa_id TEXT, nombre TEXT,
              estado TEXT, workspace_id TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE clientes_empresas (id TEXT PRIMARY KEY, cliente_id TEXT,
              empresa_id TEXT, servicio TEXT, estado TEXT, workspace_id TEXT,
              created_at TEXT, updated_at TEXT);
            CREATE TABLE seguros (id TEXT PRIMARY KEY, tomador TEXT, cliente_id TEXT,
              empresa_id TEXT, estado TEXT, fecha_efecto TEXT, workspace_id TEXT,
              updated_at TEXT);
            CREATE TABLE workspace_empresas (id TEXT, workspace_id TEXT, empresa_id TEXT);
            INSERT INTO workspace_empresas VALUES ('we1','w1','e1');
            """
        )
        for i, nombre in enumerate(self.TOMADORES):
            c.execute("INSERT INTO seguros (id, tomador, cliente_id, empresa_id, estado, "
                      "fecha_efecto, workspace_id) VALUES (?,?,'','e1','firmada',?,'w1')",
                      (f"s{i}", nombre, f"2026-01-{i + 1:02d}"))
        c.commit()
        return ruta, c

    def _corre(self, ruta):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "alta", RAIZ / "scripts" / "alta_titulares_como_clientes.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.main(["--db", ruta, "--backend", "sqlite",
                         "--workspace-id", "w1", "--modulo", "seguros",
                         "--apply", "--yes"])

    def test_catorce_polizas_de_tres_personas_dejan_tres_fichas(self):
        ruta, c = self._base()
        self.assertEqual(self._corre(ruta), 0)
        fichas = c.execute("SELECT nombre, COUNT(*) AS n FROM clientes "
                           "GROUP BY nombre ORDER BY nombre").fetchall()
        self.assertEqual([(f["nombre"], f["n"]) for f in fichas],
                         [("ANA PORTERO", 1), ("GARCISA MASAE", 1), ("JUAN RAMOS", 1)])

    def test_y_todas_las_pólizas_quedan_enlazadas(self):
        """Crear una sola ficha no puede dejar trece pólizas sin cliente."""
        ruta, c = self._base()
        self._corre(ruta)
        sueltas = c.execute("SELECT COUNT(*) AS n FROM seguros "
                            "WHERE COALESCE(cliente_id,'') = ''").fetchone()["n"]
        self.assertEqual(sueltas, 0)
        garcisa = c.execute("""SELECT COUNT(*) AS n FROM seguros s
            JOIN clientes c ON c.id = s.cliente_id WHERE c.nombre = 'GARCISA MASAE'""").fetchone()
        self.assertEqual(garcisa["n"], 10, "las diez pólizas cuelgan de la misma ficha")

    def test_y_un_solo_vínculo_con_la_empresa_por_ficha(self):
        ruta, c = self._base()
        self._corre(ruta)
        v = c.execute("SELECT COUNT(*) AS n FROM clientes_empresas").fetchone()["n"]
        self.assertEqual(v, 3)

    def test_repetirlo_no_crea_nada(self):
        """Idempotente: la segunda pasada ya no encuentra pólizas sin ficha."""
        ruta, c = self._base()
        self._corre(ruta)
        self._corre(ruta)
        self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM clientes").fetchone()["n"], 3)

    def test_el_respaldo_distingue_creadas_de_enlazadas(self):
        """El rollback tiene que borrar una ficha y sólo desenlazar las otras nueve."""
        ruta, c = self._base()
        self._corre(ruta)
        r = c.execute("SELECT cliente_creado, COUNT(*) AS n FROM hipotecas_titulares_alta_backup "
                      "GROUP BY cliente_creado ORDER BY cliente_creado").fetchall()
        self.assertEqual([(x["cliente_creado"], x["n"]) for x in r], [(0, 11), (1, 3)])


class ElNumeroDelPortalNoSeTiraTests(unittest.TestCase):
    """«Sierra Bermeja 5» y «Sierra Bermeja 7» no son la misma comunidad.

    La clave de comparación quitaba los números junto con los signos. En una
    administración de fincas eso es justo lo que no se puede hacer: las comunidades se
    llaman calle y número. Y el guion **enlaza sin preguntar cuando hay una sola
    candidata**, así que la póliza de un edificio se habría colgado del edificio de al
    lado, en silencio y sin nada que lo delatara.

    Comprobado en producción el 2026-08-25 antes de arreglarlo: no había llegado a
    pasar. Ninguna de las 392 pólizas ni de las 108 hipotecas estaba enlazada a una
    ficha que sólo difiriera en el número.
    """

    def _clave(self, valor):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "alta_clave", RAIZ / "scripts" / "alta_titulares_como_clientes.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.clave_de_nombre(valor)

    def test_dos_portales_de_la_misma_calle_son_distintos(self):
        for a, b in (("Com. Prop. Sierra Bermeja 5", "Com. Prop. Sierra Bermeja 7"),
                     ("EMILIO PRADOS 26", "EMILIO PRADOS 6"),
                     ("BARCENILLAS 6", "BARCENILLAS 12")):
            self.assertNotEqual(self._clave(a), self._clave(b), f"{a} vs {b}")

    def test_pero_el_mismo_portal_escrito_distinto_sigue_siendo_el_mismo(self):
        """El arreglo no puede romper lo que la clave venía a resolver."""
        self.assertEqual(self._clave("SIERRA BERMEJA 5"), self._clave("Sierra Bermeja, 5"))
        self.assertEqual(self._clave("MOHAMED BOUZYANE"), self._clave("BOUZYANE MOHAMED"))
        self.assertEqual(self._clave("Fernández Torres, Carmen"),
                         self._clave("FERNANDEZ TORRES CARMEN"))

    def test_lo_que_esta_clave_NO_resuelve_todavia(self):
        """Escrito para que se sepa, no para darlo por bueno.

        «C.P.» se parte en dos palabras y «CP» es una, así que no casan. No se toca
        aquí: juntar abreviaturas hace la clave más laxa, y más laxa es la dirección en
        la que se enlaza a quien no es. Si algún día molesta, se aborda aparte y con su
        propia prueba.
        """
        self.assertNotEqual(self._clave("C.P. Sierra Bermeja 5"),
                            self._clave("CP SIERRA BERMEJA 5"))

    def test_y_el_número_cuenta_como_una_palabra_más(self):
        self.assertEqual(self._clave("EMILIO PRADOS 26"), "26 emilio prados")
