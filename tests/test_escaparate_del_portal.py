"""El escaparate público: lo que se puede buscar y lo que se debe contar.

Salió de mirar qué servía el feed de verdad y qué había relleno en la cartera:
seis anuncios, dos sin foto, ninguno con etiqueta energética, y un feed que sólo
aceptaba `limit` —sin filtros, sin orden y sin paginación—, devolviendo **una
sola foto** de los doce que tiene una ficha.

La etiqueta energética no es una mejora estética: la normativa la exige en toda
publicidad de venta o alquiler de vivienda. Por eso es requisito para publicar y
no un campo más.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-13 09:00:00"


class BaseEscaparate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "portal.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        S.ensure_anuncio_schema(self.conn)
        S.asegura_la_marca_de_visible(self.conn)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

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
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _publica(self, id_, **extra):
        datos = {"id": id_, "workspace_id": self.ws, "empresa_id": "emp1",
                 "direccion": f"Calle {id_}", "poblacion": "Málaga", "zona": "Centro",
                 "estado": "Encargo", "tipo_inmueble": "Piso", "tipo_operacion": "venta",
                 "m2": 90, "habitaciones": 3, "banos": 2, "precio_objetivo": 200000,
                 "descripcion": "Un piso.", "portal_publicado": 1,
                 "portal_publicado_at": AHORA, "energia_letra": "D", "lat": 36.7, "lon": -4.4,
                 "created_at": AHORA, "updated_at": AHORA}
        datos.update(extra)
        self._ins("inmuebles", datos)
        self._ins("captaciones", {"id": f"c{id_}", "empresa_id": "emp1", "inmueble_id": id_,
                                  "direccion": datos["direccion"], "etapa": "Encargo",
                                  "noticia_verificada": 1, "created_at": AHORA, "updated_at": AHORA})
        return id_

    def _feed(self, consulta=""):
        with urllib.request.urlopen(self.base + "/api/portal_inmuebles" + consulta) as r:
            return json.loads(r.read().decode())


class LaEtiquetaEnergeticaTests(BaseEscaparate):
    def test_sin_etiqueta_no_se_publica(self):
        """La normativa la exige en toda publicidad de venta o alquiler. De trece
        encargos en producción no había ni uno con ella."""
        self._publica("sin", energia_letra=None, portal_publicado=0)
        self._ins("inmueble_docs", {"id": "d1", "inmueble_id": "sin", "nombre": "foto.jpg",
                                    "tipo": "Foto", "url": "/uploads/x.jpg",
                                    "visible_portal": 1,
                                    "created_at": AHORA, "updated_at": AHORA})
        v = S.validate_portal_publication_requirements(self.conn, "sin")
        self.assertFalse(v["ok"])
        self.assertIn("Etiqueta de eficiencia energética", v["missing"])

    def test_con_etiqueta_sí(self):
        self._publica("con", portal_publicado=0)
        self._ins("inmueble_docs", {"id": "d2", "inmueble_id": "con", "nombre": "foto.jpg",
                                    "tipo": "Foto", "url": "/uploads/x.jpg",
                                    "visible_portal": 1,
                                    "created_at": AHORA, "updated_at": AHORA})
        v = S.validate_portal_publication_requirements(self.conn, "con")
        self.assertTrue(v["ok"], v["missing"])

    def test_exento_vale_y_se_dice(self):
        """Hay casos que no la necesitan —un garaje suelto—, y decirlo es distinto
        de dejarlo en blanco."""
        fila = {"energia_letra": "exento"}
        e = S.etiqueta_energetica(fila)
        self.assertEqual(e["etiqueta"], "Exento")
        self.assertTrue(e["exento"])

    def test_una_letra_inventada_no_cuela(self):
        self.assertIsNone(S.etiqueta_energetica({"energia_letra": "Z"}))
        self.assertIsNone(S.etiqueta_energetica({"energia_letra": ""}))

    def test_sale_en_el_anuncio_con_su_consumo(self):
        self._publica("uno", energia_letra="B", energia_consumo=68.5, energia_emisiones=12.1)
        x = self._feed()["rows"][0]
        self.assertEqual(x["energia"]["letra"], "B")
        self.assertEqual(x["energia"]["consumo"], 68.5)
        self.assertEqual(x["energia"]["emisiones"], 12.1)


class ElBuscadorTests(BaseEscaparate):
    def setUp(self):
        super().setUp()
        self._publica("barato", precio_objetivo=90000, m2=50, habitaciones=1,
                      tipo_operacion="venta", zona="Centro")
        self._publica("caro", precio_objetivo=400000, m2=180, habitaciones=5,
                      tipo_operacion="venta", zona="Teatinos", ascensor=1, garaje=1)
        self._publica("alquiler", precio_objetivo=1200, m2=70, habitaciones=2,
                      tipo_operacion="alquiler", zona="Centro", ascensor=1)

    def test_sin_filtros_salen_todos(self):
        d = self._feed()
        self.assertEqual(d["count"], 3)
        self.assertEqual(d["total"], 3)

    def test_por_operacion(self):
        self.assertEqual([x["id"] for x in self._feed("?operacion=alquiler")["rows"]], ["alquiler"])

    def test_por_precio(self):
        d = self._feed("?precio_min=100000&precio_max=500000")
        self.assertEqual([x["id"] for x in d["rows"]], ["caro"])

    def test_por_habitaciones_y_superficie(self):
        self.assertEqual([x["id"] for x in self._feed("?habitaciones_min=3")["rows"]], ["caro"])
        self.assertEqual([x["id"] for x in self._feed("?m2_min=100")["rows"]], ["caro"])

    def test_por_donde(self):
        ids = sorted(x["id"] for x in self._feed("?donde=centro")["rows"])
        self.assertEqual(ids, ["alquiler", "barato"])

    def test_por_caracteristicas(self):
        """Ascensor y garaje son los dos primeros filtros que toca cualquiera, y no
        se podían ni guardar."""
        self.assertEqual([x["id"] for x in self._feed("?ascensor=1&garaje=1")["rows"]], ["caro"])
        self.assertEqual(sorted(x["id"] for x in self._feed("?ascensor=1")["rows"]),
                         ["alquiler", "caro"])

    def test_orden_por_precio(self):
        self.assertEqual([x["id"] for x in self._feed("?orden=precio_asc")["rows"]],
                         ["alquiler", "barato", "caro"])
        self.assertEqual([x["id"] for x in self._feed("?orden=precio_desc")["rows"]][0], "caro")

    def test_un_orden_inventado_no_rompe(self):
        self.assertEqual(self._feed("?orden=%3B%20DROP%20TABLE%20inmuebles")["count"], 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM inmuebles").fetchone()["c"], 3)

    def test_paginacion(self):
        d = self._feed("?limit=2&orden=precio_asc")
        self.assertEqual(len(d["rows"]), 2)
        self.assertEqual(d["total"], 3, "el total no depende de la página")
        d2 = self._feed("?limit=2&desde=2&orden=precio_asc")
        self.assertEqual([x["id"] for x in d2["rows"]], ["caro"])

    def test_una_inyeccion_por_el_filtro_no_hace_nada(self):
        d = self._feed("?donde=%27%20OR%20%271%27%3D%271")
        self.assertEqual(d["count"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM inmuebles").fetchone()["c"], 3)


class LaGaleriaYLosDatosTests(BaseEscaparate):
    def setUp(self):
        super().setUp()
        self._publica("piso", precio_objetivo=200000, m2=80, ascensor=1, terraza=1,
                      planta=3, anio_construccion=1998, gastos_comunidad=45,
                      orientacion="Sur")
        for n in range(4):
            self._ins("inmueble_docs", {"id": f"f{n}", "inmueble_id": "piso",
                                        "nombre": f"foto{n}.jpg", "tipo": "Foto",
                                        "url": f"/uploads/f{n}.jpg", "visible_portal": 1,
                                        "created_at": AHORA, "updated_at": AHORA})

    def test_el_listado_no_carga_las_galerias(self):
        """Doce consultas para doce anuncios sólo para enseñar la portada."""
        x = self._feed()["rows"][0]
        self.assertNotIn("fotos", x)
        self.assertTrue(x.get("foto"))

    def test_pero_el_detalle_sí(self):
        """El anuncio tenía doce fotos y la web enseñaba una."""
        x = self._feed("?id=piso")["rows"][0]
        self.assertEqual(len(x["fotos"]), 4)

    def test_y_se_puede_pedir_en_el_listado(self):
        self.assertEqual(len(self._feed("?galeria=1")["rows"][0]["fotos"]), 4)

    def test_las_caracteristicas_salen_con_su_nombre(self):
        x = self._feed()["rows"][0]
        claves = [c["clave"] for c in x["caracteristicas"]]
        self.assertCountEqual(claves, ["ascensor", "terraza"])
        self.assertIn("Ascensor", [c["etiqueta"] for c in x["caracteristicas"]])

    def test_planta_ano_gastos_y_orientacion(self):
        x = self._feed()["rows"][0]
        self.assertEqual(x["planta"], "3")
        self.assertEqual(x["anio_construccion"], 1998)
        self.assertEqual(x["gastos_comunidad"], 45.0)
        self.assertEqual(x["orientacion"], "Sur")

    def test_el_precio_por_metro(self):
        """Dos cifras que ya se podían calcular y que nadie enseñaba."""
        self.assertEqual(self._feed()["rows"][0]["precio_m2"], 2500.0)

    def test_las_coordenadas_ya_venian(self):
        x = self._feed()["rows"][0]
        self.assertEqual((x["lat"], x["lon"]), (36.7, -4.4))


class LaBajadaDePrecioTests(BaseEscaparate):
    def test_se_anuncia_la_bajada(self):
        """Es de las pocas cosas que hacen abrir un anuncio ya visto, y el dato
        llevaba en la bitácora desde siempre."""
        self._publica("piso", precio_objetivo=190000)
        self._ins("auditoria", {"id": "a1", "empresa_id": "emp1", "entidad": "inmueble",
                                "entidad_id": "piso", "accion": "Cambio", "usuario": "ana",
                                "detalles": json.dumps({"campo": "precio_objetivo",
                                                        "from": 210000, "to": 190000}),
                                "created_at": S.datetime.now(S.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})
        b = self._feed()["rows"][0]["bajada_precio"]
        self.assertEqual((b["desde"], b["hasta"], b["rebaja"]), (210000.0, 190000.0, 20000.0))

    def test_poner_el_precio_por_primera_vez_no_es_una_bajada(self):
        self._publica("piso", precio_objetivo=190000)
        self._ins("auditoria", {"id": "a2", "empresa_id": "emp1", "entidad": "inmueble",
                                "entidad_id": "piso", "accion": "Cambio", "usuario": "ana",
                                "detalles": json.dumps({"campo": "precio_objetivo",
                                                        "from": None, "to": 190000}),
                                "created_at": S.datetime.now(S.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})
        self.assertIsNone(self._feed()["rows"][0]["bajada_precio"])

    def test_ni_una_subida(self):
        self._publica("piso", precio_objetivo=210000)
        self._ins("auditoria", {"id": "a3", "empresa_id": "emp1", "entidad": "inmueble",
                                "entidad_id": "piso", "accion": "Cambio", "usuario": "ana",
                                "detalles": json.dumps({"campo": "precio_objetivo",
                                                        "from": 190000, "to": 210000}),
                                "created_at": S.datetime.now(S.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})
        self.assertIsNone(self._feed()["rows"][0]["bajada_precio"])


if __name__ == "__main__":
    unittest.main()


class LasFotosDelEscaparateTests(BaseEscaparate):
    """La foto del anuncio no la podía ver nadie.

    El feed repartía `/uploads/inmuebles/<id>/fotos/<hash>.jpg`, y esa ruta pide
    sesión del CRM: contra producción responde **401**. Quien recibía el anuncio
    tenía la referencia de la imagen y no podía descargarla.

    Y la marca `visible_portal`, que el portal del propietario sí respeta, aquí no
    se miraba: una foto desmarcada a mano salía igual. No se notaba porque la
    imagen no llegaba a cargar.
    """

    def _foto(self, inmueble_id, nombre, *, visible=1, contenido=b"\xff\xd8\xff\xe0jpeg"):
        carpeta = Path(S.UPLOADS) / "inmuebles" / inmueble_id / "fotos"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / nombre).write_bytes(contenido)
        self._ins("inmueble_docs", {
            "id": f"d-{inmueble_id}-{nombre}", "inmueble_id": inmueble_id, "nombre": nombre,
            "tipo": "Fotos", "url": f"/uploads/inmuebles/{inmueble_id}/fotos/{nombre}",
            "estado": "Vigente", "visible_portal": visible,
            "created_at": f"{AHORA[:-1]}{len(nombre)}", "updated_at": AHORA})
        self.addCleanup(lambda p=carpeta / nombre: p.unlink(missing_ok=True))

    def _pide(self, consulta):
        req = urllib.request.Request(self.base + "/api/portal_inmueble_foto" + consulta)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read(), r.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), None

    def test_se_ve_sin_sesion(self):
        """Es lo que arregla: antes esta descarga era un 401."""
        self._publica("uno")
        self._foto("uno", "a.jpg")
        estado, cuerpo, tipo = self._pide("?id=uno&n=0")
        self.assertEqual(estado, 200)
        self.assertEqual(cuerpo, b"\xff\xd8\xff\xe0jpeg")
        self.assertEqual(tipo, "image/jpeg")

    def test_el_feed_publica_esa_direccion_y_no_la_del_disco(self):
        self._publica("uno")
        self._foto("uno", "a.jpg")
        x = self._feed()["rows"][0]
        self.assertEqual(x["foto"], "/api/portal_inmueble_foto?id=uno&n=0")
        self.assertNotIn("/uploads/", str(x["foto"]))

    def test_una_foto_desmarcada_no_se_sirve(self):
        """`visible_portal` la respetaba el portal del propietario y el escaparate
        no."""
        self._publica("uno")
        self._foto("uno", "a.jpg", visible=0)
        self.assertIsNone(self._feed()["rows"][0]["foto"])
        self.assertEqual(self._pide("?id=uno&n=0")[0], 404)

    def test_ni_colandose_por_el_numero_de_otra(self):
        """La desmarcada no puede pedirse corriendo el índice."""
        self._publica("uno")
        self._foto("uno", "a.jpg", visible=1, contenido=b"visible")
        self._foto("uno", "bb.jpg", visible=0, contenido=b"secreta")
        self.assertEqual(self._pide("?id=uno&n=0")[1], b"visible")
        self.assertEqual(self._pide("?id=uno&n=1")[0], 404)

    def test_de_un_inmueble_sin_publicar_no(self):
        """La llave es la misma consulta que arma el feed, no una condición
        parecida."""
        self._publica("oculto", portal_publicado=0)
        self._foto("oculto", "a.jpg")
        self.assertEqual(self._pide("?id=oculto&n=0")[0], 404)

    def test_ni_de_uno_que_no_existe(self):
        self.assertEqual(self._pide("?id=noexiste&n=0")[0], 404)
        self.assertEqual(self._pide("?id=&n=0")[0], 404)

    def test_no_se_puede_pedir_un_fichero_cualquiera(self):
        """Va por posición, no por ruta: no hay parámetro con el que nombrar un
        fichero del disco."""
        self._publica("uno")
        self._foto("uno", "a.jpg")
        for n in ("../../../etc/passwd", "-1", "99", "hola"):
            estado, _c, _t = self._pide(f"?id=uno&n={urllib.parse.quote(str(n))}")
            self.assertIn(estado, (200, 404), n)
        self.assertEqual(self._pide("?id=uno&n=0")[1], b"\xff\xd8\xff\xe0jpeg")

    def test_la_galeria_va_por_posiciones(self):
        self._publica("uno")
        self._foto("uno", "a.jpg")
        self._foto("uno", "bb.jpg")
        x = self._feed("?id=uno&galeria=1")["rows"][0]
        self.assertEqual(x["fotos"], ["/api/portal_inmueble_foto?id=uno&n=0",
                                      "/api/portal_inmueble_foto?id=uno&n=1"])
