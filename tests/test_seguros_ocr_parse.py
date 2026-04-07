import unittest

from web.server import compute_ocr_quality, parse_poliza_text


class SegurosOcrParseTests(unittest.TestCase):
    def test_parse_poliza_basic_fields(self):
        text = """
        PÓLIZA Nº 1234567890
        Tomador: Juan Pérez Gómez
        Compañía: MAPFRE
        Fecha efecto: 01/02/2026
        """
        fields = parse_poliza_text(text)
        self.assertEqual(fields["poliza_numero"], "1234567890")
        self.assertEqual(fields["tomador"], "Juan Pérez Gómez")
        self.assertEqual(fields["compania"], "Mapfre")
        self.assertEqual(fields["fecha_efecto"], "01/02/2026")

    def test_parse_poliza_axa_format(self):
        text = """
        AXA
        Póliza nº 12 12345678
        Tomador: Ana López
        Fecha efecto: 01/01/2026
        """
        fields = parse_poliza_text(text)
        self.assertEqual(fields["compania"], "AXA")
        self.assertEqual(fields["poliza_numero"], "12-12345678")

    def test_parse_poliza_cif_ocr_keeps_prefix_letter(self):
        # OCR confunde 0/O dentro de dígitos, pero no debe convertir el prefijo CIF "B" a "8".
        text = """
        Compañía: Mapfre
        Póliza: 123456789
        Tomador: Empresa SL
        NIF: B12O4567B
        Fecha efecto: 01/03/2026
        """
        fields = parse_poliza_text(text)
        self.assertEqual(fields["dni"], "B1204567B")

    def test_compute_ocr_quality_validates_required(self):
        fields = {
            "tomador": "Empresa SL",
            "poliza_numero": "123456789",
            "compania": "Mapfre",
            "fecha_efecto": "01/03/2026",
        }
        quality = compute_ocr_quality(fields, required_keys=("tomador", "poliza_numero", "compania", "fecha_efecto"))
        self.assertEqual(sorted(quality["required_valid"]), ["compania", "fecha_efecto", "poliza_numero", "tomador"])


if __name__ == "__main__":
    unittest.main()

