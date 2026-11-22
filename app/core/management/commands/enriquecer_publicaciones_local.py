import json

from django.core.management.base import BaseCommand, CommandError

from core.services.enriquecimiento_local import aplicar, lote_pendiente, simular


class Command(BaseCommand):
    help = 'Completa clasificación temática y etiquetas locales. Simula por defecto.'

    def add_arguments(self, parser):
        parser.add_argument('--despues-de-id', type=int, default=0)
        parser.add_argument('--limite', type=int, default=100)
        modo = parser.add_mutually_exclusive_group()
        modo.add_argument('--aplicar', action='store_true')
        modo.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        cursor = options['despues_de_id']
        limite = options['limite']
        if cursor < 0 or not 1 <= limite <= 1000:
            raise CommandError('El cursor debe ser no negativo y el límite debe estar entre 1 y 1000.')

        dry_run = not options['aplicar']
        publicaciones, hay_mas = lote_pendiente(cursor, limite)
        resultados = []
        for publicacion in publicaciones:
            try:
                resultado = simular(publicacion) if dry_run else aplicar(publicacion.pk)
            except Exception as error:
                self.stdout.write(json.dumps({
                    'dry_run': dry_run, 'cursor': cursor, 'hay_mas': True, 'resultados': resultados,
                }, ensure_ascii=False))
                raise CommandError(
                    f'Falló la publicación {publicacion.pk}. Reanudar con --despues-de-id {cursor}.'
                ) from error
            resultados.append(resultado)
            cursor = publicacion.pk
        self.stdout.write(json.dumps({
            'dry_run': dry_run, 'cursor': cursor, 'hay_mas': hay_mas, 'resultados': resultados,
        }, ensure_ascii=False))
