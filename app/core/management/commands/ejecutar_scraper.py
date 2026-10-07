from django.core.management.base import BaseCommand
from core.scrapers.noticias import fetch_elterritorio_news

class Command(BaseCommand):
    help = 'Ejecuta la ingesta RSS de noticias desde El Territorio y persiste los datos en PostgreSQL'

    def add_arguments(self, parser):
        # Permite opcionalmente definir categoría y límite desde la terminal
        parser.add_argument('--category', type=str, default='misiones', help='Categoría de noticias a scrapear')
        parser.add_argument('--limit', type=int, default=5, help='Cantidad de noticias a consultar')

    def handle(self, *args, **options):
        categoria = options['category']
        limite = options['limit']

        self.stdout.write(self.style.SUCCESS(f"[+] Iniciando scraper de El Territorio (Categoría: {categoria}, Límite: {limite})..."))

        # Llamamos a la función que ya construimos y probamos
        articulos = fetch_elterritorio_news(category=categoria, limit=limite)

        self.stdout.write(self.style.SUCCESS(f"[✔] Ingesta finalizada correctamente. Se procesaron {len(articulos)} artículos."))