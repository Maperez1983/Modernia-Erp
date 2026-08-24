"""En un móvil, un listado de diez columnas perdía cinco por el camino.

`app.js` pinta del orden de **137 tablas** y sólo una llevaba la clase `ui-table`. Sin
ella, una tabla no se apila en tarjetas como manda el sistema de diseño; y como el propio
sistema desactiva el scroll horizontal por debajo de 760 px, lo que sobra se corta y no
hay forma de llegar a ello.

En un listado de asientos de diez columnas se veían Fecha, Nº asiento, Concepto, Cliente
y media de Cuenta. **Debe, Haber, Factura, Punteo y Acciones no existían** para quien
mira desde el teléfono.

El arreglo no toca las 137 llamadas —son 137 sitios donde equivocarse— sino que es una
pieza que envuelve cualquier tabla y le pone a cada celda de qué columna es, y un
observador que la aplica también a las que se pintan después. Se prueba y se quita de
una vez si molesta.

Cuatro formas de tabla que se dan en el CRM y que no puede romper:

  · la pelada, que es el caso normal
  · la que ya lleva `ui-table`, que no debe envolverse dos veces
  · la que no tiene cabecera, que se envuelve pero no se puede etiquetar
  · la que tiene una fila de «sin resultados» con `colspan`, donde la posición ya no
    dice la columna y etiquetar mal es peor que no etiquetar
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


class TodasLasTablasSeVenEnMovilTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node no está disponible")
        guion = RAIZ / "tests" / "_barrido_de_tablas.js"
        r = subprocess.run(["node", str(guion)], capture_output=True, text=True,
                           cwd=str(RAIZ), timeout=180)
        if r.returncode:
            if "Cannot find module 'jsdom'" in (r.stderr or ""):
                raise unittest.SkipTest("falta jsdom: ejecuta `npm install` en la raíz")
            raise AssertionError(f"node falló:\n{r.stdout}\n{r.stderr}")
        cls.r = json.loads(r.stdout)

    # --- la tabla normal --------------------------------------------------------

    def test_una_tabla_pelada_entra_en_el_sistema_de_diseño(self):
        self.assertEqual(self.r["a"]["padreDeLaTabla"], "ui-table ui-table-scroll")

    def test_y_cada_celda_dice_de_qué_columna_es(self):
        """Apilada no hay cabecera: sin esto son valores sueltos sin nombre."""
        self.assertEqual(self.r["a"]["etiquetas"], [["Fecha", "Concepto", "Importe"]])

    # --- lo que no puede romper ---------------------------------------------------

    def test_la_que_ya_tenía_ui_table_no_se_envuelve_dos_veces(self):
        self.assertEqual(self.r["b"]["envoltorios"], 1)
        self.assertEqual(self.r["b"]["tablasDentro"], 1)

    def test_y_respeta_las_etiquetas_que_ya_tenía(self):
        self.assertEqual(self.r["b"]["etiquetas"], [["Uno", "Dos"]])

    def test_una_tabla_sin_cabecera_se_envuelve_pero_no_se_inventa_etiquetas(self):
        self.assertEqual(self.r["c"]["padreDeLaTabla"], "ui-table ui-table-scroll")
        self.assertEqual(self.r["c"]["etiquetas"], [[None, None]])

    def test_una_fila_de_sin_resultados_no_se_etiqueta_mal(self):
        """Con `colspan` la posición ya no dice la columna."""
        colspan, normal = self.r["d"]["etiquetas"]
        self.assertEqual(colspan, [None])
        self.assertEqual(normal, ["A", "B", "C"])

    def test_pasarlo_dos_veces_no_cambia_nada(self):
        """El observador lo llama en cada repintado: tiene que ser inofensivo."""
        # El guión ya lo ejecuta dos veces; si no fuera idempotente habría dos
        # envoltorios o etiquetas duplicadas.
        for caja in ("a", "b", "c", "d"):
            self.assertEqual(self.r[caja]["tablasDentro"], 1, caja)
            self.assertEqual(self.r[caja]["envoltorios"], 1, caja)

    # --- y que la pieza siga estando ------------------------------------------------

    def test_hay_un_observador_para_las_que_se_pintan_después(self):
        """Casi todas las tablas del CRM aparecen al cargar datos, no al abrir la página."""
        self.assertIn("vigilaLasTablasQueLleguen", APP)
        i = APP.index("const vigilaLasTablasQueLleguen")
        cuerpo = APP[i:i + 1200]
        self.assertIn("MutationObserver", cuerpo)
        # Sin escucharse a sí mismo: envolver una tabla es otra mutación.
        self.assertIn("observador.disconnect()", cuerpo)
        # Y agrupado, que pintar una tabla dispara muchas mutaciones seguidas.
        self.assertIn("requestAnimationFrame", cuerpo)

    def test_y_se_arranca(self):
        self.assertIn("\nvigilaLasTablasQueLleguen();", APP)

    def test_el_barrido_no_se_hizo_a_mano_en_137_sitios(self):
        """Si alguien lo desmonta y vuelve a etiquetar una a una, que se note."""
        self.assertGreater(len(re.findall(r'createElement\("table"\)', APP)), 90)
        self.assertIn("son 137 sitios donde equivocarse", APP)


if __name__ == "__main__":
    unittest.main()
