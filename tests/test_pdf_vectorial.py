"""Los documentos con marca pasan de fotografía a texto.

El motor de siempre componía cada página con PIL y la incrustaba como JPEG. El
declarativo anual de hipotecas ocupaba 10,5 MB y el listado 15 MB, ninguno de los
dos llevaba una fuente incrustada —no se podía buscar ni copiar una cifra, ni lo
leía un lector de pantalla— y la tipografía del producto no llegaba a ellos.

Medido contra los 110 expedientes de producción:

    ficha          152 kB -> 36 kB
    declarativo  10.468 kB -> 2.488 kB
    listado      15.070 kB -> 352 kB   (95 páginas en vez de 111, sin perder ninguno)

Se conserva el motor viejo y se puede volver a él sin desplegar, con PDF_MOTOR=imagen.
"""

import os
import re
import unittest
from pathlib import Path

from web import server
from web.branded_pdf_vector import build_modernia_branded_document_pdf_vector

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
VECTOR = (RAIZ / "web" / "branded_pdf_vector.py").read_text(encoding="utf-8")

SECCIONES_DE_MUESTRA = [
    ("Resumen", {"kind": "feature_card", "eyebrow": "FICHA", "title": "Quien Sea",
                 "subtitle": "Banco X · Oficina Y", "badge": "FIRMADA",
                 "chips": ["BANCO X", "OFICINA Y"],
                 "items": [{"label": "Importe", "value": "100.000,00 €", "accent": True}],
                 "note": "Nota al pie."}),
    ("Datos", {"kind": "kpi_cards", "columns": 4,
               "items": [{"label": "Cliente", "value": "Quien Sea", "accent": True},
                         {"label": "Banco", "value": "Banco X"}]}),
    ("Reparto", {"kind": "split_bar", "label": "Comisión",
                 "items": [{"label": "Juan", "value": 500}, {"label": "Modernia", "value": 1500}]}),
    ("Pasos", {"kind": "waterfall", "label": "Cuadre",
               "steps": [{"label": "Entrada", "value": "35.000,00 €"}]}),
    ("Texto", ["Una línea suelta", "Otra línea"]),
]


def _pdf():
    return build_modernia_branded_document_pdf_vector(
        "Documento de prueba", "Subtítulo", SECCIONES_DE_MUESTRA,
        footer_lines=["Pie de página"], company={"nombre": "Empresa SL", "nif": "B00000000"},
    )


class ElDocumentoSaleTests(unittest.TestCase):
    def test_es_un_pdf(self):
        self.assertTrue(_pdf().startswith(b"%PDF"))

    def test_lleva_ibm_plex_incrustada(self):
        fuentes = {f.decode().split("+")[-1] for f in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-]+)", _pdf())}
        self.assertTrue(fuentes, "el PDF no declara ninguna fuente")
        for f in fuentes:
            with self.subTest(fuente=f):
                self.assertIn("IBMPlex", f)

    def test_el_texto_se_puede_extraer(self):
        """Lo que no se puede buscar ni copiar no es un documento, es una foto."""
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf no disponible")
        from io import BytesIO
        texto = "".join((p.extract_text() or "") for p in PdfReader(BytesIO(_pdf())).pages)
        self.assertIn("Quien Sea", texto)
        self.assertIn("100.000,00", texto)

    def test_entiende_todos_los_tipos_de_bloque(self):
        # Si un tipo se dejara sin dibujar, el documento saldría igualmente y nadie
        # lo notaría hasta verlo impreso.
        for tipo in ("kpi_cards", "feature_card", "split_bar", "waterfall", "page_break"):
            with self.subTest(tipo=tipo):
                self.assertIn(f'== "{tipo}"', VECTOR.replace("'", '"'))


class ElResalteSeRespetaTests(unittest.TestCase):
    """`accent` marca los datos que hay que mirar primero; perderlo aplana el documento."""

    def test_hay_una_funcion_que_lo_lee(self):
        self.assertTrue(server and True)
        self.assertIn("def _es_destacado(item):", VECTOR)

    def test_las_tarjetas_lo_usan(self):
        i = VECTOR.index("def _tarjetas_kpi")
        bloque = VECTOR[i: VECTOR.index("\ndef ", i + 10)]
        self.assertIn("_es_destacado(item)", bloque)
        self.assertIn("CREMA", bloque)


class SePuedeVolverAlMotorViejoTests(unittest.TestCase):
    def test_el_interruptor_existe(self):
        i = SERVER.index("def build_modernia_branded_document_pdf(")
        bloque = SERVER[i: SERVER.index("def build_modernia_branded_document_pdf_imagen", i)]
        self.assertIn('os.environ.get("PDF_MOTOR")', bloque)
        self.assertIn('("imagen", "pil", "raster")', bloque)

    def test_si_el_vectorial_falla_se_usa_el_de_imagen(self):
        # Un documento con el aspecto viejo es mejor que un documento que no sale.
        i = SERVER.index("def build_modernia_branded_document_pdf(")
        bloque = SERVER[i: SERVER.index("def build_modernia_branded_document_pdf_imagen", i)]
        self.assertIn("except Exception", bloque)
        self.assertIn("build_modernia_branded_document_pdf_imagen(", bloque)

    def test_el_motor_viejo_sigue_entero(self):
        self.assertIn("def build_modernia_branded_document_pdf_imagen(", SERVER)


class LosLogosNoSeIncrustanDeMasTests(unittest.TestCase):
    def test_se_reutiliza_la_misma_imagen(self):
        """Creando un lector por página, el declarativo llevaba 266 imágenes dentro."""
        i = VECTOR.index("def _logo_png")
        bloque = VECTOR[i: VECTOR.index("\ndef ", i + 10)]
        self.assertIn("cache", bloque)
        self.assertIn("ImageReader", bloque)


if __name__ == "__main__":
    unittest.main()
