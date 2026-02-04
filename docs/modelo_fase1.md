# Modelo Fase 1 - ERP Modernia

## Empresas (nombres exactos)

- Inversure
- Financiaciones Modernia
- Estudio Velazquez 2012 SL
- Modernia Asesores
- Fincas Velazquez
- Grupo Modernia

## Objetivo Fase 1

Replicar y automatizar el control actual del Excel `EMPRESAS MIGUEL.xlsm` en una plataforma multiempresa.

- Todas las tablas incluyen `empresa_id`.
- Se mantienen los campos actuales con limpieza minima.
- Preparado para unificar clientes entre empresas en fases posteriores.

## Entidades principales

### empresas

- id (uuid)
- nombre (text, unico)
- activo (bool)
- created_at (timestamp)
- updated_at (timestamp)

### clientes

Clientes por empresa (no globales en Fase 1).

- id (uuid)
- empresa_id (uuid, fk empresas)
- nombre (text)
- nif (text, opcional)
- telefono (text, opcional)
- email (text, opcional)
- tipo (text, opcional)
- perfil (text, opcional)
- estado (text, opcional)
- created_at (timestamp)
- updated_at (timestamp)

### movimientos (BDT)

Libro general de ingresos/gastos por empresa.

- id (uuid)
- empresa_id (uuid, fk empresas)
- concepto (text)
- pisos_vendidos (text, opcional)
- comision (number)
- asesor (text, opcional)
- anio (number)
- mes (text)
- sl (text, opcional)
- tipo (text)
- created_at (timestamp)
- updated_at (timestamp)

### seguros (BDT SEGUROS)

- id (uuid)
- empresa_id (uuid, fk empresas)
- mes_creacion (date)
- fecha_efecto (date)
- tomador (text)
- compania (text)
- ramo (text)
- poliza_numero (text)
- prima_neta (number)
- prima_total (number)
- comision (number)
- produccion (text, opcional)
- colaborador (text, opcional)
- estado (text)
- created_at (timestamp)
- updated_at (timestamp)

### gestoria (BDT CLIENTE GESTORIA)

- id (uuid)
- empresa_id (uuid, fk empresas)
- cliente (text)
- fecha (date)
- cuota (text, opcional)
- precio (number)
- tipo (text)
- perfil (text, opcional)
- estado (text)
- created_at (timestamp)
- updated_at (timestamp)

### hipotecas (BDT HIPOTECA)

- id (uuid)
- empresa_id (uuid, fk empresas)
- cliente (text)
- banco (text)
- precio (number)
- importe_hipoteca (number)
- porcentaje (number)
- entrada (number)
- comision (number)
- oficina (text, opcional)
- fecha_encargo (date, opcional)
- encargo (text, opcional)
- tipo_hipoteca (text, opcional)
- fecha_firma (date, opcional)
- cesion (number, opcional)
- comision_juan (number, opcional)
- comision_modernia (number, opcional)
- inmobiliaria_compra (text, opcional)
- asesor (text, opcional)
- estado (text)
- anio (number)
- created_at (timestamp)
- updated_at (timestamp)

### alquileres (ALQUILERES)

- id (uuid)
- empresa_id (uuid, fk empresas)
- fecha (date)
- direccion (text)
- propietario (text)
- telefono (text, opcional)
- precio (number)
- seguro (text, opcional)
- hacienda (text, opcional)
- comision (text, opcional)
- importe_comision (number)
- total (number)
- inquilino (text, opcional)
- telefono2 (text, opcional)
- agente (text, opcional)
- numero_alquileres (number, opcional)
- tipo (text, opcional)
- oficina (text, opcional)
- created_at (timestamp)
- updated_at (timestamp)

Nota: en el Excel hay columnas duplicadas al final (AGENTE/COMISION/OFICINA/HACIENDA/SEGURO). En Fase 1 se ignoran a menos que confirmes que contienen datos reales.

### inversores (INVERSORES)

- id (uuid)
- empresa_id (uuid, fk empresas)
- nombre (text)
- aportacion (number)
- fecha (date)
- proyecto (text)
- created_at (timestamp)
- updated_at (timestamp)

### inversure_operaciones (BDT INVERSURE)

- id (uuid)
- empresa_id (uuid, fk empresas)
- proyecto (text)
- precio (number)
- concepto (text)
- tipo (text)
- sujeto (text, opcional)
- fecha (date)
- created_at (timestamp)
- updated_at (timestamp)

## Relaciones

- empresas 1..N clientes
- empresas 1..N movimientos
- empresas 1..N seguros
- empresas 1..N gestoria
- empresas 1..N hipotecas
- empresas 1..N alquileres
- empresas 1..N inversores
- empresas 1..N inversure_operaciones

## Mapeo Excel -> Base de datos (resumen)

- Hoja `BDT` -> tabla `movimientos`
- Hoja `BDT SEGUROS` -> tabla `seguros`
- Hoja `BDT CLIENTE GESTORIA` -> tabla `gestoria`
- Hoja `BDT HIPOTECA` -> tabla `hipotecas`
- Hoja `ALQUILERES` -> tabla `alquileres`
- Hoja `INVERSORES` -> tabla `inversores`
- Hoja `BDT INVERSURE` -> tabla `inversure_operaciones`

## Decisiones abiertas

- Estados: por ahora texto libre. Si quieres, fijo un catalogo de estados por modulo.
- Clientes: Fase 1 son por empresa; se puede crear una capa de cliente global en Fase 2.
- Categorias contables en BDT: por ahora concepto libre, se puede normalizar en Fase 2.
