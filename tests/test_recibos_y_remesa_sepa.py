"""Cuotas, recibos y remesa de domiciliación.

Es lo que un administrador de fincas hace cada mes y lo que no existía: `workspace_cobros`
colgaba del módulo genérico de facturación y no había ningún concepto de recibo de
comunidad. Sin esto, el resto del módulo es una agenda con fotos del edificio.

Tres cosas de las que se hacen aquí merecen un test propio porque el fallo silencioso
cuesta dinero de verdad:

**El reparto tiene que sumar el total exacto.** Repartir 1.200 € entre 24 vecinos al
4,1667 % deja céntimos sueltos por el redondeo. Si se pierden, la contabilidad de la
comunidad se desvía un poco cada mes; si se le cargan todos al mismo, ese vecino paga
50,23 € mientras los demás pagan 49,99 € y lo nota. Se reparten por resto mayor: la suma
cuadra al céntimo y nadie se separa más de un céntimo de los demás.

**El IBAN se comprueba antes de mandarlo al banco.** Un dígito mal tecleado no lo detecta
la entidad hasta que devuelve la remesa, y para entonces el mes se daba por cobrado. El
resto módulo 97 de la ISO 13616 lo caza al teclearlo.

**No se emite dos veces el mismo periodo.** Es la forma más rápida de cobrarle dos veces
a toda la comunidad, así que hay índice único y hay que pedirlo a propósito.

Sobre el fichero SEPA: se genera pain.008.001.02 con el esquema estándar, pero cada banco
tiene sus manías —el BIC, el sufijo del identificador de acreedor, cuántas secuencias
admite por fichero—. Antes de usarlo en producción hay que validar uno de prueba con la
entidad. El primer adeudo de un mandato sale como `FRST` y los siguientes como `RCUR`,
en bloques `PmtInf` separados: el `SeqTp` vive a nivel de bloque y hay entidades que no
admiten mezclarlos en uno solo. Cuáles son los primeros lo decide quien llama, porque lo
sabe la base de datos y no el generador del fichero.
"""

import datetime
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402

NS = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"}
IBAN_BUENO = "ES9121000418450200051332"


class ElIbanSeComprubaTests(unittest.TestCase):
    def test_uno_bueno_pasa(self):
        self.assertTrue(server.iban_valido(IBAN_BUENO))

    def test_da_igual_como_venga_escrito(self):
        self.assertTrue(server.iban_valido("ES91 2100 0418 4502 0005 1332"))
        self.assertTrue(server.iban_valido("es91-2100-0418-4502-0005-1332"))

    def test_un_digito_cambiado_no_pasa(self):
        """Es justo el error que el banco no te dice hasta devolver la remesa."""
        self.assertFalse(server.iban_valido("ES9121000418450200051333"))

    def test_lo_que_no_es_un_iban_no_pasa(self):
        for valor in ("", None, "hola", "ES91210004184502000513", "1234"):
            with self.subTest(valor=valor):
                self.assertFalse(server.iban_valido(valor))

    def test_se_agrupa_de_cuatro_en_cuatro_para_leerlo(self):
        self.assertEqual(server.formatear_iban(IBAN_BUENO), "ES91 2100 0418 4502 0005 1332")


class ElRepartoNoPierdeNiUnCentimoTests(unittest.TestCase):
    def _reparte(self, total, coeficientes):
        vecinos = [{"id": f"v{i}", "coeficiente": c} for i, c in enumerate(coeficientes)]
        reparto, por_partes = server.reparte_por_coeficiente(total, vecinos)
        return [importe for _v, importe in reparto], por_partes

    def test_la_suma_es_exacta(self):
        for total, coefs in (
            (1200, [4.1667] * 24),
            (100, [100 / 7] * 7),
            (1000.01, [50, 30, 20]),
            (5000, [100 / 177] * 177),
            (0.01, [20] * 5),
        ):
            with self.subTest(total=total, n=len(coefs)):
                importes, _ = self._reparte(total, coefs)
                self.assertEqual(round(sum(importes), 2), round(total, 2))

    def test_entre_iguales_nadie_paga_mas_de_un_centimo_de_diferencia(self):
        """Con el resto al de mayor coeficiente, uno pagaba 50,23 y el resto 49,99."""
        importes, _ = self._reparte(1200, [4.1667] * 24)
        self.assertLessEqual(round(max(importes) - min(importes), 2), 0.01)

    def test_veinticuatro_partes_iguales_de_mil_doscientos_son_cincuenta(self):
        importes, _ = self._reparte(1200, [4.1667] * 24)
        self.assertEqual(set(importes), {50.0})

    def test_respeta_los_coeficientes_desiguales(self):
        importes, _ = self._reparte(1000, [50, 30, 20])
        self.assertEqual(importes, [500.0, 300.0, 200.0])

    def test_sin_coeficientes_reparte_a_partes_iguales_y_lo_dice(self):
        """Quien llama tiene que poder avisar de que no se usó ningún coeficiente."""
        importes, por_partes = self._reparte(100, [None, None, None])
        self.assertTrue(por_partes)
        self.assertEqual(round(sum(importes), 2), 100.0)

    def test_dos_emisiones_iguales_dan_lo_mismo(self):
        """Si el desempate no fuera estable, reemitir cambiaría lo que paga cada uno."""
        a, _ = self._reparte(100, [100 / 7] * 7)
        b, _ = self._reparte(100, [100 / 7] * 7)
        self.assertEqual(a, b)

    def test_sin_propietarios_o_sin_importe_no_reparte_nada(self):
        self.assertEqual(server.reparte_por_coeficiente(100, [])[0], [])
        self.assertEqual(server.reparte_por_coeficiente(0, [{"coeficiente": 1}])[0], [])


class ElFicheroSepaTests(unittest.TestCase):
    def setUp(self):
        self.comunidad = {"nombre": "C.P. Velázquez 11", "iban": IBAN_BUENO, "acreedor_sepa": "ES12ZZZ12345678"}
        self.remesa = {"referencia": "CPVELAZQUEZ-2026-08", "fecha_cobro": "2026-08-05"}
        self.recibos = [
            {"nombre": "Juan Pérez", "iban": IBAN_BUENO, "mandato_ref": "MND-1A",
             "mandato_fecha": "2024-01-15", "importe": 50.0, "concepto": "Cuota 2026-08", "vecino_id": "v1"},
            {"nombre": "Ana Ruiz", "iban": IBAN_BUENO, "mandato_ref": "MND-1B",
             "mandato_fecha": "2024-01-15", "importe": 50.01, "concepto": "Cuota 2026-08", "vecino_id": "v2"},
        ]
        self.xml = server.build_remesa_sepa_xml(
            self.remesa, self.comunidad, self.recibos, ahora=datetime.datetime(2026, 8, 1, 9, 0, 0)
        )
        self.raiz = ET.fromstring(self.xml)

    def test_es_xml_bien_formado_del_esquema_correcto(self):
        self.assertTrue(self.raiz.tag.endswith("}Document"))
        self.assertIn(b"pain.008.001.02", self.xml)

    def test_el_numero_de_adeudos_cuadra(self):
        self.assertEqual(self.raiz.find(".//p:GrpHdr/p:NbOfTxs", NS).text, "2")
        self.assertEqual(len(self.raiz.findall(".//p:DrctDbtTxInf", NS)), 2)

    def test_el_sumatorio_cuadra_con_los_importes(self):
        """Si CtrlSum no coincide con la suma, el banco rechaza el fichero entero."""
        declarado = float(self.raiz.find(".//p:GrpHdr/p:CtrlSum", NS).text)
        real = sum(float(e.text) for e in self.raiz.findall(".//p:InstdAmt", NS))
        self.assertEqual(round(declarado, 2), round(real, 2))
        self.assertEqual(round(real, 2), 100.01)

    def test_lleva_el_acreedor_y_su_cuenta(self):
        self.assertEqual(self.raiz.find(".//p:CdtrAcct//p:IBAN", NS).text, IBAN_BUENO)
        self.assertEqual(self.raiz.find(".//p:CdtrSchmeId//p:Othr/p:Id", NS).text, "ES12ZZZ12345678")

    def test_cada_adeudo_lleva_su_mandato(self):
        mandatos = [e.text for e in self.raiz.findall(".//p:MndtId", NS)]
        self.assertEqual(mandatos, ["MND-1A", "MND-1B"])

    def test_las_referencias_de_los_adeudos_no_se_repiten(self):
        refs = [e.text for e in self.raiz.findall(".//p:EndToEndId", NS)]
        self.assertEqual(len(refs), len(set(refs)))

    def test_las_tildes_no_llegan_al_banco(self):
        """Muchas entidades rechazan el fichero con caracteres fuera del juego básico."""
        nombres = [e.text for e in self.raiz.findall(".//p:Dbtr/p:Nm", NS)]
        self.assertIn("Juan Perez", nombres)
        acreedor = self.raiz.find(".//p:Cdtr/p:Nm", NS).text
        self.assertEqual(acreedor, "C.P. Velazquez 11")

    def test_el_importe_va_con_dos_decimales(self):
        for e in self.raiz.findall(".//p:InstdAmt", NS):
            with self.subTest(importe=e.text):
                self.assertRegex(e.text, r"^\d+\.\d{2}$")
            self.assertEqual(e.get("Ccy"), "EUR")

    def test_sin_saber_cuales_son_primeros_todo_va_como_recurrente(self):
        """El comportamiento de siempre cuando no se pasa `primeros`: un solo bloque
        RCUR. Vale para quien llame sin el argumento."""
        self.assertEqual([e.text for e in self.raiz.findall(".//p:SeqTp", NS)], ["RCUR"])
        self.assertEqual(len(self.raiz.findall(".//p:PmtInf", NS)), 1)

    def test_avisa_de_que_hay_que_validarlo_con_el_banco(self):
        i = SERVER.index("def build_remesa_sepa_xml")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("validar un fichero de prueba con la entidad", cuerpo)


class ElPrimerAdeudoDeUnMandatoTests(unittest.TestCase):
    """`FRST` el primero, `RCUR` los siguientes, y en bloques separados.

    Antes salía todo como `RCUR` y estaba documentado como pendiente. El motivo era
    real: distinguirlo exige saber qué mandatos ya han cobrado alguna vez, y eso lo
    sabe la base, no el generador del fichero. Ahora se le pasa en `primeros`.

    Los dos grupos van en bloques `PmtInf` distintos porque el `SeqTp` vive a nivel de
    bloque; mezclarlos obligaría a repetirlo por operación y hay entidades que no lo
    admiten.
    """

    def setUp(self):
        self.comunidad = {"nombre": "C.P. Velazquez 11", "iban": IBAN_BUENO,
                          "acreedor_sepa": "ES12ZZZ12345678"}
        self.remesa = {"referencia": "CPV-2026-09", "fecha_cobro": "2026-09-05"}
        self.recibos = [
            {"nombre": "Juan Perez", "iban": IBAN_BUENO, "mandato_ref": "MND-1A",
             "mandato_fecha": "2024-01-15", "importe": 50.0, "concepto": "Cuota", "vecino_id": "v1"},
            {"nombre": "Ana Ruiz", "iban": IBAN_BUENO, "mandato_ref": "MND-1B",
             "mandato_fecha": "2026-08-20", "importe": 30.0, "concepto": "Cuota", "vecino_id": "v2"},
        ]

    def _arbol(self, primeros=None):
        return ET.fromstring(server.build_remesa_sepa_xml(
            self.remesa, self.comunidad, self.recibos, primeros=primeros,
            ahora=datetime.datetime(2026, 9, 1, 9, 0, 0)))

    def _bloques(self, raiz):
        return {pi.find(".//p:SeqTp", NS).text: pi for pi in raiz.findall(".//p:PmtInf", NS)}

    def test_el_nuevo_va_en_su_propio_bloque_frst(self):
        bloques = self._bloques(self._arbol({"MND-1B"}))
        self.assertEqual(sorted(bloques), ["FRST", "RCUR"])
        self.assertEqual(bloques["FRST"].find(".//p:MndtId", NS).text, "MND-1B")
        self.assertEqual(bloques["RCUR"].find(".//p:MndtId", NS).text, "MND-1A")

    def test_cada_bloque_declara_lo_suyo(self):
        bloques = self._bloques(self._arbol({"MND-1B"}))
        self.assertEqual(bloques["FRST"].find("p:NbOfTxs", NS).text, "1")
        self.assertEqual(bloques["FRST"].find("p:CtrlSum", NS).text, "30.00")
        self.assertEqual(bloques["RCUR"].find("p:NbOfTxs", NS).text, "1")
        self.assertEqual(bloques["RCUR"].find("p:CtrlSum", NS).text, "50.00")

    def test_la_cabecera_sigue_cuadrando_con_la_suma_de_los_bloques(self):
        """Si el total del fichero no cuadra, el banco lo rechaza entero."""
        raiz = self._arbol({"MND-1B"})
        self.assertEqual(raiz.find(".//p:GrpHdr/p:NbOfTxs", NS).text, "2")
        self.assertEqual(raiz.find(".//p:GrpHdr/p:CtrlSum", NS).text, "80.00")
        suma = sum(float(pi.find("p:CtrlSum", NS).text) for pi in raiz.findall(".//p:PmtInf", NS))
        cuantos = sum(int(pi.find("p:NbOfTxs", NS).text) for pi in raiz.findall(".//p:PmtInf", NS))
        self.assertEqual(round(suma, 2), 80.00)
        self.assertEqual(cuantos, 2)

    def test_los_dos_bloques_no_comparten_identificador(self):
        raiz = self._arbol({"MND-1B"})
        ids = [pi.find("p:PmtInfId", NS).text for pi in raiz.findall(".//p:PmtInf", NS)]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_el_frst_va_delante(self):
        """Si la entidad procesa por orden, el primer adeudo del mandato va antes."""
        raiz = self._arbol({"MND-1B"})
        self.assertEqual([pi.find(".//p:SeqTp", NS).text for pi in raiz.findall(".//p:PmtInf", NS)],
                         ["FRST", "RCUR"])

    def test_si_todos_son_primeros_no_se_parte_en_dos(self):
        raiz = self._arbol({"MND-1A", "MND-1B"})
        self.assertEqual(len(raiz.findall(".//p:PmtInf", NS)), 1)
        self.assertEqual(raiz.find(".//p:SeqTp", NS).text, "FRST")
        self.assertEqual(raiz.find(".//p:PmtInfId", NS).text, "CPV-2026-09")

    def test_quien_decide_es_el_endpoint_y_mira_la_base(self):
        """Nunca cobrado -> FRST. Y firmado después del último cobro -> FRST otra vez,
        porque eso es un mandato nuevo del mismo propietario."""
        i = SERVER.index('if path == "/api/workspace_fincas_remesa_sepa"')
        cuerpo = SERVER[i: SERVER.index("\n        if path ==", i + 10)]
        self.assertIn("MAX(rm.fecha_cobro)", cuerpo)
        self.assertIn("primeros=primeros", cuerpo)
        self.assertIn("firma > anterior", cuerpo)
        self.assertIn("r.remesa_id != ?", cuerpo)


class ElCircuitoCompletoTests(unittest.TestCase):
    """De censo a fichero, sobre una base de verdad (SQLite en memoria)."""

    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com = "ws1", "com1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, num_vecinos, "
            "cuota_mensual, iban, acreedor_sepa, created_at, updated_at) "
            "VALUES (?,?,?,'Activa',?,?,?,?,datetime(?),datetime(?))",
            (self.com, self.ws, "C.P. Velázquez 11", 24, 1200.0, IBAN_BUENO, "ES12ZZZ12345678", ahora, ahora),
        )
        # 24 propietarios; el sexto con la cuenta mal.
        for i in range(24):
            piso = f"{i // 4 + 1}{'ABCD'[i % 4]}"
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, iban, mandato_ref, mandato_fecha, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"Propietario {piso}", piso, 4.1667,
                 IBAN_BUENO if i != 5 else "ES0000", f"MND-{piso}", "2024-01-15", ahora, ahora),
            )
        self.conn.commit()

    def _emite(self, periodo="2026-08", total=1200.0):
        props = self.conn.execute(
            "SELECT id, nombre, piso, coeficiente, iban FROM workspace_fincas_vecinos "
            "WHERE comunidad_id = ? ORDER BY piso", (self.com,)
        ).fetchall()
        reparto, _ = server.reparte_por_coeficiente(total, props)
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        for vecino, importe in reparto:
            self.conn.execute(
                "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                "concepto, importe, coeficiente, estado, fecha_emision, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,'Pendiente',?,datetime(?),datetime(?))",
                (os.urandom(8).hex(), self.ws, self.com, server.row_value(vecino, "id", ""), periodo,
                 f"Cuota de comunidad {periodo}", importe, server.row_value(vecino, "coeficiente", None),
                 "2026-08-01", ahora, ahora),
            )
        self.conn.commit()

    def test_el_censo_cuadra_a_cien(self):
        resumen = server.fetch_workspace_fincas_censo_resumen(self.conn, self.ws, self.com)
        self.assertEqual(resumen["propietarios"], 24)
        self.assertTrue(resumen["cuadra"])

    def test_lo_emitido_es_lo_que_se_reparte(self):
        self._emite()
        datos = server.fetch_workspace_fincas_recibos(self.conn, self.ws, self.com, periodo="2026-08")
        self.assertEqual(datos["resumen"]["recibos"], 24)
        self.assertEqual(datos["resumen"]["emitido"], 1200.0)
        self.assertEqual(datos["resumen"]["pendiente"], 1200.0)

    def test_avisa_de_los_que_no_tienen_cuenta_valida(self):
        self._emite()
        datos = server.fetch_workspace_fincas_recibos(self.conn, self.ws, self.com, periodo="2026-08")
        self.assertEqual(datos["resumen"]["sin_iban"], 1)

    def test_el_iban_entero_no_sale_del_servidor(self):
        """En una lista de pantalla basta con los cuatro últimos."""
        self._emite()
        datos = server.fetch_workspace_fincas_recibos(self.conn, self.ws, self.com, periodo="2026-08")
        for fila in datos["rows"]:
            self.assertNotIn("iban", fila)
            self.assertLessEqual(len(fila["iban_cola"]), 4)

    def test_no_se_puede_emitir_dos_veces_el_mismo_periodo(self):
        """Es la forma más rápida de cobrarle dos veces a toda la comunidad."""
        import sqlite3

        self._emite()
        with self.assertRaises(sqlite3.IntegrityError):
            self._emite()

    def test_la_remesa_deja_fuera_al_del_iban_malo(self):
        self._emite()
        candidatos = self.conn.execute(
            "SELECT r.id, r.importe, v.iban FROM workspace_fincas_recibos r "
            "LEFT JOIN workspace_fincas_vecinos v ON v.id = r.vecino_id "
            "WHERE r.comunidad_id = ? AND r.periodo = '2026-08'", (self.com,)
        ).fetchall()
        incluidos = [c for c in candidatos if server.iban_valido(server.row_value(c, "iban", ""))]
        self.assertEqual(len(candidatos), 24)
        self.assertEqual(len(incluidos), 23)


class LosEndpointsEstanBienGuardadosTests(unittest.TestCase):
    RUTAS = (
        "/api/workspace_fincas_recibos_emitir",
        "/api/workspace_fincas_recibo_estado",
        "/api/workspace_fincas_remesa_generar",
    )

    def _manejador(self, ruta):
        i = SERVER.index(f'elif parsed.path == "{ruta}"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_estan_dados_de_alta(self):
        for ruta in self.RUTAS:
            with self.subTest(ruta=ruta):
                self.assertIn(f'"{ruta}",', SERVER)

    def test_todos_exigen_pertenencia_con_escritura(self):
        for ruta in self.RUTAS:
            with self.subTest(ruta=ruta):
                self.assertIn(
                    "enforce_workspace_membership(conn, session, workspace_id, write=True)",
                    self._manejador(ruta),
                )

    def test_los_get_tambien_comprueban(self):
        for ruta in ("/api/workspace_fincas_recibos", "/api/workspace_fincas_remesa_sepa"):
            with self.subTest(ruta=ruta):
                i = SERVER.index(f'if path == "{ruta}"')
                self.assertIn("enforce_workspace_membership", SERVER[i: i + 1500])

    def test_emitir_exige_censo(self):
        cuerpo = self._manejador("/api/workspace_fincas_recibos_emitir")
        self.assertIn("no tiene censo", cuerpo)

    def test_la_remesa_exige_cuenta_y_acreedor(self):
        cuerpo = self._manejador("/api/workspace_fincas_remesa_generar")
        self.assertIn("la cuenta de la comunidad", cuerpo)
        self.assertIn("el identificador de acreedor SEPA", cuerpo)

    def test_la_pantalla_avisa_de_los_recibos_sin_cuenta(self):
        self.assertIn("sin cuenta válida", APP)
        self.assertIn("tumba el fichero entero en el banco", APP)


if __name__ == "__main__":
    unittest.main()
