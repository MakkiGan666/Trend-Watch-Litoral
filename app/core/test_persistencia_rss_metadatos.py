"""H5.4: persistencia RSS simulada, sin red ni procesamiento de contenido."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings

from core.models import (
    AliasURLPublicacion,
    Categoria,
    ProcesamientoIAMultifuente,
    Publicacion,
    PublicacionEtiqueta,
    PublicacionTema,
    RegistroDatos,
    Sentimiento,
)
from core.services import persistencia_rss_metadatos as servicio
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS, ResultadoRSS
from core.services.persistencia_multifuente import hash_identidad_fuente_url


def _noticia(fuente, *, url=None, titulo='Titular real del feed', fecha=None, resumen='', cuerpo=''):
    return NoticiaRSS(
        fuente.nombre,
        fuente.identificador,
        titulo,
        url or f'https://{fuente.hosts_permitidos[0]}/nota/1?utm_source=feed',
        fecha,
        resumen,
        cuerpo,
        'Sección que no debe persistirse',
    )


def _feed(fuente):
    host = fuente.hosts_permitidos[0]
    return f'''<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel><title>Feed sintético de prueba</title>
        <item><title>Titular sintético uno</title>
          <link>https://{host}/nota/1?utm_source=feed</link>
          <pubDate>Thu, 05 Nov 2026 12:00:00 +0000</pubDate>
          <description>DESCRIPCION_NO_GUARDAR</description>
          <content:encoded><![CDATA[CUERPO_NO_GUARDAR]]></content:encoded>
          <enclosure url="https://{host}/foto.jpg" type="image/jpeg" />
        </item>
        <item><title>Titular sintético dos</title>
          <link>https://{host}/nota/2</link>
          <description>OTRA_DESCRIPCION_NO_GUARDAR</description>
        </item>
      </channel>
    </rss>'''.encode('utf-8')


class PersistenciaRSSMetadatosTests(TestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[0]
        self.autorizacion = override_settings(
            RSS_METADATOS_FUENTES_AUTORIZADAS=(self.fuente.identificador,),
        )
        self.autorizacion.enable()
        self.addCleanup(self.autorizacion.disable)

    def _resultado(self, *noticias, rechazos=()):
        return ResultadoRSS(tuple(noticias), tuple(rechazos))

    def _persistir(self, *noticias, limite=5, lector=None, rechazos=()):
        lector = lector or (lambda fuente, *, limite_entradas: self._resultado(*noticias, rechazos=rechazos))
        return servicio.persistir_metadatos_rss(
            self.fuente.identificador,
            limite=limite,
            confirmar_persistencia=True,
            lector=lector,
        )

    def test_persiste_solo_fuente_titulo_url_fecha_y_no_descarga_articulos(self):
        categorias_antes = Categoria.objects.count()
        bytes_feed = _feed(self.fuente)
        with patch('core.services.descarga_segura.descargar', return_value=bytes_feed) as descargar_feed:
            resultado = servicio.persistir_metadatos_rss(
                self.fuente.identificador,
                limite=1,
                confirmar_persistencia=True,
            )
        self.assertEqual((resultado['estado'], resultado['nuevas'], resultado['duplicadas']), ('EXITO', 1, 0))
        descargar_feed.assert_called_once_with(self.fuente.feed, fuente=self.fuente)
        publicacion = Publicacion.objects.get()
        self.assertEqual(publicacion.fuente, self.fuente.nombre)
        self.assertEqual(publicacion.titulo, 'Titular sintético uno')
        self.assertEqual(publicacion.url, f'https://{self.fuente.hosts_permitidos[0]}/nota/1')
        self.assertEqual(publicacion.fecha_publicacion.isoformat(), '2026-11-05T12:00:00+00:00')
        self.assertEqual(publicacion.contenido, '')
        self.assertFalse(publicacion.contenido_completo)
        self.assertFalse(publicacion.procesado_ia)
        self.assertEqual(publicacion.imagen_url, '')
        self.assertEqual(publicacion.departamento, '')
        self.assertNotIn('DESCRIPCION_NO_GUARDAR', publicacion.contenido)
        self.assertNotIn('CUERPO_NO_GUARDAR', publicacion.contenido)
        self.assertEqual(AliasURLPublicacion.objects.get().fuente, self.fuente.identificador)
        self.assertEqual(RegistroDatos.objects.get(pk=resultado['registro_id']).estado, 'EXITO')
        self.assertFalse(ProcesamientoIAMultifuente.objects.exists())
        self.assertFalse(Sentimiento.objects.exists())
        self.assertFalse(PublicacionEtiqueta.objects.filter(publicacion=publicacion).exists())
        self.assertFalse(PublicacionTema.objects.filter(id_publicacion_api=publicacion).exists())
        self.assertEqual(Categoria.objects.count(), categorias_antes)
        self.assertFalse(self.fuente.habilitada)  # No activó H1.1.

    def test_deniega_por_defecto_o_sin_confirmacion_antes_de_leer_y_escribir(self):
        lector = Mock()
        with override_settings(RSS_METADATOS_FUENTES_AUTORIZADAS=()):
            with self.assertRaises(servicio.AutorizacionMetadatosError):
                servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=lector,
                )
        with self.assertRaises(servicio.AutorizacionMetadatosError):
            servicio.persistir_metadatos_rss(self.fuente.identificador, lector=lector)
        lector.assert_not_called()
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())

    def test_rechaza_fuentes_no_catalogadas_o_configuracion_invalida(self):
        with self.assertRaises(ValueError):
            servicio.persistir_metadatos_rss('desconocida', confirmar_persistencia=True)
        with override_settings(RSS_METADATOS_FUENTES_AUTORIZADAS=('fuente_inventada',)):
            with self.assertRaises(ImproperlyConfigured):
                servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True,
                )
        self.assertFalse(RegistroDatos.objects.exists())

    def test_limite_positivo_y_maximo_se_validan_antes_de_consultar(self):
        lector = Mock()
        for limite in (0, -1, 6, True):
            with self.subTest(limite=limite), self.assertRaises(ValueError):
                servicio.persistir_metadatos_rss(
                    self.fuente.identificador, limite=limite,
                    confirmar_persistencia=True, lector=lector,
                )
        lector.assert_not_called()

    def test_fecha_ausente_se_conserva_como_null_y_titulo_o_url_ausentes_se_rechazan(self):
        buenos = _noticia(self.fuente, fecha=None)
        sin_titulo = replace(buenos, titulo='   ')
        sin_url = replace(buenos, url='')
        resultado = self._persistir(sin_titulo, sin_url, buenos)
        self.assertEqual((resultado['nuevas'], resultado['rechazadas']), (1, 2))
        self.assertEqual(resultado['estado'], 'PARCIAL')
        publicacion = Publicacion.objects.get()
        self.assertIsNone(publicacion.fecha_publicacion)
        self.assertEqual(publicacion.titulo, buenos.titulo)
        self.assertEqual(Publicacion.objects.count(), 1)

    def test_hash_alias_tracking_y_reintentos_son_estables(self):
        noticia = _noticia(self.fuente)
        primera = self._persistir(noticia)
        otra_ejecucion = self._persistir(replace(noticia, resumen='distinto que se ignora'))
        publicacion = Publicacion.objects.get()
        url = f'https://{self.fuente.hosts_permitidos[0]}/nota/1'
        self.assertEqual(primera['nuevas'], 1)
        self.assertEqual(otra_ejecucion['duplicadas'], 1)
        self.assertEqual(publicacion.hash_origen, hash_identidad_fuente_url(self.fuente, url))
        self.assertEqual(publicacion.url, url)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)
        self.assertEqual(RegistroDatos.objects.count(), 2)

    def test_ficha_duplicada_no_sobrescribe_articulo_completo_ni_su_hash(self):
        noticia = _noticia(self.fuente, titulo='Titular que no debe reemplazar al artículo')
        url = f'https://{self.fuente.hosts_permitidos[0]}/nota/1'
        hash_origen = hash_identidad_fuente_url(self.fuente, url)
        completo = Publicacion.objects.create(
            hash_origen=hash_origen,
            fuente=self.fuente.nombre,
            titulo='Título completo original',
            contenido='Cuerpo completo que debe quedar intacto.',
            contenido_completo=True,
            url=url,
            fecha_publicacion=None,
            imagen_url=f'https://{self.fuente.hosts_permitidos[0]}/foto.jpg',
            procesado_ia=True,
            departamento='posadas',
        )
        antes = Publicacion.objects.filter(pk=completo.pk).values(
            'hash_origen', 'fuente', 'titulo', 'contenido', 'contenido_completo', 'url',
            'fecha_publicacion', 'imagen_url', 'procesado_ia', 'departamento', 'id_registro_id',
        ).get()
        resultado = self._persistir(noticia)
        completo.refresh_from_db()
        despues = Publicacion.objects.filter(pk=completo.pk).values(
            'hash_origen', 'fuente', 'titulo', 'contenido', 'contenido_completo', 'url',
            'fecha_publicacion', 'imagen_url', 'procesado_ia', 'departamento', 'id_registro_id',
        ).get()
        self.assertEqual(resultado['duplicadas'], 1)
        self.assertEqual(antes, despues)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.get().publicacion_id, completo.pk)

    def test_error_de_alias_revierte_solo_ese_elemento_y_el_lote_continua(self):
        primera = _noticia(self.fuente, url=f'https://{self.fuente.hosts_permitidos[0]}/uno')
        segunda = _noticia(self.fuente, url=f'https://{self.fuente.hosts_permitidos[0]}/dos')
        vincular_real = servicio.vincular_aliases_rss
        llamadas = 0

        def falla_una_vez(*args, **kwargs):
            nonlocal llamadas
            llamadas += 1
            if llamadas == 1:
                raise RuntimeError('fallo sintético después del INSERT')
            return vincular_real(*args, **kwargs)

        with patch.object(servicio, 'vincular_aliases_rss', side_effect=falla_una_vez):
            resultado = self._persistir(primera, segunda)
        self.assertEqual((resultado['errores'], resultado['nuevas']), (1, 1))
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(Publicacion.objects.get().url, segunda.url)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)

    def test_error_de_lectura_no_crea_registro_ni_publicacion(self):
        lector = Mock(side_effect=OSError('fallo HTTP sintético'))
        resultado = servicio.persistir_metadatos_rss(
            self.fuente.identificador, confirmar_persistencia=True, lector=lector,
        )
        self.assertEqual((resultado['estado'], resultado['errores']), ('ERROR', 1))
        self.assertEqual(resultado['causas'][0]['codigo'], 'consulta_rss_fallida')
        self.assertFalse(RegistroDatos.objects.exists())
        self.assertFalse(Publicacion.objects.exists())

    def test_comando_exige_autorizacion_configurada_y_confirmacion_por_ejecucion(self):
        salida = StringIO()
        lector = Mock(return_value=self._resultado(_noticia(self.fuente)))
        with override_settings(RSS_METADATOS_FUENTES_AUTORIZADAS=()):
            with self.assertRaises(CommandError):
                call_command(
                    'ingestar_rss_metadatos', '--fuente', self.fuente.identificador,
                    '--confirmar-persistencia', stdout=salida,
                )
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())
        with patch('core.services.persistencia_rss_metadatos.leer_rss', lector):
            with self.assertRaises(CommandError):
                call_command('ingestar_rss_metadatos', '--fuente', self.fuente.identificador)
            salida = StringIO()
            call_command(
                'ingestar_rss_metadatos', '--fuente', self.fuente.identificador,
                '--limite', '1', '--confirmar-persistencia', stdout=salida,
            )
        self.assertEqual(lector.call_count, 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertIn('"nuevas": 1', salida.getvalue())


@skipUnless(connection.vendor == 'postgresql', 'La concurrencia de advisory lock requiere PostgreSQL.')
class PersistenciaRSSMetadatosConcurrenciaTests(TransactionTestCase):
    reset_sequences = True

    def test_dos_procesos_mismo_alias_crean_una_sola_publicacion(self):
        fuente = FUENTES_RSS[0]
        noticia = _noticia(fuente, url=f'https://{fuente.hosts_permitidos[0]}/concurrente')
        barrera = Barrier(2)

        def lector(_fuente, *, limite_entradas):
            barrera.wait(timeout=10)
            return ResultadoRSS((noticia,), ())

        def ejecutar():
            close_old_connections()
            try:
                return servicio.persistir_metadatos_rss(
                    fuente.identificador,
                    limite=1,
                    confirmar_persistencia=True,
                    lector=lector,
                )
            finally:
                close_old_connections()

        with override_settings(RSS_METADATOS_FUENTES_AUTORIZADAS=(fuente.identificador,)):
            with ThreadPoolExecutor(max_workers=2) as ejecutor:
                resultados = list(ejecutor.map(lambda _: ejecutar(), range(2)))
        self.assertEqual(sum(r['nuevas'] for r in resultados), 1)
        self.assertEqual(sum(r['duplicadas'] for r in resultados), 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)
        self.assertEqual(RegistroDatos.objects.count(), 2)
        self.assertFalse(ProcesamientoIAMultifuente.objects.exists())
