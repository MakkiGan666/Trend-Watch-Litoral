import json

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from core.services.lotes_rss_metadatos import (
    consultar_trabajo,
    iniciar_lote,
    pausar_trabajo,
    recuperar_trabajo,
    reanudar_trabajo,
)


class Command(BaseCommand):
    help = 'Administra trabajos RSS reanudables con snapshot limitado a metadatos.'

    def add_arguments(self, parser):
        acciones = parser.add_mutually_exclusive_group(required=True)
        acciones.add_argument('--iniciar', action='store_true', help='Consulta una vez el feed y crea el snapshot.')
        acciones.add_argument('--estado', type=int, metavar='ID', help='Consulta el estado sin solicitar el feed.')
        acciones.add_argument('--pausar', type=int, metavar='ID', help='Pausa un trabajo entre checkpoints.')
        acciones.add_argument('--reanudar', type=int, metavar='ID', help='Procesa el siguiente lote del snapshot guardado.')
        acciones.add_argument('--recuperar', type=int, metavar='ID', help='Desbloquea un ejecutor detenido; no consulta el feed.')
        parser.add_argument('--fuente', help='ID exacto del catálogo; requerido al iniciar.')
        parser.add_argument('--tamano-lote', type=int, default=1, help='Entradas por llamada, entre 1 y 5.')
        parser.add_argument('--confirmar-persistencia', action='store_true')
        parser.add_argument(
            '--confirmar-ejecutor-detenido', action='store_true',
            help='Confirma que no existe otro proceso ejecutando el trabajo.',
        )

    def handle(self, *args, **options):
        try:
            if options['iniciar']:
                if not options['fuente']:
                    raise CommandError('--fuente es obligatorio con --iniciar.')
                resultado = iniciar_lote(
                    options['fuente'], tamano_lote=options['tamano_lote'],
                    confirmar_persistencia=options['confirmar_persistencia'],
                )
            elif options['estado'] is not None:
                resultado = consultar_trabajo(options['estado'])
            elif options['pausar'] is not None:
                resultado = pausar_trabajo(options['pausar'])
            elif options['reanudar'] is not None:
                resultado = reanudar_trabajo(
                    options['reanudar'],
                    confirmar_persistencia=options['confirmar_persistencia'],
                )
            else:
                resultado = recuperar_trabajo(
                    options['recuperar'],
                    confirmar_ejecutor_detenido=options['confirmar_ejecutor_detenido'],
                )
        except (ValueError, ImproperlyConfigured) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
        if resultado['estado'] == 'FALLIDO':
            raise CommandError('El trabajo terminó sin snapshot procesable; revisar estado y control H5.6.')
