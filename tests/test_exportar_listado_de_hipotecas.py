"""Imprimir el listado de hipotecas daba "empresa_nombre requerido".

Reproducido en producción el 2026-08-04 filtrando 2026 + Firmada y pulsando
"PDF listado": la aplicación avisaba

    No se pudo imprimir el listado. empresa_nombre requerido

y no salía nada. No era la lista blanca de rutas —eso se arregló antes—, sino la
puerta de ámbito: `server.py` exige `empresa_nombre` en **todo** POST salvo que la
ruta esté exenta o que el cuerpo traiga `workspace_id` (`empresa_scope_exempt`,
la condición `or bool(payload_workspace_id)`).

Por qué justo aquí. El front tiene un enriquecedor, `attachEmpresaIdForServiceRequest`,
que añade `workspace_id` solo, y solo pasa por él lo que se envía con `apiPost` o
`postJsonWithDbRetry`. Las dos exportaciones usan `fetch` crudo y `downloadPdfFromApi`,
así que se lo saltaban.

El `workspace_id` se pone en `getHipotecaBdtExportSelection`, que es de donde beben
los dos caminos: añadirlo en uno solo devolvería el fallo por el otro botón.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


class LaSeleccionLlevaElAmbitoTests(unittest.TestCase):
    def test_la_seleccion_de_exportacion_incluye_el_workspace(self):
        i = APP.index("const getHipotecaBdtExportSelection")
        bloque = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("workspaceId: String(state.currentWorkspaceId", bloque)


class LosDosCaminosLoMandanTests(unittest.TestCase):
    """Si solo lo mandara uno, el fallo volvería por el otro botón."""

    def _cuerpo(self, nombre):
        i = APP.index(f"const {nombre} = ")
        return APP[i: APP.index("\nconst ", i + 10)]

    def test_el_pdf_de_listado_manda_workspace_id(self):
        cuerpo = self._cuerpo("downloadHipotecaBdtPdf")
        self.assertIn("/api/hipotecas_export_pdf", cuerpo)
        self.assertIn("workspace_id: selection.workspaceId", cuerpo)

    def test_el_excel_manda_workspace_id(self):
        cuerpo = self._cuerpo("downloadHipotecaBdtExcel")
        self.assertIn("/api/hipotecas_listado_excel", cuerpo)
        self.assertIn("workspace_id: selection.workspaceId", cuerpo)


class LaPuertaDeAmbitoSigueSiendoLaQueCreemosTests(unittest.TestCase):
    """El arreglo depende de una regla del servidor; si cambia, hay que enterarse.

    Mandar `workspace_id` solo sirve mientras `empresa_scope_exempt` lo acepte como
    ámbito suficiente. El día que eso se toque, estos botones volverían a fallar y
    nadie relacionaría una cosa con la otra.
    """

    def test_llevar_workspace_id_exime_de_empresa_nombre(self):
        i = SERVER.index("empresa_scope_exempt = (")
        bloque = SERVER[i: SERVER.index("\n        )", i)]
        self.assertIn("or bool(payload_workspace_id)", bloque)

    def test_las_rutas_de_exportacion_no_estan_exentas_por_si_mismas(self):
        """No lo están, y por eso necesitan el workspace_id: que quede dicho."""
        i = SERVER.index("empresa_scope_exempt = (")
        bloque = SERVER[i: SERVER.index("\n        )", i)]
        for ruta in ("/api/hipotecas_export_pdf", "/api/hipotecas_listado_excel"):
            with self.subTest(ruta=ruta):
                self.assertNotIn(f'"{ruta}"', bloque)


if __name__ == "__main__":
    unittest.main()
