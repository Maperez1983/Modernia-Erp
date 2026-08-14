"""Los títulos y las descripciones del anuncio.

Salió de pasar el generador por los trece encargos reales. Tres cosas:

1. `subtipologia` es un cajón de sastre. Hay subtipos de verdad —«BAJO»,
   «Estudio», «Nave industrial»— y hay números sueltos: cinco fichas con «3», dos
   con «4», una con «6», una con «2». Son dormitorios escritos en el campo
   equivocado, y pegados al tipo salía **«Piso 2 en Madrid»** y **«Villa 6 en
   Coín»**, que se leen como una errata.
2. La entradilla repetía el título: «Piso 3 dormitorios en Málaga **con 3
   dormitorios**».
3. Siete de trece fichas no tenían título, y el portal las anunciaba como «Local
   en Málaga» o «Piso en Málaga», que no dice ni el tamaño.

Y el generador pisaba sin preguntar: los seis títulos publicados están escritos a
mano —«VENTA DE APARCAMIENTO EN LAS DELICIAS»— y ninguno lleva el sello
`anuncio_generado_at`. Ese sello es lo que distingue nuestro texto del suyo.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-13 09:00:00"
CLAVE = "Contrasena1!"


def copia(**campos):
    base = {"tipo_inmueble": "Piso", "tipo_operacion": "venta", "poblacion": "Málaga",
            "m2": 90, "habitaciones": 3, "banos": 2, "precio_objetivo": 200000}
    base.update(campos)
    return S.build_inmueble_anuncio_copy(base)


class LaSubtipologiaTests(unittest.TestCase):
    def test_un_numero_suelto_no_es_un_subtipo(self):
        """Los cuatro casos reales: «3», «4», «6», «2»."""
        for valor in ("3", "4", "6", "2", " 3 ", "3.0"):
            self.assertEqual(S.subtipo_publicable(valor), "", valor)

    def test_ni_los_dormitorios_escritos_ahi(self):
        for valor in ("3 DORMITORIOS", "3 dormitorios", "2 habitaciones", "4 hab"):
            self.assertEqual(S.subtipo_publicable(valor), "", valor)

    def test_los_subtipos_de_verdad_se_quedan(self):
        for valor in ("BAJO", "Estudio", "planta media", "COMERCIAL", "CASA MATA",
                      "Nave industrial"):
            self.assertEqual(S.subtipo_publicable(valor), valor)

    def test_el_titulo_ya_no_dice_piso_2(self):
        self.assertNotIn("Piso 2", copia(subtipologia="2", habitaciones=2)["titulo_anuncio"])
        self.assertNotIn("Villa 6", copia(tipo_inmueble="Villa", subtipologia="6",
                                          habitaciones=6)["titulo_anuncio"])

    def test_y_el_subtipo_bueno_sigue_saliendo(self):
        self.assertIn("Piso planta media",
                      copia(subtipologia="planta media")["titulo_anuncio"])


class ElTituloTests(unittest.TestCase):
    def test_lleva_el_tamaño(self):
        """«Local en Málaga» era lo que se publicaba y no dice nada."""
        self.assertEqual(copia()["titulo_anuncio"], "Piso de 3 dormitorios en Málaga")

    def test_en_lo_que_no_es_vivienda_manda_el_metro(self):
        """Un local con `habitaciones = 1` salía como «Local comercial de 1
        dormitorio»: es lo que tenía la ficha, pero no lo que significa."""
        t = copia(tipo_inmueble="Local", subtipologia="COMERCIAL", habitaciones=1, m2=142)
        self.assertEqual(t["titulo_anuncio"], "Local comercial de 142 m² en Málaga")
        self.assertNotIn("dormitorio", t["titulo_anuncio"])

    def test_el_tipo_no_se_dice_dos_veces(self):
        """Salía «Casa casa mata» y «Nave nave industrial»: cuando el subtipo ya
        contiene al tipo, el que sobra es el tipo."""
        self.assertEqual(
            copia(tipo_inmueble="Casa", subtipologia="CASA MATA", habitaciones=None,
                  m2=80)["titulo_anuncio"], "Casa mata de 80 m² en Málaga")
        self.assertEqual(
            copia(tipo_inmueble="Nave", subtipologia="Nave industrial", habitaciones=None,
                  m2=80)["titulo_anuncio"], "Nave industrial de 80 m² en Málaga")

    def test_un_garaje_tampoco_tiene_dormitorios(self):
        self.assertIn("de 36 m²", copia(tipo_inmueble="Garaje", habitaciones=None,
                                        m2=36)["titulo_anuncio"])

    def test_un_dormitorio_va_en_singular(self):
        self.assertIn("de 1 dormitorio en", copia(habitaciones=1)["titulo_anuncio"])
        self.assertNotIn("1 dormitorios", copia(habitaciones=1)["titulo_anuncio"])

    def test_sin_metros_ni_dormitorios_no_inventa(self):
        t = copia(habitaciones=None, m2=None)["titulo_anuncio"]
        self.assertEqual(t, "Piso en Málaga")

    def test_la_zona_afina_donde_esta(self):
        self.assertIn("Las Delicias, Málaga", copia(zona="Las Delicias")["titulo_anuncio"])

    def test_no_se_pasa_de_largo(self):
        largo = copia(zona="Z" * 200, poblacion="P" * 200)["titulo_anuncio"]
        self.assertLessEqual(len(largo), 120)


class LaDescripcionTests(unittest.TestCase):
    def test_no_repite_lo_que_dice_el_titulo(self):
        """«Piso de 3 dormitorios en Málaga con 3 dormitorios» era el texto real."""
        c = copia()
        self.assertNotIn("con 3 dormitorios", c["descripcion_corta"])
        self.assertIn("3 dormitorios", c["titulo_anuncio"])

    def test_pero_sí_cuenta_lo_demas(self):
        c = copia()
        self.assertIn("90 m²", c["descripcion_corta"])
        self.assertIn("2 baños", c["descripcion_corta"])

    def test_los_metros_tampoco_se_repiten_cuando_son_la_medida(self):
        c = copia(tipo_inmueble="Local", habitaciones=None, m2=59)
        self.assertIn("de 59 m²", c["descripcion_corta"])
        self.assertNotIn("con 59 m²", c["descripcion_corta"])

    def test_un_local_no_tiene_dormitorios_tampoco_aqui(self):
        """El local de Las Delicias llegó a publicarse como «Local comercial de
        142 m² … con 1 dormitorio»: el título ya sabía que no era vivienda y la
        descripción no."""
        c = copia(tipo_inmueble="Local", subtipologia="COMERCIAL", habitaciones=1, m2=142)
        self.assertNotIn("dormitorio", c["descripcion_corta"])
        self.assertNotIn("dormitorio", c["descripcion_larga"])

    def test_la_descripcion_larga_abre_con_la_medida(self):
        self.assertIn("Se vende piso de 3 dormitorios en Málaga",
                      copia()["descripcion_larga"])

    def test_y_el_alquiler_lo_dice(self):
        self.assertIn("Se alquila piso de 3 dormitorios",
                      copia(tipo_operacion="alquiler")["descripcion_larga"])


class DeQuienEsElTextoTests(unittest.TestCase):
    def test_sin_titulo_es_nuestro(self):
        self.assertTrue(S.texto_del_anuncio_es_nuestro(
            {"titulo_anuncio": "", "anuncio_generado_at": ""}))

    def test_un_titulo_a_mano_no_lo_es(self):
        self.assertFalse(S.texto_del_anuncio_es_nuestro(
            {"titulo_anuncio": "VENTA DE APARCAMIENTO EN LAS DELICIAS",
             "anuncio_generado_at": ""}))

    def test_el_sello_lo_convierte_en_nuestro(self):
        self.assertTrue(S.texto_del_anuncio_es_nuestro(
            {"titulo_anuncio": "Piso de 3 dormitorios en Málaga",
             "anuncio_generado_at": AHORA}))


class ElEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Agencia", activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="asesora",
                                   email="ana@x.test", rol="Administrador",
                                   servicio="Inmobiliaria", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **base))
        for iid, titulo in (("vacio", None), ("aMano", "VENTA DE APARCAMIENTO EN LAS DELICIAS")):
            self._ins("inmuebles", dict(
                id=iid, workspace_id=self.ws, empresa_id="emp1", direccion=f"Calle {iid}",
                poblacion="Málaga", estado="Encargo", tipo_inmueble="Piso",
                tipo_operacion="venta", m2=90, habitaciones=3, banos=2,
                precio_objetivo=200000, subtipologia="3", titulo_anuncio=titulo, **base))
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "asesora", "password": CLAVE},
                                 cookie=None)["cookie"]

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()))
        self.conn.commit()

    def _post(self, ruta, cuerpo, cookie=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        if cookie:
            req.add_header("Cookie", self.cookie if cookie is True else cookie)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo_b, galleta = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "json": json.loads(cuerpo_b.decode() or "{}"),
                        "cookie": galleta.split(";")[0] if galleta else None}
        except urllib.error.HTTPError as e:
            return {"estado": e.code, "json": json.loads(e.read().decode() or "{}"),
                    "cookie": None}

    def _titulo(self, iid):
        return self.conn.execute(
            "SELECT titulo_anuncio FROM inmuebles WHERE id = ?", (iid,)).fetchone()[0]

    def test_rellena_el_que_no_tiene(self):
        r = self._post("/api/inmueble_anuncio_generate", {"inmueble_id": "vacio"})
        self.assertEqual(r["estado"], 200)
        self.assertEqual(r["json"]["titulo_anuncio"], "Piso de 3 dormitorios en Málaga")
        self.assertEqual(self._titulo("vacio"), "Piso de 3 dormitorios en Málaga")

    def test_respeta_el_escrito_a_mano(self):
        r = self._post("/api/inmueble_anuncio_generate", {"inmueble_id": "aMano"})
        self.assertTrue(r["json"].get("respetado"))
        self.assertEqual(self._titulo("aMano"), "VENTA DE APARCAMIENTO EN LAS DELICIAS")

    def test_salvo_que_se_pida_expresamente(self):
        r = self._post("/api/inmueble_anuncio_generate",
                       {"inmueble_id": "aMano", "sobrescribir": True})
        self.assertEqual(r["estado"], 200)
        self.assertEqual(self._titulo("aMano"), "Piso de 3 dormitorios en Málaga")

    def test_y_una_vez_generado_se_puede_rehacer(self):
        self._post("/api/inmueble_anuncio_generate", {"inmueble_id": "vacio"})
        self.conn.execute("UPDATE inmuebles SET banos = 3 WHERE id = 'vacio'")
        self.conn.commit()
        r = self._post("/api/inmueble_anuncio_generate", {"inmueble_id": "vacio"})
        self.assertEqual(r["estado"], 200)
        self.assertNotIn("respetado", r["json"])
        self.assertIn("3 baños", r["json"]["descripcion_corta"])

    def test_el_lote_va_ficha_a_ficha(self):
        """Siete de trece sin título: de una en una es la razón de que nunca se
        hiciera."""
        r = self._post("/api/inmueble_anuncio_generate",
                       {"inmueble_ids": ["vacio", "aMano"]})
        self.assertEqual(r["estado"], 200)
        self.assertEqual([x["id"] for x in r["json"]["generados"]], ["vacio"])
        self.assertEqual([x["id"] for x in r["json"]["respetados"]], ["aMano"])
        self.assertEqual(self._titulo("aMano"), "VENTA DE APARCAMIENTO EN LAS DELICIAS")

    def test_un_id_que_no_existe_no_tumba_el_lote(self):
        r = self._post("/api/inmueble_anuncio_generate",
                       {"inmueble_ids": ["vacio", "fantasma"]})
        self.assertEqual(r["estado"], 200)
        self.assertEqual([x["id"] for x in r["json"]["generados"]], ["vacio"])
        self.assertEqual(r["json"]["fallidos"][0]["id"], "fantasma")

    def test_sin_sesion_no(self):
        r = self._post("/api/inmueble_anuncio_generate", {"inmueble_id": "vacio"},
                       cookie=None)
        self.assertIn(r["estado"], (401, 403))
        self.assertIsNone(self._titulo("vacio"))


if __name__ == "__main__":
    unittest.main()
