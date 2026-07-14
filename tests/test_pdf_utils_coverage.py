import unittest

from PIL import Image, ImageDraw

from web import pdf_utils


class PdfUtilsCoverageTests(unittest.TestCase):
    def test_brand_lookup_number_and_color_helpers(self):
        brand = pdf_utils.resolve_hipoteca_bank_brand("Santander Consumer Finance")
        self.assertEqual(brand["display_name"], "Banco Santander")
        self.assertEqual(pdf_utils.resolve_hipoteca_bank_brand("santander consumer")["display_name"], "Banco Santander")
        fallback = pdf_utils.resolve_hipoteca_bank_brand("Banco Prueba")
        self.assertEqual(fallback["short"], "BP")
        self.assertEqual(fallback["display_name"], "Banco Prueba")
        self.assertEqual(pdf_utils.build_hipoteca_bank_logo_meta("Banco Sabadell")["logo_label"], "Banco Sabadell")
        self.assertEqual(pdf_utils.normalize_hipoteca_pdf_sort_order("ASCENDENTE"), "asc")
        self.assertEqual(pdf_utils.normalize_hipoteca_pdf_sort_order("desconocido"), "desc")
        self.assertEqual(pdf_utils._parse_money_value("1.234,56"), 1234.56)
        self.assertEqual(pdf_utils._parse_money_value("1.234.567"), 1234567.0)
        self.assertEqual(pdf_utils._pdf_format_number(1234.5), "1.234,50")
        self.assertEqual(pdf_utils._parse_pdf_color("#abc"), (170, 187, 204))
        self.assertEqual(pdf_utils._parse_pdf_color("bad", fallback=(1, 2, 3)), (1, 2, 3))

    def test_wrap_justify_and_multiline_helpers(self):
        image = Image.new("RGB", (800, 400), "white")
        draw = ImageDraw.Draw(image)
        font = pdf_utils._document_font(12)

        wrapped = pdf_utils._pdf_wrap_lines("Uno dos tres cuatro cinco", width=6)
        self.assertGreater(len(wrapped), 1)

        px_wrapped = pdf_utils._pdf_wrap_lines_px(draw, "Banco Santander Modernia", font, 120)
        self.assertGreaterEqual(len(px_wrapped), 2)

        next_y = pdf_utils._pdf_draw_justified_paragraph(
            draw,
            10,
            10,
            180,
            "Texto largo para justificar en varias líneas",
            font,
            fill=(0, 0, 0),
        )
        self.assertGreater(next_y, 10)

        lines, line_height, total_height = pdf_utils._pil_multiline(draw, "Linea 1\nLinea 2", font, width=12, line_gap=4)
        self.assertEqual(lines, ["Linea 1", "Linea 2"])
        self.assertGreaterEqual(total_height, line_height * 2)

    def test_logo_badge_info_and_image_builder(self):
        self.assertEqual(pdf_utils._logo_badge_info_from_path("/assets/logos/santander.svg")["label"], "Banco Santander")
        self.assertEqual(pdf_utils._logo_badge_info_from_path("/tmp/grupo_modernia_logo.png")["label"], "Grupo Modernia")
        self.assertEqual(pdf_utils._logo_badge_info_from_path("/tmp/verifika2_wordmark.png")["label"], "Verifika²")
        badge = pdf_utils._build_logo_badge_image("Demo Bank", color="#123456", short="DB", logo_on_dark=False, max_width=200)
        self.assertGreater(badge.width, 0)
        self.assertGreater(badge.height, 0)
