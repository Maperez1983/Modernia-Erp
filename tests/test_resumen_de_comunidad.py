"""El resumen de cada comunidad, y dos arreglos de usabilidad en presupuestos.

**El resumen.** La ficha de una comunidad tenía nueve pestañas y abría por el
formulario de datos, así que para saber cómo va había que recorrerlas y
reconstruirlo mentalmente. Ahora abre por un resumen que junta censo, recibos del
mes, morosidad, incidencias, ejercicio y juntas.

Lo que más se usa de esa pantalla no son las cifras sino los **avisos**: qué le falta
a esta comunidad para poder trabajar. Un censo vacío o un IBAN sin poner no se ven en
un KPI —se ven cuando intentas emitir y no puedes—, así que salen arriba, ordenados
por lo que bloquea antes, y cada uno lleva a la pestaña que lo resuelve.

**Presupuestos.** 28 campos con los importes al final: había que bajar el formulario
entero para ver cuánto sale. Ahora hay un resumen pegado arriba con la cuota mensual y
el pago único separados —que es como se lee un presupuesto—, el «Estado» ha salido de
«Datos de la comunidad» (estaba entre el CIF y el nombre del presidente), y lo que no
decide el precio —solicitante, foto, carta— va plegado al final.

Sobre el tamaño, medido antes y después al mismo ancho y con el mismo contenido: 1.020
px frente a 982, o sea **38 px menos**. Reordenar no acorta apenas, porque lo que se
ahorra plegando se lo come el resumen pegado. Lo que cambia es el orden —primero lo
que decide el precio— y que la cifra esté siempre a la vista sin scroll.
"""

import datetime
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402

IBAN = "ES9121000418450200051332"


class ComunidadDePrueba(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        # `empresas` la crea otro tramo del arranque; aquí basta con lo que mira el
        # resumen para saber si quien administra la comunidad puede administrarla.
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS empresas (id TEXT PRIMARY KEY, nombre TEXT NOT NULL, "
            "activo INTEGER NOT NULL DEFAULT 1, administra_fincas INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT, updated_at TEXT)")
        self.ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com = "ws1", "com1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, num_vecinos, "
            "created_at, updated_at) VALUES (?,?,?,'Activa',24,datetime(?),datetime(?))",
            (self.com, self.ws, "C.P. Velázquez 11", self.ahora, self.ahora))
        self.conn.commit()

    def dashboard(self, periodo="2026-08"):
        return server.fetch_workspace_fincas_comunidad_dashboard(self.conn, self.ws, self.com, periodo=periodo)

    def poblar(self, con_iban=True, recibos=True):
        self.conn.execute(
            "UPDATE workspace_fincas_comunidades SET iban = ?, acreedor_sepa = 'ES12ZZZ12345678', "
            "cuota_mensual = 1200 WHERE id = ?", (IBAN if con_iban else None, self.com))
        for i in range(24):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, iban, created_at, updated_at) VALUES (?,?,?,?,?,?,?,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"P{i}", f"{i}A", 4.1667, IBAN, self.ahora, self.ahora))
            if recibos:
                self.conn.execute(
                    "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                    "concepto, importe, estado, created_at, updated_at) "
                    "VALUES (?,?,?,?,'2026-08','Cuota',50,?,datetime(?),datetime(?))",
                    (f"r{i}", self.ws, self.com, f"v{i}", "Cobrado" if i > 2 else "Pendiente",
                     self.ahora, self.ahora))
        self.conn.commit()


class LosAvisosSonLaListaDeTareasTests(ComunidadDePrueba):
    def _textos(self, periodo="2026-08"):
        return [a["texto"] for a in self.dashboard(periodo)["avisos"]]

    def test_una_comunidad_vacia_avisa_de_lo_que_bloquea(self):
        """Es el estado real de las 13 comunidades hoy."""
        textos = " ".join(self._textos())
        self.assertIn("No hay censo de propietarios", textos)
        self.assertIn("IBAN válido", textos)
        self.assertIn("acreedor SEPA", textos)

    def test_lo_que_bloquea_va_marcado_como_alto(self):
        niveles = {a["texto"][:20]: a["nivel"] for a in self.dashboard()["avisos"]}
        self.assertEqual(niveles["No hay censo de prop"], "alto")

    def test_cada_aviso_dice_a_donde_ir(self):
        pestanas = {"resumen", "datos", "vecinos", "recibos", "juntas", "proveedores",
                    "documentos", "incidencias", "contabilidad", "ejercicio"}
        for aviso in self.dashboard()["avisos"]:
            with self.subTest(texto=aviso["texto"][:30]):
                self.assertIn(aviso["ir"], pestanas)

    def test_con_todo_puesto_desaparecen_los_avisos_que_bloquean(self):
        self.poblar()
        textos = " ".join(self._textos())
        self.assertNotIn("No hay censo", textos)
        self.assertNotIn("IBAN válido", textos)

    def test_avisa_de_los_recibos_sin_emitir(self):
        self.poblar(recibos=False)
        self.assertIn("No hay recibos emitidos de 2026-08", " ".join(self._textos()))

    def test_avisa_de_la_deuda(self):
        self.poblar()
        self.assertIn("deben", " ".join(self._textos()))

    def test_avisa_de_que_nadie_tiene_portal(self):
        self.poblar()
        self.assertIn("acceso al portal", " ".join(self._textos()))

    def test_avisa_si_la_administra_una_sociedad_que_no_administra_fincas(self):
        """Tres de las trece comunidades colgaban de una sociedad que no es
        administradora, así que sus recibos y su presupuesto salían a nombre de
        quien no las administra. No se veía por ninguna parte."""
        self.conn.execute(
            "INSERT INTO empresas (id, nombre, activo, administra_fincas, created_at, updated_at) "
            "VALUES ('e1','Estudio Velazquez 2012 SL',1,0,datetime(?),datetime(?))", (self.ahora, self.ahora))
        self.conn.execute("UPDATE workspace_fincas_comunidades SET empresa_id = 'e1' WHERE id = ?", (self.com,))
        self.conn.commit()
        self.assertIn("no consta como administradora de fincas", " ".join(self._textos()))

    def test_si_la_administra_una_administradora_no_avisa(self):
        self.conn.execute(
            "INSERT INTO empresas (id, nombre, activo, administra_fincas, created_at, updated_at) "
            "VALUES ('e2','Fincas Velazquez',1,1,datetime(?),datetime(?))", (self.ahora, self.ahora))
        self.conn.execute("UPDATE workspace_fincas_comunidades SET empresa_id = 'e2' WHERE id = ?", (self.com,))
        self.conn.commit()
        self.assertNotIn("no consta como administradora", " ".join(self._textos()))

    def test_un_censo_descuadrado_se_ve(self):
        self.poblar()
        self.conn.execute("UPDATE workspace_fincas_vecinos SET coeficiente = 3 WHERE id = 'v0'")
        self.conn.commit()
        self.assertIn("no 100 %", " ".join(self._textos()))


class LasCifrasDelResumenTests(ComunidadDePrueba):
    def test_junta_lo_que_calculan_las_demas_pantallas(self):
        self.poblar()
        d = self.dashboard()
        self.assertEqual(d["censo"]["propietarios"], 24)
        self.assertEqual(d["recibos"]["emitido"], 1200.0)
        self.assertEqual(d["recibos"]["cobrado"], 1050.0)
        self.assertEqual(d["morosidad"]["deudores"], 3)

    def test_dice_la_proxima_junta_y_la_ultima(self):
        self.conn.execute(
            "INSERT INTO workspace_fincas_juntas (id, workspace_id, comunidad_id, fecha, tipo, estado, "
            "created_at, updated_at) VALUES ('j1',?,?, '2099-11-20','Ordinaria','Planificada',datetime(?),datetime(?))",
            (self.ws, self.com, self.ahora, self.ahora))
        self.conn.execute(
            "INSERT INTO workspace_fincas_juntas (id, workspace_id, comunidad_id, fecha, tipo, estado, "
            "created_at, updated_at) VALUES ('j0',?,?, '2020-01-10','Ordinaria','Celebrada',datetime(?),datetime(?))",
            (self.ws, self.com, self.ahora, self.ahora))
        self.conn.commit()
        d = self.dashboard()
        self.assertEqual(d["junta_proxima"]["fecha"], "2099-11-20")
        self.assertEqual(d["junta_ultima"]["fecha"], "2020-01-10")

    def test_cuenta_solo_las_incidencias_abiertas(self):
        for i, estado in enumerate(("Abierta", "En curso", "Cerrada", "Resuelta")):
            self.conn.execute(
                "INSERT INTO workspace_fincas_incidencias (id, workspace_id, comunidad_id, titulo, estado, "
                "created_at, updated_at) VALUES (?,?,?,?,?,datetime(?),datetime(?))",
                (f"i{i}", self.ws, self.com, f"Inc {i}", estado, self.ahora, self.ahora))
        self.conn.commit()
        self.assertEqual(self.dashboard()["incidencias_abiertas"], 2)

    def test_solo_cuenta_accesos_al_portal_vivos(self):
        self.poblar()
        for i, (revocado, caduca) in enumerate(((0, "2099-01-01"), (1, "2099-01-01"), (0, "2020-01-01"))):
            self.conn.execute(
                "INSERT INTO workspace_fincas_portal_accesos (id, workspace_id, comunidad_id, vecino_id, "
                "token_hash, expires_at, revocado, accesos, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,0,datetime(?),datetime(?))",
                (f"p{i}", self.ws, self.com, f"v{i}", f"hash{i}", caduca, revocado, self.ahora, self.ahora))
        self.conn.commit()
        self.assertEqual(self.dashboard()["portal"]["con_acceso"], 1)

    def test_una_comunidad_de_otro_workspace_no_se_lee(self):
        self.assertIsNone(server.fetch_workspace_fincas_comunidad_dashboard(self.conn, "otro", self.com))


class LaPantallaDelResumenTests(unittest.TestCase):
    def test_es_la_pestana_de_entrada(self):
        self.assertIn('data-community-ficha-tab="resumen"', HTML)
        self.assertIn('String(state.workspaceFincasCommunityFichaTab || "resumen")', APP)

    def test_los_avisos_llevan_a_su_pestana(self):
        self.assertIn("data-ir=", APP)
        self.assertIn("irA(b.dataset.ir)", APP)

    def test_el_nivel_no_se_distingue_solo_por_color(self):
        """Con solo color, quien no distingue rojo de ámbar no ve la prioridad."""
        i = CSS.index(".resumen-aviso[data-nivel=")
        bloque = CSS[i: i + 400]
        self.assertIn("border-left", bloque)

    def test_el_get_comprueba_pertenencia(self):
        i = SERVER.index('if path == "/api/workspace_fincas_comunidad_dashboard"')
        self.assertIn("enforce_workspace_membership", SERVER[i: i + 1400])

    def test_ensena_el_porcentaje_cobrado(self):
        """No estaba en ninguna pantalla porque exigía dividir a mano."""
        self.assertIn("% cobrado", APP)


class ElPresupuestoEnsenaElPrecioSinBajarTests(unittest.TestCase):
    def _formulario(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        return HTML[i: HTML.index("</form>", i)]

    def test_hay_resumen_arriba(self):
        self.assertIn('id="workspaceFincasBudgetResumen"', self._formulario())

    def test_se_queda_pegado_al_bajar(self):
        i = CSS.index(".presu-resumen {")
        self.assertIn("position: sticky", CSS[i: i + 300])

    def test_separa_lo_mensual_de_lo_puntual(self):
        formulario = self._formulario()
        self.assertIn("Cuota mensual (IVA incl.)", formulario)
        self.assertIn("Pago único (IVA incl.)", formulario)

    def test_el_pago_unico_solo_sale_si_lo_hay(self):
        self.assertIn("data-resumen-puntual", self._formulario())
        self.assertIn("cajaPuntual.hidden = !extrasImporte", APP)

    def test_el_resumen_se_actualiza_al_teclear(self):
        i = APP.index("const extrasImporte = fincasImporteExtras();")
        self.assertIn('pon("mensual"', APP[i: i + 900])

    def test_el_estado_del_presupuesto_sale_de_los_datos_de_la_comunidad(self):
        """Estaba entre el CIF y el nombre del presidente, y no es un dato de la comunidad.

        Se comprueba que cae en su propia sección y no dentro del bloque de la
        comunidad, en vez de compararlo con el bloque del solicitante: ese se ha
        movido al final y la comparación decía otra cosa de la que se quería.
        """
        formulario = self._formulario()
        self.assertIn("El presupuesto", formulario)
        self.assertLess(formulario.index("El presupuesto"), formulario.index('name="estado"'))
        bloque_comunidad = formulario[
            formulario.index("Datos de la comunidad"): formulario.index("Datos del edificio")
        ]
        self.assertNotIn('name="estado"', bloque_comunidad)

    def test_el_texto_de_ayuda_dice_para_que_sirve_el_precio(self):
        """Eran cuatro campos con su explicación cada uno —«la calcula la tarifa, no
        se edita»— y tres de ellos `readonly` repitiendo el resumen de arriba. Queda
        el único que se toca, y tiene que decir qué pasa si se deja en blanco."""
        formulario = self._formulario()
        self.assertIn("Precio pactado", formulario)
        self.assertIn("Vacío: manda la tarifa", formulario)
        self.assertIn("Solo si se ha cerrado un importe distinto", formulario)


class LoQueNoDecideElPrecioVaAlFinalPlegadoTests(unittest.TestCase):
    """Reordenar no acorta apenas el formulario: mide 982 px frente a 1.020, o sea
    38 menos. Lo que se ahorra plegando se lo come el resumen pegado. Lo que cambia
    de verdad es el orden —primero lo que decide el precio— y que la cifra esté
    siempre a la vista.
    """

    def _formulario(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        return HTML[i: HTML.index("</form>", i)]

    def test_el_edificio_va_antes_que_el_solicitante(self):
        """Las unidades deciden la cuota; el nombre del presidente no."""
        formulario = self._formulario()
        self.assertLess(formulario.index("Datos del edificio"), formulario.index("Datos del presidente"))

    def test_el_solicitante_esta_plegado(self):
        formulario = self._formulario()
        i = formulario.index("Datos del presidente")
        self.assertIn("presu-plegable", formulario[max(0, i - 400): i])

    def test_la_foto_y_la_carta_estan_plegadas_pero_separadas(self):
        """Empezaron en el mismo bloque; la carta se sacó al suyo cuando pasó a
        generarse con plantillas, porque es lo primero que lee el cliente y la foto
        es un adorno. Ver `test_carta_de_presentacion.py`."""
        formulario = self._formulario()
        for titulo in ("Carta de presentación", "Foto del edificio"):
            with self.subTest(titulo=titulo):
                i = formulario.index(titulo)
                self.assertIn("presu-plegable", formulario[max(0, i - 500): i])
        self.assertNotIn("Foto del edificio y carta de presentación", formulario)

    def test_los_plegables_van_despues_del_precio(self):
        """La sección se llamaba «Importes» cuando eran cuatro campos; ahora es uno."""
        formulario = self._formulario()
        self.assertLess(
            formulario.index('<div class="form-grid-section">Precio</div>'),
            formulario.index("presu-plegable"),
        )

    def test_se_abre_solo_si_ya_tiene_datos(self):
        """Plegar sirve para acortar, no para esconder lo que ya está escrito."""
        self.assertIn("const abrirPlegableSiTieneDatos", APP)
        self.assertIn("caja.open = true", APP)
        self.assertEqual(APP.count("abrirPlegableSiTieneDatos();"), 2)

    def test_ningun_campo_obligatorio_queda_plegado(self):
        """Un required escondido bloquea el envío sin decir dónde."""
        formulario = self._formulario()
        i = formulario.index("presu-plegable")
        self.assertNotIn("required", formulario[i:])


class LosTrasterosTampocoSePerdianAlPrecargarTests(unittest.TestCase):
    """Resto del mismo fallo: se arregló el cálculo y el envío, pero las dos
    precargas —cargar una comunidad y editar un presupuesto— seguían sin el campo,
    así que los trasteros volvían a cero en cuanto tocabas cualquiera de las dos.
    """

    def test_al_precargar_una_comunidad(self):
        i = APP.index('set("num_vecinos", community.num_vecinos ?? 0);')
        self.assertIn('set("num_trasteros", community.num_trasteros ?? 0);', APP[i: i + 400])

    def test_al_editar_un_presupuesto(self):
        i = APP.index('set("num_vecinos", calc.num_vecinos ?? 0);')
        self.assertIn('set("num_trasteros", calc.num_trasteros ?? 0);', APP[i: i + 400])


if __name__ == "__main__":
    unittest.main()
