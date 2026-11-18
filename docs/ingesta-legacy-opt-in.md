# Recolector legacy de El Territorio: ejecución explícita

El servicio Compose `ingesta` ejecuta `python manage.py ingestar_recientes`, que
consulta los feeds de El Territorio cada cinco minutos. Para que un `docker
compose up` ordinario no inicie recolección, el servicio pertenece al perfil
`legacy-ingesta`. El perfil no modifica el comando, la frecuencia, la fuente,
la base ni las credenciales del servicio. Tampoco activa el worker multifuente,
que sigue siendo un comando separado y apagado por defecto.

## Comprobar configuración sin iniciar servicios

Desde la raíz del repositorio y usando el `.env` del proyecto correcto:

```sh
docker compose config --services
docker compose --profile legacy-ingesta config --services
```

`config` valida la configuración y no inicia contenedores. Compose puede listar
servicios perfilados en la salida de configuración; el criterio de activación es
el perfil declarado en la definición efectiva. `ingesta` debe mostrar únicamente
el perfil `legacy-ingesta`. No se debe usar `docker compose up` general como
prueba.

## Una ejecución puntual autorizada

Confirmar antes la identidad del proyecto Compose, la base destino y que el uso
de la fuente esté aprobado. Con PostgreSQL ya disponible:

```sh
docker compose --profile legacy-ingesta run --rm --no-deps ingesta python manage.py ingestar_recientes --una-vez
```

Esto ejecuta una revisión y termina. No habilita ni inicia el worker
multifuente. La orden puede consultar varios RSS y persistir publicaciones; no
ejecutarla como diagnóstico de solo lectura.

## Ejecución periódica legacy autorizada

Solo si existe autorización operativa expresa y tras verificar proyecto y base:

```sh
docker compose --profile legacy-ingesta up -d ingesta
docker compose --profile legacy-ingesta ps ingesta
docker compose --profile legacy-ingesta stop ingesta
```

El servicio queda limitado al proyecto Compose indicado por el directorio y
archivo de configuración. No combinar esta operación con el worker
multifuente: son circuitos distintos. Si se usa un proyecto Compose implícito,
puede seleccionarse otra base/volumen.

En una máquina que opera con Compose de desarrollo, no exponer esta aplicación
como servicio público sin una configuración de despliegue y controles
específicos.
