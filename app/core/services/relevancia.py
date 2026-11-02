"""Selección regional y tendencias con señales verificables, sin IA."""
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.text import slugify

from core.localidades import DEPARTAMENTOS
from core.models import ClicPublicacion, Publicacion, TemaTrend, Trend
from core.services.clasificacion import CATEGORIAS_PROYECTO


SLUGS_MISIONES = [departamento['slug'] for departamento in DEPARTAMENTOS]


def publicaciones_provinciales():
    # Un departamento confirmado es la señal más fuerte. Las referencias en
    # el título permiten incluir noticias provinciales sin municipio concreto.
    return Publicacion.objects.filter(
        Q(departamento__in=SLUGS_MISIONES)
        | Q(titulo__icontains='Misiones')
        | Q(titulo__icontains='misionera')
        | Q(titulo__icontains='misionero')
    )


def _fecha(publicacion):
    return publicacion.fecha_publicacion or publicacion.fecha_captura


def _puntaje(publicacion):
    titulo = publicacion.titulo.casefold()
    dias = max(0, (timezone.now() - _fecha(publicacion)).days)
    return (
        min(publicacion.clics_recientes, 30) * 10
        + (5 if publicacion.departamento in SLUGS_MISIONES else 0)
        + (4 if 'misiones' in titulo or 'misioner' in titulo else 0)
        + max(0, 30 - dias)
    )


def _candidatas_destacadas(categoria=None):
    desde = timezone.now() - timedelta(days=7)
    publicaciones = publicaciones_provinciales()
    if categoria:
        publicaciones = publicaciones.filter(temas__id_categoria__nombre_categoria=categoria)
    return publicaciones.defer('contenido').annotate(
        clics_recientes=Count('clics', filter=Q(clics__ultima_visita__gte=desde), distinct=True),
    ).order_by(Coalesce('fecha_publicacion', 'fecha_captura').desc(), '-pk')[:300]


def _elegir_destacadas(candidatas, limite):
    ordenadas = sorted(candidatas, key=lambda noticia: (_puntaje(noticia), _fecha(noticia), noticia.pk), reverse=True)
    elegidas = []
    titulos = set()
    for noticia in ordenadas:
        clave = slugify(noticia.titulo)
        if clave in titulos:
            continue
        titulos.add(clave)
        elegidas.append(noticia)
        if len(elegidas) == limite:
            break
    return elegidas


def noticias_destacadas(limite=15):
    return _elegir_destacadas(_candidatas_destacadas(), limite)


def noticias_destacadas_por_categoria(limite=15):
    return [
        {
            'nombre': nombre,
            'slug': slugify(nombre),
            'publicaciones': _elegir_destacadas(_candidatas_destacadas(nombre), limite),
        }
        for nombre in CATEGORIAS_PROYECTO
    ]


def tendencias_destacadas(limite=5):
    desde = timezone.now() - timedelta(days=7)
    mas_leidas = list(publicaciones_provinciales().annotate(
        clics_recientes=Count('clics', filter=Q(clics__ultima_visita__gte=desde)),
    ).filter(clics_recientes__gt=0).order_by('-clics_recientes', '-fecha_publicacion', '-pk')[:limite])
    if mas_leidas:
        return [{'publicacion': noticia, 'clics': noticia.clics_recientes, 'estimada': False} for noticia in mas_leidas]
    return [{'publicacion': noticia, 'clics': 0, 'estimada': True}
            for noticia in noticias_destacadas(limite)]


def registrar_clic(publicacion, usuario):
    """Cuenta lectores únicos recientes y relaciona sus temas con Trends."""
    if not usuario.is_authenticated or usuario.is_superuser:
        return False
    ahora = timezone.now()
    clic, nuevo = ClicPublicacion.objects.get_or_create(
        usuario=usuario, publicacion=publicacion, defaults={'ultima_visita': ahora},
    )
    if not nuevo and clic.ultima_visita < ahora - timedelta(days=1):
        ClicPublicacion.objects.filter(pk=clic.pk, ultima_visita__lt=ahora - timedelta(days=1)).update(
            ultima_visita=ahora,
        )
    if nuevo:
        temas = list(publicacion.temas.all())
        if temas:
            trend, _ = Trend.objects.get_or_create(relevancia='Lecturas', intervalos_periodo='7 días')
            for tema in temas:
                TemaTrend.objects.get_or_create(id_temas=tema, id_trends=trend)
    return nuevo
