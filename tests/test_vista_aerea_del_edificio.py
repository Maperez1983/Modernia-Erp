"""La foto del edificio, del PNOA del IGN, gratis y sin clave.

El usuario preguntó si se podían traer fotos del edificio de la red y pidió una
opción gratuita. Probé tres fuentes contra una dirección real (Calle Rocío Jurado
18, Puerto de la Torre):

- **KartaView**: API abierta y sin clave, pero devolvió respuesta vacía — no hay
  cobertura en esa calle.
- **Mapillary**: exige token aunque sea gratuito, así que no se puede montar sin que
  alguien dé de alta una cuenta.
- **PNOA del IGN**: HTTP 200 y un JPEG de 106 kB de la manzana. Sin clave, cobertura
  de toda España y licencia CC-BY 4.0, que permite meter la imagen en un documento
  comercial citando al Instituto Geográfico Nacional.

Lo que **no** se hace es tirar de una búsqueda de imágenes genérica: las fotos tienen
dueño, y además no hay forma de garantizar que la que sale sea de ese portal y no del
de al lado. Mandarle a un presidente la fachada equivocada hunde la propuesta.

Dos reglas que fijan estos tests, las mismas que ya seguía el mapa:

- **Ante cualquier fallo, no hay bloque.** Sin red, con el IGN caído, en una zona sin
  vuelo o si el servicio responde con un XML de error, se devuelve `None` y el
  presupuesto sale sin foto. Nunca un recuadro que finja ser una imagen.
- **La atribución va dentro de la imagen**, porque el PDF circula suelto. Si no se
  puede estampar, no se entrega la foto.
"""

import json
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
    from pypdf import PdfReader

    LISTO = True
except Exception:  # pragma: no cover
    LISTO = False


def _jpeg(ancho=900, alto=420, color=(150, 140, 120)):
    buf = BytesIO()
    Image.new("RGB", (ancho, alto), color).save(buf, format="JPEG")
    return buf.getvalue()


class _Respuesta:
    def __init__(self, datos, tipo="image/jpeg"):
        self._datos = datos
        self.headers = {"Content-Type": tipo}

    def read(self):
        return self._datos

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class AnteLaDudaNoSePintaNadaTests(unittest.TestCase):
    def setUp(self):
        server._AEREA_CACHE.clear()

    def test_sin_coordenadas(self):
        for lat, lon in ((None, None), ("", ""), ("hola", "adios"), (None, 3)):
            with self.subTest(lat=lat, lon=lon):
                self.assertIsNone(server.build_vista_aerea(lat, lon))

    def test_coordenadas_imposibles(self):
        for lat, lon in ((999, 999), (91, 0), (0, 181), (-91, 0)):
            with self.subTest(lat=lat, lon=lon):
                self.assertIsNone(server.build_vista_aerea(lat, lon))

    def test_sin_red_no_revienta(self):
        with mock.patch.object(server.urllib.request, "urlopen", side_effect=OSError("sin red")):
            self.assertIsNone(server.build_vista_aerea(36.6637, -4.5856))

    def test_un_xml_de_error_no_se_cuela_como_imagen(self):
        """El WMS contesta 200 con una `ServiceException` cuando algo va mal: mirar
        solo el código de estado daría por buena una imagen que no existe."""
        xml = b'<?xml version="1.0"?><ServiceExceptionReport><ServiceException/></ServiceExceptionReport>'
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_Respuesta(xml, "text/xml")):
            self.assertIsNone(server.build_vista_aerea(36.6637, -4.5856))

    @unittest.skipUnless(LISTO, "hace falta PIL")
    def test_una_respuesta_que_no_es_imagen_no_revienta(self):
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_Respuesta(b"no soy un jpeg", "image/jpeg")):
            self.assertIsNone(server.build_vista_aerea(36.6637, -4.5856))


@unittest.skipUnless(LISTO, "hace falta PIL")
class LaFotoSePideBienTests(unittest.TestCase):
    def setUp(self):
        server._AEREA_CACHE.clear()
        self.pedidas = []

        def falso(req, timeout=None):
            self.pedidas.append(req.full_url)
            return _Respuesta(_jpeg())

        self.parche = mock.patch.object(server.urllib.request, "urlopen", falso)
        self.parche.start()
        self.addCleanup(self.parche.stop)

    def test_sale_del_tamano_pedido(self):
        foto = server.build_vista_aerea(36.6637, -4.5856, ancho=900, alto=420)
        self.assertEqual(foto.size, (900, 420))

    def test_va_contra_el_ign(self):
        server.build_vista_aerea(36.6637, -4.5856)
        self.assertTrue(self.pedidas)
        self.assertTrue(self.pedidas[0].startswith("https://www.ign.es/wms-inspire/pnoa-ma"))

    def test_pide_la_capa_de_ortofoto(self):
        server.build_vista_aerea(36.6637, -4.5856)
        self.assertIn("OI.OrthoimageCoverage", self.pedidas[0])

    def test_el_bbox_va_en_orden_latitud_longitud(self):
        """WMS 1.3.0 con EPSG:4326 invierte el orden respecto a 1.1.1. Con lon,lat
        el IGN devuelve un trozo de océano o un error."""
        server.build_vista_aerea(36.6637, -4.5856)
        url = self.pedidas[0]
        import urllib.parse as up

        bbox = up.parse_qs(up.urlparse(url).query)["bbox"][0].split(",")
        miny, minx, maxy, maxx = (float(v) for v in bbox)
        self.assertAlmostEqual((miny + maxy) / 2, 36.6637, places=3)
        self.assertAlmostEqual((minx + maxx) / 2, -4.5856, places=3)

    def test_no_sale_deformada(self):
        """El ancho en grados se corrige por el coseno de la latitud; si no, en
        España un edificio cuadrado saldría estirado casi un 25 %."""
        import urllib.parse as up

        server.build_vista_aerea(36.6637, -4.5856, ancho=900, alto=450)
        bbox = up.parse_qs(up.urlparse(self.pedidas[0]).query)["bbox"][0].split(",")
        miny, minx, maxy, maxx = (float(v) for v in bbox)
        import math

        alto_m = (maxy - miny) * server.METROS_POR_GRADO
        ancho_m = (maxx - minx) * server.METROS_POR_GRADO * math.cos(math.radians(36.6637))
        # La proporción en metros debe coincidir con la del lienzo (900/450 = 2).
        self.assertAlmostEqual(ancho_m / alto_m, 900 / 450, places=2)

    def test_no_repite_una_foto_ya_bajada(self):
        """Un mismo presupuesto se regenera varias veces mientras se ajusta."""
        server.build_vista_aerea(36.6637, -4.5856)
        primera = len(self.pedidas)
        server.build_vista_aerea(36.6637, -4.5856)
        self.assertEqual(len(self.pedidas), primera)

    def test_la_cache_no_crece_sin_freno(self):
        self.assertIn("_AEREA_CACHE_MAX", SERVER)
        i = SERVER.index("def build_vista_aerea")
        self.assertIn("_AEREA_CACHE.clear()", SERVER[i: SERVER.index("\ndef ", i + 10)])

    def test_lleva_la_marca_del_punto_en_el_centro(self):
        foto = server.build_vista_aerea(36.6637, -4.5856, ancho=400, alto=400)
        # El círculo rojo, sobre el color plano de la foto falsa.
        encontrado = any(
            foto.getpixel((x, 200))[0] > 180 and foto.getpixel((x, 200))[1] < 90
            for x in range(150, 250)
        )
        self.assertTrue(encontrado, "no se ve la marca del edificio")

    def test_la_marca_no_tapa_el_tejado(self):
        """Es un círculo hueco, no una chincheta rellena: sobre una foto cenital
        una chincheta taparía justo lo que se quiere enseñar."""
        foto = server.build_vista_aerea(36.6637, -4.5856, ancho=400, alto=400)
        rojo, verde, azul = foto.getpixel((200, 200))
        # No se compara con el color exacto: el JPEG mueve algún valor un punto.
        # Lo que importa es que el centro siga siendo la foto y no la marca.
        self.assertLess(rojo, 180)
        self.assertGreater(verde, 90)
        self.assertGreater(azul, 60)


@unittest.skipUnless(LISTO, "hace falta PIL")
class LaAtribucionEsObligatoriaTests(unittest.TestCase):
    def setUp(self):
        server._AEREA_CACHE.clear()

    def test_la_licencia_exige_citar_al_ign(self):
        self.assertEqual(server.IGN_ORTOFOTO_ATRIBUCION, "© Instituto Geográfico Nacional de España")

    def test_va_dentro_de_la_imagen(self):
        """El PDF puede circular suelto, así que la cita no puede ir solo en el pie."""
        i = SERVER.index("def build_vista_aerea")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("IGN_ORTOFOTO_ATRIBUCION", cuerpo)
        self.assertIn("dibujo.text(", cuerpo)

    def test_si_no_se_puede_estampar_no_se_entrega(self):
        with mock.patch.object(server.urllib.request, "urlopen", return_value=_Respuesta(_jpeg())), \
             mock.patch.object(server.ImageDraw, "Draw", side_effect=RuntimeError("sin dibujo")):
            self.assertIsNone(server.build_vista_aerea(36.6637, -4.5856))


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class EnElPresupuestoTests(unittest.TestCase):
    WORKSPACE = {"nombre": "Modernia", "primary_color": "#3C6E71"}
    EMPRESA = {"nombre": "Inmovere Fincas", "razon_social": "Inmovere Fincas", "nif": "B26798231"}
    CLIENTE = {"nombre": "C.P. Ejemplo", "nif": "", "telefono": "", "email": ""}
    LINEAS = [{"categoria": "Edificio", "concepto": "Por vivienda", "cantidad": 92,
               "unidad": "vivienda", "precio_unitario": 5, "total_linea": 460}]

    def genera(self, calc_extra=None, aerea=True):
        calc = {"num_vecinos": 92, "map_lat": "36.6637", "map_lon": "-4.5856",
                "comunidad_denominacion": "C.P. Ejemplo"}
        calc.update(calc_extra or {})
        budget = {"id": "x", "servicio": "fincas", "titulo": "Prueba", "fecha": "2026-08-08",
                  "subtotal": 460.0, "impuestos": 96.6, "total": 556.6,
                  "calculo_json": json.dumps(calc)}
        foto = Image.new("RGB", (900, 420), (150, 140, 120)) if aerea else None
        with mock.patch.object(server, "build_mapa_estatico", return_value=None), \
             mock.patch.object(server, "build_vista_aerea", return_value=foto) as espia:
            pdf = server.build_workspace_budget_pdf(
                budget, self.WORKSPACE, self.EMPRESA, self.CLIENTE, self.LINEAS)
        texto = "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages)
        return texto, espia

    def test_sale_el_bloque_si_hay_foto(self):
        texto, _e = self.genera()
        self.assertIn("Vista aérea del edificio", texto)
        self.assertIn("PNOA", texto)

    def test_sin_foto_no_hay_bloque(self):
        texto, _e = self.genera(aerea=False)
        self.assertNotIn("Vista aérea", texto)

    def test_sin_coordenadas_no_se_pide_siquiera(self):
        _t, espia = self.genera({"map_lat": "", "map_lon": "", "comunidad_direccion": ""})
        espia.assert_not_called()

    def test_la_foto_subida_a_mano_manda(self):
        """Una fachada de verdad vale más que una cenital, y dos imágenes seguidas
        del mismo edificio rellenan en vez de informar."""
        buf = BytesIO()
        Image.new("RGB", (600, 400), (30, 60, 90)).save(buf, format="JPEG")
        with mock.patch.object(server, "s3_get_object_bytes", return_value=(buf.getvalue(), None)):
            texto, espia = self.genera({"edificio_foto_key": "fincas/portal.jpg"})
        self.assertIn("Edificio", texto)
        self.assertNotIn("Vista aérea", texto)
        espia.assert_not_called()


if __name__ == "__main__":
    unittest.main()
