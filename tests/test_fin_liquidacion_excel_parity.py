import unittest

from web.server import compute_hipoteca_liquidacion_print_data


class FinLiquidacionExcelParityTests(unittest.TestCase):
    def build_base_case(self):
        export_row = {
            # Campos base de la ficha (sirven como fallback si faltan en el JSON)
            "precio": 90000.0,
            "importe_hipoteca": 54000.0,
        }
        liquidacion = {
            "comprador": {
                "precio_compra": 90000.0,
                "escriturado": 90000.0,
                "gastos_compraventa": {
                    "notaria": 1302.88,
                    "registro": 396.10,
                    "itp": 3150.00,
                    "gestoria": 278.30,
                },
                "hipoteca": {
                    "capital": 54000.0,
                    "notaria_impuestos_gestoria": 0.0,
                    "comision_apertura": 0.0,
                    "cuota_socio": 150.0,
                    "comision_cheques": 200.0,
                    "seguro_proteccion_pago": 694.76,
                    "seguro_hogar": 360.53,
                    "seguro_vida": 0.0,
                    "seguro_proteccion_financiado": "No",
                    "seguro_hogar_financiado": "No",
                    "seguro_vida_financiado": "No",
                },
                "gestion_inmobiliaria": 0.0,
                "gestion_financiacion": 2500.0,
                "entregas": {
                    "senal": 38000.0,
                    "transf_modernia": 2500.0,
                    "prestamo_concedido": 54000.0,
                    # "ingresar_banco": vacío -> lo autocalcula (redondeo a 100€)
                },
            },
            "vendedor": {
                "precio_vivienda": 90000.0,
                "deducciones": {
                    # Señal se autorrellena desde comprador si faltase, la dejamos explícita.
                    "senal": 38000.0,
                    # Ajuste para que el ejemplo cuadre con escriturado:
                    # 90.000 - 38.000 - 605,91 = 51.394,09
                    "cancelacion_registral": 605.91,
                },
                "vendedores": {
                    "v1": {"nombre": "VENDEDOR 1", "nif": "00000000X"},
                    "v2": {"nombre": "", "nif": ""},
                },
            },
            "cuadre": {},
            "notaria": {},
            "prestamo": {},
        }
        return export_row, liquidacion

    def test_autocalculo_ingresar_banco_y_totales_comprador(self):
        export_row, liquidacion = self.build_base_case()
        out = compute_hipoteca_liquidacion_print_data(export_row, liquidacion)
        liq = out["liq"]
        comprador = liq["comprador"]
        gastos_cv = comprador["gastos_compraventa"]
        hip = comprador["hipoteca"]
        entregas = comprador["entregas"]

        self.assertAlmostEqual(gastos_cv["total"], 5127.28, places=2)
        self.assertAlmostEqual(hip["total_gastos"], 1044.76, places=2)
        self.assertAlmostEqual(hip["total_bloque"], 1405.29, places=2)
        self.assertAlmostEqual(hip["total_necesario"], 1405.29, places=2)
        self.assertAlmostEqual(comprador["suma_total_necesaria"], 99032.57, places=2)

        # Excel: autocalcula y redondea al siguiente 100€
        self.assertAlmostEqual(entregas["ingresar_banco"], 4600.0, places=2)
        self.assertAlmostEqual(comprador["suma_total_entregada"], 45100.0, places=2)
        self.assertAlmostEqual(comprador["sobran_en_cuenta"], 67.43, places=2)

    def test_respeta_ingresar_banco_manual(self):
        export_row, liquidacion = self.build_base_case()
        liquidacion["comprador"]["entregas"]["ingresar_banco"] = 4700.0
        out = compute_hipoteca_liquidacion_print_data(export_row, liquidacion)
        liq = out["liq"]
        comprador = liq["comprador"]
        entregas = comprador["entregas"]

        self.assertAlmostEqual(entregas["ingresar_banco"], 4700.0, places=2)
        self.assertAlmostEqual(comprador["suma_total_entregada"], 45200.0, places=2)
        self.assertAlmostEqual(comprador["sobran_en_cuenta"], 167.43, places=2)

    def test_cuadre_cheques_sobrante_igual_que_comprador(self):
        export_row, liquidacion = self.build_base_case()
        out = compute_hipoteca_liquidacion_print_data(export_row, liquidacion)
        liq = out["liq"]
        comprador = liq["comprador"]
        cuadre = liq["cuadre"]

        # En este caso, con:
        # - total medios de pago = 90.000 (cuadra con escriturado)
        # - total salidas = 58.532,57
        # - prestamo + ingreso = 58.600
        # => sobrante 67,43 (igual que comprador)
        self.assertAlmostEqual(cuadre["sobran_en_cuenta"], comprador["sobran_en_cuenta"], places=2)

        flags = out["flags"]
        self.assertTrue(flags["cuadre_sobrante_ok"])
        self.assertAlmostEqual(flags["cuadre_sobrante_delta"], 0.0, places=2)

