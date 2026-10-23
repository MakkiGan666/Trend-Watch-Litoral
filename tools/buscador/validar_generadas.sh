#!/usr/bin/env bash
# Sólo bases nuevas y SQLite en tmpfs; no acepta DSN, puertos ni recursos existentes.
set -euo pipefail
raiz=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
fase=${1:-todo}
case "$fase" in todo|postgresql|sqlite|medir) ;; *) echo 'Usar todo, postgresql, sqlite o medir' >&2; exit 2 ;; esac
etiqueta="buscador-generadas-$(date +%s)-$$"
pg=''
limpiar() {
    if [[ -n "$pg" ]] && [[ $(docker inspect --format '{{index .Config.Labels "trendwatch.validacion"}}' "$pg") == "$etiqueta" ]]; then
        docker rm -f "$pg" >/dev/null
        echo "Recurso propio eliminado: $pg" >&2
    fi
}
trap limpiar EXIT
if [[ "$fase" != sqlite ]]; then
    pg=$(docker run -d --label "trendwatch.validacion=$etiqueta" --network none --tmpfs /var/lib/postgresql/data \
        -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=tw_buscador_desechable_generadas postgis/postgis:17-3.5)
    listo=0
    for intento in {1..30}; do
        # El servidor temporal de initdb sólo escucha en socket; esperar TCP
        # y la base concreta evita confundirlo con el servidor definitivo.
        if docker exec "$pg" psql -h 127.0.0.1 -U postgres -d tw_buscador_desechable_generadas -tAc 'SELECT 1' >/dev/null 2>&1; then listo=1; break; fi
        sleep 1
    done
    if [[ "$listo" != 1 ]]; then echo 'PostgreSQL desechable no quedó disponible' >&2; exit 1; fi
    docker exec "$pg" psql -U postgres -d tw_buscador_desechable_generadas -v ON_ERROR_STOP=1 \
        -c "COMMENT ON DATABASE tw_buscador_desechable_generadas IS 'trendwatch-buscador:solo-pruebas-desechables:v1';" >/dev/null
fi
ejecutar() {
    local red=none
    if [[ "$1" != sqlite ]]; then red="container:$pg"; fi
    docker run --rm --label "trendwatch.validacion=$etiqueta" --network "$red" --read-only --tmpfs /tmp \
        -e TW_GENERADAS_AISLADO=1 -e "TW_GENERADAS_LECTURAS=${TW_GENERADAS_LECTURAS:-0}" -v "$raiz/app:/app:ro" -v "$raiz/tools/buscador:/validacion:ro" \
        -v "$raiz/docs/buscador-noticias-persistido-resultados.json:/referencia.json:ro" \
        --entrypoint python trendwatch-litoral-web:latest -B /validacion/validar_generadas.py "$1"
}
if [[ "$fase" == todo ]]; then
    ejecutar postgresql
    ejecutar sqlite
    ejecutar medir
else
    ejecutar "$fase"
fi
