#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web.server import canonicalize_ramo


def main():
    parser = argparse.ArgumentParser(description="Normaliza ramos de seguros a catálogo canónico.")
    parser.add_argument("--db", required=True, help="Ruta SQLite")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios (por defecto dry-run)")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT id, COALESCE(ramo,'') AS ramo FROM seguros").fetchall()
    changes = []
    before = Counter()
    after = Counter()
    for row in rows:
        current = (row["ramo"] or "").strip()
        normalized = canonicalize_ramo(current).strip()
        before[current] += 1
        after[normalized] += 1
        if normalized != current:
            changes.append((normalized, row["id"], current))

    print(f"total_rows={len(rows)}")
    print(f"distinct_before={len(before)}")
    print(f"distinct_after={len(after)}")
    print(f"rows_to_update={len(changes)}")

    if changes:
        print("\nMuestras de cambio:")
        for new_ramo, _id, old_ramo in changes[:30]:
            print(f"- {old_ramo!r} -> {new_ramo!r}")

    if args.apply and changes:
        conn.executemany("UPDATE seguros SET ramo = ?, updated_at = datetime('now') WHERE id = ?", [(n, i) for n, i, _ in changes])
        conn.commit()
        print("\nCambios aplicados.")
    elif not args.apply:
        print("\nDry-run: no se aplicaron cambios.")


if __name__ == "__main__":
    main()
