# Fase 2.1 — Fechas y ordenamiento

Base: f81019646f64807b45b74fff7c6835e8b9c1eef2. Sin migraciones ni actualizaciones de
registros existentes. Ningún hash, relación, fecha almacenada o clasificación CAT-01
se modifica. No se ejecutaron Docker, HTTP, scraping ni Gemini.

## Defectos y decisión compatible

El orden previo `publicacion DESC NULLS LAST, captura DESC, PK DESC` agrupaba todas
las noticias con fecha del medio por delante de las que sólo tenían captura.
Una noticia antigua recién ingerida aparecía antes de una manual actual. Además,
si ambas tenían igual fecha de publicación, la captura decidía antes que la PK.
El dashboard usaba exclusivamente captura, dando un orden diferente.

Ahora las tres consultas usan `COALESCE(fecha_publicacion, fecha_captura) DESC
NULLS LAST, PK DESC` dentro de SQL, antes del límite o de paginar. Una misma fecha
efectiva desempata exclusivamente por PK descendente. PostgreSQL compara instantes
con zona, sin convertirlos a cadenas ni ordenar listas en Python. Se conserva la
precisión completa del timestamp al ordenar. Los dos campos nulos quedan al final;
el modelo impide captura nula en BD, pero la presentación también tolera ese caso.

No se añade orden global al modelo: workers y consultas de auditoría específicas
conservan sus políticas. La paginación sobre un conjunto estable es determinista;
la paginación por offset aún puede desplazarse ante altas concurrentes. No se
introduce cursor ni se cambia el límite público de 150 o el del panel de 100.

## Fechas almacenadas y precisión

- RSS: fecha conocida del medio en fecha_publicacion, posiblemente nula si pubDate
  falta o no se interpreta. Fecha_captura es el momento de incorporación.
- Histórico: fecha del artículo, o el día de la URL representado desde antes por
  12:00 UTC si no hay timestamp. Ese valor se conserva por compatibilidad, sin
  afirmar que sea la hora del medio. No se reescriben fechas antiguas ni nuevas
  bajo una convención distinta en esta fase.
- Scraper alternativo y formulario web: captura actual; fecha_publicacion nula.
- API manual: excepción histórica documentada abajo.

Sin un marcador persistente de precisión no se puede distinguir retrospectivamente
una hora real de una inferida. Se presenta **todo** El Territorio (Archivo) con
fecha del medio como día solamente. Esto oculta conservadoramente horas quizá
reales, sin perderlas en almacenamiento. La hora interna aún participa del orden
intradiario; el orden preciso entre noticias de día conocido no es comprobable.
Si se necesita esa garantía hace falta una propuesta de precisión/procedencia
persistente con migración nueva, nunca una inferencia masiva sobre históricos.

El detalle mantiene la línea de captura, etiquetada como incorporación, y añade
el día de publicación/incorporación. Para archivo indica «Hora no verificada» y
usa datetime de calendario sin hora. No se añade fecha ficticia si ambas faltan.
Los datos heredados cuya fuente no identifique Archivo no pueden detectarse como
inferidos con certeza; es una limitación de procedencia, no se reclasifican.

Django utiliza USE_TZ y America/Argentina/Buenos_Aires. El nuevo día de navegación
se calcula en esa zona, no cortando el ISO UTC ni según la zona del navegador.
02:00 UTC pertenece al día anterior; 03:00 UTC inicia el nuevo día local. Un objeto
Python defensivo sin tzinfo se interpreta explícitamente en Buenos Aires sin
mutarlo; las lecturas normales del ORM son aware. El parser RSS/histórico existente
interpreta timestamps sin zona como UTC: no hay evidencia suficiente para cambiar
esa convención de origen unilateralmente.

## API y alta manual

Se conservan íntegros los campos legacy:

- Listado global: `fecha` es captura formateada sin offset y `fecha_publicacion`
  es el valor almacenado ISO, posiblemente nulo.
- Listado por localidad: `fecha` es el timestamp efectivo ISO como antes.

Se añaden en ambos listados:

- `fecha_efectiva`: ISO con offset local, o YYYY-MM-DD para Archivo con fecha del medio.
- `fecha_dia`: YYYY-MM-DD en Buenos Aires para filtros de calendario.
- `fecha_precision`: instante/dia; nulo si no hay fecha.
- `fecha_origen`: publicacion/captura; nulo si no hay fecha.

Los campos legacy pueden contener el timestamp artificial histórico. Se preservan
para no romper clientes; un consumidor que quiera mostrar hora debe usar los nuevos
metadatos de precisión. `instante` significa precisión del timestamp disponible,
no certificación externa del medio. La precisión de un RSS que aparenta timestamp
pero deriva de una fecha sin hora no se puede verificar sólo con el valor guardado.

**Bloqueo funcional preservado:** el parámetro público fecha_publicacion del alta
manual significa realmente captura desde antes de PR #23. Se mantiene su valor
opcional, validación ISO y default now; no se copia a fecha_publicacion del modelo.
Su help_text documenta el alias histórico. Omitirlo da captura actual. Proporcionarlo
conserva la captura indicada por el cliente, que puede diferir de la incorporación
real: la semántica ideal no puede cumplirse para ese caso sin cambiar contrato o
agregar almacenamiento. Las regresiones existentes de serializer y roles verifican
esta excepción. Propuesta futura: endpoint/versionado explícito con captura del
servidor y fecha del medio opcional, manteniendo la ruta antigua hasta migrar clientes.

## PR #24: revisión de objetos Git, sin tocar otro worktree

En 7acc16a el calendario del panel filtra `data-capture-date` y su etiqueta dice
«Fecha de captura»; no usa fecha efectiva. Su filtro es coherente con esa etiqueta,
pero difiere de navegación por fecha del medio. Al integrar hay que elegir de forma
explícita si conservar filtro de captura o añadir otro basado en `fecha_dia` y
renombrarlo. No reinterpretar silenciosamente el filtro. Su límite mínimo está
fijado al 01/01/2026 y excluiría históricos anteriores si se reutiliza para publicación.
PR #24 conserva el orden anterior en vistas: resolver el conflicto manteniendo
Coalesce, el prefetch adicional de categorías y sus otros campos. El detalle tiene
ediciones adyacentes: conservar los dos bloques sin duplicar fechas.

## Validación realizada y pendiente

Disponibles sin instalar dependencias:

```sh
python3 -B -m unittest discover -s tools/fase2_1 -p 'test_*.py'
python3 -B -m unittest discover -s tools/fase1_1 -p 'test_*.py'
python3 -B tools/fase1_2/test_unit.py
```

Resultados: 9/9 de fecha/presentación/expresión ORM simulada; 32/32 de arnés;
26/26 de ingesta. No equivalen a validación de SQL PostgreSQL.
Compilación estática y git diff --check satisfactorios. Django no está instalado
en el Python local: no se ejecutaron check ni suite ORM durante esta tarea.

El arnés conserva por separado las 64 y 54 pruebas anteriores y añade un tercer
bloque `core.test_fechas` de **14 pruebas ORM** (incluye presentación defensiva).
Se comprobaron estáticamente sus guardas: red nueva isolated, tmpfs, sin volúmenes
persistentes, código read-only, conexión PostgreSQL verificada por identidad antes
de habilitar escritura, sin ampliar destinos ni permisos. No se verificó runtime
ni se ejecutó Docker: falta autorización específica de ejecución en esta fase.

Comando único preparado para una ejecución manual posterior, sin sudo:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-estabilizacion/tools/fase1_1/run.py
```

Esperar check satisfactorio y bloques de 64, 54 y 14 sin skips inesperados.
Las pruebas cubren mezcla de fuentes, fechas nulas, empates entre publicación y
captura, offsets equivalentes, madrugada local, límites previos al paginado,
paginación estable, dashboard, RSS inválido y archivo inferido sin reescritura.


## Validación integral posterior completada

El usuario confirmó la ejecución satisfactoria del arnés PostgreSQL/PostGIS
descartable, después de corregir el fixture que enviaba departamento=None a un
campo NOT NULL. El test usa ahora clasificación local real con usar_ia=False;
la ausencia de departamento se representa con cadena vacía.

- Fase 1.1: **64/64**.
- Fase 1.2: **54/54**.
- Fase 2.1: **14/14**.
- Total: **132/132 pruebas aprobadas**.
- Django System Check: **correcto, sin incidencias**.

Esta confirmación posterior sustituye el estado pendiente de la sección anterior,
que se conserva como historial de la preparación y sus límites en ese momento.
Durante la preparación de este checkpoint no se ejecutó Docker ni se repitieron
pruebas, servicios externos o migraciones.
