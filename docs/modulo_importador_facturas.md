# Modulo Importador de Facturas

## Objetivo

Integrar la lectura automatica de facturas y tickets dentro del flujo actual de gestoria y contabilidad sin crear un sistema paralelo.

El modulo debe:

- recibir documentos de un cliente
- extraer datos contables minimos
- clasificar y detectar incidencias
- crear facturas y asientos solo cuando el documento este validado
- dejar trazabilidad completa del lote y de cada documento

## Encaje con el sistema actual

El modulo se apoya en tablas y flujos ya presentes:

- `gestoria_docs`
- `gestoria_terceros`
- `gestoria_facturas`
- `gestoria_asientos`
- `gestoria_asiento_lineas`
- `gestoria_contabilidad`
- exportacion Excel via `/api/gestoria_excel_plantilla`

Flujo objetivo:

1. entra un lote de documentos
2. se crean registros de control del lote y sus documentos
3. se ejecuta OCR, clasificacion y normalizacion
4. los documentos `OK` crean `gestoria_facturas` y `gestoria_asientos`
5. los documentos `REVISAR` quedan en bandeja
6. el usuario corrige o confirma
7. el sistema exporta la plantilla contable o lista libros e IVA

## Tablas nuevas

### `gestoria_import_lotes`

Control del lote de importacion.

Campos clave:

- `empresa_id`
- `cliente_id`
- `origen`
- `estado`
- `periodo`
- `carpeta_origen`
- `template_path`
- `total_documentos`
- `total_ok`
- `total_revisar`
- `total_duplicado`
- `total_error`

Estados sugeridos:

- `borrador`
- `procesando`
- `pendiente_revision`
- `aplicado`
- `cerrado`
- `error`

### `gestoria_import_documentos`

Registro unitario por documento procesado.

Campos clave:

- referencia al lote
- datos detectados: fecha, numero, tercero, NIF, base, IVA, total
- categoria detectada
- cuenta sugerida
- metodo OCR
- estado de revision
- motivos de revision
- regla aplicada
- enlace opcional a `gestoria_facturas` cuando ya fue aplicado

Estados sugeridos:

- `OK`
- `REVISAR`
- `DUPLICADO`
- `ERROR`
- `APLICADO`
- `RECHAZADO`

### `gestoria_import_reglas`

Reglas por empresa y cliente para normalizar proveedores y contabilidad.

Sirve para:

- forzar categoria
- forzar tercero
- forzar cuentas contables
- marcar `auto_ok`
- resolver proveedores OCRados con variantes

Ejemplos:

- si proveedor contiene `LEROY` => categoria `SUMINISTROS`, cuenta gasto `629`
- si proveedor contiene `GILDUSA` => categoria `ALQUILER LOCAL`, cuenta gasto `621`
- si nombre archivo contiene `factura_gapp` => ingreso emitido, no compra de cliente

### `gestoria_import_eventos`

Log de auditoria del lote y de cada documento.

Ejemplos:

- `ocr_done`
- `rule_applied`
- `flag_review`
- `duplicate_detected`
- `factura_created`
- `asiento_created`
- `manual_override`

## Adaptaciones en tablas existentes

No hace falta rediseñar `gestoria_facturas`, pero si conviene reutilizar y ampliar su trazabilidad:

- `estado_ocr` ya existe y debe reutilizarse
- `doc_key` ya existe y debe quedar como referencia documental
- `raw_text` ya existe y debe rellenarse desde el importador

Recomendado a medio plazo:

- añadir `import_documento_id` en `gestoria_facturas`
- añadir `origen_importacion` en `gestoria_facturas`
- añadir `estado_revision` visible en UI

## Flujo de estados

### Lote

1. `borrador`
2. `procesando`
3. `pendiente_revision`
4. `aplicado`
5. `cerrado`

### Documento

1. `OK`
2. `REVISAR`
3. `DUPLICADO`
4. `ERROR`
5. `APLICADO`
6. `RECHAZADO`

Regla operativa:

- solo `OK` puede pasar automaticamente a `APLICADO`
- `REVISAR` necesita confirmacion humana
- `DUPLICADO` nunca crea factura ni asiento
- `ERROR` queda para reintento o descarte

## Endpoints a crear

### `POST /api/gestoria_import/lotes`

Crea un lote y devuelve `lote_id`.

Payload minimo:

```json
{
  "empresa_id": "...",
  "cliente_id": "...",
  "origen": "upload_web",
  "periodo": "2026-02"
}
```

### `POST /api/gestoria_import/lotes/{id}/documentos`

Adjunta documentos al lote.

Puede aceptar:

- `multipart/form-data`
- `s3_key`
- lista de rutas internas si el proceso es batch

### `POST /api/gestoria_import/lotes/{id}/procesar`

Ejecuta OCR, clasificacion y reglas.

Resultado:

- resumen del lote
- documentos `OK`
- documentos `REVISAR`
- documentos `DUPLICADO`

### `GET /api/gestoria_import/lotes/{id}`

Resumen del lote.

### `GET /api/gestoria_import/lotes/{id}/documentos`

Listado paginado de documentos con filtros:

- `estado_revision`
- `categoria_detectada`
- `tercero_detectado`

### `POST /api/gestoria_import/documentos/{id}/resolver`

Permite correccion manual.

Payload sugerido:

```json
{
  "estado_revision": "OK",
  "tercero_nombre_forzado": "INTHER Herramientas y Sistemas SLU",
  "total_detectado": 2.48,
  "categoria_detectada": "SUMINISTROS",
  "cuenta_gasto_forzada": "629"
}
```

### `POST /api/gestoria_import/lotes/{id}/aplicar`

Convierte documentos `OK` en:

- `gestoria_facturas`
- `gestoria_asientos`
- `gestoria_asiento_lineas`
- `gestoria_contabilidad`

## Reglas contables por cliente

El modulo necesita una capa configurable por cliente.

Minimo viable:

- cuenta de proveedor por defecto
- cuenta de gasto por categoria
- porcentaje IVA por defecto
- lista de proveedores conocidos
- prefijos o textos que significan duplicado o gasto no importable

Configuracion recomendada por cliente:

- `ALQUILER LOCAL` -> `621`
- `SUMINISTROS` -> `628` o `629`
- `SEGURO RC` -> `625`
- `GESTORIA` -> `623`

Esto no debe ir hardcodeado en OCR. Debe vivir en `gestoria_import_reglas`.

## Pantallas necesarias

### Bandeja de lotes

Muestra:

- cliente
- periodo
- estado
- resumen `OK / REVISAR / DUPLICADO`

### Bandeja de revision

Muestra por documento:

- vista previa
- proveedor detectado
- numero, fecha, base, IVA, total
- categoria propuesta
- motivos de revision
- accion `aprobar / corregir / rechazar`

### Reglas

Pantalla para:

- buscar proveedor
- normalizar alias
- fijar cuentas
- marcar autoaprobacion

## Orden de implementacion recomendado

### Fase 1

- tablas nuevas
- guardado de lotes y documentos
- procesado batch desde script
- informe CSV y JSON

### Fase 2

- endpoint para crear lote y procesarlo
- UI de lotes
- UI de revision

### Fase 3

- aplicar documentos `OK` a `gestoria_facturas` y `gestoria_asientos`
- exportacion a plantilla contable desde el sistema

### Fase 4

- reglas por cliente y proveedor editables en UI
- autoaprendizaje controlado

## Decisiones abiertas

- si el destino oficial sera siempre `gestoria_facturas` o a veces solo Excel
- si el `cliente_id` es obligatorio en todos los lotes
- si la deduplicacion se hara por hash, numero de factura o ambas
- si la validacion manual queda en el equipo interno o se abre al cliente

## Estado actual en local

Ya estan implementados en local:

- tablas `gestoria_import_lotes`, `gestoria_import_documentos`, `gestoria_import_reglas`, `gestoria_import_eventos`
- endpoints backend:
  - `POST /api/gestoria_import_lotes`
  - `POST /api/gestoria_import_documentos_bulk`
  - `POST /api/gestoria_import_documento_resolver`
  - `POST /api/gestoria_import_aplicar`
  - `GET /api/gestoria_import_lotes`
  - `GET /api/gestoria_import_documentos`
- trazabilidad en `gestoria_facturas` con:
  - `import_documento_id`
  - `origen_importacion`
- importador batch en `scripts/build_gapp_facturas_excel.py`

## Flujo local de prueba

### 1. Generar Excel y detalle de revision

```bash
python3 scripts/build_gapp_facturas_excel.py \
  --input-dir '/ruta/a/facturas' \
  --template '/ruta/a/GAPP.xlsx' \
  --output-excel reports/gapp_import_preview.xlsx \
  --output-csv reports/gapp_import_review.csv \
  --output-json reports/gapp_import_review.json
```

### 2. Cargar el lote directamente en la base local

```bash
python3 scripts/build_gapp_facturas_excel.py \
  --input-dir '/ruta/a/facturas' \
  --template '/ruta/a/GAPP.xlsx' \
  --output-excel reports/gapp_import_preview.xlsx \
  --output-csv reports/gapp_import_review.csv \
  --output-json reports/gapp_import_review.json \
  --import-to-db \
  --empresa-ref 'Nombre o ID empresa' \
  --cliente-id 'cliente_id' \
  --periodo '2026-03'
```

### 3. Cargar y aplicar automaticamente los `OK`

```bash
python3 scripts/build_gapp_facturas_excel.py \
  --input-dir '/ruta/a/facturas' \
  --template '/ruta/a/GAPP.xlsx' \
  --output-excel reports/gapp_import_preview.xlsx \
  --output-csv reports/gapp_import_review.csv \
  --output-json reports/gapp_import_review.json \
  --import-to-db \
  --apply-ok-to-db \
  --empresa-ref 'Nombre o ID empresa' \
  --cliente-id 'cliente_id' \
  --periodo '2026-03'
```

Resultado esperado del paso 3:

- se crea un lote en `gestoria_import_lotes`
- se insertan los documentos del OCR en `gestoria_import_documentos`
- solo los documentos `OK` crean:
  - `gestoria_facturas`
  - `gestoria_asientos`
  - `gestoria_asiento_lineas`
  - `gestoria_contabilidad`
- los `REVISAR`, `DUPLICADO` y `ERROR` no se aplican
