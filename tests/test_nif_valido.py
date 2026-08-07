"""El NIF del emisor se comprueba, por lo mismo que el IBAN.

Un dígito mal tecleado en el NIF sale impreso en el presupuesto, en el certificado
de deuda y en la factura, y no lo detecta nadie hasta que lo devuelve Hacienda o lo
reclama el cliente. El algoritmo está publicado y cuesta veinte líneas.

Vino de dar de alta Inmovere Fincas el 2026-08-07: el usuario pasó el CIF por chat y
lo primero fue validarlo antes de meterlo en producción.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402


class LosDeLaCasaSonValidosTests(unittest.TestCase):
    def test_los_tres_cif_del_grupo(self):
        for cif, quien in (
            ("B72661374", "Fincas Velázquez"),
            ("B93227643", "Estudio Velázquez 2012"),
            ("B26798231", "Inmovere Fincas"),
        ):
            with self.subTest(quien=quien):
                self.assertTrue(server.nif_valido(cif), f"{quien}: {cif}")

    def test_da_igual_como_venga_escrito(self):
        self.assertTrue(server.nif_valido("b-72.661.374"))
        self.assertTrue(server.nif_valido(" B72661374 "))


class LosErroresDeTecleoSeCazanTests(unittest.TestCase):
    def test_un_digito_de_control_cambiado(self):
        self.assertFalse(server.nif_valido("B26798232"))
        self.assertFalse(server.nif_valido("B72661375"))

    def test_dos_cifras_intercambiadas(self):
        """El error de tecleo más común, y el control lo detecta."""
        self.assertFalse(server.nif_valido("B27698231"))

    def test_lo_que_no_es_un_nif(self):
        for valor in ("", None, "hola", "1234", "B2679823", "B267982311"):
            with self.subTest(valor=valor):
                self.assertFalse(server.nif_valido(valor))


class TambienPersonasYExtranjerosTests(unittest.TestCase):
    def test_nif_de_persona_fisica(self):
        self.assertTrue(server.nif_valido("12345678Z"))
        self.assertFalse(server.nif_valido("12345678A"))

    def test_nie(self):
        self.assertTrue(server.nif_valido("X1234567L"))
        self.assertFalse(server.nif_valido("X1234567A"))

    def test_cif_con_control_de_letra(self):
        """Las sociedades P, Q, S y demás llevan letra en vez de número."""
        self.assertTrue(server.nif_valido("Q2826000H"))


if __name__ == "__main__":
    unittest.main()
