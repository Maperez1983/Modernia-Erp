"""Qué pasa cuando un presupuesto no sale adelante.

Tres cosas que faltaban:

- **La comunidad que creó ese presupuesto deja de administrarse.** Al añadir el alta
  automática al aceptar quedó un cabo suelto: aceptar creaba la comunidad y rechazar
  después no la tocaba, así que se quedaba «Activa» sin serlo. Contaría en el panel,
  sumaría en la cartera de cuotas y saldría al emitir recibos.
- **Los rechazados salen de la lista del día a día.** Mezclados con los vivos, la
  lista deja de servir para saber qué hay que atender.
- **Se cuenta cuántos se dan y cuántos entran**, que es la pregunta de cualquiera
  que vive de presentar propuestas y hasta ahora había que contarla a ojo.

La baja **no borra nada**. Puede haber quedado algo dentro y borrar se lo llevaría
por delante; además solo se toca la comunidad si la creó ese mismo presupuesto y no
cuelga nada de ella. Una comunidad dada de alta a mano no se toca jamás por esto.
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

CALC = {"comunidad_denominacion": "C.P. Prueba 1", "referencia_catastral": "AAA111",
        "num_vecinos": 20, "cuota_sugerida": 100.0}


class LaBajaAlRechazarTests(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        self.cid, _ = server.alta_comunidad_desde_presupuesto(
            self.conn, "ws1", "e1", dict(CALC), subtotal=100.0, presupuesto_id="pre1")

    def estado(self):
        return server.row_value(self.conn.execute(
            "SELECT estado FROM workspace_fincas_comunidades WHERE id = ?", (self.cid,)).fetchone(), "estado", "")

    def test_se_da_de_baja(self):
        bajada, motivo = server.baja_comunidad_por_rechazo(self.conn, "ws1", self.cid, "pre1")
        self.assertTrue(bajada, motivo)
        self.assertEqual(self.estado(), "Baja")

    def test_no_se_borra(self):
        """Puede haber quedado algo dentro; borrar se lo llevaría por delante."""
        server.baja_comunidad_por_rechazo(self.conn, "ws1", self.cid, "pre1")
        self.assertIsNotNone(self.conn.execute(
            "SELECT id FROM workspace_fincas_comunidades WHERE id = ?", (self.cid,)).fetchone())

    def test_no_toca_la_que_creo_otro_presupuesto(self):
        bajada, motivo = server.baja_comunidad_por_rechazo(self.conn, "ws1", self.cid, "otro")
        self.assertFalse(bajada)
        self.assertIn("no la creó", motivo)
        self.assertEqual(self.estado(), "Activa")

    def test_no_toca_una_dada_de_alta_a_mano(self):
        """Sin `origen_presupuesto_id` no hay forma de saber que salió de aquí."""
        self.conn.execute("UPDATE workspace_fincas_comunidades SET origen_presupuesto_id = NULL WHERE id = ?", (self.cid,))
        bajada, _m = server.baja_comunidad_por_rechazo(self.conn, "ws1", self.cid, "pre1")
        self.assertFalse(bajada)
        self.assertEqual(self.estado(), "Activa")

    def test_no_toca_la_de_otro_workspace(self):
        bajada, motivo = server.baja_comunidad_por_rechazo(self.conn, "ws2", self.cid, "pre1")
        self.assertFalse(bajada)
        self.assertEqual(motivo, "sin comunidad")

    def test_sin_comunidad_no_falla(self):
        self.assertEqual(server.baja_comunidad_por_rechazo(self.conn, "ws1", "", "pre1"), (False, "sin comunidad"))
        self.assertEqual(server.baja_comunidad_por_rechazo(self.conn, "ws1", "noexiste", "pre1")[0], False)

    def test_dos_veces_no_pasa_nada(self):
        server.baja_comunidad_por_rechazo(self.conn, "ws1", self.cid, "pre1")
        bajada, motivo = server.baja_comunidad_por_rechazo(self.conn, "ws1", self.cid, "pre1")
        self.assertFalse(bajada)
        self.assertEqual(motivo, "ya estaba de baja")


class SiYaSeTrabajoEnEllaNoSeTocaTests(unittest.TestCase):
    """Si tiene censo, recibos o asientos, alguien ha estado trabajando: la decisión
    deja de ser automática y se queda como está."""

    def preparar(self, tabla, columnas, valores):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        cid, _ = server.alta_comunidad_desde_presupuesto(
            conn, "ws1", "e1", dict(CALC), subtotal=100.0, presupuesto_id="pre1")
        marcas = ", ".join("?" for _ in valores)
        conn.execute(f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})", tuple(v or cid for v in valores))
        return conn, cid

    def test_con_censo_cargado(self):
        conn, cid = self.preparar(
            "workspace_fincas_vecinos",
            "id, workspace_id, comunidad_id, nombre, created_at, updated_at",
            ["v1", "ws1", None, "Un propietario", "a", "a"])
        bajada, motivo = server.baja_comunidad_por_rechazo(conn, "ws1", cid, "pre1")
        self.assertFalse(bajada)
        self.assertIn("vecinos", motivo)

    def test_con_recibos_emitidos(self):
        conn, cid = self.preparar(
            "workspace_fincas_recibos",
            "id, workspace_id, comunidad_id, vecino_id, periodo, concepto, created_at, updated_at",
            ["r1", "ws1", None, "v1", "2026-01", "Cuota", "a", "a"])
        bajada, motivo = server.baja_comunidad_por_rechazo(conn, "ws1", cid, "pre1")
        self.assertFalse(bajada)
        self.assertIn("recibos", motivo)

    def test_con_una_junta_convocada(self):
        conn, cid = self.preparar(
            "workspace_fincas_juntas",
            "id, workspace_id, comunidad_id, fecha, created_at, updated_at",
            ["j1", "ws1", None, "2026-03-01", "a", "a"])
        self.assertFalse(server.baja_comunidad_por_rechazo(conn, "ws1", cid, "pre1")[0])

    def test_la_lista_de_tablas_cubre_lo_que_importa(self):
        for tabla in ("workspace_fincas_vecinos", "workspace_fincas_recibos",
                      "workspace_fincas_asientos", "workspace_fincas_juntas",
                      "workspace_fincas_documentos"):
            with self.subTest(tabla=tabla):
                self.assertIn(tabla, server.TABLAS_CON_VIDA_DE_COMUNIDAD)

    def test_una_tabla_que_no_exista_no_revienta(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        self.assertEqual(server.comunidad_tiene_movimiento(conn, "loquesea"), "")


class DondeSeEngranaTests(unittest.TestCase):
    def handler(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_presupuestos"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_solo_al_rechazar(self):
        cuerpo = self.handler()
        i = cuerpo.index("baja_comunidad_por_rechazo(")
        self.assertIn('estado == "Rechazado"', cuerpo[i - 300: i])

    def test_no_se_da_de_baja_al_pasar_a_estudio(self):
        """La rama es común a Estudio y Rechazado: sin la condición, poner un
        presupuesto en estudio daría de baja la comunidad."""
        cuerpo = self.handler()
        i = cuerpo.index("baja_comunidad_por_rechazo(")
        self.assertIn('servicio_es_fincas and estado == "Rechazado"', cuerpo[i - 300: i])

    def test_el_alta_deja_dicho_de_que_presupuesto_salio(self):
        cuerpo = self.handler()
        self.assertIn("presupuesto_id=record_id", cuerpo)

    def test_la_columna_existe(self):
        self.assertIn('"workspace_fincas_comunidades", "origen_presupuesto_id"', SERVER)

    def test_un_fallo_no_tumba_el_rechazo(self):
        cuerpo = self.handler()
        i = cuerpo.index("baja_comunidad_por_rechazo(")
        self.assertIn("except Exception:", cuerpo[i: i + 400])


class ElHistoricoTests(unittest.TestCase):
    def test_por_defecto_no_se_ven_los_rechazados(self):
        self.assertIn('<option value="activos" selected>En curso</option>', HTML)

    def test_hay_una_vista_de_historico(self):
        self.assertIn('<option value="historico">Histórico (rechazados)</option>', HTML)

    def test_y_se_pueden_ver_todos_si_se_quiere(self):
        self.assertIn('<option value="all">Todos</option>', HTML)

    def test_el_filtro_separa_vivos_de_historico(self):
        i = APP.index("const renderWorkspaceFincasBudgetsList")
        cuerpo = APP[i: i + 2200]
        self.assertIn('if (filterEstado === "activos")', cuerpo)
        self.assertIn("items.filter((row) => !esRechazado(row))", cuerpo)
        self.assertIn('} else if (filterEstado === "historico")', cuerpo)
        self.assertIn("items.filter(esRechazado)", cuerpo)

    def test_el_historico_vacio_no_dice_sin_presupuestos(self):
        """«Sin presupuestos todavía» en el histórico induce a error."""
        self.assertIn("Ningún presupuesto rechazado", APP)


class LasCifrasDeConversionTests(unittest.TestCase):
    def test_hay_un_bloque_de_cifras(self):
        self.assertIn('id="workspaceFincasBudgetsKpis"', HTML)

    def test_cuenta_los_dados_y_los_aceptados(self):
        i = APP.index("const renderWorkspaceFincasBudgetsKpis")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("Presentados", cuerpo)
        self.assertIn("Aceptados", cuerpo)
        self.assertIn("Tasa de aceptación", cuerpo)

    def test_los_borradores_no_hunden_la_tasa(self):
        """Un presupuesto sin presentar no ha ganado ni perdido nada: fuera del
        denominador, y contado aparte."""
        i = APP.index("const renderWorkspaceFincasBudgetsKpis")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("const resueltos = aceptados + rechazados;", cuerpo)
        self.assertIn("resueltos ? Math.round((aceptados / resueltos) * 100) : null", cuerpo)
        self.assertIn("en borrador", cuerpo)

    def test_sin_ninguno_resuelto_no_se_inventa_un_cero(self):
        """0 % diría que se rechazan todos, y lo cierto es que no se sabe."""
        i = APP.index("const renderWorkspaceFincasBudgetsKpis")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn('tasa === null ? "—"', cuerpo)

    def test_se_cuentan_sobre_todos_y_no_sobre_lo_filtrado(self):
        """Mirando el histórico, la tasa saldría del 0 %."""
        i = APP.index("const renderWorkspaceFincasBudgetsList")
        cuerpo = APP[i: i + 900]
        self.assertIn("renderWorkspaceFincasBudgetsKpis(deFincas);", cuerpo)
        self.assertLess(cuerpo.index("renderWorkspaceFincasBudgetsKpis(deFincas)"), cuerpo.index("filterEstado"))

    def test_la_cartera_va_sin_iva(self):
        i = APP.index("const renderWorkspaceFincasBudgetsKpis")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("Number(r.subtotal || 0)", cuerpo)
        self.assertIn("sin IVA", cuerpo)


if __name__ == "__main__":
    unittest.main()
