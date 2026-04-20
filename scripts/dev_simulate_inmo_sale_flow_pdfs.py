#!/usr/bin/env python3
"""
Simula un flujo básico de venta (cita + propuesta) y genera TODOS los PDFs asociados
para revisión visual de solapes y maquetación.

Genera (venta):
  - Hoja de visita (cita)
  - Ficha informativa de venta (DIA)
  - Propuesta (documento de negociación)
  - Reconocimiento de honorarios (editable, AcroForm)
  - Nota explicativa precio/formas de pago
  - Nota de encargo (editable + final) sobre plantilla Modernia

Uso:
  python3 scripts/dev_simulate_inmo_sale_flow_pdfs.py --out /tmp/inmo_sale_flow --dpi 144
  python3 scripts/dev_simulate_inmo_sale_flow_pdfs.py --out /tmp/inmo_sale_flow --long

Requiere (recomendado):
  - `pdftoppm` (poppler) para render a PNG
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _render_pdf_to_png(pdf_path: Path, out_dir: Path, prefix: str, dpi: int) -> None:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        print("WARN: no se encuentra `pdftoppm`; se omite render a PNG.")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = out_dir / prefix
    subprocess.run([pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(out_prefix)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/inmo_sale_flow", help="Carpeta salida")
    parser.add_argument("--dpi", type=int, default=144, help="DPI para render (pdftoppm)")
    parser.add_argument("--no-render", action="store_true", help="No renderizar a PNG")
    parser.add_argument("--long", action="store_true", help="Usa textos largos (stress test)")
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root))

    from web.server import (  # pylint: disable=import-error
        build_inmueble_catastro_sheet_pdf,
        build_inmueble_consumo_sale_price_note_pdf,
        build_inmueble_consumo_sale_sheet_pdf,
        build_inmueble_consumo_rental_dia_pdf,
        build_inmueble_honorarios_ack_pdf_editable,
        build_inmueble_negotiation_offer_pdf,
        build_inmueble_nota_encargo_pdf_editable,
        build_inmueble_nota_encargo_pdf_final,
        build_inmueble_visit_sheet_pdf,
    )

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    company = {"nombre": "Modernia", "logo_url": None}
    inmueble = {
        "direccion": "PASAJE AUGUSTO GONZALEZ DE BESADA 2 14D",
        "codigo_postal": "29004",
        "poblacion": "MÁLAGA",
        "provincia": "MÁLAGA",
        "referencia": "N-P 001",
        "referencia_catastral": "0119101UF7601N00078RM",
        "tipo_inmueble": "Piso",
        "m2": "83",
        "habitaciones": "3",
        "banos": "2",
        "precio_objetivo": "220000",
    }
    captacion = {
        "precio_objetivo": inmueble["precio_objetivo"],
        "situacion_comercial": "Inmueble",
        "notas": "Expediente simulado para revisión de PDFs.",
    }

    owners = [
        {
            "nombre": "MIGUEL ANGEL PÉREZ RODRÍGUEZ",
            "nif": "25099562F",
            "direccion": "C/ Ildefonso Marzo 18, 29003 Málaga",
            "telefono": "600111222",
            "email": "miguel@example.com",
        }
    ]
    buyer = {
        "nombre": "INVER SURE HOMES & INVESTMENT S.L.",
        "nif": "B12345678",
        "telefono": "951234567",
        "email": "compras@inversure.example.com",
    }

    if args.long:
        owners[0].update(
            {
                "nombre": "MIGUEL ANGEL PÉREZ RODRÍGUEZ Y OTRO NOMBRE MUY MUY LARGO PARA PROBAR DESBORDE",
                "telefono": "+34 600 111 222 333 444",
                "email": "correo.muy.largo+con.alias.para.probar.desbordes@dominio-super-largo-ejemplo-empresa.com",
                "direccion": "CALLE ILDEFONSO MARZO 18 - MÁLAGA (29003) EDIFICIO CON NOMBRE MUY LARGO, ESCALERA 1, PLANTA 3, PUERTA B",
            }
        )
        buyer.update(
            {
                "nombre": "INVER SURE HOMES & INVESTMENT SOCIEDAD LIMITADA UNIPERSONAL CON DENOMINACIÓN MUY MUY LARGA",
                "email": "departamento.compras.inmobiliarias@dominio-corporativo-super-largo-ejemplo.com",
            }
        )
        captacion["notas"] = (
            "Notas extremadamente largas para forzar saltos de línea y validar que no hay solapes ni desbordes en los PDFs. "
            "Se deben recortar/truncar textos en overlays cuando proceda."
        )

    demanda = {
        "tipo": "Compra",
        "presupuesto": inmueble["precio_objetivo"],
        "zonas": "Málaga centro",
    }

    cita_action = {
        "fecha": "20/04/2026",
        "hora": "10:00",
        "tipo": "Cita de adquisición",
        "estado": "Realizada",
        "resultado": "Positivo",
        "notas": "Cita simulada para comprobar PDFs y maquetación.",
    }
    propuesta_action = {
        "documento_tipo": "Propuesta de compra",
        "importe_propuesta": "210000",
        "fecha": "20/04/2026",
        "notas": "Propuesta sujeta a revisión documental y validación jurídica.",
    }

    docs = [
        {"tipo": "Nota simple", "nombre": "nota_simple.pdf"},
        {"tipo": "Certificado energético", "nombre": "cee.pdf"},
        {"tipo": "IBI", "nombre": "ibi.pdf"},
    ]

    extra_encargo = {
        "tipo_operacion": "venta",
        "datos_registrales": "Tomo 1, Libro 2, Folio 3, Finca 4",
        "m2_utiles": "70",
        "otros": "Trastero y garaje incluidos",
        "cargas": "NADA",
        "honorarios_text": "3% + IVA",
        "fecha_inicio": "20/04/2026",
        "fecha_fin": "20/07/2026",
        "lugar_firma": "Málaga",
        "fecha_firma": "20/04/2026",
        "fecha_venta_desde": "20/04/2026",
        "fecha_venta_antes": "20/07/2026",
        "precio_venta": "220.000€",
    }

    jobs: list[tuple[str, bytes]] = []
    jobs.append(("01_cita_hoja_visita.pdf", build_inmueble_visit_sheet_pdf(company, inmueble, captacion, owners, buyer, demanda=demanda)))
    jobs.append(("02_cita_ficha_informativa_venta.pdf", build_inmueble_consumo_sale_sheet_pdf(company, inmueble, captacion, docs)))
    jobs.append(("03_propuesta.pdf", build_inmueble_negotiation_offer_pdf(company, inmueble, buyer, propuesta_action)))
    jobs.append(("04_reconocimiento_honorarios_editable.pdf", build_inmueble_honorarios_ack_pdf_editable(company, inmueble, buyer, propuesta_action, extra={"iva_pct": "21"})))
    jobs.append(("05_nota_precio_forma_pago.pdf", build_inmueble_consumo_sale_price_note_pdf(company, inmueble, captacion)))
    jobs.append(("06_nota_encargo_venta_editable.pdf", build_inmueble_nota_encargo_pdf_editable(company, inmueble, captacion, owners, extra=extra_encargo)))
    jobs.append(("07_nota_encargo_venta_final.pdf", build_inmueble_nota_encargo_pdf_final(company, inmueble, captacion, owners, extra=extra_encargo)))
    jobs.append(("08_dia_alquiler.pdf", build_inmueble_consumo_rental_dia_pdf(company, inmueble, captacion, docs)))
    jobs.append(
        (
            "09_ficha_catastral.pdf",
            build_inmueble_catastro_sheet_pdf(
                company,
                inmueble,
                {
                    "referencia_catastral": inmueble.get("referencia_catastral"),
                    "localizacion": inmueble.get("direccion"),
                    "superficie_construida_m2": inmueble.get("m2"),
                    "superficie_grafica_m2": "120",
                    "anio_construccion": "1998",
                    "coef_participacion": "2.34%",
                    "uso": "Residencial",
                    "referencia_parcela": str(inmueble.get("referencia_catastral") or "")[:14],
                    "tipo_parcela": "Urbana",
                    "localizacion_parcela": inmueble.get("poblacion") or "",
                },
            ),
        )
    )

    created: list[Path] = []
    for filename, pdf_bytes in jobs:
        path = out_dir / filename
        path.write_bytes(pdf_bytes)
        created.append(path)
        if not args.no_render:
            _render_pdf_to_png(path, out_dir, path.stem, args.dpi)

    print("OK. Generados:")
    for p in created:
        print(f"- {p}")
    if not args.no_render:
        print(f"PNG: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
