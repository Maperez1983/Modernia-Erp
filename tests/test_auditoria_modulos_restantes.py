"""Seguros, RRHH, financiación y documental: los 154 endpoints que faltaban.

Inmobiliaria y fincas ya tenían su barrido; gestoría lo cubre `test_auditoria_gestoria`.
Estos cuatro módulos no los había tocado nadie, y salieron tres fallos que no se ven
leyendo el código —los tres eran el mismo tipo de descuido, no un error de lógica—:

- `hipotecas_firmadas_pdf` leía `payload` estando en el manejador de GET, donde esa
  variable no existe. Reventaba **siempre**: nadie ha podido descargar nunca ese PDF.
- `workspace_rrhh_nominas_import` convertía el mes a entero antes de validarlo, así que
  un «2026-08» —la forma en que se escribe un periodo en el resto del CRM— daba un 500
  en vez del «month inválido» que el propio código tiene diez líneas más abajo.
- `fin_checklist_generate` seguía adelante cuando el asesoramiento no existía e
  insertaba tareas colgadas de un id ausente, hasta que saltaba la clave ajena.

Un 500 no es sólo una pantalla fea: en Postgres deja la transacción abortada y todo lo
que venga después en la misma petición muere con ella.
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

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

from web import server as S  # noqa: E402

AHORA = "2026-08-18 09:00:00"
CLAVE = "Auditoria1234!"


class Casa(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "a.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Grupo Modernia", nif="B29123456",
                                   activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="auditora",
                                   email="a@x.test", rol="Administrador", activo=1,
                                   servicio="Administración,Seguros,RRHH,Financiaciones",
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **base))
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "auditora",
                                                "password": CLAVE}, cookie=False)["cookie"]

    def tearDown(self):
        self.httpd.shutdown(); self.conn.close()
        if self._prev is not None: S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _lanzar(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo, g = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "cuerpo": cuerpo,
                        "cookie": g.split(";")[0] if g else None, "json": self._json(cuerpo)}
        except urllib.error.HTTPError as e:
            cuerpo = e.read()
            return {"estado": e.code, "cuerpo": cuerpo, "cookie": None, "json": self._json(cuerpo)}

    def _get(self, ruta, cookie=True):
        req = urllib.request.Request(self.base + ruta, method="GET")
        if cookie: req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    def _post(self, ruta, cuerpo, cookie=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        if cookie: req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    @staticmethod
    def _json(cuerpo):
        try: return json.loads(cuerpo.decode("utf-8"))
        except Exception: return None


class NingunoDeLosCuatroModulosRevientaTests(Casa):
    FAMILIAS = ("seguro", "rrhh", "registro_horario", "nomina", "ausencia",
                "hipoteca", "documento", "docs", "ocr", "s3_")

    def _rutas(self):
        """Gestoría queda fuera a propósito: tiene su propia auditoría en
        `test_auditoria_gestoria`, y dos barridos editando los mismos manejadores a la
        vez se pisan. `/api/gestoria_docs` revienta con la misma clave ajena que los de
        aquí —inserta con un `cliente_id` que no comprueba— y está anotado para que lo
        arregle quien lleva ese módulo."""
        import re
        return sorted({r for r in re.findall(r'"(/api/[a-z_0-9]+)"', SERVER)
                       if (any(f in r for f in self.FAMILIAS) or r.startswith("/api/fin_"))
                       and "gestoria" not in r})

    def test_ni_con_get_ni_con_post(self):
        import urllib.parse
        saco = urllib.parse.urlencode({
            "workspace_id": self.ws, "empresa_id": "emp1", "id": "cli1",
            "cliente_id": "cli1", "persona_id": "p1", "usuario_id": "u1",
            "asesoramiento_id": "fa1", "year": "2026", "month": "2026-08",
            "periodo": "2026-08", "ejercicio": "2026", "key": "docs/x.pdf", "limit": "50"})
        cuerpo = dict(urllib.parse.parse_qsl(saco))
        cuerpo.update({"nombre": "Prueba", "email": "p@x.test", "importe": 100})
        rutas = self._rutas()
        self.assertGreater(len(rutas), 120, "no reconozco los endpoints de estos módulos")
        rotos = []
        for ruta in rutas:
            for etiqueta, r in (("GET", self._get(f"{ruta}?{saco}")),
                                ("POST", self._post(ruta, cuerpo))):
                if r["estado"] >= 500:
                    rotos.append((etiqueta, ruta, r["estado"], str(r["json"])[:110]))
        self.assertEqual(rotos, [], f"revientan: {rotos}")


class LosTresQueSalieronTests(Casa):
    def test_el_pdf_de_hipotecas_firmadas_no_muere_al_abrirlo(self):
        """Leía `payload` en un GET: `UnboundLocalError` en el 100 % de las llamadas."""
        r = self._get("/api/hipotecas_firmadas_pdf?empresa_id=emp1&year=2026")
        self.assertLess(r["estado"], 500, r["json"])

    def test_un_mes_mal_escrito_es_un_400_y_no_un_500(self):
        r = self._post("/api/workspace_rrhh_nominas_import",
                       {"workspace_id": self.ws, "doc_key": "x.pdf",
                        "year": "2026", "month": "2026-08"})
        self.assertEqual(r["estado"], 400, r["json"])
        self.assertIn("month", str(r["json"]))

    def test_un_asesoramiento_que_no_existe_es_un_404(self):
        """Insertaba tareas colgadas de un id ausente hasta que saltaba la clave ajena."""
        r = self._post("/api/fin_checklist_generate",
                       {"workspace_id": self.ws, "asesoramiento_id": "no-existe"})
        self.assertEqual(r["estado"], 404, r["json"])

    def test_las_expresiones_regulares_de_los_portales_van_escapadas(self):
        """El JS de los portales viaja dentro de una cadena de Python: un `\\d` suelto
        avisa hoy y será un error de sintaxis en una versión próxima."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(SERVER, "server.py", "exec")


if __name__ == "__main__":
    unittest.main()
