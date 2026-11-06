#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/app"
APP_IMAGE="${H43B_APP_IMAGE:-trendwatch-litoral-web:latest}"
POSTGRES_IMAGE="${H43B_POSTGRES_IMAGE:-postgis/postgis:17-3.5}"
RUN_ID="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
DB_CONTAINER="tw-h43b-pilot-${RUN_ID}"
DB_CONTAINER_ID=""
TMP_DIR="$(mktemp -d "/tmp/tw-h43b-${RUN_ID}.XXXXXX")"
NONCE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

cleanup() {
  if [[ -n "$DB_CONTAINER_ID" ]]; then
    docker stop "$DB_CONTAINER_ID" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT INT TERM

if ! docker image inspect "$APP_IMAGE" >/dev/null 2>&1; then
  echo "No está disponible la imagen local de aplicación: $APP_IMAGE" >&2
  exit 2
fi
if ! docker image inspect "$POSTGRES_IMAGE" >/dev/null 2>&1; then
  echo "No está disponible la imagen PostgreSQL local: $POSTGRES_IMAGE" >&2
  exit 2
fi

# Barrera negativa antes de iniciar PostgreSQL: el módulo debe abortar en discovery,
# antes de que Django pueda crear una base de test.
if docker run --pull never --rm --network none --read-only --tmpfs /tmp \
  -v "$APP_DIR:/app:ro" -w /app \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHON_DOTENV_DISABLED=1 \
  -e DJANGO_SETTINGS_MODULE=mi_proyecto.settings -e SECRET_KEY=h43b-sintetica \
  -e DB_HOST=127.0.0.1 -e DB_NAME=tw_h43b_test -e DB_USER=tw_h43b_test \
  -e DB_PASSWORD=synthetic-only -e DB_PORT=5432 \
  -e GEMINI_API_KEY= -e GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS= \
  --entrypoint python "$APP_IMAGE" -B manage.py test core.test_h43b_piloto_postgres \
  >"$TMP_DIR/negative.log" 2>&1; then
  cat "$TMP_DIR/negative.log" >&2
  echo 'La prueba negativa no fue bloqueada sin atestación.' >&2
  exit 3
fi
if ! grep -Fq 'H4.3-B requiere tools/run_h43b_piloto_postgres.sh' "$TMP_DIR/negative.log"; then
  cat "$TMP_DIR/negative.log" >&2
  echo 'La prueba negativa falló por un motivo distinto al guard de aislamiento.' >&2
  exit 3
fi
echo 'OK: H4.3-B se bloquea sin atestación y antes de iniciar PostgreSQL.'

DB_CONTAINER_ID="$(docker run --pull never --rm -d --name "$DB_CONTAINER" --network none \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=1g \
  -e POSTGRES_DB=tw_h43b_test -e POSTGRES_USER=tw_h43b_test \
  -e POSTGRES_PASSWORD=synthetic-only \
  "$POSTGRES_IMAGE")"

INSPECT="$(docker inspect --format '{{.Id}} {{.HostConfig.NetworkMode}} {{json .HostConfig.PortBindings}} {{json .HostConfig.Tmpfs}}' "$DB_CONTAINER_ID")"
python3 -c '
import json, sys
parts = sys.argv[1].split(" ", 3)
if len(parts) != 4:
    raise SystemExit("No se pudo validar la configuración del contenedor PostgreSQL.")
container_id, network, ports, tmpfs = parts
bindings, mounts = json.loads(ports), json.loads(tmpfs)
if (container_id != sys.argv[2] or network != "none" or bindings not in (None, {}, [])
        or "/var/lib/postgresql/data" not in mounts):
    raise SystemExit("PostgreSQL no cumple network none, sin puertos y PGDATA en tmpfs.")
' "$INSPECT" "$DB_CONTAINER_ID"

listo=0
for intento in $(seq 1 60); do
  if docker exec "$DB_CONTAINER_ID" pg_isready -U tw_h43b_test -d tw_h43b_test >/dev/null 2>&1; then
    listo=1
    break
  fi
  sleep 1
done
if [[ "$listo" != 1 ]]; then
  echo 'PostgreSQL efímero no estuvo disponible dentro del timeout.' >&2
  exit 4
fi

CLUSTER_SYSTEM_IDENTIFIER="$(docker exec "$DB_CONTAINER_ID" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U tw_h43b_test -d tw_h43b_test \
  -c 'SELECT system_identifier::text FROM pg_control_system()')"
if [[ ! "$CLUSTER_SYSTEM_IDENTIFIER" =~ ^[0-9]{1,20}$ ]]; then
  echo 'No se pudo leer una identidad válida del clúster efímero.' >&2
  exit 5
fi

python3 - "$TMP_DIR/attestation.json" "$DB_CONTAINER" "$DB_CONTAINER_ID" \
  "$CLUSTER_SYSTEM_IDENTIFIER" "$NONCE" <<'PY'
import json, sys
path, container, container_id, cluster_system_identifier, nonce = sys.argv[1:]
data = {
    'version': 1,
    'container_name': container,
    'container_id': container_id,
    'network_mode': 'none',
    'published_ports': False,
    'pgdata_tmpfs': True,
    'database_name': 'tw_h43b_test',
    'test_database_name': 'test_tw_h43b_test',
    'cluster_system_identifier': cluster_system_identifier,
    'nonce': nonce,
}
with open(path, 'x', encoding='utf-8') as stream:
    json.dump(data, stream)
PY

echo 'Ejecutando H4.3-B en PostgreSQL efímero; el runner solo podrá preparar test_tw_h43b_test.'
docker run --pull never --rm --network "container:$DB_CONTAINER_ID" --read-only --tmpfs /tmp \
  -v "$APP_DIR:/app:ro" -v "$TMP_DIR:/evidence:ro" -w /app \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHON_DOTENV_DISABLED=1 \
  -e DJANGO_SETTINGS_MODULE=mi_proyecto.settings -e SECRET_KEY=h43b-sintetica \
  -e DB_HOST=127.0.0.1 -e DB_NAME=tw_h43b_test -e DB_USER=tw_h43b_test \
  -e DB_PASSWORD=synthetic-only -e DB_PORT=5432 \
  -e GEMINI_API_KEY= -e GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS= \
  -e H43B_ISOLATION_ATTESTATION=/evidence/attestation.json \
  -e H43B_ISOLATION_NONCE="$NONCE" \
  --entrypoint python "$APP_IMAGE" -B manage.py test core.test_h43b_piloto_postgres
