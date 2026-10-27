#!/usr/bin/env bash
# Exclusivamente PostgreSQL propio sin puertos/volúmenes o SQLite tmpfs.
set -euo pipefail
raiz=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
fase=${1:-postgresql}
case "$fase" in postgresql|sqlite|medir) ;; *) exit 2 ;; esac
etiqueta="tw-autocompletado-$(date +%s)-$$"
pg=''
limpiar() {
    if [[ -n "$pg" ]] && [[ $(docker inspect --format '{{index .Config.Labels "trendwatch.autocompletado"}}' "$pg") == "$etiqueta" ]]; then
        docker rm -f "$pg" >/dev/null
    fi
}
trap limpiar EXIT
red=none
if [[ "$fase" != sqlite ]]; then
    pg=$(docker run -d --label "trendwatch.autocompletado=$etiqueta" --network none --tmpfs /var/lib/postgresql/data \
        -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=tw_autocompletado_desechable postgis/postgis:17-3.5)
    listo=0
    for intento in {1..30}; do
        if docker exec "$pg" psql -h 127.0.0.1 -U postgres -d tw_autocompletado_desechable -tAc 'SELECT 1' >/dev/null 2>&1; then listo=1; break; fi
        sleep 1
    done
    [[ "$listo" == 1 ]] || exit 1
    docker exec "$pg" psql -U postgres -d tw_autocompletado_desechable -v ON_ERROR_STOP=1 \
        -c "COMMENT ON DATABASE tw_autocompletado_desechable IS 'trendwatch-autocompletado:solo-desechable:v1';" >/dev/null
    red="container:$pg"
fi
docker run --rm --network "$red" --read-only --tmpfs /tmp --label "trendwatch.autocompletado=$etiqueta" \
    -e TW_AUTOCOMPLETADO_AISLADO=1 -v "$raiz/app:/app:ro" -v "$raiz/tools/buscador:/validacion:ro" \
    --entrypoint python trendwatch-litoral-web:latest -B /validacion/validar_autocompletado.py "$fase"
