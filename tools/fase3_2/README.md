# Fase 3.2 — Colisiones de identidad

Base: `fad08fbc4e0ed44c083a402e1fe818b005d54849`.
Worktree: `/home/sebas/Escritorio/trendwatch-pr23-pr24-integracion`.
Rama: `fix/integracion-pr23-pr24-estabilizada`. Inicio limpio; AGENTS leído.
El checkpoint **253/253 PostgreSQL/PostGIS y Django check correcto** fue informado
por el usuario. No se repitió desde Codex. Este cambio no incluye migraciones,
cambios de modelo, staging ni commits.

## Contratos existentes y defectos confirmados

| Entrada | Contrato anterior | Resultado de la auditoría |
| --- | --- | --- |
| Login web/JWT | Recorta el identificador, conserva contraseña literal, username exacto y email `iexact`; rechaza más de un candidato, incluidos inactivos; verifica la PK devuelta por el backend. | Seguro ante ambigüedad conocida: no se cambia ni se elige una cuenta según su contraseña. |
| Registro web | Recorta username/email; exige ambos y contraseña; comprueba username/email duplicados por separado. UserManager normaliza username con NFKC al guardar. | Permitía que el username nuevo fuese el email ajeno y viceversa; comprobaba antes de NFKC. |
| Perfil | Solo email modificable como identidad; contraseña vigente y fila de usuario bloqueada desde Fase 3.1. | Rechazaba emails duplicados, pero aceptaba email igual al username ajeno. Bloquear una fila no coordina cuentas distintas que reclaman el mismo valor. |
| Django UserAdmin | Formularios/validaciones estándar de Django; permisos y grupos originales. | No validaba el cruce username/email entre cuentas; la edición tampoco garantiza unicidad de email. |
| `createsuperuser`, ORM/SQL directo | Escritores sin el protocolo web; username tiene unicidad exacta, email no. | No existe una restricción de BD que abarque ambos campos entre filas. Se documenta como límite, sin reemplazar managers ni instalar señales globales. |

Antes de modificar se reprodujeron **dos fallos** con el clean real del perfil y
la función real de registro, usando ORM simulado: ambos aceptaban un email que
coincidía con el username de otra cuenta inactiva, incluso con distinta caja.
No se presenta esa ejecución como una reproducción ORM/PostgreSQL.

La búsqueda de login sigue siendo deliberadamente asimétrica. Por ejemplo, si
hay un username histórico `Alias@example.com` y otro email `alias@example.com`,
`Alias@example.com` es ambiguo; `alias@example.com` solo coincide con el email.
Ese último identificador puede autenticar a su dueño con su contraseña, nunca
con la contraseña de la otra cuenta. Convertir username a `iexact` en login sería
un cambio de contrato y no se implementa.

## Corrección compatible

`core/services/identidad.py` centraliza la validación de valores nuevos:

- Username candidato contra emails ajenos, usando `iexact`.
- Email candidato contra emails y usernames ajenos, usando `iexact`.
- Excluir únicamente la PK de la propia cuenta, nunca cuentas inactivas.
- Permitir username y email iguales dentro de una cuenta.
- No convertir a minúsculas, recortar ni reescribir columnas históricas. Solo se
  comparan candidatos ya limpiados por las entradas existentes.

El registro conserva las comprobaciones y respuestas previas para duplicados del
mismo campo. Añade los cruces después de normalizar el username con el mismo NFKC
que UserManager ya aplicaba al almacenar. Conserva login automático, validadores
de contraseña/email y JSON `success/message/username`.

Perfil aplica la comprobación cruzada al cambiar el email, conserva confirmación
de contraseña y toda Fase 3.1: usuario fresco, bloqueo hasta terminar, allowlist de
campos editados y rollback con PerfilUsuario. Si el email permanece igual, no se
impide editar nombre/teléfono por un cruce histórico con username. Se conserva el
rechazo previo de emails duplicados entre cuentas, incluso si no fueron editados.

UserAdmin se especializa mediante subclase, manteniendo sus campos, permisos,
widgets, grupos, formularios de contraseña y rutas. Los formularios de alta/cambio
validan solo valores de identidad nuevos o diferentes de su valor anterior sin
considerar caja. Los cruces históricos que no se modifican no se reparan ni se
bloquean al editar otros campos. Las variaciones equivalentes de caja no crean una
clave lógica distinta. No se añade email al formulario de alta si Django no lo
incluye; su username sí se comprueba contra emails existentes.

Los identificadores históricos con espacios almacenados conservan la semántica
anterior: el login recorta la entrada, pero no los campos de BD. Un username con
espacios exteriores puede no ser utilizable; su email único sigue siendo una vía
válida. No se normalizan en masa ni se altera el catálogo de cuentas.

## Concurrencia: protocolo y límite explícito

Registro, POST de datos del perfil y POST de alta/edición de UserAdmin comparten
`serializar_identidad()`: transacción y un advisory lock transaccional PostgreSQL
con clave fija de dos enteros dentro de esta BD. Se adquiere **antes de validar**
y se conserva hasta terminar el guardado/commit o rollback. El perfil adquiere
primero identidad y después su fila; no se adquieren las mismas cerraduras en el
orden inverso entre estas rutas. El cambio de contraseña del perfil sigue tomando
solo su fila y escribiendo solo password.

El POST de contraseña de UserAdmin también se coordina antes de delegar su
lectura/formulario al padre. Así no dependemos de si la versión instalada de su
formulario guarda User completo. No se modifica ese flujo de contraseña ni se
inventa una comprobación de contraseña anterior para el administrador.

Con el READ COMMITTED habitual de Django/PostgreSQL, el segundo escritor web
espera y valida contra lo que confirmó el primero. Se evita que dos comprobaciones
separadas permitan luego dos altas/ediciones incompatibles. No se usa una señal
post_save que detecte el problema después de persistir ni un bloqueo de tabla.
El bloqueo es deliberadamente grueso: serializa estas escrituras de identidad
entre usuarios y puede esperar; no se establece timeout nuevo de producción ni
se promete el mismo aislamiento con otros niveles transaccionales.

**Esto no constituye una restricción de unicidad de base de datos.** Un script,
`createsuperuser`, un uso independiente de ModelForm o un writer ORM/SQL que no
adquiera el mismo bloqueo puede crear identidades ambiguas, incluso mientras una
ruta protegida trabaja. Una prueba PostgreSQL documenta ese bypass con dos filas
distintas bloqueadas y validaciones que ambas ven libres; ambos writers directos
confirman, y luego el login rechaza la ambigüedad. No se afirma protección contra
escritores que no participan. En SQLite se conserva atomic, sin simular advisory
locks ni certificar la misma concurrencia.

No hace falta una migración para coordinar estas rutas. Si el requisito futuro
es impedir la ambigüedad desde **cualquier escritor**, sí hace falta una decisión
de esquema: por ejemplo un registro único de identificadores que represente
username exacto, aliases de email y su equivalencia para cruces, con tratamiento
explícito de cuentas históricas. Una simple UNIQUE(email) no impide el cruce entre
columnas; tampoco permite resolver historial ambiguo sin una política de producto.
Alternativamente, un trigger necesita diseñarse con serialización/unicidad real,
no solo una consulta EXISTS. Esa propuesta queda pendiente: no se crea ninguna
migración, no se cambia AUTH_USER_MODEL ni se modifica información histórica.

## Archivos

- `app/core/services/identidad.py`: comprobación compartida y protocolo transaccional.
- `app/core/views.py`: registro normalizado/validado dentro del protocolo.
- `app/core/forms_perfil.py`, `app/core/views_perfil.py`: validación cruzada y
  orden de bloqueos compatible con Fase 3.1.
- `app/core/admin.py`: formularios/subclase de UserAdmin; los demás admins quedan intactos.
- `app/core/test_identidad.py`: **16 regresiones ORM**, incluidas tres PostgreSQL
  de concurrencia; ningún acceso externo.
- `tools/fase3_2/test_identidad_unit.py`: **10 unitarias** con dobles de ORM/locks;
  ejecutan funciones reales, clean y delegación del admin.
- `tools/fase3_1/test_perfil_credenciales_unit.py` y
  `test_perfil_persistencia_unit.py`: solo adaptar dependencias simuladas al contexto
  de identidad; se conservan sus métodos de prueba y aserciones.
- `tools/fase1_1/validation.py` y `test_validation.py`: séptimo bloque aditivo,
  sin tocar controles de daemon, red, imágenes, conexiones o medios temporales.
- Este README: hallazgos, alcance y limitaciones.

## Pruebas y resultados

Ejecutado sin Django, base de datos, Docker ni servicios:

- Reproducción previa: **dos fallos esperados** (perfil/registro).
- Nuevas unitarias Fase 3.2: **10/10**, también **10/10 con `-O`**.
- Unitarias Fase 3.1: **14/14**.
- Preparación del arnés `test_validation.py`: **7/7**.
- Total local: **31 pruebas unitarias distintas**, más la repetición con `-O`.
- Compilación en memoria de **86 archivos Python** y `git diff --check` correctos.

Django no está disponible en el anfitrión. No se ejecutaron Django check ni ORM;
no se instalaron dependencias, ejecutaron Docker, migraciones, Gemini, scraping,
HTTP ni bases reales. Las **253 aprobadas previas** no equivalen a una ejecución
sobre el árbol nuevo.

Las 16 nuevas ORM cubren entradas cruzadas en ambas direcciones, case/espacios,
cuentas inactivas, NFKC, alias propios válidos, ambigüedad histórica en web/JWT,
PK correcta en login que solo coincide por email, historial intacto al editar
otros datos, formularios/admin POST/permisos/CSRF y contraseña administrativa.
Las tres TransactionTestCase prueban dos registros cruzados simultáneos, perfil
contra registro y writers ORM que omiten el protocolo. Usan conexiones separadas,
barreras/futures con timeout y límites SQL propios del test. No usan sleeps;
cierran las conexiones aun ante fallos. Requieren PostgreSQL, sin skips en el arnés.

Se agregan también al bloque las **siete pruebas existentes** de
`core.test_auth_views`, para volver a verificar el contrato de alta/modal/CSRF.
Se mantienen sin cambios las 253 etiquetas/pruebas anteriores. Nuevo bloque:
**16 nuevas + 7 existentes = 23**. Nuevo total esperado:
**64 + 54 + 14 + 24 + 47 + 50 + 23 = 276**.

## Validación PostgreSQL pendiente

El arnés mantiene sus guardas: imágenes ya locales, red aislada, recursos propios,
PGDATA/medios descartables y comprobación de identidad antes de escribir. Solo se
amplía el plan de pruebas. Comando único para terminal normal con la autorización
de ejecución correspondiente, sin sudo ni descargas:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-pr24-integracion/tools/fase1_1/run.py
```

Esperar Django check correcto y bloques **64, 54, 14, 24, 47, 50 y 23**:
**276/276**, sin skips inesperados. Es preparación, no un resultado ejecutado.

HEAD/rama/referencias e índice permanecen en el checkpoint inicial; todos los
cambios siguen sin staging. Se comprueban hashes de migraciones, resoluciones y
archivos fuera de alcance, así como los estados/diffs observados de otros worktrees
al cerrar. Sin commits, pushes, merges ni alteraciones de identidades existentes.


## Validación integral completada y checkpoint local

El usuario confirmó la ejecución sobre PostgreSQL/PostGIS descartable:

- Bloques anteriores: **64 + 54 + 14 + 24 + 47 + 50 = 253 pruebas aprobadas**.
- Bloque de Fase 3.2: **23/23** (16 nuevas y siete existentes de autenticación).
- Total: **276/276 pruebas aprobadas, sin fallos ni skips**.
- Django System Check: **correcto, sin incidencias**.

Esta confirmación posterior sustituye el estado pendiente de la sección anterior;
se conserva el historial de preparación. No es una nueva ejecución desde Codex.
Durante el checkpoint solo se actualiza esta documentación y se realizan revisión,
pruebas unitarias con mocks, controles de sintaxis/espacios, staging explícito y el
único commit local autorizado. No se ejecutan Docker, migraciones, bases reales,
Gemini, scraping ni solicitudes externas.

Siguen vigentes las limitaciones documentadas: el protocolo protege registro,
perfil y UserAdmin que participan en él, bajo PostgreSQL/READ COMMITTED; no es una
restricción universal de base de datos. Escrituras ORM/SQL directas,
`createsuperuser` o formularios usados independientemente pueden omitirlo. No se
certifica idéntica concurrencia en SQLite ni otros niveles de aislamiento. El
bloqueo compartido puede esperar por otros escritores y no tiene un timeout nuevo
de producción. Las identidades ambiguas históricas no se reparan automáticamente;
el login conserva su rechazo seguro.

El siguiente paquete recomendado es evaluar una garantía de identidad para todos
los escritores y una política explícita para el historial ambiguo, antes de
proponer esquema/migración. Este checkpoint no implementa esa ampliación ni altera
modelos, migraciones, JWT, roles o permisos.

La revisión inicial de este checkpoint encontró las doce rutas de Fase 3.2 ya en
staging y ningún archivo fuera del índice. Se conserva ese contenido validado y
se incorpora únicamente esta actualización adicional del README. La autorización
comprende exactamente un commit local en `fix/integracion-pr23-pr24-estabilizada`,
con padre `fad08fbc4e0ed44c083a402e1fe818b005d54849`; sin push ni cambios de otras
ramas o worktrees. Los estados Git anteriores describen la preparación histórica.
