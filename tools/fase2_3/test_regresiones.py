"""Regresiones de Fase 2.3 con biblioteca estándar, sin Django ni red."""
import ast
from datetime import date
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'tools/fase2_2'))
sys.path.insert(0, str(ROOT / 'tools/fase1_2'))
from core.services import descarga_segura as red
from core.services.parametros import entero_positivo, segundos_validos
from test_contratos import cargar_clasificador
import test_unit as arnes


def funciones(archivo, nombres, contexto):
    arbol = ast.parse((ROOT / archivo).read_bytes())
    nodos = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name in nombres]
    exec(compile(ast.Module(body=nodos, type_ignores=[]), archivo, 'exec'), contexto)
    return contexto


class TerritorioConfianzaTests(unittest.TestCase):
    def setUp(self):
        self.c = cargar_clasificador()

    def test_fecha_no_es_departamento(self):
        for titulo in ('El acto será el 25 de Mayo', 'El feriado del 9 de Julio', 'Aniversario de Dos de Mayo'):
            with self.subTest(titulo=titulo):
                self.assertEqual(self.c.departamento_por_texto(titulo, ''), '')

    def test_evidencia_municipal_para_nombre_fecha(self):
        self.assertEqual(self.c.departamento_por_texto('Obras en el municipio de 25 de Mayo', ''), '25mayo')

    def test_homonimo_externo_no_asigna(self):
        for titulo in ('Festejos en San Pedro, Buenos Aires', 'Visita a Puerto Rico, Estados Unidos',
                       'La capital provincial de Corrientes'):
            with self.subTest(titulo=titulo):
                self.assertEqual(self.c.departamento_por_texto(titulo, ''), '')

    def test_guarani_municipio_y_departamento(self):
        self.assertEqual(self.c.departamento_por_texto('Obras en el municipio de Guaraní', ''), 'obera')
        self.assertEqual(self.c.departamento_por_texto('Obras en el departamento Guaraní', ''), 'guarani')
        self.assertEqual(self.c.departamento_por_texto('Lengua guaraní', ''), '')

    def test_repeticion_cuerpo_no_confirma(self):
        propuesta, segura = self.c.categoria_con_confianza('Información general', 'hospital hospital hospital')
        self.assertEqual(propuesta, 'Salud')
        self.assertFalse(segura)

    def test_seccion_o_titulo_claro_conservan_confianza(self):
        self.assertEqual(self.c.categoria_con_confianza('Hospital provincial', ''), ('Salud', True))
        self.assertEqual(self.c.categoria_con_confianza('Nota', '', 'deportes'), ('Deportes', True))

    def test_clasificacion_excesiva_rechazada(self):
        with self.assertRaises(ValueError):
            self.c._validar_respuesta(' ' * (256 * 1024 + 1), {0})

    def test_incompleta_y_vacia_conservan_indices_resueltos(self):
        self.assertEqual(self.c._validar_respuesta('[{"indice":1,"categoria":"Salud"}]', {0, 1}), {1: 'Salud'})
        self.assertEqual(self.c._validar_respuesta('[]', {0}), {})


class LimitesGeminiTests(unittest.TestCase):
    def test_entero_positivo_rechaza_bool_cadenas_y_cero(self):
        for valor in (-1, 0, True, False, '5', 1.5, None):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                entero_positivo(valor, 'limite')
        self.assertEqual(entero_positivo(5, 'limite'), 5)

    def test_segundos_finitos(self):
        for valor in (-1, float('inf'), float('nan'), True, None, '1', 10**1000):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                segundos_validos(valor, 'pausa', permitir_cero=True)
        self.assertEqual(segundos_validos(0, 'pausa', permitir_cero=True), 0)

    def test_scraper_alternativo_rechaza_booleano_antes_de_descargar(self):
        descargar = MagicMock()
        contexto = funciones('app/core/scrapers/noticias.py', {'fetch_elterritorio_news'},
                             {'CATEGORIAS_TERRITORIO': {'misiones': 'https://www.elterritorio.com.ar/rss/misiones'},
                              'descargar': descargar})
        with self.assertRaises(ValueError):
            contexto['fetch_elterritorio_news'](limit=True)
        descargar.assert_not_called()

    def test_batch_invalido_no_consulta_bd(self):
        archivo = ROOT / 'app/core/services/gemini_cliente.py'
        arbol = ast.parse(archivo.read_bytes())
        clase = next(n for n in arbol.body if isinstance(n, ast.ClassDef) and n.name == 'GeminiCliente')
        metodo = next(n for n in clase.body if isinstance(n, ast.FunctionDef) and n.name == 'procesar_pendientes')
        publicacion = MagicMock()
        contexto = {'entero_positivo': entero_positivo, 'Publicacion': publicacion}
        exec(compile(ast.Module(body=[metodo], type_ignores=[]), str(archivo), 'exec'), contexto)
        for valor in (-1, 0, True, '3', None):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                contexto['procesar_pendientes'](SimpleNamespace(), valor)
        publicacion.objects.filter.assert_not_called()

    def test_validador_sentimiento_incompleto_vacio_y_excesivo(self):
        import math
        contexto = funciones('app/core/services/integridad_sentimiento.py', {'validar_numero'}, {'math': math})
        contexto = funciones('app/core/services/gemini_cliente.py', {'validar_respuesta_gemini'},
                             {'json': json, '_numero_validado': contexto['validar_numero']})
        validar = contexto['validar_respuesta_gemini']
        for raw in ('{}', '[]', '{"polaridad":0,"confianza":1}', ' ' * (256 * 1024 + 1)):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                validar(raw)
        self.assertEqual(validar('{"polaridad":0,"confianza":1,"localidades":[]}')['localidades'], [])


class DescargaTests(unittest.TestCase):
    def setUp(self):
        for objetivo in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.getaddrinfo'):
            p = patch(objetivo, side_effect=AssertionError('Red prohibida'))
            p.start()
            self.addCleanup(p.stop)

    def test_timeout_invalido_falla_antes_de_dns(self):
        for timeout in (0, -1, None, True, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                red.descargar(arnes.URL, timeout)

    def test_tamano_acumulado_no_solo_por_bloque(self):
        respuesta = MagicMock()
        respuesta.read1.side_effect = [b'123', b'456']
        with patch.object(red, 'MAX_BYTES', 5), patch.object(red.time, 'monotonic', return_value=0), self.assertRaises(ValueError):
            red._leer_limitado(respuesta, MagicMock(), 10)

    def test_goteo_no_renueva_presupuesto(self):
        respuesta = MagicMock()
        respuesta.read1.return_value = b'a'
        with patch.object(red.time, 'monotonic', side_effect=[0, 4, 8, 12]), self.assertRaises(TimeoutError):
            red._leer_limitado(respuesta, MagicMock(), 10)
        self.assertEqual(respuesta.read1.call_count, 2)

    def test_cuerpo_se_recompone_y_limita_socket_al_restante(self):
        respuesta, conexion = MagicMock(), MagicMock()
        respuesta.read1.side_effect = [b'ab', b'cd', b'']
        with patch.object(red.time, 'monotonic', return_value=2):
            self.assertEqual(red._leer_limitado(respuesta, conexion, 10), b'abcd')
        conexion.settimeout.assert_called_with(8)

    def test_socket_retenido_en_respuesta_connection_close(self):
        # Parser HTTP real sobre archivo en memoria y socket simulado: sin red.
        import http.client
        from io import BytesIO
        lector = MagicMock()
        lector.makefile.return_value = BytesIO(b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK')
        conexion = http.client.HTTPConnection('sin-red.invalid')
        conexion.sock = lector
        conexion.request('GET', '/')
        respuesta = conexion.getresponse()
        self.addCleanup(respuesta.close)
        self.assertIsNone(conexion.sock)
        lector.close.assert_called_once()
        with patch.object(red.time, 'monotonic', return_value=0):
            self.assertEqual(red._leer_limitado(respuesta, lector, 10), b'OK')
        lector.settimeout.assert_called_with(10)


class IdentidadTests(unittest.TestCase):
    def test_equivalencia_minima_sin_cambiar_parametros(self):
        self.assertEqual(red.clave_identidad_url('HTTPS://WWW.ELTERRITORIO.COM.AR:443/noticias/X?a=1&b=2'),
                         red.clave_identidad_url('https://www.elterritorio.com.ar/noticias/X?a=1&b=2'))
        for distinto in ('/noticias/x?a=1&b=2', '/noticias/X?b=2&a=1', '/noticias/X?a=1&b=3',
                         '/noticias/X/?a=1&b=2', '/noticias/X?a=1&b=2&utm_source=x'):
            self.assertNotEqual(red.clave_identidad_url('https://www.elterritorio.com.ar' + distinto),
                                red.clave_identidad_url('https://www.elterritorio.com.ar/noticias/X?a=1&b=2'))

    def test_busqueda_legacy_verifica_clave_completa_tras_filtrar_sufijo(self):
        fixture = arnes.ServicioTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        url = arnes.URL + '?edicion=1'
        alias = url.replace('www.elterritorio.com.ar', 'WWW.ELTERRITORIO.COM.AR:443')
        fixture.s.Publicacion.objects.filter.return_value.values_list.return_value = [alias]
        self.assertTrue(fixture.s._url_equivalente_existente(url))
        fixture.s.Publicacion.objects.filter.return_value.values_list.return_value = [alias.replace('edicion=1', 'edicion=2')]
        self.assertFalse(fixture.s._url_equivalente_existente(url))
        fixture.descarga.assert_not_called()

    def test_pausa_invalida_no_crea_auditoria(self):
        fixture = arnes.ServicioTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for pausa in (-1, True, None, float('nan')):
            resultado = fixture.s.ingestar_historico_elterritorio(date(2026, 1, 1), date(2026, 1, 2), pausa=pausa)
            self.assertEqual(resultado['estado'], 'FALLO')
        fixture.s.RegistroDatos.objects.create.assert_not_called()
        fixture.descarga.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
