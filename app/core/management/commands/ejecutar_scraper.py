from django.core.management.base import BaseCommand, CommandError
from core.services.scraper import CATEGORIAS_TERRITORIO, LIMITE_POR_DEFECTO, fetch_and_store_elterritorio

class Command(BaseCommand):
    help = 'Ejecuta la ingesta RSS de noticias desde El Territorio y persiste los datos en PostgreSQL'

    def add_arguments(self, parser):
        # Permite opcionalmente definir categoría y límite desde la terminal
        parser.add_argument('--category', type=str, default='misiones', choices=tuple(CATEGORIAS_TERRITORIO),
                            help='Categoría de noticias a scrapear')
        parser.add_argument('--todas', action='store_true',
                            help='Ingesta todas las categorías RSS de El Territorio (ignora --category)')
        parser.add_argument('--limit', type=int, default=LIMITE_POR_DEFECTO,
                            help='Cantidad de noticias a consultar por categoría')
        parser.add_argument('--sin-ia', action='store_true',
                            help='Clasifica sólo con reglas locales, sin llamar a Gemini')

    def handle(self, *args, **options):
        categorias = tuple(CATEGORIAS_TERRITORIO) if options['todas'] else (options['category'],)
        for categoria in categorias:
            self._ingerir(categoria, options['limit'], not options['sin_ia'])

    def _ingerir(self, categoria, limite, usar_ia):
        self.stdout.write(self.style.WARNING(f"[+] Iniciando scraper de El Territorio (Categoría: {categoria}, Límite: {limite})..."))

        # Delegamos en el scraper oficial para compartir identidad, deduplicación y registro de ejecución.
        try:
            resultado = fetch_and_store_elterritorio(categoria, limit=limite, usar_ia=usar_ia)
        except Exception as exc:
            raise CommandError(f"Falló la ingesta RSS: {exc}") from exc
        if not isinstance(resultado, dict):
            raise CommandError("Resultado de ingesta inválido: se esperaba un diccionario.")
        if resultado.get('status') != 'EXITO':
            detalle = resultado.get('detalle') or 'Sin detalle de error'
            raise CommandError(f"Falló la ingesta RSS (estado: {resultado.get('status')!r}): {detalle}")

        errores = resultado.get('errores') or []
        procesados = resultado.get('capturados', 0) + resultado.get('omitidas', 0) + len(errores)
        for error in errores:
            self.stdout.write(self.style.WARNING(f"[!] Noticia descartada ({error.get('codigo')}): {error.get('link')}"))
        self.stdout.write(self.style.SUCCESS(f"[✔] Ingesta finalizada correctamente. Se procesaron {procesados} artículos."))
        self.stdout.write(
            f"Nuevas: {resultado.get('capturados', 0)} | Ya existentes: {resultado.get('omitidas', 0)} "
            f"| Con errores: {len(errores)}"
        )
        categorias = resultado.get('categorias') or {}
        if categorias:
            self.stdout.write('Por categoría: ' + ', '.join(f'{c}: {n}' for c, n in sorted(categorias.items())))
