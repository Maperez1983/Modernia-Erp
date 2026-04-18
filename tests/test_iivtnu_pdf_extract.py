import unittest

from web.server import _iivtnu_extract_from_text


class IivtnuPdfExtractTests(unittest.TestCase):
    def test_extracts_simulacion_ayuda_fields(self):
        text = """
        PLUSVALIA. PROGRAMA DE AYUDA AL CÁLCULO DEL IMPUESTO
        OBJETO TRIBUTARIO AV ESCRITOR ANTONIO SOLER C.P. 29003
        REFERENCIA CATASTRAL 6954101UF6665S0280
        FECHA ADQUISICIÓN 17/02/2010
        FECHA TRANSMISIÓN 10/03/2020
        VALOR SUELO 35.447,24
        100 % %PARTICIPACIÓN
        BASE IMPONIBLE 12.406,53
        TIPO DE GRAVAMEN (%) 29
        CUOTA TRIBUTARIA 3.597,90
        IMPORTE TOTAL 3.597,90
        """
        out = _iivtnu_extract_from_text(text, filename="PLUSVALIA.pdf")
        self.assertEqual(out.get("doc_type"), "simulacion_ayuda")
        self.assertEqual(out.get("codigo_postal"), "29003")
        self.assertEqual(out.get("referencia_catastral"), "6954101UF6665S0280")
        self.assertEqual(out.get("fecha_adquisicion"), "2010-02-17")
        self.assertEqual(out.get("fecha_transmision"), "2020-03-10")
        self.assertAlmostEqual(float(out.get("valor_suelo") or 0), 35447.24, places=2)
        self.assertAlmostEqual(float(out.get("participacion_pct") or 0), 100.0, places=2)
        self.assertAlmostEqual(float(out.get("base_imponible") or 0), 12406.53, places=2)
        self.assertAlmostEqual(float(out.get("tipo_gravamen_pct") or 0), 29.0, places=2)
        self.assertAlmostEqual(float(out.get("cuota_tributaria") or 0), 3597.90, places=2)
        self.assertAlmostEqual(float(out.get("importe_total") or 0), 3597.90, places=2)

    def test_classifies_guia_autoliquidacion(self):
        text = """
        IMPUESTO SOBRE EL INCREMENTO DEL VALOR DE LOS TERRENOS DE NATURALEZA URBANA
        GUÍA DE AUTOLIQUIDACIÓN
        Mod. 004 – V.1
        29003 MÁLAGA
        """
        out = _iivtnu_extract_from_text(text)
        self.assertEqual(out.get("doc_type"), "guia_autoliquidacion")
        self.assertEqual(out.get("codigo_postal"), "29003")

    def test_avoids_false_refcat_tokens(self):
        text = """
        Gestión Tributaria Organismo Autónomo
        SOLICITUD ESPECIFICA
        IMPUESTO SOBRE EL INCREMENTO DE VALOR DE LOS TERRENOS DE NATURALEZA URBANA
        (*): CUMPLIMENTAR EXCLUSIVAMENTE PARA USO INTERNO
        29003 MÁLAGA
        """
        out = _iivtnu_extract_from_text(text)
        self.assertEqual(out.get("doc_type"), "solicitud_inexistencia_incremento")
        self.assertEqual(out.get("referencia_catastral") or "", "")

    def test_extracts_carta_pago_fields(self):
        text = """
        CARTA DE PAGO
        NRC: 1234ABCD5678EFGH9012
        MODELO: 004
        EJERCICIO: 2025
        FECHA DE PAGO: 01/03/2025
        BONIFICACIÓN (%) 50
        IMPORTE TOTAL: 123,45
        """
        out = _iivtnu_extract_from_text(text, filename="carta_pago.pdf")
        self.assertEqual(out.get("doc_type"), "carta_pago")
        self.assertEqual(out.get("modelo"), "004")
        self.assertEqual(out.get("ejercicio"), "2025")
        self.assertEqual(out.get("fecha_pago"), "2025-03-01")
        self.assertEqual(out.get("nrc"), "1234ABCD5678EFGH9012")
        self.assertAlmostEqual(float(out.get("bonificacion_pct") or 0), 50.0, places=2)
        self.assertAlmostEqual(float(out.get("importe_total") or 0), 123.45, places=2)
