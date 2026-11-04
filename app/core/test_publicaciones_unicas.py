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


from datetime import datetime, timezone as tz
from random import Random
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.test import SimpleTestCase
from core.services import publicaciones_unicas as servicio_unicas


def referencia_anterior(registros):
    """Contrato previo: comparar sólo con visibles, en el orden recibido."""
    visibles = []
    grupos = {}
    for pk, titulo, publicada, captura in registros:
        palabras = servicio_unicas._palabras(titulo)
        if len(palabras) < 3:
            visibles.append(pk)
            continue
        fecha = publicada or captura
        anteriores = grupos.setdefault(palabras[:4], [])
        if servicio_unicas._es_copia(palabras, fecha, anteriores):
            continue
        anteriores.append((palabras, fecha))
        visibles.append(pk)
    return visibles


class DeduplicacionDiferencialTests(SimpleTestCase):
    def comprobar(self, registros):
        esperado = referencia_anterior(registros)
        self.assertEqual(servicio_unicas.ids_publicaciones_unicas(iter(registros)), esperado)
        objetos = [SimpleNamespace(pk=pk, titulo=titulo, fecha_publicacion=publicada, fecha_captura=captura)
                   for pk, titulo, publicada, captura in registros]
        for limite in (None, 0, -1, 1, 3, 500):
            resultado = servicio_unicas.publicaciones_unicas(iter(objetos), limite=limite)
            self.assertEqual([p.pk for p in resultado], esperado if limite is None or limite <= 0 else esperado[:limite])

    def test_limites_temporales_nulos_cortos_y_prioridad_de_captura(self):
        ahora = datetime(2026, 11, 4, 12, tzinfo=tz.utc)
        titulo = 'Palabras iniciales iguales grupo con salud mental comunitaria'
        filas = [(1, titulo, ahora, None), (2, titulo, ahora-timedelta(days=2), None),
                 (3, titulo, ahora+timedelta(days=2, microseconds=1), None),
                 (4, titulo, None, ahora), (5, titulo, None, None), (6, titulo, None, None),
                 (7, 'Agenda', ahora, ahora), (8, 'Agenda', ahora, ahora),
                 (9, 'Noticia distinta con otros datos', ahora, ahora)]
        for orden in (filas, list(reversed(filas)), filas[::2]+filas[1::2]):
            self.comprobar(orden)

    def test_variantes_y_empates_en_ordenes_arbitrarios(self):
        ahora = datetime(2026, 11, 4, 12, tzinfo=tz.utc)
        titulos = ['Palabras iniciales iguales grupo ofrece salud mental comunitaria',
                   'Palabras iniciales iguales grupo ofrece salud mental comunitaria gratuita',
                   'Palabras iniciales iguales grupo analiza economia forestal exportadora',
                   'Educación en San Pedro', 'Educación en San Pedro', 'Agenda', '']
        rng = Random(39)
        for repeticion in range(20):
            filas = []
            for pk in range(150):
                fecha = ahora+timedelta(days=rng.randrange(-12, 13), seconds=rng.randrange(3))
                filas.append((pk, rng.choice(titulos), fecha if pk % 7 else None, fecha if pk % 11 else None))
            rng.shuffle(filas)
            with self.subTest(repeticion=repeticion):
                self.comprobar(filas)

    def test_dst_y_offsets_distintos_no_pierden_equivalencias(self):
        ny = ZoneInfo('America/New_York')
        a = datetime(2026, 10, 31, 19, 30, tzinfo=ny)
        b = datetime(2026, 11, 2, 19, 30, tzinfo=ny)
        titulo = 'Palabras iniciales iguales grupo sobre salud mental comunitaria'
        # 48 horas civiles, pero 49 horas UTC y tres días de calendario UTC.
        self.assertEqual(b-a, timedelta(days=2))
        self.comprobar([(1, titulo, a, None), (2, titulo, b, None)])
        self.comprobar([(1, titulo, b, None), (2, titulo, a, None)])
        self.comprobar([(1, titulo, a.astimezone(tz.utc), None), (2, titulo, b.astimezone(tz.utc), None)])
        self.comprobar([(1, titulo, a, None), (2, titulo, b.astimezone(tz(timedelta(hours=5))), None)])

    def test_fechas_sin_zona_y_extremos_no_desbordan(self):
        titulo = 'Palabras iniciales iguales grupo sobre salud mental comunitaria'
        for a, b in [(datetime(2026, 1, 1), datetime(2026, 1, 3)),
                     (datetime(1, 1, 1, tzinfo=tz.utc), datetime(1, 1, 3, tzinfo=tz.utc)),
                     (datetime(9999, 12, 29, tzinfo=tz.utc), datetime(9999, 12, 31, tzinfo=tz.utc))]:
            self.comprobar([(1, titulo, a, None), (2, titulo, b, None)])

    def test_grupo_adverso_grande_no_compara_fechas_lejanas(self):
        ahora = datetime(2026, 11, 4, tzinfo=tz.utc)
        filas = [(i, f'Palabras iniciales iguales grupo {i} alfa{i} beta{i} gamma{i}', ahora-timedelta(days=i*3), ahora) for i in range(10000)]
        comparaciones = 0
        original = servicio_unicas._es_copia
        def contar(palabras, fecha, anteriores):
            nonlocal comparaciones
            candidatos = list(anteriores)
            comparaciones += len(candidatos)
            return original(palabras, fecha, candidatos)
        with patch.object(servicio_unicas, '_es_copia', side_effect=contar):
            self.assertEqual(servicio_unicas.ids_publicaciones_unicas(filas), list(range(10000)))
        self.assertEqual(comparaciones, 0)

    def test_grupo_denso_conserva_todas_las_noticias_distintas(self):
        ahora = datetime(2026, 11, 4, tzinfo=tz.utc)
        filas = [(i, f'Palabras iniciales iguales grupo alfa{i} beta{i} gamma{i} delta{i}', ahora, ahora) for i in range(250)]
        self.comprobar(filas)
        self.assertEqual(servicio_unicas.ids_publicaciones_unicas(filas), list(range(250)))
