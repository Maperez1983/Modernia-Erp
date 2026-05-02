#!/usr/bin/env python3
import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)


def scalar(conn: sqlite3.Connection, sql: str, args=()):
    cur = conn.execute(sql, args)
    row = cur.fetchone()
    if not row:
        return 0
    return row[0] if row[0] is not None else 0


def fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return str(value)


def fmt_pct(part, total) -> str:
    try:
        total_f = float(total or 0)
        part_f = float(part or 0)
        if total_f <= 0:
            return "0,00%"
        return f"{(part_f / total_f) * 100.0:.2f}%".replace(".", ",")
    except Exception:
        return "0,00%"


@dataclass
class SectionRow:
    label: str
    value: int
    pct_of_total: str = ""


def build_report(conn: sqlite3.Connection, db_path: Path) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines = []
    lines.append("# Auditoría integridad clientes")
    lines.append("")
    lines.append(f"- Fecha: `{now}`")
    lines.append(f"- DB: `{db_path}`")
    lines.append("")

    if not table_exists(conn, "clientes"):
        lines.append("No existe la tabla `clientes` en esta base de datos.")
        lines.append("")
        return "\n".join(lines)

    # Global
    clientes_total = scalar(conn, "SELECT COUNT(*) FROM clientes")
    clientes_sin_referido = 0
    if table_exists(conn, "clientes_empresas"):
        try:
            clientes_sin_referido = scalar(
                conn,
                "SELECT COUNT(*) FROM clientes WHERE COALESCE(TRIM(captado_por_user_id), '') = ''",
            )
        except Exception:
            clientes_sin_referido = 0
    lines.append("## Global")
    lines.append("")
    lines.append(f"- `clientes` total: **{fmt_int(clientes_total)}**")
    lines.append(
        f"- `clientes` sin `captado_por_user_id`: **{fmt_int(clientes_sin_referido)}** ({fmt_pct(clientes_sin_referido, clientes_total)})"
    )

    if table_exists(conn, "clientes_empresas"):
        ce_total = scalar(conn, "SELECT COUNT(*) FROM clientes_empresas")
        try:
            ce_sin_referido = scalar(
                conn,
                "SELECT COUNT(*) FROM clientes_empresas WHERE COALESCE(TRIM(captado_por_user_id), '') = ''",
            )
        except Exception:
            ce_sin_referido = 0
        lines.append(f"- `clientes_empresas` total: **{fmt_int(ce_total)}**")
        lines.append(
            f"- `clientes_empresas` sin `captado_por_user_id`: **{fmt_int(ce_sin_referido)}** ({fmt_pct(ce_sin_referido, ce_total)})"
        )
    lines.append("")

    def section(title: str):
        lines.append(f"## {title}")
        lines.append("")

    # Seguros
    if table_exists(conn, "seguros"):
        section("Seguros")
        seguros_total = scalar(conn, "SELECT COUNT(*) FROM seguros")
        seguros_sin_cliente_id = scalar(
            conn,
            "SELECT COUNT(*) FROM seguros WHERE COALESCE(TRIM(cliente_id), '') = ''",
        )
        seguros_cliente_inexistente = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM seguros s
            WHERE COALESCE(TRIM(s.cliente_id), '') != ''
              AND NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = s.cliente_id)
            """,
        )
        # Link clientes_empresas
        seguros_sin_link = 0
        if table_exists(conn, "clientes_empresas"):
            seguros_sin_link = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM seguros s
                WHERE COALESCE(TRIM(s.cliente_id), '') != ''
                  AND EXISTS (SELECT 1 FROM clientes c WHERE c.id = s.cliente_id)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM clientes_empresas ce
                    WHERE ce.cliente_id = s.cliente_id
                      AND ce.empresa_id = s.empresa_id
                      AND LOWER(COALESCE(ce.servicio, '')) LIKE '%seguro%'
                  )
                """,
            )

        lines.append(f"- `seguros` total: **{fmt_int(seguros_total)}**")
        lines.append(
            f"- `seguros` sin `cliente_id`: **{fmt_int(seguros_sin_cliente_id)}** ({fmt_pct(seguros_sin_cliente_id, seguros_total)})"
        )
        lines.append(
            f"- `seguros` con `cliente_id` que no existe en `clientes`: **{fmt_int(seguros_cliente_inexistente)}** ({fmt_pct(seguros_cliente_inexistente, seguros_total)})"
        )
        if table_exists(conn, "clientes_empresas"):
            lines.append(
                f"- `seguros` sin vínculo `clientes_empresas` (servicio seguros): **{fmt_int(seguros_sin_link)}** ({fmt_pct(seguros_sin_link, seguros_total)})"
            )
        lines.append("")

    # Hipotecas / Financiaciones
    if table_exists(conn, "hipotecas"):
        section("Hipotecas / Financiaciones")
        hip_total = scalar(conn, "SELECT COUNT(*) FROM hipotecas")
        hip_sin_cliente_id = scalar(conn, "SELECT COUNT(*) FROM hipotecas WHERE COALESCE(TRIM(cliente_id), '') = ''")
        hip_cliente_inexistente = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM hipotecas h
            WHERE COALESCE(TRIM(h.cliente_id), '') != ''
              AND NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = h.cliente_id)
            """,
        )
        hip_sin_link = 0
        if table_exists(conn, "clientes_empresas"):
            hip_sin_link = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM hipotecas h
                WHERE COALESCE(TRIM(h.cliente_id), '') != ''
                  AND EXISTS (SELECT 1 FROM clientes c WHERE c.id = h.cliente_id)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM clientes_empresas ce
                    WHERE ce.cliente_id = h.cliente_id
                      AND ce.empresa_id = h.empresa_id
                      AND (
                        LOWER(COALESCE(ce.servicio, '')) LIKE '%financ%'
                        OR LOWER(COALESCE(ce.servicio, '')) LIKE '%hipotec%'
                      )
                  )
                """,
            )
        lines.append(f"- `hipotecas` total: **{fmt_int(hip_total)}**")
        lines.append(
            f"- `hipotecas` sin `cliente_id`: **{fmt_int(hip_sin_cliente_id)}** ({fmt_pct(hip_sin_cliente_id, hip_total)})"
        )
        lines.append(
            f"- `hipotecas` con `cliente_id` inexistente en `clientes`: **{fmt_int(hip_cliente_inexistente)}** ({fmt_pct(hip_cliente_inexistente, hip_total)})"
        )
        if table_exists(conn, "clientes_empresas"):
            lines.append(
                f"- `hipotecas` sin vínculo `clientes_empresas` (financiaciones): **{fmt_int(hip_sin_link)}** ({fmt_pct(hip_sin_link, hip_total)})"
            )
        lines.append("")

    # Inmobiliaria (propietarios/compradores)
    if table_exists(conn, "inmueble_propietarios") or table_exists(conn, "inmueble_compradores"):
        section("Inmobiliaria (vínculos cliente)")
        if table_exists(conn, "inmueble_propietarios"):
            prop_total = scalar(conn, "SELECT COUNT(*) FROM inmueble_propietarios")
            prop_missing = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM inmueble_propietarios ip
                WHERE COALESCE(TRIM(ip.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = ip.cliente_id)
                """,
            )
            lines.append(
                f"- `inmueble_propietarios` con `cliente_id` vacío o inexistente: **{fmt_int(prop_missing)}** de **{fmt_int(prop_total)}** ({fmt_pct(prop_missing, prop_total)})"
            )
        if table_exists(conn, "inmueble_compradores"):
            comp_total = scalar(conn, "SELECT COUNT(*) FROM inmueble_compradores")
            comp_missing = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM inmueble_compradores ic
                WHERE COALESCE(TRIM(ic.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = ic.cliente_id)
                """,
            )
            lines.append(
                f"- `inmueble_compradores` con `cliente_id` vacío o inexistente: **{fmt_int(comp_missing)}** de **{fmt_int(comp_total)}** ({fmt_pct(comp_missing, comp_total)})"
            )
        lines.append("")

    # Gestoría (legacy + trabajos)
    if table_exists(conn, "gestoria") or table_exists(conn, "gestoria_trabajos") or table_exists(conn, "cliente_gestoria"):
        section("Gestoría")
        if table_exists(conn, "cliente_gestoria"):
            cg_total = scalar(conn, "SELECT COUNT(*) FROM cliente_gestoria")
            cg_missing = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM cliente_gestoria cg
                WHERE COALESCE(TRIM(cg.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = cg.cliente_id)
                """,
            )
            lines.append(
                f"- `cliente_gestoria` con `cliente_id` vacío o inexistente: **{fmt_int(cg_missing)}** de **{fmt_int(cg_total)}** ({fmt_pct(cg_missing, cg_total)})"
            )
        if table_exists(conn, "gestoria_trabajos"):
            gt_total = scalar(conn, "SELECT COUNT(*) FROM gestoria_trabajos")
            gt_missing = scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM gestoria_trabajos gt
                WHERE COALESCE(TRIM(gt.cliente_id), '') = ''
                   OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = gt.cliente_id)
                """,
            )
            lines.append(
                f"- `gestoria_trabajos` con `cliente_id` vacío o inexistente: **{fmt_int(gt_missing)}** de **{fmt_int(gt_total)}** ({fmt_pct(gt_missing, gt_total)})"
            )
        if table_exists(conn, "gestoria"):
            g_total = scalar(conn, "SELECT COUNT(*) FROM gestoria")
            # `gestoria.cliente` es texto; intentamos matching por nombre para estimar cobertura.
            g_match = 0
            try:
                g_match = scalar(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM gestoria g
                    WHERE COALESCE(TRIM(g.cliente), '') != ''
                      AND EXISTS (
                        SELECT 1 FROM clientes c
                        WHERE TRIM(UPPER(COALESCE(c.nombre,''))) = TRIM(UPPER(COALESCE(g.cliente,'')))
                      )
                    """,
                )
            except Exception:
                g_match = 0
            lines.append(f"- `gestoria` (tabla legacy con `cliente` texto) total: **{fmt_int(g_total)}**")
            lines.append(
                f"- `gestoria` con `cliente` que coincide con `clientes.nombre`: **{fmt_int(g_match)}** ({fmt_pct(g_match, g_total)})"
            )
        lines.append("")

    # Facturación workspace
    if table_exists(conn, "workspace_facturacion"):
        section("Facturación (workspace_facturacion)")
        wf_total = scalar(conn, "SELECT COUNT(*) FROM workspace_facturacion")
        wf_missing = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM workspace_facturacion f
            WHERE COALESCE(TRIM(f.cliente_id), '') = ''
               OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = f.cliente_id)
            """,
        )
        lines.append(
            f"- `workspace_facturacion` con `cliente_id` vacío o inexistente: **{fmt_int(wf_missing)}** de **{fmt_int(wf_total)}** ({fmt_pct(wf_missing, wf_total)})"
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Auditoría integridad de clientes en la DB del CRM.")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[1] / "data" / "erp_import2.sqlite"),
        help="Ruta al sqlite principal (por defecto data/erp_import2.sqlite).",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Ruta de salida (md). Si no se indica, solo imprime por stdout.",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    conn = sqlite3.connect(str(db_path))
    try:
        report = build_report(conn, db_path)
    finally:
        conn.close()

    print(report)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()

