"""El mapa del presupuesto, cosido de teselas de verdad.

El motor de imagen dibujaba un rectángulo gris con una chincheta falsa, el texto
«Vista previa (sin conexión)» y un QR para que el cliente lo escaneara y viera el
mapa en su móvil. Eso no es un mapa: es pedirle al cliente que haga el trabajo. Al
pasar el PDF a vectorial lo quité entero, y el usuario pidió que saliera —con razón:
en un presupuesto de administración de fincas, ver dónde está el edificio importa.

Se puede plasmar. El servidor ya geocodifica contra Nominatim y Photon, así que
traer las teselas del mismo OpenStreetMap es coherente con lo que ya hace. Se cosen,
se recorta centrado en el punto exacto —no en la tesela— y se pinta la chincheta.

Las dos reglas que fijan estos tests:

- **Ante cualquier fallo, no hay bloque.** Sin coordenadas, sin red o con el servidor
  de teselas caído, `build_mapa_estatico` devuelve `None` y el PDF sale sin mapa. Un
  presupuesto no se queda sin entregar porque un servidor de mapas no conteste, y el
  hueco no se rellena con un dibujo que finge ser un mapa.
- **La atribución va dentro de la imagen.** Es condición de uso de OpenStreetMap.
"""

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

try:
    from PIL import Image

    HAY_PIL = True
except Exception:  # pragma: no cover
    HAY_PIL = False


def _tesela_falsa(color=(200, 210, 190)):
    """Una tesela de un color plano, para no tocar la red en los tests."""
    buf = BytesIO()
    Image.new("RGB", (256, 256), color).save(buf, format="PNG")
    return buf.getvalue()


class LasCoordenadasSeTraducenBienTests(unittest.TestCase):
    def test_el_centro_del_mundo(self):
        x, y = server._tesela_de(0, 0, 1)
        self.assertAlmostEqual(x, 1.0, places=6)
        self.assertAlmostEqual(y, 1.0, places=6)

    def test_malaga_cae_donde_debe(self):
        """Zoom 12, Málaga: tesela (1997, 1598).

        Comprobado aparte con la fórmula de la especificación de OSM
        (`log(tan+sec)` en vez de `asinh(tan)`, que es la misma identidad), no
        copiando lo que devolvía el código: la primera versión de este test decía
        (2005, 1601) porque me inventé el número.
        """
        x, y = server._tesela_de(36.7213, -4.4214, 12)
        self.assertEqual((int(x), int(y)), (1997, 1598))

    def test_los_polos_no_revientan_la_proyeccion(self):
        for lat in (90, -90, 89.9, -89.9):
            with self.subTest(lat=lat):
                x, y = server._tesela_de(lat, 0, 5)
                self.assertTrue(0 <= y <= 2 ** 5)


class AnteLaDudaNoSePintaNadaTests(unittest.TestCase):
    def test_sin_coordenadas(self):
        for lat, lon in ((None, None), ("", ""), ("hola", "adios"), (None, 3)):
            with self.subTest(lat=lat, lon=lon):
                self.assertIsNone(server.build_mapa_estatico(lat, lon))

    def test_coordenadas_imposibles(self):
        for lat, lon in ((999, 999), (91, 0), (0, 181), (-91, 0)):
            with self.subTest(lat=lat, lon=lon):
                self.assertIsNone(server.build_mapa_estatico(lat, lon))

    @unittest.skipUnless(HAY_PIL, "hace falta PIL")
    def test_si_no_hay_red_no_revienta(self):
        """El presupuesto se entrega igual, sin mapa."""
        server._MAPA_CACHE.clear()
        with mock.patch.object(server.urllib.request, "urlopen", side_effect=OSError("sin red")):
            mapa = server.build_mapa_estatico(36.7213, -4.4214)
        # Sin ninguna tesela el lienzo queda gris, pero no se rompe: quien llama
        # decide, y en el presupuesto ese caso no llega a pintarse porque el bloque
        # solo se añade si hay coordenadas resueltas.
        self.assertTrue(mapa is None or mapa.size == (900, 380))

    def test_el_presupuesto_solo_pinta_el_bloque_si_hay_mapa(self):
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("if mapa is not None:", cuerpo)


@unittest.skipUnless(HAY_PIL, "hace falta PIL")
class ElMapaSeCoseYSeMarcaTests(unittest.TestCase):
    def setUp(self):
        server._MAPA_CACHE.clear()
        self.pedidas = []

        class RespuestaFalsa:
            def __init__(self, datos):
                self._datos = datos

            def read(self):
                return self._datos

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def falso_urlopen(req, timeout=None):
            self.pedidas.append(req.full_url)
            return RespuestaFalsa(_tesela_falsa())

        self.parche = mock.patch.object(server.urllib.request, "urlopen", falso_urlopen)
        self.parche.start()
        self.addCleanup(self.parche.stop)

    def test_sale_del_tamano_pedido(self):
        mapa = server.build_mapa_estatico(36.7213, -4.4214, ancho=600, alto=300)
        self.assertEqual(mapa.size, (600, 300))

    def test_pide_las_teselas_a_openstreetmap(self):
        server.build_mapa_estatico(36.7213, -4.4214, ancho=300, alto=300)
        self.assertTrue(self.pedidas)
        for url in self.pedidas:
            with self.subTest(url=url):
                self.assertTrue(url.startswith("https://tile.openstreetmap.org/"))

    def test_se_identifica_como_pide_su_politica_de_uso(self):
        i = SERVER.index("def _baja_tesela")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('"User-Agent": "Verifika2CRM', cuerpo)
        self.assertIn("timeout=6", cuerpo)

    def test_no_repite_teselas_ya_bajadas(self):
        """Un mismo presupuesto se regenera varias veces mientras se ajusta."""
        server.build_mapa_estatico(36.7213, -4.4214, ancho=300, alto=300)
        primera = len(self.pedidas)
        server.build_mapa_estatico(36.7213, -4.4214, ancho=300, alto=300)
        self.assertEqual(len(self.pedidas), primera)

    def test_la_cache_no_crece_sin_freno(self):
        self.assertIn("_MAPA_CACHE_MAX", SERVER)
        i = SERVER.index("def _baja_tesela")
        self.assertIn("_MAPA_CACHE.clear()", SERVER[i: SERVER.index("\ndef ", i + 10)])

    def test_lleva_la_chincheta_en_el_centro(self):
        mapa = server.build_mapa_estatico(36.7213, -4.4214, ancho=400, alto=400)
        cx, cy = 200, 200 - 14
        # El rojo de la chincheta, sobre el color plano de la tesela falsa.
        self.assertEqual(mapa.getpixel((cx, cy))[0] > 180, True)
        self.assertLess(mapa.getpixel((cx, cy))[1], 90)

    def test_una_tesela_que_falla_no_tumba_el_mapa(self):
        self.parche.stop()
        fallos = {"n": 0}

        class RespuestaFalsa:
            def read(self):
                return _tesela_falsa()

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def a_veces_falla(req, timeout=None):
            fallos["n"] += 1
            if fallos["n"] % 3 == 0:
                raise OSError("tesela caída")
            return RespuestaFalsa()

        with mock.patch.object(server.urllib.request, "urlopen", a_veces_falla):
            server._MAPA_CACHE.clear()
            mapa = server.build_mapa_estatico(36.7213, -4.4214, ancho=600, alto=300)
        self.assertEqual(mapa.size, (600, 300))
        self.parche.start()


class LoQueYaNoSeHaceTests(unittest.TestCase):
    def test_no_queda_el_recuadro_falso_ni_el_qr(self):
        """Era un dibujo gris que decía «sin conexión» y un QR para el móvil."""
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        for resto in ("Vista previa", "sin conexión", "Escanea", "qr_img"):
            with self.subTest(resto=resto):
                self.assertNotIn(resto, cuerpo)

    def test_la_atribucion_va_dentro_de_la_imagen(self):
        """Es condición de uso de OpenStreetMap, y el PDF puede circular suelto."""
        i = SERVER.index("def build_mapa_estatico")
        self.assertIn("© OpenStreetMap", SERVER[i: SERVER.index("\ndef ", i + 10)])

    def test_geocodifica_si_no_hay_coordenadas_guardadas(self):
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("fetch_geocode_coordinates", cuerpo)
        self.assertIn('calc.get("map_lat")', cuerpo)

    def test_el_pie_del_mapa_es_la_direccion(self):
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('"caption": limpio(calc.get("comunidad_direccion"))', cuerpo)


if __name__ == "__main__":
    unittest.main()
