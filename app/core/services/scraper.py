import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from core.services.descarga_segura import descargar, validar_url
from datetime import date, datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone
from core.models import Publicacion, RegistroDatos
from core.services.clasificacion import clasificar_lote, vincular_categoria_por_nombre

logger = logging.getLogger(__name__)

try:
    from newspaper import Article # pyright: ignore[reportMissingImports]
except ModuleNotFoundError:
    try:
        from newspaper3k import Article # pyright: ignore[reportMissingImports]
    except ModuleNotFoundError:
        class Article:
            def __init__(self, *args, **kwargs):
                self.text = ""

            def download(self, **kwargs):
                return None

            def parse(self):
                return None

REDES_SOCIALES = {
    "linktree": "https://linktr.ee/elterritoriooficial",
    "instagram": "https://www.instagram.com/elterritoriooficial/",
    "facebook": "https://www.facebook.com/elterritoriooficial/",
    "twitter": "https://twitter.com/elterritorio",
    "tiktok": "https://www.tiktok.com/@elterritoriooficial"
}

# Al 16/10/2026 "tecnologia" y "actualidad" se publican vacíos; se conservan por si
# el medio vuelve a cargarlos. El resto se clasifica en las categorías del proyecto.
CATEGORIAS_TERRITORIO = {
    "misiones": "https://www.elterritorio.com.ar/rss/misiones",
    "tecnologia": "https://www.elterritorio.com.ar/rss/tecnologia",
    "policiales": "https://www.elterritorio.com.ar/rss/policiales",
    "cultura": "https://www.elterritorio.com.ar/rss/cultura",
    "actualidad": "https://www.elterritorio.com.ar/rss/actualidad",
    "deportes": "https://www.elterritorio.com.ar/rss/deportes",
    "agro": "https://www.elterritorio.com.ar/rss/agro",
    "la-region": "https://www.elterritorio.com.ar/rss/la-region",
    "pais-y-mundo": "https://www.elterritorio.com.ar/rss/pais-y-mundo",
}
SITEMAP_TERRITORIO = "https://www.elterritorio.com.ar/sitemap.xml"
LIMITE_POR_DEFECTO = 30

_NS_MEDIA = '{http://search.yahoo.com/mrss/}'
_NS_SITEMAP = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
_FECHA_EN_URL = re.compile(r'/noticias/(\d{4})/(\d{2})/(\d{2})/(\d+)-')

def generar_hash(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()

def _excede_largo_maximo(campo, valor):
    return len(valor) > Publicacion._meta.get_field(campo).max_length


def _descargar(url, timeout=10):
    return descargar(url, timeout=timeout)


def _imagen_valida(url):
    """Sólo se guardan enlaces http(s) que entren en el campo; si no, la noticia queda sin foto."""
    url = (url or '').strip()
    if not re.match(r'^https?://', url) or _excede_largo_maximo('imagen_url', url):
        return ''
    return url


def _imagen_rss(item):
    media = item.find(f'{_NS_MEDIA}content')
    if media is not None and media.get('url'):
        return media.get('url')
    enclosure = item.find('enclosure')
    if enclosure is not None and (enclosure.get('type') or '').startswith('image'):
        return enclosure.get('url')
    return ''


def _fecha_rss(item):
    nodo = item.find('pubDate')
    try:
        fecha = parsedate_to_datetime(nodo.text.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return fecha if timezone.is_aware(fecha) else timezone.make_aware(fecha, dt_timezone.utc)


def _fecha_de_url(link):
    coincidencia = _FECHA_EN_URL.search(link)
    if not coincidencia:
        return None
    try:
        return date(*(int(parte) for parte in coincidencia.groups()[:3]))
    except ValueError:
        return None


def _leer_articulo(link):
    """Extrae HTML obtenido por el transporte controlado, sin descargas de imágenes."""
    try:
        article = Article(link, language='es', fetch_images=False)
        article.download(input_html=_descargar(link))
        article.parse()
        return article
    except Exception:
        return None


class _Lote:
    """Registro de ejecución y contadores compartidos por la ingesta RSS y la histórica."""

    def __init__(self, fuente_nombre):
        self.fuente_nombre = fuente_nombre
        self.registro = RegistroDatos.objects.create(
            fuentes_api=fuente_nombre,
            fecha_ejecucion=timezone.now(),
            estado="EN_PROCESO",
            lenguaje="es"
        )
        self.capturados = 0
        self.omitidas = 0
        self.errores = []
        self.categorias = {}
        self.disponibles = 0
        self.incompleta = False
        self.fuentes_completadas = 0

    def registrar_error(self, link, titulo, codigo):
        # Sólo se registran datos de identificación; nunca el contenido de la noticia.
        error = {
            'link': link or None,
            'hash_origen': generar_hash(link) if link else None,
            'titulo': titulo[:80],
            'codigo': codigo,
        }
        self.errores.append(error)
        logger.warning(
            'Ingesta %s: noticia descartada (%s). link=%s hash_origen=%s titulo=%r',
            self.fuente_nombre, codigo, error['link'], error['hash_origen'], error['titulo'],
        )

    def guardar(self, candidatos, usar_ia):
        """Clasifica el lote completo (una llamada a la IA) y guarda cada noticia en su savepoint."""
        validos = []
        for candidato in candidatos:
            try:
                validar_url(candidato['url'])
                if (not candidato['titulo'].strip() or not candidato['contenido'].strip()
                        or candidato['hash_origen'] != generar_hash(candidato['url'])):
                    raise ValueError('Identidad o contenido incompleto')
            except ValueError:
                self.registrar_error(candidato.get('url'), candidato.get('titulo', ''), 'articulo_incompleto')
                continue
            validos.append(candidato)
        candidatos = validos
        clasificaciones = clasificar_lote(candidatos, usar_ia=usar_ia)
        if len(clasificaciones) != len(candidatos):
            raise ValueError('Clasificación incompleta')
        for candidato, clasificacion in zip(candidatos, clasificaciones):
            try:
                with transaction.atomic():
                    publicacion = Publicacion.objects.create(
                        hash_origen=candidato['hash_origen'],
                        fuente=self.fuente_nombre,
                        titulo=candidato['titulo'],
                        contenido=candidato['contenido'],
                        url=candidato['url'],
                        imagen_url=candidato['imagen_url'],
                        fecha_publicacion=candidato['fecha_publicacion'],
                        departamento=clasificacion['departamento'],
                        procesado_ia=False,
                        id_registro=self.registro, # Relación ForeignKey con RegistroDatos
                        fecha_captura=timezone.now()
                    )
                    vincular_categoria_por_nombre(publicacion, clasificacion['categoria'])
            except IntegrityError:
                # Consultar después de salir del bloque que falló. Sólo es duplicado si la
                # publicación existe; cualquier otra violación interrumpe el lote.
                if not Publicacion.objects.filter(hash_origen=candidato['hash_origen']).exists():
                    raise
                self.omitidas += 1
                continue
            except DataError:
                self.registrar_error(candidato['url'], candidato['titulo'], 'datos_invalidos')
                continue
            self.capturados += 1
            categoria = clasificacion['categoria']
            self.categorias[categoria] = self.categorias.get(categoria, 0) + 1

    def exito(self):
        completa = not self.errores and not self.incompleta
        util = self.capturados or self.omitidas or self.fuentes_completadas
        estado = ('SIN_RESULTADOS' if not self.disponibles else
                  'DUPLICADOS' if self.omitidas and not self.capturados else 'EXITO') if completa else (
                      'PARCIAL' if util else 'FALLO')
        self.registro.estado = "EXITO" if completa else "ERROR: " + estado
        self.registro.save()
        return {
            "status": "EXITO" if completa else "ERROR",
            "estado": estado,
            "detalle": "Cobertura incompleta: revisar errores y límite." if not completa else "Cobertura completada.",
            "cobertura_completa": completa,
            "disponibles": self.disponibles,
            "capturados": self.capturados,
            "registro_id": self.registro.id_registro,
            "omitidas": self.omitidas,
            "errores": self.errores,
            "categorias": self.categorias,
        }

    def fallo(self, exc):
        logger.error(
            'Ingesta %s interrumpida (%s) con %d publicaciones ya guardadas.',
            self.fuente_nombre, type(exc).__name__, self.capturados,
        )
        self.registro.estado = f"ERROR: {str(exc)[:40]}"
        try:
            self.registro.save()
        except Exception:
            logger.error('No se pudo cerrar el registro de ingesta %s', self.registro.pk)
        return {"status": "ERROR", "estado": "PARCIAL" if self.capturados or self.omitidas else "FALLO",
                "cobertura_completa": False, "detalle": str(exc), "capturados": self.capturados,
                "omitidas": self.omitidas, "errores": self.errores, "categorias": self.categorias,
                "disponibles": self.disponibles, "registro_id": self.registro.pk}


def fetch_and_store_elterritorio(category="misiones", limit=LIMITE_POR_DEFECTO, usar_ia=True):
    """Ingesta el RSS de una categoría y guarda las noticias nuevas.

    Cada noticia se deriva a una categoría del proyecto y, si se identifica, a un
    departamento (ver core.services.clasificacion).

    `status` conserva EXITO/ERROR; `estado` distingue resultado y cobertura.
    Errores individuales y límites que dejan candidatos pendientes producen ERROR/PARCIAL.
    Los duplicados no son errores y nunca se actualizan publicaciones existentes.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"status": "ERROR", "estado": "FALLO", "cobertura_completa": False, "capturados": 0, "detalle": "Límite inválido"}
    url_feed = CATEGORIAS_TERRITORIO.get(category)
    if url_feed is None:
        # Antes se usaba el feed de Misiones con la etiqueta de la categoría pedida.
        return {
            "status": "ERROR", "estado": "FALLO", "cobertura_completa": False,
            "detalle": f"Categoría desconocida. Válidas: {', '.join(CATEGORIAS_TERRITORIO)}.",
            "capturados": 0,
        }

    # 1. Crear RegistroDatos (Auditoría de Ingesta)
    try:
        lote = _Lote(f"El Territorio ({category.capitalize()})")
    except Exception:
        return {"status": "ERROR", "estado": "FALLO", "cobertura_completa": False,
                "capturados": 0, "detalle": "No se pudo iniciar el registro de ingesta."}

    try:
        root = ET.fromstring(_descargar(url_feed))
        if root.tag != 'rss' or root.find('channel') is None:
            raise ValueError('Documento RSS inválido')
        todos = root.findall('.//item')
        lote.disponibles = len(todos)
        lote.incompleta = len(todos) > limit
        lote.fuentes_completadas = 1
        items = todos[:limit]

        candidatos = []
        vistos = set()
        for item in items:
            link_node = item.find('link')
            title_node = item.find('title')
            description_node = item.find('description')

            link = link_node.text.strip() if link_node is not None and link_node.text else ""
            titulo = title_node.text.strip() if title_node is not None and title_node.text else ""
            if not link:
                lote.registrar_error(link, titulo, 'sin_enlace')
                continue
            try:
                validar_url(link)
            except ValueError:
                lote.registrar_error(link, titulo, 'url_invalida')
                continue
            # Los límites salen del modelo para no duplicarlos; SQLite no los controla.
            if _excede_largo_maximo('titulo', titulo) or _excede_largo_maximo('url', link):
                lote.registrar_error(link, titulo, 'datos_invalidos')
                continue

            hash_id = generar_hash(link)

            # 2. Deduplicación mediante ORM Django (RF-02), también dentro del mismo feed
            if hash_id in vistos or Publicacion.objects.filter(hash_origen=hash_id).exists():
                lote.omitidas += 1
                continue # Si ya existe, omitir
            vistos.add(hash_id)

            # 3. Scraping con newspaper3k para cuerpo completo
            raw_desc = description_node.text if description_node is not None and description_node.text else ""
            article = _leer_articulo(link)
            contenido = (getattr(article, 'text', '') or '') if article else ''
            if not contenido.strip():
                lote.registrar_error(link, titulo, 'extraccion_incompleta')
                contenido = re.sub(r'<[^>]+>', '', raw_desc).strip()

            if not titulo or not contenido.strip():
                lote.registrar_error(link, titulo, 'articulo_incompleto')
                continue

            candidatos.append({
                'hash_origen': hash_id,
                'titulo': titulo,
                'contenido': contenido,
                'url': link,
                'imagen_url': _imagen_valida(
                    _imagen_rss(item) or (getattr(article, 'top_image', '') if article else '')
                ),
                'fecha_publicacion': _fecha_rss(item),
                'seccion': category,
            })

        # 4. Clasificar y guardar en tabla Publicacion, en un savepoint propio por noticia
        lote.guardar(candidatos, usar_ia)

        # Actualizar estado del registro a ÉXITO
        return lote.exito()

    except Exception as e:
        return lote.fallo(e)


def _urls_de_sitemaps(desde, hasta, lote=None):
    """Devuelve {link: fecha} de las noticias de El Territorio publicadas entre ambas fechas."""
    indice = ET.fromstring(_descargar(SITEMAP_TERRITORIO, timeout=20))
    if indice.tag not in (f'{_NS_SITEMAP}sitemapindex', f'{_NS_SITEMAP}urlset'):
        raise ValueError('Índice sitemap inválido')
    if indice.tag == f'{_NS_SITEMAP}sitemapindex':
        for nodo in indice.findall(f'{_NS_SITEMAP}sitemap'):
            if not (nodo.findtext(f'{_NS_SITEMAP}loc') or '').strip():
                raise ValueError('Sitemap sin destino')
    sitemaps = [n.text.strip() for n in indice.iter(f'{_NS_SITEMAP}loc') if n.text]
    urls = {}
    if indice.tag == f'{_NS_SITEMAP}urlset':
        sitemaps = [SITEMAP_TERRITORIO]
    for sitemap in sitemaps:
        try:
            raiz = indice if sitemap == SITEMAP_TERRITORIO else ET.fromstring(_descargar(sitemap, timeout=20))
            if raiz.tag != f'{_NS_SITEMAP}urlset':
                raise ValueError('Sitemap no es urlset')
            if lote is not None:
                lote.fuentes_completadas += 1
        except Exception as exc:
            # Conservar los demás sitemaps y dejar explícita la cobertura incompleta.
            logger.warning('Sitemap omitido (%s): %s', type(exc).__name__, sitemap)
            if lote is None:
                raise
            lote.registrar_error(sitemap, '', 'sitemap_no_disponible')
            continue
        for entrada in raiz.findall(f'{_NS_SITEMAP}url'):
            if not (entrada.findtext(f'{_NS_SITEMAP}loc') or '').strip():
                if lote is None:
                    raise ValueError('Entrada sitemap sin URL')
                lote.registrar_error('', '', 'sin_enlace')
        for nodo in raiz.iter(f'{_NS_SITEMAP}loc'):
            link = (nodo.text or '').strip()
            try:
                validar_url(link)
            except ValueError:
                if lote is not None:
                    lote.registrar_error(link, '', 'url_invalida')
                continue
            fecha = _fecha_de_url(link)
            if fecha and desde <= fecha <= hasta:
                urls[link] = fecha
    return urls


def _repartir_por_dia(urls):
    """Ordena los links alternando días (del más reciente al más viejo) para cubrir todo el período.

    El sitemap no informa relevancia, así que en lugar de quedarnos sólo con los últimos
    días se toma una noticia por día por vuelta, empezando por la más reciente de cada día.
    """
    por_dia = {}
    for link, fecha in urls.items():
        por_dia.setdefault(fecha, []).append(link)
    columnas = []
    for fecha in sorted(por_dia, reverse=True):
        columnas.append(sorted(
            por_dia[fecha], key=lambda l: int(_FECHA_EN_URL.search(l).group(4)), reverse=True,
        ))
    orden = []
    for vuelta in range(max((len(c) for c in columnas), default=0)):
        orden.extend(c[vuelta] for c in columnas if vuelta < len(c))
    return orden


def ingestar_historico_elterritorio(desde, hasta, limite=40, usar_ia=True, pausa=0.5):
    """Ingesta noticias publicadas entre `desde` y `hasta` (fechas) usando los sitemaps.

    Toma hasta `limite` noticias nuevas repartidas a lo largo del período. Las que ya
    existen no cuentan para el límite. Mismo contrato de resultado que la ingesta RSS.
    """
    if not isinstance(limite, int) or isinstance(limite, bool) or limite < 1:
        return {"status": "ERROR", "estado": "FALLO", "cobertura_completa": False, "capturados": 0, "detalle": "Límite inválido"}
    if desde > hasta:
        return {"status": "ERROR", "estado": "FALLO", "cobertura_completa": False, "detalle": "La fecha inicial es posterior a la final.", "capturados": 0}

    try:
        lote = _Lote("El Territorio (Archivo)")
    except Exception:
        return {"status": "ERROR", "estado": "FALLO", "cobertura_completa": False,
                "capturados": 0, "detalle": "No se pudo iniciar el registro de ingesta."}
    try:
        urls = _urls_de_sitemaps(desde, hasta, lote=lote)
        lote.disponibles = len(urls)
        existentes = set(Publicacion.objects.filter(
            hash_origen__in=[generar_hash(link) for link in urls],
        ).values_list('hash_origen', flat=True))
        lote.omitidas = len(existentes)

        candidatos = []
        for link in _repartir_por_dia(urls):
            if len(candidatos) >= limite:
                if generar_hash(link) not in existentes:
                    lote.incompleta = True
                continue
            hash_id = generar_hash(link)
            if hash_id in existentes:
                continue
            if _excede_largo_maximo('url', link):
                lote.registrar_error(link, '', 'datos_invalidos')
                continue
            if candidatos and pausa:
                time.sleep(pausa)  # No saturar el sitio del medio.
            article = _leer_articulo(link)
            titulo = (getattr(article, 'title', '') or '').strip() if article else ''
            contenido = (getattr(article, 'text', '') or '').strip() if article else ''
            if not titulo or not contenido:
                lote.registrar_error(link, titulo, 'articulo_no_disponible')
                continue
            if _excede_largo_maximo('titulo', titulo):
                lote.registrar_error(link, titulo, 'datos_invalidos')
                continue
            fecha = getattr(article, 'publish_date', None)
            if isinstance(fecha, datetime):
                fecha = fecha if timezone.is_aware(fecha) else timezone.make_aware(fecha, dt_timezone.utc)
            else:
                dia = urls[link]
                fecha = datetime(dia.year, dia.month, dia.day, 12, tzinfo=dt_timezone.utc)
            candidatos.append({
                'hash_origen': hash_id,
                'titulo': titulo,
                'contenido': contenido,
                'url': link,
                'imagen_url': _imagen_valida(getattr(article, 'top_image', '')),
                'fecha_publicacion': fecha,
                'seccion': '',
            })

        lote.guardar(candidatos, usar_ia)
        resultado = lote.exito()
        resultado['disponibles'] = len(urls)
        return resultado
    except Exception as e:
        return lote.fallo(e)
