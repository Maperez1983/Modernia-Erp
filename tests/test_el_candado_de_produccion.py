"""Levantar el CRM en un portátil abría un CRM conectado a la base real.

`web/db_backend.py` lee el `.env` de la raíz nada más importarse, y ahí está el
`DATABASE_URL` de producción. Así que arrancar el servidor en local abría, sin decir
nada, un CRM escribiendo en los datos de verdad: misma pantalla, mismos botones.
`/api/build_info` lo confirmaba con `backend: postgres` y el host de Render.

Pasar `--db ruta.sqlite` no servía de nada: el backend ya estaba decidido por el entorno.

Ahora hay un candado, y lo importante es dónde NO se activa:

  · **En la nube arranca igual.** Ahí conectarse a producción es lo correcto, y se
    reconoce por `RENDER`, que es la variable que el resto del código ya usa para eso.
  · **Con SQLite ni se entera**, que es el caso normal en local.
  · **Con `--permitir-produccion` arranca**, porque puede haber quien quiera mirar datos
    reales a propósito. Lo que no puede es pasar sin querer.

El mensaje dice el host y la base para que se vea de un vistazo dónde iba a entrar, y
**no imprime usuario ni contraseña**: eso acaba en una terminal y en un registro.
"""

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


def arranca(entorno_extra, argumentos=()):
    """Llama a `main()` con el arranque real sustituido: sólo interesa el candado."""
    guion = (
        "import sys, os\n"
        f"sys.argv = ['server'] + {list(argumentos)!r}\n"
        f"sys.path.insert(0, {str(RAIZ)!r})\n"
        "from web import server as S\n"
        "S.ThreadingHTTPServer = type('X', (), {"
        "'__init__': lambda s, *a, **k: None,"
        "'serve_forever': lambda s: print('ARRANCA'),"
        "'socket': None})\n"
        "try:\n"
        "    S.main()\n"
        "except SystemExit as e:\n"
        "    print('BLOQUEADO', e.code)\n"
        "except Exception as e:\n"
        "    print('PASA-EL-CANDADO', type(e).__name__)\n"
    )
    # Entorno mínimo y construido a mano, no copiado del de pytest: otras pruebas de la
    # suite dejan puesto APP_DB_BACKEND o POSTGRES_URL y el candado dejaba de saltar.
    # Aislada pasaba y en la suite fallaba, que es la peor forma de fallar.
    entorno = {clave: os.environ[clave] for clave in ("PATH", "HOME", "LANG", "LC_ALL",
                                                      "TMPDIR", "SYSTEMROOT")
               if clave in os.environ}
    entorno.setdefault("DATABASE_URL", "")
    entorno.setdefault("POSTGRES_URL", "")
    entorno.update(entorno_extra)
    # Con `env=` de verdad: sin esto el hijo hereda el .env real y la prueba pasa por
    # el motivo equivocado —bloquea, sí, pero contra producción en vez de contra el DSN
    # de mentira—.
    r = subprocess.run([sys.executable, "-c", guion], capture_output=True, text=True,
                       cwd=str(RAIZ), timeout=180, env=entorno)
    return (r.stdout or "") + (r.stderr or "")


FALSO_DSN = "postgresql://u:p@baseinventada.example.com:5432/moderniafalsa"


class ElCandadoDeProduccionTests(unittest.TestCase):
    def test_en_un_portatil_contra_produccion_se_para(self):
        salida = arranca({"DATABASE_URL": FALSO_DSN})
        self.assertIn("BLOQUEADO 2", salida)
        self.assertNotIn("ARRANCA", salida)

    def test_y_dice_a_dónde_iba_a_entrar(self):
        salida = arranca({"DATABASE_URL": FALSO_DSN})
        self.assertIn("PRODUCCIÓN", salida)
        self.assertIn("baseinventada.example.com", salida)
        self.assertIn("moderniafalsa", salida)

    def test_sin_enseñar_la_contraseña(self):
        """El mensaje va a una terminal y a un registro."""
        salida = arranca({"DATABASE_URL": FALSO_DSN})
        self.assertNotIn("u:p@", salida)
        self.assertNotIn(":p@", salida)

    def test_y_dice_las_dos_salidas(self):
        salida = arranca({"DATABASE_URL": FALSO_DSN})
        self.assertIn("--permitir-produccion", salida)
        self.assertIn("DATABASE_URL", salida)

    # --- dónde NO se activa ---------------------------------------------------------

    def test_en_la_nube_arranca_igual(self):
        """Ahí conectarse a producción es lo correcto."""
        salida = arranca({"DATABASE_URL": FALSO_DSN, "RENDER": "1"})
        self.assertIn("ARRANCA", salida)
        self.assertNotIn("BLOQUEADO", salida)

    def test_con_permiso_explicito_arranca(self):
        salida = arranca({"DATABASE_URL": FALSO_DSN}, ["--permitir-produccion"])
        self.assertIn("ARRANCA", salida)
        self.assertNotIn("BLOQUEADO", salida)

    def test_con_sqlite_ni_se_entera(self):
        """Es el caso normal en local: no puede estorbar."""
        salida = arranca({"DATABASE_URL": "", "POSTGRES_URL": ""})
        self.assertIn("ARRANCA", salida)
        self.assertNotIn("BLOQUEADO", salida)

    # --- un Postgres en el propio equipo no es producción ------------------------------

    def test_un_postgres_local_arranca_sin_pedir_permiso(self):
        """Antes lo bloqueaba, y la salida era --permitir-produccion.

        Eso convertía en costumbre la bandera que sí abre la base real. Un Postgres en
        127.0.0.1 es justo lo que hace falta para probar lo que SQLite esconde.
        """
        for sitio in ("127.0.0.1", "localhost", "[::1]"):
            salida = arranca({"DATABASE_URL": f"postgresql://postgres@{sitio}:55432/crm_pruebas"})
            self.assertIn("ARRANCA", salida, sitio)
            self.assertNotIn("BLOQUEADO", salida, sitio)

    def test_pero_lo_dice_por_si_creías_estar_en_sqlite(self):
        salida = arranca({"DATABASE_URL": "postgresql://postgres@127.0.0.1:55432/crm_pruebas"})
        self.assertIn("Postgres local", salida)
        self.assertIn("crm_pruebas", salida)

    def test_y_un_host_que_sólo_empieza_parecido_no_cuela(self):
        """«localhost.atacante.com» no es local."""
        salida = arranca({"DATABASE_URL": "postgresql://u:p@localhost.example.com/x"})
        self.assertIn("BLOQUEADO 2", salida)
        self.assertNotIn("ARRANCA", salida)

    # --- y que siga siendo lo que dice ser -------------------------------------------

    def test_la_opcion_existe_y_está_explicada(self):
        self.assertIn('"--permitir-produccion"', SERVER)
        m = re.search(r'--permitir-produccion".*?help="([^"]+)"', SERVER, re.S)
        self.assertIsNotNone(m)
        self.assertIn("producción", m.group(1))

    def test_el_candado_mira_las_tres_cosas(self):
        """La base, el entorno y el permiso: quitar cualquiera lo deja inútil."""
        i = SERVER.index("ALTO: esto va a conectarse a la base de PRODUCCIÓN")
        condicion = SERVER[max(0, i - 700):i]
        for pieza in ("db_is_postgres_enabled()", 'os.environ.get("RENDER")',
                      "args.permitir_produccion"):
            self.assertIn(pieza, condicion, pieza)

    def test_el_servidor_sigue_siendo_python_válido(self):
        ast.parse(SERVER)


if __name__ == "__main__":
    unittest.main()
