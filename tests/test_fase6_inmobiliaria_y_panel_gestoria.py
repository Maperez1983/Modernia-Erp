"""Fase 6 del ámbito por workspace (2026-09-19): inmobiliaria y panel de gestoría.

- Inmuebles, demandas, visitas y compraventas tenían el mismo "o sin workspace de una
  empresa del workspace" que se quitó en clientes: sobra desde la fase 1 (todas las
  filas lo llevan) y veía las de otro workspace con la empresa compartida.
- Panel de gestoría: documentos y presupuestos se acotan por el workspace de la fila, y
  el resumen de documentos de renta también. Ese resumen contaba además los documentos
  de "cualquier cliente con renta" sin mirar el workspace, y dejaba fuera los 754
  documentos de renta sin empresa. Los clientes de gestoría siguen por su vínculo con
  el servicio de la sociedad, que es lo que los define.
"""

import unittest
from pathlib import Path

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


def _bloque(ruta):
    i = SERVER.index(f'if path == "{ruta}":')
    return SERVER[i : SERVER.index('\n        if path == "/api/', i + 20)]


class InmobiliariaTests(unittest.TestCase):
    def test_sin_respaldo_por_empresa_cuando_hay_workspace(self):
        for ruta, alias in (("/api/inmuebles", "i."), ("/api/demandas", "d."), ("/api/visitas", "v."),
                            ("/api/compraventas", "")):
            with self.subTest(ruta=ruta):
                bloque = _bloque(ruta)
                self.assertNotIn(f"COALESCE({alias}workspace_id, '') = '' AND {alias}empresa_id IN", bloque)
                self.assertIn(f"COALESCE({alias}workspace_id, '') = ?", bloque)


class PanelGestoriaTests(unittest.TestCase):
    def test_documentos_y_presupuestos_por_workspace(self):
        bloque = _bloque("/api/gestoria_dashboard")
        self.assertIn("def _ambito_panel(alias):", bloque)
        self.assertEqual(bloque.count('WHERE {_ambito_panel("p")[0]}'), 3)
        self.assertIn('WHERE {_ambito_panel("d")[0]}', bloque)
        self.assertNotIn("WHERE p.empresa_id IN ({placeholders_emp})", bloque)
        self.assertIn("workspace_id=workspace_id,", bloque)

    def test_la_cache_distingue_el_workspace(self):
        bloque = _bloque("/api/gestoria_dashboard")
        self.assertIn('cache_key_base = f"{workspace_id}::{cache_key_base}"', bloque)

    def test_el_resumen_de_renta_con_workspace_no_suma_otros(self):
        i = SERVER.index("def compute_gestoria_renta_docs_summary(")
        cuerpo = SERVER[i : SERVER.index("\ndef ", i + 10)]
        self.assertIn('workspace_id=""', cuerpo.split("\n")[0])
        self.assertIn("ambito_docs = \"COALESCE(d.workspace_id, '') = ?\"", cuerpo)


if __name__ == "__main__":
    unittest.main()
