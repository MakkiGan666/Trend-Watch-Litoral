"""Regresiones ORM de territorio, respuestas IA, identidad URL y límites. Sin red."""
import hashlib
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import TestCase
from core.models import Publicacion, PublicacionTema, RegistroDatos, Sentimiento, Locacion
from core.services.scraper import ingestar_historico_elterritorio, fetch_and_store_elterritorio
from core.services.clasificacion import clasificar_lote
from core.services.gemini_cliente import GeminiCliente
from core.test_ingesta_historico import IngestaSimuladaMixin, BASE


class TerritorioConfianzaFase23TestCase(IngestaSimuladaMixin, TestCase):
    def test_fecha_y_homonimo_externo_no_persisten_departamento(self):
        for indice, titulo in enumerate(('El acto será el 25 de Mayo', 'Festejos en San Pedro, Buenos Aires',
                                        'La capital provincial de Corrientes')):
            resultado = self.ingerir((titulo, BASE + f'99040{indice}-territorio', 'Resumen'))
            self.assertEqual(resultado['capturados'], 1)
        self.assertFalse(Publicacion.objects.exclude(departamento='').exists())

    def test_guarani_distingue_municipio_y_departamento(self):
        for indice, (titulo, esperado) in enumerate((('Obras en el municipio de Guaraní', 'obera'),
                                                   ('Obras en el departamento Guaraní', 'guarani'))):
            url = BASE + f'99041{indice}-guarani'
            self.ingerir((titulo, url, 'Resumen'))
            self.assertEqual(Publicacion.objects.get(url=url).departamento, esperado)

    def test_cuerpo_repetido_no_crea_asociacion_confirmada(self):
        with patch('core.services.scraper._leer_articulo', return_value=SimpleNamespace(text='hospital hospital hospital')):
            resultado = self.ingerir(('Información general', BASE + '990420-confianza', 'Resumen'))
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(resultado['sin_categoria'], 1)
        self.assertFalse(PublicacionTema.objects.exists())


class IdentidadUrlFase23TestCase(IngestaSimuladaMixin, TestCase):
    def test_equivalente_reutiliza_historico_sin_reescribir_hash_ni_url(self):
        original = (BASE + '990430-identidad?edicion=1').replace('www.elterritorio.com.ar', 'WWW.ELTERRITORIO.COM.AR:443')
        equivalente = BASE + '990430-identidad?edicion=1'
        self.ingerir(('Título', original, 'Resumen'))
        anterior = Publicacion.objects.values().get()
        self.article.reset_mock()
        resultado = self.ingerir(('Otro título', equivalente, 'Otro resumen'))
        self.assertEqual((resultado['estado'], resultado['omitidas']), ('DUPLICADOS', 1))
        self.assertEqual(Publicacion.objects.values().get(), anterior)
        self.article.assert_not_called()

    def test_parametros_significativos_no_se_fusionan(self):
        resultado = self.ingerir(('Uno', BASE + '990431-parametro?edicion=1', 'Resumen'),
                                ('Dos', BASE + '990431-parametro?edicion=2', 'Resumen'))
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual(Publicacion.objects.count(), 2)

    def test_aliases_en_feed_se_procesan_una_vez(self):
        url = BASE + '990432-feed'
        alias = url.replace('www.elterritorio.com.ar', 'WWW.ELTERRITORIO.COM.AR:443')
        resultado = self.ingerir(('Uno', url, 'Resumen'), ('Dos', alias, 'Resumen'))
        self.assertEqual((resultado['capturados'], resultado['omitidas']), (1, 1))
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(self.article.call_count, 1)

    def test_historico_reconoce_alias_almacenado(self):
        url = BASE + '990433-historico'
        alias = url.replace('www.elterritorio.com.ar', 'WWW.ELTERRITORIO.COM.AR:443')
        self.ingerir(('Original', alias, 'Resumen'))
        anterior = Publicacion.objects.values().get()
        self.article.reset_mock()
        with patch('core.services.scraper._urls_de_sitemaps', return_value={url: date(2026, 10, 16)}):
            resultado = ingestar_historico_elterritorio(date(2026, 10, 16), date(2026, 10, 16), usar_ia=False, pausa=0)
        self.assertEqual((resultado['estado'], resultado['omitidas']), ('DUPLICADOS', 1))
        self.assertEqual(Publicacion.objects.values().get(), anterior)
        self.article.assert_not_called()

    def test_aliases_ya_existentes_no_duplican_contador(self):
        url = BASE + '990434-preexistentes'
        alias = url.replace('www.elterritorio.com.ar', 'WWW.ELTERRITORIO.COM.AR:443')
        for link in (url, alias):
            Publicacion.objects.create(hash_origen=hashlib.sha256(link.encode()).hexdigest(), url=link, contenido='Legado')
        with patch('core.services.scraper._urls_de_sitemaps', return_value={url: date(2026, 10, 16), alias: date(2026, 10, 16)}):
            resultado = ingestar_historico_elterritorio(date(2026, 10, 16), date(2026, 10, 16), usar_ia=False, pausa=0)
        self.assertEqual(resultado['omitidas'], 2)
        self.assertEqual(Publicacion.objects.count(), 2)


class GeminiFase23TestCase(TestCase):
    def setUp(self):
        self.pub = Publicacion.objects.create(hash_origen='fase23-gemini', contenido='Texto')
        self.cliente = GeminiCliente.__new__(GeminiCliente)
        self.cliente.client, self.cliente.types = MagicMock(), MagicMock()
        self.cliente.model_name = 'modelo-simulado'
        self.generar = self.cliente.client.models.generate_content
        self.valida = {'polaridad': 0.2, 'confianza': 0.8, 'localidades': []}
        p = patch('core.services.gemini_cliente.time.sleep')
        p.start()
        self.addCleanup(p.stop)

    def test_lote_invalido_no_consulta_bd_ni_llama_ia(self):
        for limite in (-1, 0, True, None, '2'):
            with self.subTest(limite=limite), self.assertNumQueries(0), self.assertRaises(ValueError):
                self.cliente.procesar_pendientes(limite)
        self.generar.assert_not_called()

    def test_sentimiento_incompleto_no_escribe_y_permite_reintento(self):
        for datos in ({}, {'polaridad': 0.2}, {'polaridad': 0.2, 'confianza': 0.8}):
            self.generar.return_value.text = json.dumps(datos)
            resultado = self.cliente.procesar_pendientes(1)
            self.assertEqual(resultado['errores'][0]['codigo'], 'validacion_respuesta')
            self.assertFalse(Sentimiento.objects.exists())
            self.assertFalse(Locacion.objects.exists())
            self.pub.refresh_from_db()
            self.assertFalse(self.pub.procesado_ia)
        self.generar.return_value.text = json.dumps(self.valida)
        self.assertEqual(self.cliente.procesar_pendientes(1)['estado'], 'EXITO')
        self.assertEqual(Sentimiento.objects.count(), 1)

    def test_localidades_vacias_validas_e_idempotentes(self):
        self.generar.return_value.text = json.dumps(self.valida)
        self.assertEqual(self.cliente.procesar_pendientes(1)['estado'], 'EXITO')
        self.assertEqual(self.cliente.procesar_pendientes(1)['estado'], 'SIN_PENDIENTES')
        self.assertEqual(Sentimiento.objects.count(), 1)
        self.assertEqual(Locacion.objects.count(), 0)
        self.generar.assert_called_once()

    def test_error_de_persistencia_revierte_todo_y_reintento_no_duplica(self):
        self.valida['localidades'] = [{'nombre': 'Posadas', 'latitud': -27.3, 'longitud': -55.9},
                                      {'nombre': 'Oberá', 'latitud': -27.4, 'longitud': -55.1}]
        self.generar.return_value.text = json.dumps(self.valida)
        crear = Locacion.objects.create
        contador = 0

        def falla_segunda(**datos):
            nonlocal contador
            contador += 1
            if contador == 2:
                raise IntegrityError('fallo simulado de persistencia')
            return crear(**datos)

        with patch('core.services.gemini_cliente.Locacion.objects.create', side_effect=falla_segunda):
            resultado = self.cliente.procesar_pendientes(1)
        self.assertEqual(resultado['errores'][0]['codigo'], 'persistencia')
        self.assertEqual(Sentimiento.objects.count(), 0)
        self.assertEqual(Locacion.objects.count(), 0)
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)
        self.assertEqual(self.cliente.procesar_pendientes(1)['estado'], 'EXITO')
        self.assertEqual((Sentimiento.objects.count(), Locacion.objects.count()), (1, 2))

    def test_respuesta_excesiva_no_persiste(self):
        self.generar.return_value.text = ' ' * (256 * 1024 + 1)
        resultado = self.cliente.procesar_pendientes(1)
        self.assertEqual(resultado['estado'], 'FALLO')
        self.assertFalse(Sentimiento.objects.exists())

    def test_clasificacion_parcial_y_vacia_no_confirma_omitidas(self):
        noticias = [{'titulo': 'Lorem ipsum', 'contenido': ''}, {'titulo': 'Dolor sit amet', 'contenido': ''}]
        gemini = SimpleNamespace(client=self.cliente.client, types=self.cliente.types, model_name='modelo-simulado')
        for raw in ('[]', '[{"indice":0,"categoria":"Salud"}]', '[{"indice":8,"categoria":"Salud"}]',
                    '[{"indice":0,"categoria":"Salud"},{"indice":0,"categoria":"Turismo"}]'):
            with self.subTest(raw=raw), patch('core.services.gemini_cliente.gemini_cliente', gemini):
                self.generar.return_value.text = raw
                resultado = clasificar_lote(noticias)
            self.assertFalse(resultado[1]['confirmada'])
            self.assertEqual(resultado[0]['confirmada'], raw == '[{"indice":0,"categoria":"Salud"}]')
        self.assertFalse(PublicacionTema.objects.exists())


class LimitesIngestaFase23TestCase(IngestaSimuladaMixin, TestCase):
    def test_pausa_invalida_falla_antes_de_auditoria(self):
        for pausa in (-1, True, None, float('nan'), float('inf')):
            with self.subTest(pausa=pausa), self.assertNumQueries(0):
                resultado = ingestar_historico_elterritorio(date(2026, 1, 1), date(2026, 1, 2), pausa=pausa)
            self.assertEqual(resultado['estado'], 'FALLO')
        self.urlopen.assert_not_called()
        self.assertFalse(RegistroDatos.objects.exists())

    def test_limite_booleano_alternativo_no_consulta_ni_descarga(self):
        from core.scrapers.noticias import fetch_elterritorio_news
        with patch('core.scrapers.noticias.descargar') as descarga, self.assertNumQueries(0):
            with self.assertRaises(ValueError):
                fetch_elterritorio_news(limit=True)
        descarga.assert_not_called()

    def test_fallo_descarga_no_persiste_publicaciones(self):
        for error in (TimeoutError('tiempo agotado'), ValueError('Respuesta demasiado grande')):
            self.urlopen.side_effect = error
            resultado = fetch_and_store_elterritorio(usar_ia=False)
            self.assertEqual((resultado['status'], resultado['estado']), ('ERROR', 'FALLO'))
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.filter(estado='EXITO').exists())
