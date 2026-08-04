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
