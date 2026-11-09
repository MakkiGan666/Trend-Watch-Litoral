import json

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from core.services.persistencia_rss_metadatos import resolver_bloqueo_pendiente


class Command(BaseCommand):
    help = 'Resuelve manualmente una reserva RSS pendiente; no realiza solicitudes HTTP.'

    def add_arguments(self, parser):
        parser.add_argument('--fuente', required=True, help='ID exacto de fuente H1.1.')
        parser.add_argument(
            '--confirmar-revision-manual', action='store_true',
            help=('Confirma que se verificaron la interrupción, Retry-After y las condiciones de acceso; '
                  'la fuente seguirá esperando un intervalo completo.'),
        )
        parser.add_argument(
            '--confirmar-retry-after-vencido', action='store_true',
            help=('Para bloqueos REVISION_MANUAL por un Retry-After excesivo: confirma que el plazo '
                  'original ya venció. No se habilita antes de esa confirmación.'),
        )

    def handle(self, *args, **options):
        try:
            resultado = resolver_bloqueo_pendiente(
                options['fuente'],
                confirmar_revision_manual=options['confirmar_revision_manual'],
                confirmar_retry_after_vencido=options['confirmar_retry_after_vencido'],
            )
        except (ValueError, ImproperlyConfigured) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
