# Auditoría de uso

Este documento recoge las **simulaciones de uso real** del CRM: no revisan el código
buscando errores, sino que hacen lo que haría una persona y comprueban que el resultado
es el correcto en cada paso.

Es un enfoque distinto al de `TECHNICAL_AUDIT.md`. Barrer endpoints buscando errores 500
dice si el servidor se cae; esto dice si el CRM **hace lo que debe**. Los dos fallos más
serios encontrados con este método devolvían `200 OK` en todas sus llamadas.

## Cómo se ejecutan

```bash
python scripts/simula_ciclo_fincas.py
python scripts/simula_ciclo_inmobiliaria.py
python scripts/simula_ciclo_rrhh.py
```

Cada uno levanta su propio servidor sobre una base temporal —borran `DATABASE_URL` antes
de importar nada, así que no tocan producción— y salen con código 1 si algún paso falla.
Imprimen el resultado paso a paso, con el número que sale en cada pantalla.

## Qué cubre cada simulación

### Ciclo mensual de una comunidad (`simula_ciclo_fincas.py`)

Alta de la comunidad → censo con coeficientes → presupuesto anual → emisión de recibos →
remesa SEPA → un recibo devuelto → morosidad.

Comprueba con la calculadora: que los coeficientes sumen 100 %, que las partidas sumen lo
aprobado, que **cada recibo sea la cuota del mes por el coeficiente de su piso**, que los
recibos sumen exactamente la cuota, que el fichero SEPA sea un `pain.008` con `CtrlSum` y
`NbOfTxs` cuadrando, y que morosidad liste sólo a quien de verdad debe.

### Ciclo de una operación inmobiliaria (`simula_ciclo_inmobiliaria.py`)

Captación → encargo → anuncio y hoja de encargo → comprador con demanda → visita y su
hoja → oferta → cierre de la venta → listado → reapertura → intento de borrado.

Comprueba que la conversión hereda dirección y precio, que los PDF salen de verdad, que
el cierre guarda importe y honorarios y archiva lo pendiente, que **el piso figura como
vendido en el listado**, que se puede retomar conservando el cierre anterior, y que una
captación con historia detrás ya no se puede borrar por error.

### Jornada de un trabajador y cierre de mes (`simula_ciclo_rrhh.py`)

Alta de la ficha de plantilla → el trabajador ficha entrada y salida → otro día se olvida
la salida → la responsable lo regulariza → se cierra el mes → se desbloquea → se exporta
para una inspección.

Comprueba que un trabajador **no** puede regularizar por su cuenta, que la regularización
**queda anotada en la auditoría** —el registro de jornada no se altera en silencio, ET
art. 34.9—, que con el mes cerrado no se ficha ni se regulariza, y que las tres
exportaciones (PDF, XLSX, XML) salen con datos.

**Sin fallos.** El control se comporta como debe y además lo explica: al intentar fichar
con el mes cerrado responde `409 · «Mes bloqueado: desbloquea el periodo para fichar.»`

## Fallos encontrados

### La comunidad entera salía morosa el día de emitir los recibos

Al marcar **un** recibo como devuelto, la pantalla de morosidad listaba a los cuatro
vecinos: 360, 300, 300 y 240 €. Nadie había tenido ocasión de pagar todavía.

Contaba como deuda todo lo que estuviera en «Pendiente». Y esa misma consulta alimenta el
**certificado de deuda**, que se pide para vender un piso y para reclamar por el art. 21
de la LPH: certificaba un importe que aún no se debía.

Arreglado: el criterio vive ahora en un solo sitio, `condicion_de_recibo_impagado()`,
compartido por la lista de morosidad y los dos certificados. Devuelto por el banco es
impago siempre; pendiente lo es cuando su mes ya ha pasado. Lo del mes en curso sigue
viéndose en «recibos pendientes», que es otra cifra y otra caja del resumen.

Prueba: `tests/test_morosidad_y_certificado.py::ElMesEnCursoTodaviaNoEsDeudaTests`.

### Cerrabas la venta y el piso seguía apareciendo como disponible

El cierre registraba los 285.000 € y sus 8.550 € de honorarios, archivaba las gestiones
pendientes y retiraba el anuncio del portal. Y después, en el listado del comercial:

```
Calle Larios 3, 4º A · estado: Inmueble · 300.000 €
```

Nada decía que estuviera vendido. Eran dos líneas seguidas: se ponía la fase en «Vendido»
y la siguiente la pisaba con «Inmueble». Por el otro camino de cerrar una venta
—convertir la captación con destino «vendido»— sí quedaba en «Vendido», con una prueba
que lo exigía: los dos caminos acababan distinto y ninguna prueba fijaba éste.

Arreglado: la ficha se queda contando lo que pasó, «Vendido» o «Alquiler». Si con el
tiempo vuelve a salir a la venta se retoma convirtiéndola otra vez a «Encargo», y el
cierre anterior se conserva. Reabrir es un acto, no el estado por defecto de lo que se
acaba de cerrar.

Prueba: `tests/test_una_venta_cerrada_figura_vendida.py`.

## Qué NO cubre esto todavía

Conviene tenerlo claro para no dar por auditado lo que no lo está:

- **Sólo el camino principal de tres módulos.** Quedan sin simular gestoría, seguros y
  financiaciones, y dentro de los tres hechos quedan los caminos que se salen de lo
  normal: derramas, cambio de propietario a mitad de ejercicio, anulaciones, devoluciones
  parciales, alquileres, ausencias y nóminas.
- **Los portales, de punta a punta.** El del propietario, el del comprador y el del
  comunero se auditaron por separado, pero no como un recorrido completo del cliente.
- **La interfaz.** Las simulaciones comprueban la API y la base. Una pantalla puede
  enseñar mal un dato correcto, y eso sólo se ve en el navegador.

## Anotaciones menores

- Un parámetro que falta en `/api/captacion_convert` responde **403 «id requerido»** en
  vez de 400. No es visible para el usuario —la interfaz manda el nombre correcto— pero
  despista a quien depure.
- Una visita se liga al comprador **por demanda**, no por cliente: la tabla `visitas` no
  tiene `cliente_id`. Es el modelo, no un fallo, pero conviene saberlo al leer el código.
