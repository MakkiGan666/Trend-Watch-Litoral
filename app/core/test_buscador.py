from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import Publicacion
from core.services.buscador import EntradaInvalida, extracto, validar_consulta


class BuscadorTests(TestCase):
    def crear(self, titulo='Otro título', contenido='Otro contenido', **kwargs):
        return Publicacion.objects.create(titulo=titulo, contenido=contenido,
                                          hash_origen=str(Publicacion.objects.count()), **kwargs)

    def get(self, q='educacion', **kwargs):
        return self.client.get(reverse('buscar_publicaciones'), {'q': q, **kwargs})

    def ids(self, q):
        return [r['id_publicacion_api'] for r in self.get(q).json()['resultados']]

    def test_campos_and_parciales_y_orden_libre(self):
        a = self.crear('Rovira educación')
        b = self.crear(contenido='Educación y Rovira')
        c = self.crear('Rovira', 'educación')
        self.crear('Rovira')
        self.assertCountEqual(self.ids('educ rov'), [a.pk, b.pk, c.pk])

    def test_unicode_y_enie(self):
        for titulo in ['EDUCACIÓN', 'educacion', 'educacio\u0301n']:
            self.crear(titulo)
        for q in ['educación', 'EDUCACION', 'educacio\u0301n']:
            self.assertEqual(len(self.ids(q)), 3)
        p = self.crear('PINGÜINO niño')
        self.assertEqual(self.ids('pinguino'), [p.pk])
        self.assertEqual(self.ids('nin'), [])
        self.assertEqual(self.ids('nin\u0303o'), [p.pk])
        otro = self.crear('pinguino')
        self.assertCountEqual(self.ids('pingu\u0308ino'), [p.pk, otro.pk])

    def test_literales(self):
        for literal in ['50%', 'a_b', '"hola"', 'a/b', 'a\\b', 'a|b', '¿hola?']:
            p = self.crear(literal)
            self.assertEqual(self.ids(literal), [p.pk])
        self.assertEqual(self.ids('"ausente"'), [])
        self.crear('500 axb a/b')
        self.assertEqual(len(self.ids('50%')), 1)
        self.assertEqual(len(self.ids('a_b')), 1)

    def test_validacion(self):
        for valor in [None, '', ' ', 'a', 'a'*151, ' '.join(['ab']*11), 'ab\x00', 'ab\u200b', 'ab\x0b']:
            with self.subTest(valor=repr(valor)), self.assertRaises(EntradaInvalida):
                validar_consulta(valor)
        for valor in ['ab', 'a'*150, ' '.join(['ab']*10), 'e\u0301e', '  ab\t\n cd\u00a0']:
            validar_consulta(valor)
        self.assertEqual(validar_consulta(' Educación  EDUCACION ')[1], ['educacion'])
        self.assertEqual(self.client.get(reverse('buscar_publicaciones')).status_code, 400)

    def test_paginacion_y_historicas(self):
        Publicacion.objects.bulk_create([Publicacion(hash_origen=str(i), titulo='noticia', contenido='texto') for i in range(175)])
        antiguo = Publicacion.objects.order_by('pk').first()
        antiguo.titulo = 'historica'
        antiguo.save()
        self.assertEqual(self.ids('historica'), [antiguo.pk])
        data = self.get('noticia').json()
        self.assertEqual((data['total'], data['total_paginas'], len(data['resultados'])), (174, 9, 20))
        self.assertIsNotNone(data['siguiente'])
        for page in ['0', '-1', '1.5', 'abc', '', '10', '9'*100]:
            self.assertEqual(self.get('noticia', page=page).status_code, 400)
        self.assertEqual(self.get('ausente').json()['resultados'], [])
        self.assertEqual(self.get('ausente', page=2).status_code, 400)

    def test_fechas_respuesta_y_lectura(self):
        ahora = timezone.now()
        a = self.crear('educacion', fecha_captura=ahora)
        b = self.crear('educacion', fecha_publicacion=ahora, fecha_captura=ahora-timedelta(days=1))
        with CaptureQueriesContext(connection) as queries:
            respuesta = self.get()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        datos = respuesta.json()['resultados']
        self.assertEqual([p['id_publicacion_api'] for p in datos], [b.pk, a.pk])
        self.assertEqual([p['fecha_origen'] for p in datos], ['publicacion', 'captura'])
        self.assertEqual(datos[0]['detalle_url'], reverse('noticia', kwargs={'pk': b.pk}))
        self.assertNotIn('contenido', datos[0])
        self.assertIsNone(datos[0]['imagen_url'])
        self.assertEqual(self.get('a').json()['error']['codigo'], 'consulta_invalida')
        for metodo in ['post', 'put', 'patch', 'delete', 'head', 'options']:
            self.assertEqual(getattr(self.client, metodo)(reverse('buscar_publicaciones')).status_code, 405)

    def test_extracto(self):
        texto = '<p>' + 'inicio '*100 + 'educación ' + 'final '*100 + '</p>'
        resultado = extracto(texto, ['educacion'])
        self.assertIn('educación', resultado)
        self.assertTrue(resultado.startswith('…'))
        self.assertLessEqual(len(resultado), 242)
        self.assertNotIn('<p>', resultado)
        self.assertEqual(extracto('<b>Hola</b> &amp; mundo', ['titulo']), 'Hola & mundo')

    def test_relaciones_no_duplican_y_fuente_archivo(self):
        from core.models import Categoria, Tema
        p = self.crear('educacion', fuente='El Territorio (Archivo)', fecha_publicacion=timezone.now())
        categoria = Categoria.objects.create(nombre_categoria='Educación')
        for descripcion in ['Uno', 'Dos']:
            tema = Tema.objects.create(descripcion=descripcion, id_categoria=categoria)
            tema.publicaciones.add(p)
        datos = self.get().json()
        self.assertEqual(datos['total'], 1)
        self.assertEqual(datos['resultados'][0]['fecha_precision'], 'dia')

    def test_sin_servicios_externos(self):
        self.crear('educacion')
        with patch('core.services.scraper.fetch_and_store_elterritorio', side_effect=AssertionError('ingesta')), \
             patch('core.services.scraper.ingestar_historico_elterritorio', side_effect=AssertionError('archivo')), \
             patch('core.services.clasificacion._clasificar_con_ia', side_effect=AssertionError('IA')), \
             patch('requests.sessions.Session.request', side_effect=AssertionError('HTTP')):
            self.assertEqual(self.get().status_code, 200)

    def test_fechas_nulas_sin_cambiar_esquema(self):
        from core.fechas import datos_fecha
        # fecha_captura es NOT NULL: sólo es representable en objetos no persistidos.
        p = Publicacion(fecha_publicacion=None, fecha_captura=None)
        self.assertIsNone(datos_fecha(p)['fecha_efectiva'])
        self.assertIsNone(datos_fecha(p)['fecha_origen'])


    def test_extracto_unicode_expansivo(self):
        # U+0130 baja a dos puntos de código: i + COMBINING DOT ABOVE.
        texto = 'İ'*350 + ' educación ' + 'final '*100
        resultado = extracto(texto, ['educacion'])
        self.assertIn('educación', resultado)
        self.assertTrue(resultado.startswith('…' + 'İ'*79 + ' educación'))
        self.assertLessEqual(len(resultado), 242)
        self.assertNotIn('i\u0307', resultado)

    def test_normalizacion_mapa_completo_en_postgresql(self):
        import unicodedata
        from core.services.buscador import BASES, VOCALES
        a = self.crear(VOCALES.upper())
        b = self.crear(contenido=BASES)
        for consulta in [VOCALES, BASES.upper(), unicodedata.normalize('NFD', VOCALES.upper())]:
            self.assertCountEqual(self.ids(consulta), [a.pk, b.pk])
        self.crear('NINO')
        self.assertEqual(len(self.ids('NIÑO')), 0)

    def test_sql_parametrizado_y_barra_literal(self):
        from core.services.buscador import plegar
        aguja = 'a\\b%_'
        p = self.crear(aguja)
        self.crear('a/bZZ')
        consultas = []

        def capturar(execute, sql, params, many, context):
            consultas.append((sql, params))
            return execute(sql, params, many, context)

        with connection.execute_wrapper(capturar):
            self.assertEqual(self.ids(aguja), [p.pk])
        patron = '%' + connection.ops.prep_for_like_query(plegar(aguja)) + '%'
        self.assertEqual(len(consultas), 2)
        for sql, parametros in consultas:
            self.assertNotIn(aguja, sql)
            self.assertIn(patron, parametros)
        self.assertEqual(self.ids("' OR 1=1 --"), [])

    def test_navegacion_y_esquema_exacto(self):
        from urllib.parse import parse_qs, urlsplit
        Publicacion.objects.bulk_create([
            Publicacion(hash_origen=str(i), titulo='Educación 50% a_b', contenido='contenido')
            for i in range(21)
        ])
        datos = self.get('  EDUCACION  50% a_b  ').json()
        self.assertEqual(set(datos), {'consulta', 'total', 'pagina', 'tamano_pagina',
                                     'total_paginas', 'anterior', 'siguiente', 'resultados'})
        self.assertEqual(set(datos['resultados'][0]), {'id_publicacion_api', 'titulo', 'fuente',
            'fecha_efectiva', 'fecha_dia', 'fecha_precision', 'fecha_origen', 'detalle_url', 'imagen_url', 'extracto'})
        self.assertEqual(parse_qs(urlsplit(datos['siguiente']).query),
                         {'q': ['EDUCACION 50% a_b'], 'page': ['2']})
        segunda = self.client.get(datos['siguiente']).json()
        self.assertEqual((segunda['pagina'], len(segunda['resultados'])), (2, 1))
        self.assertIsNone(segunda['siguiente'])
        self.assertEqual(self.client.get(segunda['anterior']).json(), datos)
        self.assertEqual(self.client.post(reverse('buscar_publicaciones'))['Allow'], 'GET')

    def test_no_oculta_errores_internos(self):
        with patch('core.views_buscador.buscar', side_effect=RuntimeError('fallo interno')):
            with self.assertRaisesMessage(RuntimeError, 'fallo interno'):
                self.get()

    def test_medicion_rechaza_base_no_identificada_antes_de_escribir(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with CaptureQueriesContext(connection) as consultas:
            mensaje = 'Base rechazada' if connection.vendor == 'postgresql' else 'requiere PostgreSQL'
            with self.assertRaisesMessage(CommandError, mensaje):
                call_command('medir_buscador', '--base-desechable')
        self.assertEqual(len(consultas), 1 if connection.vendor == 'postgresql' else 0)
        self.assertTrue(all(c['sql'].startswith('SELECT') for c in consultas))

    def test_medicion_exige_marca_nombre_y_flag(self):
        from unittest.mock import MagicMock
        from django.core.management.base import CommandError
        from core.management.commands import medir_buscador as medir
        for nombre, marca in [('produccion', medir.MARCA_BASE),
                              (medir.PREFIJO_BASE + 'prueba', None)]:
            simulada = MagicMock(vendor='postgresql')
            simulada.cursor.return_value.__enter__.return_value.fetchone.return_value = (nombre, marca)
            with patch.object(medir, 'connection', simulada), patch.object(Publicacion.objects, 'exists') as existe:
                with self.assertRaises(CommandError):
                    medir.verificar_base_desechable()
                existe.assert_not_called()
        with patch.object(medir, 'verificar_base_desechable') as verificar:
            with self.assertRaises(CommandError):
                medir.Command().handle(base_desechable=False)
            verificar.assert_not_called()
        with patch.object(medir, 'connection', MagicMock(vendor='sqlite')):
            with self.assertRaises(CommandError):
                medir.verificar_base_desechable()

    def test_medicion_rechaza_publicaciones_y_revierte_errores(self):
        from io import StringIO
        from unittest.mock import MagicMock
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from core.management.commands import medir_buscador as medir
        simulada = MagicMock(vendor='postgresql')
        simulada.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            medir.PREFIJO_BASE + 'prueba', medir.MARCA_BASE)
        self.crear('existente')
        with patch.object(medir, 'connection', simulada):
            with self.assertRaisesMessage(CommandError, 'vacía'):
                medir.verificar_base_desechable()
        if connection.vendor != 'postgresql':
            return  # El diagnóstico de rendimiento sólo admite PostgreSQL.
        # Habilitar el guard únicamente sobre esta base aislada del TestCase.
        with patch.object(medir, 'verificar_base_desechable'), \
             patch.object(medir.Client, 'get', side_effect=RuntimeError('corte sintético')):
            with self.assertRaisesMessage(RuntimeError, 'corte sintético'):
                call_command('medir_buscador', '--base-desechable', stdout=StringIO())
        self.assertEqual(list(Publicacion.objects.values_list('titulo', flat=True)), ['existente'])


    def test_incluye_publicaciones_sin_clasificar_ni_procesar(self):
        a = self.crear('Propuesta educativa', departamento='', procesado_ia=False)
        b = self.crear(contenido='Otra propuesta educativa', departamento='', procesado_ia=False)
        self.assertFalse(a.temas.exists())
        self.assertFalse(b.temas.exists())
        self.assertCountEqual(self.ids('educat'), [a.pk, b.pk])
