from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.services.scraper import ingestar_historico_elterritorio


class Command(BaseCommand):
    help = ('Ingesta noticias pasadas de El Territorio (vía sitemaps) para poblar la base. '
            'Ej.: --desde 2026-09-01 --hasta 2026-10-16 --limite 40')

    def add_arguments(self, parser):
        parser.add_argument('--desde', type=date.fromisoformat, required=True,
                            help='Fecha inicial AAAA-MM-DD (inclusive)')
        parser.add_argument('--hasta', type=date.fromisoformat, default=None,
                            help='Fecha final AAAA-MM-DD (inclusive). Por defecto, hoy.')
        parser.add_argument('--limite', type=int, default=40,
                            help='Máximo de noticias nuevas a guardar')
        parser.add_argument('--sin-ia', action='store_true',
                            help='Clasifica sólo con reglas locales, sin llamar a Gemini')

    def handle(self, *args, **options):
        desde = options['desde']
        hasta = options['hasta'] or timezone.localdate()
        limite = options['limite']
        if limite < 1:
            raise CommandError('--limite debe ser mayor que cero.')
        self.stdout.write(self.style.WARNING(
            f"[+] Ingesta histórica de El Territorio del {desde} al {hasta} (límite: {limite})..."
        ))
        resultado = ingestar_historico_elterritorio(desde, hasta, limite=limite, usar_ia=not options['sin_ia'])
        if resultado.get('status') != 'EXITO':
            raise CommandError(f"Falló la ingesta histórica: {resultado.get('detalle') or 'sin detalle'}")

        for error in resultado.get('errores') or []:
            self.stdout.write(self.style.WARNING(f"[!] Noticia descartada ({error['codigo']}): {error['link']}"))
        self.stdout.write(self.style.SUCCESS(
            f"[✔] Noticias en el período: {resultado.get('disponibles', 0)} | "
            f"Nuevas: {resultado['capturados']} | Ya existentes: {resultado['omitidas']} | "
            f"Con errores: {len(resultado.get('errores') or [])}"
        ))
        categorias = resultado.get('categorias') or {}
        if categorias:
            self.stdout.write('Por categoría: ' + ', '.join(f'{c}: {n}' for c, n in sorted(categorias.items())))
