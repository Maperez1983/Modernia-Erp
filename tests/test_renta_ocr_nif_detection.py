import unittest


class RentaOcrNifDetectionTests(unittest.TestCase):
    def test_nif_presentador_beats_date_like_false_positive(self):
        """
        Regression:
        Algunos OCR capturan texto tipo "EL 31-12-2024" y lo normalizan a un CIF falso
        (p.ej. "E13112202" por conversiones OCR L->1). Eso no debe desplazar el NIF real.
        """
        from web import server as s

        text = (
            "ESTADO CIVIL (EL 31-12-2024)\n"
            "PRESENTADOR\n"
            "NIF PRESENTADOR: 25099562F\n"
            "APELLIDOS Y NOMBRE / RAZON SOCIAL: GIL MARTIN JUAN CARLOS\n"
        )
        primary, ordered = s._find_best_nif_in_text(text)
        self.assertEqual(primary, "25099562F")
        self.assertIn("25099562F", ordered)


if __name__ == "__main__":
    unittest.main()

