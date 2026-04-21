#!/usr/bin/env python3
"""
Para los documentos de Renta que siguen en el cliente "SIN ASIGNAR", intenta:
  1) Detectar el "nombre de cliente" a partir de la RUTA local (carpetas de OneDrive)
  2) Si existe un cliente parecido en `clientes` (misma empresa), asigna el doc a ese cliente
  3) Si NO existe, crea el cliente mínimo (id, empresa_id, nombre, created_at, updated_at) y asigna el doc

Motivación: muchos PDFs auxiliares (datos fiscales, contratos, anotaciones, etc.) NO contienen NIF/NIE,
pero están organizados por carpetas con el nombre del cliente. En estos casos, la única forma de que
“cuadre” es crear/usar el cliente y vincular los docs.

Uso:
  set -a; source .env; set +a
  python3 scripts/assign_rentas_docs_create_clients.py --empresa-id <empresa_id> --dry-run
  python3 scripts/assign_rentas_docs_create_clients.py --empresa-id <empresa_id> --apply
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

ANCHORS = {
    "1 RENTAS HECHAS",
    "RENTAS HECHAS",
    "PRESENTADAS",
    "NO PRESENTADAS",
    "NO_PRESENTADAS",
    "PENDIENTES",
}

GENERIC_DIRS = {
    "DNI",
    "DATOS  FISCALES",
    "DATOS FISCALES",
    "DATOS_FISCALES",
    "RESUMEN COMPARATIVO",
    "RESUMEN_COMPARATIVO",
    "DOCUMENTOS OTRO TITULAR",
    "DOCUMENTOS_OTRO_TITULAR",
    "OTRO TITULAR",
    "OTRO_TITULAR",
    "HIJO",
    "HIJA",
    "HIJOS",
    "OTROS",
}

SKIP_CLIENT_NAMES = {"RENTAS 2024 · SIN ASIGNAR", "SIN ASIGNAR", "RENTAS 2024 SIN ASIGNAR"}
SKIP_CANDIDATE_PATTERNS = {
    "0000 RENTAS 2024",
    "RENTAS 2024",
    "RENTAS FINCAS VELAZQUEZ 2023",
}

NIF_RE = re.compile(r"\b(\d{8}[A-Z])\b")
NIE_RE = re.compile(r"\b([XYZ]\d{7}[A-Z])\b")


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


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def norm(value: object) -> str:
    text = compact_spaces(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().upper()


ANCHORS_NORM = {norm(a) for a in ANCHORS}


def tokenize_name(raw: object) -> set[str]:
    text = norm(raw)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    tokens = {t for t in text.split() if t and t not in STOP_TOKENS and len(t) >= 2}
    return tokens


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    union = len(a | b)
    return inter / union if union else 0.0


def normalize_nif(value: object) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^0-9A-Z]", "", text)
    return text


def extract_nif_from_text(text: str) -> str:
    raw = normalize_nif(text)
    if not raw:
        return ""
    m = NIF_RE.search(raw)
    if m:
        return m.group(1)
    m = NIE_RE.search(raw)
    if m:
        return m.group(1)
    return ""


def is_generic_dir(name: str) -> bool:
    n = norm(name)
    if not n:
        return True
    if n in {norm(x) for x in SKIP_CANDIDATE_PATTERNS}:
        return True
    if n in {norm(x) for x in GENERIC_DIRS}:
        return True
    if n in {"USERS", "LIBRARY", "CLOUDSTORAGE", "ONEDRIVE-TERESARAMOSRUEDA"}:
        return True
    return False


def clean_candidate_name(raw: str) -> str:
    s = compact_spaces(raw).replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # elimina números largos (teléfonos/ids)
    s = re.sub(r"\b\d{6,}\b", " ", s)
    # etiquetas frecuentes (no son parte del nombre)
    s = re.sub(
        r"\b(BORRADOR|NO OBLIGAD[OA]S?|NO OBLIGAD[OA]|NO SE HACE|NO LA HACE|NO PRESENTAD[OA]S?)\b",
        " ",
        norm(s),
        flags=re.IGNORECASE,
    )
    s = compact_spaces(s.title())
    return s


def guess_cliente_name_from_doc(notas: str, nombre: str) -> tuple[str, str]:
    """
    Devuelve el candidato más probable a nombre de cliente:
    - si está bajo ".../1 RENTAS HECHAS/<cliente>/..." => <cliente>
    - si está bajo ".../PRESENTADAS/<cliente>/..." => <cliente>
    - si está en "DATOS FISCALES" o "RESUMEN COMPARATIVO" => usa el stem del PDF
    - fallback: padre directo del PDF
    """
    path = Path(str(notas or "")).expanduser()
    parts = [p for p in path.parts if p]
    parts_norm = [norm(p) for p in parts]

    for i, pn in enumerate(parts_norm):
        if pn in ANCHORS_NORM and i + 1 < len(parts):
            cand = parts[i + 1]
            if cand and not is_generic_dir(cand):
                return clean_candidate_name(cand), "anchor"

    # si hay "DOCUMENTOS OTRO TITULAR", usa el folder anterior
    for i, pn in enumerate(parts_norm):
        if pn in {"DOCUMENTOS OTRO TITULAR", "DOCUMENTOS_OTRO_TITULAR", "OTRO TITULAR", "OTRO_TITULAR"} and i - 1 >= 0:
            cand = parts[i - 1]
            if cand and not is_generic_dir(cand):
                return clean_candidate_name(cand), "other_titular"

    # carpetas genéricas: usa el nombre del archivo (stem)
    try:
        if any(pn in {norm("DATOS FISCALES"), norm("DATOS  FISCALES")} for pn in parts_norm):
            return clean_candidate_name(path.stem), "datos_fiscales_filename"
        if any(pn in {norm("RESUMEN COMPARATIVO")} for pn in parts_norm):
            return clean_candidate_name(path.stem), "resumen_filename"
    except Exception:
        pass

    # fallback: padre
    try:
        parent = path.parent.name
        if parent and not is_generic_dir(parent):
            return clean_candidate_name(parent), "parent"
    except Exception:
        pass

    # fallback final: tail del nombre mostrado en CRM
    raw = str(nombre or "").strip()
    if "·" in raw:
        tail = raw.split("·")[-1].strip()
    else:
        tail = raw
    try:
        return clean_candidate_name(Path(tail).stem or tail), "crm_name"
    except Exception:
        return clean_candidate_name(tail), "crm_name"


@dataclass(frozen=True)
class Client:
    id: str
    nombre: str
    nif: str
    tokens: frozenset[str]


def fetch_clients(conn, empresa_id: str) -> list[Client]:
    with conn.cursor() as cur:
        rows = cur.execute(
            "SELECT id, nombre, nif FROM clientes WHERE empresa_id = %s",
            (empresa_id,),
        ).fetchall()
    out: list[Client] = []
    for r in rows:
        name = compact_spaces(r.get("nombre") or "")
        toks = tokenize_name(name)
        out.append(Client(id=str(r["id"]), nombre=name, nif=str(r.get("nif") or ""), tokens=frozenset(toks)))
    return out


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea clientes faltantes y asigna docs de renta desde SIN ASIGNAR.")
    parser.add_argument("--empresa-id", required=True)
    parser.add_argument("--unassigned-client-name", default="RENTAS 2024 · SIN ASIGNAR")
    parser.add_argument("--min-score", type=float, default=0.70, help="Score mínimo para reutilizar un cliente existente.")
    parser.add_argument(
        "--allow-create-sources",
        default="anchor,other_titular",
        help="Fuentes desde las que se permite crear clientes nuevos (csv: anchor,other_titular,parent,datos_fiscales_filename,resumen_filename,crm_name).",
    )
    parser.add_argument("--max-print", type=int, default=60, help="En dry-run, máximo de líneas a imprimir.")
    parser.add_argument("--limit", type=int, default=0)
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
        # Cliente SIN ASIGNAR
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

        clients = fetch_clients(conn, args.empresa_id)
        inv = build_inverted_index(clients)

        with conn.cursor() as cur:
            docs = cur.execute(
                """
                SELECT id, nombre, notas
                FROM gestoria_docs
                WHERE empresa_id = %s
                  AND cliente_id = %s
                  AND LOWER(COALESCE(referencia_tipo,''))='renta'
                ORDER BY updated_at DESC
                """,
                (args.empresa_id, unassigned_id),
            ).fetchall()
        if args.limit and int(args.limit) > 0:
            docs = docs[: int(args.limit)]

        processed = 0
        assigned_existing = 0
        created_clients = 0
        assigned_new = 0
        skipped = 0
        simulated_created: dict[str, str] = {}
        allow_create = {s.strip().lower() for s in str(args.allow_create_sources or "").split(",") if s.strip()}
        printed = 0

        for d in docs:
            processed += 1
            doc_id = str(d.get("id") or "").strip()
            doc_nombre = str(d.get("nombre") or "").strip()
            doc_notas = str(d.get("notas") or "").strip()

            candidate, source = guess_cliente_name_from_doc(doc_notas, doc_nombre)
            if not candidate or norm(candidate) in {norm(x) for x in SKIP_CLIENT_NAMES}:
                skipped += 1
                continue
            if norm(candidate) in {norm(x) for x in SKIP_CANDIDATE_PATTERNS}:
                skipped += 1
                continue
            cand_tokens = tokenize_name(candidate)
            if len(cand_tokens) < 2 and all(len(t) < 4 for t in cand_tokens):
                skipped += 1
                continue

            cand_key = norm(candidate)
            if args.dry_run and cand_key in simulated_created:
                target_id = simulated_created[cand_key]
                if printed < int(args.max_print or 0):
                    print(f"[dry-run] {doc_id} reuse(sim) cand='{candidate}' -> {target_id} | {doc_notas}")
                    printed += 1
                assigned_new += 1
                continue

            existing, score = best_match(cand_tokens, clients, inv)
            target_id = ""
            created = False

            if existing and float(score) >= float(args.min_score or 0.0) and norm(existing.nombre) not in {
                norm(args.unassigned_client_name)
            }:
                target_id = existing.id
            else:
                if source.lower() not in allow_create:
                    skipped += 1
                    continue
                target_id = uuid.uuid4().hex
                created = True

            if args.dry_run:
                action = "reuse" if not created else "create"
                if printed < int(args.max_print or 0):
                    print(
                        f"[dry-run] {doc_id} {action} source={source} score={score:.3f} cand='{candidate}' -> {target_id} | {doc_notas}"
                    )
                    printed += 1
                if created:
                    simulated_created[cand_key] = target_id
                    created_clients += 1
                    assigned_new += 1
                else:
                    assigned_existing += 1
                continue

            with conn.cursor() as cur:
                if created:
                    nif_guess = extract_nif_from_text(candidate) or extract_nif_from_text(doc_notas) or ""
                    cur.execute(
                        """
                        INSERT INTO clientes (id, empresa_id, nombre, nif, estado, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                        """,
                        (target_id, args.empresa_id, candidate, nif_guess, "Activo"),
                    )
                    clients.append(
                        Client(id=target_id, nombre=candidate, nif=nif_guess, tokens=frozenset(tokenize_name(candidate)))
                    )
                    inv = build_inverted_index(clients)
                    created_clients += 1

                # Asegura vínculo para que aparezca en módulos de gestoría.
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
                        target_id,
                        args.empresa_id,
                        "gestoria",
                        "Activo",
                        "",
                        "",
                        target_id,
                        args.empresa_id,
                    ),
                )

                cur.execute(
                    """
                    UPDATE gestoria_docs
                    SET cliente_id = %s, updated_at = NOW()
                    WHERE id = %s AND empresa_id = %s
                    """,
                    (target_id, doc_id, args.empresa_id),
                )

            if created:
                assigned_new += 1
            else:
                assigned_existing += 1

        if do_apply:
            conn.commit()

        print(
            {
                "processed": processed,
                "assigned_existing": assigned_existing,
                "created_clients": created_clients,
                "assigned_new": assigned_new,
                "skipped": skipped,
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
