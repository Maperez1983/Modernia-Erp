# OneDrive → S3 → OCR (Cron en Render)

Este repo incluye `scripts/onedrive_facturas_cron.py` para importar facturas desde OneDrive (cuenta personal) usando Microsoft Graph, subirlas a S3 y lanzar OCR en el CRM.

## Variables de entorno (Cron Job)

Necesarias:
- `CRM_BASE_URL`: URL pública del CRM (ej. `https://modernia-erp-2.onrender.com`)
- `APP_INGEST_API_KEY`: API key para `/api/ingest_facturas_ocr`
- `ONEDRIVE_CLIENT_ID`
- `ONEDRIVE_CLIENT_SECRET`
- `ONEDRIVE_REFRESH_TOKEN`
- `ONEDRIVE_FACTURAS_ROOT_PATH`: ruta en OneDrive a la carpeta FACTURAS (ej. `ESTUDIO VELAZQUEZ/FACTURAS`)

Recomendadas:
- `ONEDRIVE_SCOPES`: por defecto `offline_access User.Read Files.Read.All`
- `ONEDRIVE_EMPRESA_ALIAS`: si no se define, se infiere del root path antes de `/FACTURAS`
- `ONEDRIVE_SOURCE`: por defecto `onedrive`

S3 (ya usado por el CRM):
- `AWS_S3_BUCKET`
- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

DB (para guardar estado `deltaLink` y tokens en `crm_meta`):
- `DATABASE_URL`/`POSTGRES_URL` y `APP_DB_BACKEND=postgres` (igual que el web service)

## Comando del Cron

En Render, crea un **Cron Job** apuntando a este repo/branch y usa:

```bash
python3 scripts/onedrive_facturas_cron.py
```

El script usa Microsoft Graph delta queries para procesar solo cambios y guarda el estado en `crm_meta`.

