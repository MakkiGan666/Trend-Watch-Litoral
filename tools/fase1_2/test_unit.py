"""Pruebas sin dependencias: transporte real y servicio con ORM/Django simulados.

No sustituyen pruebas transaccionales Django/PostgreSQL. No abren sockets.
"""
import importlib.util
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
import socket
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

APP = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(APP))
from core.services import descarga_segura as red

URL = 'https://www.elterritorio.com.ar/noticias/2026/10/20/123-noticia'
PUBLICA = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))


class SinRed(unittest.TestCase):
    def setUp(self):
        for destino in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.getaddrinfo'):
            parche = patch(destino, side_effect=AssertionError('Red real prohibida'))
            parche.start()
            self.addCleanup(parche.stop)


class TransporteTest(SinRed):
    def test_urls_adversariales(self):
        for url in ('http://www.elterritorio.com.ar/', 'https://localhost/',
                    'https://127.0.0.1/', 'https://[::1]/', 'https://169.254.169.254/',
                    'https://www.elterritorio.com.ar.evil.org/',
                    'https://www.elterritorio.com.ar@evil.org/',
                    'https://user@www.elterritorio.com.ar/',
                    'https://www.elterritorio.com.ar:8080/',
                    'https://www.elterritorio.com.ar:abc/',
                    'https://www.elterritorio.com.ar/\nfoo',
                    'https://www.elterritorio.com.ar\\@evil.org/',
                    'https://www.elterritorio.com.ar/#fragment', '//www.elterritorio.com.ar/', ''):
            with self.subTest(url=url), self.assertRaises(ValueError):
                red.descargar(url)

    def test_dns_privado_mixto_y_vacio(self):
        for ip in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', '::ffff:127.0.0.1', '224.0.0.1', 'ff02::1', '2002:7f00:1::'):
            destino = (*PUBLICA[:4], (ip, 443))
            with self.subTest(ip=ip), patch.object(red.socket, 'getaddrinfo', return_value=[PUBLICA, destino]), \
                    patch.object(red, '_Conexion') as conexion, self.assertRaises(ValueError):
                red.descargar(URL)
            conexion.assert_not_called()
        with patch.object(red.socket, 'getaddrinfo', return_value=[]), self.assertRaises(ValueError):
            red.descargar(URL)

    def test_redireccion_rechazada_antes_de_segunda_conexion(self):
        for destino in ('http://www.elterritorio.com.ar/', 'https://localhost/', 'https://evil.org/'):
            respuesta = MagicMock(status=302)
            respuesta.getheader.return_value = destino
            with self.subTest(destino=destino), patch.object(red.socket, 'getaddrinfo', return_value=[PUBLICA]), \
                    patch.object(red, '_Conexion') as conexion, self.assertRaises(ValueError):
                conexion.return_value.getresponse.return_value = respuesta
                red.descargar(URL)
            self.assertEqual(conexion.call_count, 1)
            conexion.return_value.close.assert_called_once()

    def test_redireccion_revalida_dns(self):
        respuesta = MagicMock(status=302)
        respuesta.getheader.return_value = '/otra'
        privado = (*PUBLICA[:4], ('10.0.0.2', 443))
        with patch.object(red.socket, 'getaddrinfo', side_effect=[[PUBLICA], [privado]]), \
                patch.object(red, '_Conexion') as conexion, self.assertRaises(ValueError):
            conexion.return_value.getresponse.return_value = respuesta
            red.descargar(URL)
        self.assertEqual(conexion.call_count, 1)

    def test_redireccion_relativa_y_cuerpo(self):
        primera = MagicMock(status=302)
        primera.getheader.return_value = '/otra?x=1'
        segunda = MagicMock(status=200)
        segunda.read1.side_effect = [b'HTML', b'']
        with patch.object(red.socket, 'getaddrinfo', return_value=[PUBLICA]), patch.object(red, '_Conexion') as conexion:
            conexion.return_value.getresponse.side_effect = [primera, segunda]
            self.assertEqual(red.descargar(URL), b'HTML')
            self.assertEqual(conexion.call_count, 2)
            self.assertEqual(conexion.return_value.request.call_args.args[1], '/otra?x=1')

    def test_bucle_http_y_tamano(self):
        for estado, cuerpo in ((302, b''), (500, b''), (200, b'x' * (red.MAX_BYTES + 1))):
            respuesta = MagicMock(status=estado)
            respuesta.getheader.return_value = '/bucle'
            respuesta.read1.side_effect = [cuerpo, b'']
            with self.subTest(estado=estado), patch.object(red.socket, 'getaddrinfo', return_value=[PUBLICA]), \
                    patch.object(red, '_Conexion') as conexion, self.assertRaises((ValueError, OSError)):
                conexion.return_value.getresponse.return_value = respuesta
                red.descargar(URL)

    def test_conexion_fija_sockaddr_y_verifica_nombre_tls(self):
        conexion = red._Conexion('www.elterritorio.com.ar', PUBLICA, 10)
        with patch.object(red.socket, 'socket') as sock, patch.object(conexion, '_context') as contexto:
            conexion.connect()
            sock.return_value.connect.assert_called_once_with(PUBLICA[4])
            contexto.wrap_socket.assert_called_once_with(sock.return_value, server_hostname='www.elterritorio.com.ar')
        self.assertTrue(red.ssl.create_default_context().check_hostname)


class ServicioTest(SinRed):
    def setUp(self):
        super().setUp()
        db = ModuleType('django.db')
        db.DataError = type('DataError', (Exception,), {})
        db.IntegrityError = type('IntegrityError', (Exception,), {})
        db.transaction = SimpleNamespace(atomic=nullcontext)
        util = ModuleType('django.utils')
        util.timezone = SimpleNamespace(now=lambda: datetime.now(timezone.utc),
                                        is_aware=lambda d: d.tzinfo is not None,
                                        make_aware=lambda d, tz: d.replace(tzinfo=tz))
        modelos = ModuleType('core.models')
        modelos.Publicacion = MagicMock()
        modelos.RegistroDatos = MagicMock()
        modelos.Publicacion._meta.get_field.return_value.max_length = 255
        modelos.Publicacion.objects.filter.return_value.exists.return_value = False
        modelos.Publicacion.objects.filter.return_value.values_list.return_value = []
        clasificacion = ModuleType('core.services.clasificacion')
        clasificacion.clasificar_lote = MagicMock(side_effect=lambda datos, **kw: [
            {'categoria': 'Sociedad', 'departamento': '', 'confirmada': True} for _ in datos])
        clasificacion.vincular_categoria_por_nombre = MagicMock()
        spec = importlib.util.spec_from_file_location('scraper_bajo_prueba', APP / 'core/services/scraper.py')
        self.s = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'django': ModuleType('django'), 'django.db': db,
                                     'django.utils': util, 'core.models': modelos,
                                     'core.services.clasificacion': clasificacion}):
            spec.loader.exec_module(self.s)
        self.descarga = patch.object(self.s, '_descargar', return_value=b'<rss><channel /></rss>').start()
        self.addCleanup(patch.stopall)
        self.parche_articulo = patch.object(self.s, '_leer_articulo', return_value=SimpleNamespace(
            title='Título', text='Contenido', top_image='', publish_date=None))
        self.articulo = self.parche_articulo.start()

    def rss(self, items):
        self.descarga.return_value = ('<rss><channel>' + ''.join(
            f'<item><title>{titulo}</title><link>{link}</link><description>{contenido}</description></item>'
            for titulo, link, contenido in items) + '</channel></rss>').encode()
        return self.s.fetch_and_store_elterritorio(usar_ia=False)

    def historico(self):
        return self.s.ingestar_historico_elterritorio(date(2026, 10, 20), date(2026, 10, 20), usar_ia=False, pausa=0)

    def sitemap(self, links):
        return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
            f'<url><loc>{link}</loc></url>' for link in links) + '</urlset>').encode()

    def test_vacio_y_duplicados_son_distintos(self):
        vacio = self.rss([])
        self.s.Publicacion.objects.filter.return_value.exists.return_value = True
        duplicados = self.rss([('Título', URL, 'Resumen')])
        self.assertEqual((vacio['estado'], duplicados['estado']), ('SIN_RESULTADOS', 'DUPLICADOS'))
        self.assertEqual(duplicados['omitidas'], 1)
        self.s.Publicacion.objects.create.assert_not_called()
        self.assertTrue(vacio['cobertura_completa'])

    def test_incompletos_no_se_guardan(self):
        self.articulo.return_value = None
        resultado = self.rss([('', URL, 'Resumen'), ('Título', URL + '2', '')])
        self.assertEqual(resultado['status'], 'ERROR')
        self.assertFalse(resultado['cobertura_completa'])
        self.s.Publicacion.objects.create.assert_not_called()

    def test_fallback_util_es_parcial(self):
        self.articulo.return_value = None
        resultado = self.rss([('Título', URL, 'Resumen')])
        self.assertEqual((resultado['status'], resultado['estado'], resultado['capturados']), ('ERROR', 'PARCIAL', 1))

    def test_url_maliciosa_no_se_extrae(self):
        resultado = self.rss([('Título', 'https://localhost/noticias/2026/10/20/123-noticia', 'Resumen')])
        self.assertEqual(resultado['errores'][0]['codigo'], 'url_invalida')
        self.articulo.assert_not_called()

    def test_xml_invalido_y_documento_ajeno_fallan(self):
        for xml in (b'<rss>', b'<html />'):
            self.descarga.return_value = xml
            resultado = self.s.fetch_and_store_elterritorio(usar_ia=False)
            self.assertEqual((resultado['status'], resultado['estado']), ('ERROR', 'FALLO'))

    def test_feed_excepcion(self):
        self.descarga.side_effect = OSError('sin red')
        self.assertEqual(self.s.fetch_and_store_elterritorio()['estado'], 'FALLO')

    def test_limites_invalidos_sin_descarga(self):
        for limite in (0, -1, True, '2'):
            self.assertEqual(self.s.fetch_and_store_elterritorio(limit=limite)['estado'], 'FALLO')
            self.assertEqual(self.s.ingestar_historico_elterritorio(date.today(), date.today(), limite=limite)['estado'], 'FALLO')
        self.descarga.assert_not_called()

    def test_limite_rss_informa_cobertura_incompleta(self):
        self.rss([('Título', URL, 'Resumen'), ('Otro', URL + '2', 'Resumen')])
        resultado = self.s.fetch_and_store_elterritorio(limit=1, usar_ia=False)
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(resultado['disponibles'], 2)

    def test_sitemap_parcial_conserva_datos(self):
        indice = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.elterritorio.com.ar/a.xml</loc></sitemap><sitemap><loc>https://www.elterritorio.com.ar/b.xml</loc></sitemap></sitemapindex>'
        self.descarga.side_effect = [indice, self.sitemap([URL]), OSError('sitemap caído')]
        resultado = self.historico()
        self.assertEqual((resultado['status'], resultado['estado'], resultado['capturados']), ('ERROR', 'PARCIAL', 1))
        self.assertEqual(resultado['errores'][0]['codigo'], 'sitemap_no_disponible')

    def test_sitemaps_todos_fallidos(self):
        self.descarga.side_effect = [b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.elterritorio.com.ar/a.xml</loc></sitemap></sitemapindex>', OSError('falló')]
        self.assertEqual(self.historico()['estado'], 'FALLO')

    def test_sitemap_sin_loc_no_es_periodo_vacio(self):
        self.descarga.return_value = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url /></urlset>'
        resultado = self.historico()
        self.assertEqual(resultado['status'], 'ERROR')
        self.assertNotEqual(resultado['estado'], 'SIN_RESULTADOS')

    def test_historico_vacio(self):
        self.descarga.return_value = self.sitemap([])
        resultado = self.historico()
        self.assertEqual((resultado['estado'], resultado['disponibles']), ('SIN_RESULTADOS', 0))

    def test_historico_duplicados(self):
        self.descarga.return_value = self.sitemap([URL])
        self.s.Publicacion.objects.filter.return_value.values_list.return_value = [self.s.generar_hash(URL)]
        self.assertEqual(self.historico()['estado'], 'DUPLICADOS')
        self.articulo.assert_not_called()

    def test_historico_limite(self):
        self.descarga.return_value = self.sitemap([URL, URL.replace('123-', '124-')])
        resultado = self.s.ingestar_historico_elterritorio(date(2026, 10, 20), date(2026, 10, 20), limite=1, usar_ia=False, pausa=0)
        self.assertEqual((resultado['estado'], resultado['capturados']), ('PARCIAL', 1))

    def test_excepcion_tras_guardado_conserva_contadores(self):
        self.s.Publicacion.objects.create.side_effect = [MagicMock(), RuntimeError('fallo')]
        resultado = self.rss([('Título', URL, 'Resumen'), ('Otro', URL + '2', 'Resumen')])
        self.assertEqual((resultado['estado'], resultado['capturados']), ('PARCIAL', 1))
        self.assertIn('registro_id', resultado)

    def test_registro_no_disponible_es_fallo(self):
        self.s.RegistroDatos.objects.create.side_effect = RuntimeError('BD caída')
        self.assertEqual(self.s.fetch_and_store_elterritorio()['estado'], 'FALLO')
        self.assertEqual(self.historico()['estado'], 'FALLO')
        self.descarga.assert_not_called()

    def test_indice_sin_destino_falla(self):
        self.descarga.return_value = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap /></sitemapindex>'
        self.assertEqual(self.historico()['estado'], 'FALLO')

    def test_clasificacion_truncada_falla(self):
        self.s.clasificar_lote.side_effect = lambda *a, **kw: []
        self.assertEqual(self.rss([('Título', URL, 'Resumen')])['estado'], 'FALLO')
        self.s.Publicacion.objects.create.assert_not_called()

    def test_articulo_usa_html_y_desactiva_descargas_de_imagenes(self):
        self.parche_articulo.stop()
        with patch.object(self.s, '_descargar', return_value=b'<html>texto</html>'), patch.object(self.s, 'Article') as article:
            self.s._leer_articulo(URL)
            article.assert_called_once_with(URL, language='es', fetch_images=False)
            article.return_value.download.assert_called_once_with(input_html=b'<html>texto</html>')


if __name__ == '__main__':
    unittest.main(verbosity=2)
