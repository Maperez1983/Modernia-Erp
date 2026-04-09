# Importador Autónomos (Monitor AON → MiConversor)

Este módulo/script convierte los **exports en Excel tipo “DIARIO”** (Monitor AON) a la plantilla de contabilidad **“Plantilla MiConversor (empresas).xlsx”**.

## Qué hace

- Lee todos los ficheros `DIARIO*.xlsx` encontrados en una carpeta raíz.
- Agrupa asientos por `DOCUMENTO` y extrae:
  - `Fecha` (de la línea `Fecha: dd/mm/yyyy`)
  - `Nº factura` (de `N/Fra: ...`, si existe; si no, usa `DOCUMENTO`)
  - Subcuenta y nombre del tercero (cuentas `43xx/40xx/41xx/44xx`)
  - Base imponible (líneas que no son tercero / IVA / retención)
  - IVA (`472xxx` soportado, `477xxx` repercutido)
  - Retenciones (`473xxx`, `4750/4751`)
  - Total (desde la línea del tercero; fallback `base + iva - retención`)
- Rellena la hoja `Hoja1` de la plantilla con las columnas que exige MiConversor.
- Crea 2 hojas de control:
  - `CONTROL_LISTADO`: listado de facturas numeradas y ordenadas por fecha.
  - `CONTROL_TOTALIZADOR`: totales (base, IVA, retenciones, nº facturas) y desglose IVA soportado/repercutido.

## Requisitos

- Python 3
- `openpyxl` instalado (ya está en `requirements.txt` del proyecto).

## Uso

Generar un Excel por autónomo (por carpeta contenedora de un `DIARIO*.xlsx`):

```bash
python3 scripts/import_aon_diario_to_miconversor.py \
  --root "/ruta/AUTONOMOS - ORIGEN MONITOR AON" \
  --template "/ruta/Plantilla MiConversor (empresas).xlsx" \
  --out-dir reports/aon_miconversor
```

Generar **un único Excel** combinando todas las DIARIO:

```bash
python3 scripts/import_aon_diario_to_miconversor.py \
  --root "/ruta/AUTONOMOS - ORIGEN MONITOR AON" \
  --template "/ruta/Plantilla MiConversor (empresas).xlsx" \
  --out-dir reports/aon_miconversor \
  --one-file
```

## Notas importantes

- En los exports “DIARIO” no suele venir **NIF/domicilio/localidad/código postal** del tercero: esas columnas se dejan vacías.
- Si un documento tiene varias subcuentas de gasto/ingreso, el script elige la de mayor importe (para no duplicar líneas).
- Si necesitas que el formato sea “una línea por subcuenta de gasto/ingreso” (desglose real por cuentas), se puede añadir como modo alternativo.

