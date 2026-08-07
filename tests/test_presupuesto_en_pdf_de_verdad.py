"""El presupuesto deja de ser una fotografía del presupuesto.

Auditando el CRM de fincas el 2026-08-07 generé un presupuesto real de producción y
lo abrí: las tres páginas eran **un único JPEG cada una**, 1240×1754 px, sin una sola
fuente incrustada. El documento que se le manda al presidente de una comunidad no se
podía buscar ni copiar, salía blando al imprimir —150 ppp, cuando la imprenta pide
300— y pesaba 391 kB.

Se dibujaba con PIL y se guardaba con `pages[0].save(..., format="PDF",
resolution=150.0)`. El motor viejo se conserva como `build_workspace_budget_pdf_imagen`
por si hubiera que volver.

Y había un problema de contenido peor que el técnico: **en ninguna parte decía que la
cuota fuera mensual**. El presupuesto de 177 viviendas ponía «Total 1.523,39 €» y se
acabó. Entendido como pago único en vez de como cuota, son 18.000 € de diferencia al
año. Desde que la tarifa admite trabajos de una sola vez, además, sumarlos a la cuota
en el mismo total sería directamente incorrecto: van en su propia tabla.
"""

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))

try:
    from web import server
    from pypdf import PdfReader

    LISTO = True
except Exception:  # pragma: no cover
    LISTO = False


WORKSPACE = {"nombre": "Fincas Velázquez", "primary_color": "#3C6E71"}
COMPANY = {"nombre": "Estudio Velazquez 2012 SL", "razon_social": "Estudio Velazquez 2012 SL"}
CLIENTE = {"nombre": "C.P. Ejemplo", "nif": "", "telefono": "", "email": ""}


def presupuesto(**extra):
    calc = {
        "num_vecinos": 24,
        "num_locales": 0,
        "num_trasteros": 30,
        "num_aparcamientos": 0,
        "comunidad_denominacion": "C.P. Ejemplo",
        "comunidad_direccion": "Calle de Prueba 1",
        "servicios_incluidos": ["Gestión de incidencias", "Junta ordinaria anual"],
    }
    calc.update(extra.pop("calc", {}))
    base = {
        "id": "x", "servicio": "fincas", "titulo": "Administración de comunidad · C.P. Ejemplo",
        "fecha": "2026-08-07", "subtotal": 150.0, "impuestos": 31.5, "total": 181.5,
        "calculo_json": json.dumps(calc),
    }
    base.update(extra)
    return base


LINEAS_MENSUALES = [
    {"categoria": "Edificio", "concepto": "Por vivienda (5,00 €/unidad)", "cantidad": 24,
     "unidad": "vivienda", "precio_unitario": 5, "total_linea": 120},
    {"categoria": "Edificio", "concepto": "Por trastero (1,00 €/unidad)", "cantidad": 30,
     "unidad": "trastero", "precio_unitario": 1, "total_linea": 30},
]
LINEA_PUNTUAL = {"categoria": "Servicios puntuales", "concepto": "Constitución / alta de la comunidad",
                 "cantidad": 1, "unidad": "servicio", "precio_unitario": 350, "total_linea": 350}


def genera(lineas=None, **extra):
    pdf = server.build_workspace_budget_pdf(
        presupuesto(**extra), WORKSPACE, COMPANY, CLIENTE, lineas if lineas is not None else LINEAS_MENSUALES
    )
    lector = PdfReader(__import__("io").BytesIO(pdf))
    texto = "\n".join((p.extract_text() or "") for p in lector.pages)
    return pdf, lector, texto


@unittest.skipUnless(LISTO, "hace falta poder importar web.server y pypdf")
class YaNoEsUnaFotografiaTests(unittest.TestCase):
    def test_las_paginas_llevan_fuentes(self):
        _pdf, lector, _t = genera()
        for n, pagina in enumerate(lector.pages, 1):
            with self.subTest(pagina=n):
                fuentes = (pagina.get("/Resources", {}) or {}).get("/Font") or {}
                self.assertTrue(list(fuentes), "la página no tiene fuentes: se dibujó como imagen")

    def test_el_texto_se_puede_copiar(self):
        _pdf, _l, texto = genera()
        self.assertGreater(len(texto), 400, "no hay texto extraíble")
        self.assertIn("C.P. Ejemplo", texto)

    def test_no_hay_una_imagen_a_pagina_completa(self):
        """Una imagen de 1240×1754 es la página entera rasterizada."""
        _pdf, lector, _t = genera()
        for pagina in lector.pages:
            for objeto in ((pagina.get("/Resources", {}) or {}).get("/XObject") or {}).values():
                datos = objeto.get_object()
                if datos.get("/Subtype") == "/Image":
                    self.assertNotEqual(
                        (datos.get("/Width"), datos.get("/Height")), (1240, 1754),
                        "la página sigue siendo un JPEG de la página",
                    )

    def test_pesa_lo_que_pesa_un_documento_de_texto(self):
        pdf, _l, _t = genera()
        self.assertLess(len(pdf), 120_000, "sin fotos, un presupuesto no debería pasar de unos 100 kB")

    def test_el_motor_viejo_sigue_disponible(self):
        self.assertIn("def build_workspace_budget_pdf_imagen(", SERVER)


@unittest.skipUnless(LISTO, "hace falta poder importar web.server y pypdf")
class DiceLoQueCuestaYCadaCuantoTests(unittest.TestCase):
    def test_dice_que_la_cuota_es_mensual(self):
        _pdf, _l, texto = genera()
        self.assertIn("mensual", texto.lower())

    def test_el_importe_grande_lleva_su_periodicidad(self):
        _pdf, _l, texto = genera()
        self.assertIn("CUOTA MENSUAL", texto.upper())

    def test_lo_puntual_no_se_suma_a_la_cuota(self):
        """350 € de alta no pueden engordar la cuota de todos los meses."""
        _pdf, _l, texto = genera(lineas=LINEAS_MENSUALES + [LINEA_PUNTUAL])
        self.assertIn("Servicios puntuales", texto)
        self.assertIn("PAGO ÚNICO", texto.upper())
        # La cuota sigue siendo la de 150 € de base, no 500 €.
        self.assertIn("181,50", texto)

    def test_sin_puntuales_no_aparece_esa_tabla(self):
        _pdf, _l, texto = genera()
        self.assertNotIn("Servicios puntuales", texto)

    def test_los_trasteros_salen_en_el_desglose(self):
        _pdf, _l, texto = genera()
        self.assertIn("trastero", texto.lower())


@unittest.skipUnless(LISTO, "hace falta poder importar web.server y pypdf")
class LaPresentacionTests(unittest.TestCase):
    def test_los_campos_vacios_se_esconden(self):
        """Una ficha llena de «NIF: -» parece un documento a medio hacer."""
        _pdf, _l, texto = genera()
        self.assertNotIn("NIF: -", texto)
        self.assertNotIn("Email: -", texto)
        self.assertNotIn("Teléfono: -", texto)

    def test_la_fecha_va_en_castellano(self):
        _pdf, _l, texto = genera()
        self.assertIn("7 de agosto de 2026", texto)
        self.assertNotIn("2026-08-07", texto)

    def test_no_se_usan_emojis_de_iconos(self):
        """Eran cuatro PNG de emoji pegados como iconos del bloque de unidades."""
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertNotIn("emoji/", cuerpo)

    def test_no_se_pinta_un_mapa_falso(self):
        """El bloque del mapa era un recuadro gris que decía «sin conexión»."""
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertNotIn("Vista previa", cuerpo)
        self.assertNotIn("MAPA", cuerpo)

    def test_lleva_la_marca_de_fincas_y_el_sello_del_colegio(self):
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("logos/fincas-velazquez.png", cuerpo)
        self.assertIn("logos/colegio-administradores-v2.png", cuerpo)

    def test_usa_el_color_del_workspace(self):
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('brand_color=workspace.get("primary_color")', cuerpo)


@unittest.skipUnless(LISTO, "hace falta poder importar web.server y pypdf")
class ElMotorVectorialAguantaLoQueSeLePideTests(unittest.TestCase):
    def test_una_foto_no_se_guarda_en_png(self):
        """Guardar la foto del equipo en PNG subía el presupuesto de 33 kB a 3,3 MB."""
        from PIL import Image

        from web.branded_pdf_vector import _imagen_pil

        opaca = Image.new("RGBA", (600, 400), (120, 130, 140, 255))
        lector, ancho, alto = _imagen_pil(opaca)
        self.assertEqual((ancho, alto), (600, 400))
        # Un JPEG de un color plano cabe de sobra; el PNG equivalente también, así que
        # se comprueba el formato de verdad, no el tamaño.
        self.assertEqual(lector.fileName.getvalue()[:2], b"\xff\xd8", "una foto opaca debe ir en JPEG")

    def test_un_logo_con_transparencia_sigue_en_png(self):
        from PIL import Image

        from web.branded_pdf_vector import _imagen_pil

        con_alfa = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
        lector, _a, _b = _imagen_pil(con_alfa)
        self.assertEqual(lector.fileName.getvalue()[:4], b"\x89PNG", "un logo transparente debe ir en PNG")

    def test_la_tabla_reparte_el_ancho_por_proporciones(self):
        fuente = (RAIZ / "web" / "branded_pdf_vector.py").read_text(encoding="utf-8")
        self.assertIn("def _tabla(", fuente)
        self.assertIn("anchos = [ancho_util * (p / total_peso) for p in pesos]", fuente)

    def test_la_tabla_repite_cabecera_al_cambiar_de_pagina(self):
        fuente = (RAIZ / "web" / "branded_pdf_vector.py").read_text(encoding="utf-8")
        self.assertIn("if lienzo.pagina != pagina_tabla:", fuente)


if __name__ == "__main__":
    unittest.main()
