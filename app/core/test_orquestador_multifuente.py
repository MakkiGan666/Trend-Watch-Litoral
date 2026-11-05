"""H4.1: integración real de servicios y ORM, transporte HTTP simulado sin red."""
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape
import json
import socket

from django.apps import apps
from django.db import connection, connections, models
from django.db.migrations.state import ProjectState
from django.test.utils import CaptureQueriesContext
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from google.genai import types

from core.models import AliasURLPublicacion, Publicacion, RegistroDatos, ProcesamientoIAMultifuente
from core.services import (descarga_segura as red, extractor_articulos, fuentes_rss,
                          gemini_multifuente, persistencia_multifuente, orquestador_multifuente as servicio)


class RespuestaHTTP:
    def __init__(self, cuerpo, status=200, location=None):
        self.cuerpo, self.status, self.location, self.posicion = cuerpo, status, location, 0

    def getheader(self, nombre):
        return self.location if nombre == 'Location' else None

    def read1(self, cantidad):
        bloque = self.cuerpo[self.posicion:self.posicion + cantidad]
        self.posicion += len(bloque)
        return bloque


class OrquestadorMultifuenteTests(TransactionTestCase):
    def setUp(self):
        self.original = fuentes_rss.FUENTES_RSS
        self.catalogo = tuple(replace(f, habilitada=i < 2) for i, f in enumerate(self.original))
        self.fuente, self.otra = self.catalogo[:2]
        self.respuestas, self.peticiones = {}, []
        contexto = ExitStack()
        self.addCleanup(contexto.close)
        # Simula una configuración aprobada al importar, no una activación del comando.
        for modulo in (fuentes_rss, red, extractor_articulos, persistencia_multifuente, gemini_multifuente):
            contexto.enter_context(patch.object(modulo, 'FUENTES_RSS', self.catalogo))
        for destino in ('socket.socket.connect', 'socket.socket.connect_ex', 'urllib.request.urlopen', 'feedparser.http.get'):
            contexto.enter_context(patch(destino, side_effect=AssertionError('Red real prohibida')))
        publica = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        contexto.enter_context(patch.object(red.socket, 'getaddrinfo', return_value=[publica]))
        contexto.enter_context(patch.object(red, '_Conexion', side_effect=self.conectar))
        self.procesar_original = gemini_multifuente.procesar_nuevas
        self.gemini_prohibido = contexto.enter_context(patch.object(
            gemini_multifuente, 'procesar_nuevas', side_effect=AssertionError('Gemini requiere opt-in explícito')))

    def conectar(self, host, destino, timeout):
        conexion = Mock(sock=None)
        def request(metodo, ruta, **kwargs):
            url = 'https://' + host + ruta
            self.peticiones.append(url)
            if url not in self.respuestas:
                raise OSError('Destino simulado sin fixture')
            respuesta = self.respuestas[url]
            if isinstance(respuesta, Exception):
                raise respuesta
            if isinstance(respuesta, tuple):
                cuerpo, status, location = respuesta
            else:
                cuerpo, status, location = respuesta, 200, None
            conexion.getresponse.return_value = RespuestaHTTP(cuerpo, status, location)
        conexion.request.side_effect = request
        return conexion

    def html(self):
        return (Path(__file__).parent / 'fixtures' / 'articulos' / 'semantico.html').read_bytes()

    def feed(self, fuente, urls, *, invalida=False):
        items = ''.join('<item><title>Jornada de salud</title><link>' + escape(url)
                        + '</link><description>Resumen breve</description></item>' for url in urls)
        if invalida:
            items = '<item><title>Sin enlace</title></item>' + items
        self.respuestas[fuente.feed] = ('<rss version="2.0"><channel><title>Medio</title>' + items + '</channel></rss>').encode()
        for url in urls:
            if url.startswith('https://') and not url.startswith('https://evil.org'):
                self.respuestas[url] = self.html()

    def ejecutar(self, **kwargs):
        return servicio.ejecutar_ingesta_multifuente([self.fuente.identificador], **kwargs)

    def test_catalogo_real_deshabilitado_no_descarga_ni_escribe(self):
        with patch.object(fuentes_rss, 'FUENTES_RSS', self.original), self.assertRaises(ValueError):
            self.ejecutar()
        self.assertFalse(self.peticiones)
        self.assertFalse(RegistroDatos.objects.exists())
        self.assertFalse(any(f.habilitada for f in self.original))

    def test_seleccion_explicita_y_parametros_invalidos_sin_efectos(self):
        for seleccion in ([], 'misiones_online', ['desconocida'], ['el_territorio'], [None]):
            with self.subTest(seleccion=seleccion), self.assertRaises(ValueError):
                servicio.ejecutar_ingesta_multifuente(seleccion)
        for opciones in ({'limite_total': 0}, {'limite_por_fuente': True}, {'limite_por_fuente': 31},
                         {'limite_total': 101}, {'limite_ia': 21}, {'dry_run': 1}, {'procesar_ia': 'true'}):
            with self.subTest(opciones=opciones), self.assertRaises(ValueError):
                self.ejecutar(**opciones)
        self.assertFalse(self.peticiones)
        self.assertFalse(RegistroDatos.objects.exists())

    def test_integra_transporte_lector_html_persistencia_y_cola_sin_gemini(self):
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        resultado = self.ejecutar()
        self.assertEqual(resultado['errores'], [])
        self.assertEqual((resultado['descargadas'], resultado['validas'], resultado['nuevas']), (2, 1, 1))
        self.assertEqual(resultado['pendientes_ia'], 1)
        self.assertEqual(Publicacion.objects.get().titulo, 'Nueva biblioteca local')
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'PENDIENTE')
        self.gemini_prohibido.assert_not_called()

    def test_dry_run_descarga_valida_sin_escrituras_ni_gemini(self):
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        resultado = self.ejecutar(dry_run=True, procesar_ia=True)
        self.assertEqual((resultado['nuevas'], resultado['previstas']), (0, 1))
        self.assertEqual((resultado['pendientes_ia'], resultado['pendientes_ia_previstas']), (0, 1))
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())
        self.assertFalse(ProcesamientoIAMultifuente.objects.exists())
        self.gemini_prohibido.assert_not_called()

    def test_deduplica_urls_tracking_y_fuentes_repetidas_sin_repetir_html(self):
        urls = ['https://misionesonline.net/nota?utm_source=rss', 'https://misionesonline.net/nota?fbclid=123']
        self.feed(self.fuente, urls)
        self.respuestas['https://misionesonline.net/nota'] = self.html()
        resultado = servicio.ejecutar_ingesta_multifuente([self.fuente.identificador] * 2)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual((resultado['nuevas'], resultado['duplicadas']), (1, 1))
        self.assertEqual(self.peticiones, [self.fuente.feed, 'https://misionesonline.net/nota'])
        resultado = self.ejecutar()
        self.assertEqual((resultado['nuevas'], resultado['duplicadas']), (0, 2))
        self.assertEqual(self.peticiones.count('https://misionesonline.net/nota'), 1)

    def test_limites_por_fuente_y_total_sin_modificar_politica(self):
        self.feed(self.fuente, [f'https://misionesonline.net/n{i}' for i in range(4)])
        self.feed(self.otra, [f'https://www.primeraedicion.com.ar/n{i}' for i in range(4)])
        resultado = servicio.ejecutar_ingesta_multifuente(
            [self.fuente.identificador, self.otra.identificador], limite_por_fuente=2, limite_total=3)
        self.assertEqual(resultado['nuevas'], 3)
        self.assertEqual([r['nuevas'] for r in resultado['fuentes']], [2, 1])
        self.assertTrue(resultado['limitada'])
        self.assertEqual(len(self.peticiones), 5)  # Dos RSS y tres artículos.
        self.assertEqual(self.fuente.limite_noticias, 30)

    def test_presupuesto_agotado_no_descarga_la_siguiente_fuente(self):
        self.feed(self.fuente, ['https://misionesonline.net/uno'])
        resultado = servicio.ejecutar_ingesta_multifuente(
            [self.fuente.identificador, self.otra.identificador], limite_total=1)
        self.assertNotIn(self.otra.feed, self.peticiones)
        self.assertTrue(resultado['fuentes'][1]['limitada'])

    def test_fallo_de_feed_aislado_y_resultados_parciales(self):
        self.respuestas[self.fuente.feed] = TimeoutError('Feed caído')
        self.feed(self.otra, ['https://www.primeraedicion.com.ar/nota'])
        resultado = servicio.ejecutar_ingesta_multifuente([self.fuente.identificador, self.otra.identificador])
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(resultado['nuevas'], 1)
        self.assertEqual(resultado['errores'][0]['fuente'], self.fuente.identificador)

    def test_rechazos_rss_html_y_persistencia_no_impiden_otras_noticias(self):
        urls = ['https://misionesonline.net/breve', 'https://misionesonline.net/caida', 'https://misionesonline.net/valida']
        self.feed(self.fuente, urls, invalida=True)
        self.respuestas[urls[0]] = b'<html><article><p>Breve.</p></article></html>'
        self.respuestas[urls[1]] = OSError('Artículo caído')
        resultado = self.ejecutar()
        self.assertEqual(resultado['nuevas'], 1)
        self.assertEqual(resultado['rechazadas'], 3)
        self.assertEqual({e['etapa'] for e in resultado['errores']}, {'rss_entrada', 'articulo', 'persistencia'})

    def test_rss_malformado_vacio_y_tamano_siguen_controles_h21(self):
        for cuerpo, descargadas in ((b'<rss>', 1), (b'x' * (self.fuente.max_bytes + 1), 0)):
            self.respuestas[self.fuente.feed] = cuerpo
            resultado = self.ejecutar()
            self.assertEqual(resultado['estado'], 'FALLO')
            self.assertEqual(resultado['descargadas'], descargadas)
        self.feed(self.fuente, [])
        resultado = self.ejecutar()
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(resultado['nuevas'], 0)

    def test_redirect_entre_medios_rechazado_y_otra_fuente_continua(self):
        self.respuestas[self.fuente.feed] = (b'', 302, self.otra.feed)
        self.feed(self.otra, ['https://www.primeraedicion.com.ar/nota'])
        resultado = servicio.ejecutar_ingesta_multifuente([self.fuente.identificador, self.otra.identificador])
        self.assertEqual(resultado['nuevas'], 1)
        self.assertEqual(self.peticiones.count(self.otra.feed), 1)
        self.assertEqual(resultado['errores'][0]['etapa'], 'rss')

    def test_enlace_malicioso_no_dispara_html(self):
        self.feed(self.fuente, ['https://evil.org/no', 'https://misionesonline.net/valida'])
        resultado = self.ejecutar()
        self.assertEqual(resultado['nuevas'], 1)
        self.assertEqual(resultado['rechazadas'], 1)
        self.assertNotIn('https://evil.org/no', self.peticiones)

    def test_conflicto_historico_se_informa_sin_descargar_ni_fusionar(self):
        url = 'https://misionesonline.net/duplicada'
        self.feed(self.fuente, [url])
        for n in range(2):
            Publicacion.objects.create(hash_origen=f'historica-{n}', fuente=self.fuente.nombre,
                                       titulo='Histórica', contenido='Original', url=url)
        resultado = self.ejecutar()
        self.assertEqual(resultado['rechazadas'], 1)
        self.assertNotIn(url, self.peticiones)
        self.assertEqual(Publicacion.objects.count(), 2)

    def test_gemini_solo_opt_in_simulado_y_limite_global(self):
        self.feed(self.fuente, ['https://misionesonline.net/nueva'])
        self.feed(self.otra, ['https://www.primeraedicion.com.ar/nueva'])
        sdk = Mock()
        sdk.models.generate_content.return_value.text = json.dumps(dict(polaridad=0.4, confianza=0.8, localidades=[]))
        cliente = SimpleNamespace(client=sdk, types=types, model_name='modelo-simulado')
        self.gemini_prohibido.side_effect = lambda recibo, **kwargs: self.procesar_original(
            recibo, pausa_segundos=0, **kwargs)
        resultado = servicio.ejecutar_ingesta_multifuente([self.fuente.identificador, self.otra.identificador],
                                                        procesar_ia=True, limite_ia=1, cliente_ia=cliente)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(sdk.models.generate_content.call_count, 1)
        self.assertEqual(resultado['pendientes_ia'], 1)

    def test_comando_emite_json_y_sin_ia_por_defecto(self):
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        salida = StringIO()
        call_command('ingestar_multifuente', '--fuente', self.fuente.identificador, '--sin-ia', stdout=salida)
        resultado = json.loads(salida.getvalue())
        self.assertEqual(resultado['nuevas'], 1)
        self.assertFalse(resultado['procesar_ia'])
        self.gemini_prohibido.assert_not_called()

    def test_comando_dry_run_con_ia_no_invoca_gemini(self):
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        salida = StringIO()
        call_command('ingestar_multifuente', '--fuente', self.fuente.identificador, '--dry-run', '--con-ia', stdout=salida)
        self.assertEqual(json.loads(salida.getvalue())['previstas'], 1)
        self.gemini_prohibido.assert_not_called()

    def test_comando_exige_fuente_y_no_ofrece_activar(self):
        with self.assertRaises(CommandError):
            call_command('ingestar_multifuente')
        with self.assertRaises(CommandError):
            call_command('ingestar_multifuente', '--fuente', 'desconocida')
        with patch.object(fuentes_rss, 'FUENTES_RSS', self.original), self.assertRaises(CommandError):
            call_command('ingestar_multifuente', '--fuente', self.fuente.identificador)
        self.assertFalse(self.peticiones)


    def test_historica_sin_alias_aprende_canonica_sin_cambiar_hash_ni_pk(self):
        url, canonica = 'https://misionesonline.net/historica', 'https://misionesonline.net/canonica'
        self.feed(self.fuente, [url])
        self.respuestas[url] = b'<html><head><link rel="canonical" href="/canonica"></head></html>' + self.html()
        historica = Publicacion.objects.create(hash_origen='hash-historico-sin-alias', fuente=self.fuente.nombre,
                                              titulo='Original', contenido='Original', url=url)
        resultado = self.ejecutar()
        self.assertEqual((resultado['nuevas'], resultado['duplicadas']), (0, 1))
        self.assertEqual(Publicacion.objects.get().hash_origen, 'hash-historico-sin-alias')
        self.assertEqual(set(AliasURLPublicacion.objects.values_list('url_normalizada', flat=True)), {url, canonica})
        self.feed(self.fuente, [canonica])
        resultado = self.ejecutar()
        self.assertEqual(resultado['duplicadas'], 1)
        self.assertNotIn(canonica, self.peticiones)
        self.assertEqual(Publicacion.objects.get().pk, historica.pk)
        self.assertFalse(ProcesamientoIAMultifuente.objects.exists())

    def test_enlace_al_propio_feed_no_se_descarga_dos_veces(self):
        cuerpo = ('<rss version="2.0"><channel><item><title>Autorreferencia</title><link>'
                  + escape(self.fuente.feed) + '</link></item></channel></rss>').encode()
        self.respuestas[self.fuente.feed] = cuerpo
        resultado = self.ejecutar()
        self.assertEqual(self.peticiones, [self.fuente.feed])
        self.assertEqual(resultado['rechazadas'], 1)

    def test_dns_privado_no_abre_conexion(self):
        privado = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))
        with patch.object(red.socket, 'getaddrinfo', return_value=[privado]):
            resultado = self.ejecutar()
        self.assertEqual(resultado['estado'], 'FALLO')
        self.assertFalse(self.peticiones)

    def test_comando_fallo_emite_resumen_json_y_error(self):
        self.respuestas[self.fuente.feed] = OSError('Feed caído')
        salida = StringIO()
        with self.assertRaises(CommandError):
            call_command('ingestar_multifuente', '--fuente', self.fuente.identificador, stdout=salida)
        self.assertEqual(json.loads(salida.getvalue())['estado'], 'FALLO')

    def test_stdout_estructurado_no_se_contamina_con_mensajes_heredados(self):
        salida, errores = StringIO(), StringIO()
        def ejecutar(*args, **kwargs):
            print('Mensaje heredado de un servicio')
            return {'estado': 'EXITO', 'nuevas': 0}
        with patch('core.management.commands.ingestar_multifuente.ejecutar_ingesta_multifuente', side_effect=ejecutar):
            call_command('ingestar_multifuente', '--fuente', self.fuente.identificador, stdout=salida, stderr=errores)
        self.assertEqual(json.loads(salida.getvalue())['estado'], 'EXITO')
        self.assertIn('Mensaje heredado', errores.getvalue())

    def test_error_gemini_aislado_no_revierte_noticias_y_continua_lote(self):
        self.feed(self.fuente, ['https://misionesonline.net/uno', 'https://misionesonline.net/dos'])
        sdk = Mock()
        respuesta = SimpleNamespace(text=json.dumps(dict(polaridad=0.4, confianza=0.8, localidades=[])))
        sdk.models.generate_content.side_effect = [TimeoutError('Resultado incierto'), respuesta]
        cliente = SimpleNamespace(client=sdk, types=types, model_name='modelo-simulado')
        self.gemini_prohibido.side_effect = lambda recibo, **kwargs: self.procesar_original(
            recibo, pausa_segundos=0, **kwargs)
        resultado = self.ejecutar(procesar_ia=True, cliente_ia=cliente)
        self.assertEqual(resultado['nuevas'], 2)
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(Publicacion.objects.count(), 2)
        self.assertEqual({j.estado for j in ProcesamientoIAMultifuente.objects.all()}, {'INCIERTO', 'COMPLETADO'})
        self.assertEqual(resultado['errores'][0]['etapa'], 'gemini')

    def test_con_ia_recupera_cola_conocida_sin_redescargar_html(self):
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        self.ejecutar()
        sdk = Mock()
        sdk.models.generate_content.return_value.text = json.dumps(dict(polaridad=0.4, confianza=0.8, localidades=[]))
        cliente = SimpleNamespace(client=sdk, types=types, model_name='modelo-simulado')
        self.gemini_prohibido.side_effect = lambda recibo, **kwargs: self.procesar_original(
            recibo, pausa_segundos=0, **kwargs)
        resultado = self.ejecutar(procesar_ia=True, cliente_ia=cliente)
        self.assertEqual((resultado['nuevas'], resultado['duplicadas'], resultado['pendientes_ia']), (0, 1, 0))
        self.assertEqual(self.peticiones.count('https://misionesonline.net/nota'), 1)
        sdk.models.generate_content.assert_called_once()


    def test_integra_las_18_fuentes_simuladas_sin_activar_catalogo_real(self):
        habilitadas = tuple(replace(f, habilitada=True) for f in self.original)
        with ExitStack() as contexto:
            for modulo in (fuentes_rss, red, extractor_articulos, persistencia_multifuente, gemini_multifuente):
                contexto.enter_context(patch.object(modulo, 'FUENTES_RSS', habilitadas))
            for fuente in habilitadas:
                self.feed(fuente, ['https://' + fuente.hosts_permitidos[0] + '/nota'])
            resultado = servicio.ejecutar_ingesta_multifuente(
                [f.identificador for f in habilitadas], limite_por_fuente=1, limite_total=18)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual((resultado['nuevas'], resultado['pendientes_ia'], resultado['descargadas']), (18, 18, 36))
        self.assertFalse(any(f.habilitada for f in self.original))
        self.gemini_prohibido.assert_not_called()

    def test_pausa_gemini_entre_fuentes_y_no_solo_dentro_del_lote(self):
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        self.feed(self.otra, ['https://www.primeraedicion.com.ar/nota'])
        sdk = Mock()
        sdk.models.generate_content.return_value.text = json.dumps(dict(polaridad=0.4, confianza=0.8, localidades=[]))
        cliente = SimpleNamespace(client=sdk, types=types, model_name='modelo-simulado')
        self.gemini_prohibido.side_effect = lambda recibo, **kwargs: self.procesar_original(
            recibo, pausa_segundos=0, **kwargs)
        with patch.object(servicio.time, 'sleep') as pausa:
            resultado = servicio.ejecutar_ingesta_multifuente([self.fuente.identificador, self.otra.identificador],
                                                            procesar_ia=True, cliente_ia=cliente)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(sdk.models.generate_content.call_count, 2)
        pausa.assert_called_once_with(12)


    def test_abreviada_insuficiente_recupera_canonica_sin_envenenar_cache(self):
        corta, canonica = 'https://misionesonline.net/corta', 'https://misionesonline.net/completa'
        self.feed(self.fuente, [corta, canonica])
        self.respuestas[corta] = b'<html><head><link rel="canonical" href="/completa"></head><body><article><p>Breve.</p></article></body></html>'
        resultado = self.ejecutar()
        self.assertEqual(resultado['errores'], [])
        self.assertEqual((resultado['nuevas'], resultado['duplicadas'], resultado['rechazadas']), (1, 1, 0))
        self.assertEqual(self.peticiones, [self.fuente.feed, corta, canonica])
        self.assertIn('biblioteca', Publicacion.objects.get().contenido)
        self.assertEqual(set(AliasURLPublicacion.objects.values_list('url_normalizada', flat=True)), {corta, canonica})

    def test_cache_canonica_de_contenido_suficiente_no_descarga_otra_vez(self):
        corta, canonica = 'https://misionesonline.net/corta', 'https://misionesonline.net/completa'
        self.feed(self.fuente, [corta, canonica])
        self.respuestas[corta] = b'<html><head><link rel="canonical" href="/completa"></head></html>' + self.html()
        resultado = self.ejecutar()
        self.assertEqual((resultado['nuevas'], resultado['duplicadas']), (1, 1))
        self.assertEqual(self.peticiones, [self.fuente.feed, corta])

    def test_canonica_adicional_consume_presupuesto_global_y_de_fuente(self):
        corta, canonica = 'https://misionesonline.net/corta', 'https://misionesonline.net/completa'
        self.feed(self.fuente, [corta])
        self.feed(self.otra, ['https://www.primeraedicion.com.ar/otra'])
        self.respuestas[corta] = b'<html><head><link rel="canonical" href="/completa"></head><article><p>Breve.</p></article></html>'
        self.respuestas[canonica] = self.html()
        resultado = servicio.ejecutar_ingesta_multifuente(
            [self.fuente.identificador, self.otra.identificador], limite_total=2)
        self.assertEqual(resultado['nuevas'], 1)
        self.assertEqual(self.peticiones, [self.fuente.feed, corta, canonica])
        self.assertTrue(resultado['fuentes'][1]['limitada'])

    def test_presupuesto_impide_fallback_sin_hacer_descargas_adicionales(self):
        corta, canonica = 'https://misionesonline.net/corta', 'https://misionesonline.net/completa'
        self.feed(self.fuente, [corta])
        self.respuestas[corta] = b'<html><head><link rel="canonical" href="/completa"></head><article><p>Breve.</p></article></html>'
        self.respuestas[canonica] = self.html()
        for limites in ({'limite_total': 1}, {'limite_por_fuente': 1}):
            self.peticiones.clear()
            resultado = self.ejecutar(**limites)
            self.assertEqual(resultado['nuevas'], 0)
            self.assertTrue(resultado['limitada'])
            self.assertEqual(self.peticiones, [self.fuente.feed, corta])

    def test_ciclo_canonico_y_repeticiones_no_repite_peticiones(self):
        a, b = 'https://misionesonline.net/a', 'https://misionesonline.net/b'
        self.feed(self.fuente, [a, b, a])
        self.respuestas[a] = b'<html><head><link rel="canonical" href="/b"></head><article><p>Breve A.</p></article></html>'
        self.respuestas[b] = b'<html><head><link rel="canonical" href="/a"></head><article><p>Breve B.</p></article></html>'
        resultado = self.ejecutar()
        self.assertEqual(resultado['rechazadas'], 3)
        self.assertEqual(self.peticiones, [self.fuente.feed, a, b])

    def test_canonica_ajena_no_inicia_fallback_http(self):
        url = 'https://misionesonline.net/corta'
        self.feed(self.fuente, [url])
        self.respuestas[url] = b'<html><head><link rel="canonical" href="https://evil.org/no"></head><article><p>Breve.</p></article></html>'
        resultado = self.ejecutar()
        self.assertEqual(resultado['rechazadas'], 1)
        self.assertEqual(self.peticiones, [self.fuente.feed, url])

    @contextmanager
    def esquema_sqlite_nuevo(self, *, ausente=None, defecto=None):
        # Base independiente creada de cero. Nunca se altera el esquema del runner.
        from django.db.backends.sqlite3.base import DatabaseWrapper
        original = connections['default']
        configuracion = dict(original.settings_dict)
        configuracion.update(ENGINE='django.db.backends.sqlite3', NAME=':memory:')
        nueva = DatabaseWrapper(configuracion, alias='default')
        connections['default'] = nueva
        try:
            estado = ProjectState.from_apps(apps)
            alias = estado.models['core', 'aliasurlpublicacion']
            cola = estado.models['core', 'procesamientoiamultifuente']
            if defecto == 'alias_unique':
                alias.options['constraints'] = []
            elif defecto == 'alias_parcial':
                alias.options['constraints'] = [models.UniqueConstraint(fields=['fuente', 'url_normalizada'],
                    condition=models.Q(fuente='misiones_online'), name='alias_url_unico_por_fuente')]
            elif defecto == 'alias_fk':
                alias.fields['publicacion'].db_constraint = False
            elif defecto == 'cola_unique':
                cola.fields['publicacion'] = models.ForeignKey('core.Publicacion', on_delete=models.CASCADE)
                cola.fields['id'] = models.BigAutoField(primary_key=True)
            elif defecto == 'cola_fk':
                cola.fields['publicacion'].db_constraint = False
            elif defecto == 'cola_columna':
                cola.fields.pop('token_intento')
            elif defecto == 'cola_token_not_null':
                cola.fields['token_intento'].null = False
            elif defecto == 'alias_fuente_nullable':
                alias.fields['fuente'].null = True
            elif defecto == 'cola_estado_corto':
                cola.fields['estado'].max_length = 4
            elif defecto == 'alias_url_corta':
                alias.fields['url_normalizada'].max_length = 100
            elif defecto == 'cola_tipo_token':
                cola.fields['token_intento'] = models.CharField(max_length=32, null=True)
            elif defecto == 'cola_fecha_tipo':
                cola.fields['iniciado'] = models.CharField(max_length=64, null=True)
            elif defecto == 'alias_pk':
                alias.fields['id'] = models.IntegerField()
                alias.fields['otra_pk'] = models.AutoField(primary_key=True)

            with nueva.schema_editor() as editor:
                for modelo in estado.apps.get_models():
                    if modelo._meta.managed and not modelo._meta.proxy and modelo.__name__ != ausente:
                        editor.create_model(modelo)
            yield nueva
        finally:
            if nueva.connection is not None:
                nueva.connection.close()
            connections['default'] = original

    def test_preflight_sin_0020_o_0021_aborta_antes_de_http_y_escrituras(self):
        for modelo, version in (('AliasURLPublicacion', '0020'), ('ProcesamientoIAMultifuente', '0021')):
            with self.subTest(version=version), self.esquema_sqlite_nuevo(ausente=modelo) as db:
                for dry_run in (False, True):
                    with CaptureQueriesContext(db) as consultas:
                        with self.assertRaisesRegex(servicio.EsquemaMultifuenteIncompleto, version):
                            self.ejecutar(dry_run=dry_run, procesar_ia=True)
                    self.assertFalse(self.peticiones)
                    self.assertEqual(RegistroDatos.objects.count(), 0)
                    self.assertEqual(Publicacion.objects.count(), 0)
                    self.gemini_prohibido.assert_not_called()
                    for consulta in consultas:
                        self.assertFalse(consulta['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))
                    salida = StringIO()
                    argumentos = ['--fuente', self.fuente.identificador]
                    if dry_run:
                        argumentos.append('--dry-run')
                    with self.assertRaisesRegex(CommandError, version):
                        call_command('ingestar_multifuente', *argumentos, stdout=salida)
                    self.assertEqual(salida.getvalue(), '')
                    self.assertFalse(self.peticiones)
                    self.assertEqual(RegistroDatos.objects.count(), 0)

    def test_preflight_rechaza_restricciones_o_columnas_incompletas(self):
        for defecto, version in (('alias_unique', '0020'), ('alias_parcial', '0020'), ('alias_fk', '0020'),
                                 ('cola_unique', '0021'), ('cola_fk', '0021'), ('cola_columna', '0021')):
            with self.subTest(defecto=defecto), self.esquema_sqlite_nuevo(defecto=defecto):
                for dry_run in (False, True):
                    with self.assertRaisesRegex(servicio.EsquemaMultifuenteIncompleto, version):
                        self.ejecutar(dry_run=dry_run)
                    self.assertFalse(self.peticiones)
                    self.assertEqual(RegistroDatos.objects.count(), 0)
                    self.assertEqual(Publicacion.objects.count(), 0)


    def test_preflight_rechaza_nulabilidad_tipos_longitudes_y_pk_incompatibles(self):
        defectos = (('cola_token_not_null', '0021'), ('alias_fuente_nullable', '0020'),
                    ('cola_estado_corto', '0021'), ('alias_url_corta', '0020'),
                    ('cola_tipo_token', '0021'), ('cola_fecha_tipo', '0021'), ('alias_pk', '0020'))
        for defecto, version in defectos:
            with self.subTest(defecto=defecto), self.esquema_sqlite_nuevo(defecto=defecto) as db:
                for dry_run in (True, False):
                    with CaptureQueriesContext(db) as consultas:
                        with self.assertRaisesRegex(servicio.EsquemaMultifuenteIncompleto, version):
                            self.ejecutar(dry_run=dry_run, procesar_ia=True)
                    self.assertFalse(self.peticiones)
                    self.assertEqual(RegistroDatos.objects.count(), 0)
                    self.assertEqual(Publicacion.objects.count(), 0)
                    self.assertEqual(ProcesamientoIAMultifuente.objects.count(), 0)
                    self.gemini_prohibido.assert_not_called()
                    for consulta in consultas:
                        self.assertFalse(consulta['sql'].lstrip().upper().startswith(
                            ('INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'ALTER', 'DROP')))
                    salida = StringIO()
                    argumentos = ['--fuente', self.fuente.identificador]
                    if dry_run:
                        argumentos.append('--dry-run')
                    with self.assertRaisesRegex(CommandError, version):
                        call_command('ingestar_multifuente', *argumentos, stdout=salida)
                    self.assertEqual(salida.getvalue(), '')
                    self.assertFalse(self.peticiones)
                    self.assertEqual(RegistroDatos.objects.count(), 0)

    def test_cuerpo_largo_con_nul_no_envenena_cache_canonica(self):
        corta, canonica = 'https://misionesonline.net/nul', 'https://misionesonline.net/canonica-valida'
        self.feed(self.fuente, [corta, canonica])
        texto = 'Los vecinos participaron de una jornada para conocer los nuevos proyectos educativos de la ciudad. '
        self.respuestas[corta] = ('<html><head><link rel="canonical" href="/canonica-valida"></head>'
                                 '<article><p>' + texto + '\x00' + texto + '</p></article></html>').encode()
        resultado = self.ejecutar()
        self.assertEqual(resultado['errores'], [])
        self.assertEqual((resultado['nuevas'], resultado['duplicadas'], resultado['rechazadas']), (1, 1, 0))
        self.assertEqual(self.peticiones, [self.fuente.feed, corta, canonica])
        self.assertNotIn('\x00', Publicacion.objects.get().contenido)
        self.assertIn('biblioteca', Publicacion.objects.get().contenido)

    def test_cache_persistible_revalida_la_entrada_sin_nueva_descarga(self):
        corta, canonica = 'https://misionesonline.net/corta', 'https://misionesonline.net/completa'
        self.feed(self.fuente, [corta, canonica])
        self.respuestas[corta] = b'<html><head><link rel="canonical" href="/completa"></head></html>' + self.html()
        with patch.object(servicio, 'validar_entrada_persistencia', wraps=servicio.validar_entrada_persistencia) as validar:
            resultado = self.ejecutar()
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(validar.call_count, 2)
        self.assertEqual(self.peticiones, [self.fuente.feed, corta])
        self.assertEqual(Publicacion.objects.count(), 1)

    def test_nul_con_presupuesto_agotado_no_descarga_canonica(self):
        corta, canonica = 'https://misionesonline.net/nul', 'https://misionesonline.net/completa'
        self.feed(self.fuente, [corta])
        texto = 'La comunidad presentó una nueva propuesta para mejorar las escuelas y ampliar las actividades de estudiantes. '
        self.respuestas[corta] = ('<html><head><link rel="canonical" href="/completa"></head>'
                                 '<article><p>' + texto + '\x00' + texto + '</p></article></html>').encode()
        self.respuestas[canonica] = self.html()
        for limites in ({'limite_total': 1}, {'limite_por_fuente': 1}):
            self.peticiones.clear()
            resultado = self.ejecutar(**limites)
            self.assertTrue(resultado['limitada'])
            self.assertEqual((resultado['nuevas'], resultado['rechazadas']), (0, 1))
            self.assertEqual(self.peticiones, [self.fuente.feed, corta])

    def test_ciclo_con_cuerpos_invalidos_no_repite_descargas(self):
        a, b = 'https://misionesonline.net/a-nul', 'https://misionesonline.net/b-nul'
        self.feed(self.fuente, [a, b, a])
        texto = 'La comunidad participa de nuevas actividades educativas para compartir los proyectos de las escuelas locales. '
        for origen, destino in ((a, b), (b, a)):
            self.respuestas[origen] = ('<html><head><link rel="canonical" href="' + destino
                + '"></head><article><p>' + texto + '\x00' + texto + '</p></article></html>').encode()
        resultado = self.ejecutar()
        self.assertEqual((resultado['nuevas'], resultado['rechazadas']), (0, 3))
        self.assertEqual(self.peticiones, [self.fuente.feed, a, b])

    def test_validador_h31_no_escribe_ni_emite_senales_o_ia(self):
        from core.services.lector_rss import analizar_rss
        self.feed(self.fuente, ['https://misionesonline.net/nota'])
        noticia, = analizar_rss(self.respuestas[self.fuente.feed], self.fuente).noticias
        articulo = extractor_articulos.analizar_articulo(self.html(), noticia, self.fuente)
        entrada = persistencia_multifuente.EntradaPersistencia(noticia, articulo)
        with CaptureQueriesContext(connection) as consultas, patch.object(Publicacion, 'save') as guardar, patch(
            'core.services.clasificacion._clasificar_con_ia', side_effect=AssertionError('Sin IA')
        ) as ia:
            persistencia_multifuente.validar_entrada_persistencia(entrada)
        guardar.assert_not_called()
        ia.assert_not_called()
        for consulta in consultas:
            self.assertFalse(consulta['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())

    def test_preflight_postgresql_detecta_columnas_incompatibles_antes_de_efectos(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requiere PostgreSQL efímero')
        # Sólo el esquema vacío creado por el runner; no se usan bases existentes.
        casos = ((ProcesamientoIAMultifuente, 'token_intento', 'null', False),
                 (AliasURLPublicacion, 'fuente', 'null', True),
                 (ProcesamientoIAMultifuente, 'estado', 'max_length', 4))
        for modelo, nombre, propiedad, valor in casos:
            original = modelo._meta.get_field(nombre)
            alterado = original.clone()
            alterado.set_attributes_from_name(nombre)
            alterado.model = modelo
            setattr(alterado, propiedad, valor)
            with self.subTest(campo=nombre):
                with connection.schema_editor() as editor:
                    editor.alter_field(modelo, original, alterado)
                try:
                    for dry_run in (True, False):
                        with CaptureQueriesContext(connection) as consultas:
                            with self.assertRaises(servicio.EsquemaMultifuenteIncompleto):
                                self.ejecutar(dry_run=dry_run, procesar_ia=True)
                        self.assertFalse(self.peticiones)
                        self.gemini_prohibido.assert_not_called()
                        self.assertFalse(RegistroDatos.objects.exists())
                        self.assertFalse(Publicacion.objects.exists())
                        for consulta in consultas:
                            self.assertFalse(consulta['sql'].lstrip().upper().startswith(
                                ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP')))
                finally:
                    with connection.schema_editor() as editor:
                        editor.alter_field(modelo, alterado, original)
        servicio.verificar_esquema_multifuente()
