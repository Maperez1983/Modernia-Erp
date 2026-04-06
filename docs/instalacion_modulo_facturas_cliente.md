# Instalación · Módulo “Carga de facturas” para clientes (Portal + Inbox)

Objetivo: que un cliente pueda subir facturas (foto/PDF) desde móvil y que entren en vuestro flujo (S3 + OCR + revisión), sin exponer el CRM interno.

## Qué módulos activar

En el **workspace del cliente**, habilita:

- `portal_cliente` (para que el cliente suba documentación)
- `facturas_recibidas` (para que el equipo reciba/triagee en inbox)
- `documental` (para el repositorio/gestión de documentos)
- (opcional) `facturacion` (si además vais a llevar facturación/cobros del cliente dentro del workspace)

## Configuración técnica (Render / producción)

Requisitos:

- S3 operativo (para almacenar los ficheros)
- OCR operativo (Google Vision recomendado si hay API key)

Variables típicas:

- `AWS_S3_BUCKET`
- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `GOOGLE_VISION_API_KEY` (si se usa Vision por API key)

## Alta del cliente en el portal

1) Ir a `Workspaces` → pestaña `Motores` → `Portal cliente`.
2) Seleccionar el cliente final y pulsar `Activar portal`.
3) Copiar y enviar el enlace público al cliente con el token generado.

Formato del enlace público:

- `https://crm.verifika2.com/?portal_token=TOKEN`

Ese enlace abre el portal “solo cliente” (sin login CRM) y permite subir archivos.

## Subida de facturas por el cliente

En el portal público, el cliente puede:

- Subir **PDF** o **imagen** (cámara del móvil)
- Indicar `Clasificación` (recomendado: `Factura`, `Ticket`, `Recibo`)
- (opcional) asociarlo a un `Requerimiento` si lo habéis creado

Al enviar:

- El archivo se sube a S3.
- Se crea el documento en el workspace y queda **en revisión interna**.
- Si el OCR está activo, se encola un proceso OCR (y el portal muestra el estado).

## Flujo interno (equipo)

1) Ir a `Motores` → `Facturas recibidas` → `Inbox de entrada`.
2) Verás los documentos entrantes (canal `Portal`).
3) Clasificar/asignar (y lanzar OCR manual si hace falta).

## Recomendación de operativa (para que sea “instalable”)

- Crea una automatización `portal_client_invited` que genere un requerimiento “Subir facturas” mensual/trimestral.
- Crea una automatización `document_uploaded` que:
  - marque prioridad “Alta” si `clasificacion=Factura`
  - asigne responsable por cliente/empresa

