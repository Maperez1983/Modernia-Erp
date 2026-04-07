#!/usr/bin/env python3
"""
Backfill (Seguros): enlaza PDFs en S3 a filas de `seguros` leyendo el contenido del PDF.

Por qué:
  - En el histórico hay muchos PDFs cuyo nombre NO incluye el nº de póliza.
  - En la tabla `seguros` hay muchas filas con `poliza_numero` vacío.
  - Para poder mostrar "Ver" en el listado, necesitamos rellenar `poliza_key/poliza_url`.

Estrategia:
  1) Descarga cada PDF desde S3 (prefijo seguros/).
  2) Extrae texto (pdftotext -> ocrmypdf/tesseract si hay binarios disponibles).
  3) Intenta extraer el nº de póliza desde el texto.
  4) Match en DB:
     - Preferente: `seguros.poliza_numero` coincide (normalizado).
     - Si no existe: asigna a una fila sin nº, usando compañía + tomador (desde nombre/ocr) con umbrales estrictos.
  5) Rellena `poliza_key/poliza_url` (y `poliza_numero` si estaba vacío). No pisa valores existentes.

Seguro:
  - No borra nada.
  - No sobrescribe `poliza_key/poliza_url` si ya existen.
  - Evita asignaciones ambiguas (se reportan y se saltan).
"""

import argparse
import io
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
POLIZA_RE_LIST = [
    re.compile(
        r"(?is)\bpol[ií]za\b.{0,40}?(?:n[ºo]\s*)?(?:n[uú]m(?:ero)?)?\b.{0,12}?[:#]?\s*([A-Z0-9][A-Z0-9/\- ]{5,})"
    ),
    re.compile(
        r"(?is)\bn[ºo]\s*(?:de\s*)?pol[ií]za\b.{0,12}?[:#]?\s*([A-Z0-9][A-Z0-9/\- ]{5,})"
    ),
    re.compile(
        r"(?is)\bpolicy\b.{0,30}?\b(?:no|number)\b.{0,12}?[:#]?\s*([A-Z0-9][A-Z0-9/\- ]{5,})"
    ),
]
TOMADOR_RE_LIST = [
    re.compile(r"(?im)^\s*tomador(?:/a)?\s*[:#]?\s*(.+?)\s*$"),
    re.compile(r"(?im)^\s*asegurado(?:/a)?\s*[:#]?\s*(.+?)\s*$"),
]


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


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


def download_s3_pdf(key: str) -> bytes:
    client, bucket, _region = s3_client_and_conf()
    if not client:
        return b""
    resp = client.get_object(Bucket=bucket, Key=key)
    body = resp.get("Body")
    if not body:
        return b""
    data = body.read()
    return data or b""


def normalize_poliza_token(value: str) -> str:
    from web.server import normalize_poliza_key  # noqa: E402

    return normalize_poliza_key(value)


def normalize_company_token(value: str) -> str:
    from web.server import normalize_company_key  # noqa: E402

    return normalize_company_key(value)


def normalize_text_token(value: str) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^A-Z0-9 ]", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_words(text: str) -> list[str]:
    out: list[str] = []
    for raw in WORD_RE.findall(text or ""):
        token = normalize_text_token(raw).replace(" ", "")
        if token and token not in out:
            out.append(token)
    return out


def try_extract_poliza_numero(text: str) -> str:
    if not text:
        return ""
    for rx in POLIZA_RE_LIST:
        m = rx.search(text)
        if not m:
            continue
        cand = m.group(1) or ""
        cand = cand.strip()
        # limpia separadores pero conserva letras/números
        cand = re.sub(r"\s+", "", cand)
        cand = re.sub(r"[^A-Za-z0-9]", "", cand)
        norm = normalize_poliza_token(cand)
        if not norm or len(norm) < 6:
            continue
        # evita fechas tipo 20260330...
        if re.fullmatch(r"\d{8}", norm):
            continue
        return norm
    return ""


def try_extract_tomador(text: str) -> str:
    if not text:
        return ""
    for rx in TOMADOR_RE_LIST:
        m = rx.search(text)
        if not m:
            continue
        cand = (m.group(1) or "").strip()
        cand = cand.split("  ")[0].strip()
        cand = re.sub(r"\s+", " ", cand).strip()
        if len(cand) >= 6:
            return cand
    return ""


def extract_pdf_text_fast(pdf_path: str) -> tuple[str, str, str]:
    """
    Best-effort extraction:
      - first try `pdftotext -f 1 -l 2` (fast)
      - fallback to `extract_pdf_text` (may OCR if available)
    """
    from web.server import pdftotext_extract, extract_pdf_text  # noqa: E402

    text, err = pdftotext_extract(pdf_path, pages=2)
    if text and len(text.strip()) >= 30:
        return text, "", "pdftotext(2p)"
    full_text, full_err, src = extract_pdf_text(pdf_path)
    return full_text, full_err or err, src


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


def score_match(row, *, comp_hint: str, tomador_words: list[str]) -> tuple[int, int]:
    score = 0
    overlap = 0
    comp = normalize_company_token(row.get("compania") or "")
    if comp_hint and comp and comp == comp_hint:
        score += 6
    tom = normalize_text_token(row.get("tomador") or "").replace(" ", "")
    if tom and tomador_words:
        for w in tomador_words[:30]:
            if len(w) < 4:
                continue
            if w in tom:
                overlap += 1
        score += min(10, overlap)
    return score, overlap


def main():
    parser = argparse.ArgumentParser(
        description="Backfill: enlaza PDFs de S3 a seguros leyendo el contenido del PDF para extraer nº de póliza."
    )
    parser.add_argument("--empresa-id", required=True, help="empresa_id de Seguros.")
    parser.add_argument("--s3-prefix", default="seguros/", help="Prefijo S3 (default: seguros/).")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en DB (default).")
    parser.add_argument("--apply", action="store_true", help="Aplica updates en DB.")
    parser.add_argument("--limit", type=int, default=0, help="Limita nº de PDFs a procesar (0=sin límite).")
    parser.add_argument("--max-updates", type=int, default=0, help="Limita nº de updates (0=sin límite).")
    parser.add_argument("--max-pdfs", type=int, default=0, help="Alias de --limit (compat).")
    args = parser.parse_args()
    if not args.apply:
        args.dry_run = True
    if args.max_pdfs and not args.limit:
        args.limit = args.max_pdfs

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
    print(f"scanning_pdfs={len(keys)} seguros_rows={len(seguros)} dry_run={1 if args.dry_run else 0}", flush=True)

    by_poliza = defaultdict(list)
    missing_key_rows = []
    existing_keys = set()
    for s in seguros:
        if s.get("poliza_key"):
            existing_keys.add(s["poliza_key"])
        pol = normalize_poliza_token(s.get("poliza_numero") or "")
        if pol:
            by_poliza[pol].append(s["id"])
        if not (s.get("poliza_key") or s.get("poliza_url")):
            missing_key_rows.append(s)

    known_companies = {normalize_company_token(s.get("compania") or "") for s in missing_key_rows if (s.get("compania") or "").strip()}

    matched = []
    no_text = 0
    no_poliza = 0
    dup_poliza_in_s3 = 0
    ambiguous = 0
    assigned_by_guess = 0
    already_linked = 0
    poliza_counts = Counter()
    sources = Counter()

    used_seguros = set()
    used_polizas = set()

    for idx, key in enumerate(keys, start=1):
        if idx == 1 or idx % 10 == 0:
            # Progress heartbeat (important in Render shell; extraction can take time).
            print(
                f"progress scanned={idx}/{len(keys)} matched={len(matched)} "
                f"already_linked={already_linked} no_text={no_text} ambiguous={ambiguous}",
                flush=True,
            )
        if key in existing_keys:
            already_linked += 1
            continue
        pdf_bytes = download_s3_pdf(key)
        if not pdf_bytes:
            no_text += 1
            continue
        with tempfile.NamedTemporaryFile(prefix="poliza_", suffix=".pdf", delete=True) as tmp:
            tmp.write(pdf_bytes)
            tmp.flush()
            text, err, src = extract_pdf_text_fast(tmp.name)
        sources[src] += 1
        if not text or len(text.strip()) < 20:
            no_text += 1
            continue
        poliza = try_extract_poliza_numero(text)
        tomador_txt = try_extract_tomador(text)
        if poliza:
            poliza_counts[poliza] += 1
        if not poliza and not tomador_txt:
            no_poliza += 1
            continue
        if poliza and poliza in used_polizas:
            dup_poliza_in_s3 += 1
            continue

        chosen_id = ""
        chosen_poliza = poliza or ""

        # 1) Match directo por número de póliza
        if poliza:
            ids = by_poliza.get(poliza) or []
            if len(ids) == 1 and ids[0] not in used_seguros:
                chosen_id = ids[0]
            elif len(ids) > 1:
                ambiguous += 1
                continue

        # 2) Si no existe en DB, asigna a fila sin número por compañía/tomador
        if not chosen_id:
            tom_words = extract_words(tomador_txt or os.path.basename(key))
            comp_hint = ""
            # intenta detectar compañía por tokens en texto o nombre
            haystack = normalize_text_token(text[:8000] + " " + os.path.basename(key))
            for comp in sorted(known_companies, key=len, reverse=True):
                if comp and comp in haystack:
                    comp_hint = comp
                    break
            candidates = [r for r in missing_key_rows if not normalize_poliza_token(r.get("poliza_numero") or "") and r["id"] not in used_seguros]
            scored = []
            for r in candidates:
                score, overlap = score_match(r, comp_hint=comp_hint, tomador_words=tom_words)
                if score <= 0:
                    continue
                scored.append((score, overlap, r["id"]))
            scored.sort(reverse=True, key=lambda x: (x[0], x[1]))
            if not scored:
                no_match = True
                continue
            best = scored[0]
            if best[0] < 9 or best[1] < 2 or not comp_hint:
                # sin compañía+tomador fuerte no asignamos
                continue
            if len(scored) > 1 and (best[0] - scored[1][0]) < 2:
                ambiguous += 1
                continue
            chosen_id = best[2]
            assigned_by_guess += 1

        if not chosen_id:
            continue

        used_seguros.add(chosen_id)
        if chosen_poliza:
            used_polizas.add(chosen_poliza)
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        matched.append((chosen_id, key, public_url, chosen_poliza, src))
        if args.max_updates and args.max_updates > 0 and len(matched) >= args.max_updates:
            break

    now = datetime.now(timezone.utc).isoformat()
    print(f"ts={now}")
    print(f"empresa_id={empresa_id}")
    print(f"s3_bucket={bucket}")
    print(f"s3_region={region}")
    print(f"s3_prefix={prefix}")
    print(f"s3_pdfs_scanned={len(keys)}")
    print(f"seguros_total={len(seguros)}")
    print(f"seguros_missing_pdf={len([s for s in seguros if not (s.get('poliza_key') or s.get('poliza_url'))])}")
    print(f"db_poliza_candidates={len(by_poliza)}")
    print(f"matched_updates={len(matched)}")
    print(f"assigned_by_guess={assigned_by_guess}")
    print(f"ambiguous_skipped={ambiguous}")
    print(f"no_text={no_text}")
    print(f"no_poliza_and_no_tomador={no_poliza}")
    print(f"dup_poliza_in_s3_skipped={dup_poliza_in_s3}")
    print(f"already_linked_skipped={already_linked}")
    if sources:
        common = sources.most_common(8)
        print("text_sources_common=" + ",".join(f"{k}:{v}" for k, v in common))
    dupes = [(k, v) for k, v in poliza_counts.most_common(8) if v > 1]
    if dupes:
        print("poliza_dupes_common=" + ",".join(f"{k}:{v}" for k, v in dupes))

    if not matched:
        print("No se encontraron matches.")
        return

    if args.dry_run:
        print("dry_run=1 (no se aplican cambios)")
        print("sample:")
        for sid, key, _url, pol, src in matched[:15]:
            print(f"- seguro_id={sid} poliza={pol} src={src} key={key}")
        return

    applied = 0
    for seguro_id, key, url, poliza, _src in matched:
        conn.execute(
            """
            UPDATE seguros
            SET poliza_key = CASE WHEN COALESCE(TRIM(poliza_key), '') = '' THEN %s ELSE poliza_key END,
                poliza_url = CASE WHEN COALESCE(TRIM(poliza_url), '') = '' THEN %s ELSE poliza_url END,
                poliza_numero = CASE WHEN COALESCE(TRIM(poliza_numero), '') = '' AND %s IS NOT NULL THEN %s ELSE poliza_numero END,
                updated_at = %s
            WHERE id = %s
              AND (COALESCE(TRIM(poliza_key), '') = '' OR COALESCE(TRIM(poliza_url), '') = '')
            """,
            (key, url, poliza or None, poliza or None, now, seguro_id),
        )
        applied += 1
    conn.commit()
    print(f"applied_updates={applied}")


if __name__ == "__main__":
    main()
