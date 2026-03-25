import sqlite3
from pathlib import Path


def apply_schema_file(conn, schema_path):
    path = Path(schema_path)
    if not path.exists():
        return False
    conn.executescript(path.read_text(encoding="utf-8"))
    return True


def table_columns(conn, table_name):
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except sqlite3.Error:
        return set()


def ensure_column(conn, table_name, column_name, column_sql):
    if column_name in table_columns(conn, table_name):
        return False
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
    return True
