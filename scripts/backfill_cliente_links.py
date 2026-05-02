#!/usr/bin/env python3
import argparse
import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def normalize_lookup_text(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


STOPWORDS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "DA", "DO", "DOS"}


def name_tokens(value: str) -> List[str]:
    key = normalize_lookup_text(value or "")
    if not key:
        return []
    return [t for t in key.split(" ") if len(t) > 2 and t not in STOPWORDS]


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cols: List[str] = []
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        cols.append(str(row[1]))
    return cols


def ensure_column(conn: sqlite3.Connection, table: str, col_name: str, col_sql: str) -> None:
    if col_name in set(table_columns(conn, table)):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_sql}")


def now_sql() -> str:
    return "datetime('now','localtime')"


def ensure_client_link(conn: sqlite3.Connection, *, cliente_id: str, empresa_id: str, servicio: str) -> None:
    if not table_exists(conn, "clientes_empresas"):
        return
    existing = conn.execute(
        """
        SELECT 1
        FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(COALESCE(servicio,'')) = LOWER(?)
        LIMIT 1
        """,
        (cliente_id, empresa_id, servicio),
    ).fetchone()
    if existing:
        return
    conn.execute(
        f"""
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (
          lower(hex(randomblob(16))), ?, ?, ?, 'Activo', NULL, NULL, {now_sql()}, {now_sql()}
        )
        """,
        (cliente_id, empresa_id, servicio),
    )


@dataclass
class ClientIndex:
    by_name_key: Dict[str, str]
    by_tokens: List[Tuple[str, List[str]]]


def build_client_index(conn: sqlite3.Connection) -> ClientIndex:
    by_name_key: Dict[str, str] = {}
    by_tokens: List[Tuple[str, List[str]]] = []
    if not table_exists(conn, "clientes"):
        return ClientIndex(by_name_key=by_name_key, by_tokens=by_tokens)
    rows = conn.execute("SELECT id, nombre FROM clientes").fetchall()
    for cid, nombre in rows:
        cid = str(cid or "").strip()
        if not cid:
            continue
        nombre = str(nombre or "").strip()
        if nombre:
            key = normalize_lookup_text(nombre)
            if key and key not in by_name_key:
                by_name_key[key] = cid
            if "," in nombre:
                parts = [p.strip() for p in nombre.split(",", 1)]
                if len(parts) == 2 and parts[0] and parts[1]:
                    key2 = normalize_lookup_text(f"{parts[1]} {parts[0]}")
                    if key2 and key2 not in by_name_key:
                        by_name_key[key2] = cid
        toks = name_tokens(nombre)
        if toks:
            by_tokens.append((cid, toks))
    return ClientIndex(by_name_key=by_name_key, by_tokens=by_tokens)


def best_client_match(index: ClientIndex, name: str) -> str:
    toks = name_tokens(name)
    if len(toks) < 2:
        return ""
    best_id = ""
    best = 0.0
    second = 0.0
    for cid, ctoks in index.by_tokens:
        s = jaccard(toks, ctoks)
        if s > best:
            second = best
            best = s
            best_id = cid
        elif s > second:
            second = s
    # Conservative: only take a match if it's clearly better.
    if best >= 0.90 and (best - second) >= 0.05:
        return best_id
    return ""


def create_cliente(conn: sqlite3.Connection, *, empresa_id: str, nombre: str, estado: str) -> str:
    cliente_id = conn.execute("SELECT lower(hex(randomblob(16)))").fetchone()[0]
    conn.execute(
        f"""
        INSERT INTO clientes (id, empresa_id, nombre, estado, created_at, updated_at)
        VALUES (?, NULLIF(TRIM(?), ''), ?, ?, {now_sql()}, {now_sql()})
        """,
        (cliente_id, empresa_id, nombre, estado),
    )
    return str(cliente_id)


@dataclass
class Stats:
    total: int = 0
    linked_existing: int = 0
    created_new: int = 0


def backfill_seguros(conn: sqlite3.Connection, *, dry_run: bool) -> Stats:
    stats = Stats()
    if not table_exists(conn, "seguros") or not table_exists(conn, "clientes"):
        return stats
    index = build_client_index(conn)
    rows = conn.execute(
        "SELECT id, empresa_id, tomador FROM seguros WHERE COALESCE(TRIM(cliente_id), '') = ''"
    ).fetchall()
    stats.total = len(rows)
    for seguro_id, empresa_id, tomador in rows:
        seguro_id = str(seguro_id or "").strip()
        empresa_id = str(empresa_id or "").strip()
        tomador = str(tomador or "").strip()
        if not seguro_id or not tomador:
            continue
        key = normalize_lookup_text(tomador)
        cliente_id = index.by_name_key.get(key, "") or best_client_match(index, tomador)
        created = False
        if not cliente_id:
            created = True
            if dry_run:
                continue
            cliente_id = create_cliente(conn, empresa_id=empresa_id, nombre=tomador, estado="Activo")
            index.by_name_key[normalize_lookup_text(tomador)] = cliente_id
            toks = name_tokens(tomador)
            if toks:
                index.by_tokens.append((cliente_id, toks))
        if dry_run:
            continue
        conn.execute(
            f"UPDATE seguros SET cliente_id = ?, updated_at = {now_sql()} WHERE id = ?",
            (cliente_id, seguro_id),
        )
        ensure_client_link(conn, cliente_id=cliente_id, empresa_id=empresa_id, servicio="seguros")
        if created:
            stats.created_new += 1
        else:
            stats.linked_existing += 1
    return stats


def backfill_hipotecas(conn: sqlite3.Connection, *, dry_run: bool) -> Stats:
    stats = Stats()
    if not table_exists(conn, "hipotecas") or not table_exists(conn, "clientes"):
        return stats
    index = build_client_index(conn)
    rows = conn.execute(
        "SELECT id, empresa_id, cliente FROM hipotecas WHERE COALESCE(TRIM(cliente_id), '') = ''"
    ).fetchall()
    stats.total = len(rows)
    for hip_id, empresa_id, cliente_txt in rows:
        hip_id = str(hip_id or "").strip()
        empresa_id = str(empresa_id or "").strip()
        cliente_txt = str(cliente_txt or "").strip()
        if not hip_id or not cliente_txt:
            continue
        primary_name = cliente_txt.split("/")[0].strip()
        if not primary_name:
            continue
        key = normalize_lookup_text(primary_name)
        cliente_id = index.by_name_key.get(key, "") or best_client_match(index, primary_name)
        created = False
        if not cliente_id:
            created = True
            if dry_run:
                continue
            cliente_id = create_cliente(conn, empresa_id=empresa_id, nombre=primary_name, estado="Activo")
            index.by_name_key[normalize_lookup_text(primary_name)] = cliente_id
            toks = name_tokens(primary_name)
            if toks:
                index.by_tokens.append((cliente_id, toks))
        if dry_run:
            continue
        conn.execute(
            f"UPDATE hipotecas SET cliente_id = ?, updated_at = {now_sql()} WHERE id = ?",
            (cliente_id, hip_id),
        )
        ensure_client_link(conn, cliente_id=cliente_id, empresa_id=empresa_id, servicio="financiaciones")
        if created:
            stats.created_new += 1
        else:
            stats.linked_existing += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de cliente_id y vínculos cliente↔servicio.")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[1] / "data" / "erp_import2.sqlite"),
        help="Ruta a sqlite (por defecto data/erp_import2.sqlite).",
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribe cambios (solo calcula).")
    parser.add_argument(
        "--backup-dir",
        default=str(Path(__file__).resolve().parents[1] / "_scratch" / "db_backups"),
        help="Carpeta donde guardar backup antes de modificar.",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"DB no encontrada: {db_path}")

    if not args.dry_run:
        backup_dir = Path(args.backup_dir).expanduser().resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{db_path.name}.bak_{stamp}"
        shutil.copy2(db_path, backup_path)
        print(f"Backup creado: {backup_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Ensure new columns exist (safe no-op if already present)
        try:
            ensure_column(conn, "clientes", "captado_por_user_id", "captado_por_user_id TEXT")
        except Exception:
            pass
        try:
            ensure_column(conn, "clientes_empresas", "captado_por_user_id", "captado_por_user_id TEXT")
        except Exception:
            pass

        s = backfill_seguros(conn, dry_run=args.dry_run)
        h = backfill_hipotecas(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()

        print("\nResultados")
        print(f"- Seguros sin cliente_id: {s.total}")
        print(f"  - enlazados a cliente existente: {s.linked_existing}")
        print(f"  - clientes nuevos creados: {s.created_new}")
        print(f"- Hipotecas sin cliente_id: {h.total}")
        print(f"  - enlazadas a cliente existente: {h.linked_existing}")
        print(f"  - clientes nuevos creados: {h.created_new}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

