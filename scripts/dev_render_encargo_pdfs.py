#!/usr/bin/env python3
"""
Genera PDFs de "nota de encargo" (Modernia) en local y los renderiza a imágenes para revisar solapes.

Uso:
  python3 scripts/dev_render_encargo_pdfs.py --out /tmp/encargo_check

Requiere:
  - Dependencias Python: reportlab, pypdf (mismas que usa el servidor)
  - Binario: pdftoppm (poppler) para render a PNG (opcional, pero recomendado)
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
    parser.add_argument("--out", default="/tmp/encargo_check", help="Carpeta salida")
    parser.add_argument("--dpi", type=int, default=144, help="DPI para render (pdftoppm)")
    parser.add_argument("--no-render", action="store_true", help="No renderizar a PNG")
    parser.add_argument("--only", choices=["venta", "alquiler", "both"], default="both")
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root))

    from web.server import (  # pylint: disable=import-error
        build_inmueble_nota_encargo_pdf_editable,
        build_inmueble_nota_encargo_pdf_final,
    )

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    company = {"nombre": "Modernia", "logo_url": None}
    inmueble = {
        "direccion": "Calle de Prueba 123, 4B",
        "codigo_postal": "28001",
        "poblacion": "Madrid",
        "provincia": "Madrid",
        "referencia_catastral": "1234567VK4713S0001AB",
        "m2": "85",
        "precio_objetivo": "350000",
    }
    captacion = {"precio_objetivo": "350000"}
    owners = [
        {
            "nombre": "Juan Pérez García",
            "nif": "12345678Z",
            "direccion": "C/ Larga 1, Madrid",
            "telefono": "600111222",
            "email": "juan@example.com",
        },
        {
            "nombre": "María López",
            "nif": "87654321X",
            "direccion": "C/ Larga 1, Madrid",
            "telefono": "600333444",
            "email": "maria@example.com",
        },
    ]

    base_extra = {
        "datos_registrales": "Tomo 1, Libro 2, Folio 3, Finca 4",
        "m2_utiles": "70",
        "otros": "Trastero y garaje incluidos",
        "cargas": "NADA",
        "honorarios_text": "3% + IVA",
        "fecha_inicio": "15/04/2026",
        "fecha_fin": "15/07/2026",
        "lugar_firma": "Madrid",
        "fecha_firma": "15/04/2026",
        "fecha_venta_desde": "15/04/2026",
        "fecha_venta_antes": "15/07/2026",
    }

    jobs: list[tuple[str, dict]] = []
    if args.only in {"venta", "both"}:
        jobs.append(("venta", {**base_extra, "tipo_operacion": "venta", "precio_venta": "350.000€"}))
    if args.only in {"alquiler", "both"}:
        jobs.append(
            (
                "alquiler",
                {
                    **base_extra,
                    "tipo_operacion": "alquiler",
                    "renta_mensual": "1200€",
                    "honorarios_mensualidades": "1 mensualidad + IVA",
                    "plazo_arrendamiento": "12 meses",
                },
            )
        )

    created: list[Path] = []
    for tipo, extra in jobs:
        editable_path = out_dir / f"encargo_{tipo}_editable.pdf"
        final_path = out_dir / f"encargo_{tipo}_final.pdf"

        editable_path.write_bytes(build_inmueble_nota_encargo_pdf_editable(company, inmueble, captacion, owners, extra=extra))
        final_path.write_bytes(build_inmueble_nota_encargo_pdf_final(company, inmueble, captacion, owners, extra=extra))
        created.extend([editable_path, final_path])

        if not args.no_render:
            _render_pdf_to_png(editable_path, out_dir, f"encargo_{tipo}_editable", args.dpi)
            _render_pdf_to_png(final_path, out_dir, f"encargo_{tipo}_final", args.dpi)

    print("OK. Generados:")
    for p in created:
        print(f"- {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

