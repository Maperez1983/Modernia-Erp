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


class NingunaEmpresaLlevaLaMarcaDeOtraTests(unittest.TestCase):
    """Un documento de Estudio Velázquez no puede salir con el logo de Verifika².

    `load_brand_logo` cae siempre al wordmark de Verifika² cuando no puede cargar lo
    que le piden. Cuatro de las nueve empresas guardan su logo en S3 —ANSA, Estudio
    Velázquez, Inmovere Proyect e Inversure—, así que si el bucket no responde su nota
    de encargo saldría con la marca de otra casa encima. Para un contrato que se firma
    eso es peor que no poner nada.

    Ahora, si la empresa tiene logo configurado y no se puede cargar, se dibuja un
    distintivo con **su** nombre. El respaldo neutro se reserva para quien no ha
    configurado ninguno.
    """

    def setUp(self):
        from web import document_pdf as D
        self.D = D
        self.neutro = D._DEPENDENCIES["load_brand_logo"](None, max_width=560)

    def _resuelto(self, nombre, logo_url):
        return self.D._resuelve_logo_de_empresa({"nombre": nombre, "logo_url": logo_url})

    def test_el_logo_propio_se_respeta(self):
        img = self._resuelto("Grupo Modernia", "/assets/grupo_modernia_logo.png")
        self.assertIsNotNone(img)
        self.assertFalse(self.D._es_la_misma_imagen(img, self.neutro))

    def test_si_el_logo_no_carga_sale_su_nombre_y_no_otra_marca(self):
        img = self._resuelto("Estudio Velazquez 2012 SL", "s3://company_logos/no-existe.jpg")
        self.assertIsNotNone(img)
        self.assertFalse(
            self.D._es_la_misma_imagen(img, self.neutro),
            "un documento de esta empresa saldría con el logotipo de Verifika²",
        )

    def test_sin_logo_configurado_se_usa_el_respaldo_neutro(self):
        img = self._resuelto("Inmovere Fincas", "")
        self.assertTrue(self.D._es_la_misma_imagen(img, self.neutro))

    def test_una_empresa_sin_nombre_ni_logo_no_revienta(self):
        self.assertIsNotNone(self.D._resuelve_logo_de_empresa({}))


class LosDosDocumentosQueEranUnEsbozoTests(unittest.TestCase):
    """`web/templates/inmo/` nunca se subió a git y Render despliega desde git, así
    que producción jamás tuvo las cinco plantillas PDF: todo el código de relleno por
    coordenadas está muerto y siempre se emite el documento generado.

    Para las notas de encargo daba igual, porque el generado es un contrato completo.
    Pero la promesa de compraventa —lo que firma un comprador para comprometerse y
    entregar dinero a cuenta— eran tres líneas, y la nota explicativa del precio, dos.
    Las dos llevaban «(fallback)» impreso en la cabecera.
    """

    def texto(self, pdf):
        return "\n".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(pdf)).pages)

    def test_ninguno_anuncia_ser_un_apaño(self):
        for nombre, pdf in documentos().items():
            with self.subTest(documento=nombre):
                self.assertNotIn("fallback", self.texto(pdf).lower())

    def test_la_promesa_de_compraventa_es_un_contrato(self):
        pdf = server.build_inmueble_negotiation_offer_pdf(EMPRESA, INMUEBLE, COMPRADOR, ACCION)
        t = self.texto(pdf)
        for pieza in ("Intervinientes", "Objeto", "Precio y forma de pago",
                      "Arras penitenciales", "Plazos", "Gastos e impuestos", "Firmas"):
            with self.subTest(pieza=pieza):
                self.assertIn(pieza, t)

    def test_la_promesa_cita_los_articulos_en_que_se_apoya(self):
        """1451 (promesa de vender o comprar) y 1454 (arras penitenciales)."""
        t = self.texto(server.build_inmueble_negotiation_offer_pdf(EMPRESA, INMUEBLE, COMPRADOR, ACCION))
        for articulo in ("1451", "1454", "1124", "1504"):
            with self.subTest(articulo=articulo):
                self.assertIn(articulo, t)

    def test_la_promesa_desglosa_senal_arras_y_resto(self):
        pdf = server.build_inmueble_negotiation_offer_pdf(
            EMPRESA, INMUEBLE, COMPRADOR,
            {"importe_propuesta": 200000, "garantia": 3000, "entrega_2": 17000})
        t = self.texto(pdf).replace("\n", " ")
        self.assertIn("3.000,00", t)    # señal
        self.assertIn("17.000,00", t)   # arras
        self.assertIn("180.000,00", t)  # resto: 200.000 - 3.000 - 17.000

    def test_la_nota_de_precio_recorre_las_cinco_letras_del_articulo_8(self):
        """Decreto 218/2005 art. 8, «Nota explicativa en la venta de viviendas sobre
        el precio y las formas de pago»: precio con tributos y gastos, aplazamientos,
        subrogación hipotecaria, validez, y lugar/fecha/firma."""
        t = self.texto(server.build_inmueble_consumo_sale_price_note_pdf(EMPRESA, INMUEBLE, {}))
        for letra in ("a) Precio de venta", "b) Aplazamientos de pago",
                      "c) Subrogación en préstamo hipotecario", "d) Validez de esta nota",
                      "e) Lugar, fecha y firma"):
            with self.subTest(letra=letra):
                self.assertIn(letra, t)
        self.assertIn("218/2005", t)

    def test_lo_que_falta_queda_como_hueco_para_rellenar(self):
        """Un documento que se imprime y se firma no puede decir «PARTE VENDEDORA:
        Pendiente»: ni se entiende ni se puede completar a mano."""
        pdf = server.build_inmueble_negotiation_offer_pdf(EMPRESA, INMUEBLE, COMPRADOR, {})
        t = self.texto(pdf)
        self.assertIn("PARTE VENDEDORA", t)
        self.assertNotIn("PARTE VENDEDORA: Pendiente", t.replace("\n", " "))


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
