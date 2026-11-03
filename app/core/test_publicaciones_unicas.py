from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Categoria, Etiqueta, Publicacion
from core.services.clasificacion import vincular_categoria
from core.services.publicaciones_unicas import ids_publicaciones_unicas


class PublicacionesUnicasTests(TestCase):
    def test_oculta_titulos_identicos_y_variantes_cercanas_del_mismo_dia(self):
        ahora = timezone.now()
        registros = [
            (1, 'Personas mayores con proyectos que fortalecen la salud mental', ahora, ahora),
            (2, 'Personas mayores con proyectos que fortalecen la salud mental', ahora, ahora),
            (3, 'Los Helechos: ex cadete de la Policía de Misiones detenido como principal sospechoso del doble homicidio', ahora, ahora),
            (4, 'Los Helechos: ex cadete de la Policía de Misiones fue detenido como principal sospechoso del doble homicidio de la pareja obereña', ahora, ahora),
            (5, 'Los brutales datos de la autopsia sobre los cadáveres de la pareja en Los Helechos', ahora, ahora),
            (6, 'Personas mayores con proyectos que fortalecen la salud mental', ahora - timedelta(days=30), ahora),
            (7, 'Agenda', ahora, ahora),
            (8, 'Agenda', ahora, ahora),
            (9, 'Noticia 0 en Posadas', ahora, ahora),
            (10, 'Noticia 0 en Posadas', ahora, ahora),
        ]
        self.assertEqual(ids_publicaciones_unicas(registros), [1, 3, 5, 6, 7, 8, 9])

    def test_listados_de_etiqueta_y_categoria_paginan_sin_copias(self):
        ahora = timezone.now()
        categoria = Categoria.objects.create(nombre_categoria='Salud')
        publicaciones = []
        for numero in range(2):
            publicacion = Publicacion.objects.create(
                hash_origen=f'copia-salud-{numero}',
                titulo='Personas mayores con proyectos que fortalecen la salud mental',
                contenido='La salud mental de las personas mayores requiere atención.',
                departamento='capital', fecha_publicacion=ahora,
            )
            vincular_categoria(publicacion, categoria)
            publicaciones.append(publicacion)

        etiqueta = Etiqueta.objects.get(slug='salud')
        listado_etiqueta = self.client.get(reverse('publicaciones_etiqueta', args=[etiqueta.slug]))
        listado_categoria = self.client.get(reverse('publicaciones_categoria', args=['salud']))
        self.assertEqual(listado_etiqueta.context['pagina'].paginator.count, 1)
        self.assertEqual(listado_categoria.context['pagina'].paginator.count, 1)
        self.assertEqual(Publicacion.objects.filter(pk__in=[p.pk for p in publicaciones]).count(), 2)
