from django.core.management.base import BaseCommand, CommandError
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
        try:
            res_ingesta = fetch_and_store_elterritorio(categoria)
        except Exception as exc:
            raise CommandError(f"Falló la ingesta RSS: {exc}") from exc
        if not isinstance(res_ingesta, dict):
            raise CommandError("Resultado de ingesta inválido: se esperaba un diccionario.")
        if res_ingesta.get("status") != "EXITO":
            detalle = res_ingesta.get("detalle") or "Sin detalle de error"
            raise CommandError(
                f"Falló la ingesta RSS (estado: {res_ingesta.get('status')!r}): {detalle}"
            )
        self.stdout.write(self.style.SUCCESS(f"Ingesta finalizada: {res_ingesta}"))

        # 2. Ejecutar IA
        self.stdout.write("Ejecutando Análisis con Gemini...")
        res_ia = procesar_publicaciones_con_ia(batch_size=10)
        if (not isinstance(res_ia, dict)
                or res_ia.get('estado') not in ('EXITO', 'PARCIAL', 'FALLO', 'NO_DISPONIBLE', 'SIN_PENDIENTES')
                or not isinstance(res_ia.get('mensaje'), str)):
            raise CommandError('Resultado de IA inválido.')
        self.stdout.write(f"IA finalizada: {res_ia['mensaje']} ({res_ia['estado']})")
        if res_ia['estado'] not in ('EXITO', 'SIN_PENDIENTES'):
            raise CommandError(f"Procesamiento IA {res_ia['estado']}: {res_ia['mensaje']}")

        self.stdout.write(self.style.SUCCESS("Pipeline completado exitosamente."))
