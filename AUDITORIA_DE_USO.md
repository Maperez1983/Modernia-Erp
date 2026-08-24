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
python scripts/simula_ciclo_seguros.py
python scripts/simula_ciclo_financiaciones.py
python scripts/simula_ciclo_gestoria.py
python scripts/simula_portales.py
python scripts/simula_fincas_fuera_de_lo_normal.py
python scripts/simula_junta_de_propietarios.py
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

### Ciclo de una póliza (`simula_ciclo_seguros.py`)

Oferta → alta de la póliza → contratación → entrada en vigor → recibo → resumen y KPI →
siniestro → cola de renovaciones.

Comprueba que el flujo de estados **no se salta** —Presupuesto → Contratada → En vigor—,
que no se pone una póliza en vigor sin adjuntar su PDF, que la prima y la comisión quedan
coherentes, que el recibo hereda los importes y que el resumen del panel suma lo mismo
que hay en la base.

**Sin fallos.** Los dos controles del módulo no sólo impiden la acción, explican qué
hacer: «Transición de estado no permitida: Presupuesto → En vigor» con el flujo bueno al
lado, y «Debes adjuntar el PDF de la póliza antes de marcarla como Contratada/En vigor».

Un detalle del modelo, por si despista al leer el código: **la comisión es el dato que se
guarda** y el porcentaje se deriva de ella para mostrarlo.

### Ciclo de una financiación (`simula_ciclo_financiaciones.py`)

Estudio → checklist → conversión en hipoteca → ficha completa → firma → paneles y PDF.

Es el módulo que más ha dado. Comprueba, además del recorrido, que **lo que se guarda
queda guardado**: cada verificación usa una conexión nueva a la base, porque la del
propio script arrastra una instantánea de SQLite que no ve lo que el servidor escribe
después.

### Ciclo de una gestoría (`simula_ciclo_gestoria.py`)

Alta del cliente → servicios contratados → un trabajo con su plazo → modelos a presentar
→ apunte contable → panel → listados.

**Sin fallos.** Dos detalles del modelo, por si despistan: `/api/cliente_gestoria`
devuelve los servicios contratados, no el expediente entero —los trabajos y los modelos
se piden aparte—, y `gestoria_contabilidad` guarda un `importe` único, no base+IVA.

### Los tres portales de cliente (`simula_portales.py`)

Lo único del CRM que ve alguien de fuera. La agencia genera los tres enlaces; el cliente
entra sin cuenta, acepta el consentimiento, mira lo suyo y hace algo.

**Sin fallos, y con la puerta de RGPD bien puesta:** antes de aceptar no se enseña ni un
dato. Después, cada uno ve lo suyo y sólo lo suyo — el propietario no ve otro piso ni el
teléfono del comprador, el comprador no ve el del propietario, el comunero no ve a su
vecina. Un token inventado no abre nada, el token de un portal no vale en otro, y un
enlace revocado responde «Este enlace ha sido anulado. Pide uno nuevo a tu agencia».

El circuito cierra: el comprador pide visita desde su portal, la cita le aparece a él y
la agencia la ve en su agenda.

Detalle del contrato público: el portal identifica cada inmueble **por su índice en la
lista**, no por id, para no exponer identificadores internos.

### Lo que no es el mes normal de una comunidad (`simula_fincas_fuera_de_lo_normal.py`)

El ciclo mensual sale limpio, pero una administradora se pasa el año fuera de ese camino.
Esto recorre lo otro: una derrama, un piso que cambia de dueño en junio, un recibo
devuelto por el banco, un vecino nuevo que descuadra los coeficientes, y cerrar el
ejercicio con recibos sin cobrar.

De cinco escenarios, tres estaban bien y dos no —la derrama y el cambio de dueño, los
dos abajo—. Los que estaban bien:

- **Cobrado y devuelto**: al marcarlo cobrado deja de ser moroso; cuando el banco lo
  devuelve vuelve a contar como deuda y se borra la fecha de cobro. Correcto.
- **Coeficientes descuadrados**: dar de alta un trastero deja el reparto en 105 % y la
  emisión se niega diciendo cuánto suman y qué revisar (LPH art. 5). No se cuela ni un
  recibo.
- **Cerrar el ejercicio** no hace desaparecer lo que se debe.

### Una junta de propietarios, de la convocatoria al acta (`simula_junta_de_propietarios.py`)

Es el sitio donde el CRM deja de llevar cuentas y empieza a **decir si algo está
aprobado**. Un acuerdo dado por bueno sin la mayoría que exige la ley es impugnable
(art. 18), y quien firma el acta es el administrador. Cada porcentaje se comprueba con la
calculadora, no con lo que responde la API.

Lo que ya estaba bien, que es casi todo:

- **La convocatoria** lleva las cuatro cosas del art. 16.2: orden del día, lugar con las
  dos horas, relación de quien no está al corriente y la advertencia de que no votan.
- **Doble cómputo**: un acuerdo sólo sale si alcanza por cabezas Y por coeficiente. Con
  un vecino del 40 %, dos votos que son el 55 % de cuota pero el 40 % de propietarios no
  aprueban nada, que es lo correcto.
- **Segunda convocatoria**: el denominador pasa de toda la comunidad a los asistentes, y
  el acta dice cuál se ha usado. Es el cambio que peor se hace a mano.
- **Tres quintos y unanimidad** se exigen de verdad; los estatutos con el 80 % de los
  propietarios salen como NO aprobados.
- **El acta** recoge fecha y lugar, carácter y convocatoria, asistentes, orden del día,
  quién votó qué con su cuota, y el resultado de cada punto. Sale sin firmar, que es lo
  que debe hacer un programa.

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

### Dos botones de financiación decían «ok» y no guardaban nada

**«Generar checklist»** devolvía `{"ok": true}` y creaba cero tareas: el asesor lo
pulsaba, veía que había ido bien, y el expediente seguía con la lista vacía.

**«Convertir en hipoteca»** devolvía el identificador de una hipoteca que no existía.
Comprobado del modo más duro: tras convertir, la propia API contestaba «0 hipotecas» y el
fichero tenía 0. Con suerte la salvaba una escritura posterior de la misma conexión; sin
suerte se perdía.

A los dos les faltaba `conn.commit()`. Es la tercera vez que aparece este descuido en el
mismo módulo —`fin_checklist_update` ya se había arreglado antes—.

De paso, cada conversión dejaba un `BrokenPipeError` en el registro: faltaba el `return`
tras responder, así que la ejecución seguía hasta el 404 final e intentaba contestar dos
veces. Un barrido de las demás ramas encontró exactamente otra igual, también arreglada.

Y la ficha enseñaba «Entrada» en blanco teniendo precio e hipoteca: la misma resta que el
asesor hacía a mano. Ahora sale sola, y sólo si estaba vacía —quien la ponga a mano puede
estar contando gastos e impuestos—.

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

### El CRM aceptaba cifras que no pueden ser

Probando lo que teclea una persona con prisa, cuatro entradas pasaban sin decir nada y
todas descuadraban algo. La peor: un **coeficiente del 250 %** en la ficha de un vecino.
El coeficiente es la parte que le toca de la finca (art. 5 LPH) y multiplica directamente
lo que se le cobra, así que un 250 % le pasa dos veces y media el presupuesto entero de
la comunidad, y un negativo le devuelve dinero cada mes. Igual una **cuota mensual
negativa** y un **gasto de -500 €**, que sumaba en vez de restar porque el signo lo pone
el tipo de apunte —Gasto o Ingreso—, no el número.

El criterio lo decidió el cliente, y son dos distintos:

- **Los negativos se rechazan siempre** (400, diciendo por qué). Un abono se anota como
  ingreso, que es lo que es.
- **Las cifras absurdas no se bloquean: se preguntan.** Un apunte de un billón de euros
  responde 409 con `requiere_confirmacion`, y el front lo vuelve a mandar confirmado si
  la persona dice que sí. Una derrama grande es legítima; un tope de negocio se queda
  corto el día que hace falta.

Prueba: `tests/test_cifras_que_no_pueden_ser.py`, incluido que el front sepa reintentar
—sin eso el 409 sería un callejón sin salida—.

### Todo lo publicado se anunciaba como «Grupo Modernia»

El escaparate es lo único del CRM que ve alguien de fuera. La consulta ya traía el nombre
y el logotipo de la empresa dueña de cada inmueble; el armador de la respuesta pública no
los miraba y escribía la marca de la casa a pelo.

Hoy no se nota, porque publica una sola agencia. El día que publique la segunda, sus
pisos saldrían en el escaparate con la marca de otra —y con su contacto—, que es un
problema con quien te ha dado la exclusiva.

Arreglado, y de paso enganchado `/api/portal_empresa_logo`, que llevaba escrito sin ser
alcanzable desde ninguna ruta pública. Sólo responde si esa empresa tiene algo publicado:
no vale para pasear el directorio de empresas del CRM desde fuera.

**Y aquí me equivoqué dos veces, que es la parte que interesa.** Probé el endpoint con una
empresa de mentira cuyo logotipo era `/assets/sur.png`, un fichero que no existe. Dio 404,
lo achaqué al fichero inventado y lo di por bueno. No lo era: dentro tenía un fallo que
nunca se había ejecutado —le pasaba a `_normalize_s3_key` la URI entera en vez de la
clave—, y en producción todas las empresas con logotipo propio lo tienen en S3. El
escaparate pasó de enseñar el logotipo del grupo a enseñar un hueco.

El segundo: al mirar el nombre de la empresa, los seis anuncios pasaron a decir «Estudio
Velazquez 2012 SL». Es quien tiene el encargo y es correcto en la base, pero nadie busca
piso a una razón social. Ahora hay un **nombre comercial** en la ficha de la empresa; en
blanco se anuncia con la marca del grupo, que es lo que había siempre.

Los dos salieron de un `curl` al escaparate público con el commit ya desplegado, no de la
simulación. Si el cambio se ve desde fuera, hay que mirarlo desde fuera.

Prueba: `tests/test_el_anuncio_lleva_su_agencia.py`.

### La derrama dejaba a la comunidad sin cobrar la cuota de ese mes

La junta aprueba arreglar el ascensor: 12.000 € a repartir en agosto. Agosto ya tiene su
cuota ordinaria de 1.200 €, y emitir la derrama contestaba:

```
409 · Ya hay recibos emitidos de 2026-08. Marca «reemitir» si quieres rehacerlos.
```

Y «reemitir» —la única salida que ofrecía el aviso, y la única que ofrecía el botón—
**borraba los recibos pendientes del mes**. Quien seguía esa instrucción emitía la
derrama, leía «4 recibos por 12.000 €» y se quedaba sin cobrar los 1.200 € de la cuota.
Con 200 OK y sin nada que lo dijera. Debajo, el índice único de la tabla era
`(comunidad, vecino, periodo)`: los dos cargos no cabían ni en el esquema.

Arreglado: lo que identifica un cargo dentro de un mes es su **concepto**. Repetir el
mismo cargo sigue pidiendo confirmación y rehace sólo ése; un concepto distinto es un
cargo aparte, se dice qué hay ya en ese mes —cuántos recibos y por cuánto— y se suma si
se confirma. Que es lo que pasa de verdad: en un mes puede haber la cuota, una derrama y
una liquidación.

Prueba: `tests/test_una_derrama_no_se_come_la_cuota.py`.

### Vendías el piso y tus recibos impagados pasaban a nombre del comprador

El 1º A se vende en junio. La única forma de meter al comprador en el censo es editar la
ficha del vecino, y eso es un `UPDATE` sobre la misma fila: los 4.050 € que dejó sin
pagar la vendedora pasaban a figurar a nombre del comprador, y ella desaparecía del
histórico de la comunidad.

La deuda **sí** viaja con el piso —el comprador responde de la del año en curso y los
tres anteriores—, así que el importe estaba bien. Lo que estaba mal es que un recibo
dijera que se le emitió a quien no se le emitió. Y eso sale del CRM en un papel: el
certificado de deuda, que se pide para vender y se enseña en una notaría, listaba la
deuda de la vendedora bajo el nombre del comprador sin decirlo.

Arreglado: el recibo guarda el nombre y el NIF del propietario **el día de emitirlo**, y
ya no se mueve. Lo que había se rellenó una vez con el propietario que consta hoy, que es
exactamente lo que venía enseñándose. El certificado sigue saliendo a nombre de quien es
dueño hoy —es quien responde y quien lo va a enseñar—, pero si hay recibos de otro los
saca en su columna «Emitido a» y lo explica en un apartado aparte. Lo que no hace es
decidir quién paga: eso no lo determina un programa sin firma.

La columna sólo aparece cuando hace falta. Sin cambio de dueño, el certificado sale igual
que antes.

Prueba: `tests/test_el_recibo_dice_a_quien_se_emitio.py`.

### El deudor votaba en la junta, y su cuota contaba para la mayoría

El CRM ya sabía la regla: la convocatoria que genera lista a quien no está al corriente y
advierte, con el artículo al lado, de que puede asistir y deliberar pero **no tiene
derecho de voto** (LPH art. 15.2). Luego llegaba el recuento y contaba su voto como el de
cualquiera.

La segunda consecuencia es peor que la primera. El artículo dice que las cuotas de los
deudores **se deducen del total del inmueble a efectos de alcanzar las mayorías**. Con un
deudor del 15 %, un acuerdo apoyado por el 40 % salía como «40 % de coeficiente» cuando
legalmente es el 47,06 % de lo que vota. O sea que el CRM podía dar por no aprobado algo
que sí lo estaba, y al revés.

Arreglado en los tres sitios: no se deja registrar el voto —con un mensaje que dice quién
es, cuánto debe y cómo se recupera el derecho—, sale de los dos divisores, y un voto que
quedara guardado de antes deja de contar sin borrarse.

Recupera el voto quien antes de empezar la junta haya pagado, impugnado judicialmente la
deuda o consignado su importe. Eso el CRM no puede saberlo: lo marca quien preside con una
casilla «tiene voto», y sin marcarla manda lo que diga la deuda.

Y queda por escrito: el acta relaciona a quién no votó, por cuánto debe y sobre qué
coeficiente se han medido las mayorías. Sin esa lista, un porcentaje sobre el 85 % es un
número que nadie puede comprobar.

Prueba: `tests/test_el_moroso_no_vota.py`.

### Un acuerdo salía «no aprobado» y un mes después estaba aprobado

Al propietario ausente debidamente citado que, informado del acuerdo, **no manifieste su
discrepancia en 30 días naturales**, se le computa el voto a favor (LPH art. 17.8). Es la
regla que hace posible la unanimidad en una comunidad donde nunca vienen todos, y el CRM
no la tenía: dictaminaba con los votos del día de la junta y ahí se quedaba.

Con cinco propietarios y uno que no viene, el acta decía:

```
Modificar los estatutos · unanimidad · 80 % de propietarios → NO APROBADO
```

Cuando la verdad es que ese punto queda aprobado el día 31 si el ausente calla. El papel
decía lo contrario y nadie volvía a mirarlo.

Ahora cada punto lleva las dos cifras —la del día y la del cómputo—, el plazo con su
fecha de vencimiento y un `firme` que dice si el resultado ya puede darse por cerrado.
Tres cosas que no se dan por supuestas:

- **El plazo arranca cuando se comunica el acta** (art. 9.1.h y 19.3), no el día de la
  junta. Sin esa fecha el plazo no ha empezado, y el acta lo dice con todas las letras
  en vez de dar un resultado que no lo es.
- **No se aplica a todo.** El propio artículo lo excluye cuando el coste no se puede
  repercutir a quien no votó a favor —las energías renovables del 17.1, por ejemplo—. Va
  por tipo de acuerdo, sembrado según la ley y editable como el resto del catálogo.
- **Discrepar es de ausentes.** A quien asistió, en persona o representado, no se le
  anota: ya se manifestó votando, y colarle una postura después sería un voto fuera de
  la junta.

De paso salió que el **tipo del acuerdo no se guardaba**: se recibía al crearlo, se usaba
para derivar la mayoría y se tiraba. Es justo el dato que dice si el 17.8 aplica.

Prueba: `tests/test_computo_de_ausentes.py`.

## Qué NO cubre esto todavía

Conviene tenerlo claro para no dar por auditado lo que no lo está:

- **Los caminos que se salen de lo normal, salvo en fincas.** Ahí ya están: derrama,
  cambio de propietario, recibo devuelto, censo descuadrado y cierre de ejercicio.
  Quedan los de los otros cinco módulos: anulaciones, devoluciones parciales, alquileres,
  ausencias, nóminas, cambio de compañía y bajas de póliza. En fincas ya están, incluida la junta entera y el cómputo de ausentes; queda la impugnación de acuerdos (art. 18).
- **La interfaz.** Las simulaciones comprueban la API y la base. Una pantalla puede
  enseñar mal un dato correcto, y eso sólo se ve en el navegador.

## Anotaciones menores

- Un parámetro que falta en `/api/captacion_convert` responde **403 «id requerido»** en
  vez de 400. No es visible para el usuario —la interfaz manda el nombre correcto— pero
  despista a quien depure.
- Una visita se liga al comprador **por demanda**, no por cliente: la tabla `visitas` no
  tiene `cliente_id`. Es el modelo, no un fallo, pero conviene saberlo al leer el código.
