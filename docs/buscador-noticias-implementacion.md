# Buscador: integración de columnas generadas STORED

Implementado tras aprobación, 2026-10-23. Rama `feat/buscador-noticias`, worktree
`/home/sebas/Escritorio/trendwatch-buscador`, base
`abfb6a31f91db029f29e5f6a677b49d24fb2d2b7`. Esta etapa fue sólo backend; la interfaz posterior se documenta en
[buscador-noticias-frontend.md](buscador-noticias-frontend.md).
Los experimentos y resultados anteriores se conservan como históricos.

## Cambio y contrato

`Publicacion.titulo_busqueda` y `contenido_busqueda` son GeneratedField STORED,
TextField, `db_persist=True`, no editables y `serialize=False`. La migración nueva
`0011_publicacion_texto_busqueda` depende de 0010; ninguna migración histórica cambió.
No se añaden índices, extensiones, dependencias ni triggers.

El motor calcula los derivados desde los originales al insertar y al actualizar.
No se sobrescribe save(), no se depende de señales de guardado ni de cada escritor.
Se verificaron save completo, update_fields, QuerySet.update, bulk_create y bulk_update.
Título y contenido originales conservan incluso su representación Unicode inicial.

La búsqueda usa contains parametrizado sobre ambos campos persistidos, AND entre
palabras y OR título/contenido por palabra. Se conserva todo el contrato público:
validación y códigos, parciales, NFC/NFD, mapa de vocales, diéresis, ñ distinta de n,
escape literal de %, _ y barra inversa, total exacto, fechas, PK de desempate,
página de 20, navegación, extractos y esquema JSON. No depende de categoría,
departamento ni IA; una prueba específica confirma coincidencias en título y en
contenido de publicaciones sin esas clasificaciones y con procesado_ia=False.

La observación del usuario de unos 3.755 enlaces potenciales de 2026 hace pertinente
el corpus de 5.000 filas. No se visitaron ni ingirieron esos enlaces, ni se modificó
la clasificación. No se asume que todos sean artículos distintos o estén almacenados.

## Normalización reproducible V1

`core/busqueda_texto_v1.py` es un módulo técnico versionado, sin importar modelos,
vistas o servicios de negocio. La migración importa TextoComparableV1 de ese módulo,
no de services/buscador.py. Expresión PostgreSQL:

```sql
translate(lower(CASE WHEN campo IS NFC NORMALIZED THEN campo
                     ELSE normalize(campo, NFC) END), mapa_v1, bases_v1)
```

Mapa congelado: `áàâäãåéèêëíìîïóòôöõúùûü` → `aaaaaaeeeeiiiiooooouuuu`.
La función Python V1 aplica NFC, lower y ese mismo mapa. SHA-256 del módulo de esta
etapa: `2c947e2cd7681d377d96c33ea13e1563ef2e022191989137db9c2bb9b663ab6d`.

**No cambiar la semántica de V1.** Una evolución requiere módulo/clase/función V2,
una migración nueva que recalcule las columnas y pruebas de compatibilidad. Se
conservan V1 y su registro SQLite para reproducir desde cero y revertir migraciones
históricas. El servicio reexporta los nombres previos como alias de V1 para conservar
compatibilidad de los helpers existentes. Una actualización de Unicode/collation
requiere revisar la equivalencia y el recálculo: no se trata como cambio transparente.

## SQLite real

AppConfig.ready conecta connection_created con dispatch_uid estable. Cada conexión
SQLite registra `tw_plegar_v1` como determinista, antes de compilar DDL, escribir o
buscar. La expresión no registra funciones de manera incidental al compilar consultas.

Se probó el backend Django SQLite real con archivo temporal, migración completa,
reconstrucción de tabla al agregar/quitar columnas STORED, noticias preexistentes,
reversión, conexión cerrada/reabierta y una conexión adicional independiente. La
función se consultó antes de compilar ninguna búsqueda, y luego se insertó y buscó.
No se presenta una prueba SQL aislada como sustituto de esas verificaciones.
Versiones verificadas: Django 6.1.2, Python 3.13.16, SQLite 3.46.1.

## Proyección y exposición

El gestor PublicacionManager difiere por defecto los dos derivados en las lecturas
de instancias. No agrega filtros: todas las publicaciones siguen siendo elegibles.
SQL usa esas columnas en WHERE sin traerlas en SELECT. Las vistas sólo acceden a
originales; no se introducen cargas diferidas adicionales. Si una herramienta necesita
inspeccionar derivados, debe solicitarlos explícitamente con values/values_list.

select_related no usa el gestor del modelo unido; por eso se difieren explícitamente
los derivados en guardados, edición de comentarios y Admin de modelos relacionados.
Los tests capturan las proyecciones y excluyen consultas adicionales por esos campos.
El buscador mantiene dos SELECT con coincidencias y uno sin resultados. El listado
de portada conserva su contrato y su límite; no se refactorizó su N+1 preexistente.

GeneratedField es no editable, y serialize=False también evita exponerlo o cargarlo
al usar el serializador general de Django. ModelForms, Admin y serializers de entrada
no ofrecen esos campos; la API rechaza entradas desconocidas. Respuestas públicas
mantienen sus claves. Los textos siguen siendo datos no confiables para el frontend.

## Archivos afectados

| Archivo | Cambio |
|---|---|
| app/core/busqueda_texto_v1.py | Expresión y función V1 congeladas; receptor de conexiones SQLite |
| app/core/models.py | Dos GeneratedField y gestor que omite derivados de las lecturas |
| app/core/migrations/0011_publicacion_texto_busqueda.py | Dos AddField; sin cambios históricos |
| app/core/apps.py | Registro por conexión, también durante migraciones |
| app/core/services/buscador.py | Filtro persistido y alias de normalización V1 |
| app/core/admin.py | Proyección de publicaciones unidas en Admin |
| app/core/views_perfil.py | Proyección en guardados |
| app/core/views_comentarios.py | Proyección al editar comentarios |
| app/core/test_buscador.py | Inclusión sin clasificación/IA y pruebas del diagnóstico por motor |
| app/core/test_texto_busqueda.py | Persistencia, migración reversible, conexiones, proyección y exposición |
| tools/buscador/validar_generadas.py y .sh | Reproducción aislada de pruebas y medición integrada |
| docs/buscador-noticias*.md y generadas-resultados.json | Contrato actualizado, operación y evidencia compacta |

La vista HTTP del buscador, sus rutas y el endpoint de listado no cambian en esta
etapa. Su ruta se incorpora con el resto del backend.

## Pruebas exactas y controles

| Motor | Batería dirigida | Resultado | Tiempo |
|---|---:|---|---:|
| PostgreSQL 17.5 | 99 pruebas | OK, 1 omitida (registro exclusivo SQLite) | 57.306 s |
| SQLite 3.46.1 | 99 pruebas | OK, 2 omitidas (bloqueo/commit exclusivo PostgreSQL) | 40.530 s |
| PostgreSQL, último ajuste de lecturas/comentarios | 17 pruebas | OK, 1 omitida (SQLite) | 3.752 s |
| SQLite, último ajuste de lecturas/comentarios | 17 pruebas | OK | 3.354 s |

Las 99 incluyen core.test_buscador, core.test_texto_busqueda, core.test_fechas,
core.test_publicacion_imagen, core.test_integracion_pr24, core.test_categorias_compat,
core.test_perfil, core.test_navegacion_admin, core.test_new_dashboard,
core.test_dashboard_localidades y core.test_localidades. Las 17 adicionales cubren
TextoBusquedaTests y core.test_comentarios después de ajustar la unión de comentarios.
La consulta del buscador no cambió tras su medición; no se repitió ésta.

En ambos motores se verificó instalación desde cero. El test de migración pasa a
0010, crea una noticia con Unicode descompuesto, aplica 0011, comprueba originales y
derivados, revierte a 0010 y verifica originales y ausencia de los dos campos; luego
restaura 0011. Migrate deja cero operaciones pendientes. Check Django sin incidencias.
Sintaxis Python/bash y git diff --check sin incidencias. No se ejecutó la suite completa.

**Diferencia preexistente separada:** antes de editar, makemigrations --check --dry-run
ya salía con código 1 por AlterField id de PublicacionTema, TemaTrend, UserAuditoria y
VotoPublicacion. Después de 0011 continúa exactamente con esas cuatro operaciones,
ninguna nueva ajena al alcance y ninguna sobre los campos integrados. El validador
compara los estados sin traducciones lazy, igual que makemigrations, y exige esa lista
exacta. No se creó la migración adicional sugerida ni se arreglaron esas diferencias.
Si CI exige salida cero global, ese desfase requiere una corrección separada.

## Rendimiento del endpoint integrado

Una sola ejecución de la batería final, después de pasar PostgreSQL y SQLite.
Se reutilizan 500/5.000 noticias sintéticas de 2.040 caracteres base y tres consultas.
Seis peticiones por caso, primera descartada, mediana de cinco; incluye cliente
Django, render JSON, fechas, URLs, extractos y parseo JSON. No es HTTP de red.
No se repitieron microensayos ni se ampliaron variantes. Se hizo una comparación
funcional adicional, sin cronometrarla, con la consulta A para cada caso; JSON idéntico.

| Filas | Consulta | Referencia A guardada ms | Integrado ms | Mejora | SELECT |
|---:|---|---:|---:|---:|---:|
| 500 | educacion provincial | 44.512 | 38.285 | 1.16× | 2 |
| 500 | singularis | 529.678 | 16.317 | 32.46× | 2 |
| 500 | inexistentezz | 270.522 | 10.662 | 25.37× | 1 |
| 5000 | educacion provincial | 183.671 | 44.403 | 4.14× | 2 |
| 5000 | singularis | 5270.625 | 81.118 | 64.98× | 2 |
| 5000 | inexistentezz | 2674.426 | 58.513 | 45.71× | 1 |

Referencia: docs/buscador-noticias-persistido-resultados.json, variante A/corpus base.
Coincidencias: frecuentes 500/5.000, raras 2/11 y vacías 0. Se verificó igualdad completa
de respuestas con A, no sólo el total. SELECT no trae las columnas derivadas y las
seis repeticiones mantienen el mismo número de consultas. Se verificó attgenerated=s
en ambas columnas. La transacción de medición dejó cero publicaciones al revertirse.

Entorno: PostgreSQL 17.5, UTF8, collation/ctype en_US.utf8, Django 6.1.2, Python 3.13.16,
Linux/Docker, i5-1035G1 y ocho CPU lógicas. Datos en tmpfs, imágenes locales existentes,
base y red propias sin puertos ni volúmenes persistentes. No hubo suites/mediciones
propias simultáneas. El host es compartido: no se garantiza carga ajena cero.

El volumen de 5.000 es relevante para los aproximadamente 3.755 enlaces previstos,
pero el corpus es sintético, repetitivo y cacheado. No mide p95 ni concurrencia,
HTTP real, tamaño físico de noticias reales ni comportamiento a escalas mayores.
La consulta conserva recorrido secuencial; no necesita otra investigación de índices
para comenzar el frontend al volumen ensayado.

## Despliegue, bloqueos, almacenamiento y reversión

1. Preparar backup y una ventana de despliegue. No servir código nuevo ni activar
   escritores que esperan los derivados antes de aplicar 0011.
2. Ejecutar migrate con la versión nueva (incluye módulo V1 y hook SQLite) antes de
   levantar los procesos que la sirven. En PostgreSQL, la aplicación vieja puede
   continuar usando originales con las columnas nuevas mientras se completa el cambio.
3. Verificar migración y búsqueda, luego servir la nueva versión. Los dos derivados
   se calculan para noticias existentes y se mantienen en cada escritura.

Agregar STORED exige procesar datos existentes y puede bloquear accesos por el DDL;
las dos operaciones pueden reescribir la tabla por separado. Planificar límites de
espera de locks y ventana acordes al entorno, no asumir bloqueo despreciable. No se
aplicó ninguna migración sobre una base real en esta etapa.

El experimento previo midió unos 3.038 ms para agregar ambos campos sobre 5.000 filas
(incluidas veinte largas). Derivados: 10.691.550 bytes lógicos adicionales, unos
10,20 MiB. El payload comprimido fue mucho menor por la repetición del corpus; no
se extrapola ese tamaño físico ni tiempo de DDL a producción. Se añade almacenamiento
y CPU de escritura a cambio de eliminar el costo repetido de normalizar al buscar.
Esas cifras son históricas del experimento; no se presenta una nueva medición de DDL.

**PostgreSQL:** para revertir, volver al código que consulta originales y usar el
paquete de migración actual (que conoce 0011) para ejecutar migrate core 0010. Una
versión vieja del código puede insertar/actualizar originales con los derivados aún
presentes: PostgreSQL los mantiene. Retirar las columnas no elimina título/contenido.

**SQLite:** una versión vieja sin hook no puede escribir sobre el esquema nuevo:
faltaría tw_plegar_v1. Para revertir, detener la aplicación, ejecutar migrate core
0010 usando el código actual con hook, y sólo después desplegar el código viejo.
No servir código nuevo después de quitar columnas. La reversión puede reconstruir
la tabla y requiere espacio temporal. Herramientas externas SQLite también necesitan
la UDF para escribir mientras existan esos campos.

No hay bloqueos nuevos para el frontend. Quedan los riesgos operativos descritos y el
check global de IDs preexistente. Puede comenzarse el frontend sobre el contrato ya
validado; cualquier despliegue debe respetar primero la migración.

## Reproducción y recursos

Con las imágenes locales de desarrollo disponibles, desde el worktree:

```bash
# Crea recursos propios, valida PostgreSQL y SQLite, mide una vez y limpia.
bash tools/buscador/validar_generadas.sh todo > /tmp/generadas.jsonl 2> /tmp/generadas.log

# Fases independientes usadas en esta etapa:
bash tools/buscador/validar_generadas.sh sqlite
bash tools/buscador/validar_generadas.sh postgresql
bash tools/buscador/validar_generadas.sh medir

# Sólo la comprobación adicional de lecturas y comentarios:
TW_GENERADAS_LECTURAS=1 bash tools/buscador/validar_generadas.sh sqlite
TW_GENERADAS_LECTURAS=1 bash tools/buscador/validar_generadas.sh postgresql
```

El launcher no acepta DSN ni recursos existentes. Crea etiqueta única, PostgreSQL
con network none y tmpfs, espera la base concreta por TCP (no el servidor temporal de
initdb), marca sólo su base, monta código read-only y elimina por ID tras verificar
su etiqueta. SQLite vive exclusivamente en archivos /tmp del contenedor. Dotenv está
deshabilitado; no se leen ni imprimen credenciales. No se llaman scraping, ingesta o IA.

Los contenedores propios se eliminaron; SQLite temporal desapareció con cada cliente.
El primer intento de arrancar la medición terminó durante initdb, antes de emitir
ningún dato de rendimiento; se corrigió la espera y la batería final se ejecutó una
sola vez. Los logs auxiliares permanecen en /tmp, y la evidencia útil compacta en
buscador-noticias-generadas-resultados.json. No se generó otro dump o patch voluminoso.
El prototipo experimental y los logs históricos no forman parte de la implementación
versionada; se conservan en el worktree. Para el código actual se usa este validador.
Los recursos y cambios ajenos se preservan.
