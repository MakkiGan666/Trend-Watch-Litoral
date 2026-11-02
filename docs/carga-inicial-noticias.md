# Carga inicial de noticias reales sin Gemini

Esta guía usa el scraper ya integrado de El Territorio y el Compose de desarrollo.
No hay ingesta automática al iniciar Docker. Las migraciones crean la estructura;
una base nueva no trae noticias ni fotografías precargadas.

## 1. Actualizar y configurar la instalación local

Usar una instalación propia. Antes de actualizar una instalación existente con
servicios activos, seguir el procedimiento de [despliegue sobre una base existente
del README](../README.md#despliegue-sobre-una-base-existente): el código se monta
desde el anfitrión y no debe actualizarse mientras web atiende tráfico.

Con los servicios detenidos y el árbol de trabajo limpio, actualizar desde la raíz
del clon. Si `main` está ocupada por otro worktree, usar ese worktree; no forzar el cambio:

```bash
git status --short
git switch main
git pull --ff-only
```

Si hay cambios locales o Git rechaza el avance, detenerse y resolverlo antes de
continuar; no usar reset ni borrar trabajo. Preparar la configuración propia según
[Configuración del README](../README.md#configuración-env). Copiar `.env.example`
a `.env` solo si todavía no existe; no reemplazar una configuración existente.

- Definir `SECRET_KEY` propia y `DB_PASSWORD` local; no compartirlas ni agregarlas a Git.
- Usar `DEBUG=True` solo para desarrollo, para servir estáticos y MEDIA localmente.
- Revisar `DB_NAME` y `DB_USER`; deben corresponder a la base local elegida.
- Compose fuerza `DB_HOST=db` y `DB_PORT=5432` dentro de web.
- Desde Python ejecutado en el anfitrión, el PostgreSQL del Compose se alcanza por
  `127.0.0.1:5433`, con `DB_HOST=127.0.0.1` y `DB_PORT=5433`.
- Para esta guía no se necesita `GEMINI_API_KEY`; puede quedar vacía. Todos los
  comandos de ingesta siguientes incluyen `--sin-ia`.

Los nombres fijos de contenedores y los puertos del Compose pueden colisionar con
otra instalación. Revisar antes de iniciar; no detener ni reutilizar recursos ajenos.
Un volumen PostgreSQL existente conserva sus credenciales originales: cambiar
`.env` no cambia su contraseña. No eliminar volúmenes para resolver un acceso fallido.

## 2. Verificar PostgreSQL y aplicar migraciones

Desde la raíz del repositorio:

```bash
docker compose build web
docker compose up -d db
docker compose ps
```

### Comprobar la identidad de PostgreSQL

Esperar a que `db` esté saludable. Realizar esta comprobación antes de cualquier
migración o ingesta, también al actualizar una instalación existente.

Desde la misma raíz y con los mismos parámetros de proyecto Compose usados al
iniciar la base, identificar el contenedor del servicio `db`:

```bash
docker compose ps db
docker compose ps -q db
```

El segundo comando debe devolver un único ID de contenedor. Si no devuelve ninguno
o devuelve más de uno, detenerse y revisar el proyecto; no elegir una base por su
nombre parecido. Copiar el ID y reemplazar `ID_DB` en el siguiente comando de lectura:

```bash
docker inspect --format '{{.Name}} proyecto={{index .Config.Labels "com.docker.compose.project"}} servicio={{index .Config.Labels "com.docker.compose.service"}}{{range $red, $datos := .NetworkSettings.Networks}} red={{$red}} IPv4={{$datos.IPAddress}} IPv6={{$datos.GlobalIPv6Address}}{{end}}' ID_DB
```

Comprobar que el proyecto corresponde a la instalación propia, que el servicio es
`db` y que el contenedor está activo en la salida de `compose ps`. Anotar las IPs
mostradas junto a sus redes. No inspeccionar variables de entorno completas: este
formato solo muestra identidad y direcciones, sin credenciales. Las IPs pueden
cambiar al recrear contenedores; no guardar ni asumir una IP fija.

Después comprobar el destino configurado por Django y la conexión efectiva:

```bash
docker compose run --rm --no-deps web python manage.py shell
```

Dentro del shell:

```python
from django.db import connection
print("Motor:", connection.vendor)
print("Destino:", {k: connection.settings_dict.get(k) for k in ("NAME", "HOST", "PORT")})
assert connection.vendor == "postgresql", "Detenerse: se esperaba PostgreSQL"
with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(), current_user, inet_server_addr(), inet_server_port()")
    print("Conexión efectiva:", cursor.fetchone())
```

Ingresar una línea vacía para terminar el bloque `with` y salir del shell con
`exit()`. El motor debe ser `postgresql`; la base y el usuario deben coincidir con
la configuración local esperada, y el puerto del servidor debe ser `5432`.
La IP devuelta por `inet_server_addr()` debe coincidir con una de las direcciones
del contenedor `db` recién inspeccionado, en una red compartida con web. Si usa IPv6,
comparar direcciones equivalentes, no solo su representación textual. El nombre de
la base, por sí solo, no identifica una instalación: contrastar también proyecto,
servicio, servidor y usuario. Si alguna comprobación no coincide, no continuar.

Al ejecutar Django en el anfitrión contra este PostgreSQL de Compose, abrir el
shell con `python app/manage.py shell` y usar el puerto publicado `5433` en la
configuración de conexión; el servidor seguirá informando su puerto interno
`5432`. Si la conexión entra por el puente/NAT del anfitrión, la IP de servidor
puede corresponder a otra interfaz del mismo contenedor: contrastarla con todas
las redes mostradas por `inspect`, sin asumir que el puerto publicado es el
puerto interno. Esta guía de IPs corresponde al PostgreSQL del Compose; para
otro PostgreSQL local, comprobar la identidad contra esa instancia autorizada.

### Aplicar migraciones en una instalación nueva

Solo después de comprobar la identidad, aplicar las migraciones oficiales, comprobarlas
y después iniciar web:

```bash
docker compose run --rm --no-deps web python manage.py migrate
docker compose run --rm --no-deps web python manage.py showmigrations core token_blacklist
docker compose run --rm --no-deps web python manage.py check
docker compose up -d web
```

No abrir web si fallan las migraciones o quedan pendientes. No ejecutar
`makemigrations` para instalar el proyecto. Sobre una base existente, revisar el
plan y los respaldos siguiendo el README antes de aplicar cambios de esquema.
Para administrar publicaciones y usuarios, seguir la configuración de roles del
[README](../README.md); no cargar la fixture histórica de roles. La portada y la
API pública permiten comprobar la ingesta sin crear una cuenta de aplicación.

## 3. Primera ingesta explícita

Con web iniciado y la base de destino verificada:

```bash
docker compose exec web python manage.py ejecutar_scraper --category policiales --limit 5 --sin-ia
```

El servidor necesita resolver y acceder por HTTPS a El Territorio. El comando
consulta el RSS y obtiene el contenido de hasta cinco artículos de sus primeros
cinco elementos. No ejecuta Gemini ni requiere su clave. No usar `run_pipeline`
para esta comprobación: ese comando incluye la etapa de IA.

El límite no garantiza cinco publicaciones nuevas: puede haber duplicados, menos
artículos disponibles o errores de extracción. Se crea un registro de ejecución y
se conservan las publicaciones que efectivamente se guardaron.

### Interpretar la salida antes de continuar

- **Éxito:** se completó la cobertura considerada por el servicio; revisar cuántas
  publicaciones fueron nuevas y cuántas se omitieron.
- **Duplicados:** las URLs/hashes ya existentes se omiten. No se sobrescriben
  noticias ni se actualizan sus imágenes o categorías al volver a ingerirlas.
- **PARCIAL:** puede indicar que el feed tenía más elementos que el límite, o que
  hubo errores individuales. El comando devuelve error también por cobertura
  incompleta; eso no significa que no haya guardado noticias.
- **Otros fallos:** revisar el mensaje, logs y los registros de ingesta antes de
  continuar. No repetir automáticamente ni aumentar el límite para ocultar el fallo.

Un lote no es una transacción global: cada noticia tiene su propio savepoint.
Un error posterior no deshace las publicaciones previamente guardadas. Antes de
repetir una ejecución parcial, verificar el estado de la base y su causa.

## 4. Ampliar por categorías de forma controlada

Ejecutar de a un comando y revisar su resultado antes de elegir el siguiente:

- Cultura: `docker compose exec web python manage.py ejecutar_scraper --category cultura --limit 3 --sin-ia`
- Deportes: `docker compose exec web python manage.py ejecutar_scraper --category deportes --limit 3 --sin-ia`
- Economía mediante Agro: `docker compose exec web python manage.py ejecutar_scraper --category agro --limit 3 --sin-ia`
- Categorías según contenido: `docker compose exec web python manage.py ejecutar_scraper --category misiones --limit 3 --sin-ia`

Estos cuatro comandos pueden agregar hasta 12 publicaciones, no necesariamente
12. Los feeds configurados son `misiones`, `tecnologia`, `policiales`, `cultura`,
`actualidad`, `deportes`, `agro`, `la-region` y `pais-y-mundo`. Su disponibilidad
puede variar. No todos los nombres de la portada son opciones de `--category`.

Policiales, Cultura, Tecnología, Deportes y Agro tienen correspondencia directa
con categorías del proyecto; Agro se asigna a Economía. En los feeds generales,
las reglas usan título y contenido. Sin evidencia suficiente, la noticia puede
quedar guardada **sin categoría asociada**, aunque tenga una fotografía válida.
Esas noticias no aparecen en los carruseles por categoría. No forzar etiquetas
para llenar la portada; se pueden revisar posteriormente desde el panel autorizado.

`--todas` recorre los feeds configurados e ignora `--category`, pero `--limit` se
aplica por feed a los primeros elementos, antes de deduplicar; no es un máximo
global ni una cantidad de noticias nuevas. Además, el primer `CommandError`,
incluido un parcial, detiene el recorrido. No garantiza visitar todos los feeds
ni poblar las 12 categorías. Por eso esta guía propone ejecuciones explícitas.

## 5. Comprobar la API, portada y fotografías

Abrir en el navegador:

- `http://localhost:8000/api/publicaciones/`: revisar `status`, `data`, `id`,
  `titulo`, `categorias_detalle` e `imagen_url` de cada noticia.
- `http://localhost:8000/api/publicaciones/<id>/`: reemplazar `<id>` por uno del
  listado y comprobar el contenido completo.
- `http://localhost:8000/`: comprobar tarjetas, categoría, carrusel y navegación
  al detalle; repetir en Firefox con tamaños de escritorio y móvil.

El listado devuelve hasta 150 publicaciones; `total` describe ese lote, no un
conteo global para bases mayores. Un arreglo vacío en `categorias_detalle` es
una ausencia de asociación, no un fallo de CSS.

El scraper guarda el enlace de la fotografía en `imagen_url`; no descarga el
archivo a MEDIA. El navegador solicita la imagen al medio o CDN, por lo que
necesita conectividad independiente de la del contenedor. Que la ingesta funcione
no garantiza que el navegador pueda descargar cada foto.

En Firefox, revisar Network y la consola: URL solicitada, respuesta, bloqueos CSP,
DNS/TLS o extensiones. Si la página carga pero la foto no, comprobar si la URL está
vacía, vencida, bloqueada o devuelve error. Una URL ausente puede ser válida para
una noticia cuya fuente no proporciona imagen; no inventar una fotografía.
No desactivar protecciones ni ampliar una CSP globalmente para resolver un caso.

Una imagen subida manualmente usa `imagen_archivo` y tiene prioridad sobre la URL.
Su archivo se almacena en `app/media/` en desarrollo y no viaja con Git ni con un
respaldo de PostgreSQL. Respaldar MEDIA por separado y revisar permisos de escritura.
La referencia local no garantiza que el archivo siga presente. Ver
[Imágenes de publicaciones](publicaciones-imagenes.md) para formatos, validaciones,
persistencia y servicio de archivos en producción.

No borrar publicaciones, reiniciar volúmenes ni cambiar el diseño para corregir
una categoría vacía o una fotografía no disponible. Separar problemas de datos,
conectividad y configuración antes de proponer cambios de código.
