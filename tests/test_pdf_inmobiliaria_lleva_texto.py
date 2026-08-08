"""Los documentos de la inmobiliaria son texto, no una foto del texto.

De las nueve empresas del sistema sólo dos llevan «modernia» en el nombre, y el
enrutado de PDF miraba justo eso para decidir si usar el motor que dibuja texto o el
que compone la página con PIL y la incrusta como un mapa de bits. Las inmobiliarias
—de las que cuelgan los 86 inmuebles— caían siempre al segundo: la nota de encargo
que firma el propietario eran tres páginas de 1240x1754 píxeles, 617 kB, sin una sola
fuente dentro. No se podía buscar una cifra, ni copiar una cláusula, ni leerla un
lector de pantalla.

La nota de encargo además llamaba al generador de texto corrido directamente, sin
pasar por el enrutado, así que tampoco le valía arreglar sólo la puerta.
"""

import os
import unittest
from io import BytesIO

os.environ.setdefault("DATABASE_URL", "")

from pypdf import PdfReader  # noqa: E402

from web import server  # noqa: E402


EMPRESA = {
    "id": "emp-1",
    "nombre": "Estudio Velazquez 2012 SL",   # no lleva «modernia»: ese era el caso roto
    "nif": "B00000000",
    "direccion": "Calle Ejemplo 1",
}
INMUEBLE = {
    "id": "inm-1",
    "direccion": "Calle de la Prueba 3",
    "codigo_postal": "29010",
    "poblacion": "Málaga",
    "provincia": "Málaga",
    "referencia_catastral": "0000000XX0000X0000XX",
    "m2": 90,
}
PROPIETARIOS = [{"nombre": "Propietario Uno", "nif": "00000000T", "direccion": "Calle Ejemplo 2"}]
COMPRADOR = {"nombre": "Comprador Uno", "nif": "11111111H", "telefono": "600000000"}
ACCION = {"importe_propuesta": 120000, "fecha": "2026-08-08"}


def documentos():
    """Los diez PDF del módulo, cada uno con su generador."""
    return {
        "nota de encargo": server.build_inmueble_nota_encargo_pdf(EMPRESA, INMUEBLE, {}, PROPIETARIOS),
        "nota de encargo editable": server.build_inmueble_nota_encargo_pdf_editable(EMPRESA, INMUEBLE, {}, PROPIETARIOS),
        "nota de encargo final": server.build_inmueble_nota_encargo_pdf_final(EMPRESA, INMUEBLE, {}, PROPIETARIOS),
        "hoja de visita": server.build_inmueble_visit_sheet_pdf(EMPRESA, INMUEBLE, {}, PROPIETARIOS, COMPRADOR),
        "consumo venta": server.build_inmueble_consumo_sale_sheet_pdf(EMPRESA, INMUEBLE, {}, []),
        "nota de precio": server.build_inmueble_consumo_sale_price_note_pdf(EMPRESA, INMUEBLE, {}),
        "consumo alquiler": server.build_inmueble_consumo_rental_dia_pdf(EMPRESA, INMUEBLE, {}, []),
        "promesa de compraventa": server.build_inmueble_negotiation_offer_pdf(EMPRESA, INMUEBLE, COMPRADOR, ACCION),
        "reconocimiento de honorarios": server.build_inmueble_honorarios_ack_pdf_editable(
            EMPRESA, INMUEBLE, COMPRADOR, ACCION),
        "ficha catastral": server.build_inmueble_catastro_sheet_pdf(
            EMPRESA, INMUEBLE, {"referencia": "0000000XX0000X0000XX", "uso": "Residencial"}),
    }


class LosDiezDocumentosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = documentos()

    def test_todos_llevan_fuentes_incrustadas(self):
        for nombre, pdf in self.docs.items():
            with self.subTest(documento=nombre):
                fuentes = set()
                for pg in PdfReader(BytesIO(pdf)).pages:
                    fuentes |= set((pg.get("/Resources") or {}).get("/Font") or {})
                self.assertTrue(fuentes, f"«{nombre}» no incrusta ninguna fuente: es una imagen")

    def test_ninguno_es_una_imagen_a_pagina_completa(self):
        for nombre, pdf in self.docs.items():
            with self.subTest(documento=nombre):
                for pg in PdfReader(BytesIO(pdf)).pages:
                    for _, xo in ((pg.get("/Resources") or {}).get("/XObject") or {}).items():
                        obj = xo.get_object()
                        if obj.get("/Subtype") != "/Image":
                            continue
                        self.assertLess(
                            int(obj.get("/Width") or 0), 900,
                            f"«{nombre}» lleva una imagen de página entera: se está rasterizando",
                        )

    def test_se_puede_buscar_el_texto_dentro(self):
        for nombre, pdf in self.docs.items():
            with self.subTest(documento=nombre):
                texto = "\n".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(pdf)).pages)
                self.assertGreater(len(texto.strip()), 100, f"«{nombre}» no tiene texto extraíble")

    def test_la_direccion_del_inmueble_se_puede_encontrar(self):
        """Lo que de verdad se busca en estos documentos es la dirección.

        Las fichas informativas la escriben en mayúsculas, así que se compara sin
        distinguir caja.
        """
        for nombre, pdf in self.docs.items():
            with self.subTest(documento=nombre):
                texto = "\n".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(pdf)).pages)
                self.assertIn("calle de la prueba 3", texto.replace("\n", " ").lower())

    def test_no_se_cuela_la_tupla_de_python_en_crudo(self):
        """Las fichas pasan las filas como pares (etiqueta, valor).

        El motor de imagen las unía con dos puntos y el de texto hacía `str()`, así
        que la ficha catastral salía con `('Dirección CRM', 'Calle...')` impreso.
        """
        for nombre, pdf in self.docs.items():
            with self.subTest(documento=nombre):
                texto = "\n".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(pdf)).pages)
                sueltas = [l for l in texto.split("\n") if l.strip().startswith("('")]
                self.assertEqual(sueltas, [], f"«{nombre}» imprime tuplas en crudo: {sueltas[:2]}")

    def test_la_nota_de_encargo_pesa_lo_que_pesa_un_texto(self):
        # Eran 617 kB de mapa de bits. Un contrato de dos páginas no llega a 100 kB.
        self.assertLess(len(self.docs["nota de encargo"]), 100_000)


class ElReconocimientoDeHonorariosTests(unittest.TestCase):
    """Se anuncia como editable (AcroForm) y salía con cero campos.

    `form.textfield()` recibía IBMPlexSans, que el formato no admite en formularios;
    lanzaba en todos los campos y un `except: pass` se lo tragaba. Resultado: cuatro
    recuadros vacíos, sin los datos y sin poder escribir en ellos.
    """

    def setUp(self):
        self.pdf = server.build_inmueble_honorarios_ack_pdf_editable(
            EMPRESA, INMUEBLE, COMPRADOR, ACCION)

    def test_tiene_campos_rellenables(self):
        campos = PdfReader(BytesIO(self.pdf)).get_fields() or {}
        self.assertGreater(len(campos), 5, "el PDF «editable» no trae ningún campo")

    def test_los_campos_vienen_con_los_datos_del_expediente(self):
        campos = PdfReader(BytesIO(self.pdf)).get_fields() or {}
        valores = " · ".join(str(c.get("/V") or "") for c in campos.values())
        self.assertIn("Calle de la Prueba 3", valores)
        self.assertIn("Comprador Uno", valores)

    def test_la_casilla_del_importe_no_se_cae_por_el_simbolo_del_euro(self):
        """Un importe con «€» lanzaba `KeyError: 8364` y perdía el campo entero."""
        campos = PdfReader(BytesIO(self.pdf)).get_fields() or {}
        self.assertIn("propuesta_importe", campos)
        self.assertIn("120", str(campos["propuesta_importe"].get("/V") or ""))


class ElPieDeFirmasTests(unittest.TestCase):
    """Las dos firmas iban alineadas con tiradas de espacios.

    El motor de texto parte por palabras y las colapsa, así que «Por el
    Intermediario» y «Por el cliente/Representante» acababan pegados en una misma
    línea y no se distinguía dónde firmaba cada parte.
    """

    def test_las_dos_columnas_se_separan(self):
        from web.document_pdf import _texto_corrido_a_secciones

        secciones = _texto_corrido_a_secciones([
            "Un párrafo normal y corriente.",
            "Por el Intermediario                    Por el cliente/Representante",
            "Nombre y Apellidos                      Nombre y Apellidos",
        ])
        columnas = [c for _, c in secciones if isinstance(c, dict) and c.get("kind") == "columns"]
        self.assertEqual(len(columnas), 1, "el pie de firmas no se reconoce como dos columnas")
        self.assertEqual(
            columnas[0]["items"],
            [["Por el Intermediario", "Por el cliente/Representante"],
             ["Nombre y Apellidos", "Nombre y Apellidos"]],
        )

    def test_el_texto_normal_no_se_parte_en_columnas(self):
        from web.document_pdf import _texto_corrido_a_secciones

        secciones = _texto_corrido_a_secciones(["Una frase con un solo espacio entre palabras."])
        self.assertFalse([c for _, c in secciones if isinstance(c, dict)])

    def test_el_salto_de_pagina_se_respeta(self):
        from web.document_pdf import _texto_corrido_a_secciones

        secciones = _texto_corrido_a_secciones(["antes", "__PAGE_BREAK__", "después"])
        clases = [c.get("kind") for _, c in secciones if isinstance(c, dict)]
        self.assertIn("page_break", clases)


if __name__ == "__main__":
    unittest.main()
