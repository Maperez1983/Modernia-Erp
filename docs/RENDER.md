# Render (SQLite) · Guía rápida

Este repo es **público**. No subas bases de datos reales (`.sqlite`) ni seeds con datos personales.

## 1) Persistencia de DB

En Render, la filesystem del contenedor es efímera. Para que el ERP mantenga usuarios/vacaciones, monta un **disco persistente** y apunta la DB ahí:

- Variable: `DB_PATH=/var/data/erp.sqlite`
- (Opcional) `OCR_DB_PATH=/var/data/ocr_jobs.sqlite`

## 2) Seed demo (sin PII)

Crea un workspace + empresas demo + usuarios demo + una solicitud de vacaciones pendiente:

```bash
python3 scripts/seed_demo_data.py --db "$DB_PATH" --yes
```

Si quieres regenerar contraseñas demo y que las imprima:

```bash
python3 scripts/seed_demo_data.py --db "$DB_PATH" --yes --reset-passwords
```

## 3) Arranque

Render suele inyectar `PORT`. El servidor ya lo respeta:

```bash
python3 web/server.py --db "$DB_PATH" --port "$PORT"
```

