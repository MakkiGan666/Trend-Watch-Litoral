"""Consulta periódica de RSS de El Territorio sin bloquear el servidor web."""
import time

from django.core.management.base import BaseCommand

from core.services.scraper import CATEGORIAS_TERRITORIO, fetch_and_store_elterritorio


class Command(BaseCommand):
    help = 'Revisa todos los RSS de El Territorio cada cinco minutos e ingesta novedades.'

    def add_arguments(self, parser):
        parser.add_argument('--una-vez', action='store_true', help='Ejecuta una revisión y termina.')
        parser.add_argument('--intervalo', type=int, default=300, help='Segundos entre revisiones (mínimo 60).')
        parser.add_argument('--con-ia', action='store_true', help='Clasifica casos dudosos mediante IA.')

    def handle(self, *args, **options):
        intervalo = options['intervalo']
        if intervalo < 60:
            from django.core.management.base import CommandError
            raise CommandError('El intervalo mínimo es 60 segundos.')
        while True:
            inicio = time.monotonic()
            nuevas = 0
            self.stdout.write('Iniciando revisión de RSS de El Territorio.')
            for nombre in CATEGORIAS_TERRITORIO:
                try:
                    self.stdout.write(f'Revisando RSS {nombre}...')
                    resultado = fetch_and_store_elterritorio(nombre, limit=200, usar_ia=options['con_ia'])
                    nuevas += resultado.get('capturados', 0)
                    if resultado.get('status') != 'EXITO':
                        self.stderr.write(f'RSS {nombre}: {resultado.get("detalle", "revisar cobertura")}')
                    else:
                        self.stdout.write(f'RSS {nombre}: {resultado.get("capturados", 0)} noticias nuevas.')
                except Exception as exc:
                    # Un feed caído no impide revisar los demás; el siguiente ciclo reintenta.
                    self.stderr.write(f'RSS {nombre}: error {type(exc).__name__}')
            self.stdout.write(f'Revisión RSS terminada. Noticias nuevas: {nuevas}.')
            if options['una_vez']:
                return
            time.sleep(max(0, intervalo - (time.monotonic() - inicio)))
