# Importacion a SQLite (Fase 1)

## Requisitos

- Python 3
- Paquete `openpyxl` instalado

Si no esta instalado:

```bash
python3 -m pip install openpyxl
```

## Comando de importacion

```bash
python3 scripts/import_excel_to_sqlite.py \
  --excel "/Users/miguelperezrodriguez/Library/Mobile Documents/com~apple~CloudDocs/MIGUE TRABAJO/EXCEL MIGUE/EMPRESAS MIGUEL.xlsm" \
  --db data/erp.sqlite
```

Opcional: asignar todos los registros a una empresa concreta.

```bash
python3 scripts/import_excel_to_sqlite.py \
  --excel "/Users/miguelperezrodriguez/Library/Mobile Documents/com~apple~CloudDocs/MIGUE TRABAJO/EXCEL MIGUE/EMPRESAS MIGUEL.xlsm" \
  --db data/erp.sqlite \
  --empresa "Grupo Modernia"
```

## Nota sobre empresa_id

- Si no usas `--empresa`, el script asigna empresa automaticamente en la hoja `BDT` usando la columna `SL`.
- El resto de hojas quedan con `empresa_id` en NULL hasta que definamos su regla.

## Verificacion rapida

```bash
sqlite3 data/erp.sqlite "SELECT COUNT(*) FROM movimientos;"
sqlite3 data/erp.sqlite "SELECT COUNT(*) FROM seguros;"
sqlite3 data/erp.sqlite "SELECT COUNT(*) FROM hipotecas;"
```

## Reporte HTML (visualizacion rapida)

```bash
python3 scripts/generate_report.py --db data/erp_import2.sqlite --out reports/erp_report.html
```

Luego abre `reports/erp_report.html` en tu navegador.

## Panel web local

```bash
python3 web/server.py --db data/erp_import2.sqlite --port 8000
```

Abrir en el navegador:

```
http://127.0.0.1:8000
```
