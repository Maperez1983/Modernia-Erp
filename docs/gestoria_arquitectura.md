# Arquitectura de Gestoria

## Objetivo

Separar gestoría en dominios claros para evitar mezclar CRM, documentación, OCR y contabilidad.

## Dominios

### 1. Gestoria CRM

Responsabilidad:
- relación comercial y operativa con el cliente
- módulos contratados
- modelos, trabajos y agenda

Tablas:
- `cliente_gestoria`
- `gestoria_modelos`
- `gestoria_trabajos`

### 2. Gestoria Docs

Responsabilidad:
- documentación general del cliente
- documentos manuales o adjuntos no contables

Tabla fuente:
- `gestoria_docs`

### 3. Gestoria Importador

Responsabilidad:
- entrada masiva de facturas
- OCR
- revisión
- trazabilidad
- reglas

Tablas fuente:
- `gestoria_import_lotes`
- `gestoria_import_documentos`
- `gestoria_import_reglas`
- `gestoria_import_eventos`

Regla:
- un documento importado no es contabilidad final
- solo representa una lectura pendiente o validada

### 4. Gestoria Contabilidad

Responsabilidad:
- terceros
- facturas validadas
- asientos
- líneas contables
- exportación

Tablas fuente:
- `gestoria_terceros`
- `gestoria_facturas`
- `gestoria_asientos`
- `gestoria_asiento_lineas`

Tabla derivada o auxiliar:
- `gestoria_contabilidad`

## Fuentes de verdad

- documento manual: `gestoria_docs`
- documento OCR/importado: `gestoria_import_documentos`
- factura contable aceptada: `gestoria_facturas`
- asiento contable real: `gestoria_asientos` + `gestoria_asiento_lineas`

## Flujo correcto

1. Documento entra por `gestoria_docs` o por `gestoria_import_documentos`.
2. Si entra por importador, se revisa y clasifica.
3. Solo los documentos `OK` crean `gestoria_facturas`.
4. Desde la factura se generan `gestoria_asientos` y `gestoria_asiento_lineas`.
5. La exportación oficial sale desde la capa contable.

## Reglas de diseño

- no usar `gestoria_contabilidad` como fuente de verdad contable
- no meter lógica OCR directamente en la capa de libros
- no mezclar documentos manuales con documentos importados
- no crear UI nueva sin decidir antes en qué dominio vive

## UI recomendada

### Vista global de Gestoria

- CRM
- Trabajos
- Docs
- Contabilidad

### Vista de cliente Gestoria

- Entrada
- Importador
- Libros
- Control

## Siguientes mejoras razonables

- pantalla completa de importador con lotes, documentos y resolución
- reglas por proveedor/cliente visibles en UI
- estado formal de ciclo: `nuevo`, `preparado`, `aplicado`, `con_errores`, `cerrado`
- reducir dependencias de `web/server.py` moviendo lógica de gestoría a módulos propios
