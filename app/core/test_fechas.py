"""Regresiones ORM de fecha efectiva: sin servicios externos ni escrituras históricas."""
from datetime import datetime, timezone as tz
from types import SimpleNamespace
from unittest.mock import patch

from django.core.paginator import Paginator
from django.test import TestCase
from django.urls import reverse
from core.fechas import datos_fecha
from core.models import Publicacion
from core.views import _orden_por_publicacion


def instante(dia, hora=12):
    return datetime(2026, 10, dia, hora, tzinfo=tz.utc)


class FechasPublicacionTestCase(TestCase):
    def crear(self, nombre, publicacion, captura, **kwargs):
        return Publicacion.objects.create(hash_origen=nombre, titulo=nombre, contenido='Texto',
                                          fecha_publicacion=publicacion, fecha_captura=captura, **kwargs)

    def orden(self):
        return Publicacion.objects.order_by(*_orden_por_publicacion())

    def test_antigua_recien_capturada_no_desplaza_actual_sin_fecha_del_medio(self):
        antigua = self.crear('archivo', instante(1), instante(20))
        nueva = self.crear('manual', None, instante(19))
        self.assertEqual(list(self.orden()), [nueva, antigua])
        antigua.refresh_from_db()
        self.assertEqual(antigua.fecha_captura, instante(20))

    def test_empate_efectivo_desempata_pk_sin_usar_captura(self):
        primera = self.crear('primera', instante(10), instante(20))
        segunda = self.crear('segunda', None, instante(10))
        self.assertEqual(list(self.orden()), [segunda, primera])

    def test_todas_sin_publicacion_ordenan_por_captura(self):
        vieja = self.crear('vieja', None, instante(1))
        nueva = self.crear('nueva', None, instante(2))
        self.assertEqual(list(self.orden()), [nueva, vieja])

    def test_instantes_equivalentes_con_distintas_zonas_desempatan_pk(self):
        from datetime import timedelta, timezone
        primera = self.crear('utc', instante(10), instante(20))
        segunda = self.crear('local', instante(10).astimezone(timezone(timedelta(hours=-3))), instante(19))
        self.assertEqual(list(self.orden()), [segunda, primera])

    def test_paginacion_estable_con_empates(self):
        publicaciones = [self.crear(str(i), instante(10), instante(20)) for i in range(5)]
        paginas = Paginator(self.orden(), 2)
        obtenido = [p.pk for numero in paginas.page_range for p in paginas.page(numero)]
        self.assertEqual(obtenido, [p.pk for p in reversed(publicaciones)])

    def test_listado_global_y_localidad_coinciden(self):
        antigua = self.crear('archivo', instante(1), instante(20), departamento='capital')
        nueva = self.crear('manual', None, instante(19), departamento='capital')
        for ruta in (reverse('listar_publicaciones'), reverse('publicaciones_localidad', args=['capital'])):
            datos = self.client.get(ruta).json()['data']
            self.assertEqual([p['id'] for p in datos], [nueva.pk, antigua.pk])
            self.assertEqual(datos[0]['fecha_origen'], 'captura')

    def test_fecha_legacy_global_permanece_captura(self):
        p = self.crear('fechas-distintas', instante(1), instante(20))
        dato = self.client.get(reverse('listar_publicaciones')).json()['data'][0]
        self.assertEqual(dato['fecha'], p.fecha_captura.strftime('%Y-%m-%d %H:%M:%S'))
        self.assertEqual(dato['fecha_publicacion'], p.fecha_publicacion.isoformat())
        self.assertEqual(dato['fecha_dia'], '2026-10-01')

    def test_limite_del_listado_se_aplica_despues_del_orden_efectivo(self):
        self.crear('antigua', instante(1), instante(20))
        nueva = self.crear('nueva', None, instante(19))
        with patch('core.views.LIMITE_LISTADO', 1):
            datos = self.client.get(reverse('listar_publicaciones')).json()['data']
        self.assertEqual([p['id'] for p in datos], [nueva.pk])

    def test_archivo_no_presenta_mediodia_como_hora_comprobada(self):
        p = self.crear('historica', instante(1), instante(20), fuente='El Territorio (Archivo)')
        dato = self.client.get(reverse('listar_publicaciones')).json()['data'][0]
        self.assertEqual(dato['fecha_efectiva'], '2026-10-01')
        self.assertEqual(dato['fecha_precision'], 'dia')
        respuesta = self.client.get(reverse('noticia', args=[p.pk]))
        self.assertContains(respuesta, 'Hora no verificada')
        self.assertContains(respuesta, 'datetime="2026-10-01"')
        p.refresh_from_db()
        self.assertEqual(p.fecha_publicacion, instante(1))

    def test_dia_local_no_es_fecha_utc(self):
        p = self.crear('madrugada', instante(2, 2), instante(20))
        self.assertEqual(datos_fecha(p)['fecha_dia'], '2026-10-01')

    def test_ambas_nulas_solo_presentacion_legacy(self):
        # La captura no admite NULL en BD: comprobar el caso defensivo sin alterar esquema.
        p = SimpleNamespace(fecha_publicacion=None, fecha_captura=None, fuente='Manual')
        self.assertEqual(datos_fecha(p), {'fecha_efectiva': None, 'fecha_dia': None,
                                         'fecha_precision': None, 'fecha_origen': None})

    def test_dashboard_utiliza_el_mismo_orden(self):
        from django.contrib.auth import get_user_model
        usuario = get_user_model().objects.create_superuser(username='fechas-panel')
        self.client.force_login(usuario)
        antigua = self.crear('archivo-panel', instante(1), instante(20))
        nueva = self.crear('manual-panel', None, instante(19))
        respuesta = self.client.get(reverse('publicaciones'))
        self.assertEqual(list(respuesta.context['publicaciones']), [nueva, antigua])

    def test_rss_conserva_zona_y_fecha_invalida_es_nula(self):
        from xml.etree.ElementTree import fromstring
        from core.services.scraper import _fecha_rss
        item = fromstring('<item><pubDate>Tue, 20 Oct 2026 00:15:00 -0300</pubDate></item>')
        self.assertEqual(_fecha_rss(item), datetime(2026, 10, 20, 3, 15, tzinfo=tz.utc))
        self.assertIsNone(_fecha_rss(fromstring('<item><pubDate>inválida</pubDate></item>')))

    def test_ingesta_historica_conserva_timestamp_legacy_y_declara_precision(self):
        from datetime import date
        from core.services.scraper import ingestar_historico_elterritorio
        url = 'https://www.elterritorio.com.ar/noticias/2026/10/01/123-noticia'
        articulo = SimpleNamespace(title='Título', text='Contenido', top_image='', publish_date=None)
        with patch('core.services.scraper._urls_de_sitemaps', return_value={url: date(2026, 10, 1)}), \
                patch('core.services.scraper._leer_articulo', return_value=articulo), \
                patch('core.services.scraper.vincular_categoria_por_nombre'):
            resultado = ingestar_historico_elterritorio(date(2026, 10, 1), date(2026, 10, 1), usar_ia=False, pausa=0)
        self.assertEqual(resultado['status'], 'EXITO', resultado)
        self.assertEqual(resultado['estado'], 'EXITO')
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(resultado['errores'], [])
        p = Publicacion.objects.get(url=url)
        # El clasificador local real representa ubicación desconocida con '',
        # nunca None: departamento es NOT NULL aunque admita blank.
        self.assertEqual(p.departamento, '')
        self.assertEqual(p.fecha_publicacion, instante(1))
        self.assertEqual(datos_fecha(p)['fecha_efectiva'], '2026-10-01')
