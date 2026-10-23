#!/usr/bin/env bash
# Sólo previsualización local con red privada sin NAT y conexiones salientes bloqueadas y SQLite en tmpfs.
set -euo pipefail
raiz=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ ${1:-iniciar} == detener ]]; then
    python3 - "$2" <<'PY'
import json,subprocess,sys
from pathlib import Path
p=Path(sys.argv[1]); datos=json.loads(p.read_text())
for tipo,identificador in [('container',datos['container']),('network',datos['network'])]:
    etiqueta=subprocess.check_output(['docker',tipo,'inspect','--format','{{index .Config.Labels "trendwatch.preview"}}' if tipo=='container' else '{{index .Labels "trendwatch.preview"}}',identificador],text=True).strip()
    if etiqueta!=datos['label']: raise SystemExit('Identidad del recurso no coincide')
subprocess.run(['docker','rm','-f',datos['container']],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['docker','network','rm',datos['network']],check=True,stdout=subprocess.DEVNULL)
print('Recursos propios de previsualización eliminados.')
PY
    exit
fi
[[ ${1:-iniciar} == iniciar ]] || exit 2
etiqueta="buscador-preview-$(date +%s)-$$"
red=$(docker network create --opt com.docker.network.bridge.enable_ip_masquerade=false --label "trendwatch.preview=$etiqueta" "$etiqueta")
contenedor=''
limpiar_error() {
    if [[ -n "$contenedor" ]]; then docker rm -f "$contenedor" >/dev/null; fi
    docker network rm "$red" >/dev/null
}
trap 'if [[ -n "$contenedor" ]]; then docker logs "$contenedor" > /tmp/tw-buscador-preview-error.log 2>&1 || true; fi; limpiar_error' ERR
contenedor=$(docker run -d --label "trendwatch.preview=$etiqueta" --network "$red" --read-only --tmpfs /tmp \
    -p 127.0.0.1::8000 -e TW_FRONT_PREVIEW_AISLADO=1 \
    -v "$raiz/app:/app:ro" -v "$raiz/tools/buscador:/preview:ro" \
    --entrypoint python trendwatch-litoral-web:latest -B /preview/previsualizar_busqueda.py)
puerto=$(docker port "$contenedor" 8000/tcp)
manifiesto=$(mktemp /tmp/tw-buscador-preview.XXXXXX.json)
python3 - "$contenedor" "$red" "$etiqueta" "$puerto" "$manifiesto" <<'PY'
import json,sys
from pathlib import Path
c,n,l,p,m=sys.argv[1:]
datos={'container':c,'network':n,'label':l,'url':'http://'+p}
Path(m).write_text(json.dumps(datos,indent=2))
print(json.dumps({'url':datos['url']+'/buscar/?q=educacion','manifiesto':m},ensure_ascii=False))
PY
