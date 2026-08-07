"""La tarifa de administración de fincas se puede tocar sin desplegar.

Dos cosas distintas, encontradas el 2026-08-07 al revisar presupuestos:

**Los trasteros no se cobraban.** La fórmula los contemplaba desde siempre
(`num_trasteros` sumaba 1 € por unidad), pero el formulario rápido de presupuestos
solo pedía viviendas, locales y aparcamientos. No estaba el campo, no viajaba en el
envío y `buildFincasBudgetLineas` ni lo miraba: una comunidad con 30 trasteros se
presupuestaba como si no tuviera ninguno, y el PDF salía con esa cifra.

**Los precios estaban escritos a mano** en dos sitios a la vez —`server.py` y
`app.js`—, así que subir la cuota por vivienda era un despliegue, y no había forma
de cobrar un trabajo puntual como la constitución de la comunidad.

Ahora la tarifa vive en `workspace_fincas_tarifas`, una por workspace. La de partida
son los mismos precios de siempre (5/1/1/1, mínimo 60), así que el día que esto entre
en producción los presupuestos salen exactamente igual que el día anterior; lo que
cambia es que a partir de ahí se pueden editar.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402


class LosTrasterosYaNoSePierdenTests(unittest.TestCase):
    """El fallo concreto que se buscaba: el formulario no los pedía."""

    def _formulario_rapido(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        return HTML[i: HTML.index("</form>", i)]

    def test_el_formulario_pregunta_por_los_trasteros(self):
        self.assertIn('name="num_trasteros"', self._formulario_rapido())

    def test_viajan_en_el_envio(self):
        i = APP.index('workspaceFincasBudgetQuickForm.addEventListener("submit"')
        cuerpo = APP[i: i + 6000]
        self.assertIn("num_trasteros: numTrasteros", cuerpo)

    def test_el_desglose_los_cobra(self):
        i = APP.index("const buildFincasBudgetLineas")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("num_trasteros", cuerpo)

    def test_treinta_trasteros_cambian_el_precio(self):
        """La prueba de que no es cosmético: antes estas dos cifras eran iguales."""
        sin = server.compute_fincas_cuota_sugerida(num_vecinos=20, num_trasteros=0)
        con = server.compute_fincas_cuota_sugerida(num_vecinos=20, num_trasteros=30)
        self.assertEqual(sin, 100.0)
        self.assertEqual(con, 130.0)


class LaTarifaDePartidaNoCambiaNadaTests(unittest.TestCase):
    """Sembrar la tarifa no puede alterar lo que ya se venía cobrando."""

    def test_los_precios_de_partida_son_los_de_siempre(self):
        precios = {t["clave"]: t["precio"] for t in server.FINCAS_TARIFAS_DEFECTO}
        self.assertEqual(precios["vivienda"], 5.0)
        self.assertEqual(precios["local"], 1.0)
        self.assertEqual(precios["trastero"], 1.0)
        self.assertEqual(precios["aparcamiento"], 1.0)
        self.assertEqual(precios["minimo"], 60.0)

    def test_sin_tarifa_se_calcula_como_antes(self):
        self.assertEqual(server.compute_fincas_cuota_sugerida(0, 0, 0, 0), 60.0)
        self.assertEqual(server.compute_fincas_cuota_sugerida(10, 2, 3, 4), 60.0)
        self.assertEqual(server.compute_fincas_cuota_sugerida(24, 0, 0, 0), 120.0)

    def test_el_front_arranca_con_los_mismos_precios(self):
        """Si las dos listas se separan, el navegador y el PDF dirían cifras distintas."""
        i = APP.index("const FINCAS_TARIFA_DEFECTO")
        bloque = APP[i: APP.index("];", i)]
        for clave, precio in (("vivienda", 5), ("local", 1), ("trastero", 1), ("aparcamiento", 1), ("minimo", 60)):
            with self.subTest(clave=clave):
                self.assertIn(f'clave: "{clave}"', bloque)
                self.assertIn(f"precio: {precio},", bloque.split(f'clave: "{clave}"')[1].split("}")[0] + "}")


class LaTarifaMandaSobreElCalculoTests(unittest.TestCase):
    def test_un_precio_distinto_cambia_la_base(self):
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 8.0, "activo": 1},
            {"clave": "trastero", "tipo": "unitaria", "precio": 2.5, "activo": 1},
            {"clave": "minimo", "tipo": "minimo", "precio": 60.0, "activo": 1},
        ]
        # 20 × 8 + 10 × 2,5 = 185
        self.assertEqual(
            server.compute_fincas_cuota_sugerida(num_vecinos=20, num_trasteros=10, tarifas=tarifa),
            185.0,
        )

    def test_el_minimo_sigue_mandando_cuando_sale_poco(self):
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 5.0, "activo": 1},
            {"clave": "minimo", "tipo": "minimo", "precio": 90.0, "activo": 1},
        ]
        self.assertEqual(server.compute_fincas_cuota_sugerida(num_vecinos=4, tarifas=tarifa), 90.0)

    def test_un_concepto_desactivado_no_suma(self):
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 5.0, "activo": 1},
            {"clave": "trastero", "tipo": "unitaria", "precio": 3.0, "activo": 0},
            {"clave": "minimo", "tipo": "minimo", "precio": 0.0, "activo": 1},
        ]
        self.assertEqual(server.compute_fincas_cuota_sugerida(num_vecinos=10, num_trasteros=50, tarifas=tarifa), 50.0)

    def test_los_puntuales_no_entran_en_la_cuota_mensual(self):
        """La constitución de la comunidad se cobra una vez, no todos los meses."""
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 5.0, "activo": 1},
            {"clave": "alta_comunidad", "tipo": "fija", "precio": 400.0, "activo": 1},
            {"clave": "minimo", "tipo": "minimo", "precio": 60.0, "activo": 1},
        ]
        self.assertEqual(server.compute_fincas_cuota_sugerida(num_vecinos=20, tarifas=tarifa), 100.0)


class HayDondeTarifarUnTrabajoPuntualTests(unittest.TestCase):
    def test_la_constitucion_de_la_comunidad_viene_de_serie(self):
        claves = {t["clave"] for t in server.FINCAS_TARIFAS_DEFECTO}
        self.assertIn("alta_comunidad", claves)

    def test_viene_a_cero_para_que_se_le_ponga_precio(self):
        """Inventarle un importe sería peor que dejarlo en blanco."""
        alta = next(t for t in server.FINCAS_TARIFAS_DEFECTO if t["clave"] == "alta_comunidad")
        self.assertEqual(alta["precio"], 0.0)
        self.assertEqual(alta["tipo"], "fija")

    def test_el_formulario_tiene_donde_marcarlos(self):
        self.assertIn('id="workspaceFincasBudgetExtras"', HTML)
        self.assertIn("fincasExtrasSeleccionados", APP)

    def test_el_presupuesto_los_manda_al_servidor(self):
        i = APP.index('workspaceFincasBudgetQuickForm.addEventListener("submit"')
        self.assertIn("tarifas_fijas: extras", APP[i: i + 6000])

    def test_el_servidor_los_cobra_como_linea_aparte(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_presupuestos"')
        cuerpo = SERVER[i: i + 12000]
        self.assertIn('payload.get("tarifas_fijas")', cuerpo)
        self.assertIn('"categoria": "Servicios puntuales"', cuerpo)


class LaTarifaSeGuardaConPermisoTests(unittest.TestCase):
    def _manejador(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_tarifas"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_el_post_esta_dado_de_alta(self):
        """Sin esto el endpoint responde 'Endpoint no valido' y no se entera nadie."""
        i = SERVER.index('"/api/workspace_fincas_comunidades",')
        self.assertIn('"/api/workspace_fincas_tarifas",', SERVER[i - 4000: i + 4000])

    def test_exige_pertenecer_al_workspace_y_poder_escribir(self):
        self.assertIn(
            "enforce_workspace_membership(conn, session, workspace_id, write=True)",
            self._manejador(),
        )

    def test_el_get_tambien_comprueba(self):
        i = SERVER.index('if path == "/api/workspace_fincas_tarifas"')
        self.assertIn("enforce_workspace_membership", SERVER[i: i + 900])

    def test_la_comprobacion_va_antes_de_escribir(self):
        cuerpo = self._manejador()
        self.assertLess(cuerpo.index("enforce_workspace_membership"), cuerpo.index("INSERT INTO"))


if __name__ == "__main__":
    unittest.main()
