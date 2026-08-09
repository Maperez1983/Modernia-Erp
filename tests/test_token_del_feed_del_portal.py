"""El feed del portal se puede cerrar sin dejar al portal sin anuncios.

`/api/inmueble_portal_feed` sirve el catálogo entero —direcciones, precios y
descripciones de todas las agencias— en XML o JSON. Pedía token sólo si
`INMO_EXTERNAL_FEED_TOKEN` estaba puesto, y **en producción no lo estaba**: se lo
descargaba cualquiera que conociera la URL.

Cerrarlo tiene un riesgo evidente: el CRM y el portal Verifika2 son dos sistemas
distintos, y en cuanto se configura el token, el portal deja de recibir anuncios
hasta que alguien lo actualiza. Por eso el cierre no es un interruptor:

*   el token se acepta por `?token=`, por `X-Access-Token`, por `X-API-Key` y por
    `Authorization: Bearer`, porque cada integración manda las credenciales a su
    manera y no merece la pena discutirlo;
*   se admiten **varios** tokens separados por comas, para rotar sin cortar: se
    añade el nuevo, se avisa al portal, y cuando ya lo usa se quita el viejo. Con un
    solo token, rotar exige que los dos lados cambien a la vez, o sea nunca;
*   `INMO_EXTERNAL_FEED_ENFORCE=0` sirve el feed igual pero deja constancia en el
    log de cada petición sin token, para poder comprobar si el portal ya lo manda
    **antes** de cerrar de verdad.

La comparación es en tiempo constante, como en el resto de tokens del CRM.
"""

import os
import unittest
import urllib.parse


class _CabecerasFalsas(dict):
    def get(self, clave, defecto=None):
        for k, v in self.items():
            if k.lower() == str(clave).lower():
                return v
        return defecto


class _PeticionFalsa:
    """Lo mínimo que mira `feed_del_portal_autorizado`: cabeceras."""

    def __init__(self, **cabeceras):
        self.headers = _CabecerasFalsas(cabeceras)


def params(qs):
    return urllib.parse.parse_qs(qs)


class TokenDelFeedTests(unittest.TestCase):
    def setUp(self):
        os.environ["DATABASE_URL"] = ""
        from web import server as S
        self.S = S
        self._previos = {
            k: os.environ.get(k)
            for k in ("INMO_EXTERNAL_FEED_TOKEN", "INMO_EXTERNAL_FEED_ENFORCE")
        }

    def tearDown(self):
        for k, v in self._previos.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _autorizado(self, qs="", **cabeceras):
        return self.S.feed_del_portal_autorizado(_PeticionFalsa(**cabeceras), params(qs))

    # ---------- sin configurar: como hasta ahora ----------

    def test_sin_token_configurado_el_feed_sigue_abierto(self):
        os.environ.pop("INMO_EXTERNAL_FEED_TOKEN", None)
        ok, aviso = self._autorizado()
        self.assertTrue(ok)
        self.assertEqual(aviso, "")

    # ---------- configurado: se exige ----------

    def test_configurado_sin_token_se_deniega(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        ok, _ = self._autorizado()
        self.assertFalse(ok)

    def test_configurado_con_token_equivocado_se_deniega(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        ok, _ = self._autorizado("token=otro")
        self.assertFalse(ok)

    def test_vale_por_cualquiera_de_las_cuatro_vias(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        casos = (
            ("por query", {"qs": "token=secreto-largo-de-verdad"}),
            ("por X-Access-Token", {"X-Access-Token": "secreto-largo-de-verdad"}),
            ("por X-API-Key", {"X-API-Key": "secreto-largo-de-verdad"}),
            ("por Authorization", {"Authorization": "Bearer secreto-largo-de-verdad"}),
        )
        for etiqueta, kwargs in casos:
            with self.subTest(etiqueta):
                ok, _ = self._autorizado(**kwargs)
                self.assertTrue(ok, etiqueta)

    def test_el_bearer_se_lee_sin_importar_las_mayusculas(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        ok, _ = self._autorizado(Authorization="bearer secreto-largo-de-verdad")
        self.assertTrue(ok)

    # ---------- rotación ----------

    def test_dos_tokens_a_la_vez_para_poder_rotar(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = " viejo-en-uso , nuevo-recien-creado "
        for token in ("viejo-en-uso", "nuevo-recien-creado"):
            with self.subTest(token):
                ok, _ = self._autorizado(f"token={token}")
                self.assertTrue(ok)
        ok, _ = self._autorizado("token=ninguno-de-los-dos")
        self.assertFalse(ok)

    def test_las_comas_sueltas_no_abren_el_feed(self):
        """Un valor mal escrito no puede convertirse en «token vacío válido»."""
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "bueno,, ,"
        self.assertEqual(self.S.tokens_del_feed_del_portal(), ["bueno"])
        ok, _ = self._autorizado()
        self.assertFalse(ok)

    # ---------- fase de observación ----------

    def test_en_observacion_se_sirve_pero_queda_constancia(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        os.environ["INMO_EXTERNAL_FEED_ENFORCE"] = "0"
        ok, aviso = self._autorizado()
        self.assertTrue(ok, "en observación el portal no se puede quedar sin anuncios")
        self.assertEqual(aviso, "sin token")
        ok, aviso = self._autorizado("token=equivocado")
        self.assertTrue(ok)
        self.assertEqual(aviso, "sin token válido")

    def test_en_observacion_el_token_bueno_no_avisa(self):
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        os.environ["INMO_EXTERNAL_FEED_ENFORCE"] = "0"
        ok, aviso = self._autorizado("token=secreto-largo-de-verdad")
        self.assertTrue(ok)
        self.assertEqual(aviso, "", "si avisara siempre, el log no diría nada")

    def test_el_valor_por_defecto_es_cerrar(self):
        """Olvidarse de la variable de fase debe dejar el feed cerrado, no abierto."""
        os.environ["INMO_EXTERNAL_FEED_TOKEN"] = "secreto-largo-de-verdad"
        os.environ.pop("INMO_EXTERNAL_FEED_ENFORCE", None)
        ok, _ = self._autorizado()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
