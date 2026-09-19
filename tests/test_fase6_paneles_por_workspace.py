"""Fase 6 del ámbito por workspace (2026-09-19): los dos paneles que contaban mal.

Medido en producción: contar por workspace y por "las empresas del workspace" coincidía
en 156 combinaciones de tabla y workspace. Las diferencias reales eran dos:

- 788 documentos de gestoría (754 de renta sin empresa) que el hub de documentos no
  veía porque contaba por empresa.
- 4 filas de demostración de DEMOCASA (2 acciones, 1 captación, 1 inmueble) creadas con
  una empresa de Modernia, que los paneles de inmobiliaria de Modernia sumaban.
"""

import tempfile
import unittest
from pathlib import Path

from web import server as S

AHORA = "2026-09-19 09:00:00"


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "p.sqlite"
        S.ensure_tables(db)
        self.c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(self.c.close)
        self.c.commit()
        self.c.execute("PRAGMA foreign_keys = OFF")
        self.ins("workspaces", dict(id="wsMod", nombre="Modernia", slug="mod-prueba", estado="Activo"))
        self.ins("workspaces", dict(id="wsDemo", nombre="Demo", slug="demo-prueba", estado="Activo"))
        self.ins("empresas", dict(id="empMod", nombre="Grupo Prueba SL", nif="B11111111", activo=1))
        self.ins("workspace_empresas", dict(id="l1", workspace_id="wsMod", empresa_id="empMod"))

    def ins(self, tabla, datos):
        datos = {"created_at": AHORA, "updated_at": AHORA, **datos}
        cols = {c[1] for c in self.c.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.c.execute(
            f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()),
        )
        self.c.commit()


class InmobiliariaTests(_Base):
    def test_los_datos_de_demostracion_de_otro_workspace_no_se_cuentan(self):
        self.ins("inmuebles", dict(id="iMod", empresa_id="empMod", workspace_id="wsMod", direccion="Calle Real 1"))
        # El de DEMOCASA: misma empresa, otro workspace.
        self.ins("inmuebles", dict(id="iDemo", empresa_id="empMod", workspace_id="wsDemo", direccion="Calle Demo 1"))
        resumen = S.fetch_workspace_inmo_overview(self.c, "wsMod")
        self.assertEqual(resumen["counts"]["inmuebles"], 1)
        self.assertEqual(S.fetch_workspace_inmo_overview(self.c, "wsDemo")["counts"]["inmuebles"], 1)


class HubDeDocumentosTests(_Base):
    def test_el_documento_sin_empresa_del_workspace_se_ve(self):
        self.ins("gestoria_docs", dict(id="dSin", empresa_id=None, workspace_id="wsMod", nombre="Renta 2025",
                                       tipo="renta", doc_url="https://x/y.pdf"))
        self.ins("gestoria_docs", dict(id="dOtro", empresa_id=None, workspace_id="wsDemo", nombre="De otro",
                                       tipo="renta", doc_url="https://x/z.pdf"))
        hub = S.fetch_workspace_document_hub(self.c, "wsMod", limit=20)
        self.assertEqual([r["id"] for r in hub["rows"]], ["dSin"])


class CodigoTests(unittest.TestCase):
    SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

    def test_el_panel_de_inicio_de_inmobiliaria_va_por_workspace(self):
        i = self.SERVER.index('if path == "/api/inmo_inicio_dashboard":')
        bloque = self.SERVER[i : self.SERVER.index('\n        if path == "/api/', i + 20)]
        self.assertEqual(bloque.count("WHERE {ambito_sql}"), 15)
        self.assertNotIn("WHERE empresa_id IN ({placeholders})", bloque)
        self.assertIn("if not empresa_ids and not workspace_id:", bloque)


if __name__ == "__main__":
    unittest.main()
