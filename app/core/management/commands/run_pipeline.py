from django.core.management.base import BaseCommand
from core.services.scraper import fetch_and_store_elterritorio
from core.services.gemini_cliente import procesar_publicaciones_con_ia

class Command(BaseCommand):
    help = 'Ejecuta la ingesta RSS y procesa las noticias pendientes con Gemini 1.5 Pro'

    def add_arguments(self, parser):
        # Permite pasar la categoría como argumento opcional. Por defecto será "misiones".
        parser.add_argument(
            '--categoria', 
            type=str, 
            default='misiones', 
            help='Categoría RSS a ingestar (ej. policiales, misiones)'
        )

    def handle(self, *args, **options):
        categoria = options['categoria']
        self.stdout.write(self.style.WARNING(f"Iniciando Pipeline de TrendWatch (Categoría: {categoria})..."))
        
        # 1. Ejecutar Ingesta
        self.stdout.write("Ejecutando Ingesta RSS...")
        res_ingesta = fetch_and_store_elterritorio(categoria)
        self.stdout.write(self.style.SUCCESS(f"Ingesta finalizada: {res_ingesta}"))
        
        # 2. Ejecutar IA
        self.stdout.write("Ejecutando Análisis con Gemini...")
        res_ia = procesar_publicaciones_con_ia(batch_size=10)
        self.stdout.write(self.style.SUCCESS(f"IA finalizada: {res_ia}"))
        
        self.stdout.write(self.style.SUCCESS("Pipeline completado exitosamente."))