# ETAPA 6 — Automatización multifuente

## Arquitectura

La automatización es un comando Django en primer plano; no hay señales de inicio,
cron, Celery ni una tarea que se active al arrancar la web. El planificador
reutiliza `orquestador_multifuente`, `descarga_segura`, la lectura RSS, la
persistencia y deduplicación existentes. Cada invocación del worker recorre como
máximo cinco fuentes vencidas y procesa como máximo un artículo por fuente en
ese ciclo. Un snapshot RSS conserva hasta 30 entradas y registra explícitamente
las que quedaron fuera de ese límite.

La migración `0027_automatizacion_ingesta_multifuente` agrega únicamente cuatro
tablas: programación por fuente, trabajos/checkpoints, caché de robots.txt y
control del worker. No cambia publicaciones, contenido ni registros históricos.
Los checkpoints incluyen estado por entrada; al completar se limpia el snapshot
editorial y quedan los contadores y resultados resumidos.

## Barreras y frecuencias

Programar una fuente no la habilita. Para procesarla deben coincidir la fuente
habilitada en el catálogo, la programación de base de datos con `habilitada`,
`acceso_revisado` y `aprobacion_operativa` verdaderos, y el vencimiento de su
próxima ejecución. Todos esos campos nuevos tienen valores seguros
deshabilitados. La configuración por fuente define el intervalo mínimo; el
intervalo H5.6 y `Crawl-delay`/`Request-rate` de robots.txt pueden aumentarlo.
La implementación no reduce ni espera sincrónicamente el intervalo: guarda la
fecha próxima y atiende otras fuentes.

Antes de cada GET (robots, feed, artículo y salto de redirección) se reserva y
finaliza el control durable H5.6. El robots.txt se guarda por fuente/host durante
12 horas. Un rechazo de robots no inicia la solicitud al recurso. Un robots
distinto de HTTP 200 —salvo 429, que respeta Retry-After— requiere revisión
manual; esto incluye 404 y es deliberadamente conservador. La caché se limita a
256 KiB. Los snapshots, incluidas URLs de continuación validadas, se limitan a
128 KiB.

- HTTP 403/401 o una política robots que deniega: el trabajo pasa a
  `REVISION_MANUAL`; no se reintenta automáticamente.
- HTTP 429: H5.6 persiste Retry-After; si falta, se usa el fallback configurado
  (24 horas por defecto). Esperas superiores a un año requieren revisión.
- Errores de red y HTTP 5xx: espera durable con backoff acotado; cada fuente
  falla independientemente.
- Si no se puede confirmar la persistencia del estado H5.6, queda vigente el
  bloqueo `EN_CURSO`/`REVISION_MANUAL` durable y no se sigue solicitando.
- Una redirección que requiere otro intervalo queda guardada como URL de
  continuación; se reanuda allí sin repetir el GET anterior. Las redirecciones
  se vuelven a validar contra los hosts admitidos.

El worker y cada trabajo tienen leases y fencing tokens. Un proceso obsoleto no
puede confirmar checkpoints. El trabajo vencido se recupera en otro ciclo sin
perder el snapshot. La operación `--reanudar-trabajo` exige confirmación
explícita y solo permite resolver trabajos en revisión manual después de
verificar las barreras y el estado H5.6.

## Comandos

Todos los comandos se ejecutan explícitamente con `manage.py` en el entorno
aislado que corresponda. Ejemplos de sintaxis, no una autorización para habilitar
una fuente:

```text
python manage.py automatizar_ingesta_multifuente --estado
python manage.py automatizar_ingesta_multifuente --configurar --fuente ID --intervalo-segundos 7200
python manage.py automatizar_ingesta_multifuente --habilitar --fuente ID --confirmar-revision-acceso --confirmar-aprobacion-operativa
python manage.py automatizar_ingesta_multifuente --una-vez --max-fuentes 2
python manage.py automatizar_ingesta_multifuente --iniciar --max-fuentes 2 --poll-segundos 15
python manage.py automatizar_ingesta_multifuente --detener
python manage.py automatizar_ingesta_multifuente --deshabilitar --fuente ID
python manage.py automatizar_ingesta_multifuente --reanudar-trabajo ID --confirmar-revision
```

`--iniciar` se mantiene en primer plano y acepta SIGINT/SIGTERM. También puede
recibir una parada durable mediante `--detener`; esta se atiende al terminar el
ciclo acotado actual. El sondeo debe estar entre 5 y 60 segundos. El estado
operativo se consulta con `--estado`, que no consulta medios.

La habilitación del catálogo actual requiere además un cambio de configuración
controlado de esa fuente; esta implementación no modifica el catálogo y ninguna
fuente queda activada por defecto. La frecuencia y aprobación deben definirse
individualmente tras revisar las condiciones vigentes del medio. No existe una
frecuencia universal recomendada por este cambio.

## Validación realizada

- 18 pruebas nuevas del planificador y comando con respuestas HTTP simuladas.
- 50 pruebas focalizadas existentes del orquestador multifuente.
- Resultado conjunto: 68 pruebas aprobadas en PostgreSQL temporal aislado, sin
  red externa y con Gemini deshabilitado.
- Las pruebas cubren gates por defecto, frecuencia/H5.6, robots allow/deny,
  snapshots/reanudación, redirecciones, errores 403/429/red, fencing, parada,
  concurrencia y aislamiento entre fuentes.

Las pruebas no autorizan ni ejecutan una activación real. La automatización
continúa apagada hasta una decisión operativa posterior.

## Límites pendientes

- La primera consulta a robots.txt consume una solicitud H5.6 y normalmente
  deja el feed para un ciclo futuro tras vencer el intervalo; el worker no
  duerme durante ese tiempo.
- Un `robots.txt` 404 se trata como revisión manual; hace falta una decisión
  operativa explícita para resolverlo, no un bypass automático.
- La parada solicitada no interrumpe a mitad de una solicitud o ciclo; espera
  el ciclo acotado actual.
- El sistema no implementa retención histórica ni recorrido de archivos RSS.
- No se activaron fuentes, no se consultaron feeds reales, no se ejecutó Gemini
  ni se modificó PostgreSQL habitual.
