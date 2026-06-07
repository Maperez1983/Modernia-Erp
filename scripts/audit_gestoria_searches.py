#!/usr/bin/env python3
"""Prueba buscadores del CRM gestoría contra Postgres sin modificar datos."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def d(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def rows(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [d(r) for r in (conn.execute(sql, params).fetchall() or [])]


def one(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    return d(conn.execute(sql, params).fetchone())


def norm_doc(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "").upper())


def norm_text(value: Any) -> str:
    raw = str(value or "").strip().lower()
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    return re.sub(r"\s+", " ", raw.translate(replacements)).strip()


def contains_name(row: dict[str, Any], query: str) -> bool:
    q = norm_text(query)
    return bool(q and q in norm_text(row.get("nombre") or row.get("cliente") or ""))


def test_result(name: str, ok: bool, detail: str, sample: Any = None) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "sample": sample}


def has_duplicate_ids(items: list[dict[str, Any]]) -> bool:
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        if item_id in seen:
            return True
        seen.add(item_id)
    return False


def dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        fallback = f"{norm_doc(item.get('nif'))}:{norm_text(item.get('nombre') or item.get('cliente'))}"
        key = item_id or fallback
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def default_gestoria_empresa(conn: Any) -> str:
    row = one(
        conn,
        """
        SELECT d.empresa_id, COUNT(*) AS total
        FROM gestoria_docs d
        WHERE COALESCE(TRIM(d.empresa_id), '') <> ''
        GROUP BY d.empresa_id
        ORDER BY total DESC
        LIMIT 1
        """,
    )
    return str(row.get("empresa_id") or "").strip()


def pick_samples(conn: Any, empresa_id: str) -> dict[str, dict[str, Any]]:
    service_filter = "LOWER(COALESCE(ce.servicio,'')) IN ('gestoria','gestoría')"
    sample_client = one(
        conn,
        f"""
        SELECT c.id, c.nombre, c.nif, c.telefono, c.email
        FROM clientes c
        JOIN clientes_empresas ce ON ce.cliente_id = c.id
        WHERE ce.empresa_id = ?
          AND {service_filter}
          AND COALESCE(TRIM(c.nombre), '') <> ''
          AND LENGTH(REGEXP_REPLACE(COALESCE(c.nif,''), '[^0-9A-Za-z]', '', 'g')) >= 5
        ORDER BY c.updated_at DESC
        LIMIT 1
        """,
        (empresa_id,),
    )
    sample_legacy = one(
        conn,
        """
        SELECT g.id, g.cliente AS nombre, g.estado, g.tipo, g.perfil
        FROM gestoria g
        WHERE g.empresa_id = ?
          AND COALESCE(TRIM(g.cliente), '') <> ''
        ORDER BY g.updated_at DESC
        LIMIT 1
        """,
        (empresa_id,),
    )
    sample_renta = one(
        conn,
        f"""
        SELECT c.id, c.nombre, c.nif
        FROM cliente_gestoria cg
        JOIN clientes c ON c.id = cg.cliente_id
        JOIN clientes_empresas ce ON ce.cliente_id = c.id
        WHERE ce.empresa_id = ?
          AND {service_filter}
          AND COALESCE(cg.mod_renta, 0) = 1
          AND COALESCE(TRIM(c.nombre), '') <> ''
        ORDER BY c.updated_at DESC
        LIMIT 1
        """,
        (empresa_id,),
    )
    sample_doc = one(
        conn,
        """
        SELECT d.id, d.nombre, d.tipo, d.cliente_id, c.nombre AS cliente
        FROM gestoria_docs d
        JOIN clientes c ON c.id = d.cliente_id
        WHERE d.empresa_id = ?
          AND COALESCE(TRIM(d.nombre), '') <> ''
        ORDER BY d.updated_at DESC
        LIMIT 1
        """,
        (empresa_id,),
    )
    sample_work = one(
        conn,
        """
        SELECT gt.id, gt.tipo_trabajo, gt.estado, gt.cliente_id, c.nombre AS cliente
        FROM gestoria_trabajos gt
        JOIN clientes c ON c.id = gt.cliente_id
        WHERE gt.empresa_id = ?
          AND COALESCE(TRIM(c.nombre), '') <> ''
        ORDER BY gt.updated_at DESC
        LIMIT 1
        """,
        (empresa_id,),
    )
    return {
        "client": sample_client,
        "legacy": sample_legacy,
        "renta": sample_renta,
        "doc": sample_doc,
        "work": sample_work,
    }


def run_audit(conn: Any, empresa_id: str) -> dict[str, Any]:
    samples = pick_samples(conn, empresa_id)
    tests: list[dict[str, Any]] = []

    client = samples.get("client") or {}
    client_id = str(client.get("id") or "").strip()
    client_name = str(client.get("nombre") or "").strip()
    client_nif = norm_doc(client.get("nif"))

    if client_id and client_nif:
        by_nif = rows(
            conn,
            """
            SELECT id, nombre, nif
            FROM clientes
            WHERE REPLACE(REPLACE(UPPER(COALESCE(nif, '')), ' ', ''), '-', '') = ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 6
            """,
            (client_nif,),
        )
        tests.append(
            test_result(
                "clientes_by_nif",
                any(str(r.get("id")) == client_id for r in by_nif),
                f"Busca NIF {client_nif} y debe devolver el cliente de gestoría.",
                by_nif[:3],
            )
        )

    if client_id and client_name:
        term = client_name.split()[0] if client_name.split() else client_name[:5]
        quick_raw = rows(
            conn,
            """
            SELECT c.id, c.nombre, c.nif
            FROM clientes c
            JOIN clientes_empresas ce ON ce.cliente_id = c.id
            WHERE ce.empresa_id = ?
              AND LOWER(COALESCE(ce.servicio,'')) IN ('gestoria','gestoría')
              AND LOWER(COALESCE(c.nombre,'')) LIKE ?
            ORDER BY c.updated_at DESC
            LIMIT 20
            """,
            (empresa_id, f"%{term.lower()}%"),
        )
        quick = dedupe_by_id(quick_raw)
        tests.append(
            test_result(
                "buscador_clientes_nombre",
                any(str(r.get("id")) == client_id for r in quick) and not has_duplicate_ids(quick),
                f"Busca por nombre parcial '{term}' sin duplicar fichas. Origen bruto: {len(quick_raw)}, visible: {len(quick)}.",
                quick[:5],
            )
        )

    legacy = samples.get("legacy") or {}
    legacy_name = str(legacy.get("nombre") or "").strip()
    if legacy_name:
        term = legacy_name.split()[0] if legacy_name.split() else legacy_name[:5]
        legacy_rows = rows(
            conn,
            """
            SELECT id, cliente, tipo, perfil, estado
            FROM gestoria
            WHERE empresa_id = ?
              AND LOWER(COALESCE(cliente,'')) LIKE ?
            ORDER BY updated_at DESC
            LIMIT 20
            """,
            (empresa_id, f"%{term.lower()}%"),
        )
        tests.append(
            test_result(
                "buscador_tabla_gestoria_legacy",
                any(str(r.get("id")) == str(legacy.get("id")) for r in legacy_rows),
                f"Busca en tabla legacy por '{term}'.",
                legacy_rows[:5],
            )
        )

    renta = samples.get("renta") or {}
    renta_id = str(renta.get("id") or "").strip()
    renta_name = str(renta.get("nombre") or "").strip()
    renta_nif = norm_doc(renta.get("nif"))
    if renta_id and (renta_name or renta_nif):
        term = renta_nif or (renta_name.split()[0] if renta_name.split() else renta_name[:5])
        # Equivalente al endpoint /api/gestoria_renta_cards: cliente_gestoria + clientes + vínculo servicio.
        renta_rows = rows(
            conn,
            """
            SELECT DISTINCT c.id, c.nombre, c.nif
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            JOIN clientes_empresas ce ON ce.cliente_id = c.id
            WHERE ce.empresa_id = ?
              AND LOWER(COALESCE(ce.servicio,'')) IN ('gestoria','gestoría')
              AND COALESCE(cg.mod_renta, 0) = 1
              AND (
                LOWER(COALESCE(c.nombre,'')) LIKE ?
                OR REPLACE(REPLACE(UPPER(COALESCE(c.nif, '')), ' ', ''), '-', '') LIKE ?
              )
            ORDER BY c.nombre
            LIMIT 20
            """,
            (empresa_id, f"%{term.lower()}%", f"%{norm_doc(term)}%"),
        )
        tests.append(
            test_result(
                "buscador_rentas_nombre_nif",
                any(str(r.get("id")) == renta_id for r in renta_rows),
                f"Busca renta por '{term}'.",
                renta_rows[:5],
            )
        )

    doc = samples.get("doc") or {}
    doc_cliente_id = str(doc.get("cliente_id") or "").strip()
    if doc_cliente_id:
        doc_rows = rows(
            conn,
            """
            SELECT id, nombre, tipo, fecha, estado
            FROM gestoria_docs
            WHERE cliente_id = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (doc_cliente_id,),
        )
        tests.append(
            test_result(
                "buscador_documentos_por_cliente",
                any(str(r.get("id")) == str(doc.get("id")) for r in doc_rows),
                "Carga documentos al abrir ficha/cliente.",
                doc_rows[:5],
            )
        )

    work = samples.get("work") or {}
    work_cliente_id = str(work.get("cliente_id") or "").strip()
    if work_cliente_id:
        work_rows = rows(
            conn,
            """
            SELECT id, tipo_trabajo, estado, cliente_id
            FROM gestoria_trabajos
            WHERE cliente_id = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (work_cliente_id,),
        )
        tests.append(
            test_result(
                "buscador_trabajos_por_cliente",
                any(str(r.get("id")) == str(work.get("id")) for r in work_rows),
                "Carga trabajos al abrir ficha/cliente.",
                work_rows[:5],
            )
        )

    failed = [t for t in tests if not t.get("ok")]
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "empresa_id": empresa_id,
        "status": "ok" if not failed else "needs_fix",
        "samples": samples,
        "tests": tests,
        "summary": {"total": len(tests), "passed": len(tests) - len(failed), "failed": len(failed)},
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Auditoría buscadores CRM gestoría",
        "",
        f"- Fecha: `{audit['generated_at']}`",
        f"- Estado: **{audit['status']}**",
        f"- Tests: **{audit['summary']['passed']}** / **{audit['summary']['total']}**",
        "",
        "## Resultados",
        "",
    ]
    for test in audit.get("tests") or []:
        marker = "OK" if test.get("ok") else "FALLO"
        lines.append(f"### [{marker}] {test.get('name')}")
        lines.append("")
        lines.append(f"- {test.get('detail')}")
        sample = test.get("sample")
        if sample:
            lines.append(f"- Muestra: `{json.dumps(sample, ensure_ascii=False, default=str)}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita buscadores de clientes del CRM gestoría.")
    parser.add_argument("--empresa-id", default="")
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from web.db_backend import open_postgres_conn

    conn = open_postgres_conn(with_row_factory=True)
    try:
        empresa_id = str(args.empresa_id or "").strip() or default_gestoria_empresa(conn)
        audit = run_audit(conn, empresa_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2, default=str))
        return 0 if audit["status"] == "ok" else 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"gestoria_search_audit_{stamp}.json"
    md_path = out_dir / f"gestoria_search_audit_{stamp}.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(audit), encoding="utf-8")
    print(f"status={audit['status']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print("summary=" + json.dumps(audit.get("summary") or {}, ensure_ascii=False, sort_keys=True))
    return 0 if audit["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
