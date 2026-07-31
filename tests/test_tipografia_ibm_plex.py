"""Una sola tipografía en todo el sistema: IBM Plex.

Había seis familias sin relación entre sí, repartidas por cinco sitios:

  - pantalla: Source Sans 3 (texto), Playfair Display (títulos), Space Grotesk (interfaz)
  - vistas de impresión: Inter y la fuente del sistema
  - páginas y correos del servidor: Avenir Next y la fuente del sistema
  - PDF: Helvetica, la incrustada en reportlab
  - documentos dibujados como imagen: la del sistema — Arial en un Mac,
    DejaVu Sans en el servidor, así que el mismo documento no salía igual
    según dónde se generara

Se conservan los tres papeles de la hoja de estilos (texto, títulos, interfaz)
porque marcan la jerarquía y están usados en ~90 sitios, pero los tres salen ya
de la misma superfamilia.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

# Las que había antes. Ninguna puede volver.
FAMILIAS_RETIRADAS = (
    "Source Sans 3", "Playfair Display", "Space Grotesk",
    "Avenir Next", "Inter,", "Roboto",
)


class LaPantallaTests(unittest.TestCase):
    def test_las_tres_variables_son_ibm_plex(self):
        for variable in ("--font-body", "--font-display", "--font-ui"):
            with self.subTest(variable=variable):
                linea = re.search(rf"{variable}:([^;]+);", CSS)
                self.assertIsNotNone(linea, f"falta {variable}")
                self.assertIn("IBM Plex", linea.group(1))

    def test_los_titulos_conservan_la_serif(self):
        # Sin esto la jerarquía se aplana: los títulos dejan de distinguirse.
        self.assertIn('--font-display: "IBM Plex Serif"', CSS)

    def test_el_texto_de_codigo_no_usa_la_monospace_del_navegador(self):
        """`code` y `pre` no tenían estilo.

        Salían con la monospace por defecto de cada navegador —Menlo, Consolas,
        DejaVu Sans Mono— y se ven en la pantalla de importación de gestoría.
        """
        self.assertIn('--font-mono: "IBM Plex Mono"', CSS)
        bloque = CSS[CSS.index("code,\npre,"):]
        self.assertIn("font-family: var(--font-mono);", bloque)
        self.assertIn("family=IBM+Plex+Mono", HTML)

    def test_no_queda_ninguna_familia_suelta_en_la_hoja_de_estilos(self):
        sueltas = [l for l in re.findall(r"font-family:[^;}]+", CSS) if "var(--font" not in l]
        self.assertEqual(sueltas, [], f"font-family sin variable: {sueltas}")

    def test_se_cargan_las_dos_familias(self):
        self.assertIn("family=IBM+Plex+Sans", HTML)
        self.assertIn("family=IBM+Plex+Serif", HTML)

    def test_no_se_descargan_las_viejas(self):
        for familia in ("Playfair+Display", "Source+Sans+3", "Space+Grotesk"):
            with self.subTest(familia=familia):
                self.assertNotIn(familia, HTML)


class LasVistasDeImpresionYLosCorreosTests(unittest.TestCase):
    """Se veían distintas en cada ordenador por depender de la fuente del sistema."""

    def test_ninguna_familia_retirada_en_el_cliente(self):
        for familia in FAMILIAS_RETIRADAS:
            with self.subTest(familia=familia):
                self.assertNotIn(f"font-family:{familia}", APP.replace(" ", ""))

    def test_toda_declaracion_de_fuente_del_cliente_es_ibm_plex(self):
        for decl in re.findall(r"font-family[:=]\s*([^;}]+)", APP):
            with self.subTest(decl=decl.strip()[:40]):
                self.assertIn("IBM Plex", decl)

    def test_toda_declaracion_de_fuente_del_servidor_es_ibm_plex(self):
        for decl in re.findall(r"font-family:\s*([^;}]+)", SERVER):
            with self.subTest(decl=decl.strip()[:40]):
                self.assertIn("IBM Plex", decl)


class LosDocumentosGeneradosTests(unittest.TestCase):
    def test_no_queda_helvetica_escrita_a_mano(self):
        for fichero in ("server.py", "document_pdf.py"):
            texto = (RAIZ / "web" / fichero).read_text(encoding="utf-8")
            with self.subTest(fichero=fichero):
                self.assertNotIn("Helvetica", texto)

    def test_las_fuentes_viajan_con_el_repositorio(self):
        # Render no tiene IBM Plex instalada; si no van en el repo, no hay fuente.
        for fichero in ("IBMPlexSans-Regular.ttf", "IBMPlexSans-Bold.ttf"):
            with self.subTest(fichero=fichero):
                self.assertTrue((RAIZ / "web" / "assets" / "fonts" / fichero).is_file())

    def test_se_registran_y_quedan_activas(self):
        from web import pdf_fonts
        self.assertTrue(pdf_fonts.PDF_FONTS_OK)
        self.assertEqual(pdf_fonts.PDF_FONT_REGULAR, "IBMPlexSans")
        self.assertEqual(pdf_fonts.PDF_FONT_BOLD, "IBMPlexSans-Bold")

    def test_si_faltan_los_ficheros_se_sigue_generando(self):
        # Un documento con la fuente equivocada es mejor que un documento que no sale.
        from web import pdf_fonts
        self.assertIn('return _FALLBACK_REGULAR, _FALLBACK_BOLD', (RAIZ / "web" / "pdf_fonts.py").read_text(encoding="utf-8"))
        self.assertEqual(pdf_fonts._FALLBACK_REGULAR, "Helvetica")

    def test_la_fuente_por_defecto_del_lienzo_tambien(self):
        # Sin esto, lo que se dibuje sin fijar fuente sale en Helvetica.
        from reportlab import rl_config
        from web import pdf_fonts  # noqa: F401  (registra al importarse)
        self.assertEqual(rl_config.canvas_basefontname, "IBMPlexSans")

    def test_los_documentos_imagen_dejan_de_usar_la_fuente_del_sistema(self):
        utils = (RAIZ / "web" / "pdf_utils.py").read_text(encoding="utf-8")
        i = utils.index("def _document_font")
        bloque = utils[i: utils.index("\ndef ", i + 10)]
        self.assertIn("font_path(", bloque)
        # IBM Plex tiene que ir la primera; las del sistema quedan de respaldo.
        # Se comparan las rutas, no los nombres: el comentario de arriba nombra Arial.
        self.assertLess(
            bloque.index("candidates.append(str(plex))"),
            bloque.index("/System/Library/Fonts/Supplemental/Arial"),
        )

    def test_el_pdf_generado_solo_lleva_ibm_plex(self):
        from web.document_pdf import build_signature_evidence_pdf
        datos = build_signature_evidence_pdf(
            {"id": "x", "titulo": "Prueba", "cliente_nombre": "Quien Sea", "estado": "firmado"},
            {"firmado_en": "2026-07-31 12:00", "ip": "10.0.0.1", "navegador": "Firefox"},
        )
        crudo = datos if isinstance(datos, (bytes, bytearray)) else datos.getvalue()
        fuentes = {f.decode() for f in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-]+)", crudo)}
        self.assertTrue(fuentes, "el PDF no declara ninguna fuente")
        for fuente in fuentes:
            with self.subTest(fuente=fuente):
                self.assertIn("IBMPlex", fuente)


if __name__ == "__main__":
    unittest.main()
