#!/usr/bin/env python3
"""Cuánto acierta el lector de pólizas, medido contra 133 PDF de verdad.

La verdad conocida
------------------
Los PDF de la correduría se nombran `COMPAÑÍA RAMO NOMBRE Póliza NÚMERO.pdf`. Eso da un
patrón de referencia gratis: **el número y el nombre están en el nombre del fichero**, así
que se puede medir el acierto del OCR sin teclear nada a mano.

No es una verdad perfecta —hay ficheros sin número, y alguno donde el nombre y el papel
se contradicen— pero para 133 documentos es infinitamente mejor que mirar cuatro a ojo.

Por qué importa
---------------
El tomador que saca el OCR se equivoca en un 28 % de los casos, y no falla en silencio:
falla creando clientes. La ficha «Y CONDUCTOR» de producción salió de aquí — el PDF era
`POLIZA AUTO Nº 2002400455146 - ADRIAN GUTIERREZ.pdf` y el lector se quedó con el
encabezado «...y conductor» de la letra pequeña. Lo mismo con «del Seguro Por SANITAS» y
«Edificación y anexos».

Cada punto que suba este número es una ficha basura menos.

Cómo se usa
-----------
El texto de cada PDF se cachea una vez (es lo lento); a partir de ahí sólo se vuelve a
interpretar, que es instantáneo. Así se puede tocar `parse_poliza_text` y volver a medir
en segundos.

    python scripts/mide_el_ocr_de_polizas.py                    # mide
    python scripts/mide_el_ocr_de_polizas.py --fallos           # y enseña los fallos
    python scripts/mide_el_ocr_de_polizas.py --compania AXA     # sólo una compañía
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

CACHE = Path("/private/tmp/texto_polizas.json")

# Palabras que aparecen en el nombre del fichero y no son parte del nombre del cliente.
RUIDO_FICHERO = re.compile(
    r"(?i)\b(poliza|p[oó]liza|n[ºo°]|seguro|seguros|rc|hogar|auto|autoo|salud|caza|pesca|"
    r"vida|decesos|comercio|comercios|convenio|impago|impagos|accidente|accidentes|moto|"
    r"oficina|negocio|viaje|pyme|alquiler|confort|colectivo|de|del|la|el|y|con|pdf|"
    r"allianz|axa|mapfre|reale|ocaso|zurich|generali|occident|occidente|fiact|fiatc|"
    r"gallen|pelayo|sanitas|dkv|mutua|propietario|propietarios|arag|santa|lucia|sta|"
    r"invercapital|pias|iptiq|lloyd)\b")


def sin_tildes(v):
    return unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()


def numero_del_fichero(nombre):
    """El número de póliza tal y como lo escribieron al guardar el PDF.

    Occident y otras ponen **letra de control al final** —`8 11.239.386 E`— y la primera
    versión de esto la tiraba. Resultado: once fallos de Occident que no existían, y a
    punto estuve de «arreglar» un lector que funcionaba. La vara de medir se comprueba
    antes que lo medido.
    """
    nombre = re.sub(r"\.(pdf|PDF)$", "", nombre)        # que la «p» de .pdf no cuente
    # El número puede llevar letra de control al final, separada o no: «8 11.239.386 E».
    m = re.search(r"(?:N[ºo°]\s*|[Pp][oó]liza\s+)([0-9][0-9.\-\s]{5,}?)([\s\-]?[A-Z])?(?=\s|$)",
                  nombre)
    if not m:
        m = re.search(r"(?<![0-9A-Za-z])([0-9][0-9.\-]{7,})([\s\-]?[A-Z])?(?=\s|$)", nombre)
    if not m:
        return ""
    crudo = (m.group(1) or "") + (m.group(2) or "")
    return re.sub(r"[.\-\s]", "", crudo).upper()


def nombre_del_fichero(nombre):
    """El nombre del cliente que asoma en el nombre del fichero."""
    t = re.sub(r"\.(pdf|PDF)$", "", nombre)
    t = re.sub(r"\d[\d.\-]{4,}", " ", t)
    t = re.sub(r"[_]+", " ", t)
    t = RUIDO_FICHERO.sub(" ", sin_tildes(t))
    t = re.sub(r"[^A-Za-z ]", " ", t)
    return " ".join(w for w in t.split() if len(w) > 2).upper()


def palabras(v):
    return frozenset(w for w in sin_tildes(v).upper().split() if len(w) > 2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fallos", action="store_true", help="enseña cada fallo")
    ap.add_argument("--compania", default="", help="filtra por compañía")
    args = ap.parse_args(argv)

    if not CACHE.exists():
        print(f"\n  Falta el caché de texto en {CACHE}.\n"
              f"  Se genera una vez leyendo los PDF; después esto va instantáneo.\n")
        return 2
    os.environ.setdefault("DATABASE_URL", "")
    os.environ.setdefault("POSTGRES_URL", "")
    from web import server as S

    datos = json.loads(CACHE.read_text(encoding="utf-8"))
    tot = {"n": 0, "num_ok": 0, "num_mal": 0, "num_falta": 0,
           "nom_ok": 0, "nom_vacio": 0, "nom_inventado": 0,
           "sin_verdad_num": 0, "sin_verdad_nom": 0}
    fallos_num, fallos_nom, por_compania = [], [], {}

    for fichero, d in sorted(datos.items()):
        texto = d.get("texto") or ""
        if not texto.strip():
            continue
        campos = S.parse_poliza_text(texto, source_hint=fichero) or {}
        compania = str(campos.get("compania") or "").strip() or "?"
        if args.compania and args.compania.lower() not in compania.lower():
            continue
        tot["n"] += 1
        c = por_compania.setdefault(compania, {"n": 0, "num": 0, "nom": 0, "inv": 0})
        c["n"] += 1

        # --- el número ---
        esperado = numero_del_fichero(fichero)
        sacado = re.sub(r"[.\-\s]", "", str(campos.get("poliza_numero") or "")).upper()
        if not esperado:
            tot["sin_verdad_num"] += 1
        elif not sacado:
            tot["num_falta"] += 1
            fallos_num.append((fichero, compania, esperado, "(no lo saca)"))
        elif sacado == esperado or esperado.endswith(sacado) or sacado.endswith(esperado):
            tot["num_ok"] += 1
            c["num"] += 1
        else:
            tot["num_mal"] += 1
            fallos_num.append((fichero, compania, esperado, sacado))

        # --- el tomador ---
        verdad = palabras(nombre_del_fichero(fichero))
        salio = palabras(str(campos.get("tomador") or ""))
        # Vacío e inventado NO son el mismo fallo. Vacío para la ficha y pide a una
        # persona; inventado crea un cliente llamado «Y CONDUCTOR». Se cuentan aparte.
        if len(verdad) < 2:
            tot["sin_verdad_nom"] += 1
        elif salio & verdad:
            tot["nom_ok"] += 1
            c["nom"] += 1
        elif not salio:
            tot["nom_vacio"] += 1
            fallos_nom.append((fichero, compania, " ".join(sorted(verdad)), "(vacío)"))
        else:
            tot["nom_inventado"] += 1
            c["inv"] += 1
            fallos_nom.append((fichero, compania,
                               " ".join(sorted(verdad)), campos.get("tomador") or ""))

    print(f"\n  {tot['n']} pólizas leídas\n")
    comp_num = tot["num_ok"] + tot["num_mal"] + tot["num_falta"]
    comp_nom = tot["nom_ok"] + tot["nom_vacio"] + tot["nom_inventado"]
    print(f"  NÚMERO DE PÓLIZA   {tot['num_ok']:>3}/{comp_num} correctos "
          f"({100 * tot['num_ok'] / max(comp_num, 1):.0f} %)   "
          f"· {tot['num_mal']} distintos · {tot['num_falta']} no lo sacan")
    print(f"  TOMADOR            {tot['nom_ok']:>3}/{comp_nom} correctos "
          f"({100 * tot['nom_ok'] / max(comp_nom, 1):.0f} %)")
    print(f"    lo deja vacío    {tot['nom_vacio']:>3}   (seguro: no crea nada)")
    print(f"    SE LO INVENTA    {tot['nom_inventado']:>3}   "
          f"← esto es lo que crea fichas basura")
    print(f"  (sin referencia en el nombre del fichero: {tot['sin_verdad_num']} números, "
          f"{tot['sin_verdad_nom']} nombres)")

    print(f"\n  {'compañía':16}{'n':>4}{'nº ok':>8}{'tomador ok':>12}{'inventado':>11}")
    for comp, c in sorted(por_compania.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {comp[:15]:16}{c['n']:>4}{c['num']:>8}{c['nom']:>12}{c['inv']:>11}")

    if args.fallos:
        print(f"\n  === el número sale distinto ({len(fallos_num)}) ===")
        for f, comp, esp, sal in fallos_num:
            print(f"    {comp[:10]:12} espera {esp[:18]:20} saca {sal[:22]:24} {f[:40]}")
        print(f"\n  === el tomador no es quien dice el fichero ({len(fallos_nom)}) ===")
        for f, comp, esp, sal in fallos_nom:
            print(f"    {comp[:10]:12} {esp[:26]:28} saca {str(sal)[:30]:32} {f[:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
