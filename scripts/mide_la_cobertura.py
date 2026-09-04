#!/usr/bin/env python3
"""Mide qué parte del servidor ejecuta la suite, y avisa si ha bajado del suelo.

Por qué
-------
La herramienta llevaba configurada en `pyproject.toml` desde siempre y **nunca se había
ejecutado**: no había ni un `.coverage`. Teníamos 3.000 pruebas sobre 117.000 líneas y
nadie sabía qué fracción se tocaba, así que «está bien probado» era una impresión.

La primera medición, el 2026-08-24 sobre `main`, dio **45,05 %**. Y el reparto importa
más que el número: los módulos pequeños que alguien decidió proteger están al 90 %
—autenticación 97 %, enlaces públicos 92 %— y `server.py`, que es el 95 % del código,
al 43,7 %. Más de la mitad del servidor no la ejecuta ninguna prueba.

Lo que la cobertura NO dice
---------------------------
Que lo cubierto esté bien. Los fallos que encontró la campaña de agosto —la derrama que
se comía la cuota, el punteo que salía verde, el cierre que se apuntaba dos comisiones—
estaban todos en código **cubierto**: se ejecutaba en las pruebas y hacía lo que no
debía. Esto dice qué no has mirado nunca; no dice que lo mirado esté bien.

Y mide sólo Python. Los 95.000 líneas de `app.js` van por otro lado.

Uso
---
    python scripts/mide_la_cobertura.py           # la suite entera, ~17 min
    python scripts/mide_la_cobertura.py tests/test_una_cosa.py

Sale con código 1 si la cobertura queda por debajo del `fail_under` de
`pyproject.toml`. Ese suelo no es una nota: si baja, es que ha entrado código que nadie
ejecuta.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def suelo():
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    for linea in texto.splitlines():
        if linea.strip().startswith("fail_under"):
            try:
                return float(linea.split("=", 1)[1].strip())
            except Exception:
                break
    return None


def main():
    objetivo = sys.argv[1:] or ["tests"]
    with tempfile.TemporaryDirectory() as tmp:
        informe = Path(tmp) / "cobertura.json"
        orden = [sys.executable, "-m", "pytest", *objetivo, "-q",
                 "--cov", f"--cov-report=json:{informe}", "--cov-report=term:skip-covered"]
        print(f"  {' '.join(objetivo)} · esto tarda lo que tarde la suite\n", flush=True)
        r = subprocess.run(orden, cwd=str(RAIZ))
        if not informe.exists():
            print("\n  No se generó el informe. ¿Está instalado pytest-cov?\n"
                  "  Está en requirements-dev.txt:  pip install pytest-cov", file=sys.stderr)
            return r.returncode or 1
        datos = json.loads(informe.read_text(encoding="utf-8"))

    total = datos["totals"]
    pct = float(total["percent_covered"])
    print(f"\n{'=' * 66}")
    print(f"  Cobertura del servidor: {pct:.2f} %  "
          f"({total['covered_lines']:,} de {total['num_statements']:,} sentencias)")
    print(f"  Sin ejecutar nunca: {total['missing_lines']:,} líneas")

    filas = sorted(datos["files"].items(), key=lambda kv: -kv[1]["summary"]["num_statements"])
    print(f"\n  {'fichero':34}{'sentencias':>11}{'cubierto':>11}")
    for fichero, valores in filas[:12]:
        s = valores["summary"]
        print(f"  {fichero:34}{s['num_statements']:>11,}{s['percent_covered']:>10.1f} %")

    minimo = suelo()
    if minimo is None:
        print("\n  (sin suelo configurado en pyproject.toml)")
        return r.returncode
    # El porcentaje se calcula siempre sobre TODO el código, así que medir un puñado de
    # pruebas da un número bajísimo que no significa nada. Compararlo con el suelo sólo
    # tiene sentido con la suite entera.
    if objetivo != ["tests"]:
        print(f"\n  Medición parcial: sólo {' '.join(objetivo)}.")
        print(f"  El porcentaje sale sobre todo el código igualmente, así que NO se")
        print(f"  compara con el suelo ({minimo} %). Para eso, sin argumentos.\n")
        return r.returncode
    if pct < minimo:
        print(f"\n  POR DEBAJO DEL SUELO: {pct:.2f} % < {minimo} %.")
        print("  Ha entrado código que no ejecuta ninguna prueba. O se cubre, o se")
        print("  justifica bajar el suelo — pero no en silencio.\n")
        return 1
    print(f"\n  Por encima del suelo ({minimo} %). "
          f"{'Margen de %.2f puntos.' % (pct - minimo) if pct > minimo else ''}\n")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
