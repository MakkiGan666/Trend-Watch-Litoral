import json
from contextlib import redirect_stdout

from django.core.management.base import BaseCommand, CommandError

from core.services.orquestador_multifuente import ejecutar_ingesta_multifuente


class Command(BaseCommand):
    help = 'Ingesta multifuente explícita y acotada; sólo fuentes habilitadas en el catálogo.'

    def add_arguments(self, parser):
        parser.add_argument('--fuente', action='append', required=True,
                            help='ID del catálogo; repetir para seleccionar varias fuentes.')
        parser.add_argument('--limite-fuente', type=int, default=3)
        parser.add_argument('--limite-total', type=int, default=10)
        parser.add_argument('--limite-ia', type=int, default=5)
        parser.add_argument('--dry-run', action='store_true', help='Descarga y valida sin escrituras ni Gemini.')
        grupo = parser.add_mutually_exclusive_group()
        grupo.add_argument('--con-ia', dest='procesar_ia', action='store_true')
        grupo.add_argument('--sin-ia', dest='procesar_ia', action='store_false')
        parser.set_defaults(procesar_ia=False)

    def handle(self, *args, **options):
        try:
            # Mensajes heredados de SDK/servicios van a stderr; stdout contiene sólo JSON.
            with redirect_stdout(self.stderr):
                resultado = ejecutar_ingesta_multifuente(
                    options['fuente'], limite_por_fuente=options['limite_fuente'],
                    limite_total=options['limite_total'], limite_ia=options['limite_ia'],
                    dry_run=options['dry_run'], procesar_ia=options['procesar_ia'])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
        if resultado['estado'] == 'FALLO':
            raise CommandError('Fallaron las fuentes seleccionadas; revisar el resumen JSON.')
