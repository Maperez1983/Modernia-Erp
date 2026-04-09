#!/usr/bin/env python3
"""
Genera un PDF (manual) del CRM Inmobiliaria basado en la UI/flujo actuales.

Objetivo:
- Explicar "cómo funciona" y "cómo debería funcionar" el módulo.
- Servir como guía operativa para el equipo (checklists y buenas prácticas).

No usa DB. Se apoya en el builder de PDFs ya presente en web/server.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="/tmp/manual_crm_inmobiliaria_verifika2.pdf",
        help="Ruta de salida del PDF",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from web import server

    title = "MANUAL · CRM INMOBILIARIA"
    subtitle = (
        "Guia operativa del modulo Inmobiliaria dentro de Verifika².\n"
        "Version: abril 2026.\n"
        "Nota: este manual describe el comportamiento actual del CRM (UI y endpoints) y la forma recomendada de uso."
    )

    sections = [
        (
            "Objetivo del modulo",
            [
                "Controlar el pipeline comercial (noticia, encargo, propuesta, reserva, arras, cierre).",
                "Centralizar el expediente del inmueble: datos, propietarios, compradores, visitas, documentos, checklist y auditoria.",
                "Operar con trazabilidad: acciones, agenda y documentacion generada (PDFs).",
            ],
        ),
        (
            "Acceso y contexto (workspace y empresa)",
            [
                "Entra en el CRM, selecciona tu usuario y el workspace del cliente.",
                "Selecciona la empresa operativa de inmobiliaria (normalmente Estudio Velazquez 2012 SL).",
                "Abre la pestaña Inmobiliaria (CRM inmobiliario).",
            ],
        ),
        (
            "Estructura de pantallas (tabs)",
            [
                ("Resumen", "KPIs, proximos hitos, pendientes y enlaces rapidos."),
                ("Analisis", "Panel de series y comparativas anuales (ventas, alquileres, comisiones)."),
                ("Pipeline", "Captaciones/pipeline por etapa y accesos a ficha."),
                ("Inmuebles", "Inventario y expedientes. Entrada principal al detalle."),
                ("Alquileres", "Seguimiento de alquileres y actividad asociada."),
                ("Compraventas", "Historico de operaciones y estado."),
                ("Demandas", "Demandas de compradores/inquilinos y matching con inmuebles."),
                ("Visitas", "Visitas registradas por inmueble/demanda."),
                ("Agenda", "Acciones planificadas y seguimiento comercial."),
                ("Informadores", "Origenes/colaboradores y trazabilidad."),
                ("Edificios/Complejos", "Agrupacion de inmuebles por edificio/urbanizacion."),
                ("Copiloto legal", "Ayuda operativa para dudas legales habituales."),
            ],
        ),
        (
            "Nuevo inmueble (alta rapida)",
            [
                "Boton: 'Nuevo inmueble'.",
                "Rellena como minimo direccion, localidad y tipo (lo demas se puede completar despues).",
                "Si tienes referencia catastral, guardala desde el inicio para facilitar catastro, mapa y documentacion.",
            ],
        ),
        (
            "Pipeline (captaciones) y etapas",
            [
                "La etapa comercial se refleja en la ficha del inmueble y/o captacion vinculada.",
                "Cambios de etapa: desde la ficha, pestaña Estado, usando los botones (Noticia, Encargo, Propuesta, Reservado, Arras, Vendido, Cerrado, Alquiler).",
                "Recomendacion: antes de avanzar a Encargo, sube documentacion minima y valida datos de propietario.",
            ],
        ),
        (
            "Ficha de inmueble (expediente)",
            [
                "Cabecera: direccion, referencia y estado comercial.",
                "Datos: tipo inmueble, m2, habitaciones, banos, precio objetivo/valoracion, zona, coordenadas (lat/lon).",
                "Propietarios: enlaza clientes propietarios y mantén telefono/email actualizados.",
                "Compradores: lista de interesados (vinculados a demandas) y sus proximas acciones.",
                "Documentos: subida de archivos (PDF, imagen, office). El sistema guarda historico por version.",
                "Checklist: tareas sugeridas por etapa (generable) para no olvidar pasos operativos.",
                "Timeline/auditoria: historial de documentos, acciones y cambios.",
            ],
        ),
        (
            "Mapa y ubicacion",
            [
                "Completa lat/lon (o usa sincronizacion/consulta de catastro cuando aplique).",
                "El mapa se usa para vista rapida y para documentos (ej: presupuestos/otros).",
                "Si no hay coordenadas, el sistema puede mostrar informacion limitada.",
            ],
        ),
        (
            "Demandas y matching",
            [
                "Crea una demanda para comprador/inquilino con zona, presupuesto maximo y requisitos (m2, habitaciones, banos).",
                "Usa el matching desde demanda o desde inmueble para encontrar candidatos compatibles.",
                "Recomendacion: mantén la demanda en una fase/estado coherente para priorizar seguimientos.",
            ],
        ),
        (
            "Visitas y agenda (acciones)",
            [
                "Registra visitas vinculandolas a un inmueble y, si existe, a una demanda.",
                "Programa proximas acciones (llamada, visita, propuesta, seguimiento) con fecha/hora y responsable.",
                "Objetivo: que el pipeline sea accionable, no solo un listado de fichas.",
            ],
        ),
        (
            "PDFs disponibles en inmobiliaria (cuando procede)",
            [
                "Hoja de visita PDF (solo visible cuando el inmueble esta en Encargo).",
                "Nota de encargo PDF (documento comercial/mandato, editable via datos del expediente).",
                "Ficha venta PDF y Nota precio PDF (consumo; requiere Encargo).",
                "DIA alquiler PDF (consumo; requiere Encargo).",
                "Nota: los PDFs se guardan en los documentos del inmueble y se pueden regenerar.",
            ],
        ),
        (
            "Comportamiento esperado (checklist de calidad)",
            [
                "Alta: crear inmueble debe ser inmediato y no exigir datos no esenciales.",
                "Expediente: cambios en ficha deben guardarse sin bloquear (autosave) y con estado claro de guardado.",
                "Permisos: usuarios con acceso al servicio Inmobiliaria deben ver inmuebles, demandas, visitas y documentos del servicio.",
                "PDFs: visibles y generables solo cuando la etapa lo permite (Encargo), sin errores de layout ni textos legacy.",
                "Matching: al menos por empresa + zona + presupuesto + requisitos basicos, con resultados consistentes.",
            ],
        ),
        (
            "Puntos tipicos de incidencia (para detectar errores)",
            [
                "Botones ocultos por estado: si el estado no es exactamente 'Encargo', los PDFs no aparecen.",
                "Datos inconsistentes entre captacion e inmueble (estado comercial, precio objetivo).",
                "Documentos: versiones duplicadas si se regeneran PDFs sin reemplazo (debe reemplazar si asi se indica).",
                "Mapa: ausencia de lat/lon o errores de sincronizacion pueden dejar la ficha sin visualizacion.",
            ],
        ),
    ]

    footer = [
        "Documento interno. Si detectas un comportamiento distinto al descrito, anota: usuario, workspace, empresa y pasos para reproducir.",
        "Verifika² · Manual CRM Inmobiliaria.",
    ]

    pdf_bytes = server.build_branded_document_pdf(
        title,
        subtitle,
        sections,
        footer_lines=footer,
        brand_logo_url="/assets/verifika2/verifika2_wordmark_check_green_transparent.png",
    )

    out_path = Path(args.out).expanduser().resolve()
    out_path.write_bytes(pdf_bytes)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

