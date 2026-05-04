#!/usr/bin/env python3
"""
Importa un extracto PDF de BBVA (Movimientos) como contabilidad de Seguros.

Objetivo (Seguros):
  - Usar el extracto bancario como fuente de verdad de Ingresos/Gastos.
  - Las comisiones bancarias se consideran GASTO.
  - Idempotencia: no duplica movimientos si se reimporta el mismo extracto.

Soporta PDFs "multipart" (algunos downloads de BBVA envuelven el PDF con cabeceras).

Ejecución (Render/producción):
  export DATABASE_URL='postgresql://...'
  PYTHONPATH=. python3 scripts/import_bbva_movimientos_seguros_pdf.py \
    --pdf \"/ruta/Unknown-6.pdf\" \
    --empresa-nombre-like \"Fincas Velazquez\" \
    --apply

Dry-run (sin DB):
  PYTHONPATH=. python3 scripts/import_bbva_movimientos_seguros_pdf.py --pdf \"/ruta/Unknown-6.pdf\" --no-db
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

from web.db_backend import open_postgres_conn
import web.server as srv


IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{4}\d{14,})\b")
ROW_RE = re.compile(
    r"^\s*([0-3]\d/[01]\d/20\d{2})\s+([0-3]\d/[01]\d/20\d{2})\s+(\d{5})\s+(.*?)\s+([+\-]?\d[\d\.\,]*)\s*EUR\s+([+\-]?\d[\d\.\,]*)\s*EUR\s*$",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unwrap_pdf_multipart(src_path: str) -> str:
    """
    Si el archivo no empieza por %PDF-, busca el primer %PDF- y corta desde ahí.
    Devuelve path a un PDF válido (puede ser el mismo si ya lo es).
    """
    with open(src_path, "rb") as f:
        head = f.read(8)
        f.seek(0)
        data = f.read()
    if head.startswith(b"%PDF-"):
        return src_path
    idx = data.find(b"%PDF-")
    if idx < 0:
        raise ValueError("No se encontró cabecera %PDF- en el archivo.")
    fd, out_path = tempfile.mkstemp(prefix="bbva_mov_", suffix=".pdf")
    os.close(fd)
    with open(out_path, "wb") as out:
        out.write(data[idx:])
    return out_path


def pdftotext_layout(pdf_path: str) -> str:
    """
    Usa `pdftotext -layout` para preservar columnas (BBVA movimientos).
    """
    try:
        out = subprocess.check_output(["pdftotext", "-layout", pdf_path, "-"], stderr=subprocess.STDOUT)
        return out.decode("utf-8", "ignore")
    except subprocess.CalledProcessError as exc:
        msg = (exc.output or b"").decode("utf-8", "ignore")
        raise RuntimeError(msg or "pdftotext falló") from exc


def parse_ddmmyyyy(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def parse_eur_amount(text: str) -> float:
    return float(srv.parse_money_value(text))


def resolve_empresa_id(conn, empresa_nombre_like: str) -> str:
    like = (empresa_nombre_like or "").strip() or "Fincas Velazquez"
    row = conn.execute(
        "SELECT id, nombre FROM empresas WHERE LOWER(COALESCE(nombre,'')) LIKE LOWER(%s) ORDER BY nombre LIMIT 1",
        (f"%{like}%",),
    ).fetchone()
    if not row:
        raise SystemExit(f"No se pudo resolver empresa_id con LIKE '%{like}%'.")
    return str(row["id"])


@dataclass
class BankMove:
    iban: str
    fecha_contable: str  # YYYY-MM-DD
    fecha_valor: str  # YYYY-MM-DD
    codigo: str
    concepto: str
    contraparte: str
    importe: float
    saldo: float | None

    def to_conta_tipo(self) -> str:
        return "Gasto" if self.importe < 0 else "Ingreso"

    def to_conta_importe(self) -> float:
        return abs(float(self.importe))

    def stable_key(self) -> str:
        base = "|".join(
            [
                self.iban,
                self.fecha_contable,
                self.fecha_valor,
                self.codigo,
                str(round(float(self.importe), 2)),
                str(round(float(self.saldo or 0.0), 2)),
                (self.concepto or "").strip().upper(),
                (self.contraparte or "").strip().upper(),
            ]
        )
        return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()


def parse_bbva_movimientos_text(text: str) -> tuple[str, list[BankMove]]:
    raw_lines = [ln.rstrip("\n") for ln in (text or "").splitlines()]
    lines = [ln.rstrip() for ln in raw_lines if str(ln or "").strip()]

    iban = ""
    for ln in lines[:250]:
        m = IBAN_RE.search(ln)
        if m:
            iban = m.group(1)
            break

    moves: list[BankMove] = []
    current: BankMove | None = None

    def flush():
        nonlocal current
        if current:
            current.concepto = re.sub(r"\s+", " ", current.concepto or "").strip()
            current.contraparte = re.sub(r"\s+", " ", current.contraparte or "").strip()
            moves.append(current)
            current = None

    for ln in lines:
        m = ROW_RE.match(ln)
        if m:
            flush()
            f_cont = parse_ddmmyyyy(m.group(1))
            f_val = parse_ddmmyyyy(m.group(2))
            codigo = m.group(3)
            concepto_blob = (m.group(4) or "").strip()
            imp_raw = m.group(5)
            saldo_raw = m.group(6)
            concepto = concepto_blob
            contraparte = ""
            if "|" in concepto_blob:
                left, right = concepto_blob.split("|", 1)
                concepto = left.strip()
                contraparte = right.strip()
            importe = parse_eur_amount(imp_raw)
            saldo = None
            try:
                saldo = parse_eur_amount(saldo_raw)
            except Exception:
                saldo = None
            current = BankMove(
                iban=iban,
                fecha_contable=f_cont,
                fecha_valor=f_val,
                codigo=codigo,
                concepto=concepto,
                contraparte=contraparte,
                importe=float(importe),
                saldo=saldo,
            )
            continue
        if current:
            if "F. CONTABLE" in ln or "CONCEPTO" in ln or "IMPORTE" in ln or "SALDO" in ln:
                continue
            current.concepto = (current.concepto + " " + ln.strip()).strip()

    flush()
    return iban, moves


def is_bank_commission(move: BankMove) -> bool:
    blob = srv.normalize_lookup_text(f"{move.concepto} {move.contraparte}")
    return any(token in blob for token in ("COMISION", "COMISIÓN", "GASTOS", "MANTENIMIENTO", "ADMINISTRACION", "ADMINISTRACIÓN"))


def contabilidad_exists(conn, empresa_id: str, stable_key: str) -> bool:
    marker = f"[SEGUROS][BANCO] key={stable_key}"
    row = conn.execute(
        "SELECT id FROM gestoria_contabilidad WHERE empresa_id=%s AND COALESCE(notas,'') LIKE %s LIMIT 1",
        (empresa_id, f"%{marker}%"),
    ).fetchone()
    return bool(row)


def insert_contabilidad(conn, empresa_id: str, move: BankMove, *, dry_run: bool) -> str | None:
    stable = move.stable_key()
    if contabilidad_exists(conn, empresa_id, stable):
        return None
    tipo = move.to_conta_tipo()
    importe = move.to_conta_importe()
    gestion = "Banco seguros"
    if is_bank_commission(move):
        gestion = "Comisiones bancarias"
        tipo = "Gasto"
    concepto = (move.concepto or "").strip() or "Movimiento banco"
    notas = (
        f"[SEGUROS][BANCO] key={stable} "
        f"IBAN={move.iban} COD={move.codigo} FVAL={move.fecha_valor} "
        + (f"SALDO={move.saldo}" if move.saldo is not None else "")
        + (f" · {move.contraparte}" if move.contraparte else "")
    )
    if dry_run:
        return stable
    row_id = os.urandom(16).hex()
    conn.execute(
        """
        INSERT INTO gestoria_contabilidad (
          id, empresa_id, cliente_id, hipoteca_id, seguro_id, poliza_numero,
          fecha, concepto, gestion, tipo, importe, notas,
          cliente_ids_json, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            row_id,
            empresa_id,
            None,
            None,
            None,
            None,
            move.fecha_contable,
            concepto,
            gestion,
            tipo,
            float(importe),
            notas,
            None,
            now_iso(),
            now_iso(),
        ),
    )
    return row_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="Ruta al PDF (o multipart que contenga PDF).")
    parser.add_argument("--empresa-nombre-like", default="Fincas Velazquez", help="Resolver empresa_id por nombre LIKE.")
    parser.add_argument("--empresa-id", default="", help="empresa_id explícito (si se pasa, no resuelve por nombre).")
    parser.add_argument("--no-db", action="store_true", help="Solo parsea y muestra resumen; no conecta a la BD.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en DB.")
    parser.add_argument("--apply", action="store_true", help="Escribe en DB.")
    args = parser.parse_args()
    dry_run = bool(args.dry_run) or (not args.apply)

    conn = None
    empresa_id = (args.empresa_id or "").strip()
    if not args.no_db:
        setattr(srv, "__crm_backend__", "postgres")
        conn = open_postgres_conn(with_row_factory=True)
        if not empresa_id:
            empresa_id = resolve_empresa_id(conn, args.empresa_nombre_like)

    src_path = os.path.expanduser(args.pdf)
    pdf_path = unwrap_pdf_multipart(src_path)
    try:
        text = pdftotext_layout(pdf_path)
        iban, moves = parse_bbva_movimientos_text(text)
        print(f"[{now_iso()}] empresa_id={empresa_id or '-'} iban={iban or '-'} movimientos_detectados={len(moves)} dry_run={dry_run} no_db={bool(args.no_db)}")
        if args.no_db:
            for mv in moves[:8]:
                print(
                    {
                        "fecha": mv.fecha_contable,
                        "codigo": mv.codigo,
                        "tipo": mv.to_conta_tipo(),
                        "importe": mv.importe,
                        "concepto": mv.concepto,
                        "contraparte": mv.contraparte,
                    }
                )
            print({"detected": len(moves), "dry_run": True, "no_db": True})
            return

        inserted = skipped = 0
        for mv in moves:
            res = insert_contabilidad(conn, empresa_id, mv, dry_run=dry_run)
            if res:
                inserted += 1
            else:
                skipped += 1
        if (not dry_run) and conn:
            conn.commit()
        print({"detected": len(moves), "inserted": inserted, "skipped": skipped, "dry_run": dry_run})
    finally:
        if pdf_path != src_path:
            try:
                os.unlink(pdf_path)
            except Exception:
                pass


if __name__ == "__main__":
    main()

