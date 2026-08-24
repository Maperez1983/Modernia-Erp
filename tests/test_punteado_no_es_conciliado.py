"""Un emparejamiento con cero de confianza salía en verde como «Punteado».

El conciliador bancario empareja cada movimiento del extracto con un asiento y guarda
tres cosas: si está punteado, en qué estado dejó la conciliación (`auto`, `pendiente`…)
y con cuánta confianza. La pantalla sólo miraba la primera.

En producción hay **siete movimientos** así: `punteado = 1`, pero
`conciliacion_estado = 'pendiente'` y `conciliacion_confianza = 0.0`. O sea que el
emparejador automático los enlazó, no se fio nada, y los dejó marcados para revisar. La
tabla los pintaba en verde y el contador los sumaba a «Punteados».

Y había un detalle que lo empeoraba: junto a la etiqueta se enseñaba el porcentaje de
confianza **sólo si era distinto de cero**. Con confianza 0 —el caso más flojo de todos—
desaparecía justo la señal que habría avisado, y quedaba una etiqueta verde limpia.

Ahora hay tres estados: sin puntear (Pendiente), punteado con confianza suficiente
(Punteado) y punteado pero por validar (Por revisar, en ámbar, con el porqué en el
título). El porcentaje se enseña siempre que esté punteado, incluido el 0.

El umbral es 55, que es el mismo con el que el servidor cuenta los de «baja confianza»
al importar el extracto. Si aquí fuera otro, la pantalla y el resumen dirían cosas
distintas sobre los mismos movimientos.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


class LoQueSePintaTests(unittest.TestCase):
    """Ejecuta la función real que pinta la tabla, con jsdom, y mira lo que sale.

    Las comprobaciones de más abajo miran el código fuente; éstas miran el resultado,
    que es lo que ve quien concilia. Los cuatro movimientos son los mismos que siembra
    `scripts/contrasta_pantalla_con_la_base.py`.
    """

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node no está disponible")
        guion = RAIZ / "tests" / "_pinta_punteo_banco.js"
        r = subprocess.run(["node", str(guion)], capture_output=True, text=True, cwd=str(RAIZ))
        if r.returncode:
            if "Cannot find module 'jsdom'" in (r.stderr or ""):
                raise unittest.SkipTest("falta jsdom: ejecuta `npm install` en la raíz")
            raise AssertionError(f"node falló:\n{r.stdout}\n{r.stderr}")
        cls.pintado = json.loads(r.stdout)
        cls.por_concepto = {f["concepto"]: f for f in cls.pintado["filas"]}

    def test_el_conciliado_de_verdad_sale_en_verde(self):
        f = self.por_concepto["Transferencia ACME"]
        self.assertEqual(f["etiqueta"], "Punteado")
        self.assertIn("ok", f["clase"])
        self.assertIn("92%", f["celda"])

    def test_el_de_confianza_cero_ya_no_se_disfraza(self):
        """Era el caso exacto de los siete de producción."""
        f = self.por_concepto["Compra Apple.com"]
        self.assertEqual(f["etiqueta"], "Por revisar")
        self.assertIn("media", f["clase"])
        self.assertNotIn("ok", f["clase"])

    def test_y_enseña_el_cero_en_vez_de_esconderlo(self):
        self.assertIn("(0%)", self.por_concepto["Compra Apple.com"]["celda"])

    def test_y_dice_en_el_título_por_qué(self):
        titulo = self.por_concepto["Compra Apple.com"]["titulo"]
        self.assertIn("pendiente", titulo)
        self.assertIn("0 % de confianza", titulo)

    def test_el_punteado_con_poca_confianza_tambien_avisa(self):
        """Estado «auto», pero 40 % está por debajo del umbral."""
        f = self.por_concepto["Cuota gestoría"]
        self.assertEqual(f["etiqueta"], "Por revisar")
        self.assertIn("(40%)", f["celda"])

    def test_el_que_no_esta_punteado_sigue_en_rojo(self):
        f = self.por_concepto["Recibo luz"]
        self.assertEqual(f["etiqueta"], "Pendiente")
        self.assertIn("danger", f["clase"])

    def test_el_pie_separa_los_tres(self):
        """Antes decía «Punteados 3» de cuatro; dos de esos había que revisarlos."""
        self.assertEqual(self.pintado["pie"],
                         "Movimientos: 4 · Punteados 1 · Por revisar 2 · Pendientes 1")


class PunteadoNoEsConciliadoTests(unittest.TestCase):
    def _celda_del_badge(self):
        ini = APP.index("const score = Number(row.conciliacion_confianza || row.matched_score || 0);")
        return APP[ini:ini + 2400]

    def test_la_etiqueta_ya_no_mira_solo_punteado(self):
        celda = self._celda_del_badge()
        self.assertIn("conciliacion_estado", celda)
        self.assertIn("CONCILIACION_CONFIANZA_MINIMA", celda)

    def test_hay_un_estado_intermedio_para_lo_que_hay_que_revisar(self):
        celda = self._celda_del_badge()
        self.assertIn("Por revisar", celda)
        # En ámbar, no en verde: la clase existe en la hoja de estilos.
        self.assertIn('ocr-badge media', celda)
        self.assertIn(".ocr-badge.media", (RAIZ / "web" / "styles.css").read_text(encoding="utf-8"))

    def test_y_dice_por_qué_hay_que_revisarlo(self):
        celda = self._celda_del_badge()
        self.assertIn("title=", celda)
        self.assertIn("confianza", celda)

    def test_el_porcentaje_se_enseña_aunque_sea_cero(self):
        """Era el detalle que lo remataba: con 0 % desaparecía el aviso."""
        celda = self._celda_del_badge()
        self.assertIn("${punteado ? ` <span class=\"muted\">(${Math.round(score)}%)</span>` : \"\"}",
                      celda)
        self.assertNotIn("${score ? ` <span class=\"muted\">(${Math.round(score)}%)</span>",
                         celda)

    def test_el_recuento_separa_los_que_hay_que_revisar(self):
        # La primera aparición es la del estado vacío: la que cuenta es la de después.
        ini = APP.index("const punteados = items.filter((row) => Number(row.punteado || 0) === 1).length;")
        trozo = APP[ini:ini + 900]
        self.assertIn("porRevisarTotal", trozo)
        self.assertIn("Por revisar", trozo)

    def test_el_umbral_es_el_mismo_que_usa_el_servidor(self):
        """Si no, la pantalla y el resumen dirían cosas distintas de lo mismo."""
        m = re.search(r"const CONCILIACION_CONFIANZA_MINIMA = (\d+);", APP)
        self.assertIsNotNone(m, "no está la constante")
        umbral = int(m.group(1))
        self.assertIn(
            f"COALESCE(conciliacion_confianza, matched_score, 0) < {umbral}", SERVER,
            "el servidor cuenta la baja confianza con otro número")

    def test_el_umbral_esta_explicado(self):
        ini = APP.index("const CONCILIACION_CONFIANZA_MINIMA")
        self.assertIn("mismo umbral", APP[max(0, ini - 400):ini])


if __name__ == "__main__":
    unittest.main()
