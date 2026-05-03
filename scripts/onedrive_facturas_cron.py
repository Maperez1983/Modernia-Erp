#!/usr/bin/env python3
"""
Ingesta de facturas desde OneDrive Personal (Microsoft Graph) -> S3 -> OCR (CRM MODERNIA).

Pensado para ejecutarse como Cron Job en Render (no depende de OneDrive sync en Mac).

Requisitos (env):
  - APP_INGEST_API_KEY: API key para endpoints ingest del CRM
  - CRM_BASE_URL: URL pública del CRM (p.ej. https://modernia-erp-2.onrender.com)
  - ONEDRIVE_CLIENT_ID / ONEDRIVE_CLIENT_SECRET / ONEDRIVE_REFRESH_TOKEN
  - ONEDRIVE_FACTURAS_ROOT_PATH: ruta a la carpeta FACTURAS dentro de OneDrive (p.ej. "ESTUDIO VELAZQUEZ/FACTURAS")
Opcional:
  - ONEDRIVE_SCOPES (default: "offline_access User.Read Files.Read.All")
  - ONEDRIVE_SOURCE (default: "onedrive")
  - ONEDRIVE_EMPRESA_ALIAS (default: se infiere del root path antes de "/FACTURAS")

Persistencia:
  - Guarda deltaLink y refresh_token (si rota) en crm_meta para evitar reprocesos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import requests

from web.db_backend import open_db_conn


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def normalize_lookup_text(value: str) -> str:
    if not value:
        return ""
    import unicodedata

    text = str(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def ensure_crm_meta(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_meta (
          key TEXT PRIMARY KEY,
          value TEXT,
          updated_at TEXT
        )
        """
    )
    conn.commit()


def meta_get(conn, key: str) -> str:
    try:
        row = conn.execute("SELECT value FROM crm_meta WHERE key = ? LIMIT 1", (str(key),)).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    if isinstance(row, dict):
        return str(row.get("value") or "")
    try:
        return str(row["value"] or "")
    except Exception:
        try:
            return str(row[0] or "")
        except Exception:
            return ""


def meta_set(conn, key: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO crm_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        """,
        (str(key), str(value), now),
    )
    conn.commit()


def graph_refresh_access_token(conn, *, client_id: str, client_secret: str, scopes: str, refresh_token_env: str) -> tuple[str, str]:
    refresh_token = meta_get(conn, "onedrive_refresh_token").strip() or str(refresh_token_env or "").strip()
    if not refresh_token:
        raise RuntimeError("ONEDRIVE_REFRESH_TOKEN no configurado (ni en crm_meta)")
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": scopes,
    }
    resp = requests.post(TOKEN_URL, data=data, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Refresh token falló: HTTP {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    access_token = str(payload.get("access_token") or "").strip()
    new_refresh = str(payload.get("refresh_token") or "").strip()
    if not access_token:
        raise RuntimeError("Refresh token OK pero access_token vacío")
    if new_refresh and new_refresh != refresh_token:
        # Rotación silenciosa: guardamos el nuevo refresh token en DB.
        meta_set(conn, "onedrive_refresh_token", new_refresh)
    return access_token, (new_refresh or refresh_token)


def graph_get(session: requests.Session, url: str, *, timeout_s: int = 30) -> dict:
    resp = session.get(url, timeout=timeout_s)
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph GET error HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def graph_get_driveitem_by_path(session: requests.Session, path: str) -> dict:
    safe = str(path or "").strip().strip("/")
    if not safe:
        url = f"{GRAPH_BASE}/me/drive/root"
    else:
        url = f"{GRAPH_BASE}/me/drive/root:/{urllib.parse.quote(safe)}"
    return graph_get(session, url)


def graph_get_driveitem_by_id(session: requests.Session, item_id: str) -> dict:
    item_id = str(item_id or "").strip()
    if not item_id:
        return {}
    select = "id,name,parentReference,file,folder,lastModifiedDateTime,size"
    url = f"{GRAPH_BASE}/me/drive/items/{urllib.parse.quote(item_id)}?$select={urllib.parse.quote(select)}"
    return graph_get(session, url)


def graph_download_file_bytes(session: requests.Session, item_id: str) -> bytes:
    # According to Graph docs, /content returns 302 to a preauthenticated download URL. requests can follow it.
    url = f"{GRAPH_BASE}/me/drive/items/{urllib.parse.quote(str(item_id))}/content"
    resp = session.get(url, stream=True, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph download error HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.content


def infer_empresa_alias_from_root(root_path: str) -> str:
    raw = str(root_path or "").strip().strip("/")
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return ""
    # root_path suele ser "<EMPRESA>/FACTURAS"
    for i, p in enumerate(parts):
        if normalize_lookup_text(p) == "FACTURAS":
            if i > 0:
                return "/".join(parts[:i])
            return ""
    # Si no encontramos FACTURAS, devolvemos el primer segmento.
    return parts[0]


def ensure_empresa_aliases_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS empresa_aliases (
          id TEXT PRIMARY KEY,
          empresa_id TEXT NOT NULL,
          source TEXT NOT NULL,
          alias TEXT NOT NULL,
          alias_norm TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (source, alias_norm)
        )
        """
    )
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_empresa_aliases_empresa_id ON empresa_aliases (empresa_id)")
    except Exception:
        pass
    conn.commit()


def resolve_empresa_id_from_alias(conn, alias: str, *, source: str = "onedrive") -> str:
    ensure_empresa_aliases_table(conn)
    raw = str(alias or "").strip()
    if not raw:
        return ""
    alias_norm = normalize_lookup_text(raw)
    if not alias_norm:
        return ""
    source_key = (source or "onedrive").strip().lower() or "onedrive"
    row = conn.execute(
        """
        SELECT empresa_id
        FROM empresa_aliases
        WHERE source = ? AND alias_norm = ?
        LIMIT 1
        """,
        (source_key, alias_norm),
    ).fetchone()
    if row:
        if isinstance(row, dict):
            return str(row.get("empresa_id") or "").strip()
        try:
            return str(row["empresa_id"] or "").strip()
        except Exception:
            try:
                return str(row[0] or "").strip()
            except Exception:
                return ""

    empresas = conn.execute("SELECT id, nombre FROM empresas WHERE COALESCE(activo, 1) = 1").fetchall()
    candidates = []
    for e in empresas or []:
        try:
            name = e["nombre"] if not isinstance(e, dict) else e.get("nombre")
            eid = e["id"] if not isinstance(e, dict) else e.get("id")
        except Exception:
            continue
        name_norm = normalize_lookup_text(name or "")
        if not name_norm:
            continue
        if alias_norm == name_norm or alias_norm in name_norm:
            candidates.append(str(eid or "").strip())
    if len(candidates) != 1:
        return ""
    empresa_id = candidates[0]
    now = datetime.now(timezone.utc).isoformat()
    alias_id = os.urandom(16).hex()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO empresa_aliases (
              id, empresa_id, source, alias, alias_norm, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (alias_id, empresa_id, source_key, raw, alias_norm, now, now),
        )
    except Exception:
        pass
    conn.commit()
    return empresa_id


def safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "factura.pdf"))
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "factura.pdf"


def build_s3_key(*, empresa_id: str, tipo: str, year: str, item_id: str, filename: str) -> str:
    tipo_key = "emitidas" if str(tipo or "").strip().lower().startswith("emit") else "recibidas"
    year_s = str(year or "").strip()
    if not re.fullmatch(r"\d{4}", year_s):
        year_s = datetime.now().strftime("%Y")
    return f"facturas_inbox/{empresa_id}/{tipo_key}/{year_s}/{item_id}_{safe_filename(filename)}"


def infer_tipo_year_from_ancestry(ancestry: list[str]) -> tuple[str, str]:
    if not ancestry:
        return "", ""
    first = normalize_lookup_text(ancestry[0])
    if first not in {"EMITIDAS", "RECIBIDAS"}:
        return "", ""
    year = ""
    if len(ancestry) >= 2:
        second = str(ancestry[1] or "").strip()
        if re.fullmatch(r"\d{4}", second):
            year = second
    return ("emitidas" if first == "EMITIDAS" else "recibidas"), year


def build_ancestry(session: requests.Session, *, root_id: str, parent_id: str, cache: dict[str, dict]) -> list[str]:
    out = []
    current = str(parent_id or "").strip()
    root_id = str(root_id or "").strip()
    while current and current != root_id:
        if current in cache:
            meta = cache[current]
        else:
            meta = graph_get_driveitem_by_id(session, current)
            cache[current] = meta
        name = str(meta.get("name") or "").strip()
        if name:
            out.append(name)
        current = str((meta.get("parentReference") or {}).get("id") or "").strip()
        if len(out) > 50:
            break
    out.reverse()
    return out


def crm_ingest_ocr(*, base_url: str, api_key: str, empresa_id: str, s3_key: str, tipo: str, filename: str, source_hint: str) -> dict:
    url = base_url.rstrip("/") + "/api/ingest_facturas_ocr"
    headers = {"Content-Type": "application/json", "X-API-Key": api_key}
    payload = {
        "empresa_id": empresa_id,
        "s3_key": s3_key,
        "tipo": tipo,
        "filename": filename,
        "source": "onedrive",
        "source_hint": source_hint,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"OCR error HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()

def crm_ingest_presign(*, base_url: str, api_key: str, empresa_id: str, tipo: str, year: str, filename: str) -> dict:
    url = base_url.rstrip("/") + "/api/ingest_facturas_presign"
    headers = {"Content-Type": "application/json", "X-API-Key": api_key}
    payload = {
        "empresa_id": empresa_id,
        "tipo": tipo,
        "year": year,
        "filename": filename,
        "content_type": "application/pdf",
        "source": "onedrive",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"Presign error HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def upload_via_presign(*, presign_url: str, data: bytes, content_type: str = "application/pdf") -> None:
    resp = requests.put(presign_url, data=data, headers={"Content-Type": content_type}, timeout=180)
    if resp.status_code >= 400:
        raise RuntimeError(f"PUT S3 presign error HTTP {resp.status_code}: {resp.text[:300]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.environ.get("APP_DB_PATH") or "data/erp.sqlite")
    args = parser.parse_args()

    crm_base_url = str(os.environ.get("CRM_BASE_URL") or "").strip()
    ingest_key = str(os.environ.get("APP_INGEST_API_KEY") or "").strip()
    if not crm_base_url:
        print("ERROR: CRM_BASE_URL requerido", file=sys.stderr)
        return 2
    if not ingest_key:
        print("ERROR: APP_INGEST_API_KEY requerido", file=sys.stderr)
        return 2

    od_client_id = str(os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
    od_client_secret = str(os.environ.get("ONEDRIVE_CLIENT_SECRET") or "").strip()
    od_refresh = str(os.environ.get("ONEDRIVE_REFRESH_TOKEN") or "").strip()
    od_scopes = str(os.environ.get("ONEDRIVE_SCOPES") or "offline_access User.Read Files.Read.All").strip()
    od_root_path = str(os.environ.get("ONEDRIVE_FACTURAS_ROOT_PATH") or "").strip().strip("/")
    od_source = str(os.environ.get("ONEDRIVE_SOURCE") or "onedrive").strip()
    od_empresa_alias = str(os.environ.get("ONEDRIVE_EMPRESA_ALIAS") or "").strip()
    if not od_empresa_alias:
        od_empresa_alias = infer_empresa_alias_from_root(od_root_path)

    if not od_client_id or not od_client_secret:
        print("ERROR: ONEDRIVE_CLIENT_ID/ONEDRIVE_CLIENT_SECRET requeridos", file=sys.stderr)
        return 2
    if not od_root_path:
        print("ERROR: ONEDRIVE_FACTURAS_ROOT_PATH requerido (p.ej. 'ESTUDIO VELAZQUEZ/FACTURAS')", file=sys.stderr)
        return 2
    if not od_empresa_alias:
        print("ERROR: ONEDRIVE_EMPRESA_ALIAS no se pudo inferir; configúralo explícitamente", file=sys.stderr)
        return 2

    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        ensure_crm_meta(conn)

        access_token, _refresh_used = graph_refresh_access_token(
            conn,
            client_id=od_client_id,
            client_secret=od_client_secret,
            scopes=od_scopes,
            refresh_token_env=od_refresh,
        )
        graph = requests.Session()
        graph.headers.update({"Authorization": f"Bearer {access_token}"})

        root_norm = normalize_lookup_text(od_root_path)
        root_id = meta_get(conn, f"onedrive_root_id:{root_norm}").strip()
        if not root_id:
            root_item = graph_get_driveitem_by_path(graph, od_root_path)
            root_id = str(root_item.get("id") or "").strip()
            if not root_id:
                raise RuntimeError("No se pudo resolver el id de la carpeta root en OneDrive")
            meta_set(conn, f"onedrive_root_id:{root_norm}", root_id)

        empresa_id = resolve_empresa_id_from_alias(conn, od_empresa_alias, source=od_source)
        if not empresa_id:
            raise RuntimeError(f"No se pudo resolver empresa_id para alias '{od_empresa_alias}'")

        delta_key = f"onedrive_delta:{root_id}"
        delta_url = meta_get(conn, delta_key).strip() or f"{GRAPH_BASE}/me/drive/items/{urllib.parse.quote(root_id)}/delta"

        print(f"[onedrive] root='{od_root_path}' root_id='{root_id}' empresa_alias='{od_empresa_alias}' empresa_id='{empresa_id}'")
        print(f"[onedrive] delta_url={'(stored)' if 'delta?(' in delta_url or 'delta(token=' in delta_url else '(initial)'}")

        item_cache: dict[str, dict] = {}
        processed = 0
        skipped = 0
        errors = 0
        new_delta_link = ""

        while True:
            page = graph_get(graph, delta_url)
            items = page.get("value") or []
            for it in items:
                try:
                    if not isinstance(it, dict):
                        continue
                    if it.get("deleted") is not None:
                        continue
                    if not it.get("file"):
                        continue
                    name = str(it.get("name") or "").strip()
                    if not name.lower().endswith(".pdf"):
                        continue
                    item_id = str(it.get("id") or "").strip()
                    if not item_id:
                        continue
                    last_mod = str(it.get("lastModifiedDateTime") or "").strip()
                    done_key = f"onedrive_done:{item_id}"
                    if last_mod and meta_get(conn, done_key).strip() == last_mod:
                        skipped += 1
                        continue

                    parent_id = str((it.get("parentReference") or {}).get("id") or "").strip()
                    ancestry = build_ancestry(graph, root_id=root_id, parent_id=parent_id, cache=item_cache)
                    tipo, year = infer_tipo_year_from_ancestry(ancestry)
                    if not tipo:
                        skipped += 1
                        continue

                    s3_key = build_s3_key(
                        empresa_id=empresa_id,
                        tipo=tipo,
                        year=year,
                        item_id=item_id,
                        filename=name,
                    )
                    # Descargar bytes -> subir a S3 -> OCR
                    data = graph_download_file_bytes(graph, item_id)
                    signed = crm_ingest_presign(
                        base_url=crm_base_url,
                        api_key=ingest_key,
                        empresa_id=empresa_id,
                        tipo=tipo.upper(),
                        year=year,
                        filename=name,
                    )
                    presign_url = str(signed.get("url") or "").strip()
                    final_key = str(signed.get("key") or "").strip()
                    if not presign_url or not final_key:
                        raise RuntimeError("Respuesta presign inválida (faltan url/key)")
                    upload_via_presign(presign_url=presign_url, data=data, content_type="application/pdf")
                    source_hint = f"onedrive item={item_id} lastModified={last_mod}"
                    crm_ingest_ocr(
                        base_url=crm_base_url,
                        api_key=ingest_key,
                        empresa_id=empresa_id,
                        s3_key=final_key,
                        tipo=tipo.upper(),
                        filename=name,
                        source_hint=source_hint,
                    )
                    if last_mod:
                        meta_set(conn, done_key, last_mod)
                    processed += 1
                except Exception as exc:
                    errors += 1
                    try:
                        print(f"[ERROR] item: {type(exc).__name__}: {exc}", file=sys.stderr)
                    except Exception:
                        pass

            if page.get("@odata.nextLink"):
                delta_url = str(page.get("@odata.nextLink") or "").strip()
                continue
            new_delta_link = str(page.get("@odata.deltaLink") or "").strip()
            break

        if errors == 0 and new_delta_link:
            meta_set(conn, delta_key, new_delta_link)
        print(f"[done] processed={processed} skipped={skipped} errors={errors}")
        return 0 if errors == 0 else 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
