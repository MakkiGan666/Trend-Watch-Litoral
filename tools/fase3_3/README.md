# Fase 3.3 — configuración productiva separada

## Alcance

Resuelve la preparación de los P1 de servidor/contenedor y HTTPS/cookies.
No despliega, no proporciona infraestructura real ni implementa rate limiting o
los P2. Se mantienen noticias, autenticación, perfiles, categorías, JWT y permisos.

El checkpoint previo es `21ee7751ae73918b7dc5999f8df65a7e62dd67af`, con
**276/276 PostgreSQL/PostGIS y Django check correcto**, confirmados por el usuario.
No se atribuye ese resultado al árbol nuevo ni a una ejecución de producción.

## Archivos y desarrollo

- `app/mi_proyecto/production_config.py`: política pura, validación y valores seguros.
- `app/mi_proyecto/settings_production.py`: valida y luego reutiliza settings comunes.
- `app/mi_proyecto/settings.py`: únicamente omite `load_dotenv()` cuando el módulo
  seleccionado es exactamente `mi_proyecto.settings_production`. La producción
  recibe exclusivamente variables del proceso; no completa secretos desde .env local.
- `Dockerfile.production`, `requirements-production.txt`, `compose.production.yml`:
  alternativa independiente con Gunicorn, usuario 10001:10001 y raíz de solo lectura.
- `tools/fase3_3/test_production.py` y este documento: regresiones y operación pendiente.

No cambian Dockerfile, docker-compose.yml, .env.example, .dockerignore,
requirements.txt, arnés descartable ni migraciones. El entorno local sigue usando
`mi_proyecto.settings`, dotenv, SQLite cuando falta DB_HOST y PostgreSQL cuando existe.
No combinar los dos archivos Compose: el de producción debe seleccionarse solo,
mediante `-f compose.production.yml`, sin el Compose local como base u override.

## Variables obligatorias, sin valores reales en el repositorio

Provisionarlas mediante el sistema de secretos/entorno elegido, fuera del código y
fuera del contexto de construcción. No copiar .env.example como configuración productiva.
El Compose productivo no carga un env_file en el contenedor; su interpolación puede
leer un .env del directorio anfitrión, por lo que hay que usar un entorno/directorio
operativo controlado o un archivo externo seleccionado explícitamente. Revisar la
configuración renderizada de forma privada: puede contener secretos, no adjuntarla a logs.

| Variable | Condición |
| --- | --- |
| DJANGO_SETTINGS_MODULE | `mi_proyecto.settings_production`; fijado por imagen y Compose |
| DEBUG | `False` explícito; fijado por Compose y validado al importar |
| SECRET_KEY | Clave aleatoria propia, mínimo 50 caracteres y cinco distintos; rechaza prefijo inseguro y marcadores comunes. La validación estructural no demuestra entropía |
| ALLOWED_HOSTS | Lista explícita de hosts reales, sin comodines, sufijos abiertos, esquemas o puertos; IPv6 entre corchetes |
| DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD | PostgreSQL explícito, sin fallback SQLite; puerto 1–65535. Rol de mínimo privilegio provisionado externamente |
| DB_SSLMODE | Decisión explícita: `verify-full`, `verify-ca`, `require` o `disable` |
| DB_SSLROOTCERT | Ruta dentro del contenedor obligatoria para verify-full/verify-ca |
| MEDIA_ROOT | Ruta absoluta obligatoria; Compose fija `/var/lib/trendwatch/media` |
| MEDIA_HOST_PATH | Ruta absoluta existente en el anfitrión, exclusiva de este despliegue y preparada para UID/GID 10001 |

Generar SECRET_KEY con un generador criptográfico y guardarla en el gestor de
secretos. Mantenerla estable entre réplicas y reinicios; no regenerarla al arrancar.
La imagen solo genera una clave efímera no productiva en el proceso de construcción
para ejecutar collectstatic sin credenciales ni conexión PostgreSQL. No se guarda
como ENV de la imagen ni se usa al ejecutar Gunicorn.

Para PostgreSQL remoto, preferir **verify-full**, CA confiable y nombre del servidor
verificable. `require` cifra pero no garantiza por sí solo la identidad del servidor;
`disable` solo es aceptable si otro mecanismo o aislamiento verificado protege el
transporte. El Compose no inventa una CA ni la monta: provisionar un montaje de solo
lectura explícito, en una configuración operativa externa revisada, si se necesita.
El código no puede comprobar los privilegios del rol ni la red real.
No se inicia ni incluye un contenedor de base de datos, ni se reutilizan los volúmenes
locales. Preparar backups, restauración, política de acceso y migraciones controladas
por separado; el arranque web no ejecuta migraciones automáticamente.

## HTTPS, proxy y CSRF

En producción: redirección HTTPS, cookies de sesión/CSRF Secure y SameSite=Lax,
sesión HttpOnly y nosniff. Se mantiene el middleware CSRF. No se amplían CORS ni
CSRF_TRUSTED_ORIGINS: la interfaz y API se plantean en el mismo origen.
ALLOWED_HOSTS no sustituye los controles de CSRF ni garantiza que DNS/TLS existan.

La alternativa preparada supone un proxy TLS **en el anfitrión** que conecta a
`127.0.0.1:8001`. No exponer ese puerto al exterior. El contenedor escucha HTTP
solo como backend. Para un proxy remoto o en otro contenedor, diseñar una red
privada y reglas de acceso explícitas; no resolverlo abriendo el puerto a todos.

`TRUST_PROXY_HTTPS=false` por defecto: Django ignora X-Forwarded-Proto. Sin TLS
directo o confianza configurada, el HTTP backend redirige; un proxy TLS sin esta
adaptación produciría un bucle. No publicar hasta completar la configuración.
Usar `TRUST_PROXY_HTTPS=true` solo cuando:

1. Todo acceso al backend esté restringido al proxy/host de confianza.
2. El proxy descarte el X-Forwarded-Proto enviado por el cliente y escriba un
   único valor basado en la conexión TLS real (`https` solo cuando corresponda).
3. El proxy sanee las demás cabeceras Forwarded/X-Forwarded-* y conserve un Host
   real validado; no confiar en X-Forwarded-Host (permanece deshabilitado).
4. Se prueben redirecciones, cabeceras falsificadas y CSRF en un entorno aislado.

Solo entonces se activa `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')`.
No verifica la IP del proxy: la frontera de red y la sobrescritura son indispensables.
El proxy debe redirigir también el HTTP público a HTTPS y gestionar certificados
válidos y su renovación. No se incluyen certificados, claves privadas ni dominios.

HSTS empieza en **0**, sin subdominios y sin preload. Tras verificar HTTPS y la
renovación, definir SECURE_HSTS_SECONDS inicialmente corto y aumentarlo según
política; el validador acepta 0–31536000. HSTS persiste en navegadores: bajar el
valor no revierte inmediatamente una política ya recibida. No habilitar subdominios
ni preload sin auditar todos los dominios afectados. `check --deploy` puede avisar
por HSTS desactivado o por su alcance: documentar la decisión, no ocultar advertencias.

## Contenedor, static y media

Gunicorn es una dependencia **solo productiva** (`gunicorn==23.0.0`); se fija una
versión candidata, sin instalarla ni construir la imagen en esta tarea. Antes de
publicar hay que verificar disponibilidad, compatibilidad y avisos de seguridad de
esta versión y todas las dependencias/imágenes; no se afirma una auditoría de CVE.
La imagen Python sigue la línea existente, tampoco se inventa un digest verificado.

El contenedor usa UID/GID 10001, raíz read-only, capacidades eliminadas,
no-new-privileges y /tmp descartable limitado. El código no tiene bind mount de
escritura. Gunicorn usa dos workers y timeout de 60 segundos como valores iniciales,
pendientes de dimensionamiento; no son rate limiting ni una garantía de capacidad.
El timeout debe revisarse frente a operaciones síncronas legítimas antes de publicar.

`collectstatic` genera `/app/staticfiles` al construir. Gunicorn no sirve static ni
media: publicar los estáticos de esa misma imagen mediante proxy/CDN/servidor de
archivos externo, con artefactos correspondientes a cada versión. No montar todo
/app para extraer o servir archivos. Media se mantiene fuera de la imagen, en el
único bind mount de escritura explícito; el directorio debe existir, Compose no lo
crea. Provisionar permisos, espacio, backup y acceso del servidor de archivos sin
dar escritura al código ni al proxy. No usar los volúmenes de desarrollo.

Servir media sin ejecución, sin listado de directorio y con tipos/nosniff adecuados;
un origen separado es preferible y requiere adaptar la URL de media operativamente.
La propuesta base usa `/media/` bajo el proxy. No se amplía aquí la validación de
imágenes de admin ni la política de cargas; esos P2 siguen pendientes.

## Validación realizada y pendiente

Ejecutado en el anfitrión, sin Django instalado ni servicios:

- **17 pruebas nuevas**: variables ausentes, DEBUG, secretos débiles sin revelarlos,
  hosts adversariales, PostgreSQL/SSL/puertos, media, cookies/CSRF, proxy y HSTS;
  importación real de ambos settings con dependencias simuladas y sin lectura de .env;
  conservación de desarrollo y controles estáticos de contenedor.
- **31 regresiones previas**: Fase 3.2 10, Fase 3.1 14, preparación del arnés 7.
- Nueva suite repetida con Python `-O`.
- Sintaxis Python en memoria, YAML de producción parseado y controles de diff.

Estas pruebas no simulan un despliegue ni acreditan la configuración de una red real.
Quedan pendientes construcción/arranque de la imagen, integración real con Gunicorn,
Django `check --deploy`, TLS/proxy/CSRF, static/media, certificados, PostgreSQL SSL,
permisos del sistema y restauración. No se instalaron dependencias ni ejecutaron
Docker, HTTP, Gemini, scraping, migraciones o acceso a datos reales.

Con las variables reales provisionadas y usando un entorno aislado autorizado,
comprobar antes de publicar (no ejecutado aquí):

```sh
DJANGO_SETTINGS_MODULE=mi_proyecto.settings_production python -B app/manage.py check --deploy
```

Revisar cualquier advertencia, en especial la decisión HSTS. Comprobar además rechazo
de Host inválido, ausencia de DEBUG, no exposición de BD/backend, permisos del rol,
cookies Secure, cabeceras del proxy falsificadas y funcionamiento de media/static.

**El arnés no se modifica**: mantiene 276 pruebas PostgreSQL esperadas y Django check
con settings de pruebas/desarrollo, no con los requisitos productivos. Las 17 nuevas
son unitarias separadas; no se anuncian como 293 pruebas PostgreSQL. La repetición
sobre este árbol sigue pendiente. Comando para terminal normal, con autorización
específica para Docker y comprobando las guardas del propio arnés:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-pr24-integracion/tools/fase1_1/run.py
```

Sin staging ni commits. La Fase 3.3 prepara una alternativa productiva; no constituye
una autorización ni una certificación de publicación.

## Actualización de validación y cierre de Fase 3.3

El usuario confirmó que, **después de aplicar Fase 3.3**, el arnés PostgreSQL/PostGIS
aprobó **276/276 pruebas, sin fallos ni skips**, y Django System Check fue correcto.
Esta validación posterior sustituye el estado pendiente del árbol nuevo indicado
anteriormente; se conserva el historial de preparación. No se ejecuta nuevamente
PostgreSQL desde Codex durante el checkpoint. Las 17 unitarias nuevas permanecen
separadas del total de 276 pruebas PostgreSQL y se repiten localmente para el cierre.

La confirmación corresponde al arnés descartable y a los settings de pruebas;
**no valida el despliegue productivo**. Siguen pendientes construcción/arranque de
Dockerfile.production, compatibilidad real de Gunicorn y dependencias, proxy HTTPS,
frontera de confianza de cabeceras, certificados, static/media y `check --deploy`
con configuración productiva. También requieren comprobación operativa el SSL y
los privilegios PostgreSQL, permisos/backup de media y la política progresiva HSTS.
No se ocultan estas limitaciones ni se habilita publicación automática.

El cierre autorizado comprende únicamente las ocho rutas revisadas y exactamente
un commit local con padre `21ee7751ae73918b7dc5999f8df65a7e62dd67af`. Los estados
anteriores sin staging/commit describen la preparación histórica. No se ejecutan
Docker, servicios externos, bases reales ni despliegues, ni se modifican desarrollo,
autenticación, migraciones o el arnés durante este checkpoint; sin push ni merge.
