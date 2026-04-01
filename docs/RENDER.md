# Render (SQLite o Postgres) · Guía rápida

Este repo es **público**. No subas bases de datos reales (`.sqlite`) ni seeds con datos personales.

## 1) Elegir backend de DB

El ERP soporta:

- **SQLite** (por fichero) usando `DB_PATH`
- **Postgres** (recomendado para escalar) usando `DATABASE_URL` o `POSTGRES_URL`

Si configuras `DATABASE_URL` / `POSTGRES_URL`, el servidor usa Postgres automáticamente.

## 2) Persistencia (si usas SQLite y/o OCR)

En Render, la filesystem del contenedor es efímera. Para mantener DB por fichero y/o cola OCR, monta un **disco persistente** y apunta a rutas dentro del disco:

- Variable: `DB_PATH=/var/data/erp.sqlite`
- (Opcional) `OCR_DB_PATH=/var/data/ocr_jobs.sqlite`

Si usas Postgres, `DB_PATH` sigue siendo útil para `OCR_DB_PATH` y para datos temporales, pero **la DB principal** vive en Postgres.

## 3) Seed demo (sin PII)

Crea un workspace + empresas demo + usuarios demo + una solicitud de vacaciones pendiente:

```bash
python3 scripts/seed_demo_data.py --db "$DB_PATH" --yes
```

Si quieres regenerar contraseñas demo y que las imprima:

```bash
python3 scripts/seed_demo_data.py --db "$DB_PATH" --yes --reset-passwords
```

Con Postgres, puedes pasar cualquier `--db` (se ignora), pero conviene mantener `DB_PATH` apuntando al disco si también usas OCR.

## 4) Migrar datos (SQLite → Postgres)

Si vienes de SQLite (por ejemplo `DB_PATH=/var/data/erp.sqlite`) y quieres mover esos datos a Postgres:

```bash
python3 scripts/migrate_sqlite_to_postgres.py --sqlite "$DB_PATH" --truncate --yes
```

## 5) Arranque

Render suele inyectar `PORT`. El servidor ya lo respeta:

```bash
python3 web/server.py --db "$DB_PATH" --port "$PORT"
```
