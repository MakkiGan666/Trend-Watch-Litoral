"""Genera etiquetas temáticas con IA para publicaciones elegidas, en lotes acotados.

Nunca se ejecuta solo (ni en la ingesta ni al guardar). Sin `--confirmar` sólo
muestra qué publicaciones procesaría, sin llamar a ningún modelo. Ejemplos:

    python manage.py etiquetar_con_ia --ids 120 121 122            # vista previa
    python manage.py etiquetar_con_ia --ids 120 121 122 --confirmar
    python manage.py etiquetar_con_ia --limite 5 --confirmar        # 5 más recientes sin etiquetas de IA
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef
from django.db.models.functions import Coalesce

from core.models import Publicacion, PublicacionEtiqueta
from core.services.etiquetas_ia import etiquetar_publicacion
from core.services.ia.gestor import obtener_gestor

LIMITE_MAXIMO = 25
PAUSA_POR_DEFECTO = 4.0


class Command(BaseCommand):
    help = 'Genera etiquetas temáticas con IA (Gemini u Ollama) para publicaciones elegidas.'

    def add_arguments(self, parser):
        parser.add_argument('--ids', type=int, nargs='+', help='Publicaciones a etiquetar (id).')
        parser.add_argument('--limite', type=int, help=f'Cantidad de publicaciones recientes sin etiquetas de IA (máx. {LIMITE_MAXIMO}).')
        parser.add_argument('--rehacer', action='store_true', help='Incluir publicaciones que ya tienen etiquetas de IA.')
        parser.add_argument('--pausa', type=float, default=PAUSA_POR_DEFECTO, help='Segundos entre llamadas al modelo.')
        parser.add_argument('--confirmar', action='store_true', help='Ejecutar de verdad (sin esto es sólo una vista previa).')

    def handle(self, *args, **opciones):
        ids, limite = opciones['ids'], opciones['limite']
        if bool(ids) == bool(limite):
            raise CommandError('Indicá --ids o --limite (uno de los dos).')
        if ids and len(ids) > LIMITE_MAXIMO:
            raise CommandError(f'Como máximo {LIMITE_MAXIMO} publicaciones por ejecución.')
        if limite is not None and not 1 <= limite <= LIMITE_MAXIMO:
            raise CommandError(f'--limite debe estar entre 1 y {LIMITE_MAXIMO}.')
        if not 0 <= opciones['pausa'] <= 120:
            raise CommandError('--pausa debe estar entre 0 y 120 segundos.')

        publicaciones = Publicacion.objects.annotate(con_ia=Exists(PublicacionEtiqueta.objects.filter(
            publicacion_id=OuterRef('pk'), origen=PublicacionEtiqueta.Origen.IA)))
        if ids:
            publicaciones = publicaciones.filter(pk__in=ids).order_by('pk')
            faltantes = set(ids) - set(publicaciones.values_list('pk', flat=True))
            if faltantes:
                raise CommandError(f'No existen publicaciones con id: {", ".join(map(str, sorted(faltantes)))}.')
        else:
            publicaciones = publicaciones.order_by(Coalesce('fecha_publicacion', 'fecha_captura').desc(), '-pk')
        if not opciones['rehacer']:
            publicaciones = publicaciones.filter(con_ia=False)
        publicaciones = list(publicaciones[:limite] if limite else publicaciones)

        if not publicaciones:
            self.stdout.write('No hay publicaciones para etiquetar (las que ya tienen etiquetas de IA se omiten sin --rehacer).')
            return
        if not opciones['confirmar']:
            self.stdout.write(f'Vista previa: se etiquetarían {len(publicaciones)} publicaciones (no se llamó a ningún modelo).')
            for publicacion in publicaciones:
                self.stdout.write(f'  #{publicacion.pk} {publicacion.titulo[:90]}')
            self.stdout.write('Agregá --confirmar para ejecutar.')
            return

        gestor = obtener_gestor()
        if not gestor.disponible():
            raise CommandError('El motor de IA principal no está disponible (GEMINI_API_KEY u Ollama).')
        conteo = {'etiquetada': 0, 'invalida': 0, 'fallida': 0}
        for indice, publicacion in enumerate(publicaciones):
            if indice and opciones['pausa']:
                time.sleep(opciones['pausa'])  # respeta los límites de frecuencia del proveedor
            resultado = etiquetar_publicacion(publicacion, gestor=gestor)
            conteo[resultado.estado] += 1
            if resultado.estado == 'etiquetada':
                self.stdout.write(f'#{publicacion.pk} {resultado.proveedor}:{resultado.modelo} → '
                                  f'{", ".join(resultado.etiquetas)} ({resultado.descartadas} descartadas)')
            else:
                self.stdout.write(f'#{publicacion.pk} {resultado.estado} ({resultado.codigo})')
        self.stdout.write(f'Etiquetadas: {conteo["etiquetada"]}. Inválidas: {conteo["invalida"]}. '
                          f'Fallidas: {conteo["fallida"]}. Detalle en Administración → Seguimiento de IA.')
