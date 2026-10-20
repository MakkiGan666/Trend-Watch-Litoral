"""Transporte del medio: HTTPS directo, sin proxies ni resolución posterior al control."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

HOSTS = frozenset({'elterritorio.com.ar', 'www.elterritorio.com.ar'})
MAX_BYTES = 8 * 1024 * 1024


def validar_url(url):
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url:
        raise ValueError('URL inválida')
    partes = urlsplit(url)
    if (partes.scheme != 'https' or partes.hostname not in HOSTS
            or partes.username is not None or partes.password is not None
            or partes.port not in (None, 443) or partes.fragment):
        raise ValueError('Destino no autorizado')
    return partes


def _direccion_publica(texto):
    ip = ipaddress.ip_address(texto)
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
        if ip.ipv4_mapped is not None:
            return _direccion_publica(str(ip.ipv4_mapped))
    return True


class _Conexion(http.client.HTTPSConnection):
    def __init__(self, host, destino, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.destino = destino

    def connect(self):
        familia, tipo, protocolo, _, direccion = self.destino
        sock = socket.socket(familia, tipo, protocolo)
        try:
            sock.settimeout(self.timeout)
            sock.connect(direccion)  # sockaddr validado; no vuelve a resolver el nombre.
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def descargar(url, timeout=10):
    for salto in range(6):
        partes = validar_url(url)
        destinos = socket.getaddrinfo(partes.hostname, 443, type=socket.SOCK_STREAM)
        if not destinos or any(not _direccion_publica(d[4][0]) for d in destinos):
            raise ValueError('Resolución DNS no pública')
        conexion = _Conexion(partes.hostname, destinos[0], timeout)
        try:
            ruta = partes.path or '/'
            if partes.query:
                ruta += '?' + partes.query
            conexion.request('GET', ruta, headers={'User-Agent': 'TrendWatch/1.0', 'Accept-Encoding': 'identity'})
            respuesta = conexion.getresponse()
            if respuesta.status in (301, 302, 303, 307, 308):
                ubicacion = respuesta.getheader('Location')
                if not ubicacion:
                    raise ValueError('Redirección sin destino')
                url = urljoin(url, ubicacion)
                continue  # Cada salto vuelve a validar URL y resolución.
            if respuesta.status != 200:
                raise OSError(f'HTTP {respuesta.status}')
            datos = respuesta.read(MAX_BYTES + 1)
            if len(datos) > MAX_BYTES:
                raise ValueError('Respuesta demasiado grande')
            return datos
        finally:
            conexion.close()
    raise ValueError('Demasiadas redirecciones')
