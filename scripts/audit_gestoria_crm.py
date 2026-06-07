#!/usr/bin/env python3
"""Audita el CRM de gestoría en Postgres sin modificar datos."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class Finding:
    severity: str
    title: str
    count: int
    detail: str
    sample: list[dict[str, Any]] = field(default_factory=list)


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    data = row_to_dict(row)
    if data:
        value = next(iter(data.values()))
    else:
        value = row[0]
    try:
        return int(value or 0)
    except Exception:
        return 0


def rows(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in (conn.execute(sql, params).fetchall() or [])]


def table_exists(conn: Any, table: str) -> bool:
    return bool(
        scalar(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table,),
        )
    )


def column_exists(conn: Any, table: str, column: str) -> bool:
    return bool(
        scalar(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ? AND column_name = ?
            """,
            (table, column),
        )
    )


def sample_query(conn: Any, sql: str, params: tuple[Any, ...], limit: int) -> list[dict[str, Any]]:
    return rows(conn, sql, (*params, limit))


def add_finding(
    findings: list[Finding],
    conn: Any,
    *,
    severity: str,
    title: str,
    count_sql: str,
    sample_sql: str,
    detail: str,
    params: tuple[Any, ...] = (),
    limit: int = 10,
) -> None:
    count = scalar(conn, count_sql, params)
    sample: list[dict[str, Any]] = []
    if count:
        sample = sample_query(conn, sample_sql, params, limit)
    findings.append(Finding(severity, title, count, detail, sample))


def fmt_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def severity_score(value: str) -> int:
    return {"blocker": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(value, 9)


def build_audit(conn: Any, sample_limit: int) -> dict[str, Any]:
    required = [
        "clientes",
        "clientes_empresas",
        "cliente_gestoria",
        "gestoria_docs",
        "gestoria_trabajos",
        "gestoria_import_lotes",
        "gestoria_import_documentos",
        "gestoria_facturas",
        "gestoria_asientos",
        "gestoria_asiento_lineas",
        "gestoria_terceros",
        "gestoria_modelos",
    ]
    tables = {name: table_exists(conn, name) for name in required}
    findings: list[Finding] = []

    for table, exists in tables.items():
        if not exists:
            findings.append(
                Finding(
                    "blocker",
                    f"Falta tabla {table}",
                    1,
                    "El módulo no puede darse por cerrado si falta una tabla esperada.",
                )
            )

    metrics: dict[str, Any] = {}
    for table, exists in tables.items():
        if exists:
            metrics[f"{table}_total"] = scalar(conn, f"SELECT COUNT(*) AS total FROM {table}")

    if tables.get("cliente_gestoria"):
        add_finding(
            findings,
            conn,
            severity="blocker",
            title="Clientes de gestoría sin cliente maestro",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM cliente_gestoria cg
                WHERE COALESCE(TRIM(cg.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = cg.cliente_id)
            """,
            sample_sql="""
                SELECT cg.id, cg.cliente_id, cg.tipo_cliente, cg.mod_fiscal, cg.mod_renta
                FROM cliente_gestoria cg
                WHERE COALESCE(TRIM(cg.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = cg.cliente_id)
                ORDER BY cg.updated_at DESC
                LIMIT ?
            """,
            detail="Rompe la ficha 360 y cualquier flujo asociado al cliente.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="high",
            title="Clientes de gestoría sin vínculo activo de servicio",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM cliente_gestoria cg
                JOIN clientes c ON c.id = cg.cliente_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM clientes_empresas ce
                    WHERE ce.cliente_id = cg.cliente_id
                      AND LOWER(COALESCE(ce.servicio, '')) IN ('gestoria', 'gestoría')
                      AND LOWER(COALESCE(ce.estado, 'activo')) NOT IN ('baja', 'inactivo')
                )
            """,
            sample_sql="""
                SELECT cg.id, c.id AS cliente_id, c.nombre, c.nif, cg.tipo_cliente
                FROM cliente_gestoria cg
                JOIN clientes c ON c.id = cg.cliente_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM clientes_empresas ce
                    WHERE ce.cliente_id = cg.cliente_id
                      AND LOWER(COALESCE(ce.servicio, '')) IN ('gestoria', 'gestoría')
                      AND LOWER(COALESCE(ce.estado, 'activo')) NOT IN ('baja', 'inactivo')
                )
                ORDER BY c.nombre
                LIMIT ?
            """,
            detail="Puede hacer que el cliente no aparezca correctamente en filtros por servicio o workspace.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Clientes de gestoría sin ningún módulo activo",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM cliente_gestoria
                WHERE COALESCE(mod_fiscal,0) = 0
                  AND COALESCE(mod_laboral,0) = 0
                  AND COALESCE(mod_contable,0) = 0
                  AND COALESCE(mod_renta,0) = 0
                  AND COALESCE(mod_registro,0) = 0
                  AND COALESCE(mod_trafico,0) = 0
                  AND COALESCE(mod_puntuales,0) = 0
            """,
            sample_sql="""
                SELECT cg.id, c.id AS cliente_id, c.nombre, c.nif, cg.tipo_cliente
                FROM cliente_gestoria cg
                LEFT JOIN clientes c ON c.id = cg.cliente_id
                WHERE COALESCE(mod_fiscal,0) = 0
                  AND COALESCE(mod_laboral,0) = 0
                  AND COALESCE(mod_contable,0) = 0
                  AND COALESCE(mod_renta,0) = 0
                  AND COALESCE(mod_registro,0) = 0
                  AND COALESCE(mod_trafico,0) = 0
                  AND COALESCE(mod_puntuales,0) = 0
                ORDER BY cg.updated_at DESC
                LIMIT ?
            """,
            detail="Son altas incompletas o fichas residuales que generan ruido operativo.",
            limit=sample_limit,
        )

    if tables.get("clientes"):
        add_finding(
            findings,
            conn,
            severity="high",
            title="NIF duplicado en clientes",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM (
                    SELECT UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g')) AS nif_norm
                    FROM clientes
                    WHERE COALESCE(TRIM(nif), '') <> ''
                      AND LENGTH(UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g'))) >= 5
                    GROUP BY UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g'))
                    HAVING COUNT(*) > 1
                ) dup
            """,
            sample_sql="""
                SELECT UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g')) AS nif_norm,
                       COUNT(*) AS total,
                       STRING_AGG(COALESCE(nombre,''), ' | ' ORDER BY nombre) AS nombres
                FROM clientes
                WHERE COALESCE(TRIM(nif), '') <> ''
                  AND LENGTH(UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g'))) >= 5
                GROUP BY UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g'))
                HAVING COUNT(*) > 1
                ORDER BY total DESC, nif_norm
                LIMIT ?
            """,
            detail="Un mismo contribuyente puede quedar dividido en varias fichas y documentos.",
            limit=sample_limit,
        )

    if tables.get("gestoria_docs"):
        has_hash = column_exists(conn, "gestoria_docs", "archivo_hash")
        add_finding(
            findings,
            conn,
            severity="blocker",
            title="Documentos de gestoría sin cliente válido",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_docs d
                WHERE COALESCE(TRIM(d.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = d.cliente_id)
            """,
            sample_sql="""
                SELECT d.id, d.empresa_id, d.cliente_id, d.nombre, d.tipo, d.referencia_tipo, d.fecha
                FROM gestoria_docs d
                WHERE COALESCE(TRIM(d.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = d.cliente_id)
                ORDER BY d.updated_at DESC
                LIMIT ?
            """,
            detail="Impide garantizar trazabilidad documental por cliente.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="high",
            title="Documentos de gestoría sin archivo accesible",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_docs
                WHERE COALESCE(TRIM(doc_key), '') = ''
                  AND COALESCE(TRIM(doc_url), '') = ''
            """,
            sample_sql="""
                SELECT id, empresa_id, cliente_id, nombre, tipo, referencia_tipo, fecha, notas
                FROM gestoria_docs
                WHERE COALESCE(TRIM(doc_key), '') = ''
                  AND COALESCE(TRIM(doc_url), '') = ''
                ORDER BY updated_at DESC
                LIMIT ?
            """,
            detail="La ficha puede enseñar un documento que después no se puede abrir.",
            limit=sample_limit,
        )
        if has_hash:
            add_finding(
                findings,
                conn,
                severity="high",
                title="Archivos duplicados por hash en el mismo cliente",
                count_sql="""
                    SELECT COUNT(*) AS total
                    FROM (
                        SELECT cliente_id, archivo_hash
                        FROM gestoria_docs
                        WHERE COALESCE(TRIM(cliente_id), '') <> ''
                          AND COALESCE(TRIM(archivo_hash), '') <> ''
                        GROUP BY cliente_id, archivo_hash
                        HAVING COUNT(*) > 1
                    ) dup
                """,
                sample_sql="""
                    SELECT cliente_id, archivo_hash,
                           COUNT(*) AS total,
                           STRING_AGG(COALESCE(nombre,''), ' | ' ORDER BY nombre) AS nombres
                    FROM gestoria_docs
                    WHERE COALESCE(TRIM(cliente_id), '') <> ''
                      AND COALESCE(TRIM(archivo_hash), '') <> ''
                    GROUP BY cliente_id, archivo_hash
                    HAVING COUNT(*) > 1
                    ORDER BY total DESC
                    LIMIT ?
                """,
                detail="La misma renta/factura/documento está repetida dentro de una misma ficha.",
                limit=sample_limit,
            )
            add_finding(
                findings,
                conn,
                severity="info",
                title="Archivos por hash compartidos entre clientes",
                count_sql="""
                    SELECT COUNT(*) AS total
                    FROM (
                        SELECT archivo_hash
                        FROM gestoria_docs
                        WHERE COALESCE(TRIM(cliente_id), '') <> ''
                          AND COALESCE(TRIM(archivo_hash), '') <> ''
                        GROUP BY archivo_hash
                        HAVING COUNT(DISTINCT cliente_id) > 1
                    ) dup
                """,
                sample_sql="""
                    SELECT archivo_hash,
                           COUNT(DISTINCT cliente_id) AS clientes,
                           COUNT(*) AS documentos,
                           STRING_AGG(DISTINCT COALESCE(nombre,''), ' | ' ORDER BY COALESCE(nombre,'')) AS nombres
                    FROM gestoria_docs
                    WHERE COALESCE(TRIM(cliente_id), '') <> ''
                      AND COALESCE(TRIM(archivo_hash), '') <> ''
                    GROUP BY archivo_hash
                    HAVING COUNT(DISTINCT cliente_id) > 1
                    ORDER BY clientes DESC, documentos DESC
                    LIMIT ?
                """,
                detail="Puede ser una declaración conjunta o documentación compartida; se informa sin bloquear el cierre.",
                limit=sample_limit,
            )
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Rentas/Modelo 100 sin módulo de renta activo",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_docs d
                LEFT JOIN cliente_gestoria cg ON cg.cliente_id = d.cliente_id
                WHERE (
                    LOWER(COALESCE(d.referencia_tipo,'')) = 'renta'
                    OR LOWER(COALESCE(d.tipo,'')) IN ('renta', 'declaracion de renta', 'declaración de renta')
                    OR LOWER(COALESCE(d.nombre,'')) LIKE '%modelo 100%'
                    OR LOWER(COALESCE(d.nombre,'')) LIKE 'renta %'
                )
                  AND COALESCE(cg.mod_renta, 0) = 0
            """,
            sample_sql="""
                SELECT d.id, d.cliente_id, c.nombre AS cliente, c.nif, d.nombre, d.tipo, d.fecha
                FROM gestoria_docs d
                LEFT JOIN clientes c ON c.id = d.cliente_id
                LEFT JOIN cliente_gestoria cg ON cg.cliente_id = d.cliente_id
                WHERE (
                    LOWER(COALESCE(d.referencia_tipo,'')) = 'renta'
                    OR LOWER(COALESCE(d.tipo,'')) IN ('renta', 'declaracion de renta', 'declaración de renta')
                    OR LOWER(COALESCE(d.nombre,'')) LIKE '%modelo 100%'
                    OR LOWER(COALESCE(d.nombre,'')) LIKE 'renta %'
                )
                  AND COALESCE(cg.mod_renta, 0) = 0
                ORDER BY d.updated_at DESC
                LIMIT ?
            """,
            detail="Puede ocultar contribuyentes en paneles de campaña de renta.",
            limit=sample_limit,
        )

    if tables.get("gestoria_trabajos"):
        add_finding(
            findings,
            conn,
            severity="blocker",
            title="Trabajos de gestoría sin cliente válido",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_trabajos gt
                WHERE COALESCE(TRIM(gt.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = gt.cliente_id)
            """,
            sample_sql="""
                SELECT gt.id, gt.empresa_id, gt.cliente_id, gt.tipo_trabajo, gt.estado, gt.fecha_inicio, gt.fecha_fin
                FROM gestoria_trabajos gt
                WHERE COALESCE(TRIM(gt.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = gt.cliente_id)
                ORDER BY gt.updated_at DESC
                LIMIT ?
            """,
            detail="Rompe el seguimiento de trabajos y el resumen de ficha cliente.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Trabajos vencidos todavía abiertos",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_trabajos
                WHERE COALESCE(TRIM(fecha_fin), '') <> ''
                  AND fecha_fin < CURRENT_DATE::text
                  AND LOWER(COALESCE(estado, '')) NOT IN ('completado', 'cerrado', 'finalizado', 'hecho', 'presentado', 'cancelado')
            """,
            sample_sql="""
                SELECT id, empresa_id, cliente_id, tipo_trabajo, estado, fecha_inicio, fecha_fin, responsable
                FROM gestoria_trabajos
                WHERE COALESCE(TRIM(fecha_fin), '') <> ''
                  AND fecha_fin < CURRENT_DATE::text
                  AND LOWER(COALESCE(estado, '')) NOT IN ('completado', 'cerrado', 'finalizado', 'hecho', 'presentado', 'cancelado')
                ORDER BY fecha_fin ASC
                LIMIT ?
            """,
            detail="Genera agenda falsa y pérdida de control operativo.",
            limit=sample_limit,
        )

    if tables.get("gestoria_import_lotes") and tables.get("gestoria_import_documentos"):
        add_finding(
            findings,
            conn,
            severity="high",
            title="Documentos de importación con lote inexistente",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_import_documentos d
                WHERE NOT EXISTS (SELECT 1 FROM gestoria_import_lotes l WHERE l.id = d.lote_id)
            """,
            sample_sql="""
                SELECT id, lote_id, empresa_id, cliente_id, archivo_nombre, estado_revision
                FROM gestoria_import_documentos d
                WHERE NOT EXISTS (SELECT 1 FROM gestoria_import_lotes l WHERE l.id = d.lote_id)
                ORDER BY updated_at DESC
                LIMIT ?
            """,
            detail="Hace imposible auditar un lote importado.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Lotes con totales descuadrados",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_import_lotes l
                LEFT JOIN (
                    SELECT lote_id,
                           COUNT(*) AS total_documentos,
                           SUM(CASE WHEN UPPER(COALESCE(estado_revision,''))='OK' THEN 1 ELSE 0 END) AS total_ok,
                           SUM(CASE WHEN UPPER(COALESCE(estado_revision,''))='DUPLICADO' THEN 1 ELSE 0 END) AS total_duplicado,
                           SUM(CASE WHEN UPPER(COALESCE(estado_revision,''))='ERROR' THEN 1 ELSE 0 END) AS total_error
                    FROM gestoria_import_documentos
                    GROUP BY lote_id
                ) calc ON calc.lote_id = l.id
                WHERE COALESCE(l.total_documentos,0) <> COALESCE(calc.total_documentos,0)
                   OR COALESCE(l.total_ok,0) <> COALESCE(calc.total_ok,0)
                   OR COALESCE(l.total_duplicado,0) <> COALESCE(calc.total_duplicado,0)
                   OR COALESCE(l.total_error,0) <> COALESCE(calc.total_error,0)
            """,
            sample_sql="""
                SELECT l.id, l.empresa_id, l.cliente_id, l.estado, l.periodo,
                       l.total_documentos, COALESCE(calc.total_documentos,0) AS calc_total,
                       l.total_ok, COALESCE(calc.total_ok,0) AS calc_ok,
                       l.total_duplicado, COALESCE(calc.total_duplicado,0) AS calc_duplicado,
                       l.total_error, COALESCE(calc.total_error,0) AS calc_error
                FROM gestoria_import_lotes l
                LEFT JOIN (
                    SELECT lote_id,
                           COUNT(*) AS total_documentos,
                           SUM(CASE WHEN UPPER(COALESCE(estado_revision,''))='OK' THEN 1 ELSE 0 END) AS total_ok,
                           SUM(CASE WHEN UPPER(COALESCE(estado_revision,''))='DUPLICADO' THEN 1 ELSE 0 END) AS total_duplicado,
                           SUM(CASE WHEN UPPER(COALESCE(estado_revision,''))='ERROR' THEN 1 ELSE 0 END) AS total_error
                    FROM gestoria_import_documentos
                    GROUP BY lote_id
                ) calc ON calc.lote_id = l.id
                WHERE COALESCE(l.total_documentos,0) <> COALESCE(calc.total_documentos,0)
                   OR COALESCE(l.total_ok,0) <> COALESCE(calc.total_ok,0)
                   OR COALESCE(l.total_duplicado,0) <> COALESCE(calc.total_duplicado,0)
                   OR COALESCE(l.total_error,0) <> COALESCE(calc.total_error,0)
                ORDER BY l.updated_at DESC
                LIMIT ?
            """,
            detail="El panel de lotes no reflejaría el estado real de los documentos importados.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Importaciones duplicadas por hash no marcadas como duplicado",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM (
                    SELECT archivo_hash
                    FROM gestoria_import_documentos
                    WHERE COALESCE(TRIM(archivo_hash), '') <> ''
                      AND UPPER(COALESCE(estado_revision,'')) <> 'DUPLICADO'
                    GROUP BY archivo_hash
                    HAVING COUNT(*) > 1
                ) dup
            """,
            sample_sql="""
                SELECT archivo_hash, COUNT(*) AS total,
                       STRING_AGG(COALESCE(archivo_nombre,''), ' | ' ORDER BY archivo_nombre) AS archivos
                FROM gestoria_import_documentos
                WHERE COALESCE(TRIM(archivo_hash), '') <> ''
                  AND UPPER(COALESCE(estado_revision,'')) <> 'DUPLICADO'
                GROUP BY archivo_hash
                HAVING COUNT(*) > 1
                ORDER BY total DESC
                LIMIT ?
            """,
            detail="Puede duplicar facturas/asientos si el usuario aplica lotes repetidos.",
            limit=sample_limit,
        )

    if tables.get("gestoria_facturas"):
        add_finding(
            findings,
            conn,
            severity="info",
            title="Facturas de gestoría sin cliente asociado",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_facturas f
                WHERE COALESCE(TRIM(f.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = f.cliente_id)
            """,
            sample_sql="""
                SELECT f.id, f.empresa_id, f.cliente_id, f.numero, f.fecha_emision, f.total, f.estado_ocr
                FROM gestoria_facturas f
                WHERE COALESCE(TRIM(f.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = f.cliente_id)
                ORDER BY f.updated_at DESC
                LIMIT ?
            """,
            detail="Puede ser gasto interno de empresa; se informa para revisión, pero no bloquea el módulo.",
            limit=sample_limit,
        )
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Facturas con total descuadrado frente a base/IVA/IRPF",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_facturas
                WHERE total IS NOT NULL
                  AND ABS(COALESCE(total,0) - (COALESCE(base_imponible,0) + COALESCE(cuota_iva,0) - COALESCE(cuota_irpf,0))) > 0.05
            """,
            sample_sql="""
                SELECT id, empresa_id, cliente_id, numero, fecha_emision,
                       base_imponible, cuota_iva, cuota_irpf, total
                FROM gestoria_facturas
                WHERE total IS NOT NULL
                  AND ABS(COALESCE(total,0) - (COALESCE(base_imponible,0) + COALESCE(cuota_iva,0) - COALESCE(cuota_irpf,0))) > 0.05
                ORDER BY updated_at DESC
                LIMIT ?
            """,
            detail="Señal de OCR/importación contable que requiere revisión.",
            limit=sample_limit,
        )

    if tables.get("gestoria_asientos"):
        add_finding(
            findings,
            conn,
            severity="high",
            title="Asientos descuadrados",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_asientos
                WHERE ABS(COALESCE(total_debe,0) - COALESCE(total_haber,0)) > 0.01
            """,
            sample_sql="""
                SELECT id, empresa_id, cliente_id, factura_id, fecha, concepto, total_debe, total_haber
                FROM gestoria_asientos
                WHERE ABS(COALESCE(total_debe,0) - COALESCE(total_haber,0)) > 0.01
                ORDER BY updated_at DESC
                LIMIT ?
            """,
            detail="Bloquea una contabilidad mínimamente fiable.",
            limit=sample_limit,
        )
        if tables.get("gestoria_asiento_lineas"):
            add_finding(
                findings,
                conn,
                severity="medium",
                title="Asientos sin líneas contables",
                count_sql="""
                    SELECT COUNT(*) AS total
                    FROM gestoria_asientos a
                    WHERE NOT EXISTS (SELECT 1 FROM gestoria_asiento_lineas l WHERE l.asiento_id = a.id)
                """,
                sample_sql="""
                    SELECT a.id, a.empresa_id, a.cliente_id, a.factura_id, a.fecha, a.concepto
                    FROM gestoria_asientos a
                    WHERE NOT EXISTS (SELECT 1 FROM gestoria_asiento_lineas l WHERE l.asiento_id = a.id)
                    ORDER BY a.updated_at DESC
                    LIMIT ?
                """,
                detail="Hay asiento de cabecera, pero no se puede revisar el detalle.",
                limit=sample_limit,
            )

    if tables.get("gestoria_contabilidad"):
        add_finding(
            findings,
            conn,
            severity="medium",
            title="Movimientos de gestoría sin fecha o importe",
            count_sql="""
                SELECT COUNT(*) AS total
                FROM gestoria_contabilidad
                WHERE COALESCE(TRIM(fecha), '') = ''
                   OR importe IS NULL
            """,
            sample_sql="""
                SELECT id, empresa_id, cliente_id, fecha, concepto, gestion, tipo, importe
                FROM gestoria_contabilidad
                WHERE COALESCE(TRIM(fecha), '') = ''
                   OR importe IS NULL
                ORDER BY updated_at DESC
                LIMIT ?
            """,
            detail="Desvirtúa dashboards de ingresos/cobros y listados por periodo.",
            limit=sample_limit,
        )

    findings.sort(key=lambda f: (severity_score(f.severity), -f.count, f.title))
    blockers = sum(1 for f in findings if f.severity == "blocker" and f.count)
    high = sum(1 for f in findings if f.severity == "high" and f.count)
    medium = sum(1 for f in findings if f.severity == "medium" and f.count)
    status = "blocked" if blockers else ("needs_fix" if high or medium else "ok")
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": status,
        "metrics": metrics,
        "tables": tables,
        "summary": {"blockers": blockers, "high": high, "medium": medium},
        "findings": [f.__dict__ for f in findings],
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Auditoría CRM gestoría")
    lines.append("")
    lines.append(f"- Fecha: `{audit['generated_at']}`")
    lines.append(f"- Estado: **{audit['status']}**")
    summary = audit.get("summary") or {}
    lines.append(
        f"- Hallazgos activos: blockers `{summary.get('blockers', 0)}`, high `{summary.get('high', 0)}`, medium `{summary.get('medium', 0)}`"
    )
    lines.append("")
    lines.append("## Métricas")
    lines.append("")
    for key, value in sorted((audit.get("metrics") or {}).items()):
        lines.append(f"- `{key}`: **{fmt_int(value)}**")
    lines.append("")
    lines.append("## Hallazgos")
    lines.append("")
    for finding in audit.get("findings") or []:
        count = int(finding.get("count") or 0)
        marker = "ACTIVO" if count else "OK"
        lines.append(f"### [{marker}] {finding.get('severity')} · {finding.get('title')}")
        lines.append("")
        lines.append(f"- Registros: **{fmt_int(count)}**")
        lines.append(f"- Impacto: {finding.get('detail')}")
        sample = finding.get("sample") or []
        if sample:
            lines.append("- Muestra:")
            for row in sample[:10]:
                compact = {k: v for k, v in row.items() if v not in (None, "")}
                lines.append(f"  - `{json.dumps(compact, ensure_ascii=False, default=str)}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita el CRM de gestoría en Postgres.")
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--json", action="store_true", help="Imprime JSON por stdout.")
    args = parser.parse_args()

    from web.db_backend import open_postgres_conn

    conn = open_postgres_conn(with_row_factory=True)
    try:
        audit = build_audit(conn, max(1, min(int(args.sample_limit or 10), 50)))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2, default=str))
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"gestoria_crm_audit_{stamp}.json"
    md_path = out_dir / f"gestoria_crm_audit_{stamp}.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(audit), encoding="utf-8")
    print(f"status={audit['status']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(
        "summary="
        + json.dumps(audit.get("summary") or {}, ensure_ascii=False, sort_keys=True, default=str)
    )
    return 1 if audit["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
