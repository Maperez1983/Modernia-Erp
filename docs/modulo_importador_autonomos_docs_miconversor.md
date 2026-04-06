# Importador Autónomos (PDF/JPG → MiConversor)

Este importador procesa **facturas y tickets en PDF/JPG/PNG** y genera un Excel compatible con la plantilla **“Plantilla MiConversor (empresas).xlsx”**.

## Qué hace

- Busca recursivamente documentos con extensiones: `.pdf`, `.jpg`, `.jpeg`, `.png`.
- Extrae texto con:
  - `pdftotext` (si está disponible) y fallback a OCR para PDFs.
  - OCR (Tesseract) para imágenes.
- Parsea campos básicos (heurístico):
  - Fecha, nº factura, tercero, NIF, base, IVA, IRPF/retención, total.
- Rellena `Hoja1` de la plantilla MiConversor.
- Crea 2 hojas de control:
  - `CONTROL_LISTADO`: listado de documentos numerado y ordenado por fecha (incluye método/errores OCR).
  - `CONTROL_TOTALIZADOR`: totales (base, IVA, retenciones, nº facturas) + IVA soportado/repercutido.

## Requisitos

- Python 3
- Dependencias Python: `openpyxl` (ya en el proyecto).
- Para extraer texto:
  - `pdftotext` (opcional, mejora PDFs con texto embebido)
  - `tesseract` (recomendado para OCR de imágenes/PDF escaneado)
  - `pdftoppm` (para convertir PDF a imágenes si hay que hacer OCR)

## Uso

```bash
python3 scripts/import_docs_to_miconversor.py \
  --root "/ruta/con/facturas_y_tickets" \
  --template "/ruta/Plantilla MiConversor (empresas).xlsx" \
  --out reports/miconversor_autonomos_ocr.xlsx \
  --pdf-pages 2
```

## Notas

- Las columnas de domicilio/localidad/provincia/código postal se dejan vacías si no se detectan con fiabilidad.
- `SUBCUENTA` (tercero) se genera de forma **determinística** por NIF o nombre:
  - Compras → `410000001`, `410000002`, …
  - Ventas → `430000001`, `430000002`, …
- `SUBCUENTA GASTOS/INGRESOS` se infiere por descripción (6xx/7xx) y se deja como `xxx000000` por defecto.

