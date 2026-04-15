import random
import unittest

from web.server import compute_hipoteca_liquidacion_print_data


def r2(value):
    return round(float(value), 2)


class FinLiquidacionFuzzTests(unittest.TestCase):
    def build_operation(self, rng: random.Random, idx: int):
        precio = r2(rng.uniform(70000, 260000))
        # Hipoteca entre 0% y 90% (evitar 0 exacto para la mayoría).
        pct = rng.uniform(0.2, 0.9)
        importe_hipoteca = r2(precio * pct)

        # Gastos compraventa (ITP aprox 3.5% - 7%).
        itp_rate = rng.choice([0.035, 0.04, 0.06, 0.07])
        gastos_cv = {
            "notaria": r2(rng.uniform(900, 1600)),
            "registro": r2(rng.uniform(250, 550)),
            "itp": r2(precio * itp_rate),
            "gestoria": r2(rng.uniform(200, 450)),
        }

        # Hipoteca: gastos + seguros.
        hip_notaria = r2(rng.uniform(0, 350))
        hip_apertura = r2(rng.choice([0, 0, 0, rng.uniform(150, 450)]))
        hip_cuota_socio = r2(rng.choice([0, 0, 150, 75]))
        hip_com_cheques = r2(rng.choice([0, 150, 200, 250]))

        seg_prot = r2(rng.choice([0, rng.uniform(300, 1100)]))
        seg_hogar = r2(rng.choice([0, rng.uniform(200, 650)]))
        seg_vida = r2(rng.choice([0, rng.uniform(200, 900)]))

        prot_fin = rng.choice(["Sí", "No"])
        hogar_fin = rng.choice(["Sí", "No"])
        vida_fin = rng.choice(["Sí", "No"])

        # Gestión: la transferencia a Modernia debe igualar (inmo + financiación) para que cuadre.
        gest_inmo = r2(rng.choice([0, 0, rng.uniform(0, 1200)]))
        gest_fin = r2(rng.choice([0, 1500, 2000, 2500, 3000]))
        transf_modernia = r2(gest_inmo + gest_fin)

        # Señal: parte de la entrada (10%-60% del precio), pero permitir casos donde no haga falta ingresar más.
        senal = r2(rng.uniform(precio * 0.1, precio * 0.6))

        # Ingresar banco: a veces vacío (auto), a veces manual (incluye 0).
        manual_ingresar = rng.choice([True, False])
        ingresar_banco = None
        if manual_ingresar:
            # Puede ser 0 o cualquier valor positivo; lo importante es que cuadre.
            ingresar_banco = r2(rng.choice([0, rng.uniform(0, max(precio * 0.35, 1))]))

        comprador = {
            "precio_compra": precio,
            "escriturado": precio,
            "gastos_compraventa": gastos_cv,
            "hipoteca": {
                "capital": importe_hipoteca,
                "notaria_impuestos_gestoria": hip_notaria,
                "comision_apertura": hip_apertura,
                "cuota_socio": hip_cuota_socio,
                "comision_cheques": hip_com_cheques,
                "seguro_proteccion_pago": seg_prot,
                "seguro_hogar": seg_hogar,
                "seguro_vida": seg_vida,
                "seguro_proteccion_financiado": prot_fin,
                "seguro_hogar_financiado": hogar_fin,
                "seguro_vida_financiado": vida_fin,
            },
            "gestion_inmobiliaria": gest_inmo,
            "gestion_financiacion": gest_fin,
            "entregas": {
                "senal": senal,
                "transf_modernia": transf_modernia,
                "prestamo_concedido": importe_hipoteca,
            },
        }
        if ingresar_banco is not None:
            comprador["entregas"]["ingresar_banco"] = ingresar_banco

        # Vendedor: deducciones que NO rompan el total.
        # Para medios de pago, evitamos plusvalía en este modelo (en Excel no entra en "medios de pago").
        canc_eco = r2(rng.choice([0, 0, rng.uniform(0, precio * 0.2)]))
        canc_reg = r2(rng.choice([0, rng.uniform(0, 1800)]))
        ibi = r2(rng.choice([0, rng.uniform(0, 1800)]))
        ret = r2(rng.choice([0, rng.uniform(0, precio * 0.03)]))
        gest_nr = r2(rng.choice([0, rng.uniform(0, 450)]))

        vendedor = {
            "precio_vivienda": precio,
            "deducciones": {
                "senal": senal,
                "cancelacion_economica": canc_eco,
                "cancelacion_registral": canc_reg,
                "deuda_ibi": ibi,
                "plusvalia": 0.0,
                "retencion_no_residente": ret,
                "gestion_no_residente": gest_nr,
            },
            "vendedores": {
                "v1": {"nombre": f"VENDEDOR {idx+1}", "nif": "00000000X"},
                "v2": {"nombre": "", "nif": ""},
            },
        }

        export_row = {"precio": precio, "importe_hipoteca": importe_hipoteca}
        liquidacion = {"comprador": comprador, "vendedor": vendedor, "cuadre": {}, "notaria": {}, "prestamo": {}}
        return export_row, liquidacion

    def test_1000_operaciones_cuadran(self):
        rng = random.Random(20260415)
        for idx in range(1000):
            export_row, liquidacion = self.build_operation(rng, idx)
            out = compute_hipoteca_liquidacion_print_data(export_row, liquidacion)
            liq = out["liq"]
            flags = out["flags"]

            comprador = liq["comprador"]
            cuadre = liq["cuadre"]

            # Invariantes clave (lo que usamos como “revisión Excel”).
            self.assertTrue(flags["cuadre_sobrante_ok"], msg=f"Operación {idx}: sobrante no cuadra")
            self.assertAlmostEqual(flags["cuadre_sobrante_delta"], 0.0, places=2)

            # Medios de pago deben cuadrar con escriturado (cuando plusvalía=0).
            self.assertAlmostEqual(cuadre["diferencia_medios_pago"], 0.0, places=2, msg=f"Operación {idx}: medios pago")

            # Sobrantes deben coincidir.
            self.assertAlmostEqual(cuadre["sobran_en_cuenta"], comprador["sobran_en_cuenta"], places=2)
