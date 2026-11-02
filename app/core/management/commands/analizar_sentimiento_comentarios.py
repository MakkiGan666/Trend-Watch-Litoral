"""Comando idempotente para analizar el sentimiento de los comentarios.

Se puede correr tantas veces como se quiera: no reanaliza un comentario cuyo
texto no cambió desde el último análisis, salvo que se pase `--reanalizar`.
El procesamiento es independiente de las peticiones HTTP de los usuarios
(ver `core/services/sentimiento_comentarios.py`).
"""
from django.core.management.base import BaseCommand, CommandError

from core.services.sentimiento_comentarios import (
    METODO_IA,
    METODO_LEXICON,
    SentimientoNoDisponible,
    analizar_comentario,
    candidatos_con_hash_desactualizado,
    candidatos_sin_analisis_validos,
    registrar_error_analisis,
)


class Command(BaseCommand):
    help = (
        'Analiza el sentimiento de los comentarios pendientes. '
        'Es idempotente: omite los que ya tienen un análisis vigente.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--limite', type=int, default=200,
                            help='Máximo de comentarios a procesar en esta corrida (0 = sin límite).')
        parser.add_argument('--reanalizar', action='store_true',
                            help='Reanaliza también los comentarios ya procesados cuyo texto no cambió.')
        parser.add_argument('--metodo', choices=(METODO_LEXICON, METODO_IA), default=METODO_LEXICON,
                            help='Método preferido. Si falla el IA, cae al léxico y lo registra.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Muestra qué se procesaría, sin escribir en la base.')

    def handle(self, *args, **options):
        limite = options['limite']
        if limite < 0:
            raise CommandError('--limite debe ser >= 0.')
        reanalizar = options['reanalizar']
        usar_ia = options['metodo'] == METODO_IA
        dry_run = options['dry_run']

        candidatos = self._candidatos(reanalizar=reanalizar, limite=limite)
        procesados, actualizados, omitidos, fallidos = 0, 0, 0, 0

        for comentario in candidatos:
            if dry_run:
                self.stdout.write(f'[dry-run] comentario #{comentario.pk}')
                procesados += 1
                continue
            try:
                _, accion = analizar_comentario(
                    comentario, usar_ia=usar_ia, forzar=reanalizar,
                )
            except SentimientoNoDisponible as exc:
                registrar_error_analisis(comentario, exc.codigo)
                fallidos += 1
                continue
            except Exception as exc:  # noqa: BLE001
                # Un error inesperado se registra y sigue el lote; no se propaga para
                # no detener el proceso en segundo plano. Se audita en el log de Django.
                self.stderr.write(f'comentario #{comentario.pk}: {exc!r}')
                registrar_error_analisis(comentario, 'excepcion_inesperada')
                fallidos += 1
                continue
            if accion == 'creado':
                procesados += 1
            elif accion == 'actualizado':
                actualizados += 1
            else:
                omitidos += 1

        resumen = (f'procesados={procesados} actualizados={actualizados} '
                   f'omitidos={omitidos} fallidos={fallidos}')
        self.stdout.write(self.style.SUCCESS(resumen) if not fallidos else resumen)

    def _candidatos(self, reanalizar, limite):
        """Itera primero los comentarios sin análisis válido y luego los desactualizados.

        Si `reanalizar=True` abarca todos (incluidos los que están al día), lo que
        permite recorrer la tabla completa cuando cambia el método o la versión.
        """
        if reanalizar:
            from core.models import Comentario

            # Un solo recorrido: incluye nuevos, errores, editados y vigentes,
            # sin volver a emitir los ya procesados durante esta corrida.
            qs = Comentario.objects.select_related('sentimiento').order_by('pk')
            if limite:
                qs = qs[:limite]
            yield from qs.iterator(chunk_size=200)
            return

        pendientes = candidatos_sin_analisis_validos().order_by('pk')
        if limite:
            pendientes = pendientes[:limite]
        emitidos = 0
        for comentario in pendientes:
            yield comentario
            emitidos += 1

        restante = (limite - emitidos) if limite else None
        if restante is not None and restante <= 0:
            return

        for comentario in candidatos_con_hash_desactualizado():
            if restante is not None and emitidos >= limite:
                return
            yield comentario
            emitidos += 1
