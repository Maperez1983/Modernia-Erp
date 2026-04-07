#!/usr/bin/env python3
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SAFE_SPLIT_RE = re.compile(r"[_\-\s]+")
TOKEN_RE = re.compile(r"[A-Za-z0-9]{6,}")
SPLIT_NUM_RE = re.compile(r"(?<![0-9])(\d{6,})[ _\\-](\d{1,3})(?![0-9])")
PLACEHOLDER_VALUES = {"poliza_key", "poliza_url", "doc_key", "doc_url"}


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def normalize_poliza_token(value: str) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def is_placeholder_value(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    return raw.lower() in PLACEHOLDER_VALUES


def looks_like_stamp_parts(parts: list[str]) -> bool:
    if len(parts) < 4:
        return False
    if not re.fullmatch(r"\d{8}", parts[0] or ""):
        return False
    if not re.fullmatch(r"\d{6}", parts[1] or ""):
        return False
    if not re.fullmatch(r"[0-9a-f]{8}", (parts[2] or "").lower()):
        return False
    return True


def original_filename_from_key(key: str) -> str:
    base = os.path.basename(str(key or ""))
    parts = base.split("_")
    if looks_like_stamp_parts(parts):
        return "_".join(parts[3:]) or base
    return base


def extract_tokens_from_filename(name: str) -> list[str]:
    text = str(name or "")
    tokens = []
    # 1) Números largos partidos (ej: "82124000009210 0" -> "821240000092100")
    for m in SPLIT_NUM_RE.finditer(text):
        merged = normalize_poliza_token((m.group(1) or "") + (m.group(2) or ""))
        if merged:
            tokens.append(merged)
    for raw in TOKEN_RE.findall(text):
        norm = normalize_poliza_token(raw)
        if not norm:
            continue
        # Excluye tokens muy genéricos
        if norm in {"POLIZA", "POLIZAS", "SEGURO", "SEGUROS", "DOCUMENTO", "DOC"}:
            continue
        tokens.append(norm)
    # orden estable y únicos
    out = []
    for t in tokens:
        if t not in out:
            out.append(t)
    return out


def s3_client_and_conf():
    try:
        import boto3
    except Exception:
        return None, "", ""
    bucket = env_first("AWS_S3_BUCKET", "S3_BUCKET")
    region = env_first("AWS_REGION", "AWS_DEFAULT_REGION")
    if not bucket or not region:
        return None, bucket, region
    return boto3.client("s3", region_name=region), bucket, region


def list_s3_objects(prefix: str) -> list[str]:
    client, bucket, _region = s3_client_and_conf()
    if not client:
        return []
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for item in resp.get("Contents") or []:
            k = str(item.get("Key") or "").strip()
            if k:
                keys.append(k)
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
            continue
        break
    return keys


def open_pg():
    from web.db_backend import open_postgres_conn  # noqa: E402

    return open_postgres_conn(with_row_factory=True)


def fetch_seguros(conn, empresa_id: str):
    rows = conn.execute(
        """
        SELECT id, poliza_numero, tomador, compania, ramo, poliza_key, poliza_url
        FROM seguros
        WHERE empresa_id = %s
        ORDER BY created_at ASC NULLS LAST
        """,
        (empresa_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r.get("id") or "").strip(),
                "poliza_numero": str(r.get("poliza_numero") or "").strip(),
                "tomador": str(r.get("tomador") or "").strip(),
                "compania": str(r.get("compania") or "").strip(),
                "ramo": str(r.get("ramo") or "").strip(),
                "poliza_key": str(r.get("poliza_key") or "").strip(),
                "poliza_url": str(r.get("poliza_url") or "").strip(),
            }
        )
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Backfill: enlaza PDFs en S3 (prefijo seguros/) a filas de `seguros` rellenando poliza_key/poliza_url, usando el nombre original del fichero para buscar el nº de póliza."
    )
    parser.add_argument("--empresa-id", required=True, help="empresa_id de Seguros (p.ej. Fincas Velazquez).")
    parser.add_argument("--s3-prefix", default="seguros/", help="Prefijo S3 (default: seguros/).")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en DB (default).")
    parser.add_argument("--apply", action="store_true", help="Aplica updates en DB.")
    parser.add_argument("--limit", type=int, default=0, help="Limita nº de PDFs a procesar (0=sin límite).")
    parser.add_argument("--max-updates", type=int, default=0, help="Limita nº de updates (0=sin límite).")
    args = parser.parse_args()

    if not args.apply:
        args.dry_run = True

    client, bucket, region = s3_client_and_conf()
    if not client:
        raise SystemExit("S3 no disponible: faltan credenciales/env (AWS_S3_BUCKET/AWS_REGION) o boto3.")
    if not bucket or not region:
        raise SystemExit("S3 no configurado: faltan AWS_S3_BUCKET y/o AWS_REGION.")

    empresa_id = str(args.empresa_id).strip()
    prefix = str(args.s3_prefix or "").lstrip("/")
    keys = [k for k in list_s3_objects(prefix) if k.lower().endswith(".pdf")]
    if args.limit and args.limit > 0:
        keys = keys[: args.limit]

    conn = open_pg()
    seguros = fetch_seguros(conn, empresa_id)

    missing = []
    for s in seguros:
        key = s.get("poliza_key") or ""
        url = s.get("poliza_url") or ""
        # Algunos despliegues antiguos devolvieron literalmente el nombre del campo como valor.
        if is_placeholder_value(key):
            key = ""
            s["poliza_key"] = ""
        if is_placeholder_value(url):
            url = ""
            s["poliza_url"] = ""
        if not (str(key).strip() or str(url).strip()):
            missing.append(s)
    by_poliza = defaultdict(list)
    for s in missing:
        pol = normalize_poliza_token(s["poliza_numero"])
        if not pol:
            continue
        by_poliza[pol].append(s["id"])

    matched = []
    ambiguous = 0
    no_match = 0
    token_hits = Counter()
    used_seguros = set()

    for key in keys:
        name = original_filename_from_key(key)
        tokens = extract_tokens_from_filename(name)
        chosen = ""
        chosen_token = ""
        for tok in tokens:
            ids = by_poliza.get(tok) or []
            if not ids:
                continue
            token_hits[tok] += 1
            if len(ids) == 1 and ids[0] not in used_seguros:
                chosen = ids[0]
                chosen_token = tok
                break
            # Si hay varias filas con el mismo nº de póliza, no asumimos.
            if len(ids) > 1:
                ambiguous += 1
                chosen = ""
                chosen_token = ""
                break
        if not chosen:
            no_match += 1
            continue
        used_seguros.add(chosen)
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        matched.append((chosen, key, public_url, chosen_token, name))

    now = datetime.now(timezone.utc).isoformat()
    print(f"ts={now}")
    print(f"empresa_id={empresa_id}")
    print(f"s3_bucket={bucket}")
    print(f"s3_region={region}")
    print(f"s3_prefix={prefix}")
    print(f"s3_pdfs_scanned={len(keys)}")
    print(f"seguros_total={len(seguros)}")
    print(f"seguros_missing_pdf={len(missing)}")
    print(f"candidates_by_poliza={len(by_poliza)}")
    print(f"matched_updates={len(matched)}")
    print(f"no_match={no_match}")
    print(f"ambiguous={ambiguous}")
    common = token_hits.most_common(8)
    if common:
        print("matched_tokens_common=" + ",".join(f"{t}:{c}" for t, c in common))

    if not matched:
        print("No se encontraron matches por nº de póliza en nombre de archivo.")
        return

    if args.max_updates and args.max_updates > 0:
        matched = matched[: args.max_updates]

    if args.dry_run:
        print("dry_run=1 (no se aplican cambios)")
        print("sample:")
        for seguro_id, key, _url, tok, name in matched[:12]:
            print(f"- seguro_id={seguro_id} token={tok} key={key} name={name}")
        return

    updated = 0
    for seguro_id, key, url, _tok, _name in matched:
        conn.execute(
            """
            UPDATE seguros
            SET poliza_key = CASE
                  WHEN COALESCE(TRIM(poliza_key), '') = '' OR LOWER(TRIM(poliza_key)) IN ('poliza_key', 'doc_key') THEN %s
                  ELSE poliza_key
                END,
                poliza_url = CASE
                  WHEN COALESCE(TRIM(poliza_url), '') = '' OR LOWER(TRIM(poliza_url)) IN ('poliza_url', 'doc_url') THEN %s
                  ELSE poliza_url
                END,
                updated_at = %s
            WHERE id = %s
              AND (
                COALESCE(TRIM(poliza_key), '') = '' OR LOWER(TRIM(poliza_key)) IN ('poliza_key', 'doc_key')
                OR COALESCE(TRIM(poliza_url), '') = '' OR LOWER(TRIM(poliza_url)) IN ('poliza_url', 'doc_url')
              )
            """,
            (key, url, now, seguro_id),
        )
        updated += 1
    conn.commit()
    print(f"applied_updates={updated}")


if __name__ == "__main__":
    main()
