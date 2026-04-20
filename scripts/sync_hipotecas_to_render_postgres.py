#!/usr/bin/env python3
"""
Sincroniza a Render (Postgres) las hipotecas de Financiaciones Modernia creadas en la SQLite local.

Objetivo:
  - Mostrar un resumen de los datos detectados (nif/email/teléfono, inmueble, importes, preferencias).
  - Importar a producción Render (Postgres) por SSH, como se hace con rentas.

Uso:
  python3 scripts/sync_hipotecas_to_render_postgres.py \
    --local-db data/erp_import2.sqlite \
    --render-host srv-xxxx@ssh.frankfurt.render.com

Para ver sólo el extract sin subir:
  python3 scripts/sync_hipotecas_to_render_postgres.py \
    --local-db data/erp_import2.sqlite \
    --render-host dummy --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any


FIN_EMPRESA_ID = "5a676274-4ba8-4ec5-8010-af2bd2bfada7"
DEFAULT_RENDER_WORKDIR = "/opt/render/project/src"
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


def safe_json_object(raw: object) -> dict[str, Any]:
    try:
        text = str(raw or "").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def get_nested(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for key in str(path).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def fetch_payload(local_db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(local_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM hipotecas
            WHERE empresa_id = ?
            ORDER BY COALESCE(NULLIF(fecha_firma, ''), NULLIF(fecha_encargo, ''), updated_at, created_at) DESC
            """,
            (FIN_EMPRESA_ID,),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            rowd = dict(row)
            ci = safe_json_object(rowd.get("cliente_inmueble_json"))
            hd = safe_json_object(rowd.get("hipoteca_detalle_json"))
            # Cliente base: prioriza comprador.c1
            cliente = {
                "nombre": str(get_nested(ci, "comprador.c1.nombre") or rowd.get("cliente") or "").strip(),
                "nif": str(get_nested(ci, "comprador.c1.nif") or "").strip(),
                "email": str(get_nested(ci, "comprador.c1.email") or "").strip(),
                "telefono": str(get_nested(ci, "comprador.c1.telefono") or "").strip(),
                "direccion": str(get_nested(ci, "comprador.c1.domicilio") or "").strip(),
                "codigo_postal": str(get_nested(ci, "inmueble.codigo_postal") or "").strip(),
                "localidad": str(get_nested(ci, "inmueble.localidad") or "").strip(),
                "provincia": str(get_nested(ci, "inmueble.provincia") or "").strip(),
                "tipo": "Física",
                "perfil": "Autónomo",
                "estado": "Activo",
            }
            hipoteca = {
                "cliente": rowd.get("cliente") or "",
                "banco": rowd.get("banco") or "",
                "precio": rowd.get("precio"),
                "importe_hipoteca": rowd.get("importe_hipoteca"),
                "porcentaje": rowd.get("porcentaje"),
                "entrada": rowd.get("entrada"),
                "comision": rowd.get("comision"),
                "oficina": rowd.get("oficina") or "",
                "fecha_encargo": rowd.get("fecha_encargo") or "",
                "encargo": rowd.get("encargo") or "",
                "tipo_hipoteca": rowd.get("tipo_hipoteca") or "",
                "fecha_firma": rowd.get("fecha_firma") or "",
                "cesion": rowd.get("cesion"),
                "comision_juan": rowd.get("comision_juan"),
                "comision_modernia": rowd.get("comision_modernia"),
                "inmobiliaria_compra": rowd.get("inmobiliaria_compra") or "",
                "asesor": rowd.get("asesor") or "",
                "estado": rowd.get("estado") or "",
                "anio": rowd.get("anio"),
                "cliente_inmueble_json": json.dumps(ci, ensure_ascii=False, separators=(",", ":")),
                "hipoteca_detalle_json": json.dumps(hd, ensure_ascii=False, separators=(",", ":")),
                "liquidacion_json": rowd.get("liquidacion_json") or "{}",
            }
            items.append(
                {
                    "source": {"hipoteca_id": rowd.get("id"), "updated_at": rowd.get("updated_at")},
                    "cliente": cliente,
                    "hipoteca": hipoteca,
                }
            )
        return {"items": items}
    finally:
        conn.close()


class CommandError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        super().__init__(f"Command failed ({returncode}): {' '.join(cmd)}")
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout or ""
        self.stderr = stderr or ""


def run(cmd: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[str]:
    if input_bytes is None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    else:
        # Python 3.9: si `text=True`, `input` debe ser str. Enviamos bytes sin modo texto y decodificamos.
        proc = subprocess.run(cmd, input=input_bytes, capture_output=True)
        if isinstance(proc.stdout, (bytes, bytearray)):
            proc.stdout = proc.stdout.decode("utf-8", errors="replace")
        if isinstance(proc.stderr, (bytes, bytearray)):
            proc.stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode == 0:
        return proc
    raise CommandError(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")


def is_transient_ssh_error(err: CommandError) -> bool:
    msg = (err.stderr or "") + "\n" + (err.stdout or "")
    needles = (
        "Connection reset by peer",
        "Connection timed out",
        "Broken pipe",
        "kex_exchange_identification",
        "Connection closed by remote host",
        "ssh_exchange_identification",
        "Could not resolve hostname",
        "Temporary failure",
    )
    return any(n in msg for n in needles)


def run_retry(cmd: list[str], retries: int, wait_seconds: float) -> subprocess.CompletedProcess[str]:
    attempt = 0
    last: CommandError | None = None
    while attempt <= max(0, int(retries)):
        try:
            return run(cmd)
        except CommandError as err:
            last = err
            if attempt >= retries or not is_transient_ssh_error(err):
                break
            print(f"[sync] Transient failure, retry {attempt + 1}/{retries}: {' '.join(cmd)}", file=sys.stderr)
            time.sleep(max(0.5, float(wait_seconds)))
            attempt += 1
    assert last is not None
    print(f"[sync] Command failed ({last.returncode}): {' '.join(last.cmd)}", file=sys.stderr)
    if last.stdout:
        print(last.stdout.rstrip(), file=sys.stderr)
    if last.stderr:
        print(last.stderr.rstrip(), file=sys.stderr)
    raise SystemExit(last.returncode)


def run_retry_with_input(cmd: list[str], input_bytes: bytes, retries: int, wait_seconds: float) -> subprocess.CompletedProcess[str]:
    attempt = 0
    last: CommandError | None = None
    while attempt <= max(0, int(retries)):
        try:
            return run(cmd, input_bytes=input_bytes)
        except CommandError as err:
            last = err
            if attempt >= retries or not is_transient_ssh_error(err):
                break
            print(f"[sync] Transient failure, retry {attempt + 1}/{retries}: {' '.join(cmd)}", file=sys.stderr)
            time.sleep(max(0.5, float(wait_seconds)))
            attempt += 1
    assert last is not None
    print(f"[sync] Command failed ({last.returncode}): {' '.join(last.cmd)}", file=sys.stderr)
    if last.stdout:
        print(last.stdout.rstrip(), file=sys.stderr)
    if last.stderr:
        print(last.stderr.rstrip(), file=sys.stderr)
    raise SystemExit(last.returncode)


def build_tar_gz(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def summarize_items(items: list[dict[str, Any]]) -> None:
    for item in items:
        cliente = item.get("cliente") or {}
        hip = item.get("hipoteca") or {}
        ci = safe_json_object(hip.get("cliente_inmueble_json"))
        hd = safe_json_object(hip.get("hipoteca_detalle_json"))
        inmueble_dir = str(get_nested(ci, "inmueble.direccion") or "").strip()
        prefs = get_nested(hd, "preferencias") or {}
        pre = get_nested(hd, "precontractual") or {}
        print("-" * 60)
        print(f"Cliente: {cliente.get('nombre')}")
        print(f"NIF: {cliente.get('nif')} · Email: {cliente.get('email')} · Tel: {cliente.get('telefono')}")
        print(f"Domicilio: {cliente.get('direccion')}")
        print(f"Inmueble: {inmueble_dir}")
        print(f"Fecha encargo: {hip.get('fecha_encargo')} · Importe: {hip.get('importe_hipoteca')} · Entrada: {hip.get('entrada')}")
        print(f"Preferencias: plazo={prefs.get('plazo_anos')} años · interés={prefs.get('tipo_interes')} · viv_hab={prefs.get('garantia_vivienda_habitual')}")
        print(f"Precontractual: registro={pre.get('registro')} · seguro_rc={pre.get('seguro_rc')}")


def _is_nonempty_json_text(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if raw == "{}":
        return False
    return True


def filter_items(
    items: list[dict[str, Any]],
    *,
    only_ids: set[str] | None,
    only_with_json: bool,
    since: str,
) -> list[dict[str, Any]]:
    since_norm = str(since or "").strip()
    out: list[dict[str, Any]] = []
    for item in items:
        src = item.get("source") or {}
        src_id = str(src.get("hipoteca_id") or "").strip()
        if only_ids and src_id and src_id not in only_ids:
            continue
        if since_norm:
            updated_at = str(src.get("updated_at") or "").strip()
            # ISO string compare works for UTC ISO8601.
            if updated_at and updated_at < since_norm:
                continue
        if only_with_json:
            hip = item.get("hipoteca") or {}
            if not (
                _is_nonempty_json_text(hip.get("cliente_inmueble_json"))
                or _is_nonempty_json_text(hip.get("hipoteca_detalle_json"))
            ):
                continue
        out.append(item)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza hipotecas a Render (Postgres) por SSH.")
    parser.add_argument("--local-db", default="data/erp_import2.sqlite", help="Ruta a la SQLite local.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render, ej. srv-xxx@ssh.frankfurt.render.com")
    parser.add_argument("--render-workdir", default=DEFAULT_RENDER_WORKDIR, help="Directorio del proyecto en Render para ficheros temporales.")
    parser.add_argument("--render-python", default="", help="Python a usar en Render (si vacío: .venv/bin/python).")
    parser.add_argument("--retries", type=int, default=6, help="Reintentos ante fallos transitorios de SSH/SCP.")
    parser.add_argument("--retry-wait", type=float, default=8.0, help="Segundos entre reintentos.")
    parser.add_argument("--via-stdin", action="store_true", help="Sincroniza en una sola conexión SSH (recomendado en Render).")
    parser.add_argument("--keep-remote", action="store_true", help="No borra los ficheros temporales en /tmp tras sincronizar.")
    parser.add_argument("--only-id", action="append", default=[], help="Limita a un hipoteca_id de la SQLite local (repetible).")
    parser.add_argument("--since", default="", help="Solo hipotecas con updated_at >= este ISO8601 (ej: 2026-04-20T00:00:00Z).")
    parser.add_argument("--all", action="store_true", help="Incluye hipotecas sin JSON (por defecto se filtra a las que tienen JSON).")
    parser.add_argument("--dry-run", action="store_true", help="Genera el payload, muestra resumen, pero no lo sube.")
    args = parser.parse_args()

    local_db = Path(args.local_db).expanduser().resolve()
    if not local_db.exists():
        raise SystemExit(f"No existe la base local: {local_db}")

    payload = fetch_payload(local_db)
    items_all = payload.get("items") or []
    only_ids = {str(x).strip() for x in (args.only_id or []) if str(x).strip()}
    items = filter_items(
        items_all,
        only_ids=only_ids if only_ids else None,
        only_with_json=(not args.all),
        since=str(args.since or "").strip(),
    )
    if not items:
        raise SystemExit("No se encontraron hipotecas de Financiaciones Modernia en la base local.")

    payload = {"items": items}
    print(f"Preparadas {len(items)} hipotecas para sincronizar (Financiaciones Modernia).")
    summarize_items(items[:10])
    if args.dry_run:
        return

    render_workdir = str(args.render_workdir or DEFAULT_RENDER_WORKDIR).rstrip("/")
    scratch_dir = "/tmp/hipotecas_sync"
    remote_payload = f"{scratch_dir}/hipotecas_sync.json"
    remote_script = f"{scratch_dir}/hipotecas_sync_remote_pg.py"
    render_python = str(args.render_python or "").strip() or f"{render_workdir}/.venv/bin/python"

    remote_py = Path(__file__).with_name("hipotecas_sync_remote_pg.py").read_text(encoding="utf-8")
    try:
        compile(remote_py, "hipotecas_sync_remote_pg.py", "exec")
    except SyntaxError as exc:
        raise SystemExit(f"El script remoto no compila: {exc}") from exc

    with tempfile.TemporaryDirectory() as tmpdir:
        payload_path = Path(tmpdir) / "hipotecas_sync.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.via_stdin:
            tar_bytes = build_tar_gz(
                {
                    "hipotecas_sync.json": payload_path.read_bytes(),
                    "hipotecas_sync_remote_pg.py": remote_py.encode("utf-8"),
                }
            )
            cleanup = "" if args.keep_remote else f" && rm -rf {scratch_dir}"
            remote_cmd = (
                f"set -e; mkdir -p {scratch_dir} "
                f"&& tar -xzf - -C {scratch_dir} "
                f"&& {render_python} {remote_script} {remote_payload}{cleanup} "
                f"&& echo '__SYNC_OK__'"
            )
            proc = run_retry_with_input(["ssh", *SSH_OPTIONS, args.render_host, remote_cmd], tar_bytes, args.retries, args.retry_wait)
            if proc.stdout.strip():
                print(proc.stdout.strip())
        else:
            run_retry(["ssh", *SSH_OPTIONS, args.render_host, f"mkdir -p {scratch_dir}"], args.retries, args.retry_wait)
            run_retry(["scp", *SSH_OPTIONS, str(payload_path), f"{args.render_host}:{remote_payload}"], args.retries, args.retry_wait)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as handle:
                handle.write(remote_py)
                script_local = handle.name
            run_retry(["scp", *SSH_OPTIONS, script_local, f"{args.render_host}:{remote_script}"], args.retries, args.retry_wait)
            cleanup = "" if args.keep_remote else f" && rm -rf {scratch_dir}"
            remote_cmd = f"{render_python} {remote_script} {remote_payload}{cleanup} && echo '__SYNC_OK__'"
            run_retry(["ssh", *SSH_OPTIONS, args.render_host, remote_cmd], args.retries, args.retry_wait)
        print("Sincronización de hipotecas completada (Render Postgres).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
