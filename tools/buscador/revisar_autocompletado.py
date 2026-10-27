"""Lanza perfiles Firefox propios; Node 20 usa WebSocket nativo sin paquetes."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

if len(sys.argv) != 3:
    raise SystemExit('Uso: python3 tools/buscador/revisar_autocompletado.py URL-local carpeta-capturas')
base, salida = sys.argv[1:]
url = urlsplit(base)
if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.path not in ('', '/'):
    raise SystemExit('Sólo URL de la previsualización localhost con puerto explícito')
base = base.rstrip('/')
script = Path(__file__).with_suffix('.mjs')
for sin_js in (False, True):
    with tempfile.TemporaryDirectory(prefix='tw-front-firefox-') as perfil:
        Path(perfil, 'user.js').write_text(
            'user_pref("browser.startup.homepage", "about:blank");\n'
            'user_pref("focusmanager.testmode", true);\n' +
            ('user_pref("javascript.enabled", false);\n' if sin_js else ''))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            puerto = sock.getsockname()[1]
        with tempfile.TemporaryFile() as log:
            proceso = subprocess.Popen(['firefox', '--headless', '--no-remote', '--profile', perfil,
                                        '--remote-debugging-port=' + str(puerto)], stdout=log, stderr=log)
            try:
                for intento in range(100):
                    try:
                        with socket.create_connection(('127.0.0.1', puerto), timeout=.2):
                            break
                    except OSError:
                        if proceso.poll() is not None:
                            raise RuntimeError('Firefox terminó antes de abrir BiDi')
                        time.sleep(.1)
                else:
                    raise RuntimeError('Firefox no abrió BiDi')
                subprocess.run(['node', '--experimental-websocket', str(script), str(puerto), base,
                                salida] + (['sin-js'] if sin_js else []), check=True, timeout=180)
            finally:
                if proceso.poll() is None:
                    proceso.terminate()
                    try:
                        proceso.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proceso.kill()
                        proceso.wait()
