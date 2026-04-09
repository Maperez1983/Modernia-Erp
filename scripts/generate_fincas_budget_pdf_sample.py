#!/usr/bin/env python3
"""
Genera un PDF de presupuesto de prueba (Fincas) para validar:
- Carta de presentación (portada)
- Logos alineados sin solapes
- Mapa embebido (no QR) cuando hay coordenadas

No depende de la DB: construye un payload mínimo y llama al builder.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="/tmp/presupuesto_prueba_fincas.pdf",
        help="Ruta de salida del PDF",
    )
    args = parser.parse_args()

    # Import tardío para que el script sea portable.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from web import server

    carta = (
        "Hola {{solicitante_nombre}},\n"
        "\n"
        "Gracias por solicitarnos presupuesto para la comunidad {{comunidad_denominacion}}.\n"
        "Nuestro objetivo es que tengas una administración clara, rápida y cercana: respuesta inmediata, "
        "seguimiento continuo y un equipo accesible para vecinos y junta de gobierno.\n"
        "\n"
        "Además de Administración de Fincas, contamos con servicios complementarios para la comunidad:\n"
        "  • Asesoría fiscal\n"
        "  • Seguros\n"
        "  • Inmobiliaria\n"
        "  • Construcciones y reformas\n"
        "  • Asesoría jurídica\n"
        "  • Inversiones\n"
        "\n"
        "Contacto directo:\n"
        "Miguel Angel Perez Rodriguez · 667646193 · info@fincasvelazquez.es\n"
        "Antonio Chacon 5 · 29003 Malaga\n"
    )

    calc = {
        "num_vecinos": 12,
        "num_locales": 0,
        "num_trasteros": 0,
        "num_aparcamientos": 0,
        "cuota_sugerida": 60.0,
        "comunidad_denominacion": "C.P. Maria Manrique 4",
        "comunidad_direccion": "Antonio Chacon 5, 29003 Malaga",
        "comunidad_cif": "",
        "solicitante_nombre": "C.P. Maria Manrique 4",
        "solicitante_dni": "",
        "solicitante_telefono": "",
        "solicitante_email": "",
        "colegiado_numero": "3079",
        # Coordenadas aproximadas en Malaga (para forzar mapa embebido).
        "map_lat": 36.7116,
        "map_lon": -4.4313,
        # Carta opcional (portada).
        "carta_presentacion": carta,
        # Lista de servicios incluidos en la ficha.
        "servicios_incluidos": [
            "Atencion y gestion de incidencias (priorizacion por urgencia).",
            "Gestion y control de proveedores y mantenimientos.",
            "Convocatoria y asistencia a junta ordinaria anual.",
            "Gestion de juntas extraordinarias (segun necesidad).",
            "Contabilidad de la comunidad (ingresos, gastos) y reporting.",
            "Gestion de cobros, seguimiento de impagos.",
            "Cumplimiento LPH: comunicaciones y soporte administrativo.",
        ],
    }

    budget = {
        "id": "DEMO-FINCAS-0001",
        "workspace_id": "ws_demo",
        "empresa_id": "empresa_demo",
        "cliente_id": "cliente_demo",
        "servicio": "Administracion de fincas",
        "titulo": "Propuesta de servicios de administracion de fincas",
        "estado": "Borrador",
        "fecha": "2026-04-09",
        "responsable": "Miguel Angel Perez Rodriguez",
        "forma_pago": "Pendiente de definir",
        "observaciones": "",
        "subtotal": 60.0,
        "impuestos": 12.6,
        "total": 72.6,
        "calculo_json": json.dumps(calc, ensure_ascii=False),
    }

    workspace = {
        "nombre": "Verifika²",
        "primary_color": "#0B1D33",
        "accent_color": "#F2C14E",
    }

    company = {
        "nombre": "Estudio Velazquez 2012 SL",
        # El builder de Fincas fuerza el logo de assets (Fincas Velazquez) cuando servicio_key == fincas.
        "logo_url": "",
    }

    client = {
        "nombre": "C.P. Maria Manrique 4",
        "nif": "",
        "email": "",
        "telefono": "",
    }

    lineas = [
        {
            "orden": 1,
            "categoria": "Viviendas",
            "concepto": "Administracion mensual",
            "cantidad": 12,
            "unidad": "unidad",
            "precio_unitario": 5.0,
            "descuento_pct": 0.0,
            "total_linea": 60.0,
        }
    ]

    pdf_bytes = server.build_workspace_budget_pdf(budget, workspace, company, client, lineas)
    out_path = Path(args.out).expanduser().resolve()
    out_path.write_bytes(pdf_bytes)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
