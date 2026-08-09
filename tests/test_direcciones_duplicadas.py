"""Dos fichas de la misma casa escrita de otra forma no eran un duplicado.

El alta de un inmueble ya avisaba de duplicados comparando dirección, referencia
catastral y NIF del propietario. Pero la dirección se comparaba casi en crudo, así
que «CALLE Goya 12» y «C/ Goya 12» eran dos direcciones distintas y el aviso no
saltaba. Pasó de verdad, y salió caro: «Avenida las Postas Nº22 bajo 3g» y «bajo 6g»
—misma referencia catastral— generaron dos operaciones de la misma venta, y 209.000 €
se contaron dos veces en el volumen de cierre.

`normalize_inmobiliaria_address` ahora canoniza el tipo de vía con el mismo mapa que
ya se usaba para consultar al Catastro (CALLE = CL = C/) y quita las formas del
número (Nº22 = N 22 = núm. 22 = 22).

Lo que este test protege es el equilibrio, que es lo delicado: tiene que juntar lo
que es la misma casa **sin** juntar lo que no lo es. Un piso y otro del mismo portal
se diferencian sólo en la puerta —«bajo 3G» y «bajo 6G»—, así que un normalizador
demasiado agresivo fusionaría vecinos distintos. Por eso hay tantos casos de «no
deben coincidir» como de «deben coincidir».

Se comprobó contra las 86 direcciones reales de producción: detecta exactamente un
grupo, y es correcto (una venta y un alquiler del mismo local).
"""

import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Sin esto, importar el servidor abre la base de producción.
os.environ.setdefault("DATABASE_URL", "")

from web.server import (  # noqa: E402
    CATRASTRO_STREET_TYPE_MAP,
    normalize_inmobiliaria_address,
)


class MismaCasaEscritaDeOtraForma(unittest.TestCase):
    """Estas parejas son la misma dirección y tienen que dar el mismo resultado."""

    def comprueba(self, *variantes):
        normalizadas = {normalize_inmobiliaria_address(v) for v in variantes}
        self.assertEqual(
            len(normalizadas),
            1,
            f"{variantes} deberían ser la misma dirección, y salen {normalizadas}",
        )

    def test_el_tipo_de_via_se_escribe_de_seis_formas(self):
        self.comprueba("CALLE Goya 12", "C/ Goya 12", "C Goya 12", "Cl Goya 12", "calle goya 12")

    def test_avenida_abreviada(self):
        self.comprueba("Avenida las Postas 22", "Avda las Postas 22", "AV LAS POSTAS 22")

    def test_urbanizacion_abreviada(self):
        self.comprueba("Urbanización El Rocío 3", "Urb. El Rocio 3", "UR EL ROCIO 3")

    def test_las_formas_del_numero(self):
        self.comprueba(
            "Avenida las Postas Nº22",
            "Avenida las Postas N 22",
            "Avenida las Postas núm. 22",
            "Avenida las Postas numero 22",
            "Avenida las Postas 22",
        )

    def test_los_acentos_y_los_espacios_de_mas(self):
        self.comprueba("Calle  Andrés   Segovia 4", "CALLE ANDRES SEGOVIA 4")

    def test_el_caso_real_que_costo_209000_euros(self):
        # Aquí lo que las une no es la dirección —la puerta difiere de verdad— sino
        # la referencia catastral. Se deja escrito para que quede claro que el
        # normalizador NO debe fusionarlas: son dos puertas distintas.
        a = normalize_inmobiliaria_address("Avenida las Postas Nº22 bajo 3g")
        b = normalize_inmobiliaria_address("Avenida las Postas Nº22 bajo 6g")
        self.assertNotEqual(a, b, "bajo 3G y bajo 6G son dos pisos, no uno")


class CasasDistintasQueNoSeDebenFusionar(unittest.TestCase):
    """Lo que más daño hace no es no detectar un duplicado, sino inventarse uno."""

    def comprueba_distintas(self, a, b):
        self.assertNotEqual(
            normalize_inmobiliaria_address(a),
            normalize_inmobiliaria_address(b),
            f"«{a}» y «{b}» no son la misma dirección",
        )

    def test_numeros_distintos(self):
        self.comprueba_distintas("Calle Goya 12", "Calle Goya 14")

    def test_puertas_distintas(self):
        self.comprueba_distintas("Calle Goya 12 bajo A", "Calle Goya 12 bajo B")

    def test_plantas_distintas(self):
        self.comprueba_distintas("Calle Goya 12 1º A", "Calle Goya 12 3º A")

    def test_calles_distintas(self):
        self.comprueba_distintas("Calle Goya 12", "Calle Velázquez 12")

    def test_una_plaza_no_es_un_pasaje(self):
        # El mapa daba la sigla PJ a las dos, así que se veían iguales.
        self.comprueba_distintas("Plaza Mayor 3", "Pasaje Mayor 3")

    def test_la_cadena_vacia_no_agrupa_nada(self):
        # Si el vacío devolviera algo, todas las fichas sin dirección saldrían
        # como duplicadas entre sí. Es el falso positivo más fácil de cometer.
        for vacio in ("", "   ", None):
            self.assertEqual(normalize_inmobiliaria_address(vacio), "")


class LaSiglaDeCadaVia(unittest.TestCase):
    def test_plaza_lleva_la_sigla_del_catastro(self):
        # PZ es la sigla del Catastro para plaza; PJ es la de pasaje. Con PJ, la
        # consulta al Catastro de una plaza no encontraba la vía.
        for forma in ("PLAZA", "PZA", "PLZ", "PZ", "PL"):
            self.assertEqual(CATRASTRO_STREET_TYPE_MAP[forma], "PZ", forma)
        for forma in ("PASAJE", "PJ"):
            self.assertEqual(CATRASTRO_STREET_TYPE_MAP[forma], "PJ", forma)

    def test_ninguna_sigla_se_usa_para_dos_vias_distintas(self):
        # Este es el fallo que tuvo el mapa: dos tipos de vía compartiendo sigla
        # hacen que dos direcciones distintas se vean como la misma.
        familias = {
            "CL": {"CALLE", "CL", "C"},
            "AV": {"AVENIDA", "AV", "AVDA"},
            "PS": {"PASEO", "PS"},
            "PJ": {"PASAJE", "PJ"},
            "PZ": {"PLAZA", "PZA", "PLZ", "PZ", "PL"},
            "CM": {"CAMINO", "CM"},
            "CR": {"CARRETERA", "CR"},
            "RD": {"RONDA", "RD"},
            "UR": {"URBANIZACION", "URBANIZACIÓN", "URB"},
            "TR": {"TRAVESIA", "TRAVESÍA", "TR"},
            "BA": {"BARRIADA", "BARDA", "BA"},
        }
        for sigla, formas in familias.items():
            reales = {k for k, v in CATRASTRO_STREET_TYPE_MAP.items() if v == sigla}
            self.assertEqual(
                reales,
                formas,
                f"la sigla {sigla} no cubre exactamente lo que debería",
            )


if __name__ == "__main__":
    unittest.main()
