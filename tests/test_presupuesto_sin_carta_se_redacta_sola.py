"""Un presupuesto de fincas ya no puede salir sin carta de presentación.

Detectado al generar el presupuesto real de la Comunidad de Propietarios Avenida
Juan XXIII 43: el PDF llegó sin carta ni foto de equipo, porque `carta_presentacion`
se guardaba tal cual llegara del formulario y el formulario la deja vacía salvo que
alguien pulse a mano «Generar carta». Como la foto del equipo del PDF solo se pega
cuando hay carta (ver `build_workspace_budget_pdf`), el fallo se notaba doble.

Ahora, si al guardar un presupuesto de fincas la carta llega vacía, el servidor la
redacta él mismo con la primera plantilla disponible — el mismo texto que ya
generaba `/api/workspace_fincas_carta`, factorizado en `generate_default_fincas_carta`
para no tener la lógica dos veces.

Segundo fallo, distinto pero encontrado en el mismo presupuesto: el selector
«Empresa emisora» mandaba el id de `workspace_companies` (la tabla nueva), pero
`fetch_workspace_budget_pdf_payload` resuelve la empresa contra la tabla legacy
`empresas` — el mismo id que ya usa `state.currentWorkspaceCompanyId` en el resto
de la aplicación. El presupuesto se guardaba igual, pero la empresa no resolvía:
nombre y logo salían vacíos y el registro no aparecía en los listados filtrados por
empresa. El fix vive en `hydrateWorkspaceCompanySelects` (web/app.js): las
`<option>` de empresa ahora llevan `legacy_empresa_id` cuando existe, no `id`.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))

from web import server as S  # noqa: E402

AHORA = "2026-08-24 09:00:00"
CLAVE = "Fincas1234!"


class PresupuestoDeFincasSinCartaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fincas.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp-legacy-1", nombre="Fincas Velazquez",
                                    razon_social="Fincas Velázquez.sl", nif="B72661374",
                                    direccion="Calle Velázquez 11, Málaga", activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                              empresa_id="emp-legacy-1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana Administradora", usuario="administradora",
                                    email="ana@fincas.test", rol="Administrador", servicio="Fincas",
                                    activo=1, password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws, usuario_id="u1",
                                              rol="Owner", **base))
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "administradora", "password": CLAVE},
                                  cookie=False)["cookie"]

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
                                      headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo_resp, galleta = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "cookie": galleta.split(";")[0] if galleta else None,
                        "json": json.loads(cuerpo_resp.decode("utf-8"))}
        except urllib.error.HTTPError as e:
            return {"estado": e.code, "cookie": None, "json": json.loads(e.read().decode("utf-8"))}

    def _crear_presupuesto(self, **overrides):
        payload = dict(
            workspace_id=self.ws, empresa_id="emp-legacy-1", servicio="fincas",
            titulo="Administración de comunidad · C.P. de prueba",
            comunidad_denominacion="C.P. de prueba", comunidad_direccion="Calle Falsa 1, Málaga",
            num_vecinos="24", num_locales="2", num_trasteros="0", num_aparcamientos="10",
        )
        payload.update(overrides)
        r = self._post("/api/workspace_presupuestos", payload)
        self.assertEqual(r["estado"], 200, r["json"])
        return r["json"]

    def test_sin_carta_en_el_payload_se_redacta_sola(self):
        res = self._crear_presupuesto()
        fila = self.conn.execute(
            "SELECT calculo_json FROM workspace_presupuestos WHERE id = ?", (res["id"],)
        ).fetchone()
        calc = json.loads(fila["calculo_json"])
        self.assertTrue(calc.get("carta_presentacion", "").strip())

    def test_la_carta_generada_menciona_la_comunidad(self):
        res = self._crear_presupuesto(comunidad_denominacion="Comunidad Torre del Mar 7")
        fila = self.conn.execute(
            "SELECT calculo_json FROM workspace_presupuestos WHERE id = ?", (res["id"],)
        ).fetchone()
        calc = json.loads(fila["calculo_json"])
        self.assertIn("Torre del Mar 7", calc["carta_presentacion"])

    def test_una_carta_escrita_a_mano_no_se_pisa(self):
        res = self._crear_presupuesto(carta_presentacion="Texto redactado por la administradora.")
        fila = self.conn.execute(
            "SELECT calculo_json FROM workspace_presupuestos WHERE id = ?", (res["id"],)
        ).fetchone()
        calc = json.loads(fila["calculo_json"])
        self.assertEqual(calc["carta_presentacion"], "Texto redactado por la administradora.")

    def test_fuera_de_fincas_no_se_inventa_una_carta(self):
        res = self._crear_presupuesto(servicio="gestoria", titulo="Gestoría · Cliente de prueba")
        fila = self.conn.execute(
            "SELECT calculo_json FROM workspace_presupuestos WHERE id = ?", (res["id"],)
        ).fetchone()
        calc = json.loads(fila["calculo_json"] or "{}")
        self.assertNotIn("carta_presentacion", calc)

    def test_al_editar_sin_carta_tambien_se_redacta(self):
        """`buildWorkspacePresupuestoUpdatePayloadFromRow` reenvía lo que ya hubiera
        en `calc.carta_presentacion`; si seguía vacío, también se rellena al guardar."""
        primero = self._crear_presupuesto()
        segundo = self._post("/api/workspace_presupuestos", dict(
            id=primero["id"], workspace_id=self.ws, empresa_id="emp-legacy-1", servicio="fincas",
            titulo="Administración de comunidad · C.P. de prueba",
            comunidad_denominacion="C.P. de prueba", comunidad_direccion="Calle Falsa 1, Málaga",
            num_vecinos="24", num_locales="2", num_trasteros="0", num_aparcamientos="10",
        ))["json"]
        self.assertEqual(segundo["id"], primero["id"])
        fila = self.conn.execute(
            "SELECT calculo_json FROM workspace_presupuestos WHERE id = ?", (primero["id"],)
        ).fetchone()
        calc = json.loads(fila["calculo_json"])
        self.assertTrue(calc.get("carta_presentacion", "").strip())


class ElSelectorDeEmpresaMandaElIdLegacyTests(unittest.TestCase):
    """El id de `workspace_companies` no resuelve en `fetch_workspace_budget_pdf_payload`
    (que hace `LEFT JOIN empresas e ON e.id = p.empresa_id`): un presupuesto creado con
    ese id se guardaba, pero la empresa salía en blanco y no aparecía en los listados
    filtrados por empresa. El resto de la aplicación ya resuelve esto con
    `legacy_empresa_id` (ver `setWorkspaceCompanyContext`); el selector de presupuestos
    era el único que mandaba el id nuevo a pelo.
    """

    def _cuerpo(self):
        i = APP.index("const hydrateWorkspaceCompanySelects")
        return APP[i: APP.index("\n};", i) + 3]

    def test_hay_un_resolutor_de_id_legacy(self):
        self.assertIn("const companyLegacyId = (row) =>", APP)
        self.assertIn("row?.legacy_empresa_id || row?.id", APP)

    def test_las_opciones_de_fincas_usan_el_id_legacy(self):
        cuerpo = self._cuerpo()
        self.assertIn("companyLegacyId(c)", cuerpo)
        self.assertNotIn('option value="${escapeHtml(String(c.id))}"', cuerpo)

    def test_las_opciones_generales_tambien_usan_el_id_legacy(self):
        cuerpo = self._cuerpo()
        self.assertIn("companyLegacyId(row)", cuerpo)

    def test_el_alta_por_defecto_de_fincas_usa_el_id_legacy(self):
        cuerpo = self._cuerpo()
        self.assertIn("select.value = companyLegacyId(paraAltasNuevas)", cuerpo)
        self.assertNotIn("select.value = paraAltasNuevas.id", cuerpo)


if __name__ == "__main__":
    unittest.main()
