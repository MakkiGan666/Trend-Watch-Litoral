from django.core.management.base import BaseCommand

from core.models import Publicacion
from core.services.etiquetas import sincronizar_etiquetas


class Command(BaseCommand):
    help = 'Genera etiquetas para publicaciones existentes, por lotes reanudables.'

    def add_arguments(self, parser):
        parser.add_argument('--despues-de-id', type=int, default=0)
        parser.add_argument('--limite', type=int, default=200)
        parser.add_argument('--solo-sin-etiquetas', action='store_true')

    def handle(self, *args, **options):
        limite = options['limite']
        if limite < 1:
            self.stderr.write('El límite debe ser positivo.')
            return
        publicaciones = Publicacion.objects.filter(pk__gt=options['despues_de_id'])
        if options['solo_sin_etiquetas']:
            publicaciones = publicaciones.filter(etiquetas__isnull=True)
        publicaciones = list(publicaciones.order_by('pk')[:limite])
        total = sum(sincronizar_etiquetas(publicacion) for publicacion in publicaciones)
        cursor = publicaciones[-1].pk if publicaciones else options['despues_de_id']
        self.stdout.write(f'Publicaciones procesadas: {len(publicaciones)}. Etiquetas vinculadas: {total}. Cursor: {cursor}.')
