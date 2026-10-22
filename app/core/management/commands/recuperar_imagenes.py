from html.parser import HTMLParser
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

    def handle(self, *args, **options):
        if not 1 <= options['limite'] <= 100:
            raise CommandError('--limite debe estar entre 1 y 100.')
        pendientes = Publicacion.objects.filter(
            fuente__icontains='Policiales', imagen_url='',
        ).filter(Q(imagen_archivo='') | Q(imagen_archivo__isnull=True)).order_by('pk')[:options['limite']]
        actualizadas = 0
        for noticia in pendientes:
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
                if options['aplicar']:
                    actualizadas += Publicacion.objects.filter(
                        pk=noticia.pk, url=noticia.url, imagen_url='',
                    ).filter(Q(imagen_archivo='') | Q(imagen_archivo__isnull=True)).update(imagen_url=imagen)
                self.stdout.write(f'#{noticia.pk}: imagen encontrada' + (' (aplicada si sigue vacía).' if options['aplicar'] else ' (simulación).'))
            except (OSError, ValueError) as error:
                self.stderr.write(f'#{noticia.pk}: no se pudo recuperar ({type(error).__name__}).')
        self.stdout.write(f'Actualizadas: {actualizadas}. No se modificaron otros campos.')
