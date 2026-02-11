#!/usr/bin/env python3
import argparse
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path


VALID_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}


def norm_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def norm_company(value):
    return norm_text(value)


def norm_policy(value):
    text = str(value or "").upper()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def split_name_variants(name):
    raw = str(name or "").strip()
    if not raw:
        return []
    variants = {norm_text(raw)}
    if "," in raw:
        left, right = [p.strip() for p in raw.split(",", 1)]
        if left and right:
            variants.add(norm_text(f"{right} {left}"))
    tokens = [t for t in norm_text(raw).split(" ") if t]
    if len(tokens) >= 3:
        variants.add(" ".join(tokens[:2]))
        variants.add(" ".join(tokens[-2:]))
    return [v for v in variants if v]


def scan_policy_paths(roots):
    by_policy = defaultdict(list)
    paths = []
    if not roots:
        return by_policy, paths
    for root in roots:
        base = Path(root).expanduser()
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in VALID_EXTS:
                continue
            rel = str(path.relative_to(base))
            normalized = norm_text(rel)
            paths.append((str(path), normalized))
            raw_tokens = re.findall(r"[A-Z0-9]{6,}", re.sub(r"[^A-Za-z0-9]+", " ", rel.upper()))
            for token in raw_tokens:
                pol = norm_policy(token)
                if len(pol) >= 6:
                    by_policy[pol].append((str(path), normalized))
    return by_policy, paths


def choose_unique(candidates):
    uniq = sorted({c for c in candidates if c})
    return uniq[0] if len(uniq) == 1 else ""


def main():
    parser = argparse.ArgumentParser(description="Relink seguros rows without cliente_id.")
    parser.add_argument("--db", required=True, help="SQLite database path.")
    parser.add_argument("--empresa-id", default="", help="Filter by empresa_id.")
    parser.add_argument("--empresa-nombre-like", default="", help="Resolve empresa_id by company name LIKE.")
    parser.add_argument(
        "--polizas-root",
        action="append",
        default=[],
        help="Optional folder with policy files for extra matching. Repeat flag for multiple roots.",
    )
    parser.add_argument("--create-missing", action="store_true", help="Create customer if no unique match found.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run).")
    parser.add_argument("--limit", type=int, default=0, help="Limit rows to process.")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    empresa_id = args.empresa_id
    if not empresa_id and args.empresa_nombre_like:
        row = conn.execute(
            "SELECT id FROM empresas WHERE UPPER(nombre) LIKE UPPER(?) ORDER BY nombre LIMIT 1",
            (f"%{args.empresa_nombre_like}%",),
        ).fetchone()
        if row:
            empresa_id = row["id"]

    where = ["(cliente_id IS NULL OR TRIM(cliente_id) = '')"]
    values = []
    if empresa_id:
        where.append("empresa_id = ?")
        values.append(empresa_id)
    limit_sql = f"LIMIT {args.limit}" if args.limit and args.limit > 0 else ""
    seguros = conn.execute(
        f"""
        SELECT id, empresa_id, cliente_id, tomador, compania, poliza_numero
        FROM seguros
        WHERE {' AND '.join(where)}
        ORDER BY id
        {limit_sql}
        """,
        values,
    ).fetchall()

    clientes = conn.execute(
        "SELECT id, nombre FROM clientes"
    ).fetchall()
    cliente_by_name = defaultdict(list)
    for c in clientes:
        for variant in split_name_variants(c["nombre"]):
            cliente_by_name[variant].append(c["id"])

    # Existing seguros already linked: use as strong hints.
    where_linked = ["cliente_id IS NOT NULL", "TRIM(cliente_id) != ''"]
    linked_values = []
    if empresa_id:
        where_linked.append("empresa_id = ?")
        linked_values.append(empresa_id)
    linked = conn.execute(
        f"""
        SELECT cliente_id, tomador, compania, poliza_numero
        FROM seguros
        WHERE {' AND '.join(where_linked)}
        """
        ,
        linked_values,
    ).fetchall()
    by_policy_company = defaultdict(set)
    by_tomador = defaultdict(set)
    for row in linked:
        client = row["cliente_id"]
        pol = norm_policy(row["poliza_numero"])
        comp = norm_company(row["compania"])
        if pol and comp:
            by_policy_company[(pol, comp)].add(client)
        for variant in split_name_variants(row["tomador"]):
            by_tomador[variant].add(client)

    file_by_policy, normalized_paths = scan_policy_paths(args.polizas_root)

    updates = []
    created = []
    unresolved = []
    reasons = defaultdict(int)

    for row in seguros:
        seguro_id = row["id"]
        tomador = row["tomador"] or ""
        comp = row["compania"] or ""
        poliza = row["poliza_numero"] or ""
        tomador_variants = split_name_variants(tomador)
        pol_norm = norm_policy(poliza)
        comp_norm = norm_company(comp)
        cliente_id = ""
        reason = ""

        # 1) Strongest: policy + company from already linked seguros.
        if pol_norm and comp_norm:
            cliente_id = choose_unique(by_policy_company.get((pol_norm, comp_norm), []))
            if cliente_id:
                reason = "policy+company"

        # 2) Name exact against clientes.
        if not cliente_id:
            candidate_ids = []
            for variant in tomador_variants:
                candidate_ids.extend(cliente_by_name.get(variant, []))
            cliente_id = choose_unique(candidate_ids)
            if cliente_id:
                reason = "tomador->clientes"

        # 3) Name from already linked seguros.
        if not cliente_id:
            candidate_ids = []
            for variant in tomador_variants:
                candidate_ids.extend(by_tomador.get(variant, []))
            cliente_id = choose_unique(candidate_ids)
            if cliente_id:
                reason = "tomador->seguros_linked"

        # 4) Optional extra: policy files path contains policy number and exactly one client name.
        if not cliente_id and pol_norm and file_by_policy:
            hits = file_by_policy.get(pol_norm, [])
            path_candidates = set()
            for _path, norm_path in hits:
                for name_key, ids in cliente_by_name.items():
                    if name_key and len(name_key) >= 8 and name_key in norm_path:
                        path_candidates.update(ids)
            cliente_id = choose_unique(path_candidates)
            if cliente_id:
                reason = "policy_path+name"

        # 5) Optional create new customer.
        if not cliente_id and args.create_missing and tomador_variants:
            primary_name = tomador.strip()
            if primary_name:
                new_id = os.urandom(16).hex()
                conn.execute(
                    """
                    INSERT INTO clientes (id, nombre, estado, created_at, updated_at)
                    VALUES (?, ?, 'Activo', datetime('now'), datetime('now'))
                    """,
                    (new_id, primary_name),
                )
                cliente_id = new_id
                created.append((new_id, primary_name))
                reason = "created_cliente"
                for variant in tomador_variants:
                    cliente_by_name[variant].append(new_id)

        if not cliente_id:
            unresolved.append((seguro_id, tomador, comp, poliza))
            reasons["unresolved"] += 1
            continue

        updates.append((cliente_id, seguro_id, row["empresa_id"]))
        reasons[reason] += 1

    # Apply updates + link service.
    if args.apply:
        for cliente_id, seguro_id, row_empresa_id in updates:
            conn.execute(
                "UPDATE seguros SET cliente_id = ?, updated_at = datetime('now') WHERE id = ?",
                (cliente_id, seguro_id),
            )
            if row_empresa_id:
                exists = conn.execute(
                    """
                    SELECT id FROM clientes_empresas
                    WHERE cliente_id = ? AND empresa_id = ? AND LOWER(servicio) = 'seguros'
                    LIMIT 1
                    """,
                    (cliente_id, row_empresa_id),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """
                        INSERT INTO clientes_empresas (
                          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
                        ) VALUES (
                          ?, ?, ?, 'seguros', 'Activo', NULL, NULL, datetime('now'), datetime('now')
                        )
                        """,
                        (os.urandom(16).hex(), cliente_id, row_empresa_id),
                    )
        conn.commit()

    print(f"db={args.db}")
    print(f"empresa_id={empresa_id or '(all)'}")
    print(f"rows_without_cliente_id={len(seguros)}")
    print(f"policy_files_scanned={len(normalized_paths)}")
    print(f"matched={len(updates)}")
    print(f"created_clientes={len(created)}")
    print(f"unresolved={len(unresolved)}")
    for k in sorted(reasons):
        print(f"  {k}: {reasons[k]}")

    if unresolved:
        print("\nTop unresolved (up to 20):")
        for seguro_id, tomador, comp, poliza in unresolved[:20]:
            print(f"- {seguro_id} | {tomador} | {comp} | {poliza}")

    conn.close()


if __name__ == "__main__":
    main()
