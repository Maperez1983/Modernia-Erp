"""Todo lo publicado salía anunciado por «Grupo Modernia», fuera de quien fuera.

`portal_inmuebles` es lo que ve alguien de fuera. La consulta ya traía `e.nombre` y
`e.logo_url` de la empresa dueña del inmueble, pero el armador de la respuesta pública no
los miraba: escribía el nombre y el logotipo de la casa a pelo.

Hoy no se nota, porque todo lo publicado es de la misma agencia. El día que publique la
segunda, sus pisos saldrían en el escaparate con la marca de otra —y con su teléfono de
contacto—, que es un problema de quien te ha confiado la exclusiva, no de estética.

De paso quedaba escrito y sin enganchar `/api/portal_empresa_logo`, que es justamente el
que sirve el logotipo de cada agencia a un visitante sin cuenta. Ahora está en la lista
pública de GET, y sólo responde si esa empresa tiene algo publicado: no vale para pasear
el directorio de empresas del CRM desde fuera.

Lo que se anuncia es un **nombre comercial** propio, no el nombre interno de la empresa
ni su razón social. Al arreglarlo mirando el nombre de la empresa, los seis anuncios de
producción pasaron a decir «Estudio Velazquez 2012 SL»: correcto en la base y malo en un
escaparate, porque nadie busca piso a una razón social. El campo va en la ficha de la
empresa y en blanco se anuncia con la marca del grupo, que es lo que había siempre.
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

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
LOGO_REAL = "/assets/grupo_modernia_logo.png"
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
AHORA = "2026-08-23 09:00:00"


class ElAnuncioLlevaSuAgenciaTests(unittest.TestCase):
    SERVER = SERVER

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        self.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables",
                   "ensure_anuncio_schema"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        b = dict(created_at=AHORA, updated_at=AHORA)
        # Dos agencias distintas publicando en el mismo escaparate.
        # La primera tiene nombre de escaparate; la segunda no lo ha puesto.
        self._ins("empresas", dict(id="emp1", nombre="Inmobiliaria Sur SL",
                                   razon_social="Inmobiliaria Sur 2012 S.L.",
                                   nombre_comercial="Pisos del Sur",
                                   nif="B29111111", activo=1, logo_url=LOGO_REAL, **b))
        self._ins("empresas", dict(id="emp2", nombre="Fincas Poniente SL",
                                   nif="B29222222", activo=1, **b))
        # Y una tercera sin nada publicado.
        self._ins("empresas", dict(id="emp9", nombre="Sin anuncios SL",
                                   nif="B29999999", activo=1, logo_url=LOGO_REAL, **b))
        for i, emp in enumerate(("emp1", "emp2", "emp9"), start=1):
            self._ins("workspace_empresas", dict(id=f"we{i}", workspace_id=self.ws,
                                                 empresa_id=emp, **b))
        for i, (emp, calle) in enumerate((("emp1", "Calle Sur 1"),
                                          ("emp2", "Calle Poniente 2")), start=1):
            self._ins("inmuebles", dict(id=f"inm{i}", workspace_id=self.ws, empresa_id=emp,
                                        direccion=calle, poblacion="Málaga",
                                        estado="Encargo", tipo_operacion="venta",
                                        precio_encargo=250000, portal_publicado=1,
                                        descripcion="Piso exterior", **b))
            self._ins("captaciones", dict(id=f"cap{i}", workspace_id=self.ws,
                                          empresa_id=emp, inmueble_id=f"inm{i}",
                                          etapa="Encargo", noticia_verificada=1, **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]

    def _ins(self, tabla, datos):
        cols = {c[1] for c in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _get(self, ruta, **params):
        """Sin galleta: es lo que ve alguien de fuera."""
        url = f"http://127.0.0.1:{self.puerto}{ruta}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.status, r.read(), r.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), None

    def _anuncios(self):
        estado, crudo, _ = self._get("/api/portal_inmuebles")
        self.assertEqual(estado, 200, crudo[:200])
        cuerpo = json.loads(crudo or b"{}")
        filas = cuerpo.get("rows") or cuerpo.get("inmuebles") or []
        return {str(f.get("direccion")): f for f in filas}

    def test_cada_piso_se_anuncia_con_la_marca_de_su_agencia(self):
        anuncios = self._anuncios()
        self.assertEqual(len(anuncios), 2, anuncios)
        self.assertEqual(anuncios["Calle Sur 1"]["empresa_nombre"], "Pisos del Sur")

    def test_no_se_publica_la_razon_social_ni_el_nombre_interno(self):
        """Fue lo que pasó en producción al mirar el nombre de la empresa."""
        anuncio = self._anuncios()["Calle Sur 1"]
        for texto in ("S.L.", "SL", "Inmobiliaria Sur"):
            self.assertNotIn(texto, str(anuncio["empresa_nombre"]))

    def test_la_que_no_lo_ha_puesto_se_anuncia_con_la_marca_del_grupo(self):
        """En blanco no se cae a la razón social: se cae a lo que había siempre."""
        self.assertEqual(self._anuncios()["Calle Poniente 2"]["empresa_nombre"],
                         "Grupo Modernia")

    def test_el_nombre_comercial_se_guarda_desde_la_ficha_de_la_empresa(self):
        """Si no se puede editar, el campo no sirve de nada."""
        self.assertIn('name="nombre_comercial"',
                      (RAIZ / "web" / "index.html").read_text(encoding="utf-8"))
        self.assertIn('set("nombre_comercial"',
                      (RAIZ / "web" / "app.js").read_text(encoding="utf-8"))
        self.assertIn('if "nombre_comercial" in payload:', self.SERVER)
        self.assertIn("COALESCE(nombre_comercial, '') AS nombre_comercial", self.SERVER)

    def test_y_con_su_logotipo(self):
        self.assertEqual(self._anuncios()["Calle Sur 1"]["empresa_logo"], LOGO_REAL)

    def test_la_que_no_tiene_logo_se_cae_a_la_marca_de_la_casa(self):
        """Mejor el logotipo del grupo que un hueco en el escaparate."""
        self.assertEqual(self._anuncios()["Calle Poniente 2"]["empresa_logo"],
                         "/assets/grupo_modernia_logo.png")

    def test_el_logotipo_se_sirve_a_quien_entra_sin_cuenta(self):
        estado, crudo, tipo = self._get("/api/portal_empresa_logo", id="emp1")
        self.assertEqual(estado, 200, crudo[:200])
        self.assertEqual(tipo, "image/png")
        self.assertGreater(len(crudo), 0)

    def test_pero_no_sirve_para_pasear_el_directorio_de_empresas(self):
        """Una empresa sin nada publicado no existe para el mundo de fuera."""
        self.assertEqual(self._get("/api/portal_empresa_logo", id="emp9")[0], 404)

    def test_una_empresa_inventada_tampoco_dice_nada(self):
        self.assertEqual(self._get("/api/portal_empresa_logo", id="emp-que-no-existe")[0], 404)

    def test_un_logotipo_en_s3_se_sirve(self):
        """`_normalize_s3_key` espera la clave, no la URI.

        Pasarle el «s3://» entero dejaba la comprobación del prefijo en falso siempre,
        así que ningún logotipo guardado en S3 llegaba a servirse. En producción todos
        los que tienen logotipo propio lo tienen así. No se llegó a notar porque el
        endpoint no era alcanzable: en cuanto lo fue, salió."""
        clave = ("s3://company_logos/20260408_204404_6aab4d1b_empresa_"
                 "ceff9019-5715-4867-a8a5-31ecf447020b_1775681044215.jpg")
        self.assertEqual(S._normalize_s3_key(clave[5:]),
                         clave[5:],
                         "la clave sale distinta de lo que se guardó")
        self.assertTrue(S._normalize_s3_key(clave[5:]).startswith("company_logos/"))
        # Y el manejador la trocea igual que el generador de informes, que sí funciona.
        ini = self.SERVER.index('if path == "/api/portal_empresa_logo":')
        manejador = self.SERVER[ini:ini + 2500]
        self.assertIn("_normalize_s3_key(logo_url[5:])", manejador)

    def test_si_su_logotipo_no_se_puede_servir_no_queda_un_hueco(self):
        """La clave de S3 puede no resolver. Quien mira el anuncio no tiene la culpa."""
        self.conn.execute("UPDATE empresas SET logo_url = 's3://company_logos/no-existe.jpg' "
                          "WHERE id = 'emp1'")
        self.conn.commit()
        estado, crudo, tipo = self._get("/api/portal_empresa_logo", id="emp1")
        self.assertEqual(estado, 200, crudo[:200])
        self.assertEqual(tipo, "image/png")
        self.assertGreater(len(crudo), 0)

    def test_pero_eso_no_abre_la_puerta_a_quien_no_publica(self):
        """El respaldo es para el escaparate, no un 200 para cualquier id."""
        self.conn.execute("UPDATE empresas SET logo_url = 's3://company_logos/no-existe.jpg' "
                          "WHERE id = 'emp9'")
        self.conn.commit()
        self.assertEqual(self._get("/api/portal_empresa_logo", id="emp9")[0], 404)

    def test_la_ruta_esta_dada_de_alta_como_publica(self):
        """El manejador llevaba escrito desde antes; lo que faltaba era la lista."""
        self.assertIn("/api/portal_empresa_logo", S.AUTH_PUBLIC_GET_ENDPOINTS)

    def test_un_alquilado_no_sigue_en_el_escaparate(self):
        self.conn.execute("UPDATE inmuebles SET estado = 'Alquilado' WHERE id = 'inm1'")
        self.conn.commit()
        self.assertNotIn("Calle Sur 1", self._anuncios())


if __name__ == "__main__":
    unittest.main()
