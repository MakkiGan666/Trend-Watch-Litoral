import json

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.services.agrupacion_automatica import (
    MAX_CANDIDATOS_PREVISUALIZACION,
    aplicar_candidato_automatico,
    previsualizar_candidatos,
)


class Command(BaseCommand):
    help = 'Evalúa candidatos editoriales o agrupa sólo los que cumplen una regla estricta.'
    requires_system_checks = []

    def add_arguments(self, parser):
        modos = parser.add_mutually_exclusive_group(required=True)
        modos.add_argument('--dry-run', action='store_true', help='Informa elegibilidad sin escribir.')
        modos.add_argument('--aplicar', action='store_true', help='Aplica la regla; requiere el gate operativo activo.')
        parser.add_argument('--limite', type=int, default=MAX_CANDIDATOS_PREVISUALIZACION)
        parser.add_argument('--fuente', default='', help='Filtra por fuente editorial normalizada.')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('La operación requiere PostgreSQL.')
        limite = options['limite']
        if type(limite) is not int or not 1 <= limite <= MAX_CANDIDATOS_PREVISUALIZACION:
            raise CommandError(f'--limite debe estar entre 1 y {MAX_CANDIDATOS_PREVISUALIZACION}.')
        if options['aplicar'] and not settings.AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA:
            raise CommandError('La agrupación editorial automática está deshabilitada por configuración.')

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            evaluaciones = previsualizar_candidatos(limite=limite, fuente=options['fuente'])

        if options['dry_run']:
            resultados = evaluaciones
            modo = 'dry-run'
        else:
            resultados = []
            for evaluacion in evaluaciones:
                if not evaluacion['elegible']:
                    resultados.append(evaluacion)
                    continue
                try:
                    resultados.append(aplicar_candidato_automatico(evaluacion['candidato_id']))
                except PermissionDenied as error:
                    raise CommandError(str(error)) from error
            modo = 'aplicacion'

        resumen = {}
        for resultado in resultados:
            clave = resultado.get('motivo', 'SIN_MOTIVO')
            resumen[clave] = resumen.get(clave, 0) + 1
        salida = {
            'modo': modo,
            'version_regla': 'auto-editorial-exacto-v1',
            'limite': limite,
            'fuente': options['fuente'] or None,
            'evaluados': len(resultados),
            'elegibles': sum(bool(r.get('elegible', r.get('creado'))) for r in resultados),
            'creados': sum(bool(r.get('creado')) for r in resultados),
            'por_motivo': dict(sorted(resumen.items())),
            'resultados': resultados,
        }
        self.stdout.write(json.dumps(salida, ensure_ascii=False, sort_keys=True, default=str))
