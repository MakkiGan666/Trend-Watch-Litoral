"""Clasificación por categoría/departamento, imágenes, ingesta histórica y su uso en la web.

Sin red ni Gemini reales: el feed, los sitemaps, los artículos y la IA están simulados.
"""
import json
from datetime import date, datetime, timezone as dt_timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Categoria, Locacion, Publicacion, PublicacionTema
from core.services.clasificacion import (
    CATEGORIAS_PROYECTO, categoria_por_reglas, clasificar_lote, departamento_por_texto,
    vincular_categoria_por_nombre,
)
from core.services.scraper import (
    CATEGORIAS_TERRITORIO, fetch_and_store_elterritorio, ingestar_historico_elterritorio,
)
from core.test_ingesta_historico import BASE, IngestaSimuladaMixin, identidad


class CategoriaPorReglasTestCase(TestCase):
    def test_seccion_del_medio_sin_equivalente_se_deriva_a_categoria_propia(self):
        self.assertEqual(categoria_por_reglas('Cosecha récord', '', 'agro'), 'Economía')
        self.assertEqual(categoria_por_reglas('Cualquier título', '', 'policiales'), 'Policiales')
        self.assertEqual(categoria_por_reglas('Cualquier título', '', 'deportes'), 'Deportes')

    def test_seccion_general_se_clasifica_por_contenido(self):
        casos = {
            'Productores de yerba mate reclaman un mejor precio': 'Economía',
            'El hospital Madariaga refuerza la campaña contra el dengue': 'Salud',
            'Norma Radke asumió como supervisora escolar de primaria en San Pedro': 'Educación',
            'Detuvieron a un hombre tras un robo en Garupá': 'Policiales',
        }
        for titulo, esperada in casos.items():
            with self.subTest(titulo=titulo):
                self.assertEqual(categoria_por_reglas(titulo, '', 'misiones'), esperada)

    def test_sin_palabras_clave_usa_categoria_por_defecto(self):
        self.assertEqual(categoria_por_reglas('Lorem ipsum', 'dolor sit amet', 'misiones'), 'Sociedad')

    def test_prefijos_no_generan_falsos_positivos(self):
        # "monte" no debe confundir Montecarlo con Ambiente.
        self.assertNotEqual(categoria_por_reglas('Montecarlo', 'Vecinos de Montecarlo', ''), 'Ambiente')


class DepartamentoPorTextoTestCase(TestCase):
    def test_municipio_mencionado_identifica_su_departamento(self):
        self.assertEqual(departamento_por_texto('Inauguraron una escuela en Oberá', ''), 'obera')
        self.assertEqual(departamento_por_texto('Récord de visitantes', 'llegaron a Puerto Iguazú'), 'iguazu')
        self.assertEqual(departamento_por_texto('Obras en Posadas y Garupá', ''), 'capital')

    def test_sin_menciones_o_empate_no_asigna_departamento(self):
        self.assertEqual(departamento_por_texto('Suba del dólar', 'mercados nacionales'), '')
        self.assertEqual(departamento_por_texto('Oberá y Eldorado', ''), '')

    def test_referencias_conocidas_identifican_el_departamento(self):
        self.assertEqual(departamento_por_texto('Récord de turistas en Cataratas', ''), 'iguazu')
        self.assertEqual(departamento_por_texto('Obras en la capital misionera', ''), 'capital')
        self.assertEqual(departamento_por_texto('Crecida en los Saltos del Moconá', ''), 'guarani')

    def test_nombres_ambiguos_requieren_referencia_a_la_localidad(self):
        self.assertEqual(departamento_por_texto('Corte en la calle San Martín', ''), '')
        self.assertEqual(departamento_por_texto('Festejos en San Pedro', ''), 'sanpedro')


def respuesta_ia(*items):
    return SimpleNamespace(text=json.dumps(list(items)))


class ClasificarLoteConIATestCase(TestCase):
    # 0: la sección define la categoría; 1: palabra clave clara en el título; 2: dudosa.
    noticias = [
        {'titulo': 'Exportaciones de té', 'contenido': 'Productores de Oberá', 'seccion': 'agro'},
        {'titulo': 'Detuvieron a un hombre por un robo en Cataratas', 'contenido': '', 'seccion': 'misiones'},
        {'titulo': 'Nota nacional', 'contenido': 'Sin localidad', 'seccion': 'pais-y-mundo'},
    ]

    def setUp(self):
        self.gemini = SimpleNamespace(client=MagicMock(), types=MagicMock(), model_name='modelo')
        parche = patch('core.services.gemini_cliente.gemini_cliente', self.gemini)
        parche.start()
        self.addCleanup(parche.stop)

    def enviadas_a_la_ia(self):
        llamada = self.gemini.client.models.generate_content.call_args
        return [n['titulo'] for n in json.loads(llamada.kwargs['contents'])]

    def test_solo_las_dudosas_van_a_la_ia(self):
        self.gemini.client.models.generate_content.return_value = respuesta_ia(
            {'indice': 2, 'categoria': 'Política'},
        )
        resultado = clasificar_lote(self.noticias)
        self.assertEqual(self.gemini.client.models.generate_content.call_count, 1)
        self.assertEqual(self.enviadas_a_la_ia(), ['Nota nacional'])
        self.assertEqual([r['categoria'] for r in resultado], ['Economía', 'Policiales', 'Política'])
        self.assertEqual([r['metodo'] for r in resultado], ['reglas', 'reglas', 'ia'])

    def test_departamento_siempre_por_texto_sin_ia(self):
        resultado = clasificar_lote(self.noticias, usar_ia=False)
        self.assertEqual([r['departamento'] for r in resultado], ['obera', 'iguazu', ''])
        self.assertNotIn('departamento', self.gemini.client.models.generate_content.call_args or '')

    def test_sin_dudosas_no_se_llama_a_la_ia(self):
        clasificar_lote(self.noticias[:2])
        self.gemini.client.models.generate_content.assert_not_called()

    def test_respuesta_invalida_de_la_ia_cae_a_reglas(self):
        for invalida in (
            respuesta_ia({'indice': 2, 'categoria': 'Agro'}),
            respuesta_ia({'indice': 0, 'categoria': 'Salud'}),  # no era dudosa
            respuesta_ia({'indice': 2, 'categoria': 'Salud', 'departamento': 'obera'}),
            SimpleNamespace(text='no es json'),
        ):
            with self.subTest(respuesta=invalida.text):
                self.gemini.client.models.generate_content.return_value = invalida
                resultado = clasificar_lote(self.noticias)
                self.assertEqual([r['metodo'] for r in resultado], ['reglas', 'reglas', 'reglas'])
                self.assertEqual(resultado[0]['categoria'], 'Economía')
                self.assertIn(resultado[2]['categoria'], CATEGORIAS_PROYECTO)

    def test_ia_no_disponible_o_desactivada_no_se_llama(self):
        self.assertEqual([r['metodo'] for r in clasificar_lote(self.noticias, usar_ia=False)],
                         ['reglas'] * 3)
        self.gemini.client = None
        self.assertEqual([r['metodo'] for r in clasificar_lote(self.noticias)], ['reglas'] * 3)
        self.gemini.types.GenerateContentConfig.assert_not_called()


class VincularCategoriaTestCase(TestCase):
    def test_reutiliza_la_categoria_existente(self):
        existente = Categoria.objects.create(nombre_categoria='Economía')
        publicacion = Publicacion.objects.create(hash_origen='h', contenido='c', url=BASE + '1-a')
        vincular_categoria_por_nombre(publicacion, 'Economía')
        vincular_categoria_por_nombre(publicacion, 'Economía')
        self.assertEqual(Categoria.objects.count(), 1)
        self.assertEqual(
            list(PublicacionTema.objects.values_list('id_temas__id_categoria', flat=True)), [existente.pk],
        )


RSS_CON_MEDIA = """<rss xmlns:media="http://search.yahoo.com/mrss/"><channel>{items}</channel></rss>"""
ITEM_CON_MEDIA = """<item><title>{titulo}</title><link>{link}</link><description>Resumen</description>
<pubDate>Fri, 16 Oct 2026 22:20:17 GMT</pubDate>
<media:content url="https://cdn.ejemplo.com/foto-{n}.webp" type="image/jpg"/></item>"""


class IngestaRSSClasificadaTestCase(IngestaSimuladaMixin, TestCase):
    def feed_con_media(self, cantidad, titulo='Productores de yerba en Oberá'):
        items = ''.join(
            ITEM_CON_MEDIA.format(titulo=titulo, link=f'{BASE}93{n:04d}-nota', n=n) for n in range(cantidad)
        )
        self.urlopen.return_value = RSS_CON_MEDIA.format(items=items).encode('utf-8')

    def test_guarda_imagen_fecha_categoria_y_departamento(self):
        self.feed_con_media(1)
        resultado = fetch_and_store_elterritorio('agro')

        self.assertEqual(resultado['status'], 'EXITO')
        self.assertEqual(resultado['categorias'], {'Economía': 1})
        publicacion = Publicacion.objects.get()
        self.assertEqual(publicacion.imagen_url, 'https://cdn.ejemplo.com/foto-0.webp')
        self.assertEqual(publicacion.fecha_publicacion,
                         datetime(2026, 10, 16, 22, 20, 17, tzinfo=dt_timezone.utc))
        self.assertEqual(publicacion.departamento, 'obera')
        self.assertEqual(
            list(PublicacionTema.objects.filter(id_publicacion_api=publicacion)
                 .values_list('id_temas__id_categoria__nombre_categoria', flat=True)),
            ['Economía'],
        )

    def test_limite_por_defecto_es_30(self):
        self.feed_con_media(35)
        resultado = fetch_and_store_elterritorio('misiones')
        self.assertEqual(resultado['capturados'], 30)

    def test_imagen_no_http_se_descarta_sin_perder_la_noticia(self):
        xml = RSS_CON_MEDIA.format(items=ITEM_CON_MEDIA.format(titulo='Nota', link=BASE + '930100-x', n=0)
                                   .replace('https://cdn.ejemplo.com', 'javascript:alert(1)//'))
        self.urlopen.return_value = xml.encode('utf-8')
        self.assertEqual(fetch_and_store_elterritorio('misiones')['capturados'], 1)
        self.assertEqual(Publicacion.objects.get().imagen_url, '')


SITEMAP_INDICE = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://sm/1.xml</loc></sitemap>
<sitemap><loc>https://sm/2.xml</loc></sitemap></sitemapindex>"""
URLSET = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{}</urlset>'


def nota(fecha, numero):
    return f'https://www.elterritorio.com.ar/noticias/{fecha.replace("-", "/")}/{numero}-nota-{numero}'


class IngestaHistoricaTestCase(IngestaSimuladaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.links = {
            'sm/1.xml': [nota('2026-09-01', 100), nota('2026-09-01', 101), nota('2026-09-02', 102),
                         nota('2026-08-31', 99)],
            'sm/2.xml': [nota('2026-09-03', 103), nota('2026-09-03', 104), nota('2026-10-20', 200),
                         'https://www.elterritorio.com.ar/contacto'],
        }

        def descargar(url, timeout=None):
            if url.endswith('sitemap.xml'):
                cuerpo = SITEMAP_INDICE
            elif url in {link for enlaces in self.links.values() for link in enlaces}:
                return b'<html><body>Articulo simulado</body></html>'
            else:
                clave = url.split('://', 1)[1]
                cuerpo = URLSET.format(''.join(f'<url><loc>{l}</loc></url>' for l in self.links[clave]))
            return cuerpo.encode('utf-8')

        self.urlopen.side_effect = descargar
        self.article.side_effect = lambda url, language=None, **kwargs: SimpleNamespace(
            title=f'Escuela en Posadas {url[-3:]}', text=f'Texto de {url}', top_image=f'https://cdn.ejemplo.com/{url[-3:]}.webp',
            publish_date=None, download=lambda **kwargs: None, parse=lambda: None,
        )

    def ingerir(self, **opciones):
        opciones.setdefault('pausa', 0)
        return ingestar_historico_elterritorio(date(2026, 9, 1), date(2026, 9, 30), **opciones)

    def test_toma_solo_el_periodo_y_reparte_entre_dias(self):
        resultado = self.ingerir(limite=3)

        self.assertEqual(resultado['status'], 'ERROR')
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(resultado['capturados'], 3)
        self.assertEqual(resultado['disponibles'], 5)
        # Una noticia por día, de la fecha más reciente a la más vieja.
        self.assertEqual(
            sorted(Publicacion.objects.values_list('url', flat=True)),
            sorted([nota('2026-09-03', 104), nota('2026-09-02', 102), nota('2026-09-01', 101)]),
        )
        publicacion = Publicacion.objects.get(url=nota('2026-09-02', 102))
        self.assertEqual(publicacion.fuente, 'El Territorio (Archivo)')
        self.assertEqual(publicacion.imagen_url, 'https://cdn.ejemplo.com/102.webp')
        self.assertEqual(publicacion.fecha_publicacion.date(), date(2026, 9, 2))
        self.assertTrue(PublicacionTema.objects.filter(id_publicacion_api=publicacion).exists())

    def test_existentes_no_cuentan_para_el_limite(self):
        existente = nota('2026-09-03', 104)
        Publicacion.objects.create(hash_origen=identidad(existente), contenido='Previa', url=existente)
        resultado = self.ingerir(limite=10)
        self.assertEqual((resultado['capturados'], resultado['omitidas']), (4, 1))
        self.assertEqual(Publicacion.objects.get(url=existente).contenido, 'Previa')

    def test_articulo_sin_texto_se_registra_y_continua(self):
        self.article.side_effect = lambda url, language=None, **kwargs: SimpleNamespace(
            title='', text='', top_image='', publish_date=None, download=lambda **kwargs: None, parse=lambda: None,
        )
        resultado = self.ingerir(limite=2)
        self.assertEqual(resultado['capturados'], 0)
        self.assertEqual({e['codigo'] for e in resultado['errores']}, {'articulo_no_disponible'})

    def test_rango_invertido_es_error(self):
        resultado = ingestar_historico_elterritorio(date(2026, 10, 1), date(2026, 9, 1))
        self.assertEqual(resultado['status'], 'ERROR')
        self.urlopen.assert_not_called()

    def test_comando_informa_resultado(self):
        salida = StringIO()
        with patch('core.services.scraper.time.sleep'):
            call_command('ingestar_historico', '--desde=2026-09-01', '--hasta=2026-09-30', '--limite=10',
                         stdout=salida)
        self.assertIn('Nuevas: 5', salida.getvalue())
        self.assertEqual(Publicacion.objects.count(), 5)


class EjecutarScraperTodasTestCase(TestCase):
    @patch('core.management.commands.ejecutar_scraper.fetch_and_store_elterritorio', return_value={
        'status': 'EXITO', 'capturados': 0, 'registro_id': 1, 'omitidas': 0, 'errores': [],
    })
    def test_todas_recorre_cada_feed(self, scraper):
        call_command('ejecutar_scraper', todas=True, sin_ia=True, stdout=StringIO())
        self.assertEqual([c.args[0] for c in scraper.call_args_list], list(CATEGORIAS_TERRITORIO))
        self.assertTrue(all(c.kwargs == {'limit': 30, 'usar_ia': False} for c in scraper.call_args_list))


class VistasConClasificacionTestCase(TestCase):
    def setUp(self):
        self.publicacion = Publicacion.objects.create(
            hash_origen='h1', fuente='El Territorio (Agro)', titulo='Cosecha de yerba',
            contenido='Texto', url=BASE + '940000-yerba', imagen_url='https://cdn.ejemplo.com/y.webp',
            departamento='obera', fecha_publicacion=datetime(2026, 9, 2, tzinfo=dt_timezone.utc),
        )
        vincular_categoria_por_nombre(self.publicacion, 'Economía')

    def test_listado_incluye_categorias_imagen_y_departamento(self):
        dato = self.client.get(reverse('listar_publicaciones')).json()['data'][0]
        self.assertEqual(dato['categorias'], ['Economía'])
        self.assertEqual(dato['imagen_url'], 'https://cdn.ejemplo.com/y.webp')
        self.assertEqual(dato['departamento'], 'obera')

    def test_departamento_detectado_al_ingerir_aparece_en_su_localidad(self):
        otra = Publicacion.objects.create(hash_origen='h2', contenido='c', url=BASE + '940001-otra')
        Locacion.objects.create(id_publicacion_api=otra, location='Eldorado', latitud=0, longitud=0)
        datos = self.client.get(reverse('publicaciones_localidad', args=['obera'])).json()['data']
        self.assertEqual([d['id'] for d in datos], [self.publicacion.pk])
        self.assertEqual(datos[0]['imagen_url'], 'https://cdn.ejemplo.com/y.webp')

    def test_detalle_muestra_credito_del_medio_sobre_la_foto(self):
        respuesta = self.client.get(reverse('noticia', args=[self.publicacion.pk]))
        self.assertContains(respuesta, '© Foto: El Territorio<')
        self.assertContains(respuesta, 'https://cdn.ejemplo.com/y.webp')

    def test_categorias_muestra_las_12_categorias(self):
        respuesta = self.client.get(reverse('categorias'))
        for nombre in CATEGORIAS_PROYECTO:
            self.assertContains(respuesta, f'>{nombre}</h3>')
