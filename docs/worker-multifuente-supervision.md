# Supervisión explícita del worker multifuente

El servicio Compose `worker-multifuente` ejecuta el comando Django existente
`automatizar_ingesta_multifuente --iniciar`, limitado a una fuente por ciclo y
con sondeo de 15 segundos. Pertenece al perfil opt-in `worker-multifuente`; un
`docker compose up` habitual no lo selecciona. El perfil `legacy-ingesta` es
independiente: habilitar el worker multifuente no inicia el recolector legacy de
El Territorio.

El worker no habilita fuentes. Para que una fuente sea considerada deben
coincidir el catálogo y las aprobaciones/configuración persistida existentes.
Sin una fuente habilitada, el proceso consulta el estado local, no solicita feeds
y permanece disponible para ciclos posteriores. El servicio no expone puertos,
no ejecuta Gemini y no procesa importaciones históricas.

## Validar selección sin iniciar contenedores

Usar el archivo Compose y el proyecto de la instalación que se pretende operar:

```sh
docker compose config --services
docker compose --profile worker-multifuente config --services
docker compose --profile legacy-ingesta config --services
```

La selección habitual no debe contener `worker-multifuente` ni `ingesta`. El
perfil `worker-multifuente` añade solamente el worker (además de sus
dependencias normales); el perfil `legacy-ingesta` solo habilita el servicio
legacy. `config` no inicia servicios.

## Consultar estado

```sh
docker compose --profile worker-multifuente ps -a worker-multifuente
docker compose --profile worker-multifuente logs --tail=100 worker-multifuente
docker compose exec web python manage.py automatizar_ingesta_multifuente --estado
```

La opción `--estado` consulta PostgreSQL y no contacta medios. Revisar `activo`,
heartbeat, programación de fuentes y trabajos abiertos. El comando no es una
prueba de lectura estricta de la base: no modifica publicaciones ni solicita
RSS.

## Inicio y detención

Antes del inicio, verificar el proyecto/base seleccionados, las fuentes y sus
gates. La orden explícita es:

```sh
docker compose --profile worker-multifuente up -d worker-multifuente
```

No agregar `--profile legacy-ingesta`. Para detener de manera intencional y
evitar que `restart: unless-stopped` revierta la parada:

```sh
docker compose --profile worker-multifuente stop -t 420 worker-multifuente
```

Compose envía SIGTERM al proceso. El comando marca su evento de parada y
termina el ciclo acotado actual antes de salir. `stop_grace_period` concede
siete minutos; si se agota el plazo y Docker fuerza SIGKILL, no iniciar otra
instancia manualmente hasta revisar el heartbeat y que expire el lease del
worker (cinco minutos) y los leases de trabajos (dos minutos). Usar `docker
compose stop`, no `automatizar_ingesta_multifuente --detener` desde otro proceso:
con la política de reinicio, una salida limpia solicitada por la bandera durable
puede hacer que el contenedor vuelva a arrancar.

## Reinicio del host o interrupción

`restart: unless-stopped` vuelve a iniciar un contenedor que estaba ejecutándose
cuando Docker se interrumpió. Una detención manual con `docker compose stop`
queda detenida tras el reboot. Si el proceso murió sin ejecutar su bloque de
cierre, los controles persistentes mantienen su lease hasta el vencimiento; el
worker reiniciado puede encontrar temporalmente el control activo y salir con
error. Docker reintenta con backoff; no iniciar un segundo worker para acelerar
la recuperación.

Al volver el host:

1. Confirmar que PostgreSQL del proyecto esperado está saludable.
2. Consultar `ps`, logs y `--estado`; no arrancar otra copia si el lease sigue
   vigente.
3. Dejar que venza el lease persistente (hasta cinco minutos para el worker) y
   observar que la instancia supervisada retome el control.
4. Comprobar que el trabajo abierto conserve su cursor/snapshot y que el nuevo
   fencing token impida confirmar desde un ejecutor obsoleto.
5. No resolver manualmente `REVISION_MANUAL`, HTTP 403, Retry-After excesivo ni
   estados H5.6 `EN_CURSO` sin revisar la causa. Usar el comando explícito de
   recuperación solo tras comprobar acceso y frecuencia.

Los snapshots, resultados y checkpoints viven en PostgreSQL, no en el
filesystem efímero del contenedor. Una interrupción no debe borrar progreso
confirmado; la deduplicación protege reintentos, y los controles H5.6 siguen
reservándose antes de cada GET. Una espera por robots o Retry-After no se reduce
al reiniciar.

## Logs y política de reinicio

El comando escribe salida JSON a stdout y errores a stderr; Compose conserva
hasta tres archivos de 10 MiB. `unless-stopped` permite recuperación automática
tras una caída del proceso o del host solo si el servicio había sido iniciado
explícitamente y no fue detenido por el operador. Si hay un worker externo activo,
el token persistente evita una segunda instancia; los reintentos de arranque
fallidos deben revisarse en logs, no corregirse borrando el control.

No se recomienda `docker compose up` general para probar ni para detener. El
servicio legacy de El Territorio tiene el perfil distinto `legacy-ingesta`; no
se inicia con el perfil del worker.
