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
python scripts/simula_seguros_fuera_de_lo_normal.py
python scripts/simula_rrhh_fuera_de_lo_normal.py
python scripts/simula_inmobiliaria_fuera_de_lo_normal.py
python scripts/contrasta_pantalla_con_la_base.py
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

### Impugnar un acuerdo tiene tres reglas, y no había ninguna

El artículo 18 no dice sólo que un acuerdo se puede impugnar. Dice **quién**, **hasta
cuándo** y **qué pasa mientras tanto**, y las tres se fallan a menudo:

- **Quién** (18.2). Sólo los que salvaron su voto, los ausentes y los privados
  indebidamente de votar. Quien votó a favor, no: no se impugna lo que uno mismo ha
  votado. Y hay que estar al corriente o haber consignado judicialmente lo debido, salvo
  que el acuerdo sea sobre el establecimiento o la alteración de las cuotas de
  participación — ésos sí los puede impugnar un deudor.
- **Hasta cuándo** (18.3). Tres meses… o **un año** si el acuerdo es contrario a la ley o
  a los estatutos. Y para los ausentes se cuenta desde que se les comunicó, no desde la
  junta: cuatro fechas posibles, que es justo la cuenta que sale mal a mano. El CRM da
  las cuatro calculadas.
- **Qué pasa mientras tanto** (18.4). **No suspende la ejecución.** Es lo que peor sale:
  dejar de ejecutar un acuerdo porque «está impugnado» es meterse en otro problema. Se
  avisa al anotarla y se repite en el acta.

El plazo vencido no bloquea —el hecho ocurrió y hay que poder anotarlo— pero tampoco se
traga en silencio: se dice hasta cuándo era y se pide confirmar. Mismo criterio que con
los importes absurdos.

Prueba: `tests/test_impugnar_un_acuerdo.py`.

### Cambiar de compañía cobraba la prima de la anterior

Cuatro cosas en el mismo sitio, todas con 200 OK, todas de dinero:

- **La póliza nueva entraba «En vigor» sin su PDF.** Por el camino normal eso se
  rechaza; por el cambio de compañía no lo miraba nadie. Dos caminos al mismo sitio y
  sólo uno con el control — el patrón que más veces ha salido en esta auditoría. Ahora
  se queda en Pendiente y se dice por qué, en vez de rechazar el cambio: el cambio ha
  ocurrido y hay que registrarlo; lo que no vale es mentir sobre el estado.
- **Heredaba la prima.** El cliente se va de Mapfre a Generali por 415 € y la póliza
  nueva se guardaba con los 640 € de la anterior. Nadie cambia de compañía para pagar lo
  mismo: la prima nueva es justo el motivo del cambio.
- **Y la comisión.** 96 € de la póliza vieja liquidados sobre la nueva.
- **Anular dejaba el recibo pendiente cobrándose solo.** La póliza quedaba «Anulada» con
  su fecha de baja y el recibo de 900 € seguía en «Pendiente»: sigue en el resumen y
  entra en la remesa, o sea que se le pasa al cobro a quien ya no tiene póliza.

El último va en un ayudante compartido a propósito: la interfaz anula con un
`seguros_update` de estado y la API con `seguros_poliza_accion`. Poner el control en uno
solo es como no ponerlo, y da la casualidad de que el que usa la gente es el otro.

Lo que **no** se toca, y conviene que quede dicho: los recibos pendientes de una póliza
*sustituida*. Una póliza que se cambia a mitad de año puede deber legítimamente la prima
del periodo transcurrido, y anularlos ahí sería borrar deuda real. Sólo se anulan al
anular de verdad, y nunca los ya cobrados —si hay que devolver dinero eso es un extorno—.

Prueba: `tests/test_cambio_de_compania_y_anulacion.py`.

### Unas vacaciones del 20 al 10 entraban, y gastaban cero días

Las ausencias se piden a mano, y a mano se teclea mal.

**La ausencia que acaba antes de empezar** no era sólo fea. El contador de vacaciones
cuenta los días de inicio a fin, así que una del 20 al 10 sale en negativo y se guarda
como **cero días consumidos**: el trabajador se va quince días y el resumen dice que no
ha gastado ninguno, y los vuelve a tener disponibles en diciembre.

**Dos ausencias encima del mismo día** se guardaban las dos sin decir nada, y el cómputo
contaba los días dos veces. Aquí no vale bloquear, porque el caso común es legítimo: una
baja médica que cae dentro de unas vacaciones aprobadas, y la ley dice que esos días de
vacaciones se recuperan (ET art. 38.3). Se avisa de con qué se solapa, se explica eso, y
se pide confirmar.

Lo que ya estaba bien y queda fijado: un trabajador puede pedir su ausencia pero **no
aprobársela** (403); cerrar el mes no borra lo que está sin resolver; y el resumen
descuenta los días aprobados.

Prueba: `tests/test_ausencias_que_no_cuadran.py`.

### Cada vez que se pulsaba «cerrar», la agencia se apuntaba otra comisión

El cierre es el momento en que entra el dinero, y es un botón que se pulsa una vez al año
por inmueble: cuando falla, falla en silencio y no se nota hasta que alguien cuadra el
año. Pulsándolo cinco veces sobre el mismo piso quedaban **cinco cierres**, y los paneles
sumaban 417.850 € de honorarios de una venta de 285.000 €.

Nadie duplica un cierre a propósito. Pero sí se pulsa dos veces cuando la primera parece
que no ha respondido, y sí se vuelve a entrar para corregir un importe mal tecleado.

Por el camino entraban tres importes imposibles: una venta en negativo, unos honorarios
en negativo, y unos honorarios mayores que el precio de venta.

Los criterios son los que ya se fijaron en fincas: los negativos se rechazan siempre, y
lo absurdo se pregunta. Volver a cerrar avisa de lo que ya hay —tipo, fecha, importe y
honorarios— y, si se confirma, **sustituye** aquel cierre en vez de añadir otro. Que es
lo que quiere quien está corrigiendo.

Prueba: `tests/test_cerrar_dos_veces_el_mismo_piso.py`.

### Un apunte de 2.450,75 € contaba como 2,45 € al sumarlo

El importe de un apunte de contabilidad de gestoría entraba tal cual venía del
formulario, **sin pasar por el analizador de importes**. La columna es `REAL`, así que un
importe tecleado en español normal se guardaba como texto —`'2.450,75'`—, y SQLite lo
convierte quedándose con lo de antes del punto:

```
2.450,75 € + 100,00 €  =  102,45 €
```

**Con una corrección importante sobre el alcance**, porque la primera versión de esta
nota lo contaba peor de lo que es. Eso pasa en SQLite, que es donde corren el desarrollo
y la suite. En producción la base es PostgreSQL y la columna es `numeric`, que **rechaza**
el texto: `invalid input syntax for type numeric: "2.450,75"`. O sea que en producción el
síntoma no era un panel descuadrado en silencio, sino que el apunte **no se llegaba a
guardar** y quien teclease un importe en formato español se encontraba un error.

Se comprobó contra la base de producción: los 656 apuntes existentes son todos numéricos
válidos, sin negativos, sumando 757.234,29 €. **No hay ni un dato mal.** Los importes
pequeños que aparecen son comisiones bancarias de verdad, no miles mal leídos.

Sigue siendo un fallo —no se podía teclear un importe como se teclea en España— y el
arreglo lo resuelve en las dos bases. Es la misma familia que el importe en formato
inglés que se arregló en tres analizadores al principio de la campaña; éste se quedó
fuera porque no analizaba nada.

Y de paso, los otros dos criterios que ya se fijaron en fincas, aplicados igual aquí: los
negativos se rechazan y lo absurdo se pregunta. En los dos caminos, alta y edición.

Prueba: `tests/test_el_importe_de_gestoria_era_texto.py`.

### En financiaciones no había nada que arreglar

Se comprobó y conviene dejarlo dicho para no repetirlo: convertir un asesoramiento en
hipoteca **dos veces no duplica** la hipoteca, y la hipoteca nace sin banco, precio ni
comisión **a propósito** — el asesoramiento no tiene esos campos, así que no hay nada que
arrastrar y el asesor los completa después. La máquina de estados del expediente
—denegada, cancelada, pospuesta— lleva cada caso a su sitio.

### Un emparejamiento con cero de confianza salía en verde

El conciliador bancario guarda tres cosas de cada movimiento: si está punteado, en qué
estado dejó la conciliación y con cuánta confianza. La pantalla sólo miraba la primera.

En producción hay **siete movimientos** con `punteado = 1`, `conciliacion_estado =
'pendiente'` y `conciliacion_confianza = 0.0`: el emparejador automático los enlazó, no
se fio nada, y los dejó marcados para revisar. La tabla los pintaba en verde y el
contador los sumaba a «Punteados».

Y un detalle que lo remataba: el porcentaje de confianza se enseñaba junto a la etiqueta
**sólo si era distinto de cero**. Con confianza 0 —el caso más flojo de todos—
desaparecía justo la señal que habría avisado.

Ahora hay tres estados: sin puntear, punteado, y **por revisar** en ámbar con el porqué
en el título. El porcentaje sale siempre que esté punteado, incluido el 0. El umbral es
55, el mismo con el que el servidor cuenta los de «baja confianza» al importar el
extracto: si fueran distintos, la pantalla y el resumen dirían cosas diferentes de los
mismos movimientos, y hay una prueba que lo ata.

Prueba: `tests/test_punteado_no_es_conciliado.py`.

### En nóminas no había nada que arreglar

Se comprobó: la importación parte el PDF por NIF, y el que no encuentra a nadie en la
plantilla lo cuenta aparte y **lo devuelve como `persona_not_found`**, que es justo el
nombre con el que el front lo lee y lo enseña. No se pierde ninguna nómina en silencio.

### Un endpoint de conciliación escrito y sin enganchar

`/api/gestoria_conciliacion_validar` existe, valida un movimiento contra un asiento con
su confianza y sus notas… y **no está en la lista blanca de POST ni lo llama nadie**. Hoy
no rompe nada porque ningún botón apunta ahí. Si algún día se engancha, hacen falta dos
cosas: darlo de alta en las **dos** listas —la blanca y el grupo que despacha— y añadirle
la comprobación de importes, que no la tiene: hoy dejaría conciliar un movimiento de
500 € contra un asiento de 5.000 €.

## Levantar el CRM en local te conecta a PRODUCCIÓN

Esto no salió auditando una pantalla: salió al intentar auditarlas. Es lo más importante
de todo el documento y por eso va aparte.

El arranque local que hay en `.claude/launch.json` —`python -m web.server`— importa
`web/db_backend.py`, que lo primero que hace es leer el `.env` de la raíz. Y ahí está el
`DATABASE_URL` de producción. O sea que **levantar el CRM en local abre un CRM local
conectado a la base real**, y `/api/build_info` lo confirma: `backend: postgres`, con el
host de Render.

No hay ningún aviso. La pantalla es idéntica.

Quien vaya a trabajar contra una base de prueba tiene que apagarlo a mano **antes de
importar nada**, porque `_load_env_file` sólo rellena las claves que no estén ya en el
entorno:

```python
import os
for clave in ("DATABASE_URL", "POSTGRES_URL"):
    os.environ[clave] = ""          # antes de `from web import ...`
from web import db_backend as D
assert not D.is_postgres_enabled()  # y comprobarlo, no suponerlo
```

Merece la pena decidir si el servidor debe **negarse a arrancar contra Postgres sin un
`--permitir-produccion` explícito**. No se ha hecho aquí porque puede haber quien
depure con datos reales a propósito, y eso es una decisión del cliente, no del auditor.

## Contrastar la pantalla con la base (`contrasta_pantalla_con_la_base.py`)

Siembra una base con importes y estados escogidos a mano, levanta el servidor encima y
compara, pantalla por pantalla, las cifras que recibe el front con las que hay guardadas.

Es la red para la clase de fallo que más tarde se descubre: el dato está bien y sólo se
lee mal. El último que salió así fue el punteo bancario, que pintaba en verde un
emparejamiento con cero de confianza porque la tabla leía uno de los tres campos que le
llegaban.

Hoy cubre los movimientos bancarios —con los cuatro estados que hay que saber
distinguir— y la contabilidad de gestoría, comprobando que los importes llegan **como
número y no como texto** y que su suma cuadra con la de la base. Sale limpio.

**Lo que no ve:** el HTML y el CSS. Un número correcto pintado fuera de su columna, o una
etiqueta con el color cambiado, esto no lo detecta. Eso sigue necesitando un navegador, y
en esta sesión no se pudo completar: el panel del navegador quedó oculto y cada acción
agotaba el tiempo. Lo que sí se comprobó a mano: la aplicación carga, el acceso funciona
y las 27 llamadas del arranque responden 200.

## Qué NO cubre esto todavía

Conviene tenerlo claro para no dar por auditado lo que no lo está:

- **Los caminos que se salen de lo normal, salvo en fincas.** Ahí ya están: derrama,
  cambio de propietario, recibo devuelto, censo descuadrado y cierre de ejercicio.
  En seguros ya están los de la póliza: cambio de compañía, anulación y recibo
  devuelto. Están los seis módulos, con sus caminos raros, las nóminas y la conciliación
  bancaria. En fincas ya están: ciclo mensual, caminos raros, junta completa, cómputo de ausentes e impugnación.
- **El HTML y el CSS.** El contraste de arriba cubre lo que la pantalla *recibe*; lo que
  *pinta* —columnas, colores, etiquetas— sigue pendiente de recorrer con un navegador.

## Anotaciones menores

- Un parámetro que falta en `/api/captacion_convert` responde **403 «id requerido»** en
  vez de 400. No es visible para el usuario —la interfaz manda el nombre correcto— pero
  despista a quien depure.
- Una visita se liga al comprador **por demanda**, no por cliente: la tabla `visitas` no
  tiene `cliente_id`. Es el modelo, no un fallo, pero conviene saberlo al leer el código.
