"""Regresión del parser de nóminas `_parse_nomina_pdf_fields`.

Trabaja sobre TEXTO (lo que `pdftotext -layout` / tesseract producen), así que no
necesita dependencias externas (cryptography/openpyxl/PIL). Blinda los bugs
detectados al probar el OCR con nóminas de ejemplo:
  * el importe de cada etiqueta se toma de SU línea, sin colarse en las filas
    siguientes (neto/bruto se iban al FOGASA o al Desempleo).
  * el NIF del empleado (DNI/NIE) se prioriza sobre el CIF de la empresa.
  * el nombre no arrastra la etiqueta del identificador ("... D.N.I.:", "_NIF:").
  * no se truncan nombres que contengan "NIE"/"NIF"/"DNI" (NIEVES, DANIEL...).
"""
import unittest

from web.server import _parse_nomina_pdf_fields


NOMINA_A = """\
MODERNIA SERVICIOS SL
CIF: B12345678 C.C.C.: 28/1234567/89
Trabajador: LUCÍA FERRER GÓMEZ                     NIF: 12345678Z
Periodo de liquidación: del 1 al 30 de Abril de 2026 (30 días)
I. DEVENGOS
 Salario base ............................. 1.450,00
 Horas extraordinarias ...................... 120,00
 TOTAL DEVENGADO .......................... 1.900,00
II. DEDUCCIONES
 Seguridad Social Trabajador (6,35%) ........ 120,65
 Desempleo (1,55%) ........................... 29,45
 Retención IRPF (12,00%) .................... 228,00
 TOTAL DEDUCCIONES .......................... 348,65
Base sujeta a retención del IRPF ........... 1.900,00
LÍQUIDO A PERCIBIR ......................... 1.551,35
APORTACIÓN DE LA EMPRESA
 Contingencias comunes (23,60%) ............. 448,40
 FOGASA (0,20%) .............................. 3,80
"""

# Formato distinto: periodo MM/YYYY, "NETO A PERCIBIR", "I.R.P.F." con puntos,
# CIF de empresa antes del DNI del trabajador.
NOMINA_B = """\
TALLERES DELTA S.L.   C.I.F.: B87654321
Apellidos y nombre: RUIZ MARCOS, ANTONIO      D.N.I.: 87654321X
Periodo: 05/2026    Días: 31
DEVENGOS
  Salario base                              2.100,00
  TOTAL DEVENGOS                            2.600,00
DEDUCCIONES
  I.R.P.F.  15,00 %                           390,00
  TOTAL A DEDUCIR                             580,00
NETO A PERCIBIR                             2.020,00
"""


class NominaAmountTests(unittest.TestCase):
    def test_neto_no_se_cuela_en_lineas_siguientes(self):
        # El bug original devolvía 3,80 (FOGASA) por leer una ventana ancha.
        f = _parse_nomina_pdf_fields(NOMINA_A)
        self.assertEqual(f.get("neto"), 1551.35)

    def test_bruto_toma_total_devengado_de_su_linea(self):
        # El bug original devolvía 29,45 (Desempleo).
        f = _parse_nomina_pdf_fields(NOMINA_A)
        self.assertEqual(f.get("bruto"), 1900.00)

    def test_periodo_y_irpf_texto_con_mes_nombre(self):
        f = _parse_nomina_pdf_fields(NOMINA_A)
        self.assertEqual(f.get("year"), 2026)
        self.assertEqual(f.get("month"), 4)
        self.assertEqual(f.get("irpf_pct"), 12.0)

    def test_formato_b_importes_y_periodo_mmyyyy(self):
        f = _parse_nomina_pdf_fields(NOMINA_B)
        self.assertEqual(f.get("neto"), 2020.00)
        self.assertEqual(f.get("bruto"), 2600.00)
        self.assertEqual(f.get("year"), 2026)
        self.assertEqual(f.get("month"), 5)

    def test_irpf_con_puntos_se_reconoce(self):
        # "I.R.P.F.  15,00 %" debe dar 15.0.
        f = _parse_nomina_pdf_fields(NOMINA_B)
        self.assertEqual(f.get("irpf_pct"), 15.0)


class NominaNifTests(unittest.TestCase):
    def test_prefiere_dni_empleado_sobre_cif_empresa(self):
        # A: CIF B12345678 antes del DNI 12345678Z -> debe ganar el DNI.
        self.assertEqual(_parse_nomina_pdf_fields(NOMINA_A).get("empleado_nif"), "12345678Z")

    def test_dni_con_etiqueta_punteada_dni(self):
        # B: "D.N.I.: 87654321X" con CIF de empresa antes.
        self.assertEqual(_parse_nomina_pdf_fields(NOMINA_B).get("empleado_nif"), "87654321X")

    def test_detecta_nie(self):
        txt = "Trabajador: JUAN NIE: X1234567T\nLÍQUIDO A PERCIBIR 1.000,00\n"
        self.assertEqual(_parse_nomina_pdf_fields(txt).get("empleado_nif"), "X1234567T")


class NominaNombreTests(unittest.TestCase):
    def test_nombre_no_arrastra_etiqueta_nif(self):
        self.assertEqual(_parse_nomina_pdf_fields(NOMINA_A).get("empleado_nombre"), "LUCÍA FERRER GÓMEZ")

    def test_nombre_no_arrastra_etiqueta_dni_punteada(self):
        self.assertEqual(_parse_nomina_pdf_fields(NOMINA_B).get("empleado_nombre"), "RUIZ MARCOS, ANTONIO")

    def test_nombre_con_etiqueta_pegada_estilo_ocr(self):
        # tesseract a veces pega "__NIF:" al nombre.
        txt = "Trabajador: LUCIA FERRER GOMEZ __NIF: 12345678Z\nLÍQUIDO A PERCIBIR 900,00\n"
        self.assertEqual(_parse_nomina_pdf_fields(txt).get("empleado_nombre"), "LUCIA FERRER GOMEZ")

    def test_nombre_que_contiene_nie_no_se_trunca(self):
        # "NIEVES" contiene "NIE" y "DANIEL" contiene "NIE": no deben cortarse.
        txt = "Trabajador: MARIA NIEVES SAN DANIEL      NIF: 11223344H\nLÍQUIDO 800,00\n"
        self.assertEqual(_parse_nomina_pdf_fields(txt).get("empleado_nombre"), "MARIA NIEVES SAN DANIEL")


if __name__ == "__main__":
    unittest.main()
