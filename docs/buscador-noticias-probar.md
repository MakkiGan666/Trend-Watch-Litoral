# Probar el buscador desde un checkout limpio

Rama `feat/buscador-noticias`, PR en borrador. Falta auditoría final; no es una
indicación de desplegar sobre datos reales. No ejecutar ingesta, scraping ni IA
para revisar el buscador. La prueba sintética es la opción recomendada.

```bash
git clone --branch feat/buscador-noticias --single-branch https://github.com/MakkiGan666/Trend-Watch-Litoral.git
cd Trend-Watch-Litoral
```

## A. Previsualización sintética y desechable

Requisitos: Linux con Docker Engine accesible, Bash y Python 3 en el anfitrión.
Docker Desktop/Windows/otras arquitecturas no se verificaron. No hacen falta `.env`,
PostgreSQL local, Gemini ni paquetes Python del proyecto en el anfitrión.
La primera construcción requiere Internet para obtener la imagen base y requirements.

```bash
docker build -t trendwatch-litoral-web:latest .
bash tools/buscador/previsualizar_busqueda.sh iniciar
```

La etiqueta de imagen es la que usan los scripts; se construye íntegramente con
`Dockerfile` y `requirements.txt` de esta rama. No iniciar Compose para esta opción.
El comando devuelve un JSON con `url` y `manifiesto`: guardar ambos, esperar unos
segundos a que termine migrate y abrir **la URL generada en el propio equipo**.
Si aún no responde, esperar y reintentar. No reutilizar puertos/manifiestos ajenos.

Hay 43 noticias sintéticas (tres páginas), imágenes locales opcionales, varias fechas
y ninguna clasificación/IA. `educacion` tiene resultados; `provincia` encuentra sólo
contenido en varios casos; `inexistentezz` no tiene coincidencias. Para probar la
cuenta sintética, abrir `/preview/sesion/` dentro del mismo origen generado; no pide
contraseña y sólo existe en el servidor de prueba. Para volver a visitante, cerrar sesión.
La previsualización sólo se publica en loopback: cada compañero debe crear la suya.

La base SQLite con 0011 aplicada, el secreto aleatorio y los datos viven en tmpfs.
El código se monta read-only, se ignora dotenv y se bloquean conexiones salientes de
la aplicación. No se tocan Compose, bases, medios ni volúmenes existentes.

Al terminar, sustituir el marcador por el manifiesto devuelto al iniciar:

```bash
bash tools/buscador/previsualizar_busqueda.sh detener RUTA_DEL_MANIFIESTO
```

Esto elimina sólo el contenedor/red etiquetados por ese manifiesto y sus datos
sintéticos. No borrar recursos por nombre genérico.

### Comprobaciones automatizadas opcionales

Usan la misma imagen construida arriba; PostgreSQL descarga `postgis/postgis:17-3.5`
si no está disponible. Crean y eliminan recursos propios, sin DSN externos:

```bash
TW_BUSCADOR_FRONTEND=1 bash tools/buscador/validar_generadas.sh sqlite
TW_BUSCADOR_FRONTEND=1 bash tools/buscador/validar_generadas.sh postgresql
```

Para las capturas: Firefox con BiDi (validado en 145.0.1) y Node 20 con WebSocket nativo;
no se instala Playwright ni paquetes npm. Sustituir `ORIGEN_GENERADO` por el origen
sin ruta de la URL devuelta y elegir carpeta local para evidencias:

```bash
python3 tools/buscador/revisar_frontend.py ORIGEN_GENERADO capturas-locales
```

Los scripts `previsualizar_busqueda.{sh,py}`, `revisar_frontend.{py,mjs}`,
`validar_generadas.{sh,py}` y el JSON de referencia necesario están versionados.

## B. Instalación normal con PostgreSQL/PostGIS

Esta opción usa el Compose habitual y datos persistentes. Verificar antes que sus
nombres fijos de contenedores y puertos no colisionen con otro entorno. No confundirla
con A. Si ya hay base/configuración, conservarlas: **no reemplazar `.env` ni crear otra
clave o volumen por accidente**. Nadie aplicó estos pasos a una base real al preparar el PR.

En una instalación nueva, copiar `.env.example` a `.env` y completar en privado
`SECRET_KEY`, `DB_PASSWORD`, `DB_NAME`, `DB_USER` y hosts adecuados. No publicar `.env`.
No hacen falta claves Gemini para la búsqueda. PostgreSQL 17/PostGIS 3.5 es la imagen
Compose validada; los paquetes Django se construyen desde el Dockerfile de la rama.

**0011 debe aplicarse antes de iniciar procesos web con el código nuevo.**
No usar `docker compose up --build` como primer paso, pues iniciaría web antes de migrar.
Para una instalación nueva sin datos:

```bash
docker compose build web
docker compose up -d db
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose run --rm --no-deps web python manage.py showmigrations core
docker compose run --rm --no-deps web python manage.py check
docker compose up -d web
```

Comprobar `[X] 0011_publicacion_texto_busqueda` antes del último paso. Si migrate falla,
no iniciar web. La instalación normal no carga noticias sintéticas: con base vacía la
búsqueda muestra cero resultados; usar A para una revisión con noticias sin ingesta.

### Si se decide usar una base existente

Procedimiento a cargo de su responsable; **no es necesario para probar A**:

1. Identificar base/volumen exactos y versión PostgreSQL. Detener web y todos los demás
   escritores (tareas/ingestas) durante la ventana acordada. Guardar versión de código
   y configuración privada para rollback. No bajar volúmenes.
2. Crear un respaldo completo fuera del repositorio, con permisos privados y espacio
   suficiente. Ejemplo para el servicio `db` del Compose existente ya levantado:

   ```bash
   umask 077
   mkdir -p "$HOME/trendwatch-respaldos"
   respaldo="$HOME/trendwatch-respaldos/antes-buscador-$(date +%Y%m%d-%H%M%S).dump"
   docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$respaldo"
   test -s "$respaldo"
   docker compose exec -T db pg_restore --list < "$respaldo"
   ```

   Verificar salida exitosa; listar el dump no prueba una restauración. Restaurarlo
   antes en **otra base desechable** y comprobar noticias/relaciones. Respaldar medios
   y configuración por separado; no versionar dump, credenciales ni medios.
3. Con respaldo probado y escritores detenidos, construir web, ejecutar migrate,
   showmigrations y check como arriba, sin iniciar web todavía. Añadir STORED recorre
   las noticias y puede bloquear/reescribir la tabla; prever espacio y ventana de DDL.
   Los dos campos se calculan sobre los originales existentes y luego se mantienen
   automáticamente en todas las escrituras.
4. Verificar búsqueda y preservación de datos; sólo entonces iniciar web y restablecer
   los escritores. Si falla, mantener el servicio detenido y seguir el plan de rollback
   del responsable; no improvisar `reset`, borrado de volúmenes o restauración encima.

Reversión PostgreSQL: el código previo que consulta originales funciona con las columnas
presentes; si hace falta retirarlas, usar el paquete actual de migraciones para volver
`core` a 0010 durante una ventana. Esto conserva título/contenido. **SQLite es distinto:**
revertir con el código/hook actual antes de usar código viejo sin la UDF. Más detalles,
costo de espacio y riesgos en [implementación](buscador-noticias-implementacion.md).

## Lista manual breve

- Visitante y cuenta: lupa abre, enfoca campo; segunda pulsación/Escape cierran y
  devuelven foco; conserva lo escrito. Tab, Enter y Espacio nativos. Sin JS, enlace
  y formulario GET siguen funcionando.
- `educación`/`EDUCACION`, `niño`/`nino` (distintos), varias palabras repartidas entre
  título y contenido, y parciales como `educ`. Los términos deben aparecer todos.
- Sólo contenido (`provincia`), consulta sin resultados (`inexistentezz`), consulta
  inválida (`x`), imagen ausente/rota y título/extracto resaltados legibles.
- Pasar a página 2 y volver: consulta conservada, 20 por página, detalle correcto.
- Móvil estrecho: barra completa, sin desbordes, menú y cuenta sin conflictos.

Pendientes explícitos: auditoría final, teclado nativo real, lector de pantalla y
móvil físico. La automatización de activación/envío usó `click()` por limitación de
BiDi; no acredita Enter/Espacio nativos. El modal de cuenta conserva una limitación
previa de foco inicial documentada. No sumar baterías históricas como casos distintos:
ver [resultados exactos](buscador-noticias-frontend.md).
