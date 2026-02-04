# Integracion contabilidad (preparacion)

Objetivo: dejar lista una interfaz para que un futuro software de contabilidad alimente este ERP sin duplicados.

## Principios

- Cada movimiento contable debe tener `external_id` para evitar duplicados.
- Se soporta multiempresa y multi-origen.
- Integracion por API REST sencilla.

## Modelo propuesto

### tabla `integraciones`

- id (uuid)
- empresa_id (uuid)
- origen (text) -> ej: "contabilidad_v1"
- ultimo_sync (timestamp)
- estado (text) -> ok / error
- detalle_error (text, opcional)

### tabla `movimientos` (extensiones futuras)

- external_id (text, unico por origen)
- origen (text) -> ej: "contabilidad_v1"
- cuenta_contable (text)
- centro_coste (text, opcional)

## Endpoints propuestos

### POST /api/contabilidad/asientos

Inserta asientos contables (debito/credito) o movimientos estandarizados.

Payload sugerido:

```json
{
  "empresa": "Grupo Modernia",
  "origen": "contabilidad_v1",
  "asientos": [
    {
      "external_id": "CTB-2026-0001",
      "fecha": "2026-02-01",
      "concepto": "Nominas febrero",
      "cuenta": "640",
      "centro_coste": "AIE",
      "importe": 12450.25,
      "tipo": "Gasto"
    }
  ]
}
```

### POST /api/contabilidad/diario

Carga masiva del libro diario en formato simplificado (por mes o por rango).

### POST /api/contabilidad/saldos

Sube saldos acumulados por cuenta y periodo.

## Flujo de sincronizacion

1) El software contable envia asientos con `external_id`.
2) El ERP valida y guarda, ignorando duplicados.
3) Se actualiza `integraciones.ultimo_sync`.

## Decisiones pendientes

- Catalogo de cuentas contables y centros de coste por empresa.
- Reglas de conversion de asientos a BDT (si aplica).
- Control de permisos para integraciones externas.
