# Integración preparatoria PR #23 estabilizado + PR #24

Worktree: `/home/sebas/Escritorio/trendwatch-pr23-pr24-integracion`.
Rama: `fix/integracion-pr23-pr24-estabilizada`.
HEAD de partida: `09ec0072e3b480b81fc21a34accdaca3c53958b0`.
PR #24 fijado: `7acc16a7d0ef8fd5d10abe7be9a1594d48936981`.
Base común: `dace336899c05d41459b0275eb61b8d37f4e717c`.

## Dependencias y alcance

Ambas puntas tienen cinco commits exclusivos. La referencia auditada sigue siendo
una pila sobre el PR #23 original, sin las cinco estabilizaciones. No se hizo
fetch ni se afirma que el estado remoto actual coincida con la referencia local.
PR #24 se incorpora completo, sin copiar vistas aisladas:

| Commit | Cambios y dependencias principales |
| --- | --- |
| `2a725c3` | Login, imágenes/alta-edición, dashboard/calendario, formularios, configuración de medios; migración 0007. |
| `f5c92ed` | Comentarios y valoraciones, modelos, permisos, rutas, detalle y pruebas; migraciones 0008–0009. |
| `358dd1c` | Navegación responsive de las categorías, layout y assets. |
| `f1556c7` | Mapa de categorías, navegación y limpieza de ejemplos del frontend. |
| `7acc16a` | Perfil privado y guardados, formularios/vistas/rutas/templates/pruebas; migración 0010. |

El delta original de PR #24 abarca 60 archivos, 2241 inserciones y 657
eliminaciones. Se conservan las doce categorías y sus asociaciones históricas;
PR #23/#24 prevalecen sobre CAT-01. No se introducen modelos ni migraciones
adicionales a los de PR #24.

## Operación Git y resolución

Primero se ejecutó `merge-tree --trivial-merge` de los tres árboles, sin aplicar
cambios. Después se aplicó un merge fijado en `7acc16a` con `--no-ff --no-commit`;
se deshabilitó rerere para esta invocación y no se usó autostash. Se deja el merge
pendiente, con HEAD en `09ec007`, sin crear commits ni mover referencias originales.

- `app/core/views.py`: tres conflictos. Los listados conservan metadatos de
  categorías (`categorias_detalle`, origen/sección) y adoptan `imagen_publica_url`
  de PR #24 sin cambiar la clave pública `imagen_url`. El dashboard conserva
  `Coalesce(fecha_publicacion, fecha_captura)` descendente y desempate por PK,
  nombres/IDs de categorías, sumando departamentos directos y por localidades.
- `app/core/templates/core/dashboard.html`: un conflicto. Se combinan los IDs y
  nombres asociados con atributos de captura y departamentos, filtros y edición.
- `app/core/templates/noticia.html`: merge automático revisado semánticamente.
  Se conservan fecha efectiva y aviso de hora no verificada del archivo, categorías
  separadas de sección, imágenes, comentarios, valoraciones y guardados.
- `app/static/js/landing-news.js`: merge automático revisado semánticamente.
  Mantiene lectura múltiple de categorías y listas vacías autoritativas, tarjetas
  navegables, imágenes locales y ausencia de datos de muestra.

El calendario continúa siendo un filtro de **captura**, según su etiqueta y
atributo `data-capture-date`, mientras el orden de filas usa fecha efectiva.
No se cambia silenciosamente ese contrato ni su mínimo original de enero de 2026.
La fecha legacy de API continúa siendo captura; los campos efectivos son aditivos.

Las migraciones `0007_publicacion_imagen_archivo`, `0008_comentario`,
`0009_valoracionpublicacion` y `0010_perfilusuario_publicacionguardada` se conservan
byte por byte respecto de PR #24, encadenadas desde 0006. No se modifica
`AUTH_USER_MODEL`, ninguna migración previa ni dato existente. No se ejecutan.

## Regresiones y validación disponible

Se agregan cuatro regresiones ORM en `core.test_integracion_pr24`: combinación de
imágenes/categorías/orden en listados global y territorial; dashboard con orden,
categorías, localidad y captura al límite de día; detalle histórico con precisión
y funciones sociales/guardados; ausencia de asociaciones y fallback de imagen.
Usan BD de pruebas y referencias sintéticas de archivos, sin descargas ni archivos
reales. Quedan pendientes de ejecución en PostgreSQL.

El arnés agrega un bloque `PR24_LABELS`: los cinco módulos originales de PR #24
(32 pruebas) y las cuatro regresiones anteriores. Se conservan los cinco bloques
anteriores y sus 203 pruebas. Total preparado: **239 pruebas ORM**, todavía no
validado sobre este árbol. Se ajusta la prueba del plan para exigir los seis
bloques en orden y comprobar que las nuevas etiquetas resuelven.

Comprobaciones locales, sin bases ni servicios:

- Fase 1.1: 32 pruebas unitarias del arnés. Una primera ejecución encontró la
  restricción de escritura del sandbox al crear su directorio temporal; se repitió
  con autorización del comando y pasó 32/32. El cliente Docker está simulado.
- Fase 1.2: 26/26; fechas: 9/9; categorías: 16/16; Fase 2.3: 21/21.
- Integración: dos pruebas unitarias ejecutan funciones reales de vistas extraídas
  por AST con ORM simulado; cuatro escenarios JS ejercitan funciones reales de
  tarjetas/categorías con DOM simulado. No abren red ni cargan imágenes.
- Frontend previo: nueve escenarios JS de categorías. Puertos: dos comprobaciones.
- Compilación en memoria de Python, sintaxis de JS y `git diff --check` al cierre.

No hay Django ni DRF disponibles en el Python anfitrión; no se ejecutaron Django
check ni pruebas ORM. Las **203/203 PostgreSQL/PostGIS anteriores** son el checkpoint
informado por el usuario, no un resultado de la integración actual. No se ejecutan
Docker, scraping, Gemini, HTTP, bases reales ni migraciones; no se instalan paquetes.

El arnés conserva sus defensas: imágenes locales fijadas sin pull/build, red nueva
interna isolated sin puertos, contenedores propios, datos en tmpfs, copia de código
sin medios/.env/SQLite, directorios de medios temporales y validación de identidad
PostgreSQL antes de escribir. Solo cambia la selección de pruebas, no el transporte
ni las políticas de aislamiento. Su ejecución requiere autorización separada y
superar todas sus guardas desde la terminal normal:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-pr24-integracion/tools/fase1_1/run.py
```

Esperar Django check correcto y bloques **64 + 54 + 14 + 24 + 47 + 36**,
sin skips inesperados. No equivale a toda la suite del repositorio ni a validación
visual del navegador. El arnés no copia assets estáticos; las comprobaciones JS
locales cubren parte de ese límite.

## Riesgos que no se resuelven mediante este merge

- **AUD-01 sigue presente** en `views_perfil.py` original: ModelForm guarda la
  instancia completa. La siguiente corrección debe limitar columnas autorizadas
  y probar rotación concurrente de contraseña. No se altera esa funcionalidad
  incidentalmente para resolver conflictos.
- La confirmación de cambio de email usa una instancia potencialmente obsoleta;
  requiere validación sobre usuario fresco y pruebas de intercalado. La política
  de colisiones entre username/email queda pendiente. Consultar el PLAN preservado
  sin seguimiento en el worktree original `trendwatch-pr23-estabilizacion`.
- La compatibilidad ORM/migraciones del conjunto y las pruebas de imágenes/perfil
  requieren la ejecución descartable pendiente. La interfaz necesita revisión
  visual posterior; los escenarios con DOM simulado no la sustituyen.
- Siguen los límites previos de clasificación territorial heurística,
  equivalencia URL conservadora y tiempos DNS/cabeceras/Gemini documentados en
  Fase 2.3. No se amplía el alcance para resolverlos.

No crear el commit de merge ni publicar/integrar ramas sin autorización nueva.


## Resultado del cierre

- Merge sin commit: HEAD en `09ec007`, MERGE_HEAD en `7acc16a`, sin entradas
  no resueltas. Índice con 66 rutas; sin cambios adicionales fuera del índice ni
  archivos sin seguimiento. Referencias originales y estados/diffs observados de
  los demás worktrees intactos, incluido el PLAN original sin seguimiento.
- Pasaron 106 pruebas unitarias Python (32 + 26 + 9 + 16 + 21 + 2), dos
  comprobaciones de puertos y 13 escenarios JavaScript (9 + 4).
- Compilación en memoria: 81 archivos Python. Sintaxis JS: 13 archivos.
  Cadena estática de migraciones 0006–0010 correcta; archivos intactos.
- `git diff --check` sin incidencias. El control estándar del índice señala
  el CR final de la línea 72 de `landing.html`: las 82 líneas de ese archivo usan
  CRLF, tal como en PR #24. No se normalizó el archivo ni se alteró configuración.
  La comprobación completa con ese formato admitido pasó mediante
  `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --cached --check`.
- Los 56 archivos exclusivos de PR #24 conservan los bytes originales; los
  otros cuatro incorporan las resoluciones textuales/semánticas descritas arriba.
  Las correcciones estabilizadas previas quedan intactas, salvo la ampliación
  explícita del plan de pruebas y su prueba unitaria.
- PostgreSQL, Django check, navegador real y AUD-01 continúan pendientes.
  No se creó commit ni se ejecutó Docker, push, migración o servicio externo.


## Validación posterior del merge, antes de AUD-01

El usuario confirmó **239/239 pruebas PostgreSQL/PostGIS aprobadas** para el árbol
integrado anterior a esta corrección. Esa confirmación sustituye el estado
pendiente de PostgreSQL de las secciones históricas anteriores. No es una nueva
corrida realizada desde Codex ni cubre todavía las cinco regresiones ORM AUD-01.

## AUD-01 — Corrección de persistencia de perfil

La advertencia histórica «AUD-01 sigue presente» queda sustituida por esta sección.
El merge permanece sin commit, con HEAD en `09ec007` y MERGE_HEAD en `7acc16a`.

### Causa y solución mínima

`PerfilForm` restringía la entrada a nombre, apellido y email, pero el
`datos.save()` heredado de ModelForm persistía todas las columnas de la instancia
`request.user`, leída anteriormente. Una segunda instancia podía guardar una
contraseña o atributos nuevos y perderlos al guardarse luego el perfil obsoleto.
`transaction.atomic()` no actualiza esa instancia ni limita las columnas escritas.

En la rama de edición de datos de `views_perfil.py`:

- Lista explícita permitida: `first_name`, `last_name`, `email`.
- Intersección de esa lista con `datos.changed_data`, calculada antes del guardado.
- `datos.save(commit=False)` y `usuario.save(update_fields=campos)` solo si hay
  campos permitidos editados; nunca guardar el User completo por esta ruta.
- Si solo cambian fecha de nacimiento/celular, no emitir UPDATE de User.
- Conservar el guardado de User y `PerfilUsuario.update_or_create()` dentro de la
  misma transacción y su rollback conjunto ante fallos.

Se mantienen el formulario y todas sus validaciones, propietario derivado de la
sesión, permisos, CSRF, métodos, errores, redirects y contrato HTTP. La rama de
cambio de contraseña conserva su validación y `update_session_auth_hash` originales.
La edición de datos no renueva el hash de sesión: una contraseña rotada desde otro
flujo debe invalidar la sesión anterior normalmente. No se tocan categorías,
fechas, funciones sociales, modelos, migraciones ni las resoluciones del merge.

### Regresiones y comprobaciones ejecutadas

Antes de cambiar la vista se ejecutaron cinco pruebas unitarias nuevas sobre la
función real extraída por AST, con almacenamiento/formulario simulados: **tres
fallaron y dos pasaron**, reproduciendo las sobrescrituras y el UPDATE innecesario.
No se presenta esa ejecución como reproducción ORM/PostgreSQL.

Después de la corrección:

- `python3 -B -m unittest discover -s tools/fase3_1 -p 'test_*.py'`: **7/7**
  (dos de integración previas y cinco nuevas de persistencia).
- `python3 -B -m unittest discover -s tools/fase1_1 -p 'test_validation.py'`:
  **7/7**, plan/etiquetas/copia/guardas; llamadas Django/Docker simuladas.
- Cinco pruebas nuevas de persistencia con Python `-O`: **5/5**.
- Compilación en memoria de **82 archivos Python**, sin crear pycache.
- `git diff --check` correcto para el cambio AUD-01. El índice original conserva
  su observación CRLF de `landing.html` y pasa con la opción por invocación
  `core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol`.

Se agregan **cinco pruebas ORM** a `core.test_perfil.PerfilTests`, conservando las
8 anteriores sin modificarlas:

1. Segunda instancia guarda una contraseña después de cargar/validar el usuario
   de la solicitud y antes del guardado real del formulario. Comprobar hash exacto,
   autenticación nueva/antigua, nombre editado, otro usuario intacto e invalidación
   de sesión vieja. El guardado real de User/ModelForm no se reemplaza por mocks.
2. Preservar username, staff/superuser, desactivación, last_login y date_joined
   cambiados por otra instancia durante el mismo intercalado.
3. Editar nombre sin reescribir email/apellido no editados y cambiados mientras tanto.
4. Cambiar solo fecha/celular sin invocar User.save, conservando persistencia extra.
5. Fallo del guardado de PerfilUsuario revierte el cambio de User dentro de atomic.

El intercalado es determinista con dos objetos ORM; no se afirma que sean dos
conexiones o hilos simultáneos. No se añade select_for_update ni un protocolo nuevo
de bloqueo. Los tests existentes siguen cubriendo confirmación de contraseña para
email, duplicados, CSRF, permisos y conservación de sesión al cambiar la clave.

El bloque existente `core.test_perfil` ya incluye las cinco nuevas; **el arnés no
se modifica**. Total preparado: **244** = 64 + 54 + 14 + 24 + 47 + 41. Las nuevas
pruebas ORM y la repetición integral están pendientes: Django no está disponible
en el Python anfitrión. No se ejecutaron Docker, Django check, migraciones, bases,
scraping, Gemini ni solicitudes HTTP, ni se instalaron dependencias.

Comando único de validación desde la terminal normal, con imágenes ya locales y
las guardas del arnés aprobadas, sin sudo:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-pr24-integracion/tools/fase1_1/run.py
```

Esperar los seis bloques **64, 54, 14, 24, 47 y 41**, total **244/244**, sin skips
inesperados, y Django System Check correcto. Es un resultado esperado, no ejecutado.
El arnés copia el árbol de trabajo, por lo que incluye esta corrección sin staging.

### Riesgos y estado Git

La corrección limita exclusivamente la persistencia autorizada. No promete
concurrencia optimista: dos ediciones explícitas del mismo campo permitido siguen
con política de última escritura. No sincroniza las ediciones simultáneas de los
campos adicionales de PerfilUsuario.

La comprobación de contraseña al cambiar email continúa usando la instancia del
request; la ventana de validación sobre una contraseña desactualizada descrita en
el plan sigue pendiente. No se cambia silenciosamente esa validación ni se afirma
que update_fields resuelva ese riesgo. Tampoco se audita/cambia aquí el guardado
interno de PasswordChangeForm ni la política de colisiones username/email. Esos
riesgos relacionados necesitan un paquete separado con pruebas de sincronización.

Los 66 archivos y blobs previamente preparados en el índice se conservan sin
alteraciones. AUD-01 queda **sin staging**: cambios en `views_perfil.py`,
`test_perfil.py` y este README, más el nuevo
`tools/fase3_1/test_perfil_persistencia_unit.py`. No se descarta ni restaura ningún
archivo. Referencias, HEAD, MERGE_HEAD, migraciones y estados/diffs observados de
otros worktrees se verifican al cierre. No hay commits, push ni merges adicionales.


## Cierre residual — Contraseña vigente y lectura desactualizada

### Checkpoint previo confirmado

El usuario confirmó **244/244 pruebas PostgreSQL/PostGIS aprobadas** tras AUD-01.
Sustituye el estado pendiente de las cinco regresiones ORM de la sección anterior;
no se repitió esa ejecución desde Codex. Las **nueve pruebas ORM de esta sección**
son nuevas y están pendientes. Las observaciones anteriores sobre validación
obsoleta y guardado de PasswordChangeForm quedan sustituidas por este resultado.

### Defecto confirmado por inspección y reproducción con dobles

En la edición de email, `PerfilForm.clean` llama a
`self.instance.check_password`. En cambio de contraseña, PasswordChangeForm recibe
el usuario de la solicitud. Antes del cambio ambos formularios bound usaban
`request.user`: si una segunda instancia ya había reemplazado su contraseña en
BD, el objeto anterior todavía podía aceptar la clave vieja y rechazar la vigente.
El guardado limitado de AUD-01 impedía restaurar el hash por edición de datos,
pero no impedía autorizar un cambio de email con esa comprobación obsoleta.

Se reprodujeron cuatro fallos antes de cambiar la vista ejecutando su función
real por AST y el `clean` real de email, con ORM/hash/PasswordChangeForm simulados.
La actualización se intercaló tras cargar el usuario y antes de validar. La clave
anterior permitía ambos cambios; la vigente era rechazada. Esto no se presenta
como una reproducción PostgreSQL ya ejecutada.

### Corrección implementada

Solo cambia la ruta POST de datos/contraseña de `views_perfil.py`:

1. Abrir `transaction.atomic()` antes de construir y validar el formulario bound.
2. Obtener nuevamente el usuario por la PK autenticada mediante
   `get_user_model().objects.select_for_update()`; no refrescar un objeto sin
   mantener un bloqueo hasta la escritura.
3. Rechazar la cuenta eliminada (404) o desactivada concurrentemente (403), sin
   recrearla, reactivarla ni tomar una identidad enviada por POST.
4. Construir PerfilForm o PasswordChangeForm con esa instancia fresca y validar
   dentro de la misma transacción. Mantener el bloqueo hasta terminar el guardado
   o salir por error; no usar skip_locked, reintentos ni bloqueos de tablas.
5. Conservar la lista de campos editados permitidos de AUD-01 y el guardado
   transaccional de PerfilUsuario. Para cambiar contraseña, obtener la instancia
   con `password.save(commit=False)` y guardar únicamente `password`.
6. Mantener `update_session_auth_hash` después del guardado exitoso de contraseña.
   La edición de datos/email no renueva una sesión con hash anterior. Mantener
   login/CSRF/métodos, campos y mensajes/redirects/errores de los formularios.

En PostgreSQL, una UPDATE de contraseña necesita bloquear la misma fila aunque
su escritor no use select_for_update. Si ya confirmó antes de nuestra lectura,
se valida la contraseña nueva. Si llega después de nuestro bloqueo, no puede
confirmar entre validación y escritura: espera hasta terminar la transacción.
No existe una ventana de liberar el bloqueo y luego guardar. Se usa el aislamiento
habitual READ COMMITTED de Django/PostgreSQL; otros aislamientos pueden abortar
por serialización y no se añade un reintento automático.

GET y guardados permanecen iguales, sin bloqueos nuevos. No se modifican
formularios, categorías, noticias, modelos, migraciones ni funciones sociales.
La sesión del usuario se conserva tras un cambio legítimo de contraseña. No se
vuelve a validar la contraseña para operaciones que nunca la exigían, como editar
solo el nombre: no se introduce ese cambio de contrato.

### Pruebas ORM agregadas: nueve

Se agregan dos clases al módulo ya seleccionado `core.test_perfil`; se conservan
las trece pruebas anteriores sin cambiar sus métodos:

- Siete casos deterministas: contraseña anterior rechazada y vigente aceptada
  al cambiar email y contraseña; sesión obsoleta no renovada al editar email;
  sesión conservada tras cambiar contraseña; rollback ante fallo posterior al
  guardar contraseña y ante fallo de PerfilUsuario; cuenta desactivada rechazada.
  El cambio previo usa otra instancia y ocurre después de cargar request.user.
- Dos `TransactionTestCase` exclusivos de PostgreSQL, cada uno ejercita los dos
  tipos de operación. Usan un worker con conexión independiente y commit real:
  uno confirma la rotación antes de validar y exige rechazo de la clave vieja;
  otro intenta una UPDATE mientras se valida, exige SQLSTATE 55P03 por bloqueo
  acotado y comprueba que el mismo writer sí confirma después de terminar el POST.

Las pruebas concurrentes no usan sleeps: esperan futures con timeout de cinco
segundos. La conexión del worker tiene lock_timeout de 250 ms y statement_timeout
local de tres segundos, cierra su conexión incluso si falla y solo usa la base de
pruebas. Esos límites son propios del test, no una nueva política de producción.
En otros motores los dos casos se omiten explícitamente; en el arnés PostgreSQL
se esperan ambos ejecutados, sin skips. No hay servicios ni conexiones externas.

### Comprobaciones locales ejecutadas

- Reproducción antes del cambio: **cuatro fallos esperados**, sin errores de setup.
- Unitarias de Fase 3.1: **14/14**, incluyendo las siete nuevas de credenciales y
  las siete previas. Ejecutan vista/clean reales con dependencias simuladas.
- Preparación del arnés (`test_validation.py`): **7/7**; Docker y Django simulados.
- Siete nuevas unitarias con Python `-O`: **7/7**.
- Compilación en memoria de **83 archivos Python**; sin pycache.
- Diff de trabajo sin errores. El índice conserva exactamente sus blobs iniciales
  y el CRLF heredado de landing.html, comprobado como antes con la opción
  `core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol` por comando.

El fixture del test unitario anterior de persistencia solo se adapta para proveer
el nuevo lookup del usuario; sus cinco métodos y aserciones se conservan.
Django no está disponible en el anfitrión: no se ejecutaron ORM, Django check,
Docker, migraciones, bases reales, Gemini, scraping ni HTTP; no se instalaron
paquetes. La ejecución real de concurrencia PostgreSQL continúa pendiente.

### Total y comando de validación descartable

El arnés no necesita modificaciones: `core.test_perfil` descubre ambas clases
nuevas. Bloques preparados: **64 + 54 + 14 + 24 + 47 + 50 = 253**.
Las 244 previas deben volver a pasar junto con las nueve nuevas, sin skips en
PostgreSQL. No se afirma 253 aprobadas hasta ejecutar el comando desde la terminal
normal, con imágenes locales y las guardas de aislamiento del arnés satisfechas:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-pr24-integracion/tools/fase1_1/run.py
```

Esperar **253/253** y Django System Check correcto. No se ejecutó desde Codex.

### Límites y estado Git

La garantía de serialización descrita requiere el bloqueo transaccional de la
base PostgreSQL; no se certifica la misma concurrencia en SQLite u otros motores
mediante los dobles unitarios. Una operación puede esperar por otra transacción
sobre el mismo usuario: no se define un timeout nuevo para producción. No se
protege frente a escritores externos que restauren deliberadamente un hash viejo,
ni se cambia la política de colisiones username/email o de edición simultánea de
un mismo campo. La persistencia de sesiones sigue a cargo del middleware existente.

HEAD permanece en `09ec007`, MERGE_HEAD en `7acc16a`. Índice original de 66 rutas
intacto; todos los cambios de AUD-01 y de este cierre siguen fuera de staging.
Se conserva el PLAN original y los estados/diffs observados de otros worktrees.
No hay commits, pushes, merges adicionales, resets ni descartes.


## Checkpoint de integración — Validación integral completada

El usuario confirmó la ejecución satisfactoria del árbol integrado y de todas
las correcciones de Fase 3.1 sobre PostgreSQL/PostGIS descartable:

- Fase 1.1: **64/64**.
- Fase 1.2: **54/54**.
- Fase 2.1: **14/14**.
- Fase 2.2: **24/24**.
- Fase 2.3: **47/47**.
- Integración PR #24 y Fase 3.1: **50/50**.
- Total: **253/253 pruebas aprobadas**.
- Migraciones **0007–0010 correctas** y Django System Check **sin incidencias**.

Esta validación posterior sustituye los estados pendientes de las secciones
históricas anteriores, incluidas las nueve regresiones de credenciales y sus dos
casos de concurrencia PostgreSQL. El historial de preparación y los riesgos
residuales se conservan: no se certifica el mismo bloqueo en otros motores, no se
impone un timeout de producción, no se cambia la política de colisiones entre
username/email ni se agrega control optimista de ediciones del mismo campo.
Siguen los límites territoriales, de identidad URL y de transporte ya documentados.

El checkpoint reúne PR #24 completo, resoluciones de integración, persistencia
limitada de AUD-01 y validación de credenciales sobre usuario fresco bloqueado.
La autorización comprende un único commit local que complete el merge pendiente,
con primer padre `09ec0072e3b480b81fc21a34accdaca3c53958b0` y segundo padre
`7acc16a7d0ef8fd5d10abe7be9a1594d48936981`. Los estados Git anteriores describen
la preparación; las correcciones se incorporan al índice para este checkpoint.

Durante el checkpoint solo se actualiza este documento, se revisan los archivos,
se comprueban espacios/sintaxis y se prepara el commit local. La validación
PostgreSQL fue informada por el usuario: no se repite desde Codex ni se ejecutan
Docker, servicios externos, scraping, Gemini o migraciones. No hay publicación
ni integración a las ramas originales.
