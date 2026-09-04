#!/usr/bin/env python3
"""Pasa PDFs de póliza por el lector, de uno en uno, y dice qué haría con cada uno.

Por qué de uno en uno
---------------------
Es la forma de comprobar que el lector funciona antes de soltarlo sobre 120 ficheros:
qué número de póliza saca, a qué cliente la asigna, si la póliza ya existe y si crearía
un duplicado. Un importador que se equivoca en masa deja un desastre que hay que
deshacer a mano —hoy ya nos ha pasado— y de uno en uno se ve venir.

Qué NO hace
-----------
**No escribe nada.** Lee el PDF, resuelve el cliente y compara con lo que hay, pero no
crea ni la póliza ni la ficha. Sólo informa. Para eso está `--aplicar`, que todavía no
existe a propósito: primero se mira si lee bien.

Y **nada sale del equipo**: fuerza `APP_SEGUROS_OCR_EXTERNAL=0`, así que el documento no
se manda ni a OpenAI ni a Google DocAI. Sólo `pdftotext`/`tesseract`, en local.

Uso
---
    CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_ocr \\
        python scripts/prueba_lector_de_polizas.py carpeta_con_pdfs/

    ... un_pdf.pdf otro.pdf        # o ficheros sueltos

Qué mirar en la salida
----------------------
  · **número de póliza**: si no lo saca, esa póliza seguirá sin número
  · **tomador**: que sea una persona y no la calle del piso asegurado
  · **cliente**: si lo encuentra, si lo crearía, o si hay varias fichas candidatas
  · **¿existe ya?**: si el número casa con una póliza que ya está, hay que enganchar el
    PDF, no crear otra
"""

import argparse
import base64
import os
import sys
import unicodedata
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def clave(v):
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return " ".join(sorted(re.sub(r"[^a-z0-9 ]", " ", t.lower()).split()))


def limpia_numero(v):
    return re.sub(r"[.\-\s]", "", str(v or ""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("rutas", nargs="+", help="PDFs o carpetas con PDFs")
    ap.add_argument("--empresa", default="", help="empresa_id a la que atribuir la póliza")
    args = ap.parse_args(argv)

    dsn = (os.environ.get("CRM_POSTGRES_PRUEBAS") or "").strip()
    if not dsn:
        print("\n  Falta CRM_POSTGRES_PRUEBAS. Esto no se prueba contra producción.\n")
        return 2
    import urllib.parse
    if (urllib.parse.urlparse(dsn).hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
        print("  CRM_POSTGRES_PRUEBAS no es local. No.")
        return 2
    os.environ["DATABASE_URL"] = dsn
    os.environ["APP_DB_BACKEND"] = "postgres"
    # Que el documento no salga del equipo.
    os.environ["APP_SEGUROS_OCR_EXTERNAL"] = "0"

    from web import server as S

    S.Handler.db_path = ":lector:"
    conn = S.get_db(S.Handler.db_path)

    pdfs = []
    for r in args.rutas:
        p = Path(r)
        pdfs.extend(sorted(p.glob("*.pdf")) + sorted(p.glob("*.PDF")) if p.is_dir() else [p])
    if not pdfs:
        print("  No hay PDFs en lo que has pasado.")
        return 1

    # Lo que ya hay, para comparar.
    clientes = [(x["id"], x["nombre"], clave(x["nombre"])) for x in
                conn.execute("SELECT id, nombre FROM clientes").fetchall()]
    polizas = {}
    for x in conn.execute("SELECT id, COALESCE(poliza_numero,'') AS n, cliente_id FROM seguros").fetchall():
        n = limpia_numero(S.row_value(x, "n"))
        if n:
            polizas.setdefault(n, []).append(x)

    print(f"\n  {len(pdfs)} PDF · {len(clientes)} clientes y {len(polizas)} pólizas numeradas en la base")
    print(f"  envío a terceros: DESACTIVADO · lectura con pdftotext/tesseract en local\n")

    resumen = {"leidos": 0, "sin_numero": 0, "ya_existe": 0, "cliente_ok": 0,
               "cliente_nuevo": 0, "cliente_ambiguo": 0, "error": 0}
    for pdf in pdfs:
        print(f"  {'─' * 72}\n  {pdf.name}")
        try:
            datos = base64.b64encode(pdf.read_bytes()).decode()
            r = S.process_seguros_ocr(
                {"file_base64": datos, "filename": pdf.name,
                 "empresa_id": args.empresa, "allow_external": False}, conn)
        except Exception as exc:
            resumen["error"] += 1
            print(f"      NO SE PUDO LEER: {type(exc).__name__}: {str(exc).splitlines()[0][:70]}")
            continue
        resumen["leidos"] += 1
        f = r.get("fields") or {}
        num = limpia_numero(f.get("poliza_numero"))
        q = r.get("ocr_quality") or {}
        faltan = q.get("missing_required") or []
        malos = q.get("required_invalid") or []
        print(f"      leído con {r.get('method')} · confianza {q.get('confidence', 0):.2f}"
              f" · calidad {q.get('calidad', '—')}"
              + (f" · FALTAN {faltan}" if faltan else "")
              + (f" · INVÁLIDOS {malos}" if malos else ""))
        print(f"      compañía  {f.get('compania') or '—'!r}")
        print(f"      póliza    {f.get('poliza_numero') or '— NO LA SACA'!r}")
        print(f"      tomador   {f.get('tomador') or '—'!r}")
        print(f"      efecto    {f.get('fecha_efecto') or '—'!r}")
        if not num:
            resumen["sin_numero"] += 1

        # ¿Esta póliza ya está?
        if num and num in polizas:
            resumen["ya_existe"] += 1
            print(f"      ¿existe?  SÍ — {len(polizas[num])} en la base con ese número: "
                  f"engancharía el PDF, no crearía otra")
        elif num:
            print(f"      ¿existe?  no: sería una póliza nueva")

        # ¿A quién se la asigna?
        cid = r.get("cliente_id")
        if cid:
            nombre = next((n for i, n, _ in clientes if i == cid), "(?)")
            resumen["cliente_ok"] += 1
            print(f"      cliente   encontrado → {nombre!r}")
        else:
            tom = f.get("tomador") or ""
            k = clave(tom)
            # Con el tomador vacío o de una sola palabra, la contención casa con TODO:
            # el conjunto vacío es subconjunto de cualquiera. Medido: 2.188 «candidatas».
            palabras = set(k.split())
            cands = ([n for _, n, q in clientes
                      if len(palabras) >= 2 and (palabras == set(q.split())
                                                 or palabras <= set(q.split()))]
                     if len(palabras) >= 2 else [])
            if len(cands) == 1:
                resumen["cliente_ok"] += 1
                print(f"      cliente   por nombre → {cands[0]!r}")
            elif cands:
                resumen["cliente_ambiguo"] += 1
                print(f"      cliente   AMBIGUO: {len(cands)} fichas se parecen → {cands[:3]}")
            else:
                resumen["cliente_nuevo"] += 1
                print(f"      cliente   no está: habría que darlo de alta como {tom!r}")

    print(f"\n  {'═' * 72}")
    for k, v in resumen.items():
        print(f"    {k.replace('_', ' '):18} {v}")
    print("\n  (no se ha escrito nada en la base)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
