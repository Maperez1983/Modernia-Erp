import unittest

from web.server import _parse_nomina_pdf_fields


class NominaEmpresaAportacionFallbackTests(unittest.TestCase):
    def test_extracts_ss_empresa_from_empresa_aportacion_block(self):
        sample = """
        Periodo de liquidación: del 1 de Febrero al 28 de Febrero de 2026
        Trabajador: BARTHA GONZALO JOSE
        NIF: Z0068840Y
        TOTAL DEVENGOS: 711,39
        Observaciones: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        LIQUIDO A PERCIBIR: 665,14

        LA BASE SUJETA A RETENCIÓN DEL IRPF Y APORTACIÓN DE LA EMPRESA
        APORTACIÓN DE LA EMPRESA                               APORTACIÓN                     BASE            TIPO
                                      TOTAL .................................................................................      711,39        24,35               173,22
                                                                  AT y EP ...............................................          711,39         1,65                11,73
        2. Contingencias profesionales y conceptos de Desempleo ..........................................                         711,39         5,50                39,13
           recaudación conjunta                                   Formación .................................................        711,39         0,60                 4,27
           FOGASA ..................................................                                        711,39         0,20                 1,42
           Desempleo ..............................................                                        711,39        32,30               229,77
        """
        fields = _parse_nomina_pdf_fields(sample)
        self.assertEqual(fields.get("year"), 2026)
        self.assertEqual(fields.get("month"), 2)
        self.assertEqual(fields.get("empleado_nif"), "Z0068840Y")
        self.assertAlmostEqual(float(fields.get("bruto") or 0), 711.39, places=2)
        self.assertAlmostEqual(float(fields.get("neto") or 0), 665.14, places=2)
        self.assertAlmostEqual(float(fields.get("ss_empresa") or 0), 459.54, places=2)


if __name__ == "__main__":
    unittest.main()

