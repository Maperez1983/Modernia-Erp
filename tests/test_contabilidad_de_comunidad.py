"""Contabilidad de comunidad: diario, conciliación bancaria, liquidación y cierre.

Lo que había era una lista plana de movimientos —fecha, tipo, concepto, importe— con
cero filas en producción. El usuario lo señaló el 2026-08-07: «no podemos gestionar
comunidades con nuestro programa si le faltan piezas», y tenía razón. Sin libro
diario, sin conciliar con el banco y sin liquidación por propietario, esto no es un
programa de administración de fincas.

Tres reglas sostienen todo lo demás, y son las que estos tests fijan:

**1. Un asiento que no cuadra no se guarda.** La suma del debe tiene que ser
exactamente la del haber. Permitir un descuadre «para arreglarlo luego» es lo que
convierte un libro en un montón de apuntes sueltos. Se compara en céntimos enteros:
con flotantes, `0.10 + 0.20 != 0.30` habría rechazado un asiento correcto.

**2. Un extracto que no cuadra consigo mismo no se importa.** El cuaderno 43 declara
su propio saldo final y sus totales; si lo leído no coincide, es que algún campo se
ha leído mal y los importes no son de fiar. Dar por bueno un extracto mal leído es
peor que no importarlo.

**3. La conciliación no adivina.** Se propone solo si hay un único candidato. Con
veinticuatro recibos de 50 €, elegir uno al azar marcaría cobrado al vecino
equivocado, y eso se descubre reclamando a quien sí había pagado.

Y una decisión de fondo en la liquidación: **se reparte el gasto real, no el
presupuestado**. Un presupuesto es una previsión; lo que se aprueba en junta es lo
que se ha gastado. Repartiendo lo presupuestado, la suma de las liquidaciones no
cuadraría con la caja.
"""

import datetime
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402


def reg11(banco="2100", oficina="0418", cuenta="0200051332", ini="260801", fin="260831",
          signo="2", saldo=250000, titular="CP VELAZQUEZ 11"):
    return ("11" + banco.zfill(4) + oficina.zfill(4) + cuenta.zfill(10) + ini + fin + signo
            + str(saldo).zfill(14) + "978" + "1" + titular.ljust(26)[:26] + "   ").ljust(80)


def reg22(fecha, valor, signo, centimos, documento, referencia=""):
    return ("22" + "    " + "0001" + fecha + valor + "12" + "003" + signo + str(centimos).zfill(14)
            + documento.zfill(10) + referencia.ljust(12)[:12] + "".ljust(16)).ljust(80)


def reg23(texto):
    return ("23" + "01" + texto.ljust(38)[:38] + "".ljust(38)).ljust(80)


def reg33(cuenta="0200051332", n_debe=0, c_debe=0, n_haber=0, c_haber=0, signo="2", saldo=0):
    return ("33" + "2100" + "0001" + cuenta.zfill(10) + str(n_debe).zfill(5) + str(c_debe).zfill(14)
            + str(n_haber).zfill(5) + str(c_haber).zfill(14) + signo + str(saldo).zfill(14)
            + "978" + "".ljust(3)).ljust(80)


FICHERO = "\n".join([
    reg11(),
    reg22("260805", "260805", "2", 115000, "1", "REMESA0826"), reg23("ABONO REMESA RECIBOS AGOSTO"),
    reg22("260812", "260812", "1", 5000, "2", "DEVOL01"), reg23("DEVOLUCION RECIBO"),
    reg22("260815", "260815", "1", 50000, "3", "LIMPIEZA"), reg23("TRANSFERENCIA LIMPIEZAS DEL SUR SL"),
    reg33(n_debe=2, c_debe=55000, n_haber=1, c_haber=115000, saldo=310000),
    "88" + "9" * 18 + "".ljust(60),
])


class BaseConta(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        self.ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com = "ws1", "com1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, created_at, updated_at) "
            "VALUES (?,?,?,'Activa',datetime(?),datetime(?))", (self.com, self.ws, "C.P. X", self.ahora, self.ahora))
        self.conn.commit()

    def asiento(self, concepto, apuntes, fecha="2026-08-15"):
        return server.registrar_asiento(self.conn, self.ws, self.com, fecha=fecha,
                                        concepto=concepto, apuntes=apuntes)


class UnAsientoQueNoCuadraNoEntraTests(BaseConta):
    def test_uno_que_cuadra_entra(self):
        r = self.asiento("Cuotas", [{"cuenta": "440", "debe": 1200}, {"cuenta": "700", "haber": 1200}])
        self.assertEqual(r["numero"], 1)
        self.assertEqual(r["total"], 1200.0)

    def test_un_centimo_de_descuadre_lo_tumba(self):
        with self.assertRaises(server.AsientoDescuadrado) as cm:
            self.asiento("Malo", [{"cuenta": "572", "debe": 100.00}, {"cuenta": "700", "haber": 99.99}])
        self.assertIn("no cuadra", str(cm.exception))

    def test_el_clasico_de_la_coma_flotante_si_entra(self):
        """0,10 + 0,20 no es 0,30 en flotante; en céntimos enteros sí."""
        r = self.asiento("Céntimos", [{"cuenta": "621", "debe": 0.10}, {"cuenta": "622", "debe": 0.20},
                                      {"cuenta": "572", "haber": 0.30}])
        self.assertEqual(r["total"], 0.30)

    def test_un_apunte_no_puede_llevar_debe_y_haber(self):
        with self.assertRaises(server.AsientoDescuadrado):
            self.asiento("Ambos", [{"cuenta": "572", "debe": 100, "haber": 100}])

    def test_no_se_admiten_importes_negativos(self):
        """Un negativo en el debe es un haber: si se admite, el signo se pierde."""
        with self.assertRaises(server.AsientoDescuadrado):
            self.asiento("Negativo", [{"cuenta": "572", "debe": -100}, {"cuenta": "700", "haber": -100}])

    def test_sin_apuntes_no_hay_asiento(self):
        with self.assertRaises(server.AsientoDescuadrado):
            self.asiento("Vacío", [])

    def test_la_numeracion_es_correlativa_por_ejercicio(self):
        self.asiento("A", [{"cuenta": "572", "debe": 10}, {"cuenta": "700", "haber": 10}], fecha="2026-01-05")
        self.asiento("B", [{"cuenta": "572", "debe": 10}, {"cuenta": "700", "haber": 10}], fecha="2026-06-05")
        primero = self.asiento("C", [{"cuenta": "572", "debe": 10}, {"cuenta": "700", "haber": 10}], fecha="2027-01-05")
        self.assertEqual(primero["numero"], 1)
        self.assertEqual(primero["ejercicio"], "2027")

    def test_el_diario_no_puede_salir_descuadrado(self):
        for n in range(5):
            self.asiento(f"A{n}", [{"cuenta": "621", "debe": 33.33}, {"cuenta": "572", "haber": 33.33}])
        self.conn.commit()
        d = server.fetch_workspace_fincas_diario(self.conn, self.ws, self.com, "2026")
        self.assertEqual(d["totales"]["descuadre"], 0.0)
        self.assertEqual(d["totales"]["debe"], d["totales"]["haber"])


class ElExtractoDelBancoTests(unittest.TestCase):
    def leido(self, fichero=FICHERO):
        return server.parse_norma43(fichero)

    def test_lee_la_cabecera_de_cuenta(self):
        c = self.leido()["cuentas"][0]
        self.assertEqual(c["cuenta"], "0200051332")
        self.assertEqual(c["fecha_inicial"], "2026-08-01")
        self.assertEqual(c["saldo_inicial"], 2500.0)
        self.assertEqual(c["titular"], "CP VELAZQUEZ 11")

    def test_el_signo_no_va_en_el_importe(self):
        """Los céntimos vienen sin signo y el cargo o abono es un dígito aparte."""
        movs = self.leido()["cuentas"][0]["movimientos"]
        self.assertEqual(movs[0]["importe"], 1150.0)
        self.assertEqual(movs[1]["importe"], -50.0)

    def test_el_concepto_se_arma_con_los_registros_23(self):
        movs = self.leido()["cuentas"][0]["movimientos"]
        self.assertIn("ABONO REMESA", movs[0]["concepto"])
        self.assertIn("LIMPIEZAS DEL SUR", movs[2]["concepto"])

    def test_cuadra_con_el_saldo_que_el_propio_fichero_declara(self):
        c = self.leido()["cuentas"][0]
        self.assertEqual(c["saldo_calculado"], c["saldo_final"])
        self.assertTrue(c["cuadra"])

    def test_un_saldo_final_mal_se_detecta(self):
        malo = FICHERO.replace(reg33(n_debe=2, c_debe=55000, n_haber=1, c_haber=115000, saldo=310000),
                               reg33(n_debe=2, c_debe=55000, n_haber=1, c_haber=115000, saldo=999999))
        self.assertFalse(self.leido(malo)["cuentas"][0]["cuadra"])

    def test_un_total_de_cargos_mal_se_avisa(self):
        malo = FICHERO.replace(reg33(n_debe=2, c_debe=55000, n_haber=1, c_haber=115000, saldo=310000),
                               reg33(n_debe=2, c_debe=44444, n_haber=1, c_haber=115000, saldo=310000))
        self.assertTrue(any("cargos" in a for a in self.leido(malo)["avisos"]))

    def test_el_contador_de_apuntes_suma_debe_y_haber(self):
        """La primera versión leía solo el contador del debe y avisaba de un
        descuadre inexistente en un fichero correcto."""
        c = self.leido()["cuentas"][0]
        self.assertEqual(c["apuntes_declarados"], 3)
        self.assertEqual(c["apuntes_leidos"], 3)
        self.assertEqual(self.leido()["avisos"], [])

    def test_una_fecha_imposible_no_revienta(self):
        malo = FICHERO.replace(reg22("260812", "260812", "1", 5000, "2", "DEVOL01"),
                               reg22("269999", "260812", "1", 5000, "2", "DEVOL01"))
        self.assertEqual(self.leido(malo)["cuentas"][0]["movimientos"][1]["fecha"], "")

    def test_un_fichero_vacio_o_basura(self):
        for texto in ("", None, "esto no es un cuaderno 43"):
            with self.subTest(texto=texto):
                self.assertEqual(server.parse_norma43(texto)["cuentas"], [])

    def test_la_huella_distingue_movimientos_parecidos(self):
        movs = self.leido()["cuentas"][0]["movimientos"]
        huellas = {server.huella_movimiento(m) for m in movs}
        self.assertEqual(len(huellas), len(movs))

    def test_la_huella_es_estable(self):
        """Si cambiara entre importaciones, el mismo extracto se duplicaría."""
        m = self.leido()["cuentas"][0]["movimientos"][0]
        self.assertEqual(server.huella_movimiento(m), server.huella_movimiento(dict(m)))


class LaConciliacionNoAdivinaTests(BaseConta):
    def poblar(self, cuantos=24, importe=50):
        for i in range(cuantos):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, created_at, updated_at) VALUES (?,?,?,?,?,?,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"P{i}", f"{i}A", 100 / cuantos, self.ahora, self.ahora))
            self.conn.execute(
                "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                "concepto, importe, estado, created_at, updated_at) "
                "VALUES (?,?,?,?,'2026-08','Cuota',?, 'Pendiente',datetime(?),datetime(?))",
                (f"r{i}", self.ws, self.com, f"v{i}", importe, self.ahora, self.ahora))
        self.conn.commit()

    def test_con_veinticuatro_recibos_iguales_no_propone_ninguno(self):
        """Marcar cobrado al vecino equivocado se descubre reclamando a quien pagó."""
        self.poblar()
        sugerencia = server.sugerir_conciliacion(
            self.conn, self.ws, self.com, {"fecha": "2026-08-12", "importe": 50.0})
        self.assertIsNone(sugerencia)

    def test_con_un_solo_candidato_si_lo_propone(self):
        self.poblar(cuantos=3, importe=50)
        self.conn.execute("UPDATE workspace_fincas_recibos SET importe = 77 WHERE id = 'r1'")
        self.conn.commit()
        sugerencia = server.sugerir_conciliacion(
            self.conn, self.ws, self.com, {"fecha": "2026-08-12", "importe": 77.0})
        self.assertIsNotNone(sugerencia)
        self.assertEqual(sugerencia["tipo"], "recibo")

    def test_un_abono_por_el_total_casa_con_la_remesa(self):
        self.poblar()
        self.conn.execute(
            "INSERT INTO workspace_fincas_remesas (id, workspace_id, comunidad_id, periodo, fecha_cobro, "
            "referencia, total, num_recibos, estado, created_at, updated_at) "
            "VALUES ('rem1',?,?,'2026-08','2026-08-05','CPX-2026-08',1150,23,'Generada',datetime(?),datetime(?))",
            (self.ws, self.com, self.ahora, self.ahora))
        self.conn.commit()
        sugerencia = server.sugerir_conciliacion(
            self.conn, self.ws, self.com, {"fecha": "2026-08-05", "importe": 1150.0})
        self.assertEqual(sugerencia["tipo"], "remesa")

    def test_un_gasto_no_se_casa_con_nada(self):
        self.poblar()
        self.assertIsNone(server.sugerir_conciliacion(
            self.conn, self.ws, self.com, {"fecha": "2026-08-15", "importe": -500.0}))

    def test_una_fecha_muy_lejana_no_casa(self):
        self.poblar(cuantos=1, importe=50)
        self.assertIsNone(server.sugerir_conciliacion(
            self.conn, self.ws, self.com, {"fecha": "2027-12-31", "importe": 50.0}))


class LaLiquidacionRepartElGastoRealTests(BaseConta):
    def setUp(self):
        super().setUp()
        for i in range(4):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, created_at, updated_at) VALUES (?,?,?,?,?,25,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"P{i}", f"{i+1}A", self.ahora, self.ahora))
            for mes in range(1, 13):
                self.conn.execute(
                    "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                    "concepto, importe, estado, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,'Cuota',100,'Cobrado',datetime(?),datetime(?))",
                    (f"r{i}_{mes}", self.ws, self.com, f"v{i}", f"2026-{mes:02d}", self.ahora, self.ahora))
        self.asiento("Limpieza", [{"cuenta": "628", "debe": 2400}, {"cuenta": "572", "haber": 2400}],
                     fecha="2026-06-30")
        self.asiento("Luz", [{"cuenta": "621", "debe": 900}, {"cuenta": "572", "haber": 900}],
                     fecha="2026-07-15")
        self.conn.commit()

    def test_lo_imputado_es_exactamente_el_gasto(self):
        """Si no, la suma de las liquidaciones no cuadra con la caja."""
        liq = server.fetch_workspace_fincas_liquidacion(self.conn, self.ws, self.com, "2026")
        self.assertEqual(liq["resumen"]["gasto"], 3300.0)
        self.assertEqual(liq["resumen"]["imputado"], 3300.0)

    def test_se_reparte_por_coeficiente(self):
        liq = server.fetch_workspace_fincas_liquidacion(self.conn, self.ws, self.com, "2026")
        self.assertEqual({f["imputado"] for f in liq["rows"]}, {825.0})

    def test_el_saldo_es_lo_pagado_menos_lo_que_le_tocaba(self):
        liq = server.fetch_workspace_fincas_liquidacion(self.conn, self.ws, self.com, "2026")
        self.assertEqual({f["saldo"] for f in liq["rows"]}, {375.0})

    def test_el_gasto_sale_del_diario_cuando_lo_hay(self):
        liq = server.fetch_workspace_fincas_liquidacion(self.conn, self.ws, self.com, "2026")
        self.assertEqual(liq["resumen"]["origen_gasto"], "diario")

    def test_sin_diario_cae_al_libro_simple(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        conn.execute("INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, created_at, "
                     "updated_at) VALUES ('c','w','X','Activa',datetime(?),datetime(?))", (self.ahora, self.ahora))
        conn.execute("INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                     "coeficiente, created_at, updated_at) VALUES ('v','w','c','P','1A',100,datetime(?),datetime(?))",
                     (self.ahora, self.ahora))
        conn.execute("INSERT INTO workspace_fincas_contabilidad (id, workspace_id, comunidad_id, fecha, tipo, "
                     "concepto, importe, created_at, updated_at) "
                     "VALUES ('m','w','c','2026-03-01','Gasto','Obra',500,datetime(?),datetime(?))",
                     (self.ahora, self.ahora))
        conn.commit()
        liq = server.fetch_workspace_fincas_liquidacion(conn, "w", "c", "2026")
        self.assertEqual(liq["resumen"]["gasto"], 500.0)
        self.assertEqual(liq["resumen"]["origen_gasto"], "libro simple")

    def test_sin_censo_no_revienta(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        liq = server.fetch_workspace_fincas_liquidacion(conn, "w", "c", "2026")
        self.assertEqual(liq["rows"], [])


class ElCierreDelEjercicioTests(LaLiquidacionRepartElGastoRealTests):
    def setUp(self):
        super().setUp()
        self.asiento("Cuotas del ejercicio", [{"cuenta": "440", "debe": 4800}, {"cuenta": "700", "haber": 4800}],
                     fecha="2026-01-31")
        self.asiento("Cobros", [{"cuenta": "572", "debe": 4800}, {"cuenta": "440", "haber": 4800}],
                     fecha="2026-12-20")
        self.conn.commit()

    def cerrar(self, **extra):
        r = server.cerrar_ejercicio_fincas(self.conn, self.ws, self.com, "2026", **extra)
        self.conn.commit()
        return r

    def test_deja_gastos_e_ingresos_a_cero(self):
        self.cerrar()
        saldos = {c["cuenta"]: c["saldo"]
                  for c in server.fetch_workspace_fincas_sumas_y_saldos(self.conn, self.ws, self.com, "2026")["cuentas"]}
        for cuenta in ("621", "628", "700"):
            with self.subTest(cuenta=cuenta):
                self.assertEqual(saldos.get(cuenta, 0.0), 0.0)

    def test_el_resultado_es_ingresos_menos_gastos(self):
        r = self.cerrar()
        self.assertEqual(r["resultado"], 1500.0)

    def test_la_dotacion_al_fondo_sale_del_resultado(self):
        self.cerrar(dotacion_fondo=330)
        saldos = {c["cuenta"]: c["saldo"]
                  for c in server.fetch_workspace_fincas_sumas_y_saldos(self.conn, self.ws, self.com, "2026")["cuentas"]}
        self.assertEqual(saldos["113"], -330.0)
        self.assertEqual(saldos["129"], -1170.0)

    def test_el_ejercicio_siguiente_abre_cuadrado(self):
        self.cerrar()
        d = server.fetch_workspace_fincas_diario(self.conn, self.ws, self.com, "2027")
        self.assertEqual(d["totales"]["descuadre"], 0.0)
        self.assertTrue(d["asientos"])

    def test_arrastra_la_tesoreria_al_ano_siguiente(self):
        self.cerrar()
        saldos = {c["cuenta"]: c["saldo"]
                  for c in server.fetch_workspace_fincas_sumas_y_saldos(self.conn, self.ws, self.com, "2027")["cuentas"]}
        self.assertEqual(saldos["572"], 1500.0)

    def test_no_se_cierra_dos_veces(self):
        """Cerrar dos veces duplicaría el resultado y el arrastre."""
        self.cerrar()
        with self.assertRaises(server.AsientoDescuadrado) as cm:
            self.cerrar()
        self.assertIn("ya está cerrado", str(cm.exception))

    def test_el_cierre_queda_en_el_diario(self):
        """Se hace con asientos, no tocando saldos: se puede auditar."""
        self.cerrar()
        d = server.fetch_workspace_fincas_diario(self.conn, self.ws, self.com, "2026")
        self.assertTrue(any(a["origen"] == "cierre" for a in d["asientos"]))


class LosEndpointsEstanGuardadosTests(unittest.TestCase):
    ESCRITURAS = (
        "/api/workspace_fincas_extracto_importar",
        "/api/workspace_fincas_extracto_conciliar",
        "/api/workspace_fincas_asiento",
        "/api/workspace_fincas_cerrar_ejercicio",
    )
    LECTURAS = (
        "/api/workspace_fincas_diario",
        "/api/workspace_fincas_liquidacion",
    )

    def test_las_escrituras_exigen_pertenencia(self):
        for ruta in self.ESCRITURAS:
            with self.subTest(ruta=ruta):
                i = SERVER.index(f'elif parsed.path == "{ruta}"')
                cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
                self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_todas_estan_dadas_de_alta(self):
        for ruta in self.ESCRITURAS:
            with self.subTest(ruta=ruta):
                self.assertIn(f'"{ruta}",', SERVER)

    def test_las_lecturas_comprueban(self):
        for ruta in self.LECTURAS:
            with self.subTest(ruta=ruta):
                i = SERVER.index(f'if path == "{ruta}"') if f'if path == "{ruta}"' in SERVER else SERVER.index(ruta)
                self.assertIn("enforce_workspace_membership", SERVER[i: i + 2000])

    def test_importar_rechaza_un_fichero_que_no_cuadra(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_extracto_importar"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("no cuadra con el saldo que él mismo declara", cuerpo)
        self.assertIn('payload.get("forzar")', cuerpo)

    def test_conciliar_un_cobro_marca_el_recibo(self):
        """Hacerlo en dos pasos separados se olvida a la mitad."""
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_extracto_conciliar"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("SET estado = 'Cobrado'", cuerpo)
        self.assertIn("SET estado = 'Devuelto'", cuerpo)

    def test_la_pantalla_avisa_si_el_diario_se_descuadra(self):
        self.assertIn("El diario está descuadrado", APP)

    def test_la_pantalla_explica_por_que_se_reparte_el_gasto_real(self):
        self.assertIn("un presupuesto es una previsión", APP)


if __name__ == "__main__":
    unittest.main()


class ElPlanDeCuentasEsElDelSectorTests(unittest.TestCase):
    """Mi primera versión me la inventé por analogía con el PGC de empresa y tenía
    tres códigos mal. El usuario preguntó si había mirado cómo lo hacen los programas
    del sector; no lo había hecho. El plan normalizado del Instituto Profesional de
    Administración Inmobiliaria dice otra cosa, y ahora se sigue ese.
    """

    def codigos(self):
        return {c[0]: c[1] for c in server.FINCAS_CUENTAS_DEFECTO}

    def test_los_tres_que_estaban_mal(self):
        codigos = self.codigos()
        self.assertIn("112", codigos)   # fondo de reserva, no la 113
        self.assertIn("4310", codigos)  # propietarios deudores, no la 440
        self.assertIn("7310", codigos)  # cuotas ordinarias, no la 700

    def test_la_700_ya_no_se_usa_para_cobrar_cuotas(self):
        """700 es «ventas de mercaderías»: cobrar cuotas contra ella era el peor."""
        self.assertNotIn("700", self.codigos())
        self.assertEqual(server.CUENTA_CUOTAS, "7310")

    def test_el_113_es_fondo_de_obras_no_de_reserva(self):
        self.assertIn("obras", self.codigos()["113"].lower())
        self.assertEqual(server.CUENTA_FONDO_RESERVA, "112")

    def test_la_440_es_de_deudores_que_no_son_propietarios(self):
        self.assertIn("no propietarios", self.codigos()["440"])
        self.assertEqual(server.CUENTA_PROPIETARIOS, "4310")

    def test_estan_las_cuentas_del_dia_a_dia(self):
        codigos = self.codigos()
        for cuenta, para_que in (("6699", "devolución de recibos"), ("6693", "comisiones bancarias"),
                                 ("4751", "retenciones"), ("120", "remanente"), ("435", "impagados"),
                                 ("437", "anticipos"), ("4459", "reclamados judicialmente")):
            with self.subTest(cuenta=cuenta, para_que=para_que):
                self.assertIn(cuenta, codigos)

    def test_no_hay_codigos_repetidos(self):
        codigos = [c[0] for c in server.FINCAS_CUENTAS_DEFECTO]
        self.assertEqual(len(codigos), len(set(codigos)))

    def test_el_codigo_no_reparte_literales_por_ahi(self):
        """Cambiar una convención tiene que ser cambiar una constante."""
        for nombre in ("CUENTA_BANCO", "CUENTA_PROPIETARIOS", "CUENTA_CUOTAS",
                       "CUENTA_FONDO_RESERVA", "CUENTA_RETENCIONES"):
            with self.subTest(nombre=nombre):
                self.assertIn(getattr(server, nombre), self.codigos())


class NoTodosPaganTodoTests(BaseConta):
    """El hueco de fondo: la primera versión repartía todo con un único coeficiente,
    y eso le cobra la limpieza de la escalera al local del bajo que no tiene acceso
    al portal. El ejemplo es el del artículo de referencia: un bajo y 16 viviendas,
    presupuesto de 10.000 € de los que 4.000 son servicios de vivienda.
    """

    def setUp(self):
        super().setUp()
        self.conn.execute(
            "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, coeficiente, "
            "created_at, updated_at) VALUES ('bajo',?,?,'Local','Bajo',10,datetime(?),datetime(?))",
            (self.ws, self.com, self.ahora, self.ahora))
        for i in range(16):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, created_at, updated_at) VALUES (?,?,?,?,?,?,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"Vivienda {i}", f"{i//4+1}{'ABCD'[i%4]}", 90 / 16,
                 self.ahora, self.ahora))
        self.conn.commit()
        self.general = server.fetch_workspace_fincas_grupos(self.conn, self.ws, self.com)[0]
        self.viviendas = os.urandom(8).hex()
        self.conn.execute(
            "INSERT INTO workspace_fincas_grupos (id, workspace_id, comunidad_id, clave, nombre, cuenta_gasto, "
            "activo, orden, created_at, updated_at) "
            "VALUES (?,?,?,'viviendas','Gastos de viviendas','6223',1,2,?,?)",
            (self.viviendas, self.ws, self.com, self.ahora, self.ahora))
        for i in range(16):
            self.conn.execute(
                "INSERT INTO workspace_fincas_coeficientes (id, workspace_id, grupo_id, vecino_id, coeficiente, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (os.urandom(8).hex(), self.ws, self.viviendas, f"v{i}", 100 / 16, self.ahora, self.ahora))
        self.conn.commit()

    def reparte(self):
        return server.reparte_por_grupos(self.conn, self.ws, self.com, [
            {"concepto": "Gastos generales", "importe": 6000, "grupo_id": self.general["id"]},
            {"concepto": "Servicios de viviendas", "importe": 4000, "grupo_id": self.viviendas},
        ])

    def test_el_general_se_siembra_con_el_censo(self):
        self.assertEqual(self.general["clave"], "general")
        self.assertEqual(self.general["participantes"], 17)
        self.assertTrue(self.general["cuadra"])

    def test_el_bajo_no_paga_los_servicios_de_vivienda(self):
        """10 % de 6.000 y nada de los 4.000."""
        self.assertEqual(self.reparte()["reparto"]["bajo"], 600.0)

    def test_cada_vivienda_paga_de_los_dos_grupos(self):
        """5,625 % de 6.000 más 6,25 % de 4.000."""
        self.assertEqual(self.reparte()["reparto"]["v0"], 587.50)

    def test_la_suma_es_exactamente_el_gasto(self):
        self.assertEqual(self.reparte()["total"], 10000.0)

    def test_un_grupo_que_no_suma_cien_se_avisa(self):
        """Lo que falte no se le cobra a nadie."""
        self.conn.execute("UPDATE workspace_fincas_coeficientes SET coeficiente = 3 "
                          "WHERE grupo_id = ? AND vecino_id = 'v0'", (self.viviendas,))
        self.conn.commit()
        self.assertTrue(any("no 100 %" in a for a in self.reparte()["avisos"]))

    def test_la_liquidacion_reparte_por_grupos(self):
        self.asiento("Limpieza de viviendas", [{"cuenta": "6223", "debe": 4000},
                                               {"cuenta": "572", "haber": 4000}], fecha="2026-05-01")
        self.asiento("Seguro del edificio", [{"cuenta": "621", "debe": 6000},
                                             {"cuenta": "572", "haber": 6000}], fecha="2026-05-02")
        self.conn.commit()
        liq = server.fetch_workspace_fincas_liquidacion(self.conn, self.ws, self.com, "2026")
        porv = {f["vecino_id"]: f["imputado"] for f in liq["rows"]}
        self.assertEqual(porv["bajo"], 600.0)
        self.assertEqual(porv["v0"], 587.50)
        self.assertEqual(liq["resumen"]["imputado"], 10000.0)
        self.assertTrue(liq["resumen"]["por_grupos"])

    def test_sin_grupos_configurados_sigue_funcionando(self):
        """Quien no configure grupos reparte todo por el general, como antes."""
        self.conn.execute("DELETE FROM workspace_fincas_coeficientes WHERE grupo_id = ?", (self.viviendas,))
        self.conn.execute("DELETE FROM workspace_fincas_grupos WHERE id = ?", (self.viviendas,))
        self.asiento("Gasto único", [{"cuenta": "621", "debe": 1000}, {"cuenta": "572", "haber": 1000}],
                     fecha="2026-05-01")
        self.conn.commit()
        liq = server.fetch_workspace_fincas_liquidacion(self.conn, self.ws, self.com, "2026")
        self.assertEqual(liq["resumen"]["imputado"], 1000.0)
        self.assertFalse(liq["resumen"]["por_grupos"])


class RetencionesYModelo347Tests(BaseConta):
    def factura(self, **kw):
        base = {"fecha": "2026-03-10", "concepto": "Servicios", "base": 1000, "cuenta_gasto": "628"}
        base.update(kw)
        r = server.registrar_factura_proveedor(self.conn, self.ws, self.com, **base)
        self.conn.commit()
        return r

    def test_la_factura_con_retencion_cuadra(self):
        self.factura(iva=210, retencion=150, proveedor="Fincas Velazquez SL")
        d = server.fetch_workspace_fincas_diario(self.conn, self.ws, self.com, "2026")
        self.assertEqual(d["totales"]["descuadre"], 0.0)

    def test_el_proveedor_cobra_menos_la_retencion(self):
        self.factura(iva=210, retencion=150, proveedor="X")
        apuntes = {p["cuenta"]: p for a in server.fetch_workspace_fincas_diario(
            self.conn, self.ws, self.com, "2026")["asientos"] for p in a["apuntes"]}
        self.assertEqual(apuntes["400"]["haber"], 1060.0)
        self.assertEqual(apuntes[server.CUENTA_RETENCIONES]["haber"], 150.0)

    def test_el_iva_no_deducible_engorda_el_gasto(self):
        """En una comunidad el IVA soportado no suele ser deducible."""
        self.factura(iva=210, proveedor="X")
        apuntes = {p["cuenta"]: p for a in server.fetch_workspace_fincas_diario(
            self.conn, self.ws, self.com, "2026")["asientos"] for p in a["apuntes"]}
        self.assertEqual(apuntes["628"]["debe"], 1210.0)

    def test_una_retencion_mayor_que_la_base_se_rechaza(self):
        with self.assertRaises(server.AsientoDescuadrado):
            self.factura(base=100, retencion=200)

    def test_las_retenciones_se_agrupan_por_trimestre(self):
        self.factura(fecha="2026-02-10", retencion=100, proveedor="A")
        self.factura(fecha="2026-08-10", retencion=50, proveedor="B")
        r = server.fetch_retenciones_practicadas(self.conn, self.ws, self.com, "2026")
        self.assertEqual(r["trimestres"][1], 100.0)
        self.assertEqual(r["trimestres"][3], 50.0)
        self.assertEqual(r["total"], 150.0)

    def test_el_347_solo_declara_a_quien_supera_el_umbral(self):
        self.factura(base=4000, proveedor="Grande SL")
        self.factura(base=500, proveedor="Pequeña SL")
        m = server.fetch_modelo_347(self.conn, self.ws, self.com, "2026")
        self.assertEqual([t["tercero"] for t in m["declarables"]], ["Grande SL"])
        self.assertEqual([t["tercero"] for t in m["por_debajo"]], ["Pequeña SL"])

    def test_el_umbral_es_el_de_la_norma(self):
        self.assertEqual(server.MODELO_347_UMBRAL, 3005.06)

    def test_acumula_varias_facturas_del_mismo_tercero(self):
        self.factura(fecha="2026-02-01", base=2000, proveedor="Limpiezas SL")
        self.factura(fecha="2026-07-01", base=1500, proveedor="Limpiezas SL")
        m = server.fetch_modelo_347(self.conn, self.ws, self.com, "2026")
        self.assertEqual(m["declarables"][0]["importe"], 3500.0)
        self.assertEqual(m["declarables"][0]["facturas"], 2)

    def test_avisa_de_proveedores_que_parecen_el_mismo(self):
        """Separados pueden quedarse los dos por debajo del umbral."""
        self.factura(base=2000, proveedor="Limpiezas del Sur SL")
        self.factura(base=1500, proveedor="Limpiezas del Sur, S.L.")
        m = server.fetch_modelo_347(self.conn, self.ws, self.com, "2026")
        self.assertTrue(m["avisos"])

    def test_reparte_por_trimestres(self):
        self.factura(fecha="2026-02-01", base=4000, proveedor="X")
        m = server.fetch_modelo_347(self.conn, self.ws, self.com, "2026")
        self.assertEqual(m["declarables"][0]["trimestres"][1], 4000.0)


class ElModuloSigueExponiendoLoSuyoTests(unittest.TestCase):
    """Guardián contra un error que cometí de verdad: al sustituir el plan de cuentas
    con un reemplazo por rangos, me llevé por delante el lector de norma 43, que
    estaba justo en medio del tramo. Lo cazaron los tests del extracto, pero una
    comprobación explícita cuesta cuatro líneas y falla con un mensaje claro.
    """

    PIEZAS = (
        "parse_norma43", "huella_movimiento", "sugerir_conciliacion",
        "registrar_asiento", "AsientoDescuadrado", "cerrar_ejercicio_fincas",
        "fetch_workspace_fincas_diario", "fetch_workspace_fincas_sumas_y_saldos",
        "fetch_workspace_fincas_liquidacion", "fetch_workspace_fincas_grupos",
        "reparte_por_grupos", "registrar_factura_proveedor", "fetch_modelo_347",
        "fetch_retenciones_practicadas", "build_mapa_estatico", "nif_valido",
        "iban_valido", "reparte_por_coeficiente", "parse_censo_vecinos",
        "render_carta_presentacion", "fetch_fincas_portal_public",
    )

    def test_estan_todas(self):
        for pieza in self.PIEZAS:
            with self.subTest(pieza=pieza):
                self.assertTrue(hasattr(server, pieza), f"falta {pieza}: ¿un reemplazo se la ha llevado?")
