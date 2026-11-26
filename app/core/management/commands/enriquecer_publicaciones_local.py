import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.services.enriquecimiento_local import aplicar, lote_pendiente, simular
from core.services.lotes_enriquecimiento_local import LoteInvalido, aplicar_lote_exacto, simular_lote_exacto


def _lista_ids(valor):
    try:
        return [int(pk) for pk in valor.split(',')]
    except ValueError as error:
        raise LoteInvalido('Indicá los IDs separados por comas.') from error


def _sin_claves_repetidas(pares):
    resultado = dict(pares)
    if len(resultado) != len(pares):
        raise LoteInvalido('El manifiesto contiene claves JSON repetidas.')
    return resultado


class Command(BaseCommand):
    help = 'Completa clasificación temática y etiquetas locales. Simula por defecto.'

    def add_arguments(self, parser):
        parser.add_argument('--despues-de-id', type=int)
        parser.add_argument('--limite', type=int)
        seleccion = parser.add_mutually_exclusive_group()
        seleccion.add_argument('--ids', help='IDs exactos separados por comas para generar un manifiesto.')
        seleccion.add_argument('--manifiesto', type=Path, help='Archivo JSON aprobado para aplicar.')
        parser.add_argument('--excluir-ids', help='IDs que deben quedar fuera de la selección explícita.')
        parser.add_argument('--sha256', help='SHA-256 aprobado y guardado por separado del manifiesto.')
        modo = parser.add_mutually_exclusive_group()
        modo.add_argument('--aplicar', action='store_true')
        modo.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if options['ids'] is not None or options['manifiesto'] is not None:
            try:
                self._ejecutar_exacto(options)
            except (ValueError, OSError, RecursionError) as error:
                raise CommandError(str(error)) from error
            return
        if options['excluir_ids'] is not None or options['sha256'] is not None:
            raise CommandError('Las exclusiones y el SHA-256 requieren el modo de selección explícita.')
        cursor = options['despues_de_id'] if options['despues_de_id'] is not None else 0
        limite = options['limite'] if options['limite'] is not None else 100
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


    def _ejecutar_exacto(self, options):
        if options['limite'] is not None or options['despues_de_id'] is not None:
            raise LoteInvalido('El modo exacto no admite cursor ni límite.')
        if options['ids'] is not None:
            if options['aplicar'] or options['sha256'] is not None:
                raise LoteInvalido('Para aplicar un lote exacto, usá un manifiesto revisado y su SHA-256.')
            excluidos = options['excluir_ids']
            resultado = simular_lote_exacto(
                _lista_ids(options['ids']), [] if excluidos is None else _lista_ids(excluidos),
            )
        else:
            if not options['aplicar'] or not options['sha256'] or options['excluir_ids'] is not None:
                raise LoteInvalido('La aplicación requiere --aplicar, --manifiesto y --sha256 aprobado.')
            with options['manifiesto'].open(encoding='utf-8') as archivo:
                manifiesto = json.load(archivo, object_pairs_hook=_sin_claves_repetidas)
            resultado = aplicar_lote_exacto(manifiesto, options['sha256'])
        self.stdout.write(json.dumps(resultado, ensure_ascii=False))
