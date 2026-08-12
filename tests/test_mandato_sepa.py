"""La orden de domiciliación SEPA, y que su referencia no discrepe del fichero.

El CRM guardaba `mandato_ref` y `mandato_fecha` y los metía en el `<MndtId>` y el
`<DtOfSgntr>` de la remesa, pero el documento que los origina —el que firma el
propietario y que el acreedor debe custodiar— se hacía fuera y luego se teclaba la
referencia a mano.

Lo que estos tests vigilan sobre todo es una cosa: **el papel y el fichero dicen la
misma referencia**. Si el banco recibe un `MndtId` que no es el del mandato que el
acreedor custodia, devuelve el adeudo. Antes el fichero caía al `vecino_id` crudo
cuando la referencia estaba vacía, y como el papel no existía, nadie podía comprobarlo.

Y una trampa que salió escribiendo esto: `referencia_mandato` recibe tanto la ficha del
propietario —donde su id es `id`— como la fila del recibo, donde `id` es el del recibo
y el del propietario viene en `vecino_id`. Derivarla del id equivocado daba dos
referencias distintas para el mismo mandato.
"""

import re
import sys
import unittest
from io import BytesIO
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

COMUNIDAD = {
    "id": "c1", "nombre": "C. P Urbanización Barceló Bl4",
    "direccion": "Avenida Europa 108, Málaga",
    "acreedor_sepa": "ES12ZZZH29123456",
    "iban": "ES9121000418450200051332",
}
VECINO = {
    "id": "a1b2c3d4e5f60718293a4b5c", "comunidad_id": "c1",
    "nombre": "ANA PEREZ VILLAMIL", "nif": "25123456X", "piso": "6 C",
    "iban": "ES6621000418401234567891", "mandato_ref": "",
}


def texto_de(vecino=None, comunidad=None):
    from pypdf import PdfReader

    pdf = server.build_mandato_sepa_pdf(
        dict(VECINO, **(vecino or {})),
        dict(COMUNIDAD, **(comunidad or {})),
        workspace={}, company={"nombre": "Fincas Velazquez"},
    )
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


class LaReferenciaEsLaMismaEnElPapelYEnElFicheroTests(unittest.TestCase):
    def test_se_deriva_del_propietario_y_no_cambia(self):
        primera = server.referencia_mandato(VECINO)
        self.assertTrue(primera.startswith("MND-"))
        self.assertEqual(primera, server.referencia_mandato(VECINO))

    def test_la_tecleada_a_mano_manda(self):
        self.assertEqual(server.referencia_mandato(dict(VECINO, mandato_ref="MI-REF-2024")),
                         "MI-REF-2024")

    def test_la_fila_del_recibo_da_la_misma_que_la_del_vecino(self):
        """La trampa: en el recibo `id` es el del recibo, no el del propietario."""
        desde_recibo = server.referencia_mandato(
            {"id": "RECIBO999", "vecino_id": VECINO["id"], "mandato_ref": ""}
        )
        self.assertEqual(desde_recibo, server.referencia_mandato(VECINO))

    def test_cabe_en_el_campo_del_fichero(self):
        """`MndtId` admite 35 caracteres."""
        self.assertLessEqual(len(server.referencia_mandato(VECINO)), 35)
        larga = "X" * 60
        self.assertEqual(len(server.referencia_mandato(dict(VECINO, mandato_ref=larga))), 35)

    def test_el_fichero_usa_el_mismo_ayudante(self):
        i = SERVER.index("def build_remesa_sepa_xml")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("referencia_mandato(recibo)", cuerpo)
        self.assertNotIn("row_value(recibo, 'vecino_id', '')", cuerpo)

    def test_el_documento_imprime_esa_referencia(self):
        self.assertIn(server.referencia_mandato(VECINO), texto_de())


class LoQuePideLaNormativaSepaTests(unittest.TestCase):
    def test_el_texto_legal_va_literal(self):
        texto = texto_de()
        self.assertIn("ocho semanas que siguen a la fecha de adeudo", texto)
        self.assertIn("legitimado al reembolso", texto)

    def test_el_texto_legal_tiene_su_propio_titulo(self):
        """Sin encabezado se leía como una continuación del tipo de pago, y es la
        cláusula que autoriza el adeudo."""
        self.assertIn("Autorización del deudor", texto_de())

    def test_lleva_acreedor_con_su_identificador(self):
        texto = texto_de()
        self.assertIn("Identificador del acreedor: ES12ZZZH29123456", texto)
        self.assertIn("C. P Urbanización Barceló Bl4", texto)

    def test_lleva_deudor_con_nif_y_cuenta(self):
        texto = texto_de()
        self.assertIn("ANA PEREZ VILLAMIL", texto)
        self.assertIn("25123456X", texto)
        self.assertIn("ES66 2100 0418 4012 3456 7891", texto)   # con separación, legible

    def test_marca_pago_recurrente_y_se_ve_cual(self):
        texto = texto_de()
        self.assertIn("[X] Pago recurrente", texto)
        self.assertIn("[ ] Pago único", texto)

    def test_dice_que_hay_que_custodiarla(self):
        self.assertEqual(server.SEPA_MESES_CUSTODIA, 13)
        self.assertIn("custodiar", texto_de())
        self.assertIn("13 meses", texto_de())

    def test_tiene_donde_firmar(self):
        texto = texto_de()
        self.assertIn("Firma del titular de la cuenta", texto)
        self.assertIn("Localidad", texto)


class LoQueNoSeSabeNoSeInventaTests(unittest.TestCase):
    def test_sin_iban_deja_el_hueco(self):
        """Un mandato con un IBAN inventado es un adeudo devuelto."""
        texto = texto_de({"iban": ""})
        self.assertRegex(texto, r"Cuenta de cargo \(IBAN\): _+")

    def test_sin_identificador_de_acreedor_lo_dice(self):
        texto = texto_de(comunidad={"acreedor_sepa": ""})
        self.assertIn("no lo tiene dado de alta", texto)

    def test_sin_nif_deja_el_hueco(self):
        self.assertRegex(texto_de({"nif": ""}), r"NIF: _+")


class SeSirveYSeDescargaTests(unittest.TestCase):
    def test_hay_endpoint_y_pide_pertenencia(self):
        i = SERVER.index('if path == "/api/workspace_fincas_mandato":')
        cuerpo = SERVER[i: SERVER.index("\n        if path ==", i + 10)]
        self.assertIn("enforce_workspace_membership", cuerpo)
        self.assertIn("build_mandato_sepa_pdf", cuerpo)
        self.assertLess(cuerpo.index("enforce_workspace_membership"),
                        cuerpo.index("build_mandato_sepa_pdf"))

    def test_hay_boton_en_la_ficha_del_propietario(self):
        self.assertIn("data-vecino-mandato", APP)
        i = APP.index("[data-vecino-mandato]")
        self.assertIn("/api/workspace_fincas_mandato", APP[i: i + 700])

    def test_avisa_si_el_propietario_no_esta_guardado(self):
        """Sin id no hay referencia que emitir, y emitir una orden con la referencia en
        blanco es peor que no emitirla."""
        i = APP.index("[data-vecino-mandato]")
        self.assertIn("Guarda primero al propietario", APP[i: i + 700])


if __name__ == "__main__":
    unittest.main()
