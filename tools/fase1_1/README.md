> Actualización de preparación Fase 1.2 (20/10/2026): el usuario informa una
> ejecución previa de Fase 1.1 con PostgreSQL/PostGIS y 64 pruebas aprobadas.
> El texto siguiente conserva la revisión histórica. Para el plan ampliado,
> estado vigente y comando preparado, consultar
> [Validación Fase 1.2](../fase1_2/VALIDACION.md).
> Esta tarea sólo ejecutó pruebas sin Docker; no volvió a validar el runtime.

# Fase 1.1: arnés pendiente de nueva revisión de seguridad

**No ejecutar el arnés PostgreSQL hasta completar la nueva revisión.**
Esta versión se verificó únicamente mediante pruebas sin daemon ni servicios.
No se afirma que las imágenes o el Docker local hayan superado sus controles.

## Verificación permitida sin Docker

Desde la raíz del worktree:

```sh
python3 -B tools/fase1_1/check_ports.py
python3 -B -m unittest discover -s tools/fase1_1 -p 'test_*.py'
python3 -B -O tools/fase1_1/check_ports.py
python3 -B -O -m unittest discover -s tools/fase1_1 -p 'test_*.py'
```

Sólo requieren la biblioteca estándar. Las pruebas usan metadatos sintéticos y
clientes simulados; no acceden al socket, bases, servicios ni archivos `.env`.
Las comprobaciones críticas usan excepciones explícitas, incluso con `-O`.
El contrato de puertos verifica `web -> db:5432` y conserva
`127.0.0.1:5433:5432`. Depende deliberadamente del formato actual de Compose.

## Ejecución futura, después de la revisión

```sh
python3 -B tools/fase1_1/run.py
```

No necesita instalar paquetes en el anfitrión. Exige las imágenes **ya locales**
`postgis/postgis:17-3.5` y `trendwatch-litoral-web:latest`, dependencias compatibles
con `requirements.txt`, Docker Engine Linux 28+ y bridge `gateway_mode_ipv4=isolated`.
No construye ni descarga imágenes (`inspect` local y `--pull=never`).

El único daemon admitido es `unix:///var/run/docker.sock`, root-owned, sin symlink
final ni escritura para otros. El cliente es `/usr/bin/docker`, propiedad de root
sin escritura de grupo/otros. Todas las operaciones incluyen el mismo `--host`
y un `--config` temporal nuevo, sin contextos ni credenciales. No se consulta ni
modifica la configuración global del cliente. Los contextos personales, incluidos
los remotos, no participan; no hay opción para seleccionar otro contexto/daemon.
Se rechaza cualquier variable heredada `DOCKER_*`, `CONTAINER_*` o `SSH_*`.
El cliente recibe únicamente PATH y LANG constantes, sin HOME ni proxies.
Se detecta el reemplazo del inode del socket durante la ejecución.
No utilizar sudo, cambiar permisos del socket ni alterar el sandbox para ejecutarlo.

## Imágenes y contenedores

Antes de crear recursos se validan IDs, sistema Linux, entorno mediante lista
permitida, entrypoint, comando, usuario, directorio, volúmenes declarados,
puertos declarados y ausencia de hooks de imagen. Variables desconocidas,
incluidas credenciales o destinos libpq, provocan rechazo sin imprimir sus valores.
La lista es conservadora: una imagen legítima con metadatos distintos puede fallar.
No ampliar la lista automáticamente ante un rechazo.

Para PostgreSQL 17 se admiten exactamente el PATH base
`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` y ese mismo valor
con `:/usr/lib/postgresql/17/bin` al final. La variante base también permite
metadatos con el comando absoluto `/usr/lib/postgresql/17/bin/postgres`;
el entrypoint admite sólo su nombre conocido o `/usr/local/bin/docker-entrypoint.sh`.
El arnés usa siempre el PATH extendido propio tanto para inicialización como para
`pg_isready`, sin heredar el de la imagen o del anfitrión. Conserva `postgres` como
argumento del entrypoint para activar su inicialización normal. La política de PATH
de la aplicación web no cambia. Las rutas reales de la imagen local siguen
pendientes de verificación durante la ejecución controlada.

Los IDs de imagen quedan fijados. Ambos contenedores arrancan mediante
`/usr/bin/env -i` con variables explícitas. No se heredan variables de imagen en
los procesos de prueba. PostgreSQL usa UID/GID 999 y la aplicación 65534:65534;
ambos tienen raíz de sólo lectura, capabilities eliminadas, no-new-privileges,
IPC/cgroup privados, sin reinicio automático y logging Docker desactivado.
El código se recibe por un único bind de sólo lectura y propagación privada.
Antes de cada arranque se inspeccionan configuraciones efectivas de contenedores:
entorno, comandos, usuario, imagen, montajes, namespaces, puertos y red.
Un volumen anónimo o montaje inesperado bloquea el arranque.

La red es nueva, bridge local, interna, sin IPv6 y con gateway IPv4 `isolated`:
no asigna dirección al bridge para comunicación con el anfitrión. Se valida su
configuración, IPAM predeterminado y que no contenga miembros ajenos.
No publica puertos. El DNS se limita al loopback del contenedor, sin búsqueda de
dominios externos; la conexión PostgreSQL utiliza IP literal. No monta socket Docker.
El parche de sockets Python sólo es una defensa adicional, no la frontera de red.

PostgreSQL guarda PGDATA, sockets y temporales en tmpfs. La aplicación tiene tmpfs
para temporales, medios y uploads. No se reutilizan recursos existentes ni
volúmenes persistentes. Cada corrida imprime un UUID exclusivo y etiqueta sus
recursos. Sólo copia `.py` y `.html` a una carpeta temporal del worktree; excluye
ocultos, symlinks, medios, uploads y SQLite. No abre ni monta `.env` reales.
La carga de dotenv se desactiva antes de importar settings. `static` queda vacío.

## Identidad PostgreSQL y operaciones SQL

Credenciales públicas de prueba: usuario/base `tw_disposable`, contraseña
`disposable-only`; base Django `test_tw_disposable`. No se utilizan credenciales reales.

El runner exige un entorno exacto. Rechaza variables libpq y configuraciones
Django con alias, OPTIONS, TEST o campos adicionales. Introduce únicamente opciones
propias: IP/hostaddr del contenedor inspeccionado, passfile `/dev/null`, sin TLS
para esta red descartable, timeout y modo de sólo lectura inicial.
La validación de parámetros libpq ocurre **antes de abrir cada conexión**;
rechaza servicios, otras bases y parámetros adicionales.

Cada nueva conexión Django debe comprobar mediante SELECT su base, usuario,
dirección/puerto del servidor, PGDATA y un token UUID de esta ejecución, configurado
al arrancar el servidor. La dirección se consulta con `host(inet_server_addr())`:
PostgreSQL devuelve `inet::text` con máscara (`172.29.0.2/32`), mientras Docker
entrega la IP sin máscara (`172.29.0.2`). Se corrige la proyección SQL, sin aceptar
máscaras ni otras IP en la comparación estricta. Véase la
[documentación PostgreSQL 17](https://www.postgresql.org/docs/17/functions-net.html).
La corrección tiene cobertura unitaria, pero todavía no fue validada contra el
motor en una nueva ejecución. Hasta superar esa comprobación mantiene el modo de sólo
lectura. Sólo entonces habilita escrituras. Las conexiones administrativas del
runner de Django se redirigen exclusivamente a `tw_disposable`, evitando la base
convencional `postgres`; también atraviesan los mismos controles.

Después verifica PostGIS y ejecuta `check` y las suites
`LoginIdentificadorTestCase`, `RolesPermisosTestCase` y
`PublicacionDuplicadosTestCase`. Django crea, migra y destruye su base descartable.
No modifica archivos de migraciones ni ejecuta comandos de ingesta, scraping o IA.

## Fallos y limpieza

Se registra la intención antes de crear cada recurso. Si se pierde la respuesta de
creación, la limpieza busca candidatos con el UUID exacto y verifica ID completo,
nombre y etiqueta antes de borrar. Con un ID ya registrado, rechaza reemplazos.
No borra por coincidencias parciales ni por filtro solamente. No elimina una red
ocupada. Cada error se registra y se intenta limpiar el siguiente recurso propio.
Los errores de limpieza producen fallo y enumeran recursos pendientes.

Las llamadas Docker tienen timeout; las pruebas disponen de diez minutos.
Una interrupción normal entra en `finally`; SIGKILL, corte eléctrico, caída del
daemon o interrupciones repetidas pueden dejar recursos. Eso requiere revisión
manual, no adopción ni eliminación automática en otra ejecución. Para inventariar,
usando el **UUID exacto impreso** y el mismo daemon local:

```sh
/usr/bin/docker --host unix:///var/run/docker.sock ps -a --no-trunc --filter label=trendwatch.fase1_1=tw-f11-UUID
/usr/bin/docker --host unix:///var/run/docker.sock network ls --no-trunc --filter label=trendwatch.fase1_1=tw-f11-UUID
```

Antes de cualquier eliminación manual, inspeccionar IDs completos, nombres,
etiquetas y miembros de red. No ejecutar limpiezas globales. Revisar también la
carpeta temporal exacta `.tw-f11-*` de esa ejecución si el proceso fue forzado.

## Límites y estado de validación

Se confía en el kernel, daemon y cliente locales, en el código revisado y en la
procedencia de las imágenes. Inspeccionar metadatos no demuestra que sus capas no
contengan secretos ni código malicioso; deben tener procedencia conocida y no
incorporar credenciales. Este arnés no protege frente a un administrador hostil,
un daemon comprometido o cambios concurrentes deliberados de archivos/recursos.
No es una certificación de seguridad del runtime Docker.

Las pruebas negativas verifican rechazo de metadatos inseguros, configuración
libpq, identidad, controles con `-O`, daemon fijo y limpieza parcial o ajena.
No demuestran aún comportamiento real de redes, tmpfs, inicialización PostGIS ni
compatibilidad de Django con sus hooks. Esas verificaciones quedan pendientes
hasta aprobar esta revisión y autorizar una ejecución separada.

Historial: la versión anterior pudo listar imágenes, pero su ejecución quedó
bloqueada por el sandbox al inspeccionar la primera imagen, sin crear recursos.
En esta corrección no se ejecutó ningún comando Docker ni se accedió a bases reales.
