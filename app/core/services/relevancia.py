"""Selección regional y tendencias con señales verificables, sin IA."""
from datetime import timedelta
import re
import unicodedata

from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.text import slugify

from core.localidades import DEPARTAMENTOS
from core.models import ClicPublicacion, Comentario, Publicacion, ValoracionPublicacion
from core.services.clasificacion import CATEGORIAS_PROYECTO
from core.services.publicaciones_unicas import publicaciones_unicas


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
    publicaciones = publicaciones_provinciales().con_cuerpo_completo()
    if categoria:
        publicaciones = publicaciones.filter(temas__id_categoria__nombre_categoria=categoria)
    return publicaciones.defer('contenido').annotate(
        clics_recientes=Count('clics', filter=Q(clics__ultima_visita__gte=desde), distinct=True),
    ).order_by(Coalesce('fecha_publicacion', 'fecha_captura').desc(), '-pk')[:300]


def _elegir_destacadas(candidatas, limite):
    ordenadas = sorted(candidatas, key=lambda noticia: (_puntaje(noticia), _fecha(noticia), noticia.pk), reverse=True)
    return publicaciones_unicas(ordenadas, limite)


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


def _participacion_reciente():
    desde = timezone.now() - timedelta(days=7)
    desde_24h = timezone.now() - timedelta(hours=24)
    return Publicacion.objects.defer('contenido').annotate(
        positivos=Count('valoraciones', filter=Q(valoraciones__sentimiento=ValoracionPublicacion.Sentimiento.POSITIVO,
                                                  valoraciones__fecha_actualizacion__gte=desde), distinct=True),
        neutrales=Count('valoraciones', filter=Q(valoraciones__sentimiento=ValoracionPublicacion.Sentimiento.NEUTRAL,
                                                 valoraciones__fecha_actualizacion__gte=desde), distinct=True),
        negativos=Count('valoraciones', filter=Q(valoraciones__sentimiento=ValoracionPublicacion.Sentimiento.NEGATIVO,
                                                 valoraciones__fecha_actualizacion__gte=desde), distinct=True),
        comentaristas=Count('comentarios__autor', filter=Q(comentarios__estado=Comentario.Estado.PUBLICADO,
                                                            comentarios__fecha_creacion__gte=desde,
                                                            comentarios__autor__isnull=False), distinct=True),
        positivos_24h=Count('valoraciones', filter=Q(valoraciones__sentimiento=ValoracionPublicacion.Sentimiento.POSITIVO,
                                                      valoraciones__fecha_actualizacion__gte=desde_24h), distinct=True),
        neutrales_24h=Count('valoraciones', filter=Q(valoraciones__sentimiento=ValoracionPublicacion.Sentimiento.NEUTRAL,
                                                     valoraciones__fecha_actualizacion__gte=desde_24h), distinct=True),
        negativos_24h=Count('valoraciones', filter=Q(valoraciones__sentimiento=ValoracionPublicacion.Sentimiento.NEGATIVO,
                                                     valoraciones__fecha_actualizacion__gte=desde_24h), distinct=True),
        comentaristas_24h=Count('comentarios__autor', filter=Q(comentarios__estado=Comentario.Estado.PUBLICADO,
                                                                comentarios__fecha_creacion__gte=desde_24h,
                                                                comentarios__autor__isnull=False), distinct=True),
    )


def _con_participacion():
    return _participacion_reciente().filter(
        Q(positivos__gt=0) | Q(neutrales__gt=0) | Q(negativos__gt=0) | Q(comentaristas__gt=0)
    )


def tendencias_destacadas(limite=10):
    # Una valoración vigente y un comentarista publicado suman una participación
    # cada uno. Priorizamos su velocidad reciente; los clics no intervienen.
    candidatas = list(_con_participacion().order_by('-fecha_publicacion', '-pk'))
    def ritmo(publicacion):
        total = publicacion.positivos + publicacion.neutrales + publicacion.negativos + publicacion.comentaristas
        ultimas_24h = (publicacion.positivos_24h + publicacion.neutrales_24h
                       + publicacion.negativos_24h + publicacion.comentaristas_24h)
        anteriores = total - ultimas_24h
        return (ultimas_24h * 6 / (anteriores + 1), ultimas_24h, total)

    candidatas = [p for p in candidatas if ritmo(p)[1] >= 2]
    candidatas.sort(key=lambda p: (*ritmo(p), _fecha(p), p.pk), reverse=True)
    elegidas = publicaciones_unicas(candidatas, limite)
    resultado = [{'publicacion': p, 'participaciones': p.positivos + p.neutrales + p.negativos + p.comentaristas,
                  'estimada': False} for p in elegidas]
    usadas = {p.pk for p in elegidas}
    for tendencia in _cobertura_creciente(limite):
        if tendencia['publicacion'].pk in usadas:
            continue
        resultado.append(tendencia)
        usadas.add(tendencia['publicacion'].pk)
        if len(resultado) == limite:
            break
    return resultado


ETIQUETAS_GENERICAS = {
    'misiones', 'argentina', 'nacional', 'provincia', 'ciudad', 'posadas',
    'iguazu', 'eldorado', 'personas', 'familias', 'situacion', 'actividad',
    'jornada', 'inicio', 'empresa', 'trabajo', 'presidente', 'gobierno',
    'noticia', 'noticias', 'salud', 'politica', 'policia', 'vecinos',
    'uruguay', 'paraguay', 'brasil', 'escenario', 'alimentos',
}
MUNICIPIOS_MISIONES = {slugify(nombre) for departamento in DEPARTAMENTOS for nombre in departamento['municipios']}
TEMAS_CONCRETOS_DE_UNA_PALABRA = {
    'crecida', 'tornado', 'inundacion', 'incendio', 'elecciones',
    'dengue', 'desalojo', 'rescate', 'sismo', 'derrumbe',
}


def _cobertura_creciente(limite):
    """Señal editorial interna: varias notas sobre el mismo tema en 24 horas."""
    ahora = timezone.now()
    desde_24h = ahora - timedelta(hours=24)
    desde_7d = ahora - timedelta(days=7)
    publicaciones = publicaciones_provinciales().con_cuerpo_completo().filter(
        Q(fecha_publicacion__gte=desde_7d)
        | Q(fecha_publicacion__isnull=True, fecha_captura__gte=desde_7d)
    ).prefetch_related('etiquetas__etiqueta').order_by(Coalesce('fecha_publicacion', 'fecha_captura').desc(), '-pk')
    temas = {}
    prefijos = set()
    for publicacion in publicaciones_unicas(publicaciones):
        fecha = _fecha(publicacion)
        if fecha > ahora:
            continue
        palabras_titulo = _palabras_normales(publicacion.titulo)
        prefijo = tuple(palabras_titulo[:7]) if len(palabras_titulo) >= 7 else None
        if prefijo and prefijo in prefijos:
            continue
        if prefijo:
            prefijos.add(prefijo)
        titulo_slug = slugify(publicacion.titulo)
        for relacion in publicacion.etiquetas.all():
            etiqueta = relacion.etiqueta
            if (etiqueta.slug in ETIQUETAS_GENERICAS or etiqueta.slug in SLUGS_MISIONES
                    or etiqueta.slug in MUNICIPIOS_MISIONES or etiqueta.slug not in titulo_slug):
                continue
            if '-' not in etiqueta.slug and etiqueta.slug not in TEMAS_CONCRETOS_DE_UNA_PALABRA:
                continue
            grupo = temas.setdefault(etiqueta.slug, {'nombre': etiqueta.nombre, 'recientes': [], 'anteriores': []})
            grupo['recientes' if fecha >= desde_24h else 'anteriores'].append(publicacion)

    ordenados = []
    for grupo in temas.values():
        recientes = len(grupo['recientes'])
        anteriores = len(grupo['anteriores'])
        if recientes < 2 or recientes <= anteriores / 6:
            continue
        velocidad = recientes * (recientes + 1) / (1 + anteriores / 6)
        ordenados.append((velocidad, recientes, _fecha(grupo['recientes'][0]), grupo))
    ordenados.sort(key=lambda item: item[:3], reverse=True)

    elegidas = []
    usadas = set()
    for _, recientes, _, grupo in ordenados:
        publicacion = next((p for p in grupo['recientes'] if p.pk not in usadas), None)
        if publicacion is None:
            continue
        usadas.add(publicacion.pk)
        elegidas.append({'publicacion': publicacion, 'participaciones': 0, 'estimada': True,
                         'cobertura': True, 'tema': grupo['nombre'], 'publicaciones_24h': recientes})
        if len(elegidas) == limite:
            return elegidas
    for _, recientes, _, grupo in ordenados:
        for publicacion in grupo['recientes']:
            if publicacion.pk in usadas:
                continue
            usadas.add(publicacion.pk)
            elegidas.append({'publicacion': publicacion, 'participaciones': 0, 'estimada': True,
                             'cobertura': True, 'tema': grupo['nombre'], 'publicaciones_24h': recientes})
            if len(elegidas) == limite:
                return elegidas

    # Si aún faltan lugares, se muestran temas con varias notas en siete días.
    # Son una vista previa editorial: no se presentan como crecimiento verificado.
    temas_en_crecimiento = {id(grupo) for _, _, _, grupo in ordenados}
    otros = [grupo for grupo in temas.values()
             if id(grupo) not in temas_en_crecimiento
             and len(grupo['recientes']) + len(grupo['anteriores']) >= 2]
    otros.sort(key=lambda grupo: (len(grupo['recientes']),
                                   len(grupo['recientes']) + len(grupo['anteriores']),
                                   _fecha((grupo['recientes'] + grupo['anteriores'])[0])), reverse=True)
    for grupo in otros:
        publicacion = next((p for p in grupo['recientes'] + grupo['anteriores'] if p.pk not in usadas), None)
        if publicacion is None:
            continue
        usadas.add(publicacion.pk)
        elegidas.append({'publicacion': publicacion, 'participaciones': 0, 'estimada': True,
                         'previa': True, 'tema': grupo['nombre'],
                         'publicaciones_7d': len(grupo['recientes']) + len(grupo['anteriores'])})
        if len(elegidas) == limite:
            return elegidas
    for grupo in otros:
        for publicacion in grupo['recientes'] + grupo['anteriores']:
            if publicacion.pk in usadas:
                continue
            usadas.add(publicacion.pk)
            elegidas.append({'publicacion': publicacion, 'participaciones': 0, 'estimada': True,
                             'previa': True, 'tema': grupo['nombre'],
                             'publicaciones_7d': len(grupo['recientes']) + len(grupo['anteriores'])})
            if len(elegidas) == limite:
                return elegidas
    return elegidas


def rankings_valoraciones(limite=15):
    candidatas = list(_con_participacion().order_by('-fecha_publicacion', '-pk'))
    # Mínimos de participación evitan que una sola valoración defina el ranking.
    positivas = [p for p in candidatas if p.positivos >= 3]
    positivas.sort(key=lambda p: (p.positivos / (p.positivos + p.neutrales + p.negativos),
                                  p.positivos, _fecha(p), p.pk), reverse=True)
    polemicas = [p for p in candidatas if p.positivos >= 2 and p.negativos >= 2]
    polemicas.sort(key=lambda p: (min(p.positivos, p.negativos) * 2 + p.comentaristas,
                                  p.positivos + p.negativos + p.neutrales, _fecha(p), p.pk), reverse=True)
    return publicaciones_unicas(positivas, limite), publicaciones_unicas(polemicas, limite)


SENALES_POSITIVAS = (
    'solidarid', 'esperanz', 'superacion', 'rescat', 'recuper', 'logr',
    'avance', 'historico', 'benefici', 'mejor', 'cura', 'donac', 'ayud',
    'voluntari', 'inaugur', 'comunitari', 'altru', 'salv', 'triunf',
)
SENALES_POSITIVAS_FUERTES = (
    'solidarid', 'esperanz', 'superacion', 'rescat', 'recuper', 'cura',
    'donac', 'ayud', 'voluntari', 'comunitari', 'altru', 'salv',
    'cientific', 'vacun',
)
SENALES_CONFLICTO = ('contra', 'oposicion', 'derecha', 'izquierda', 'balotaje',
                     'golpe', 'muerte', 'homicidio', 'corrupcion', 'guerra')
SENALES_POLEMICAS = (
    'polem', 'debate', 'critic', 'rechaz', 'cuestion', 'denunci', 'acus',
    'indign', 'escandal', 'controvers', 'disputa', 'enfrent', 'conflict',
    'protest', 'reclam', 'veto', 'reforma', 'desafi', 'censur', 'corrup',
    'estalla', 'tension',
)


def _palabras_normales(texto):
    normalizado = unicodedata.normalize('NFKD', texto or '').casefold()
    normalizado = ''.join(letra for letra in normalizado if not unicodedata.combining(letra))
    return re.findall(r'[a-z]+', normalizado)


def _senales(palabras, raices):
    return sum(any(palabra.startswith(raiz) for palabra in palabras) for raiz in raices)


def _puntaje_previa(publicacion, tipo):
    titulo = _palabras_normales(publicacion.titulo)
    cuerpo = _palabras_normales((publicacion.contenido or '')[:1800])
    propias = SENALES_POSITIVAS if tipo == 'positivo' else SENALES_POLEMICAS
    contrarias = SENALES_POLEMICAS if tipo == 'positivo' else SENALES_POSITIVAS
    senales_titulo = _senales(titulo, propias)
    if not senales_titulo:
        return 0
    senales_opuestas = _senales(titulo, contrarias)
    if tipo == 'positivo':
        if not _senales(titulo, SENALES_POSITIVAS_FUERTES):
            return 0
        if senales_opuestas >= senales_titulo or _senales(titulo, SENALES_CONFLICTO):
            return 0
    return 4 * senales_titulo + min(_senales(cuerpo, propias), 3)


def ejemplos_rankings(limite=15):
    """Vista previa por contenido; nunca atribuye votos o reacciones inexistentes."""
    # Leemos primero sólo títulos: el texto completo se consulta para las
    # candidatas, evitando cargar miles de artículos en cada visita.
    titulos = Publicacion.objects.con_cuerpo_completo().values_list(
        'pk', 'titulo', 'fecha_publicacion', 'fecha_captura'
    )
    candidatas = {'positivo': [], 'polemico': []}
    for pk, titulo, fecha_publicacion, fecha_captura in titulos.iterator(chunk_size=500):
        palabras = _palabras_normales(titulo)
        fecha = fecha_publicacion or fecha_captura
        for tipo, raices in (('positivo', SENALES_POSITIVAS), ('polemico', SENALES_POLEMICAS)):
            if _senales(palabras, raices):
                candidatas[tipo].append((fecha, pk))

    ids = {pk for registros in candidatas.values() for _, pk in sorted(registros, reverse=True)[:200]}
    publicaciones = Publicacion.objects.in_bulk(ids)

    def seleccionar(tipo):
        puntuadas = (
            (_puntaje_previa(publicaciones[pk], tipo), fecha, pk)
            for fecha, pk in sorted(candidatas[tipo], reverse=True)[:200]
        )
        ordenadas = (publicaciones[pk] for puntaje, _, pk in sorted(puntuadas, reverse=True) if puntaje)
        return publicaciones_unicas(ordenadas, limite)

    return seleccionar('positivo'), seleccionar('polemico')


def registrar_clic(publicacion, usuario):
    """Conserva la lectura única por usuario sin alterar las tendencias."""
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
    return nuevo
