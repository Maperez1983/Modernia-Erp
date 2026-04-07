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
WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
STOPWORD_TOKENS = {
    "POLIZA",
    "POLIZAS",
    "SEGURO",
    "SEGUROS",
    "DOCUMENTO",
    "DOC",
    "PDF",
    "SCAN",
    "ESCANEO",
    "ESCANEO",
    "FIRMADO",
    "FIRMADA",
    "MODERNIA",
    "MALAGA",
    "MÁLAGA",
    "FINANCIACIONES",
    "FINANCIACION",
    "HIPOTECA",
    "HIPOTECAS",
    "GESTORIA",
    "RENTA",
}
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


def normalize_company_token(value: str) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\s+", " ", text).strip()
    # mantén letras/números (algunas compañías llevan números)
    text = re.sub(r"[^A-Z0-9 ]", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_ramo_token(value: str) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^A-Z ]", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_date_token(token: str) -> bool:
    t = str(token or "").strip()
    if not re.fullmatch(r"\d{8}", t):
        return False
    year = int(t[:4])
    month = int(t[4:6])
    day = int(t[6:8])
    return 2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31


def infer_ramo_from_filename(name: str) -> str:
    key = normalize_ramo_token(name)
    if not key:
        return ""
    if "IMPAGO" in key or "PROTECCION" in key or "PROTECCIÓN" in key:
        return "PROTECCIÓN DE PAGOS"
    if "DEFENSA" in key or "JURID" in key or "ARAG" in key:
        return "DEFENSA JURÍDICA"
    if "SALUD" in key or "SANIT" in key or "DKV" in key:
        return "SALUD"
    if "DECES" in key:
        return "DECESOS"
    if "ACCIDENT" in key:
        return "ACCIDENTES"
    if "VIDA" in key:
        return "VIDA"
    if "AHORRO" in key:
        return "AHORRO"
    if "VIAJE" in key or "VIAJ" in key:
        return "VIAJE"
    if "COMUNIDAD" in key:
        return "COMUNIDAD"
    if "COMERCIO" in key or "PYME" in key or "LOCAL" in key:
        return "COMERCIO"
    if "HOGAR" in key:
        return "HOGAR"
    if "AUTO" in key or "AUTOMOV" in key or "VEHIC" in key or "MOTO" in key or "MOTOR" in key:
        return "AUTO"
    if "RC" in key or "RESPONSABILIDAD" in key:
        return "RESPONSABILIDAD CIVIL"
    return ""


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
        if norm in STOPWORD_TOKENS:
            continue
        tokens.append(norm)
    # orden estable y únicos
    out = []
    for t in tokens:
        if t not in out:
            out.append(t)
    return out


def extract_words_from_filename(name: str) -> list[str]:
    text = str(name or "")
    out: list[str] = []
    for raw in WORD_RE.findall(text):
        token = normalize_company_token(raw).replace(" ", "").strip()
        if not token:
            continue
        if token in STOPWORD_TOKENS:
            continue
        if token not in out:
            out.append(token)
    return out


def pick_poliza_candidate(tokens: list[str]) -> str:
    best = ""
    for tok in tokens:
        t = normalize_poliza_token(tok)
        if not t:
            continue
        if is_date_token(t):
            continue
        # Evita confundir timestamps cortos.
        if re.fullmatch(r"\d{6}", t):
            continue
        has_digit = any(ch.isdigit() for ch in t)
        if not has_digit:
            continue
        if len(t) > len(best):
            best = t
    return best


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

    # Índices para fuzzy-match cuando la póliza en DB no tiene `poliza_numero`.
    missing_rows = []
    by_comp_ramo = defaultdict(list)
    known_companies = set()
    for s in missing:
        comp = normalize_company_token(s.get("compania") or "")
        ramo = normalize_ramo_token(s.get("ramo") or "")
        tom = normalize_company_token(s.get("tomador") or "").replace(" ", "")
        row = {
            "id": s["id"],
            "compania": comp,
            "ramo": ramo,
            "tomador": tom,
            "raw_compania": s.get("compania") or "",
            "raw_ramo": s.get("ramo") or "",
            "raw_tomador": s.get("tomador") or "",
        }
        missing_rows.append(row)
        by_comp_ramo[(comp, ramo)].append(row)
        if comp:
            known_companies.add(comp)

    matched = []
    ambiguous = 0
    no_match = 0
    token_hits = Counter()
    used_seguros = set()
    used_polizas = set()
    matched_direct = 0
    matched_fuzzy = 0
    fuzzy_no_candidate = 0
    fuzzy_ambiguous = 0
    poliza_candidate_counts = Counter()
    pdfs_with_candidate = 0
    skipped_non_seguros = 0

    for key in keys:
        name = original_filename_from_key(key)
        # Ignora documentos claramente fuera de Seguros aunque estén en el prefijo.
        upper_name = normalize_company_token(name)
        if any(word in upper_name for word in ("FINANCIACIONES", "HIPOTECA", "HIPOTECAS", "NOMINA", "NÓMINA", "RENTA", "IRPF")):
            skipped_non_seguros += 1
            no_match += 1
            continue
        tokens = extract_tokens_from_filename(name)
        poliza_candidate = pick_poliza_candidate(tokens)
        if poliza_candidate:
            pdfs_with_candidate += 1
            poliza_candidate_counts[poliza_candidate] += 1
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
        if chosen:
            matched_direct += 1
        if not chosen:
            # Fuzzy-match: si el PDF tiene nº de póliza pero en DB falta, intentamos enlazar
            # usando compañía/ramo/tomador por similitud.
            if not poliza_candidate:
                fuzzy_no_candidate += 1
                no_match += 1
                continue
            if poliza_candidate in used_polizas:
                # ya usado por otro match; evita duplicados.
                no_match += 1
                continue
            words = extract_words_from_filename(name)
            comp_hint = ""
            for comp in sorted(known_companies, key=len, reverse=True):
                if comp and comp.replace(" ", "") in upper_name.replace(" ", ""):
                    comp_hint = comp
                    break
            ramo_hint = infer_ramo_from_filename(name)
            candidates = []
            if comp_hint or ramo_hint:
                candidates = by_comp_ramo.get((comp_hint, ramo_hint), []) or by_comp_ramo.get((comp_hint, ""), []) or []
            if not candidates:
                candidates = missing_rows
            scored = []
            for row in candidates:
                if row["id"] in used_seguros:
                    continue
                score = 0
                if comp_hint and row["compania"] and row["compania"] == comp_hint:
                    score += 4
                if ramo_hint and row["ramo"] and ramo_hint and row["ramo"] == ramo_hint:
                    score += 3
                # overlap tomador tokens
                tom = row["tomador"] or ""
                if tom and words:
                    overlap = 0
                    for w in words[:20]:
                        if len(w) < 4:
                            continue
                        if w in tom:
                            overlap += 1
                    score += min(8, overlap)
                scored.append((score, row["id"]))
            scored.sort(reverse=True, key=lambda x: x[0])
            if not scored or scored[0][0] < 6:
                no_match += 1
                continue
            # Si el segundo está muy cerca, lo consideramos ambiguo.
            if len(scored) > 1 and (scored[0][0] - scored[1][0]) < 2:
                fuzzy_ambiguous += 1
                no_match += 1
                continue
            chosen = scored[0][1]
            chosen_token = poliza_candidate
            matched_fuzzy += 1

        if not chosen:
            no_match += 1
            continue
        used_seguros.add(chosen)
        if chosen_token:
            used_polizas.add(chosen_token)
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        matched.append((chosen, key, public_url, chosen_token, name))

    now = datetime.now(timezone.utc).isoformat()
    print(f"ts={now}")
    print(f"empresa_id={empresa_id}")
    print(f"s3_bucket={bucket}")
    print(f"s3_region={region}")
    print(f"s3_prefix={prefix}")
    print(f"s3_pdfs_scanned={len(keys)}")
    print(f"s3_pdfs_skipped_non_seguros={skipped_non_seguros}")
    print(f"seguros_total={len(seguros)}")
    print(f"seguros_missing_pdf={len(missing)}")
    print(f"candidates_by_poliza={len(by_poliza)}")
    print(f"s3_pdfs_with_poliza_candidate={pdfs_with_candidate}")
    print(f"s3_poliza_candidates_unique={len(poliza_candidate_counts)}")
    dupes = [(k, v) for k, v in poliza_candidate_counts.most_common(8) if v > 1]
    if dupes:
        print("s3_poliza_candidates_dupes=" + ",".join(f"{k}:{v}" for k, v in dupes))
    print(f"matched_updates={len(matched)}")
    print(f"matched_direct={matched_direct}")
    print(f"matched_fuzzy={matched_fuzzy}")
    print(f"fuzzy_no_poliza_candidate={fuzzy_no_candidate}")
    print(f"fuzzy_ambiguous={fuzzy_ambiguous}")
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
    for seguro_id, key, url, tok, _name in matched:
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
                poliza_numero = CASE
                  WHEN COALESCE(TRIM(poliza_numero), '') = '' THEN %s
                  ELSE poliza_numero
                END,
                updated_at = %s
            WHERE id = %s
              AND (
                COALESCE(TRIM(poliza_key), '') = '' OR LOWER(TRIM(poliza_key)) IN ('poliza_key', 'doc_key')
                OR COALESCE(TRIM(poliza_url), '') = '' OR LOWER(TRIM(poliza_url)) IN ('poliza_url', 'doc_url')
              )
            """,
            (key, url, tok or None, now, seguro_id),
        )
        updated += 1
    conn.commit()
    print(f"applied_updates={updated}")


if __name__ == "__main__":
    main()
