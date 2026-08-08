"""El contrato de administración, redactado con la ley delante.

Lo que había eran seis frases —Objeto (2), Alcance operativo (2), Honorarios y
duración (2)— y un pie que ya avisaba de que aquello requería validación jurídica.
Para un contrato que se firma con una comunidad de propietarios se quedaba muy
corto, y le faltaba algo que no es opcional: **la cláusula de encargado de
tratamiento**. Al administrar se tratan datos personales de los propietarios por
cuenta de la comunidad, y el artículo 28 del RGPD exige que ese encargo conste por
escrito.

El texto se redactó consultando el BOE, no de memoria. De esa consulta salieron dos
correcciones a lo que yo mismo había dicho antes:

- El plazo de custodia documental es de **cinco años**, no de tres, y está en el
  **artículo 19.4** de la LPH, no en el 20.
- Los artículos del mandato se comprobaron sobre el PDF consolidado del Código Civil
  del propio BOE, no citados de oído.

Cada cláusula lleva el artículo del que sale, igual que se hizo con las mayorías de
junta: para poder comprobarla sin salir del documento, y para saber qué hay que
revisar cuando la ley cambie.

**Sigue siendo un borrador.** Estos tests comprueban que el documento dice lo que
dice la ley y que no se le ha quitado el aviso; no sustituyen a que lo lea un
abogado antes de firmarlo con nadie.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402


def plantilla(clave):
    return server.get_workspace_contract_templates()[clave]


def texto(clave):
    p = plantilla(clave)
    trozos = []
    for _titulo, lineas in p["sections"]:
        for l in lineas:
            trozos.append(l if isinstance(l, str) else " ".join(str(x) for x in l))
    return "\n".join(trozos + list(p.get("footer") or []))


class LoQueDiceLaLeyTests(unittest.TestCase):
    """Cada dato se comprobó contra el texto consolidado del BOE."""

    def test_el_nombramiento_es_por_un_ano_y_removible(self):
        """LPH art. 13.7: por un año salvo estatutos, y la Junta puede remover
        antes de que expire el mandato."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("plazo de un año", t)
        self.assertIn("artículo 13.7", t)
        self.assertIn("remover", t)

    def test_la_custodia_es_de_cinco_anos_y_del_articulo_19_4(self):
        """Yo había dicho tres años y artículo 20. Las dos cosas estaban mal: son
        cinco años y está en el 19.4."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("cinco años", t)
        self.assertIn("artículo 19.4", t)
        self.assertNotIn("tres años", t)

    def test_estan_las_seis_funciones_del_articulo_20(self):
        t = texto("fincas_contrato_comunidad")
        for inicio in ("a) Velar por el buen régimen", "b) Preparar", "c) Atender a la conservación",
                       "d) Ejecutar los acuerdos", "e) Actuar como Secretaría", "f) Las demás atribuciones"):
            with self.subTest(funcion=inicio[:2]):
                self.assertIn(inicio, t)

    def test_el_fondo_de_reserva_es_el_10_por_ciento(self):
        """LPH art. 9.1.f: nunca inferior al 10 % del último presupuesto ordinario."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("10 por ciento del último presupuesto ordinario", t)
        self.assertIn("artículo 9.1.f", t)

    def test_el_certificado_de_deuda_lo_firma_secretaria_con_visto_bueno(self):
        """LPH art. 21.3."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("acuerdo de liquidación", t)
        self.assertIn("visto bueno de la Presidencia", t)
        self.assertIn("artículo 21.3", t)

    def test_se_apoya_en_el_mandato_del_codigo_civil(self):
        """Comprobados sobre el PDF consolidado del BOE: 1709 (definición), 1719
        (instrucciones), 1720 (rendir cuentas), 1726 (dolo y culpa), 1732 y 1733
        (extinción y revocación)."""
        t = texto("fincas_contrato_comunidad")
        for articulo in ("1709", "1719", "1720", "1726", "1732", "1733"):
            with self.subTest(articulo=articulo):
                self.assertIn(articulo, t)

    def test_la_culpa_se_estima_con_mas_rigor_por_ser_retribuido(self):
        """Es lo que dice el 1726 y conviene que la Administración lo sepa."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("dolo", t)
        self.assertIn("más rigor", t)

    def test_los_fondos_no_se_confunden(self):
        """Cuenta a nombre de la comunidad: es donde más se pierden despachos."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("nombre de la Comunidad", t)
        self.assertIn("confundirá", t)

    def test_la_documentacion_es_de_la_comunidad_y_se_devuelve(self):
        t = texto("fincas_contrato_comunidad")
        self.assertIn("propiedad de la Comunidad", t)
        self.assertIn("plazo máximo de un mes desde el cese", t)


class LoQueNoPuedeFaltarTests(unittest.TestCase):
    def test_la_clausula_de_proteccion_de_datos_esta(self):
        """Era lo único que echaba de menos que no es opcional: art. 28 RGPD exige
        que el encargo conste por escrito."""
        t = texto("fincas_contrato_comunidad")
        self.assertIn("encargada del tratamiento", t)
        self.assertIn("artículo 28 del Reglamento (UE) 2016/679", t)

    def test_hay_anexo_de_encargo_de_tratamiento(self):
        self.assertIn("fincas_anexo_rgpd", server.get_workspace_contract_templates())

    def test_el_anexo_cubre_el_contenido_minimo_del_28_3(self):
        t = texto("fincas_anexo_rgpd")
        for exigencia in ("instrucciones documentadas", "confidencialidad", "artículo 32",
                          "No recurrir a otro encargado", "derechos", "violación de la seguridad",
                          "suprimir o devolver", "auditorías"):
            with self.subTest(exigencia=exigencia):
                self.assertIn(exigencia, t)

    def test_el_anexo_dice_qué_datos_se_tratan(self):
        t = texto("fincas_anexo_rgpd")
        self.assertIn("IBAN", t)
        self.assertIn("coeficiente", t)
        self.assertIn("categorías especiales", t)

    def test_el_anexo_recoge_como_funciona_el_portal(self):
        """Lo que se promete en la lista de servicios tiene que estar aquí."""
        t = texto("fincas_anexo_rgpd")
        self.assertIn("enlace personal", t)
        self.assertIn("ningún otro propietario", t)

    def test_la_colegiacion_y_el_seguro_constan(self):
        t = texto("fincas_contrato_comunidad")
        self.assertIn("colegiada", t)
        self.assertIn("responsabilidad civil profesional", t)


class SigueSiendoUnBorradorTests(unittest.TestCase):
    """No lo he redactado como abogado y el documento no puede fingir que sí."""

    def test_los_dos_avisan_de_que_son_borrador(self):
        for clave in ("fincas_contrato_comunidad", "fincas_anexo_rgpd"):
            with self.subTest(clave=clave):
                pie = " ".join(plantilla(clave)["footer"])
                self.assertIn("BORRADOR", pie)
                self.assertIn("revisado y validado por la asesoría jurídica", pie)

    def test_dicen_de_donde_sale_el_texto(self):
        pie = " ".join(plantilla("fincas_contrato_comunidad")["footer"])
        self.assertIn("Ley 49/1960", pie)
        self.assertIn("Código Civil", pie)

    def test_dejan_sitio_para_las_firmas(self):
        for clave in ("fincas_contrato_comunidad", "fincas_anexo_rgpd"):
            with self.subTest(clave=clave):
                self.assertIn("Firma comunidad", " ".join(plantilla(clave)["footer"]))


class SeGeneraDesdeLaPantallaTests(unittest.TestCase):
    def test_el_contrato_sale_al_aceptar(self):
        self.assertIn("data-fincas-budget-contract", APP)

    def test_el_anexo_rgpd_tiene_su_boton(self):
        self.assertIn("data-fincas-budget-rgpd", APP)
        self.assertIn('payload.template_key = "fincas_anexo_rgpd"', APP)

    def test_la_nota_de_encargo_ya_esta_en_la_lista_de_fincas(self):
        """Existía, pero solo se llegaba a ella desde el listado general."""
        i = APP.index("workspaceFincasBudgetsTable.innerHTML = `")
        self.assertIn("workspace_presupuesto_encargo_pdf", APP[i: i + 3200])

    def test_los_tres_solo_con_el_presupuesto_aceptado(self):
        """Generar el contrato de algo que aún no se ha aceptado no tiene sentido."""
        i = APP.index("workspaceFincasBudgetsTable.innerHTML = `")
        cuerpo = APP[i: i + 3200]
        for marca in ("data-fincas-budget-contract", "data-fincas-budget-rgpd", "workspace_presupuesto_encargo_pdf"):
            with self.subTest(marca=marca):
                j = cuerpo.index(marca)
                self.assertIn("isAccepted ?", cuerpo[max(0, j - 220): j])

    def test_el_anexo_queda_guardado_como_documento(self):
        """No un PDF suelto del que nadie sabe si se firmó."""
        i = APP.index("data-fincas-budget-rgpd]")
        self.assertIn('fetch("/api/workspace_contratos"', APP[i: i + 1400])


if __name__ == "__main__":
    unittest.main()


class LasPlantillasSeEditanSinDesplegarTests(unittest.TestCase):
    """Quien revisa estas cláusulas es la asesoría jurídica, no quien toca el
    código. Obligarle a pedir un despliegue para cambiar una coma garantiza que no
    se cambie nunca."""

    def conn(self):
        c = server.get_db(":memory:")
        server.ensure_workspace_product_tables(c)
        return c

    def test_ida_y_vuelta_sin_perder_nada(self):
        base = server.get_workspace_contract_templates()["fincas_contrato_comunidad"]
        texto = server.plantilla_contrato_a_texto(base)
        vuelta = server.parse_plantilla_contrato(texto)
        self.assertEqual([t for t, _ in vuelta], [t for t, _ in base["sections"]])
        self.assertEqual(sum(len(l) for _, l in vuelta), sum(len(l) for _, l in base["sections"]))

    def test_los_apartados_se_marcan_con_almohadillas(self):
        """JSON habría sido más cómodo de programar y peor de editar."""
        texto = server.plantilla_contrato_a_texto(
            server.get_workspace_contract_templates()["fincas_anexo_rgpd"])
        self.assertTrue(texto.startswith("## "))

    def test_lo_escrito_antes_del_primer_apartado_no_se_tira(self):
        """Tirarlo sería la forma más silenciosa de que alguien escriba una
        cláusula y no salga en el documento."""
        vuelta = server.parse_plantilla_contrato("Un párrafo suelto.\n## Primera\nOtro.")
        self.assertEqual(vuelta[0], ("", ["Un párrafo suelto."]))
        self.assertEqual(vuelta[1], ("Primera", ["Otro."]))

    def test_un_cuerpo_vacio_no_da_apartados(self):
        self.assertEqual(server.parse_plantilla_contrato(""), [])
        self.assertEqual(server.parse_plantilla_contrato("## Solo un título"), [])

    def test_se_siembran_desde_el_codigo(self):
        items = server.fetch_workspace_contrato_plantillas(self.conn(), "ws1")
        claves = [i["clave"] for i in items]
        self.assertIn("fincas_contrato_comunidad", claves)
        self.assertIn("fincas_anexo_rgpd", claves)

    def test_cada_workspace_tiene_las_suyas(self):
        c = self.conn()
        server.fetch_workspace_contrato_plantillas(c, "ws1")
        c.execute("UPDATE workspace_contrato_plantillas SET cuerpo = '## Mío\nTexto' WHERE workspace_id='ws1'")
        c.commit()
        otras = server.fetch_workspace_contrato_plantillas(c, "ws2")
        self.assertNotIn("Mío", otras[0]["cuerpo"])

    def test_la_editada_manda_sobre_la_del_codigo(self):
        c = self.conn()
        server.fetch_workspace_contrato_plantillas(c, "ws1")
        c.execute("UPDATE workspace_contrato_plantillas SET cuerpo = ? WHERE workspace_id='ws1' AND clave=?",
                  ("## Primera\nCláusula reescrita por el abogado.", "fincas_contrato_comunidad"))
        c.commit()
        tmpl = server.resolve_contract_template(c, "ws1", "fincas_contrato_comunidad")
        self.assertEqual(tmpl["sections"], [("Primera", ["Cláusula reescrita por el abogado."])])

    def test_si_la_vacian_se_cae_a_la_del_codigo(self):
        """Un contrato en blanco es peor que uno desactualizado."""
        c = self.conn()
        server.fetch_workspace_contrato_plantillas(c, "ws1")
        c.execute("UPDATE workspace_contrato_plantillas SET cuerpo = '' WHERE workspace_id='ws1' AND clave=?",
                  ("fincas_contrato_comunidad",))
        c.commit()
        tmpl = server.resolve_contract_template(c, "ws1", "fincas_contrato_comunidad")
        self.assertEqual(len(tmpl["sections"]), 12)

    def test_sin_tabla_migrada_tampoco_se_rompe(self):
        c = server.get_db(":memory:")
        tmpl = server.resolve_contract_template(c, "ws1", "fincas_contrato_comunidad")
        self.assertIsNotNone(tmpl)
        self.assertEqual(len(tmpl["sections"]), 12)

    def test_una_clave_desconocida_devuelve_nada(self):
        self.assertIsNone(server.resolve_contract_template(self.conn(), "ws1", "no_existe"))

    def test_el_pdf_usa_la_plantilla_resuelta(self):
        for llamada in ("tmpl=resolve_contract_template(",):
            self.assertEqual(SERVER.count(llamada), 2, "los dos caminos del PDF deben resolverla")

    def test_los_endpoints_comprueban_pertenencia(self):
        i = SERVER.index('if path == "/api/workspace_contrato_plantillas"')
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id)", SERVER[i: i + 1200])
        j = SERVER.index('elif parsed.path == "/api/workspace_contrato_plantillas"')
        cuerpo = SERVER[j: SERVER.index("\n        elif parsed.path ==", j + 10)]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_esta_en_la_lista_de_rutas_permitidas(self):
        self.assertIn('"/api/workspace_contrato_plantillas",', SERVER)

    def test_no_deja_guardar_un_cuerpo_sin_apartados(self):
        j = SERVER.index('elif parsed.path == "/api/workspace_contrato_plantillas"')
        cuerpo = SERVER[j: SERVER.index("\n        elif parsed.path ==", j + 10)]
        self.assertIn("El cuerpo está vacío o no tiene ningún apartado", cuerpo)

    def test_se_puede_volver_al_texto_de_origen(self):
        j = SERVER.index('elif parsed.path == "/api/workspace_contrato_plantillas"')
        cuerpo = SERVER[j: SERVER.index("\n        elif parsed.path ==", j + 10)]
        self.assertIn('payload.get("restaurar")', cuerpo)
        self.assertIn("plantilla_contrato_a_texto(base)", cuerpo)

    def test_la_pantalla_existe_y_explica_el_formato(self):
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="workspaceContratoPlantillasPanel"', html)
        self.assertIn("Los apartados se marcan con", html)
        self.assertIn("cada uno guarda el texto con el que se creó", html)

    def test_restaurar_pide_confirmacion(self):
        self.assertIn("Se perderán los cambios de esta plantilla", APP)
