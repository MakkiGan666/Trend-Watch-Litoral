"""Firefox headless con perfil propio; no visita servicios ni bases existentes."""
import functools
import http.server
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def main():
    output = Path(sys.argv[1]).resolve()
    root = Path(__file__).resolve().parents[2]
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(output),
    ))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = Path(tempfile.mkdtemp(prefix='tw-ui-firefox-'))
    (profile / 'user.js').write_text(
        'user_pref("network.proxy.type",1);\n'
        'user_pref("network.proxy.http","127.0.0.1");\n'
        'user_pref("network.proxy.http_port",9);\n'
        'user_pref("network.proxy.ssl","127.0.0.1");\n'
        'user_pref("network.proxy.ssl_port",9);\n'
        'user_pref("network.proxy.no_proxies_on","localhost,127.0.0.1");\n'
        'user_pref("network.prefetch-next",false);\n'
        'user_pref("focusmanager.testmode",true);\n'
    )
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with (output / 'firefox.log').open('w') as log:
        process = subprocess.Popen([
            'firefox', '--headless', '--no-remote', '--profile', str(profile),
            '--remote-debugging-port', str(port),
        ], stdout=log, stderr=log)
        try:
            for _ in range(60):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.2)
            result = subprocess.run([
                'node', '--experimental-websocket', str(root / 'tools/frontend/verificar_visuales.mjs'),
                str(port), f'http://127.0.0.1:{server.server_port}', str(output),
            ], timeout=180)
            return result.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            server.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
