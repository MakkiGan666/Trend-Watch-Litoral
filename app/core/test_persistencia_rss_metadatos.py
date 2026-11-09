"""H5.4: persistencia RSS simulada, sin red ni procesamiento de contenido."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta, timezone as datetime_timezone
from io import StringIO
from threading import Event
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, DatabaseError
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from core.models import (
    AliasURLPublicacion,
    Categoria,
    ControlSolicitudRSSMetadatos,
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
from core.services.descarga_segura import (
    MAX_RETRY_AFTER_SEGUNDOS,
    RespuestaHTTPError,
    _interpretar_retry_after,
    _retry_after_segundos,
)
from django.utils import timezone


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


class RetryAfterParserTests(SimpleTestCase):
    def test_acepta_delta_y_fecha_http_y_rechaza_valores_invalidos(self):
        ahora = timezone.now().astimezone(datetime_timezone.utc)
        fecha = (ahora + timedelta(seconds=120)).strftime('%a, %d %b %Y %H:%M:%S GMT')
        self.assertEqual(_retry_after_segundos('45', ahora=ahora), 45)
        self.assertGreaterEqual(_retry_after_segundos(fecha, ahora=ahora), 119)
        self.assertLessEqual(_retry_after_segundos(fecha, ahora=ahora), 120)
        self.assertIsNone(_retry_after_segundos('no es una fecha', ahora=ahora))
        self.assertIsNone(_retry_after_segundos(None, ahora=ahora))
        self.assertEqual(
            _interpretar_retry_after(str(MAX_RETRY_AFTER_SEGUNDOS + 1), ahora=ahora),
            (None, True),
        )
        fecha_excesiva = (ahora + timedelta(days=366)).strftime('%a, %d %b %Y %H:%M:%S GMT')
        self.assertEqual(_interpretar_retry_after(fecha_excesiva, ahora=ahora), (None, True))

    @patch('core.services.descarga_segura.socket.getaddrinfo', return_value=[
        (2, 1, 6, '', ('8.8.8.8', 443)),
    ])
    @patch('core.services.descarga_segura._Conexion')
    def test_transporte_entrega_429_y_retry_after_sin_leer_cuerpo(self, conexion_cls, _dns):
        from core.services import descarga_segura

        conexion = conexion_cls.return_value
        conexion.getresponse.return_value.status = 429
        conexion.getresponse.return_value.getheader.return_value = '37'
        with self.assertRaises(RespuestaHTTPError) as capturado:
            descarga_segura.descargar('https://www.elterritorio.com.ar/rss/misiones')
        self.assertEqual(capturado.exception.estado, 429)
        self.assertEqual(capturado.exception.retry_after_segundos, 37)
        conexion.getresponse.return_value.read1.assert_not_called()
        conexion.close.assert_called_once()

        conexion.getresponse.return_value.getheader.return_value = str(MAX_RETRY_AFTER_SEGUNDOS + 1)
        with self.assertRaises(RespuestaHTTPError) as excesivo:
            descarga_segura.descargar('https://www.elterritorio.com.ar/rss/misiones')
        self.assertTrue(excesivo.exception.retry_after_excesivo)
        self.assertIsNone(excesivo.exception.retry_after_segundos)


class PersistenciaRSSMetadatosTests(TestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[0]
        self.autorizacion = override_settings(
            RSS_METADATOS_FUENTES_AUTORIZADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 60},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        self.autorizacion.enable()
        self.addCleanup(self.autorizacion.disable)

    def _resultado(self, *noticias, rechazos=()):
        return ResultadoRSS(tuple(noticias), tuple(rechazos))

    def _persistir(self, *noticias, limite=5, lector=None, rechazos=()):
        # Las pruebas de idempotencia de H5.4 no miden espera temporal.
        hace_61 = timezone.now() - timedelta(seconds=61)
        ControlSolicitudRSSMetadatos.objects.filter(fuente_id=self.fuente.identificador).update(
            estado=ControlSolicitudRSSMetadatos.Estado.ESPERA,
            ultimo_intento=hace_61,
            retry_after_hasta=hace_61,
        )
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
        with override_settings(
            RSS_METADATOS_FUENTES_AUTORIZADAS=(),
            RSS_METADATOS_FUENTES_HABILITADAS=(),
            RSS_METADATOS_FUENTES_REVISADAS=(),
            RSS_METADATOS_LIMITES_POR_FUENTE={},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={},
        ):
            with self.assertRaises(servicio.AutorizacionMetadatosError):
                servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=lector,
                )
        with self.assertRaises(servicio.AutorizacionMetadatosError):
            servicio.persistir_metadatos_rss(self.fuente.identificador, lector=lector)
        lector.assert_not_called()
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())

    def test_exige_habilitacion_y_revision_independientes_antes_de_la_peticion(self):
        lector = Mock()
        escenarios = (
            {'RSS_METADATOS_FUENTES_HABILITADAS': ()},
            {'RSS_METADATOS_FUENTES_REVISADAS': ()},
        )
        for politica in escenarios:
            with self.subTest(politica=politica), override_settings(**politica):
                with self.assertRaises(servicio.AutorizacionMetadatosError):
                    servicio.persistir_metadatos_rss(
                        self.fuente.identificador, confirmar_persistencia=True, lector=lector,
                    )
        lector.assert_not_called()
        self.assertFalse(ControlSolicitudRSSMetadatos.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())

    def test_limite_por_fuente_es_obligatorio_y_no_se_puede_superar(self):
        lector = Mock()
        with override_settings(RSS_METADATOS_LIMITES_POR_FUENTE={}):
            with self.assertRaises(servicio.AutorizacionMetadatosError):
                servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=lector,
                )
        with override_settings(RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 1}):
            with self.assertRaises(ValueError):
                servicio.persistir_metadatos_rss(
                    self.fuente.identificador, limite=2,
                    confirmar_persistencia=True, lector=lector,
                )
        lector.assert_not_called()

    def test_intervalo_minimo_bloquea_una_segunda_solicitud_y_es_por_fuente(self):
        lector = Mock(return_value=self._resultado())
        primero = servicio.persistir_metadatos_rss(
            self.fuente.identificador, confirmar_persistencia=True, lector=lector,
        )
        segundo = servicio.persistir_metadatos_rss(
            self.fuente.identificador, confirmar_persistencia=True, lector=lector,
        )
        otra = FUENTES_RSS[1]
        autorizaciones_otra = override_settings(
            RSS_METADATOS_FUENTES_AUTORIZADAS=(self.fuente.identificador, otra.identificador),
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador, otra.identificador),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador, otra.identificador),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5, otra.identificador: 1},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={
                self.fuente.identificador: 60, otra.identificador: 60,
            },
        )
        with autorizaciones_otra:
            independiente = servicio.persistir_metadatos_rss(
                otra.identificador, limite=1, confirmar_persistencia=True, lector=lector,
            )
        self.assertEqual(primero['estado'], 'EXITO')
        self.assertEqual(segundo['estado'], 'BLOQUEADA')
        self.assertGreater(segundo['espera_segundos'], 0)
        self.assertEqual(independiente['estado'], 'EXITO')
        self.assertEqual(lector.call_count, 2)

    def test_http_429_persiste_retry_after_y_no_reintenta(self):
        lector = Mock(side_effect=RespuestaHTTPError(429, 3600))
        primer = servicio.persistir_metadatos_rss(
            self.fuente.identificador, confirmar_persistencia=True, lector=lector,
        )
        segundo = servicio.persistir_metadatos_rss(
            self.fuente.identificador, confirmar_persistencia=True, lector=lector,
        )
        control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
        self.assertEqual(primer['estado'], 'ERROR')
        self.assertEqual(primer['causas'][0]['codigo'], 'http_429')
        self.assertEqual(primer['causas'][0]['http_status'], 429)
        self.assertEqual(primer['espera_segundos'], 3600)
        self.assertGreater(control.retry_after_hasta, timezone.now())
        self.assertEqual(segundo['estado'], 'BLOQUEADA')
        self.assertEqual(lector.call_count, 1)

    def test_429_sin_header_aplica_espera_conservadora_configurada(self):
        lector = Mock(side_effect=RespuestaHTTPError(429))
        with override_settings(RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=7200):
            resultado = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=lector,
            )
        self.assertEqual(resultado['espera_segundos'], 7200)
        restante = (
            ControlSolicitudRSSMetadatos.objects.get().retry_after_hasta - timezone.now()
        ).total_seconds()
        self.assertGreater(restante, 7190)
        self.assertLessEqual(restante, 7200)

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


class ControlSolicitudRSSMetadatosDurableTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.fuente = FUENTES_RSS[0]

    def _politica(self, fuentes=None, intervalo=60):
        fuentes = tuple(fuentes or (self.fuente.identificador,))
        return override_settings(
            RSS_METADATOS_FUENTES_AUTORIZADAS=fuentes,
            RSS_METADATOS_FUENTES_HABILITADAS=fuentes,
            RSS_METADATOS_FUENTES_REVISADAS=fuentes,
            RSS_METADATOS_LIMITES_POR_FUENTE={id_fuente: 1 for id_fuente in fuentes},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={
                id_fuente: intervalo for id_fuente in fuentes
            },
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )

    def test_reserva_esta_confirmada_antes_del_get_y_luego_conserva_intervalo(self):
        lector = Mock()

        def leer(fuente, *, limite_entradas):
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=fuente.identificador)
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.EN_CURSO)
            self.assertIsNotNone(control.ultimo_intento)
            return ResultadoRSS((), ())

        lector.side_effect = leer
        with self._politica():
            resultado = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=lector,
            )
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
            self.assertEqual(resultado['estado'], 'EXITO')
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)
            self.assertGreaterEqual(
                (control.retry_after_hasta - control.ultimo_intento).total_seconds(), 60,
            )
            segunda = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=lector,
            )
        self.assertEqual(segunda['estado'], 'BLOQUEADA')
        lector.assert_called_once()

    def test_fallo_al_guardar_429_deja_en_curso_y_exige_recuperacion_explicita(self):
        lector = Mock(side_effect=RespuestaHTTPError(429, 3600))
        with self._politica():
            with patch.object(servicio, '_finalizar_solicitud', side_effect=DatabaseError('fallo simulado')):
                primero = servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=lector,
                )
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.EN_CURSO)
            self.assertTrue(primero['revision_manual_requerida'])
            segundo_lector = Mock(return_value=ResultadoRSS((), ()))
            segundo = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=segundo_lector,
            )
            self.assertEqual(segundo['estado'], 'BLOQUEADA')
            self.assertTrue(segundo['revision_manual_requerida'])
            segundo_lector.assert_not_called()
            with self.assertRaises(CommandError):
                call_command('resolver_bloqueo_rss_metadatos', '--fuente', self.fuente.identificador)
            salida = StringIO()
            call_command(
                'resolver_bloqueo_rss_metadatos', '--fuente', self.fuente.identificador,
                '--confirmar-revision-manual', stdout=salida,
            )
            control.refresh_from_db()
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)
            self.assertGreater(control.retry_after_hasta, timezone.now())
            tercera = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=segundo_lector,
            )
        self.assertEqual(tercera['estado'], 'BLOQUEADA')
        segundo_lector.assert_not_called()

    def test_fallo_al_persistir_resultado_de_feed_deja_reserva_en_curso(self):
        lector = Mock(return_value=ResultadoRSS((_noticia(self.fuente),), ()))
        with self._politica():
            with patch.object(servicio, '_finalizar_solicitud', side_effect=DatabaseError('fallo simulado')):
                primero = servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=lector,
                )
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.EN_CURSO)
            self.assertTrue(primero['revision_manual_requerida'])
            self.assertEqual(Publicacion.objects.count(), 1)
            segundo_lector = Mock(return_value=ResultadoRSS((), ()))
            segunda = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=segundo_lector,
            )
        self.assertEqual(segunda['estado'], 'BLOQUEADA')
        segundo_lector.assert_not_called()

    def test_interrupcion_entre_reserva_y_resultado_bloquea_hasta_revision_manual(self):
        lector = Mock(return_value=ResultadoRSS((), ()))
        with self._politica():
            servicio._reservar_solicitud(self.fuente, 60)  # Simula proceso muerto tras confirmar EN_CURSO.
            close_old_connections()
            resultado = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=lector,
            )
            self.assertEqual(resultado['estado'], 'BLOQUEADA')
            self.assertTrue(resultado['revision_manual_requerida'])
            lector.assert_not_called()
            resuelto = servicio.resolver_bloqueo_pendiente(
                self.fuente.identificador, confirmar_revision_manual=True,
            )
            self.assertEqual(resuelto['estado'], ControlSolicitudRSSMetadatos.Estado.ESPERA)
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
            self.assertGreaterEqual(
                (control.retry_after_hasta - timezone.now()).total_seconds(), 59,
            )

    def test_segunda_ejecucion_concurrente_no_consulta_mientras_primera_sigue_en_curso(self):
        iniciada = Event()
        liberar = Event()
        primer_lector = Mock()

        def leer_primera(fuente, *, limite_entradas):
            iniciada.set()
            if not liberar.wait(timeout=10):
                raise AssertionError('La prueba no liberó la primera consulta simulada.')
            return ResultadoRSS((), ())

        primer_lector.side_effect = leer_primera
        segundo_lector = Mock(return_value=ResultadoRSS((), ()))

        def ejecutar_primera():
            close_old_connections()
            try:
                return servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=primer_lector,
                )
            finally:
                close_old_connections()

        with self._politica():
            with ThreadPoolExecutor(max_workers=1) as ejecutor:
                primera = ejecutor.submit(ejecutar_primera)
                self.assertTrue(iniciada.wait(timeout=5))
                segunda = servicio.persistir_metadatos_rss(
                    self.fuente.identificador, confirmar_persistencia=True, lector=segundo_lector,
                )
                self.assertEqual(segunda['estado'], 'BLOQUEADA')
                segundo_lector.assert_not_called()
                liberar.set()
                resultado_primero = primera.result(timeout=10)

        self.assertEqual(resultado_primero['estado'], 'EXITO')
        primer_lector.assert_called_once()
        control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
        self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)

    def test_retry_after_excesivo_pasa_a_revision_manual_y_no_se_acorta(self):
        lector = Mock(side_effect=RespuestaHTTPError(429, None, retry_after_excesivo=True))
        segundo_lector = Mock(return_value=ResultadoRSS((), ()))
        with self._politica():
            resultado = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=lector,
            )
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL)
            self.assertIsNone(control.retry_after_hasta)
            self.assertTrue(resultado['revision_manual_requerida'])
            otra = servicio.persistir_metadatos_rss(
                self.fuente.identificador, confirmar_persistencia=True, lector=segundo_lector,
            )
            with self.assertRaises(servicio.AutorizacionMetadatosError):
                servicio.resolver_bloqueo_pendiente(
                    self.fuente.identificador, confirmar_revision_manual=True,
                )
            servicio.resolver_bloqueo_pendiente(
                self.fuente.identificador,
                confirmar_revision_manual=True,
                confirmar_retry_after_vencido=True,
            )
        self.assertEqual(otra['estado'], 'BLOQUEADA')
        segundo_lector.assert_not_called()


@skipUnless(connection.vendor == 'postgresql', 'La concurrencia de advisory lock requiere PostgreSQL.')
class PersistenciaRSSMetadatosConcurrenciaTests(TransactionTestCase):
    reset_sequences = True

    def test_dos_procesos_mismo_alias_crean_una_sola_publicacion(self):
        fuente = FUENTES_RSS[0]
        noticia = _noticia(fuente, url=f'https://{fuente.hosts_permitidos[0]}/concurrente')
        lector = Mock(return_value=ResultadoRSS((noticia,), ()))

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

        with override_settings(
            RSS_METADATOS_FUENTES_AUTORIZADAS=(fuente.identificador,),
            RSS_METADATOS_FUENTES_HABILITADAS=(fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={fuente.identificador: 1},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={fuente.identificador: 60},
        ):
            with ThreadPoolExecutor(max_workers=2) as ejecutor:
                resultados = list(ejecutor.map(lambda _: ejecutar(), range(2)))
        self.assertEqual(sum(r['nuevas'] for r in resultados), 1)
        self.assertEqual(sum(r['estado'] == 'BLOQUEADA' for r in resultados), 1)
        lector.assert_called_once()
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)
        self.assertEqual(RegistroDatos.objects.count(), 1)
        self.assertFalse(ProcesamientoIAMultifuente.objects.exists())
