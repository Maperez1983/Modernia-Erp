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

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


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
