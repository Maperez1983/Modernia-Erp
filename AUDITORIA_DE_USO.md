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

**Ya hay candado** (decidido por el cliente el 2026-08-24). El servidor se niega a
arrancar contra Postgres y dice a qué host y a qué base iba a entrar —sin usuario ni
contraseña, que esto acaba en un registro—. No se activa en tres casos: en la nube
(se reconoce por `RENDER`, la variable que ya usa el resto del código), con SQLite, y
si se pasa `--permitir-produccion` a propósito.

Prueba: `tests/test_el_candado_de_produccion.py`.

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

**Lo que no ve:** el HTML y el CSS.

Para eso hay una segunda vía que **sí funciona sin navegador**: ejecutar con jsdom la
función que pinta la tabla y mirar lo que sale. Está en
`tests/test_punteado_no_es_conciliado.py::LoQueSePintaTests`, y comprueba los cuatro
casos del punteo bancario tal y como los ve quien concilia:

```
Transferencia ACME    Punteado (92%)      ocr-badge ok
Compra Apple.com      Por revisar (0%)    ocr-badge media   ← los 7 de producción
Recibo luz            Pendiente           ocr-badge danger
Cuota gestoría        Por revisar (40%)   ocr-badge media
pie: Movimientos: 4 · Punteados 1 · Por revisar 2 · Pendientes 1
```

Antes ese pie decía «Punteados 3». Es la forma de auditar la pantalla que ha resultado
más fiable: determinista, sin depender de que el navegador esté visible, y comprobando
el resultado en vez del código fuente.

### La maquetación, mirada de verdad

Se montó la tabla real con la hoja de estilos real en una página suelta y se miró en
escritorio, en móvil y en modo oscuro. Salieron dos cosas, y ninguna se ve leyendo código.

**Las etiquetas verde y roja no existían.** El front pinta `ocr-badge ok` y
`ocr-badge danger` en ocho sitios —punteo bancario, cuenta principal, validación de
asientos— y la hoja de estilos sólo define `alta`, `media` y `baja`. Resultado: esas ocho
salían como **texto negro sin píldora**, así que «Punteado» y «Pendiente» se veían
exactamente igual y sólo los distinguía la palabra.

Conviene corregir aquí algo que dijeron los commits anteriores: el punteo con cero de
confianza **nunca salió en verde**. Salía en negro, igual que el pendiente. El fallo era
real —los estados no se distinguían— pero el color no.

**La tabla se salía de la pantalla en un móvil.** El sistema de diseño resuelve eso
apilando las filas en tarjetas, pero sólo para `.ui-table`, y esta tabla se pintaba sin
esa clase ni `data-label` en las celdas. Por debajo de 760 px el propio sistema desactiva
el scroll horizontal, así que la columna de punteo salía partida y la del asiento no se
alcanzaba: justo las dos que se vienen a mirar aquí.

Las dos arregladas y comprobadas a ojo en las tres vistas.

### Y después, las 137 tablas

Lo anterior arregló una. `app.js` pinta del orden de **137** y sólo esa llevaba
`ui-table`. Con un listado de asientos de diez columnas, en el móvil se veían Fecha,
Nº asiento, Concepto, Cliente y media de Cuenta: **Debe, Haber, Factura, Punteo y
Acciones no existían** para quien mira desde el teléfono. Comprobado con una captura, no
deducido.

No se etiquetaron las 137 llamadas a mano —son 137 sitios donde equivocarse y habría que
escribir un `data-label` por celda—. Se hizo con **una pieza**: una función que envuelve
cualquier tabla y deriva las etiquetas de su propia cabecera, más un observador que la
aplica también a las que se pintan al llegar los datos, que son casi todas. Se prueba
entera y se quita de una vez si molesta.

Las cuatro formas que se dan en el CRM están cubiertas y ninguna se rompe: la pelada, la
que ya llevaba `ui-table` —no se envuelve dos veces—, la que no tiene cabecera —se
envuelve pero no se inventan etiquetas— y la fila de «sin resultados» con `colspan`,
donde la posición ya no dice la columna y etiquetar mal sería peor que no etiquetar.

En escritorio la tabla se ve igual que antes; en móvil se apila con sus diez campos.
Las dos vistas miradas a ojo.

Prueba: `tests/test_todas_las_tablas_se_ven_en_movil.py`.

## La suite prueba SQLite; producción es Postgres

Petición: «corre la suite contra Postgres». **No se puede, y conviene saber por qué.** De
los 163 ficheros de prueba, **68 abren SQLite a mano** —`open_sqlite_conn`,
`pragma table_info`, `import sqlite3`— y **47 fuerzan `DATABASE_URL=""`** al importarse.
No es un interruptor que falte: es una reescritura de la mitad de la suite.

Lo que sí se hizo: levantar un Postgres aislado en el bucle local, comprobar que el CRM
**arranca y se usa sobre él** —las 156 tablas se crean sin un solo error, y login, sesión
y lecturas responden— y luego medir una por una las divergencias entre las dos bases.

### Lo que SQLite tolera y Postgres no

| | SQLite | Postgres |
|---|---|---|
| `importe = '2.450,75'` en columna numérica | lo guarda (como 2,45) | **rechaza la fila** |
| `WHERE columna_de_texto = 1` | empareja por afinidad de tipo | **la consulta no compila** |
| `GROUP_CONCAT` sobre columna numérica | devuelve el texto | **no existe esa función** |
| `INSERT OR REPLACE` con unicidad que no es `id` | reemplaza en silencio | **viola la restricción** |
| `LIKE '%modernia%'` sobre «Modernia» | 1 resultado | 0 resultados |

De las cinco, **ninguna ocurre hoy en el código**: los siete `GROUP_CONCAT` van sobre
texto, los tres `INSERT OR REPLACE` se bifurcan a mano por backend, las búsquedas usan
`LOWER()` y no hay comparaciones texto/número en consultas. Se comprobó una por una
contra el esquema real, no de oídas. Pero ya nos costó un diagnóstico equivocado —el
importe de gestoría, contado primero mirando sólo SQLite—, así que queda medido y escrito.

Prueba: `tests/test_lo_que_sqlite_esconde.py`, que además levanta el esquema entero sobre
Postgres y comprueba que las migraciones de esta campaña aplicaron allí. Todo el arranque
va envuelto en `try/except`: una migración que no traduzca no se ve al levantar, se ve el
día que alguien abre la pantalla que usaba esa columna.

### Las pruebas podían conectarse a producción

Importar `web.db_backend` vuelca `.env` en el entorno —a propósito, para que el servidor
arranque sin exportar nada—. El efecto colateral: **dentro de la suite, `DATABASE_URL` es
la base de producción**, aunque nadie la haya exportado.

`tests/test_puntos_de_retorno_postgres.py` la leía. Pedir sus pruebas de Postgres abría
una conexión a Frankfurt y hacía DDL allí. No hizo daño porque trabaja sobre una tabla
temporal y deshace siempre — pero era el patrón que iban a copiar las siguientes, y la
suite crea y borra tablas.

Arreglado con `tests/_postgres_de_pruebas.py`: el DSN se lee de una variable propia,
`CRM_POSTGRES_PRUEBAS`, nunca de `DATABASE_URL` ni de `.env`; y si apunta fuera del bucle
local **falla**, no se salta —saltar dejaría creer que se probó—. Lo que necesita base
propia usa una de usar y tirar que se borra al terminar.

El candado de `main()` protege el arranque del servidor. Éste protege la suite.

### El traductor devolvía SQL inválido en silencio

`_rewrite_insert_or_replace` devolvía la sentencia intacta cuando no sabía reescribirla.
Pero `INSERT OR REPLACE` no es sintaxis de Postgres: dejarlo pasar sólo cambia dónde
muere —del traductor al servidor— y con un mensaje que no dice nada, «error de sintaxis
en o cerca de OR». Ahora lanza un error que nombra la tabla y dice qué escribir.

Hoy no salta: los tres sitios que lo usan se bifurcan a mano. Está para el cuarto.
`crm_meta` tiene la clave primaria en `key`, no en `id`.

### Cómo se corre

```
CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \
    .venv-test/bin/python -m pytest tests/test_lo_que_sqlite_esconde.py
```

Sin la variable se salta limpiamente, que es como corre en la suite normal. Cómo levantar
el Postgres está en la cabecera de `tests/_postgres_de_pruebas.py`.

## Volumen: qué pasa con los datos que hay de verdad

Todo lo auditado en esta campaña se probó con **cuatro vecinos y tres clientes**. La
escala real, medida en producción el 2026-08-25:

| | |
|---|---|
| clientes | **2.262** |
| vecinos / comunidades | 318 en 14 (la mayor, **59**) |
| recibos de fincas | **0** — el módulo está cargado y todavía no ha facturado |
| reglas de importación de gestoría | 16.528 |
| asientos de gestoría | 1.225 |
| pólizas | 408 |

Dos guiones lo montan y lo miden, sembrando la base y luego **usando el CRM por la
puerta de delante**:

```bash
CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \
    python scripts/mide_el_volumen.py --escalas 2262,10000,25000
    python scripts/mide_el_volumen_fincas.py --vecinos 59 --meses 12
```

### Lo que aguanta

El servidor escala bien, y eso es un resultado, no una suposición:

- La lista de clientes: 14 ms con 2.262, 119 ms con **25.000**. Lineal, sin consultas
  por fila escondidas.
- Emitir un mes de recibos para 318 propietarios: 165 ms el primer mes y **162 ms el
  duodécimo**, con 3.498 recibos ya dentro. Plano — emitir no repasa lo emitido.
- La remesa SEPA de 318 adeudos sale con su `CtrlSum` cuadrando al céntimo. Un fichero
  que no cuadra lo rechaza el banco entero, no una línea.

### La lista de clientes enseñaba 120 de 2.262 y no lo decía

La pantalla de clientes del workspace pide 120 y pinta 120. Con una gestoría pequeña
eso ES la lista completa; con la de verdad son los 120 primeros por orden alfabético y
**nada lo distinguía**. El pie decía «CRM 360 cargado.»

Se puede llegar a los demás —el buscador manda la consulta al servidor y encuentra al
último del abecedario, comprobado— pero hay que saber que hay más para buscarlos.

Arreglado: el servidor devuelve el total, y la lista dice «120 de 2.262 clientes · busca
por nombre, DNI, teléfono o email para llegar al resto». El total sólo se cuenta cuando
la lista viene llena, para no pagar un `COUNT` en cada tecleo.

Prueba: `tests/test_una_lista_cortada_lo_dice.py`.

### Los importes de los recibos se sumaban sobre la página

Con 1.200 recibos y 120.000 € emitidos, el panel de recibos decía **800 recibos ·
80.000 € emitido · 80.000 € pendiente**. La lista tiene un tope de 800 filas —razonable—
pero el resumen se calculaba sobre esas 800.

**Hoy la pantalla no lo alcanza**: el front siempre pide un mes concreto, y un mes son
59 recibos en la comunidad más grande. Para llenar la lista haría falta una comunidad de
más de 800 pisos. O sea que no hay ninguna cifra mal en producción — esto quita la
trampa antes de pisarla, que es justo el momento de hacerlo: fincas tiene cero recibos y
está a punto de empezar a emitir.

Arreglado: el resumen sale de un agregado sobre todos los recibos del filtro. Y si el
agregado falla, se devuelven las cifras de la página **marcadas como parciales**: antes
un número pequeño y honesto que uno grande y falso.

Prueba: `tests/test_el_resumen_no_se_calcula_sobre_una_pagina.py`.

### El candado dejaba pasar el bucle local

El candado bloqueaba **cualquier** Postgres fuera de la nube, también uno en 127.0.0.1.
La salida era `--permitir-produccion`, y esa bandera convertida en costumbre sí abre la
base real. Ahora el bucle local pasa —diciendo a qué base se conecta— y lo remoto sigue
preguntando. Un `localhost.loquesea.com` no cuela.

### Lo que se dobla por encima de la escala real

Sin urgencia, porque queda muy por encima de lo que hay, pero anotado:

- **Morosidad** pasa de 5 ms con 318 vecinos a **2,8 s con 1.000**. Crece mucho más
  rápido que los datos.
- **Balance** hace lo mismo: 39 ms con 59 vecinos, 1,2 s con 1.000.

La comunidad más grande de producción tiene 59 propietarios, así que ninguna de las dos
molesta hoy.

## Concurrencia: dos personas a la vez

Todo lo anterior se midió con **un usuario**. Modernia tiene 19, el servidor va con
hilos, y dos administradoras pueden estar en la misma comunidad a la misma hora.

```bash
CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \
    python scripts/prueba_de_concurrencia.py --a-la-vez 6 --vueltas 3
```

Va **contra Postgres a la fuerza**: SQLite serializa las escrituras con un cerrojo de
base entera, así que esconde justo esta clase de fallo.

### Numerar una factura estaba roto en Postgres

No es un fallo de concurrencia: es que no funcionaba. El `SELECT` pedía dos columnas sin
nombre —`COALESCE(prefijo,'')` y `COALESCE(siguiente_numero,1)`— y en Postgres la fila
vuelve como diccionario: **las dos se llaman «coalesce» y una pisa a la otra**, así que
la fila es `{'id': …, 'coalesce': 1}` y `series_row[1]` revienta con `KeyError`.

Traducido: rellenar la serie y dejar el número en blanco —que es lo que dice el
formulario, «Autogenerado»— devolvía un 500. En SQLite las filas se indexan por posición
y no se notaba. Producción no tiene ninguna serie creada todavía, así que nadie lo ha
pisado; el primero que lo haga, sí.

### Y la numeración era una carrera

Leer el contador, componer el número y guardar el siguiente son tres pasos. Dos
peticiones leían el mismo y salían **dos facturas con el mismo número**, que en una
numeración correlativa no es una molestia sino un problema.

Ahora es un `UPDATE … RETURNING`: el contador se reserva y se lee de una vez, con la
fila bloqueada mientras tanto. Y un índice único de `(workspace, empresa, serie, número)`
detrás, porque una comprobación antes de insertar no ve lo que otra petición está
escribiendo sin confirmar; el índice sí. Medido: en ninguna ejecución se repite un
número.

### Emitir los recibos del mes a la vez daba un 500

El bucle mira si el recibo existe y lo inserta. Con dos personas las dos pasan la
comprobación y una choca con el índice único. **Que choque es lo que hay que querer** —el
índice es lo que impide cobrar dos veces al vecindario, y funciona: nunca aparece un
propietario con dos recibos—. Lo que no valía es que saliera como error del servidor.
Ahora responde «los recibos acaban de emitirse desde otro sitio, recarga para verlos».

### Lo que se deja abierto, y por qué

**La serie se bloquea durante toda la petición.** El `UPDATE` retiene la fila hasta que
la petición confirma, y eso no pasa hasta el final, después de guardar la factura y de
correr las automatizaciones. Con seis personas a la vez, medido, **ocho de cuarenta y
ocho facturas no salen**: unas con 500 por `lock_timeout`, otras rechazadas por número
duplicado. Fallan a la vista, y el número nunca se repite, pero fallan.

Lo suyo sería confirmar la reserva en el acto y soltar el candado, aceptando que un
fallo posterior deje un hueco en la numeración. Se probó: sube a **47 de 48** y
desaparecen los 500. Pero **una de esas 48 devolvía 200 sin guardar la factura**, y no se
ha encontrado por qué. Cambiar un fallo que se ve por uno que no se ve, en facturación,
es peor negocio. Queda anotado en el código, donde se va a leer.

### Dar de alta el mismo cliente a la vez creaba fichas duplicadas

Seis peticiones con el mismo NIF a la vez dejaron **cuatro fichas**. La comprobación de
duplicados mira lo confirmado, así que no ve a las otras cinco. Y una ficha duplicada no
se arregla sola: hay que fusionarla a mano decidiendo cuál es la buena.

Arreglado con un índice único que usa **el mismo criterio que la comprobación** —NIF en
mayúsculas y sin espacios, puntos ni guiones, dentro del workspace—. Si usara otro,
rechazaría altas que la aplicación considera distintas. El choque devuelve el 409
«Cliente duplicado» de siempre, con el id de la ficha que ganó, para acabar en la ficha
buena en vez de en un error. Medido después: seis altas simultáneas, **una ficha**.

Y si algún día no se puede crear el índice, **el arranque lo dice** con la cuenta de
grupos pendientes de fusionar. Un `try/except` mudo ahí dejaría creer que existe.

Para poder crearlo hubo que tocar producción. Tres clientes tenían `nif = 'ES'`, que no
es un NIF: **Caja Diaria** y **DOMINGO ALVAREZ DE LOS SANTOS**, éste dos veces. No se
borraron las fichas —son reales y las tres tenían vínculo con su empresa—: se vació el
campo del NIF, que era lo que estorbaba. Los 2.262 clientes siguen ahí y el estado previo
quedó guardado antes de tocar nada.

Queda una decisión aparte: **las dos fichas de DOMINGO ALVAREZ DE LOS SANTOS siguen
siendo un duplicado** y hay que fusionarlas. El índice ya no lo impide porque ninguna
tiene NIF, pero el duplicado sigue ahí.

## Los duplicados de clientes: qué los hizo

Producción tenía **42 grupos de fichas repetidas, 71 de más**. Revisados uno a uno, no
eran un problema sino tres.

### Una ficha por póliza en vez de una por titular

20 grupos se crearon **el mismo segundo**, `2026-08-04 12:20`, todos de seguros. Copias
exactas: comprobadas columna por columna, ninguna difiere. Y cada ficha con **una sola
póliza**: GARCISA MASAE ×10 = 10 pólizas, JUAN RAMOS ×8 = 8 pólizas.

Lo hizo `scripts/alta_titulares_como_clientes.py`. Carga el índice de clientes **una
vez, antes de decidir**, y el bucle que crea nunca lo actualiza: diez pólizas del mismo
tomador consultan las diez el mismo índice vacío y las diez concluyen «no existe ficha».
La huella de su `INSERT` —`id, empresa_id, nombre, estado='Activo', workspace_id,
created_at, updated_at` y nada más— coincide exactamente con lo que había en la base.

El guion ya se cuidaba de no elegir mal entre varias candidatas. No vigilaba fabricarlas
él mismo. Arreglado: la primera fila de cada nombre crea, las demás se enlazan.

Otros 7 grupos son la misma historia en otra tanda: el `2026-04-21 06:02` se crearon 78
fichas, **ninguna con NIF**, gemelas de gente que ya existía. La buena es la del
`2026-03-24`: 619 clientes, todos con su documento.

### Y una trampa peor, que no llegó a saltar

`clave_de_nombre` **borraba los dígitos** al comparar nombres. En una administración de
fincas eso significa que «Sierra Bermeja 5» = «Sierra Bermeja 7», «Emilio Prados 26» =
«Emilio Prados 6», «Barcenillas 6» = «Barcenillas 12». Y el guion **enlaza sin preguntar
cuando encuentra una sola candidata**: la póliza de un edificio se habría colgado del
edificio de al lado, en silencio.

Comprobado antes de tocarlo: **no llegó a pasar** —0 de 392 pólizas y 0 de 108 hipotecas
estaban enlazadas a una ficha que sólo difiriera en el número—. Arreglado conservando los
números, lo que hace la clave más estricta: como mucho deja un duplicado, que se ve.

### La limpieza

`scripts/fusiona_clientes_duplicados.py` deja una ficha por cliente. Busca las columnas
que apuntan a clientes **en el esquema**, no en una lista escrita a mano; mueve todo lo
que colgaba de las retiradas; hereda los datos que sólo tenían ellas sin pisar los de la
que se queda; y **descarta el grupo si sus fichas tienen documentos distintos**, porque
mezclar a dos personas no se deshace mirando la base.

Aplicado el 2026-08-25: **69 fichas retiradas, 210 referencias movidas, 2.261 → 2.192
clientes**, cero referencias sueltas. Con respaldo completo en `clientes_fusion_backup`.

Quedan **2 grupos sin fusionar, a propósito**: VILLABA BAEZ GLADYS RAQUEL (un DNI de
persona y un CIF de sociedad) y LOPEZ CONDE JOSE (dos DNI). Ésos los decide una persona.

### Lo que se aprendió por las malas

Dos cosas fallaron durante la propia limpieza, y las dos están arregladas en el guion:

- **Preguntar por ficha y por tabla** eran 3.588 consultas contra un servidor al otro
  lado de Europa. La conexión se cayó a mitad. Sin daño —va en una transacción— pero sin
  terminar. Ahora se pregunta una vez por tabla: 52.
- **Una lista de ids dentro de un JSON** (`cliente_ids_json`) no se cambia con un
  `UPDATE` de igualdad: el valor es `["abc…"]`, nunca el id pelado. Se quedaron tres
  apuntes de contabilidad nombrando a una ficha retirada. Corregidos, y el guion ahora
  sustituye dentro del texto comprobando que siga siendo JSON válido.

## El lector de pólizas inventaba nombres, y con ellos clientes

Las fichas de cliente llamadas «Y CONDUCTOR», «del Seguro Por SANITAS», «Edificación y
anexos» o «de la póliza TERESA RAMOS RUEDA» que había en producción no las tecleó nadie:
**las escribió el OCR**. Cuando un PDF no encaja con el patrón de su compañía, el lector
recorta la zona donde suele ir el tomador y se trae lo que hubiera al lado — la letra
pequeña, la etiqueta del impreso, o media palabra cortada por el margen.

«Y CONDUCTOR» salió de `POLIZA AUTO Nº 2002400455146 - ADRIAN GUTIERREZ.pdf`.

### Medido, no supuesto

Los PDF de la correduría se nombran `COMPAÑÍA RAMO NOMBRE Póliza NÚMERO.pdf`, así que el
nombre del fichero sirve de referencia y se puede medir el acierto sobre **133 pólizas
reales** sin teclear nada. Eso es `scripts/mide_el_ocr_de_polizas.py`.

| | antes | después |
|---|---|---|
| **tomadores inventados** | **40** de 122 | **7** |
| aciertos | 59 | 59 |
| lo deja vacío | 23 | 56 |
| número de póliza | 83 % | 83 % |

De 40 nombres falsos a 7, sin perder un acierto. Lo que hace el arreglo es convertir
«inventado» en «vacío», y **no son el mismo fallo**: vacío se lo pregunta a una persona,
inventado lo escribe en la base. Occident pasó de 10 a 0; Mapfre, de 7 a 0.

Los 7 que quedan no son fallos: son pólizas de impago donde el fichero lleva la dirección
del piso alquilado (`ARAG IMPAGO - FLORES GARCIA 3, BAJO 5.2`) y el lector saca al
arrendador, que es lo correcto.

### Cómo funciona

Dos piezas, ambas en `web/server.py`:

- `limpia_tomador` quita lo que viene pegado a los extremos: la etiqueta del impreso
  («de la póliza …»), los restos del margen («up … oD», «ica … pl») y el documento de
  detrás («… NIF: 24835591F»). Sólo toca los bordes: «MALAGAMBA **DE OÑA** FERNANDO»
  conserva su partícula.
- `tomador_parece_un_nombre` descarta lo que es texto de contrato. La lista de palabras
  sale del corpus real, no de la imaginación.

### Dos errores por el camino, que valen más que el arreglo

**Medí antes de comprobar la vara.** La primera medición decía «Occident 0 de 12» y estuve
a punto de reescribir un lector que funcionaba: era mi extractor de referencia, que tiraba
la letra de control del número (`8 11.239.386 E`). Corregida, el número estaba al 83 %, no
al 67 %.

**Y la primera prueba no probaba nada.** Quité el arreglo del código y las trece pruebas
siguieron en verde: comprobaban las funciones sueltas, no que el lector las llamara. Sólo
lo detectó la medición sobre el corpus. Hay tres pruebas más que ejercitan
`parse_poliza_text` entero, y ésas sí se ponen rojas.

Prueba: `tests/test_el_tomador_que_no_era_un_nombre.py`.

### Lo que la carpeta de OneDrive no arregla

Se revisaron los 133 PDF contra la base (`scripts/prueba_lector_de_polizas.py`, en local y
sin que ningún documento salga del equipo). **113 pólizas ya existen en el CRM** casadas
por número, y **110 de ellas ya tienen su PDF dentro**. Sólo faltan 5 documentos y 14
pólizas nuevas.

Es decir: subir la carpeta **no resuelve las 66 pólizas sin número**. Ésas no están aquí.

## Qué NO cubre esto todavía

Conviene tenerlo claro para no dar por auditado lo que no lo está:

- **Los caminos que se salen de lo normal, salvo en fincas.** Ahí ya están: derrama,
  cambio de propietario, recibo devuelto, censo descuadrado y cierre de ejercicio.
  En seguros ya están los de la póliza: cambio de compañía, anulación y recibo
  devuelto. Están los seis módulos, con sus caminos raros, las nóminas y la conciliación
  bancaria. En fincas ya están: ciclo mensual, caminos raros, junta completa, cómputo de ausentes e impugnación.
- **El HTML y el CSS.** El contraste de arriba cubre lo que la pantalla *recibe*; lo que
  *pinta* —columnas, colores, etiquetas— sigue pendiente de recorrer con un navegador.
- **La suite entera sobre Postgres.** Se cubre la capa donde las dos bases se separan
  (arriba), no las 3.000 pruebas. Para eso habría que reescribir los 68 ficheros que
  abren SQLite a mano.
- **Concurrencia bajo carga sostenida.** Se han probado seis personas a la vez (arriba);
  no se ha probado el sistema entero con todo el equipo trabajando a la vez durante
  horas, ni qué hace el pool de conexiones ahí.
- **Migrar una base antigua** y **restaurar desde copia**: siguen sin una sola prueba.

## Anotaciones menores

- Un parámetro que falta en `/api/captacion_convert` responde **403 «id requerido»** en
  vez de 400. No es visible para el usuario —la interfaz manda el nombre correcto— pero
  despista a quien depure.
- Una visita se liga al comprador **por demanda**, no por cliente: la tabla `visitas` no
  tiene `cliente_id`. Es el modelo, no un fallo, pero conviene saberlo al leer el código.
