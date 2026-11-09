# H5.4: persistencia acotada de metadatos RSS

## Alcance

`ingestar_rss_metadatos` ofrece un circuito separado del orquestador H4.1 y de
`ingestar_multifuente`. Lee una sola vez el feed seleccionado mediante H2.1 y
H2.2; no descarga HTML, no solicita imágenes y no ejecuta extracción H2.3.
El cambio no agrega modelos ni migraciones.

Cada ficha nueva guarda únicamente el nombre editorial del catálogo, título
normalizado del RSS, URL del enlace normalizada por H2.2, fecha RSS interpretable
(o `NULL` si no existe), `contenido=''` y `contenido_completo=False`. El ID
canónico se persiste como fuente del alias H3.1. No se guardan descripción,
contenido RSS, sección, imagen, localidad, categoría, etiquetas, sentimiento ni
resultado de IA. Los valores técnicos `hash_origen`, `fecha_captura`,
`id_registro` y `procesado_ia=False` sostienen identidad, auditoría y modelo.

## Activación independiente

H5.7 separa los controles antes mezclados bajo
`RSS_METADATOS_FUENTES_AUTORIZADAS`. Cada ejecución exige que el ID esté en
`RSS_METADATOS_FUENTES_HABILITADAS` (habilitación técnica),
`RSS_METADATOS_FUENTES_REVISADAS` (revisión de condiciones de acceso) y
`RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO` (decisión interna de usar
metadatos), además de límite/intervalo y `--confirmar-persistencia`. Todos
deniegan por defecto. La aprobación del equipo no afirma que el medio concedió
derechos ni convierte un RSS público en licencia.

`RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO`, también vacío por
defecto, registra por separado los IDs con evidencia comprobable de autorización
expresa del titular. Es documental, no un gate operativo; no se infiere desde la
aprobación interna y su ausencia no demuestra ni prohibición ni permiso. Si la
revisión determina que hace falta autorización del titular, la fuente no debe
recibir aprobación operativa hasta resolverlo. La confirmación por comando sólo
cubre una invocación; no cambia allowlists ni `FuenteRSS.habilitada`. Gemini es
independiente.

La cantidad visible y persistible se limita a cinco entradas por ejecución
(default: una) y al máximo por fuente configurado en
`RSS_METADATOS_LIMITES_POR_FUENTE`. El intervalo mínimo se configura por fuente
en `RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE`. El lector recibe el límite
antes de llamar a H2.1/H2.2; los rechazos posteriores al límite no se cuentan.
Los intentos se reservan en una tabla de control separada antes del GET y bajo
el mismo advisory lock por fuente, evitando solicitudes simultáneas, incluso
si aún no existe fila de control. El cooldown sobrevive reinicios.

## Uso futuro, sólo después de autorización por fuente

```sh
RSS_METADATOS_FUENTES_HABILITADAS=ID_AUTORIZADO \
RSS_METADATOS_FUENTES_REVISADAS=ID_AUTORIZADO \
RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=ID_AUTORIZADO \
RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO= \
RSS_METADATOS_LIMITES_POR_FUENTE='{"ID_AUTORIZADO":1}' \
RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE='{"ID_AUTORIZADO":1800}' \
python manage.py ingestar_rss_metadatos \
  --fuente ID_AUTORIZADO --limite 1 --confirmar-persistencia
```

El ejemplo documenta el contrato, no habilita ni autoriza ejecutar contra un
medio. Antes de configurar cada ID, el responsable debe documentar las
condiciones de acceso y decidir operativamente si el uso concreto de metadatos
es adecuado. La variable de permiso expreso sólo se llena con evidencia del
titular; vacía significa que el proyecto no registra una autorización expresa,
no que se haya demostrado permiso o prohibición. Los valores son ilustrativos
y todas las listas/mapas permanecen vacíos por defecto.

La salida JSON contiene estado, `fuente_id`, `registro_id`, `nuevas`,
`duplicadas`, `rechazadas`, `errores` y códigos de causa por índice. No incluye
títulos, URLs, resúmenes ni mensajes de excepción. Un fallo de consulta no crea
registro de auditoría ni publicación; el intento queda en el control de
frecuencia. Después de leer el feed, cada ficha usa una transacción
independiente. Una fila fallida se revierte sin descartar las anteriores.

## Identidad e idempotencia

La identidad es SHA-256 compatible con H3.1 sobre `['rss:v1', fuente_id,
URL_normalizada]`. El alias usa la restricción única existente
`(fuente, url_normalizada)`. H3.1 y H5.4 comparten el advisory transaction lock
por fuente, de modo que una carrera entre el modo de cuerpo completo y el modo
de metadatos se resuelve antes de insertar. PostgreSQL debe operar en
`Read Committed`.

Si una identidad ya pertenece a un artículo completo, la ficha se informa como
duplicada y sólo se puede añadir su alias técnico; título, fecha, cuerpo, imagen,
hash e indicadores del artículo no se sobrescriben. Si la identidad pertenece
a una ficha, el pipeline completo actual también la tratará como duplicada; no
hay promoción automática. H5.5/H5.6 deberán definir una transición explícita,
autorizada y transaccional para una futura promoción.

## Validaciones

- Persistencia sólo para un ID canónico H1.1 y las barreras H5.6/H5.4
  independientes, con confirmación puntual.
- Título no vacío, sin controles inválidos y sin truncamiento; URL HTTPS validada
  contra los hosts exactos de la fuente; fecha ausente admitida, fecha inválida
  rechazada.
- `Publicacion` valida el par de campos cuerpo/disponibilidad; el CHECK 0023
  conserva la garantía en PostgreSQL.
- No se crea reserva `ProcesamientoIAMultifuente`, sentimiento, categoría ni
  etiqueta. Las señales H5.3 también excluyen las fichas vacías.
- `RegistroDatos` audita cada ejecución autorizada que logró leer el feed. La
  identidad del feed no habilita automatización ni derechos de reutilización.

HTTP 429 no genera reintentos automáticos. La reserva persistente `EN_CURSO` se
confirma antes del GET y permanece bloqueada si el proceso se interrumpe o la
base no puede guardar el resultado. Un `Retry-After` válido se conserva junto
con el intervalo mínimo; si falta o es inválido, se aplica la pausa conservadora
configurada (24 horas por defecto). Valores superiores a 365 días pasan a
`REVISION_MANUAL`, sin acortarse. Ambos estados requieren revisión explícita;
`resolver_bloqueo_rss_metadatos --fuente ID --confirmar-revision-manual` no hace
una petición y añade otro intervalo completo antes de permitir un nuevo GET.
No se debe borrar ni editar el control directamente en la base.

Las pruebas usan RSS sintético en memoria y mocks del transporte. Deben correrse
con PostgreSQL/PostGIS efímero, almacenamiento temporal y red externa bloqueada;
nunca apuntarse al PostgreSQL habitual. Este cambio no autoriza lecturas reales,
no habilita los cinco medios y no resuelve sus condiciones particulares.
