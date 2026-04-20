#!/usr/bin/env python3
"""
Re-asigna documentos de Renta (gestoria_docs) desde el cliente "SIN ASIGNAR" al cliente real,
usando señal de la RUTA local guardada en `gestoria_docs.notas` (carpetas tipo
`.../1 RENTAS HECHAS/<CLIENTE>/...` o `.../PRESENTADAS/<CLIENTE>/...`), y como fallback el
nombre del PDF.

Esto sirve cuando los PDFs NO contienen NIF/NIE (o son documentos auxiliares), pero están
organizados por carpetas en OneDrive.

Uso:
  set -a; source .env; set +a
  python3 scripts/assign_rentas_docs_by_path.py --empresa-id <empresa_id> --apply

Primero probar:
  python3 scripts/assign_rentas_docs_by_path.py --empresa-id <empresa_id> --dry-run --limit 50
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path


STOP_TOKENS = {
    "DE",
    "DEL",
    "LA",
    "LAS",
    "LO",
    "LOS",
    "Y",
    "E",
    "DA",
    "DO",
    "DOS",
    "SAN",
    "SANTA",
}

COMMON_GIVEN_NAMES = {
    "MARIA",
    "JOSE",
    "JUAN",
    "CARLOS",
    "ANA",
    "CARMEN",
    "DOLORES",
    "FRANCISCO",
    "JAVIER",
    "LUCIA",
    "INMACULADA",
    "ASUNCION",
    "ASUNCIÓN",
    "M",
}


GENERIC_DIRS = {
    "DNI",
    "DATOS FISCALES",
    "DATOS_FISCALES",
    "RESUMEN COMPARATIVO",
    "RESUMEN_COMPARATIVO",
    "PRESENTADAS",
    "NO PRESENTADAS",
    "NO_PRESENTADAS",
    "PENDIENTES",
    "DOCUMENTOS",
    "DOCUMENTACION",
    "DOCUMENTACIÓN",
    "DOCUMENTOS OTRO TITULAR",
    "DOCUMENTOS_OTRO_TITULAR",
    "OTRO TITULAR",
    "OTRO_TITULAR",
    "OTROS",
    "RENTAS",
    "RENTA",
    "RENTA 2024",
    "RENTA_2024",
    "RENTA 2023",
    "RENTA_2023",
}


ANCHORS = {
    "1 RENTAS HECHAS",
    "RENTAS HECHAS",
    "RENTAS  FINCAS  VELAZQUEZ  2023",
    "RENTAS FINCAS VELAZQUEZ 2023",
    "PRESENTADAS",
    "NO PRESENTADAS",
    "NO_PRESENTADAS",
}


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def norm(value: object) -> str:
    text = compact_spaces(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().upper()


ANCHORS_NORM = {norm(a) for a in ANCHORS}


def simplify_filename(stem: str) -> str:
    s = norm(stem)
    s = re.sub(r"\b\d{8}\b", " ", s)  # 28102025
    s = re.sub(r"\b\d{2}[_/-]?\d{2}[_/-]?\d{4}\b", " ", s)
    # Quita códigos tipo M91XHX, N4AH3B, etc. (mezcla letras+NÚMEROS).
    s = re.sub(r"\b(?=[A-Z0-9]{5,}\b)(?=.*\d)[A-Z0-9]+\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize_name(raw: object) -> set[str]:
    text = norm(raw)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    tokens = {t for t in text.split() if t and t not in STOP_TOKENS and len(t) >= 2}
    return tokens


def is_generic_dir(name: str) -> bool:
    n = norm(name)
    if not n:
        return True
    if n in GENERIC_DIRS:
        return True
    # Rutas técnicas o de sistema
    if n in {"USERS", "LIBRARY", "CLOUDSTORAGE", "ONEDRIVE-TERESARAMOSRUEDA"}:
        return True
    return False


def extract_tail_from_doc_nombre(nombre: str) -> str:
    # Formato típico: "Renta 2024 · Pendiente asignar · <archivo.pdf>"
    raw = str(nombre or "").strip()
    if "·" in raw:
        tail = raw.split("·")[-1].strip()
        return tail or raw
    return raw


def candidates_from_path(notas: str) -> list[str]:
    path = Path(str(notas or "")).expanduser()
    parts = [p for p in path.parts if p]
    parts_norm = [norm(p) for p in parts]

    out: list[str] = []

    # Si hay "DOCUMENTOS OTRO TITULAR", el cliente suele ser el folder anterior.
    for i, pn in enumerate(parts_norm):
        if pn in {"DOCUMENTOS OTRO TITULAR", "DOCUMENTOS_OTRO_TITULAR", "OTRO TITULAR", "OTRO_TITULAR"}:
            if i - 1 >= 0 and not is_generic_dir(parts[i - 1]):
                out.append(parts[i - 1])

    # Anclas típicas: el siguiente segmento suele ser el cliente.
    for i, pn in enumerate(parts_norm):
        if pn in ANCHORS_NORM:
            if i + 1 < len(parts) and not is_generic_dir(parts[i + 1]):
                out.append(parts[i + 1])

    # Padre directo (si no es genérico).
    try:
        parent = path.parent.name
        if parent and not is_generic_dir(parent):
            out.append(parent)
    except Exception:
        pass

    # Fallback: filename (stem).
    try:
        stem = path.stem
        if stem:
            out.append(stem)
    except Exception:
        pass

    # Dedup conservando orden.
    seen = set()
    uniq = []
    for c in out:
        key = norm(c)
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def pg_connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise SystemExit(f"Postgres no disponible: falta psycopg. ({type(exc).__name__})")
    return psycopg.connect(dsn, row_factory=dict_row)


@dataclass(frozen=True)
class Client:
    id: str
    nombre: str
    nif: str
    tokens: frozenset[str]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    union = len(a | b)
    return inter / union if union else 0.0


def build_inverted_index(clients: list[Client]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i, c in enumerate(clients):
        for token in c.tokens:
            index.setdefault(token, []).append(i)
    return index


def best_match(tokens: set[str], clients: list[Client], inv: dict[str, list[int]]) -> tuple[Client | None, float]:
    if not tokens:
        return None, 0.0
    candidates: set[int] = set()
    for t in tokens:
        for idx in inv.get(t, []):
            candidates.add(idx)
    if not candidates:
        return None, 0.0
    best_client: Client | None = None
    best_score = 0.0
    for idx in candidates:
        c = clients[idx]
        score = jaccard(tokens, set(c.tokens))
        if score > best_score:
            best_score = score
            best_client = c
    return best_client, best_score


def overlap_quality(query_tokens: set[str], client_tokens: set[str]) -> tuple[int, int]:
    overlap = query_tokens & client_tokens
    non_common = {t for t in overlap if t not in COMMON_GIVEN_NAMES}
    return len(overlap), len(non_common)


def fetch_clients(conn, empresa_id: str) -> list[Client]:
    with conn.cursor() as cur:
        cols = cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='clientes'
            """
        ).fetchall()
        has_apellidos = any(r["column_name"] == "apellidos" for r in cols)
        has_empresa_id = any(r["column_name"] == "empresa_id" for r in cols)

        select_name = "COALESCE(c.nombre,'')"
        if has_apellidos:
            select_name = "TRIM(COALESCE(c.nombre,'') || ' ' || COALESCE(c.apellidos,''))"

        if has_empresa_id:
            rows = cur.execute(
                f"""
                SELECT c.id, {select_name} AS full_name, c.nif
                FROM clientes c
                WHERE c.empresa_id = %s
                """,
                (empresa_id,),
            ).fetchall()
        else:
            rows = cur.execute(
                f"""
                SELECT DISTINCT c.id, {select_name} AS full_name, c.nif
                FROM clientes c
                JOIN clientes_empresas ce ON ce.cliente_id = c.id
                WHERE ce.empresa_id = %s
                """,
                (empresa_id,),
            ).fetchall()

    out: list[Client] = []
    for r in rows:
        name = compact_spaces(r.get("full_name") or "")
        toks = tokenize_name(name)
        if not toks:
            continue
        out.append(
            Client(
                id=str(r["id"]),
                nombre=name,
                nif=norm(r.get("nif")),
                tokens=frozenset(toks),
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Asigna docs de renta a clientes por ruta (Postgres).")
    parser.add_argument("--empresa-id", required=True)
    parser.add_argument("--unassigned-client-name", default="RENTAS 2024 · SIN ASIGNAR")
    parser.add_argument("--min-score", type=float, default=0.50)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-print", type=int, default=50, help="En dry-run, máximo de líneas a imprimir.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    do_apply = bool(args.apply) and (not args.dry_run)
    if not do_apply:
        args.dry_run = True

    dsn = env_first("POSTGRES_URL", "DATABASE_URL")
    if not dsn.lower().startswith("postgres"):
        raise SystemExit("Falta POSTGRES_URL/DATABASE_URL (postgres...).")

    conn = pg_connect(dsn)
    conn.autocommit = False
    try:
        clients = fetch_clients(conn, args.empresa_id)
        inv = build_inverted_index(clients)
        with conn.cursor() as cur:
            unassigned = cur.execute(
                """
                SELECT id
                FROM clientes
                WHERE empresa_id = %s AND LOWER(COALESCE(nombre,'')) = LOWER(%s)
                LIMIT 1
                """,
                (args.empresa_id, args.unassigned_client_name),
            ).fetchone()
        if not unassigned:
            raise SystemExit("No existe el cliente SIN ASIGNAR para esa empresa.")
        unassigned_id = str(unassigned["id"])

        with conn.cursor() as cur:
            rows = cur.execute(
                """
                SELECT id, nombre, notas
                FROM gestoria_docs
                WHERE empresa_id = %s
                  AND cliente_id = %s
                  AND LOWER(COALESCE(referencia_tipo,'')) = 'renta'
                ORDER BY updated_at DESC
                """,
                (args.empresa_id, unassigned_id),
            ).fetchall()
        docs = list(rows)
        if args.limit and int(args.limit) > 0:
            docs = docs[: int(args.limit)]

        processed = 0
        assigned = 0
        no_match = 0
        low_score = 0
        printed = 0


        for r in docs:
            processed += 1
            doc_id = str(r.get("id") or "").strip()
            doc_nombre = str(r.get("nombre") or "").strip()
            doc_notas = str(r.get("notas") or "").strip()

            best_client = None
            best_score = 0.0
            best_source = ""

            for cand in candidates_from_path(doc_notas) + [extract_tail_from_doc_nombre(doc_nombre)]:
                stem = simplify_filename(str(cand))
                tokens = tokenize_name(stem)
                client, score = best_match(tokens, clients, inv)
                if client and score > best_score:
                    best_client = client
                    best_score = score
                    best_source = str(cand)

            if not best_client:
                no_match += 1
                continue
            if float(best_score) < float(args.min_score or 0.0):
                low_score += 1
                continue

            # Evita falsos positivos por nombres comunes (MARIA/JOSE/ANA...).
            # Si el solapamiento sólo tiene nombres comunes, no auto-asignamos.
            try:
                q_tokens = tokenize_name(simplify_filename(best_source))
                overlap_count, non_common_overlap = overlap_quality(q_tokens, set(best_client.tokens))
                if overlap_count <= 0:
                    low_score += 1
                    continue
                if non_common_overlap <= 0:
                    # Permitimos casos muy claros (score alto) para nombres cortos (p.ej. "ANA").
                    if not (float(best_score) >= 0.85 and len(q_tokens) <= 2):
                        low_score += 1
                        continue
            except Exception:
                pass

            if args.dry_run:
                if printed < int(args.max_print or 0):
                    print(
                        f"[dry-run] {doc_id} -> {best_client.id} ({best_client.nombre}) score={best_score:.3f} via={best_source} | {doc_notas}"
                    )
                    printed += 1
                assigned += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE gestoria_docs
                    SET cliente_id = %s, updated_at = NOW()
                    WHERE id = %s AND empresa_id = %s
                    """,
                    (best_client.id, doc_id, args.empresa_id),
                )
                # Asegura vínculo en clientes_empresas para que sea visible en módulos de gestoría.
                cur.execute(
                    """
                    INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at)
                    SELECT %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    WHERE NOT EXISTS (
                      SELECT 1 FROM clientes_empresas WHERE cliente_id=%s AND empresa_id=%s AND LOWER(COALESCE(servicio,'')) IN ('gestoria','gestoría')
                    )
                    """,
                    (
                        uuid.uuid4().hex,
                        best_client.id,
                        args.empresa_id,
                        "gestoria",
                        "Activo",
                        "",
                        "",
                        best_client.id,
                        args.empresa_id,
                    ),
                )
            assigned += 1

        if do_apply:
            conn.commit()

        print(
            {
                "processed": processed,
                "assigned": assigned,
                "no_match": no_match,
                "low_score": low_score,
                "dry_run": bool(args.dry_run),
                "unassigned_client_id": unassigned_id,
                "min_score": float(args.min_score),
            }
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
