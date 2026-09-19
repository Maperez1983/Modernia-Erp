"""Carga en la gestoría los gastos ya leídos (JSON de la lectura documento a documento).

Hecho para GAPP (2026-09-19): 384 documentos entre facturas, tiques y fotos, leídos uno a
uno. Aquí se decide cómo se contabiliza cada uno y por qué hay que revisarlo:

- Factura completa a nombre del cliente (su NIF como destinatario): base al gasto e IVA
  deducible (472).
- Tique / factura simplificada / justificante de datáfono / factura a nombre de otra
  persona: el importe entero al gasto, sin IVA deducible.
- Duplicados, proformas, pretiques, multas y facturas emitidas mezcladas: no se cargan.

Cada documento sale con sus motivos de revisión (tique, lectura dudosa, IVA raro...), que
el CRM guarda como alerta para que alguien lo revise y anote el apunte.

Sin --aplicar solo enseña lo que haría.

  python scripts/cargar_gastos_leidos.py CONSOLIDADO.json --empresa-id ID --cliente-id ID [--aplicar]
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cargar_facturas_de_carpeta import _post, _r2  # noqa: E402

COMBUSTIBLE = re.compile(r"gasoil|gas[oó]leo|gasolin|diesel|di[eé]sel|combust|repost|carburante", re.I)


def es_factura_deducible(f):
    return f.get("tipo") == "factura" and f.get("a_nombre_de_gapp") is True


def motivos_de_revision(f):
    """Por qué este apunte necesita que alguien lo mire. Vacío = factura limpia."""
    m = []
    notas = (f.get("notas") or "").lower()
    concepto = f"{f.get('concepto') or ''} {f.get('proveedor') or ''}"
    if f.get("tipo") == "ticket":
        m.append("tique: IVA no deducible, comprobar que es gasto de la empresa")
    elif f.get("tipo") == "factura" and f.get("a_nombre_de_gapp") is False:
        m.append("factura a nombre de otra persona: IVA no deducible")
    elif f.get("tipo") == "factura" and f.get("a_nombre_de_gapp") is None:
        m.append("factura sin destinatario: se trata como tique")
    if f.get("confianza") == "baja":
        m.append("lectura dudosa: documento poco legible, pedir copia")
    elif f.get("confianza") == "media":
        m.append("lectura con dudas: revisar datos")
    if es_factura_deducible(f) and f.get("iva_pct") == 10 and COMBUSTIBLE.search(concepto):
        m.append("combustible con IVA al 10 %: debería ser 21 %")
    if es_factura_deducible(f) and not f.get("iva") and float(f.get("total") or 0) > 50:
        m.append("factura sin IVA desglosado: confirmar IVA y retención")
    if float(f.get("total") or 0) < 0:
        m.append("abono o rectificativa")
    if "rectificativa" in notas or "anticipo" in notas:
        m.append("rectificativa: comprobar el anticipo")
    if "páginas" in notas or "agregado" in notas or "20 p" in notas:
        m.append("varios tiques en un documento: desglosar")
    if not f.get("numero"):
        m.append("sin número de factura")
    if not f.get("nif_proveedor") and f.get("tipo") == "factura":
        m.append("factura sin NIF del proveedor")
    return m


def apunte(f):
    """Datos para la ingesta: lo deducible solo si es factura a nombre del cliente."""
    total = _r2(f.get("total"))
    numero = (f.get("numero") or "").strip()
    if not numero:
        # Sin número: uno estable a partir del fichero, para que recargar no duplique.
        numero = "S/N-" + hashlib.sha1(f["archivo"].encode()).hexdigest()[:8]
    datos = {
        "numero": numero,
        "fecha": f.get("fecha"),
        "tercero": (f.get("proveedor") or "").strip()[:120],
        "nif": re.sub(r"[\s.\-]", "", str(f.get("nif_proveedor") or "")).upper(),
        "descripcion": (f.get("concepto") or "").strip()[:200],
        "total": total,
        "sin_ocr": True,
    }
    if es_factura_deducible(f):
        datos.update({
            "base_imponible": _r2(f.get("base")),
            "cuota_iva": _r2(f.get("iva")),
            "cuota_irpf": _r2(f.get("irpf")),
            "iva_pct": f.get("iva_pct") or 0,
        })
    else:
        datos.update({"base_imponible": total, "cuota_iva": 0, "cuota_irpf": 0, "iva_pct": 0})
    datos["revision_motivos"] = motivos_de_revision(f)
    return datos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("consolidado")
    ap.add_argument("--empresa-id", required=True)
    ap.add_argument("--cliente-id", required=True)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    validos = json.load(open(a.consolidado, encoding="utf-8"))["validos"]
    apuntes = [(Path(f["archivo"]), f, apunte(f)) for f in validos]
    sin_fecha = [f["archivo"] for _p, f, d in apuntes if not d["fecha"]]
    for s in sin_fecha:
        print("AVISO sin fecha, no se carga:", s)
    apuntes = [x for x in apuntes if x[2]["fecha"]]
    deducibles = sum(1 for _p, f, _d in apuntes if es_factura_deducible(f))
    con_revision = sum(1 for _p, _f, d in apuntes if d["revision_motivos"])
    print(f"{len(apuntes)} gastos · {deducibles} facturas con IVA deducible · {len(apuntes) - deducibles} al gasto entero · "
          f"{con_revision} con alerta de revisión · total {sum(d['total'] for _p, _f, d in apuntes):.2f}")
    if not a.aplicar:
        for p, _f, d in apuntes[:15]:
            print(f"  {d['fecha']} {d['numero'][:14]:<14} {d['tercero'][:28]:<28} base {d['base_imponible']:>8.2f} "
                  f"IVA {d['cuota_iva']:>7.2f} total {d['total']:>8.2f} | {'; '.join(d['revision_motivos'])[:90]}")
        print("(prueba: no se ha cargado nada; añade --aplicar)")
        return
    clave = os.environ.get("APP_INGEST_API_KEY", "").strip()
    if not clave:
        sys.exit("Falta APP_INGEST_API_KEY en el entorno (.env).")
    resultado, fallos = [], 0
    for pdf, f, datos in apuntes:
        tipo_mime = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png"}.get(
            pdf.suffix.lower().lstrip("."), "application/pdf")
        try:
            firma = _post("/api/ingest_facturas_presign", {
                "empresa_id": a.empresa_id, "tipo": "RECIBIDAS", "year": datos["fecha"][:4],
                "filename": pdf.name, "content_type": tipo_mime,
            }, clave)
            import urllib.request

            req = urllib.request.Request(firma["url"], data=pdf.read_bytes(), method="PUT",
                                         headers={"Content-Type": tipo_mime})
            with urllib.request.urlopen(req, timeout=120):
                pass
            r = _post("/api/ingest_facturas_ocr", {
                "empresa_id": a.empresa_id, "s3_key": firma["key"], "filename": pdf.name, "tipo": "RECIBIDAS",
                "cliente_id": a.cliente_id, **datos,
            }, clave)
            resultado.append({"archivo": str(pdf), "factura_id": r.get("factura_id") or r.get("id"),
                              "duplicada": bool(r.get("duplicate")), "revision_motivos": datos["revision_motivos"]})
        except Exception as exc:
            fallos += 1
            detalle = getattr(exc, "read", lambda: b"")().decode(errors="replace")[:300]
            print("ERROR", pdf.name, exc, detalle)
            resultado.append({"archivo": str(pdf), "error": str(exc)})
    salida = Path(a.consolidado).with_name("cargados.json")
    json.dump(resultado, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Terminado: {len(apuntes) - fallos} cargados, {fallos} con error. Detalle en {salida}")


if __name__ == "__main__":
    main()
