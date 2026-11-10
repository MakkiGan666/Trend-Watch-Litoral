# H5.8-A: lotes RSS reanudables

## Alcance y arquitectura

`ingestar_rss_lotes` administra trabajos explícitos de fichas RSS. El inicio
hace como máximo un GET mediante `leer_rss` (H2.1/H2.2), valida las mismas
barreras H5.6/H5.7 y persiste un snapshot acotado. Cada elemento del snapshot
contiene exclusivamente índice, estado, título, URL normalizada y fecha RSS;
no conserva XML, descripción, resumen, cuerpo, imagen ni clasificación.
`TrabajoLoteRSSMetadatos` almacena progreso y resumen; `RegistroDatos` conserva
un registro de ejecución. La migración 0025 es aditiva y no altera publicaciones
ni controles H5.6.

El snapshot contiene hasta el máximo del catálogo por fuente (actualmente 30).
El tamaño procesado por llamada es configurable entre 1 y 5 y no puede superar
el límite de fuente ya aprobado. Si el feed contiene más que el snapshot,
`entradas_fuera_snapshot` lo informa explícitamente. No se afirma que el medio
conserve esos elementos en consultas futuras ni se promete recuperación
histórica.

## Estados y checkpoints

- `PENDIENTE`: trabajo creado; aún no hay snapshot durable.
- `EN_PROGRESO`: un ejecutor posee token exclusivo.
- `PAUSADO`: hay entradas pendientes conservadas y puede reanudarse.
- `COMPLETADO`: no quedan entradas pendientes; el snapshot editorial se limpia
  y permanece el resumen de conteos/estados.
- `FALLIDO`: no se obtuvo snapshot utilizable; requiere inspección antes de
  crear otro trabajo.

Cada entrada conserva su estado en el JSON del trabajo. La publicación, su
alias y el checkpoint de esa entrada se guardan en una misma transacción; un
fallo de base deja el elemento pendiente y no revierte los checkpoints
anteriores. Errores/rechazos por entrada quedan identificados por índice y
código sanitizado, sin guardar el texto del error. La identidad y deduplicación
son las de H5.4 (fuente + URL normalizada); reanudar una entrada tras una
interrupción entre persistencia y confirmación no duplica la ficha.

Una restricción única permite un trabajo abierto por fuente. El token se asigna
antes de reservar frecuencia y hacer el GET, y se verifica al guardar el snapshot
y en cada checkpoint. Una pausa solicitada durante el GET se conserva y se
aplica antes de procesar la primera entrada. `--pausar` durante el procesamiento
se atiende entre elementos. Si el ejecutor muere abruptamente, el token queda
en `EN_PROGRESO`; sólo `--recuperar ... --confirmar-ejecutor-detenido` permite
retirarlo después de verificar que el proceso terminó. La recuperación invalida
el token anterior: un ejecutor que todavía reaparezca no puede escribir ni
avanzar el checkpoint. Si no hay snapshot durable, el trabajo termina `FALLIDO`
y el bloqueo H5.6 de la fuente sigue intacto para revisión manual.
Un trabajo sin snapshot no se vuelve a consultar automáticamente: se marca
fallido y cualquier nueva solicitud debe pasar de nuevo por el bloqueo H5.6.

Los bloqueos `EN_CURSO`, `ESPERA`, `REVISION_MANUAL`, el mínimo entre GET,
Retry-After, host/DNS/redirecciones, aprobación de equipo, revisión de acceso,
habilitación y confirmación de persistencia siguen siendo responsabilidad de
H5.6/H5.7. Consultar estado, pausar, recuperar o reanudar un snapshot no hace
GET. Reanudar sí vuelve a comprobar habilitación/revisión/aprobación operativa
y exige `--confirmar-persistencia`; no cambia la reserva ni el intervalo porque
no solicita la fuente. No se infiere permiso expreso del titular.

## Comandos

En todos los casos, el servicio sólo está disponible cuando la fuente concreta
está habilitada, revisada y aprobada por el equipo, con límite e intervalo
explícitos. Las listas continúan vacías por defecto.

```sh
# Un solo GET, snapshot y primer chunk. El máximo por invocación es 1–5.
python manage.py ingestar_rss_lotes --iniciar --fuente ID \
  --tamano-lote 5 --confirmar-persistencia

# Lectura de estado; no consulta el feed.
python manage.py ingestar_rss_lotes --estado ID_TRABAJO

# Solicitar pausa (se aplica después del elemento en curso).
python manage.py ingestar_rss_lotes --pausar ID_TRABAJO

# Procesar el chunk siguiente desde el snapshot, sin GET.
python manage.py ingestar_rss_lotes --reanudar ID_TRABAJO \
  --confirmar-persistencia

# Sólo tras verificar fuera de banda que el proceso original terminó.
python manage.py ingestar_rss_lotes --recuperar ID_TRABAJO \
  --confirmar-ejecutor-detenido
```

La salida JSON incluye el ID del trabajo, estado, cantidad total del feed,
entradas incluidas/fuera del snapshot, procesadas, nuevas, duplicadas,
rechazadas, errores y resultados por índice. No devuelve títulos ni URLs.
Un 429 utiliza la persistencia H5.6; un fallo al guardar el resultado mantiene
la fuente bloqueada. No se reintenta el GET automáticamente.

## Retención y límites

El snapshot queda en PostgreSQL mientras haya entradas por procesar, incluso
durante pausas; no se expira automáticamente porque eso perdería trabajo
confirmado. Al completar, se elimina el snapshot con títulos y URLs, conservando
el resultado agregado y los códigos/índices. Cada snapshot está limitado por
el tope de catálogo de 30 entradas y las longitudes de título/URL existentes.
Los trabajos y sus resúmenes se retienen como auditoría; la purga administrativa
de trabajos históricos queda fuera de H5.8-A y deberá diseñarse sin borrar
trabajos abiertos.

## Despliegue seguro

1. Crear respaldo verificable y aplicar la migración 0025 sólo en el entorno
   previsto.
2. Mantener deshabilitadas todas las fuentes hasta revisar acceso y uso de los
   metadatos y aprobar cada ID operativamente.
3. Configurar para una sola fuente límite e intervalo acordes con su política.
4. Iniciar un trabajo pequeño; revisar estado y conteos. Reanudar sólo el mismo
   ID mientras conserve snapshot y no hacer consultas diagnósticas al feed.
5. Ante `EN_PROGRESO`, verificar que el ejecutor terminó antes de recuperar.
   Ante control H5.6 pendiente, usar su resolución explícita; nunca editar la
   tabla manualmente ni repetir una petición para averiguar qué ocurrió.

H5.8-A añade lotes limitados, checkpoints y reanudación para el snapshot actual
del feed. No implementa crawling histórico, paginación de proveedores, colas
automáticas, workers en segundo plano ni una garantía sobre elementos que la
fuente ya no exponga.
