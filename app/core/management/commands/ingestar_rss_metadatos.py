import json

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from core.services.persistencia_rss_metadatos import persistir_metadatos_rss


class Command(BaseCommand):
    help = 'Persiste únicamente metadatos RSS de una fuente autorizada; no descarga artículos.'

    def add_arguments(self, parser):
        parser.add_argument('--fuente', required=True, help='ID exacto de una fuente del catálogo H1.1.')
        parser.add_argument('--limite', type=int, default=1, help='Máximo de entradas (1 a 5).')
        parser.add_argument(
            '--confirmar-persistencia', action='store_true',
            help='Confirma esta ejecución; no habilita fuentes ni el pipeline completo.',
        )

    def handle(self, *args, **options):
        try:
            resultado = persistir_metadatos_rss(
                options['fuente'],
                limite=options['limite'],
                confirmar_persistencia=options['confirmar_persistencia'],
            )
        except (ValueError, ImproperlyConfigured) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
        if resultado['estado'] == 'ERROR':
            raise CommandError('No se pudo completar la consulta RSS; revisar las causas del resumen.')
        if resultado['estado'] == 'PARCIAL':
            raise CommandError('La ejecución fue parcial; revisar las causas del resumen.')
