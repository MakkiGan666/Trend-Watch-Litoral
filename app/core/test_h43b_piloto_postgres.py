"""H4.3-B: piloto sintético en PostgreSQL efímero, sin red externa ni Gemini."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape
import json
import os
import secrets
import socket
import sys

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import override_settings
from django.urls import reverse
from unittest import skipUnless

from core.models import AliasURLPublicacion, ProcesamientoIAMultifuente, Publicacion, RegistroDatos
from core.services import (descarga_segura as red, extractor_articulos, fuentes_rss,
                           gemini_multifuente, orquestador_multifuente,
                           persistencia_multifuente)


_RUTA_ATTESTATION = '/evidence/attestation.json'
_BASE_DB = 'tw_h43b_test'
_TEST_DB = 'test_tw_h43b_test'
_DB_USER = 'tw_h43b_test'


def _aislamiento_valido(configuracion, nombre_test, interfaces, attestation, nonce):
    """Requiere prueba temporal verificada, configuración sintética y netns aislado."""
    if not isinstance(attestation, dict):
        return False
    test_db = configuracion.get('TEST') or {}
    return all((
        configuracion.get('ENGINE') == 'django.db.backends.postgresql',
        configuracion.get('HOST') == '127.0.0.1',
        str(configuracion.get('PORT')) == '5432',
        configuracion.get('NAME') == _BASE_DB,
        configuracion.get('USER') == _DB_USER,
        configuracion.get('PASSWORD') == 'synthetic-only',
        not configuracion.get('OPTIONS'),
        not test_db.get('MIRROR'),
        test_db.get('NAME') in (None, _TEST_DB),
        nombre_test == _TEST_DB,
        set(interfaces) == {'lo'},
        attestation.get('version') == 1,
        isinstance(attestation.get('container_name'), str)
        and attestation['container_name'].startswith('tw-h43b-pilot-'),
        isinstance(attestation.get('container_id'), str)
        and len(attestation['container_id']) == 64
        and all(caracter in '0123456789abcdef' for caracter in attestation['container_id']),
        attestation.get('network_mode') == 'none',
        attestation.get('published_ports') is False,
        attestation.get('pgdata_tmpfs') is True,
        attestation.get('database_name') == _BASE_DB,
        attestation.get('test_database_name') == _TEST_DB,
        _identidad_cluster_valida(attestation.get('cluster_system_identifier')),
        isinstance(nonce, str) and len(nonce) == 64
        and secrets.compare_digest(attestation.get('nonce', ''), nonce),
    ))


def _identidad_cluster_valida(identidad):
    return isinstance(identidad, str) and identidad.isascii() and identidad.isdecimal() \
        and 1 <= len(identidad) <= 20


def _identidad_cluster_coincide(identidad_real, identidad_atestada):
    return _identidad_cluster_valida(identidad_real) \
        and _identidad_cluster_valida(identidad_atestada) \
        and secrets.compare_digest(identidad_real, identidad_atestada)


def _identidad_cluster_configurado():
    """Lee la identidad del destino sin pasar por conexiones/escrituras del runner."""
    conexion = None
    try:
        parametros = connection.get_connection_params()
        conexion = connection.Database.connect(**parametros)
        conexion.autocommit = True
        with conexion.cursor() as cursor:
            cursor.execute('BEGIN READ ONLY')
            cursor.execute('SELECT system_identifier::text FROM pg_control_system()')
            fila = cursor.fetchone()
            cursor.execute('ROLLBACK')
        identidad = fila[0] if fila else None
        return identidad if _identidad_cluster_valida(identidad) else None
    except Exception:
        return None
    finally:
        if conexion is not None:
            try:
                conexion.close()
            except Exception:
                pass


def _leer_atestacion():
    if os.environ.get('H43B_ISOLATION_ATTESTATION') != _RUTA_ATTESTATION:
        return None
    try:
        ruta = Path(_RUTA_ATTESTATION)
        if ruta.stat().st_size > 4096:
            return None
        return json.loads(ruta.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None


_ATESTACION = _leer_atestacion()
_AISLAMIENTO_ESTATICO_VALIDO = _aislamiento_valido(
    connection.settings_dict,
    connection.creation._get_test_db_name(),
    [nombre for _, nombre in socket.if_nameindex()],
    _ATESTACION,
    os.environ.get('H43B_ISOLATION_NONCE'),
)
_IDENTIDAD_REAL_CLUSTER = (
    _identidad_cluster_configurado() if _AISLAMIENTO_ESTATICO_VALIDO else None
)
_PILOTO_AISLADO = _AISLAMIENTO_ESTATICO_VALIDO and _identidad_cluster_coincide(
    _IDENTIDAD_REAL_CLUSTER,
    (_ATESTACION or {}).get('cluster_system_identifier'),
)
_SOLICITUD_DIRECTA = any(
    'test_h43b_piloto_postgres' in argumento for argumento in sys.argv[1:]
)
if not _PILOTO_AISLADO and _SOLICITUD_DIRECTA:
    # Ocurre durante discovery, antes de DiscoverRunner.setup_databases().
    raise SystemExit(
        'H4.3-B requiere tools/run_h43b_piloto_postgres.sh; '
        'se rechazó antes de preparar la base de test.'
    )

_BasePiloto = TransactionTestCase if _PILOTO_AISLADO else SimpleTestCase


class ProteccionAislamientoH43BTests(SimpleTestCase):
    def test_rechaza_configuracion_sin_atestacion_o_con_aislamiento_incompleto(self):
        configuracion = {
            'ENGINE': 'django.db.backends.postgresql', 'HOST': '127.0.0.1',
            'PORT': '5432', 'NAME': _BASE_DB, 'USER': _DB_USER, 'TEST': {},
            'PASSWORD': 'synthetic-only',
        }
        nonce = 'a' * 64
        atestacion = {
            'version': 1, 'container_name': 'tw-h43b-pilot-test',
            'container_id': 'a' * 64,
            'network_mode': 'none', 'published_ports': False, 'pgdata_tmpfs': True,
            'database_name': _BASE_DB, 'test_database_name': _TEST_DB,
            'cluster_system_identifier': '7654321098765432109', 'nonce': nonce,
        }
        argumentos = (configuracion, _TEST_DB, ['lo'], atestacion, nonce)
        self.assertTrue(_aislamiento_valido(*argumentos))
        self.assertFalse(_aislamiento_valido(configuracion, _TEST_DB, ['lo'], None, nonce))

        variantes = (
            ({**configuracion, 'HOST': 'db'}, atestacion, ['lo']),
            ({**configuracion, 'NAME': 'produccion'}, atestacion, ['lo']),
            ({**configuracion, 'PASSWORD': 'real-secret'}, atestacion, ['lo']),
            ({**configuracion, 'OPTIONS': {'hostaddr': '192.0.2.10'}}, atestacion, ['lo']),
            ({**configuracion, 'TEST': {'MIRROR': 'default'}}, atestacion, ['lo']),
            ({**configuracion, 'TEST': {'NAME': 'test_other'}}, atestacion, ['lo']),
            (configuracion, {**atestacion, 'network_mode': 'bridge'}, ['lo']),
            (configuracion, {**atestacion, 'published_ports': True}, ['lo']),
            (configuracion, {**atestacion, 'pgdata_tmpfs': False}, ['lo']),
            (configuracion, {**atestacion, 'cluster_system_identifier': 'not-an-id'}, ['lo']),
            (configuracion, atestacion, ['lo', 'eth0']),
        )
        for config, attestation, interfaces in variantes:
            with self.subTest(config=config, attestation=attestation, interfaces=interfaces):
                self.assertFalse(_aislamiento_valido(
                    config, _TEST_DB, interfaces, attestation, nonce))

    def test_rechaza_identidad_de_cluster_diferente(self):
        identidad_real = '7654321098765432109'
        identidad_atestada = '1234567890123456789'
        self.assertTrue(_identidad_cluster_valida(identidad_real))
        self.assertTrue(_identidad_cluster_coincide(identidad_real, identidad_real))
        self.assertFalse(_identidad_cluster_coincide(identidad_real, identidad_atestada))


class _Respuesta:
    status = 200

    def __init__(self, cuerpo):
        self.cuerpo = cuerpo
        self.posicion = 0

    def getheader(self, nombre):
        return None

    def read1(self, cantidad):
        bloque = self.cuerpo[self.posicion:self.posicion + cantidad]
        self.posicion += len(bloque)
        return bloque


@skipUnless(_PILOTO_AISLADO, 'Requiere el lanzador PostgreSQL efímero verificado.')
class PilotoNoticiasDel6PostgreSQLTests(_BasePiloto):
    reset_sequences = True

    def setUp(self):
        originales = fuentes_rss.FUENTES_RSS
        piloto = next(f for f in originales if f.identificador == 'noticias_del_6')
        self.catalogo = tuple(replace(f, habilitada=(f.identificador == piloto.identificador))
                              for f in originales)
        self.fuente = next(f for f in self.catalogo if f.identificador == piloto.identificador)
        self.original_habilitada = piloto.habilitada
        self.respuestas = {}
        self.peticiones = []
        contexto = ExitStack()
        self.addCleanup(contexto.close)
        for modulo in (fuentes_rss, red, extractor_articulos,
                       persistencia_multifuente, gemini_multifuente):
            contexto.enter_context(patch.object(modulo, 'FUENTES_RSS', self.catalogo))
        for destino in ('socket.socket.connect', 'socket.socket.connect_ex',
                        'urllib.request.urlopen', 'feedparser.http.get'):
            contexto.enter_context(patch(destino, side_effect=AssertionError('Red externa prohibida.')))
        destino_publico = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        contexto.enter_context(patch.object(red.socket, 'getaddrinfo', return_value=[destino_publico]))
        contexto.enter_context(patch.object(red, '_Conexion', side_effect=self._conexion))
        self.gemini = contexto.enter_context(patch.object(
            gemini_multifuente, 'procesar_nuevas', side_effect=AssertionError('Gemini prohibido.')))
        self.clasificacion_ia = contexto.enter_context(patch(
            'core.services.clasificacion._clasificar_con_ia',
            side_effect=AssertionError('Gemini de clasificación prohibido.')))

    def _conexion(self, host, destino, timeout):
        conexion = Mock(sock=None)

        def solicitar(metodo, ruta, **kwargs):
            url = 'https://' + host + ruta
            self.peticiones.append(url)
            if url not in self.respuestas:
                raise OSError('Respuesta sintética no configurada.')
            cuerpo = self.respuestas[url]
            if isinstance(cuerpo, Exception):
                raise cuerpo
            conexion.getresponse.return_value = _Respuesta(cuerpo)

        conexion.request.side_effect = solicitar
        return conexion

    def _feed(self, filas):
        items = ''.join(
            '<item><title>Ensayo sintético H43B</title><link>' + escape(url)
            + '</link><pubDate>Fri, 06 Nov 2026 12:00:00 GMT</pubDate>'
            '<description>Resumen sintético, no persistir como cuerpo.</description></item>'
            for url in filas
        )
        self.respuestas[self.fuente.feed] = (
            '<rss version="2.0"><channel><title>Feed sintético H43B</title>'
            + items + '</channel></rss>'
        ).encode()

    def _html_valido(self, canonic_path='/h43b/canonica'):
        cuerpo = (
            'Contenido sintético de prueba para verificar persistencia multifuente. '
            'Este texto no corresponde a una noticia real y supera deliberadamente '
            'el mínimo local de longitud y cantidad de palabras para el extractor. '
            'Se usa únicamente en una base efímera sin conexión externa.'
        )
        return (
            '<html><head><meta property="og:title" content="Artículo sintético H43B">'
            '<meta property="article:published_time" content="2026-11-06T12:00:00Z">'
            '<meta property="og:image" content="/assets/h43b-sintetica.png">'
            '<link rel="canonical" href="' + canonic_path + '"></head><body><article>'
            '<h1>Artículo sintético H43B</h1><div class="entry-content"><p>' + cuerpo
            + '</p></div><img src="/assets/h43b-sintetica.png"></article></body></html>'
        ).encode()

    def _ejecutar(self, *, limite=1):
        salida = StringIO()
        call_command('ingestar_multifuente', '--fuente', self.fuente.identificador,
                     '--limite-fuente', str(limite), '--limite-total', str(limite),
                     '--sin-ia', stdout=salida)
        return json.loads(salida.getvalue())

    def test_comando_persistencia_alias_reintento_api_y_territorio_intacto(self):
        rss_url = 'https://noticiasdel6.com/h43b/sintetica'
        canonical_url = 'https://noticiasdel6.com/h43b/canonica'
        self._feed([rss_url])
        self.respuestas[rss_url] = self._html_valido()

        registro_territorio = RegistroDatos.objects.create(
            fuentes_api='El Territorio', fecha_ejecucion=datetime(2026, 11, 6, tzinfo=timezone.utc),
            estado='EXITO', lenguaje='es')
        territorio = Publicacion.objects.create(
            hash_origen='h43b-territorio-sintetico', fuente='El Territorio',
            titulo='Registro histórico sintético', contenido='Contenido histórico sintético.',
            url='https://www.elterritorio.com.ar/h43b-sintetica', id_registro=registro_territorio)
        territorio_antes = Publicacion.objects.filter(pk=territorio.pk).values().get()
        registros_antes = RegistroDatos.objects.count()

        with override_settings(GEMINI_API_KEY='', GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=()):
            orquestador_multifuente.verificar_esquema_multifuente()
            with connection.cursor() as cursor:
                cursor.execute('SHOW transaction_isolation')
                self.assertEqual(cursor.fetchone()[0], 'read committed')
            self.assertEqual(Publicacion.objects.count(), 1)
            self.assertEqual(RegistroDatos.objects.count(), registros_antes)
            primero = self._ejecutar()
            self.assertEqual(primero['estado'], 'EXITO')
            self.assertEqual(primero['errores'], [])
            self.assertEqual((primero['descargadas'], primero['nuevas'], primero['duplicadas']), (2, 1, 0))
            # Sin autorización Gemini la cola conserva PENDIENTE, pero el resumen
            # cuenta sólo trabajos elegibles para el procesador de IA.
            self.assertEqual(primero['pendientes_ia'], 0)
            self.assertFalse(primero['procesar_ia'])

            publicacion = Publicacion.objects.get(fuente=self.fuente.nombre)
            self.assertEqual(publicacion.url, canonical_url)
            self.assertEqual(publicacion.titulo, 'Artículo sintético H43B')
            self.assertTrue(publicacion.contenido.startswith('Contenido sintético'))
            self.assertEqual(publicacion.fecha_publicacion, datetime(2026, 11, 6, 12, tzinfo=timezone.utc))
            self.assertTrue(publicacion.imagen_url.endswith('/assets/h43b-sintetica.png'))
            self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'PENDIENTE')
            aliases = AliasURLPublicacion.objects.filter(publicacion=publicacion).order_by(
                'url_normalizada').values_list('fuente', 'url_normalizada')
            self.assertEqual(set(aliases), {
                (self.fuente.identificador, rss_url),
                (self.fuente.identificador, canonical_url),
            })

            html_count = self.peticiones.count(rss_url)
            segundo = self._ejecutar()
            self.assertEqual(segundo['estado'], 'EXITO')
            self.assertEqual((segundo['nuevas'], segundo['duplicadas']), (0, 1))
            self.assertEqual(Publicacion.objects.filter(fuente=self.fuente.nombre).count(), 1)
            self.assertEqual(AliasURLPublicacion.objects.filter(publicacion=publicacion).count(), 2)
            self.assertEqual(ProcesamientoIAMultifuente.objects.filter(publicacion=publicacion).count(), 1)
            self.assertEqual(self.peticiones.count(rss_url), html_count)

            response = self.client.get(reverse('listar_publicaciones'))
            self.assertEqual(response.status_code, 200)
            filas_publicas = response.json()['data']
            self.assertIn(publicacion.pk, [fila['id'] for fila in filas_publicas])
            self.assertIn(territorio.pk, [fila['id'] for fila in filas_publicas])

        territorio.refresh_from_db()
        self.assertEqual(Publicacion.objects.filter(pk=territorio.pk).values().get(), territorio_antes)
        self.assertEqual(Publicacion.objects.filter(fuente='El Territorio').count(), 1)
        self.assertEqual(RegistroDatos.objects.filter(pk=registro_territorio.pk).count(), 1)
        self.assertEqual(self.original_habilitada, False)
        self.assertFalse(any(f.habilitada for f in fuentes_rss.FUENTES_RSS if f != self.fuente))
        self.gemini.assert_not_called()
        self.clasificacion_ia.assert_not_called()
        self.assertEqual(self.peticiones.count(self.fuente.feed), 2)

    def test_aisla_error_de_articulo_y_persiste_el_valido(self):
        host = self.fuente.hosts_permitidos[0]
        rechazado = 'https://' + host + '/h43b/rechazada'
        valido = 'https://' + host + '/h43b/valida'
        self._feed([rechazado, valido])
        self.respuestas[rechazado] = (
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","url":"https://example.invalid/noticia"}'
            '</script><article><p>Artículo sintético que declara identidad ajena.</p></article>'
        ).encode()
        self.respuestas[valido] = self._html_valido('/h43b/valida-canonica')

        with override_settings(GEMINI_API_KEY='', GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=()):
            resultado = self._ejecutar(limite=2)

        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual((resultado['nuevas'], resultado['rechazadas']), (1, 1))
        self.assertEqual(Publicacion.objects.filter(fuente=self.fuente.nombre).count(), 1)
        self.assertEqual(Publicacion.objects.get(fuente=self.fuente.nombre).url,
                         'https://' + host + '/h43b/valida-canonica')
        self.assertEqual(AliasURLPublicacion.objects.count(), 2)
        self.assertEqual(ProcesamientoIAMultifuente.objects.count(), 1)
        self.assertEqual(self.peticiones, [self.fuente.feed, rechazado, valido])
        self.gemini.assert_not_called()
        self.clasificacion_ia.assert_not_called()
