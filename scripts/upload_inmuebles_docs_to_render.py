#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import open_db_conn, is_postgres_enabled  # type: ignore

SSH_OPTIONS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UpdateHostKeys=no",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=4",
]


def split_pipe(value: object) -> list[str]:
    return [chunk.strip() for chunk in str(value or "").split("|") if chunk.strip()]


def gather_doc_paths(row: dict) -> list[str]:
    paths: list[str] = []
    for key in (
        "doc_nota_encargo_path",
        "doc_propuesta_path",
        "doc_escritura_path",
        "doc_nota_simple_path",
    ):
        val = str(row.get(key) or "").strip()
        if val:
            paths.append(val)
    for val in split_pipe(row.get("doc_partes_visita_paths")):
        paths.append(val)
    # Dedup conservando orden.
    out: list[str] = []
    seen = set()
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sube documentación (PDF/DOCX/imagenes) de compraventas históricas a Render (carpeta /var/data/uploads)."
    )
    parser.add_argument("--db", default="data/erp_import2_2020_offline.sqlite", help="SQLite local (fuente de rutas doc_*).")
    parser.add_argument("--company", required=True, help="Empresa (nombre exacto).")
    parser.add_argument("--local-root", type=Path, required=True, help="Raíz local que contiene las rutas relativas guardadas en BD (p.ej. /tmp/inmuebles_vendidos_offline).")
    parser.add_argument("--year-from", type=int, default=0, help="Filtra desde año inclusive.")
    parser.add_argument("--year-to", type=int, default=0, help="Filtra hasta año inclusive.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render (p.ej. render@srv-xxx@ssh.frankfurt.render.com o el alias que uses).")
    parser.add_argument("--ssh-port", type=int, default=int(os.environ.get("RENDER_SSH_PORT", "10022") or 10022), help="Puerto SSH (Render suele usar 10022).")
    parser.add_argument("--render-dest", default="/var/data/uploads/inmuebles_vendidos", help="Destino en Render (por defecto bajo UPLOADS).")
    parser.add_argument("--apply", action="store_true", help="Ejecuta la subida. Sin esto, solo previsualiza.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    local_root = args.local_root.expanduser().resolve()
    if not is_postgres_enabled() and not db_path.exists():
        raise SystemExit(f"No existe SQLite: {db_path}")
    if not local_root.exists():
        raise SystemExit(f"No existe local-root: {local_root}")

    conn = open_db_conn(str(db_path), with_row_factory=True)
    try:
        empresa = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (args.company,)).fetchone()
        if not empresa:
            backend = "Postgres" if is_postgres_enabled() else "SQLite"
            raise SystemExit(f"Empresa no encontrada en {backend}: {args.company!r}")
        empresa_id = str(empresa["id"])

        where = ["empresa_id = ?", "LOWER(COALESCE(tipo_operacion, 'venta')) = 'venta'"]
        values: list[object] = [empresa_id]
        if args.year_from:
            where.append("COALESCE(anio, 0) >= ?")
            values.append(args.year_from)
        if args.year_to:
            where.append("COALESCE(anio, 0) <= ?")
            values.append(args.year_to)
        where_sql = " AND ".join(where)

        rows = conn.execute(
            f"""
            SELECT id, anio, direccion,
                   doc_nota_encargo_path, doc_propuesta_path, doc_escritura_path, doc_nota_simple_path, doc_partes_visita_paths
            FROM operaciones_inmobiliarias
            WHERE {where_sql}
            ORDER BY COALESCE(updated_at, created_at) DESC
            """,
            values,
        ).fetchall()
        doc_rel_paths: list[str] = []
        for raw in rows:
            row = dict(raw)
            for rel in gather_doc_paths(row):
                # Si ya es un /uploads/... lo consideramos ya “publicado”.
                if rel.startswith("/uploads/"):
                    continue
                doc_rel_paths.append(rel.lstrip("/"))

        # Dedup.
        unique_rel: list[str] = []
        seen = set()
        for rel in doc_rel_paths:
            if rel in seen:
                continue
            seen.add(rel)
            unique_rel.append(rel)

        missing: list[str] = []
        total_bytes = 0
        for rel in unique_rel:
            src = local_root / rel
            if not src.exists() or not src.is_file():
                missing.append(rel)
                continue
            try:
                total_bytes += src.stat().st_size
            except Exception:
                pass

        print(
            {
                "company": args.company,
                "db": str(db_path),
                "local_root": str(local_root),
                "render_dest": args.render_dest,
                "ops": len(rows),
                "files": len(unique_rel),
                "missing_files": len(missing),
                "total_mb": round(total_bytes / (1024 * 1024), 2),
                "apply": bool(args.apply),
            }
        )
        if missing:
            print("Faltan archivos (primeros 20):")
            for rel in missing[:20]:
                print(f"- {rel}")
            if not args.apply:
                return 0

        if not args.apply:
            return 0

        # Prepara lista para tar (-T).
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            list_path = Path(tmp.name)
            for rel in unique_rel:
                if rel in missing:
                    continue
                tmp.write(rel + "\n")

        try:
            remote_cmd = f"mkdir -p {sh_quote(args.render_dest)} && tar -xf - -C {sh_quote(args.render_dest)}"
            ssh_cmd = ["ssh", *SSH_OPTIONS]
            if args.ssh_port:
                ssh_cmd.extend(["-p", str(args.ssh_port)])
            ssh_cmd.extend([args.render_host, remote_cmd])
            tar_cmd = ["tar", "-cf", "-", "-C", str(local_root), "-T", str(list_path)]
            print("Subiendo (tar | ssh)…")
            tar_proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ssh_proc = subprocess.Popen(ssh_cmd, stdin=tar_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert tar_proc.stdout is not None
            tar_proc.stdout.close()
            ssh_out, ssh_err = ssh_proc.communicate()
            tar_err = tar_proc.stderr.read() if tar_proc.stderr else b""
            tar_code = tar_proc.wait()
            if tar_code != 0:
                raise SystemExit(f"tar falló (code {tar_code}): {tar_err.decode('utf-8', errors='replace')[:800]}")
            if ssh_proc.returncode != 0:
                raise SystemExit(f"ssh falló (code {ssh_proc.returncode}): {ssh_err.decode('utf-8', errors='replace')[:800]}")
            if ssh_out:
                sys.stdout.write(ssh_out.decode("utf-8", errors="replace"))
            print("OK: documentación subida.")
            return 0
        finally:
            try:
                list_path.unlink()
            except Exception:
                pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def sh_quote(value: str) -> str:
    # quoting mínimo para comandos remotos.
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
