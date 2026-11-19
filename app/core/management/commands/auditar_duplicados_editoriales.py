import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.services.duplicados_editoriales import detectar_candidatos, normalizar_fuente, normalizar_texto


class Command(BaseCommand):
    help = 'Genera candidatos editoriales en modo estrictamente de solo lectura.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Obligatorio: no existe modo de escritura.')
        parser.add_argument('--fuente', help='Limita el análisis a una fuente normalizada.')
        parser.add_argument('--etiqueta-fuente', help='Limita a la etiqueta de fuente exacta almacenada.')
        parser.add_argument('--titulo-minimo', type=int, default=35)

    def handle(self, *args, **options):
        if not options['dry_run']:
            raise CommandError('Este comando sólo admite --dry-run.')
        if options['titulo_minimo'] < 1:
            raise CommandError('--titulo-minimo debe ser positivo.')
        if connection.vendor != 'postgresql':
            raise CommandError('El análisis requiere PostgreSQL para imponer una transacción READ ONLY.')

        from core.models import Publicacion

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            registros = list(
                Publicacion.objects.order_by('pk').values(
                    'pk', 'fuente', 'titulo', 'url', 'fecha_publicacion',
                    'contenido', 'contenido_completo',
                )
            )
            registros = [
                fila for fila in registros
                if len(str(fila['titulo'] or '')) >= options['titulo_minimo']
                and (not options['fuente'] or normalizar_fuente(fila['fuente']) == normalizar_fuente(options['fuente']))
                and (not options['etiqueta_fuente'] or fila['fuente'] == options['etiqueta_fuente'])
            ]
            candidatos = detectar_candidatos(registros)

        resumen = {}
        for candidato in candidatos:
            resumen[candidato['estado']] = resumen.get(candidato['estado'], 0) + 1
        self.stdout.write(json.dumps({
            'modo': 'dry-run',
            'registros_evaluados': len(registros),
            'candidatos': len(candidatos),
            'por_estado': dict(sorted(resumen.items())),
            'resultados': candidatos,
        }, ensure_ascii=False, sort_keys=True, default=str))
