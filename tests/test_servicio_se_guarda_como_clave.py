"""La etiqueta que se ve no es la clave que se guarda.

En `clientes_empresas.servicio` convivían "gestoria" (1647) y "Gestoría" (617).
No es solo fealdad: en minúsculas la tilde sigue ahí, así que

    WHERE LOWER(servicio) = 'gestoria'

deja fuera los 617. Un cuarto de los vínculos de gestoría, invisibles para
cualquier consulta escrita de la forma habitual, sin que nada falle ni avise.

Lo mismo con "Seguros" (14), "Inmobiliaria" (1) y "Administración de fincas" (5),
y con un detalle que solo se ve mirando el formulario: el desplegable manda
`financiacion` en singular mientras la base y las consultas usan `financiaciones`.

`normalize_service_key` ya resolvía todo esto —incluido el singular— pero no se
llamaba al escribir, así que la base se iba ensuciando sola.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

try:
    from web import server
except Exception:  # pragma: no cover - solo si faltan dependencias del servidor
    server = None


@unittest.skipIf(server is None, "no se pudo importar web.server")
class LaClaveDeServicioTests(unittest.TestCase):
    def test_traduce_las_grafias_que_habia_en_produccion(self):
        casos = {
            "Gestoría": "gestoria",
            "gestoria": "gestoria",
            "Seguros": "seguros",
            "Inmobiliaria": "inmobiliaria",
            "Administración de fincas": "fincas",
        }
        for crudo, esperado in casos.items():
            with self.subTest(crudo=crudo):
                self.assertEqual(server.normalize_service_key(crudo), esperado)

    def test_el_singular_del_formulario_llega_al_plural_de_la_base(self):
        """El desplegable ofrece `financiacion`; las consultas buscan `financiaciones`."""
        for crudo in ("financiacion", "Financiación", "financiaciones"):
            with self.subTest(crudo=crudo):
                self.assertEqual(server.normalize_service_key(crudo), "financiaciones")

    def test_la_clave_es_estable(self):
        """Normalizar lo ya normalizado no lo cambia: si no, cada guardado lo movería."""
        for clave in ("gestoria", "seguros", "inmobiliaria", "financiaciones", "fincas"):
            with self.subTest(clave=clave):
                self.assertEqual(server.normalize_service_key(clave), clave)


class ElAltaDeVinculosGuardaLaClaveTests(unittest.TestCase):
    def test_el_endpoint_normaliza_antes_de_escribir(self):
        codigo = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
        i = codigo.index('servicio = (payload.get("servicio") or "").strip()')
        bloque = codigo[i: i + 800]
        self.assertIn("normalize_service_key(servicio)", bloque)


class ElFormularioOfreceValoresTraduciblesTests(unittest.TestCase):
    """Toda opción del desplegable tiene que caer en una clave conocida."""

    @unittest.skipIf(server is None, "no se pudo importar web.server")
    def test_ninguna_opcion_se_queda_sin_clave(self):
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        # Los cinco CRM verticales, más los servicios que solo viven en otras tablas:
        # "reformas" es del desplegable de presupuestos y "captaciones" del inmobiliario.
        conocidas = {
            "gestoria",
            "seguros",
            "inmobiliaria",
            "financiaciones",
            "fincas",
            "reformas",
            "captaciones",
        }
        huerfanas = []
        for bloque in re.findall(r'<select name="servicio">(.*?)</select>', html, re.S):
            for valor in re.findall(r'<option value="([^"]*)"', bloque):
                if not valor:
                    continue
                clave = server.normalize_service_key(valor)
                if clave not in conocidas:
                    huerfanas.append((valor, clave))
        self.assertEqual(
            huerfanas,
            [],
            "opciones del formulario que no caen en un servicio conocido: " + repr(huerfanas),
        )


if __name__ == "__main__":
    unittest.main()
