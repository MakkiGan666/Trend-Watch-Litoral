# Validación de calendarios y lectura

Sin dependencias nuevas: utiliza la imagen Django existente, Python, Node 20
con WebSocket experimental y Firefox instalado. No utiliza el puerto 8010.
Ejecutar desde la raíz del worktree de la corrección.

```sh
mkdir -p /tmp/tw-ui-evidence
ln -s "$PWD/app/static" /tmp/tw-ui-evidence/static

docker run --rm --network none --read-only --tmpfs /tmp \
  -v "$PWD/app:/app:ro" -v "$PWD/tools/frontend:/checks:ro" \
  -v /tmp/tw-ui-evidence:/evidence --entrypoint python \
  trendwatch-litoral-web:latest -B /checks/validar_plantillas.py test

docker run --rm --network none --read-only --tmpfs /tmp \
  -v "$PWD/app:/app:ro" -v "$PWD/tools/frontend:/checks:ro" \
  -v /tmp/tw-ui-evidence:/evidence --entrypoint python \
  trendwatch-litoral-web:latest -B /checks/validar_plantillas.py

python3 -B tools/frontend/ejecutar_navegador.py /tmp/tw-ui-evidence
```

Utilizar un directorio de evidencias propio si el indicado ya contiene trabajo
ajeno. Los tests Django usan exclusivamente SQLite en memoria, sin conexiones
externas. Las fixtures se renderizan desde las plantillas reales, sin ejecutar
las vistas ni consultar una base de datos. El servidor estático no aplica los
filtros: se comprueba su serialización GET; la semántica se cubre con Django.

El navegador usa un perfil temporal, bloquea solicitudes externas con un proxy
inaccesible y se cierra al finalizar. Conserva capturas y resultados JSON en el
directorio de evidencias; no modifica cuentas, sesiones ni contenedores existentes.
La imagen fallida produce un 404 intencional. Las fuentes externas no se cargan:
queda pendiente revisar la tipografía web y la interacción táctil en equipos reales.
