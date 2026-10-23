from html.parser import HTMLParser
from http.client import HTTPException
from urllib.parse import urljoin

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from core.models import Publicacion
from core.services.descarga_segura import descargar, validar_url
from core.services.scraper import _imagen_valida


class MetadatosImagen(HTMLParser):
    def __init__(self):
        super().__init__()
        self.imagenes = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'meta':
            return
        data = dict(attrs)
        key = (data.get('property') or data.get('name') or '').lower()
        if key in ('og:image', 'twitter:image', 'twitter:image:src') and data.get('content'):
            self.imagenes.setdefault(key, data['content'].strip())


class Command(BaseCommand):
    help = 'Recupera fotos faltantes de Policiales sin reingestar noticias. Por defecto sólo simula.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true')
        parser.add_argument('--limite', type=int, default=10)
        parser.add_argument('--despues-de-id', type=int, default=0,
                            help='Continúa con PK mayores al cursor del lote anterior.')

    def handle(self, *args, **options):
        if not 1 <= options['limite'] <= 100:
            raise CommandError('--limite debe estar entre 1 y 100.')
        cursor = options['despues_de_id']
        if cursor < 0:
            raise CommandError('--despues-de-id debe ser mayor o igual a cero.')
        pendientes = Publicacion.objects.filter(
            fuente__icontains='Policiales', imagen_url='', pk__gt=cursor,
        ).filter(Q(imagen_archivo='') | Q(imagen_archivo__isnull=True)).order_by('pk')
        lote = list(pendientes[:options['limite'] + 1])
        hay_mas = len(lote) > options['limite']
        actualizadas = intentadas = errores = 0
        for noticia in lote[:options['limite']]:
            cursor = noticia.pk
            intentadas += 1
            try:
                validar_url(noticia.url)
                documento = descargar(noticia.url, timeout=15)
                meta = MetadatosImagen()
                meta.feed(documento.decode('utf-8', errors='replace'))
                imagen = ''
                for key in ('og:image', 'twitter:image', 'twitter:image:src'):
                    if meta.imagenes.get(key):
                        imagen = _imagen_valida(urljoin(noticia.url, meta.imagenes[key]))
                        if imagen:
                            break
                if not imagen:
                    self.stdout.write(f'#{noticia.pk}: sin imagen original disponible.')
                    continue
            except (OSError, ValueError, HTTPException) as error:
                errores += 1
                self.stderr.write(f'#{noticia.pk}: no se pudo recuperar ({type(error).__name__}).')
                continue
            if options['aplicar']:
                actualizadas += Publicacion.objects.filter(
                    pk=noticia.pk, url=noticia.url, imagen_url='',
                ).filter(Q(imagen_archivo='') | Q(imagen_archivo__isnull=True)).update(imagen_url=imagen)
            self.stdout.write(f'#{noticia.pk}: imagen encontrada' + (' (aplicada si sigue vacía).' if options['aplicar'] else ' (simulación).'))
        self.stdout.write(f'Actualizadas: {actualizadas}. No se modificaron otros campos.')
        self.stdout.write(f'Intentadas: {intentadas}. Errores: {errores}. Cursor: {cursor}.')
        if hay_mas:
            self.stdout.write(f'Hay más candidatos. Continuar con --despues-de-id={cursor} y los mismos --limite/--aplicar.')
        else:
            self.stdout.write('Fin del conjunto de candidatos posterior al cursor inicial.')
