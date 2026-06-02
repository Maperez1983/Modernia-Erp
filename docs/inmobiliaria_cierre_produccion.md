# Cierre Producción CRM Inmobiliario

## Configuración Externa

Variables necesarias para activar comunicaciones reales:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM`

Variables opcionales para SMS/WhatsApp mediante webhook:

- `SIGNATURE_SMS_WEBHOOK_URL`
- `SIGNATURE_WHATSAPP_WEBHOOK_URL`
- `SIGNATURE_WEBHOOK_SECRET`

Feed externo:

- `INMO_EXTERNAL_FEED_TOKEN`

Firma externa avanzada:

- `SIGNATURE_PROVIDER`
- Configuración propia del proveedor seleccionado.

## Comprobaciones

Ejecutar smoke de producción:

```bash
CRM_E2E_URL='https://crm.verifika2.com/?swcleared=1' \
CRM_E2E_USER='usuario' \
CRM_E2E_PASS='password' \
.venv/bin/python scripts/prod_inmo_smoke.py
```

Endpoints de diagnóstico:

- `/api/inmueble_signature_config`
- `/api/inmueble_portal_feed?format=json&token=...`
- `/api/inmueble_portal_feed?format=xml&token=...`

## Flujo Manual Final

1. Crear inmueble de prueba.
2. Pasarlo a Encargo.
3. Generar expediente completo.
4. Solicitar firma de un documento.
5. Confirmar envío por email/SMS/WhatsApp si están configurados.
6. Firmar desde enlace público.
7. Verificar justificante en documentos del inmueble.
8. Publicar en Verifika2.
9. Enviar lead desde portal público.
10. Comprobar que se crea demanda/comprador y relación con inmueble.

## Revisión Legal

Las plantillas generadas deben validarse jurídicamente antes de uso operativo general:

- Nota de encargo venta/alquiler.
- Documento informativo abreviado/DIA.
- Justificación de precio.
- Hoja de visita.
- Reconocimiento de honorarios.
- Textos de aceptación de firma.

La firma interna deja trazabilidad técnica, pero no sustituye por sí sola a una firma cualificada eIDAS. Para firma avanzada/cualificada debe integrarse un prestador externo.
