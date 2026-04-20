import unittest

from web.server import _iivtnu_extract_from_text, _iivtnu_load_tipo_gravamen_andalucia


class IivtnuPdfExtractTests(unittest.TestCase):
    def test_extracts_simulacion_ayuda_fields(self):
        text = """
        PLUSVALIA. PROGRAMA DE AYUDA AL CÁLCULO DEL IMPUESTO
        OBJETO TRIBUTARIO AV ESCRITOR ANTONIO SOLER C.P. 29003
        REFERENCIA CATASTRAL 6954101UF6665S0280
        FECHA ADQUISICIÓN 17/02/2010
        FECHA TRANSMISIÓN 10/03/2020
        VALOR SUELO 35.447,24
        VALOR CATASTRAL TOTAL 120.000,00
        COEF. REDUCCIÓN 0,60
        VALOR REDUCIDO (A) 21.268,34
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
        self.assertAlmostEqual(float(out.get("valor_catastral_total") or 0), 120000.00, places=2)
        self.assertAlmostEqual(float(out.get("coef_reduccion") or 0), 0.60, places=2)
        self.assertAlmostEqual(float(out.get("valor_suelo_reducido") or 0), 21268.34, places=2)
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

    def test_extracts_documento_de_pago_malaga_fields(self):
        text = """
        DOCUMENTO DE PAGO
        29003 MALAGA
        Fecha transmisión efectiva: 20/06/2025 U.T.M.: 0123104/UF7602S 0006
        Clase trans.:Compra-venta Dcho.transm.:Pleno 100,00% Subdiv: 50,00
        V.Catastral: 26.878,89 V.Suelo: 17.901,36 Prop.%: 66,60
        V.Transmis.: 65.000,00 V.Adquis.: 45.000,00
        BI-Mét.obj: 1.521,62 BI-Mé.dir.: 13.320,00
        Tipo %:29,0 Cuota íntegra: 441,27 Bon.: 0,0
        Referencia A.E.B.: 9050702906700500004032076603601082500000441270
        """
        out = _iivtnu_extract_from_text(text, filename="documento_pago.pdf")
        self.assertEqual(out.get("doc_type"), "carta_pago")
        self.assertEqual(out.get("codigo_postal"), "29003")
        self.assertEqual(out.get("fecha_transmision"), "2025-06-20")
        self.assertAlmostEqual(float(out.get("valor_catastral_total") or 0), 26878.89, places=2)
        self.assertAlmostEqual(float(out.get("valor_suelo") or 0), 17901.36, places=2)
        self.assertAlmostEqual(float(out.get("porcentaje_suelo") or 0), 66.60, places=2)
        self.assertAlmostEqual(float(out.get("subdivision_pct") or 0), 50.0, places=2)
        self.assertAlmostEqual(float(out.get("valor_transmision") or 0), 65000.0, places=2)
        self.assertAlmostEqual(float(out.get("valor_adquisicion") or 0), 45000.0, places=2)
        self.assertAlmostEqual(float(out.get("base_imponible") or 0), 1521.62, places=2)
        self.assertAlmostEqual(float(out.get("tipo_gravamen_pct") or 0), 29.0, places=2)
        self.assertAlmostEqual(float(out.get("cuota_tributaria") or 0), 441.27, places=2)
        self.assertTrue(str(out.get("referencia_aeb") or "").startswith("90507029067"))

    def test_extracts_autoliquidacion_table_style_fields(self):
        # Caso típico OCR/autoliquidación: tabla A/B con valor catastral y valor suelo,
        # y "Tipo gravamen" sin "de" y con separador coma.
        text = """
        IMPUESTO SOBRE EL INCREMENTO DEL VALOR DE LOS TERRENOS DE NATURALEZA URBANA
        AUTOLIQUIDACION Mod. 004-2
        PROTOCOLO FECHA DOCUMENTO NOTARIO
        2023000461 16/02/2023 DIAZ SERRANO, PEDRO
        MUNICIPIO PROVINCIA CÓDIGO POSTAL
        MALAGA MALAGA 29140
        1 BIEN TRANSMITIDO (OBJETO TRIBUTARIO) FECHA ADQUISICION
        A | VALOR CATASTRAL
        16.710,95 D 25/05/1987 100,0000
        B | VALOR SUELO
        10.735,12
        2 BASE IMPONIBLE
        3 DEUDA TRIBUTARIA
        BASE IMPONIBLE 4.830,80
        Tipo gravamen 29,0
        CUOTA TRIBUTARIA 1.400,93
        IMPORTE TOTAL 1.400,93
        """
        out = _iivtnu_extract_from_text(text, filename="Plusvalia.pdf")
        self.assertEqual(out.get("doc_type"), "autoliquidacion")
        self.assertEqual(out.get("codigo_postal"), "29140")
        self.assertEqual(out.get("fecha_transmision"), "2023-02-16")
        self.assertEqual(out.get("fecha_adquisicion"), "1987-05-25")
        self.assertAlmostEqual(float(out.get("valor_catastral_total") or 0), 16710.95, places=2)
        self.assertAlmostEqual(float(out.get("valor_suelo") or 0), 10735.12, places=2)
        self.assertAlmostEqual(float(out.get("base_imponible") or 0), 4830.80, places=2)
        self.assertAlmostEqual(float(out.get("tipo_gravamen_pct") or 0), 29.0, places=2)
        self.assertAlmostEqual(float(out.get("cuota_tributaria") or 0), 1400.93, places=2)
        self.assertAlmostEqual(float(out.get("importe_total") or 0), 1400.93, places=2)

    def test_extracts_estimacion_importe_pagar_fields(self):
        text = """
        IMPUESTO SOBRE EL INCREMENTO DE VALOR DE
        LOS TERRENOS DE NATURALEZA URBANA.
        ESTIMACIÓN DEL IMPORTE A PAGAR
        OBJETO TRIBUTARIO CL MARCONI 7 06 29004

        TRANSMISIÓN ACTUAL FECHA FIN PLAZO PRESENTACION/PAGO
        Tipo Fecha Fecha fallecimiento
        COMPRAVENTA 09/04/2025 26/05/2025

        1 BIEN TRANSMITIDO (OBJETO TRIBUTARIO) FECHA ADQUISICIÓN
        REF. CATASTRAL 0123104UF7602S0006IB
        VALOR CATASTRAL
        A TIPO EDAD % (D) t1 23/02/2007 100,00
        26.878,89
        VALOR SUELO Usufructo
        B 17.901,36 t2
        Nuda prop. 100,00% t3

        % VALOR SUELO SOBRE VALOR CATASTRAL (B/A) 66,60

        SUMA = BASE IMPONIBLE MÉTODO OBJETIVO 3.043,23
        BASE IMPONIBLE 3.043,23
        Tipo gravamen 29,0
        CUOTA TRIBUTARIA 882,54
        IMPORTE TOTAL 882,54
        """
        out = _iivtnu_extract_from_text(text, filename="simulacionPlusvalia año 2025.pdf")
        self.assertEqual(out.get("doc_type"), "simulacion_ayuda")
        self.assertEqual(out.get("codigo_postal"), "29004")
        self.assertEqual(out.get("fecha_transmision"), "2025-04-09")
        self.assertEqual(out.get("fecha_adquisicion"), "2007-02-23")
        self.assertAlmostEqual(float(out.get("valor_catastral_total") or 0), 26878.89, places=2)
        self.assertAlmostEqual(float(out.get("valor_suelo") or 0), 17901.36, places=2)
        self.assertAlmostEqual(float(out.get("porcentaje_suelo") or 0), 66.60, places=2)
        self.assertAlmostEqual(float(out.get("base_imponible") or 0), 3043.23, places=2)
        self.assertAlmostEqual(float(out.get("tipo_gravamen_pct") or 0), 29.0, places=2)
        self.assertAlmostEqual(float(out.get("cuota_tributaria") or 0), 882.54, places=2)
        self.assertAlmostEqual(float(out.get("importe_total") or 0), 882.54, places=2)

    def test_extracts_palma_catalan_autoliquidacion_fields(self):
        text = """
        Ajuntament de Palma Exemplar per al Contribuent
        IMPOST INCREMENT VALOR TERRENYS NATURALESA URBANA
        Detalle de la Autoliquidación
        D.MERITACIÓ ACTUAL: 18/02/2025 REF.CADASTRAL:1298501DD7719G0303WE
        VC SÒL: 18190,74 V.TRIB: 18190,74
        F.TRANS ANT. (%) OPERACIÓ TEMPS COEFICIENT B.IMPOSABLETIPUS% QUOTA INT
        06/06/2016 100 PD 8A 0.19 3456,24 21.5 743,09
        ADQUIRENTS (0): QUOTA INT T:743,09
        % BONIF: QUOTA LIQ: 743,09
        """
        out = _iivtnu_extract_from_text(text, filename="palma.pdf")
        self.assertEqual(out.get("doc_type"), "autoliquidacion")
        self.assertEqual(out.get("municipio"), "Palma")
        self.assertEqual(out.get("codigo_postal") or "", "")
        self.assertEqual(out.get("fecha_adquisicion"), "2016-06-06")
        self.assertEqual(out.get("fecha_transmision"), "2025-02-18")
        self.assertAlmostEqual(float(out.get("valor_suelo") or 0), 18190.74, places=2)
        self.assertAlmostEqual(float(out.get("base_imponible") or 0), 3456.24, places=2)
        self.assertAlmostEqual(float(out.get("tipo_gravamen_pct") or 0), 21.5, places=2)
        self.assertAlmostEqual(float(out.get("cuota_tributaria") or 0), 743.09, places=2)
        self.assertAlmostEqual(float(out.get("importe_total") or 0), 743.09, places=2)

    def test_andalucia_tipo_catalog_loaded(self):
        data = _iivtnu_load_tipo_gravamen_andalucia() or {}
        self.assertTrue(isinstance(data, dict))
        years = data.get("years") or {}
        self.assertTrue(isinstance(years, dict))
        self.assertTrue(bool(years))
        ymap = next(iter(years.values())) or {}
        self.assertTrue(isinstance(ymap, dict))
        self.assertGreater(len(ymap), 100)
