"""Un lead del portal cae en la agencia de su anuncio, no en la de al lado.

El CRM inmobiliario está conectado con **Verifika2**, un portal externo que publica
los anuncios de varias agencias. La conexión tiene dos sentidos:

*   hacia fuera, `/api/portal_inmuebles`, `/api/portal_inmueble` y el feed XML
    `/api/inmueble_portal_feed`, que sólo sacan lo que tiene `portal_publicado = 1`,
    una captación con `noticia_verificada = 1` y no está vendido ni alquilado. No
    exponen al propietario: ni nombre, ni NIF, ni teléfono;
*   hacia dentro, `/api/portal_lead`, que exige un bearer token (Lead Hub → CRM) y
    da de alta al interesado como cliente, vinculándolo al inmueble.

El fallo estaba en el segundo. El workspace del lead se resolvía así:

    payload → listing → inmueble.workspace_id → empresa (si sólo cuelga de uno)
            → PORTAL_LEADS_WORKSPACE_ID → "6e63e1d1..."  ← Modernia, a pelo

y los dos últimos escalones son los que se usaban de verdad, porque 81 de los 86
inmuebles son anteriores al campo `workspace_id` y **todas** las empresas cuelgan de
dos workspaces (el suyo y el de plataforma, que las agrupa a todas).

Hoy acertaba por casualidad: lo único publicado —4 anuncios— es de «Estudio Velazquez
2012 SL», que es de Modernia. El día que publique ANSA, que es de Modernia Centro, su
lead se archivaría en el CRM de otra agencia. Un contacto que no es tuyo apareciendo
en tu cartera, y sin que nadie lo note.

Dos cambios:

1. El ámbito se deduce del anuncio y ya no se acepta del cuerpo. El portal es un
   integrante de confianza —tiene token—, pero de qué agencia es un dato no es cosa
   suya, y así un token filtrado tampoco sirve para sembrar contactos donde se quiera.
2. Al deducir por empresa se descarta el workspace de plataforma, que es el que hacía
   ambigua toda deducción. Sin él, cada empresa de producción se queda con
   exactamente uno. Y si aun así no se puede saber, el portal recibe un error y
   reintenta: perder un lead se ve; archivarlo en la agencia equivocada, no.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ.pop("PORTAL_LEADS_WORKSPACE_ID", None)

from web import server as S  # noqa: E402

NOW = "2026-08-09 10:00:00"


class LeadsDelPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "portal.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self._seed()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _cols(self, tabla):
        return [r[1] for r in self.conn.execute(f"pragma table_info({tabla})")]

    def _insert(self, tabla, datos):
        validas = set(self._cols(tabla))
        d = {k: v for k, v in datos.items() if k in validas}
        hueco = ",".join("?" * len(d))
        self.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({hueco})", tuple(d.values()))
        self.conn.commit()

    def _seed(self):
        # `ensure_tables` ya siembra el workspace de plataforma.
        self.ws_plataforma = self.conn.execute(
            "SELECT id FROM workspaces WHERE nombre = 'Verifika²' LIMIT 1"
        ).fetchone()["id"]
        self._insert("empresas", {"id": "empPlat", "nombre": "Verifika2", "activo": 1,
                                  "created_at": NOW, "updated_at": NOW})
        self._insert("workspace_empresas", {"id": "wep", "workspace_id": self.ws_plataforma,
                                            "empresa_id": "empPlat", "created_at": NOW,
                                            "updated_at": NOW})
        # Dos agencias en workspaces distintos, como Estudio Velazquez y ANSA.
        for eid, nombre, ws, ws_nombre in (
            ("empVel", "Estudio Velazquez 2012 SL", "wsMod", "Modernia"),
            ("empAnsa", "ANSA INMOASESORES.SL", "wsCentro", "Modernia Centro"),
        ):
            self._insert("empresas", {"id": eid, "nombre": nombre, "activo": 1,
                                      "created_at": NOW, "updated_at": NOW})
            self._insert("workspaces", {"id": ws, "nombre": ws_nombre, "slug": ws.lower(),
                                        "estado": "Activo", "plan": "Enterprise",
                                        "created_at": NOW, "updated_at": NOW})
            self._insert("workspace_empresas", {"id": f"we{eid}", "workspace_id": ws,
                                                "empresa_id": eid, "created_at": NOW,
                                                "updated_at": NOW})
            self._insert("workspace_empresas", {"id": f"wep{eid}",
                                                "workspace_id": self.ws_plataforma,
                                                "empresa_id": eid, "created_at": NOW,
                                                "updated_at": NOW})
        # Anuncios publicados, sin workspace en la ficha: la forma de 81 de los 86.
        for iid, eid, direccion in (("inmVel", "empVel", "Local Puerto Oncala"),
                                    ("inmAnsa", "empAnsa", "Piso de ANSA")):
            self._insert("inmuebles", {"id": iid, "empresa_id": eid, "direccion": direccion,
                                       "estado": "Encargo", "tipo_inmueble": "Local",
                                       "poblacion": "Málaga", "precio_objetivo": 145000,
                                       "portal_publicado": 1, "created_at": NOW,
                                       "updated_at": NOW})
            self._insert("captaciones", {"id": f"cap{iid}", "empresa_id": eid,
                                         "inmueble_id": iid, "direccion": direccion,
                                         "noticia_verificada": 1, "created_at": NOW,
                                         "updated_at": NOW})

    def _lead(self, listing_id, nombre, **extra):
        resultado, estado = S.create_portal_inmueble_lead(
            self.conn, {"listing_id": listing_id, "nombre": nombre,
                        "telefono": "600111222", **extra}, NOW)
        self.conn.commit()
        return resultado, estado

    def _workspace_del_cliente(self, nombre):
        fila = self.conn.execute(
            "SELECT workspace_id FROM clientes WHERE nombre = ? LIMIT 1", (nombre,)
        ).fetchone()
        return str(fila["workspace_id"] or "").strip() if fila else None

    # ---------- el destino ----------

    def test_cada_lead_va_a_la_agencia_de_su_anuncio(self):
        for listing, nombre, esperado in (
            ("inmVel", "Interesado en Velazquez", "wsMod"),
            ("inmAnsa", "Interesado en ANSA", "wsCentro"),
        ):
            with self.subTest(listing):
                _r, estado = self._lead(listing, nombre)
                self.assertEqual(estado, 200)
                self.assertEqual(self._workspace_del_cliente(nombre), esperado)

    def test_el_workspace_de_la_ficha_manda_si_lo_tiene(self):
        self.conn.execute("UPDATE inmuebles SET workspace_id = 'wsCentro' WHERE id = 'inmVel'")
        self.conn.commit()
        self._lead("inmVel", "Interesado Explicito")
        self.assertEqual(self._workspace_del_cliente("Interesado Explicito"), "wsCentro")

    def test_el_portal_no_elige_el_workspace(self):
        """Tiene token, pero de qué agencia es el lead no es cosa suya."""
        self._lead("inmAnsa", "Colado", workspace_id="wsMod")
        self.assertEqual(self._workspace_del_cliente("Colado"), "wsCentro")

    def test_tampoco_por_el_listing_del_cuerpo(self):
        self._lead("inmAnsa", "Colado Dos", listing={"id": "inmAnsa", "workspace_id": "wsMod"})
        self.assertEqual(self._workspace_del_cliente("Colado Dos"), "wsCentro")

    def test_si_no_se_puede_saber_se_avisa_en_vez_de_elegir(self):
        # Una empresa en dos workspaces reales: ni la ficha ni la empresa deciden.
        self._insert("workspace_empresas", {"id": "extra", "workspace_id": "wsCentro",
                                            "empresa_id": "empVel", "created_at": NOW,
                                            "updated_at": NOW})
        resultado, estado = self._lead("inmVel", "Nadie Sabe")
        self.assertEqual(estado, 409, resultado)
        self.assertIsNone(self._workspace_del_cliente("Nadie Sabe"))

    # ---------- el resolutor ----------

    def test_descarta_el_workspace_de_plataforma(self):
        self.assertEqual(S.workspaces_propios_de_empresa(self.conn, "empVel"), ["wsMod"])
        self.assertEqual(S.workspaces_propios_de_empresa(self.conn, "empAnsa"), ["wsCentro"])

    def test_la_propia_empresa_de_plataforma_conserva_el_suyo(self):
        self.assertEqual(
            S.workspaces_propios_de_empresa(self.conn, "empPlat"), [self.ws_plataforma])

    # ---------- lo que el portal enseña ----------

    def test_el_anuncio_publico_no_lleva_datos_del_propietario(self):
        self._insert("clientes", {"id": "cliProp", "empresa_id": "empVel",
                                  "workspace_id": "wsMod", "nombre": "Propietario Privado",
                                  "nif": "99999999R", "telefono": "600000000",
                                  "email": "privado@x.test", "created_at": NOW,
                                  "updated_at": NOW})
        self._insert("inmueble_propietarios", {"id": "ipVel", "inmueble_id": "inmVel",
                                               "cliente_id": "cliProp", "empresa_id": "empVel",
                                               "created_at": NOW, "updated_at": NOW})
        filas = S.fetch_portal_inmuebles_public(self.conn, listing_id="inmVel", limit=1)
        self.assertEqual(len(filas), 1)
        texto = repr(filas[0])
        for pista in ("Propietario Privado", "99999999R", "600000000", "privado@x.test"):
            self.assertNotIn(pista, texto, f"el anuncio público filtra «{pista}»")

    def test_no_se_publica_lo_que_no_esta_verificado(self):
        self.conn.execute("UPDATE captaciones SET noticia_verificada = 0 WHERE inmueble_id = 'inmVel'")
        self.conn.commit()
        self.assertEqual(S.fetch_portal_inmuebles_public(self.conn, listing_id="inmVel", limit=1), [])

    def test_no_se_publica_lo_ya_vendido(self):
        self.conn.execute("UPDATE inmuebles SET estado = 'Vendido' WHERE id = 'inmVel'")
        self.conn.commit()
        self.assertEqual(S.fetch_portal_inmuebles_public(self.conn, listing_id="inmVel", limit=1), [])

    def test_un_lead_sobre_algo_no_publicado_no_entra(self):
        self.conn.execute("UPDATE inmuebles SET portal_publicado = 0 WHERE id = 'inmVel'")
        self.conn.commit()
        _r, estado = self._lead("inmVel", "Interesado Fantasma")
        self.assertEqual(estado, 404)


if __name__ == "__main__":
    unittest.main()
