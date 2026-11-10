"""Catálogo H1.1: configuración pura, sin descargas ni persistencia.

Feeds confirmados por la auditoría local del 05/11/2026. El Territorio
conserva su circuito independiente. Habilitar una fuente aquí no ejecuta ingesta.
"""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from core.services.parametros import entero_positivo, segundos_validos


@dataclass(frozen=True)
class FuenteRSS:
    identificador: str
    nombre: str
    feed: str | None
    hosts_permitidos: tuple[str, ...]
    habilitada: bool = False
    limite_noticias: int = 30
    timeout_segundos: float = 10
    max_bytes: int = 1_500_000
    max_redirecciones: int = 4
    solo_importacion_historica: bool = False

    def __post_init__(self):
        if not isinstance(self.identificador, str) or not re.fullmatch(
            r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', self.identificador
        ):
            raise ValueError('Identificador de fuente inválido.')
        if not isinstance(self.nombre, str) or not self.nombre.strip():
            raise ValueError('Nombre de fuente vacío.')
        if type(self.habilitada) is not bool:
            raise ValueError('habilitada debe ser un booleano.')
        if type(self.solo_importacion_historica) is not bool:
            raise ValueError('solo_importacion_historica debe ser un booleano.')
        if type(self.hosts_permitidos) is not tuple or not self.hosts_permitidos:
            raise ValueError('hosts_permitidos debe ser una tupla no vacía.')
        for host in self.hosts_permitidos:
            if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(
                r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
                r'[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?', host
            ):
                raise ValueError('Host permitido inválido: usar DNS exacto en minúsculas.')
        if len(set(self.hosts_permitidos)) != len(self.hosts_permitidos):
            raise ValueError('Hosts permitidos duplicados.')
        for campo in ('limite_noticias', 'max_bytes'):
            entero_positivo(getattr(self, campo), campo)
        segundos_validos(self.timeout_segundos, 'timeout_segundos')
        if type(self.max_redirecciones) is not int or self.max_redirecciones < 0:
            raise ValueError('max_redirecciones debe ser un entero no negativo.')
        if self.solo_importacion_historica:
            if self.feed is not None or self.habilitada:
                raise ValueError('Una fuente histórica debe carecer de feed y permanecer deshabilitada.')
        else:
            if not isinstance(self.feed, str) or not self.feed.strip():
                raise ValueError('Una fuente RSS requiere una URL de feed.')
            self.validar_url(self.feed)

    def validar_url(self, url):
        """Valida sólo sintaxis y host exacto; no resuelve DNS ni descarga.

        Un futuro transporte deberá controlar además DNS público, cada salto y
        los límites de descarga. Esta validación por sí sola no evita SSRF.
        """
        if (not isinstance(url, str) or '\\' in url
                or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
            raise ValueError('URL inválida.')
        partes = urlsplit(url)
        if (partes.scheme != 'https' or partes.hostname not in self.hosts_permitidos
                or partes.username is not None or partes.password is not None
                or partes.port not in (None, 443) or '#' in url):
            raise ValueError('Destino no autorizado para la fuente.')
        return partes


def validar_catalogo(fuentes):
    """Devuelve una tupla validada, rechazando IDs y feeds duplicados."""
    fuentes = tuple(fuentes)
    identificadores, feeds = set(), set()
    for fuente in fuentes:
        if not isinstance(fuente, FuenteRSS):
            raise ValueError('El catálogo sólo admite FuenteRSS.')
        clave_feed = None
        if fuente.feed is not None:
            partes = fuente.validar_url(fuente.feed)
            clave_feed = (partes.hostname, partes.path or '/', partes.query)
        if fuente.identificador in identificadores or (clave_feed and clave_feed in feeds):
            raise ValueError('Identificador o feed duplicado en el catálogo.')
        identificadores.add(fuente.identificador)
        if clave_feed:
            feeds.add(clave_feed)
    return fuentes


FUENTES_RSS = validar_catalogo((
    FuenteRSS('misiones_online', 'Misiones Online', 'https://misionesonline.net/feed/', ('misionesonline.net', 'www.misionesonline.net')),
    FuenteRSS('primera_edicion', 'Primera Edición', 'https://www.primeraedicion.com.ar/feed/', ('primeraedicion.com.ar', 'www.primeraedicion.com.ar')),
    FuenteRSS('noticias_de_la_calle', 'Noticias de la Calle', 'https://www.noticiasdelacalle.com.ar/rss/noticias', ('noticiasdelacalle.com.ar', 'www.noticiasdelacalle.com.ar')),
    FuenteRSS('noticias_del_6', 'Noticias del 6', 'https://noticiasdel6.com/feed/', ('noticiasdel6.com', 'www.noticiasdel6.com')),
    FuenteRSS('infober', 'INFOBER', 'https://infoberdigital.com/feed/', ('infoberdigital.com', 'www.infoberdigital.com')),
    FuenteRSS('obera_online', 'OberaOnline', 'https://oberaonline.com.ar/feed/', ('oberaonline.com.ar', 'www.oberaonline.com.ar')),
    FuenteRSS('obera_inside', 'Oberá Inside', 'https://oberainside.com.ar/?feed=rss2', ('oberainside.com.ar', 'www.oberainside.com.ar')),
    FuenteRSS('stop_en_linea', 'Stop en Línea', 'https://www.stopenlinea.com.ar/rss/noticias', ('stopenlinea.com.ar', 'www.stopenlinea.com.ar')),
    FuenteRSS('e24n', 'E24N', 'https://e24n.com.ar/feed/', ('e24n.com.ar', 'www.e24n.com.ar')),
    FuenteRSS('eldorado_noticias', 'Eldorado Noticias', 'https://eldoradonoticias.com.ar/feed/', ('eldoradonoticias.com.ar', 'www.eldoradonoticias.com.ar')),
    FuenteRSS('norte_misionero', 'Norte Misionero', 'https://nortemisionero.com.ar/feed/', ('nortemisionero.com.ar', 'www.nortemisionero.com.ar')),
    FuenteRSS('la_voz_de_cataratas', 'La Voz de Cataratas', 'https://lavozdecataratas.com/feed/', ('lavozdecataratas.com', 'www.lavozdecataratas.com')),
    FuenteRSS('iguazu_ahora', 'Iguazú Ahora', 'https://iguazuahora.com/feed/', ('iguazuahora.com', 'www.iguazuahora.com')),
    FuenteRSS('radio_yguazu', 'Radio Yguazú', 'https://radioiguazu.com/feed/', ('radioiguazu.com', 'www.radioiguazu.com')),
    FuenteRSS('alem_news', 'Alem News', 'https://www.alem.news/feed/', ('alem.news', 'www.alem.news')),
    FuenteRSS('la_mision_digital', 'La Misión Digital', 'https://lamisiondigital.com/feed/', ('lamisiondigital.com', 'www.lamisiondigital.com')),
    FuenteRSS('fracran_noticias', 'Fracrán Noticias', 'https://www.fracran.com.ar/feed.xml', ('fracran.com.ar', 'www.fracran.com.ar')),
    FuenteRSS('noticias_de_irigoyen', 'Noticias de Irigoyen', 'https://noticiasdeirigoyen.com.ar/feed/', ('noticiasdeirigoyen.com.ar', 'www.noticiasdeirigoyen.com.ar')),
))

# Fuentes de descubrimiento/importación, deliberadamente fuera del catálogo RSS
# para no incluirlas en consultas ni orquestación de feeds.
FUENTES_HISTORICAS = validar_catalogo((
    FuenteRSS(
        'el_territorio', 'El Territorio', None,
        ('elterritorio.com.ar', 'www.elterritorio.com.ar'),
        solo_importacion_historica=True,
    ),
))


def obtener_fuentes(*, solo_habilitadas=True):
    return tuple(f for f in FUENTES_RSS if f.habilitada or not solo_habilitadas)
