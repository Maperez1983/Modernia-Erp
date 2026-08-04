"""El listado en Excel lleva el logo de cada entidad.

Excel no admite SVG y nueve de los doce logos del catálogo lo son, así que no se
pueden incrustar tal cual. Se rasterizan **una vez** a PNG en
`assets/logos/excel/` y el servidor solo los pega: así no hace falta un
rasterizador instalado en producción, que es lo que habría exigido convertirlos al
vuelo.

Detalles que se comprobaron mirando el resultado, no suponiéndolo:

- Con la columna a 27 caracteres el logo se comía la primera letra de "Caja Rural
  de Granada". Con 34 caben el logo (unos 11) y el nombre más largo (21).
- Tres logos vienen en negativo —tinta blanca sobre fondo oscuro— y sobre blanco
  desaparecen. Intenté detectarlos midiendo el contraste y salió peor: bajando el
  umbral lo justo para cazar a Caja Rural del Sur, CaixaBank y UCI acababan sobre
  un fondo de color donde se leían peor que antes. Con doce logos, mirarlos uno a
  uno y dejar la excepción escrita es más honesto que una heurística que falla.

El nombre se conserva junto al logo: la columna sigue sirviendo para filtrar y
buscar, que es para lo que se usa una hoja de cálculo.
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
LOGOS = RAIZ / "assets" / "logos" / "excel"

try:
    import sys

    sys.path.insert(0, str(RAIZ))
    from web import pdf_utils, server
    from openpyxl import Workbook

    LISTO = True
except Exception:  # pragma: no cover
    LISTO = False


class LosPngExistenTests(unittest.TestCase):
    def test_hay_un_png_por_cada_marca_del_catalogo(self):
        self.assertTrue(LOGOS.is_dir(), "falta assets/logos/excel/")
        if not LISTO:
            self.skipTest("no se pudo importar web.pdf_utils")
        faltan = []
        for marca in pdf_utils.HIPOTECA_BANK_BRANDS:
            nombre = Path(str(marca.get("logo") or "")).stem
            if nombre and not (LOGOS / f"{nombre}.png").exists():
                faltan.append(nombre)
        self.assertEqual(faltan, [], "marcas sin PNG para Excel: " + ", ".join(faltan))

    def test_son_pequenos(self):
        """Van uno por fila: un PNG pesado multiplica el tamaño del fichero."""
        gordos = [p.name for p in LOGOS.glob("*.png") if p.stat().st_size > 40_000]
        self.assertEqual(gordos, [], "logos demasiado pesados: " + ", ".join(gordos))


class LaFuncionQueLosPegaTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index("def add_logos_de_banco_al_listado")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_existe_y_se_llama_desde_el_listado(self):
        self.assertIn("def add_logos_de_banco_al_listado(", SERVER)
        i = SERVER.index("def build_hipotecas_listado_excel_workbook")
        self.assertIn("add_logos_de_banco_al_listado(detail)", SERVER[i: SERVER.index("\ndef ", i + 10)])

    def test_un_logo_que_falle_no_deja_sin_excel(self):
        cuerpo = self._bloque()
        self.assertIn("except Exception:", cuerpo)
        i = SERVER.index("def build_hipotecas_listado_excel_workbook")
        self.assertIn("except Exception:", SERVER[i: SERVER.index("\ndef ", i + 10)])

    def test_la_columna_deja_sitio_al_logo_y_al_nombre(self):
        self.assertIn("width = 34", self._bloque())

    def test_el_nombre_se_conserva(self):
        """Si se sustituyera por el logo, la columna dejaría de servir para filtrar."""
        cuerpo = self._bloque()
        self.assertNotIn("celda.value = None", cuerpo)
        self.assertNotIn('celda.value = ""', cuerpo)


@unittest.skipUnless(LISTO, "hace falta openpyxl y poder importar web.server")
class SobreDatosDeVerdadTests(unittest.TestCase):
    def test_pega_un_logo_por_operacion_reconocida(self):
        items = [
            {"anio": "2026", "fecha_firma": "2026-01-15", "cliente": "A", "banco": "Banco Santander",
             "importe_hipoteca": 100000, "honorarios": 3000},
            {"anio": "2026", "fecha_firma": "2026-02-20", "cliente": "B", "banco": "Caja Rural de Granada",
             "importe_hipoteca": 200000, "honorarios": 4000},
            {"anio": "2026", "fecha_firma": "2026-03-01", "cliente": "C", "banco": "Banco Inventado SA",
             "importe_hipoteca": 50000, "honorarios": 1000},
        ]
        wb = server.build_hipotecas_listado_excel_workbook(items, "2026", brand_name="X")
        hoja = wb["Operaciones listado"]
        # El banco inventado no tiene logo, así que son dos, no tres.
        self.assertEqual(len(hoja._images), 2)

    def test_sin_columna_de_banco_no_revienta(self):
        hoja = Workbook().active
        hoja["A1"] = "Otra cosa"
        self.assertEqual(server.add_logos_de_banco_al_listado(hoja), 0)


if __name__ == "__main__":
    unittest.main()
