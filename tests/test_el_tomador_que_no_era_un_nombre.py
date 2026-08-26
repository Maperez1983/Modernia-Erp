"""El lector de pólizas creaba clientes llamados «Y CONDUCTOR».

Cuando el PDF no encaja con el patrón de su compañía, el lector recorta la zona donde
suele estar el tomador y se trae lo que hubiera al lado: la letra pequeña, la etiqueta
del impreso, o media palabra cortada por el margen.

Eso no falla en silencio: **falla creando fichas de cliente**. En producción había, y se
han limpiado a mano:

  · «Y CONDUCTOR»                    ← de POLIZA AUTO Nº 2002400455146 - ADRIAN GUTIERREZ
  · «del Seguro Por SANITAS»
  · «de la póliza TERESA RAMOS RUEDA»
  · «de la póliza JOSE BANDERA DOMINGUEZ»
  · «Edificación y anexos»

Medido sobre las **133 pólizas reales** de la correduría: de 122 tomadores extraídos,
**40 no eran un nombre**. Con el arreglo bajan a 7, y esos 7 son casos donde el nombre
del fichero es una dirección —pólizas de impago, que aseguran un alquiler— y el lector
en realidad acierta.

La regla es que **vacío y equivocado no son el mismo fallo**. Vacío se lo pregunta a una
persona; equivocado lo escribe en la base. Ante la duda, vacío.

El medidor está en `scripts/mide_el_ocr_de_polizas.py`, y usa como referencia el nombre
del propio fichero, que en esta correduría lleva el número de póliza y el cliente.
"""

import os
import unittest

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web.server import (limpia_tomador, parse_poliza_text,  # noqa: E402
                        tomador_parece_un_nombre)


def leido(valor):
    """Lo que acabaría en la ficha: se limpia y, si no es un nombre, se descarta."""
    limpio = limpia_tomador(valor)
    return limpio if tomador_parece_un_nombre(limpio) else ""


class LoQueSalioDeAquiYAcaboEnProduccionTests(unittest.TestCase):
    """Cada uno de éstos fue una ficha de cliente de verdad."""

    def test_y_conductor(self):
        self.assertEqual(leido("Y CONDUCTOR"), "")

    def test_del_seguro_por_sanitas(self):
        self.assertEqual(leido("del Seguro Por SANITAS"), "")

    def test_edificacion_y_anexos(self):
        self.assertEqual(leido("Edificación y anexos"), "")

    def test_la_letra_pequena_de_occident(self):
        self.assertEqual(leido("de agua, gas, electricidad, en"), "")
        self.assertEqual(leido("r y que derogan expresamente l"), "")

    def test_la_etiqueta_del_impreso(self):
        for x in ("El asegurado: El tomador", "del Seguro", "Datos de su mediador",
                  "TOMADOR", "o, en su caso, al profesional/"):
            self.assertEqual(leido(x), "", x)

    def test_y_lo_que_no_tiene_letras(self):
        self.assertEqual(leido("2"), "")
        self.assertEqual(leido("8 11.239.386 E"), "")


class ElNombreSeRescataDeLaBasuraTests(unittest.TestCase):
    """Descartar no basta: el nombre está ahí y hay que sacarlo."""

    def test_con_la_etiqueta_pegada_delante(self):
        self.assertEqual(leido("de la póliza TERESA RAMOS RUEDA"), "TERESA RAMOS RUEDA")
        self.assertEqual(leido("de la póliza JOSE BANDERA DOMINGUEZ"),
                         "JOSE BANDERA DOMINGUEZ")

    def test_con_media_palabra_del_margen(self):
        """El recorte se lleva el final de la palabra de al lado."""
        self.assertEqual(leido("up SANTANA MUÑOZ, MARIA DEL CARMEN oD"),
                         "SANTANA MUÑOZ, MARIA DEL CARMEN")
        self.assertEqual(leido("ica KONECNY FIORE, BARBARA pl"), "KONECNY FIORE, BARBARA")

    def test_con_el_documento_detras(self):
        """El nombre acaba donde empieza el NIF."""
        self.assertEqual(leido("MIGUEL ANGEL PEREZ RODRIGUEZ NIF: 24835591F"),
                         "MIGUEL ANGEL PEREZ RODRIGUEZ")
        self.assertEqual(leido("TOMADOR LEOPOLDO ALBERTO CASTILLO NIF: 75149517F"),
                         "LEOPOLDO ALBERTO CASTILLO")


class LoQueNoPuedeRomperTests(unittest.TestCase):
    """Un nombre bueno tiene que salir intacto."""

    def test_un_nombre_normal(self):
        for x in ("MARIA MERCEDES MENDEZ GARCIA", "SEBASTIAN CORRALES",
                  "Sandra Lozano Romero", "BARBARA KONECNY"):
            self.assertEqual(leido(x), x, x)

    def test_las_particulas_de_un_apellido_se_quedan(self):
        """«DE OÑA» va por dentro del nombre y no es basura del margen."""
        self.assertEqual(leido("MALAGAMBA DE OÑA FERNANDO"), "MALAGAMBA DE OÑA FERNANDO")
        self.assertEqual(leido("CANO DE HOYOS JOSE LUIS"), "CANO DE HOYOS JOSE LUIS")

    def test_una_sociedad_tambien_es_un_tomador(self):
        for x in ("MOTIF STUDIO SL", "GAPP MONTAJE REPARACIONES",
                  "ESTUDIO VELAZQUEZ 2012 SL"):
            self.assertEqual(leido(x), x, x)


class ElFiltroEstaEnchufadoTests(unittest.TestCase):
    """Las de arriba prueban las piezas; ésta, que el lector las use.

    Escrita porque no lo estaba: quité la llamada de `parse_poliza_text` y las trece
    pruebas siguieron en verde. Sólo lo notó la medición sobre el corpus.
    """

    PAPEL = (
        "AXA SEGUROS GENERALES, S.A.\n"
        "CONDICIONES PARTICULARES\n"
        "Numero de poliza: 92202408\n"
        "Tomador del seguro: Y CONDUCTOR\n"
        "Fecha de efecto: 01/07/2025\n"
    )

    def test_el_lector_no_devuelve_un_tomador_que_no_es_un_nombre(self):
        campos = parse_poliza_text(self.PAPEL) or {}
        self.assertEqual(campos.get("tomador") or "", "",
                         "«Y CONDUCTOR» ha vuelto a salir del lector")

    def test_pero_sí_devuelve_uno_bueno(self):
        papel = self.PAPEL.replace("Y CONDUCTOR", "ADRIAN GUTIERREZ MORENO")
        campos = parse_poliza_text(papel) or {}
        self.assertIn("ADRIAN", (campos.get("tomador") or "").upper())

    def test_y_lo_limpia_por_el_camino(self):
        papel = self.PAPEL.replace("Y CONDUCTOR", "de la póliza TERESA RAMOS RUEDA")
        campos = parse_poliza_text(papel) or {}
        self.assertEqual((campos.get("tomador") or "").upper(), "TERESA RAMOS RUEDA")


class ElMedidorSigueEstandoTests(unittest.TestCase):
    def test_el_guion_que_mide_el_corpus(self):
        from pathlib import Path
        guion = Path(__file__).resolve().parents[1] / "scripts" / "mide_el_ocr_de_polizas.py"
        self.assertTrue(guion.exists())
        texto = guion.read_text(encoding="utf-8")
        # Vacío e inventado se cuentan aparte: son fallos distintos.
        self.assertIn("SE LO INVENTA", texto)
        self.assertIn("lo deja vacío", texto)


if __name__ == "__main__":
    unittest.main()
