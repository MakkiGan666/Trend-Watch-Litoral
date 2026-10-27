from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from core.models import Publicacion


class SugerenciasTests(TestCase):
    def crear(self, titulo, contenido='Texto de prueba', **kwargs):
        return Publicacion.objects.create(titulo=titulo, contenido=contenido,
            hash_origen=str(Publicacion.objects.count()), **kwargs)

    def get(self, q):
        return self.client.get(reverse('sugerencias_publicaciones'), {'q': q})

    def test_validacion_y_metodos(self):
        for q in ['', 'a', 'a'*151, '\x00mi', 'mi '*11]:
            with self.subTest(q=q):
                with self.assertNumQueries(0):
                    self.assertEqual(self.get(q).status_code, 400)
        self.assertEqual(self.client.get(reverse('sugerencias_publicaciones')).status_code, 400)
        self.assertEqual(self.client.post(reverse('sugerencias_publicaciones')).status_code, 405)

    def test_prefijo_frecuencia_y_limites(self):
        self.crear('Misiones Misiones Milei Ministerio Minería Militancia Militar Mirada')
        self.crear('Misiones crece')
        with self.assertNumQueries(2):
            data = self.get('Mi').json()
        self.assertEqual(len(data['terminos']), 5)
        self.assertEqual(data['terminos'][0]['texto'], 'Misiones')
        self.assertEqual(len({t['texto'].lower() for t in data['terminos']}), 5)
        self.assertTrue(all(t['texto'].lower().startswith('mi') for t in data['terminos']))

    def test_normalizacion_y_enes(self):
        self.crear('MINERI\u0301A niño nido pingüino')
        for q, palabra in [('mi', 'MINERÍA'), ('MINÉ', 'MINERÍA'), ('niñ', 'niño'), ('pingu', 'pingüino')]:
            with self.subTest(q=q):
                self.assertIn(palabra, [t['texto'] for t in self.get(q).json()['terminos']])
        self.assertNotIn('niño', [t['texto'] for t in self.get('nin').json()['terminos']])

    def test_contexto_varias_palabras(self):
        self.crear('Obras de Misiones')
        self.crear('Ministerio nuevo', contenido='Obras públicas')
        self.crear('Militancia sin contexto')
        data = self.get('obras mi').json()
        self.assertTrue(data['terminos'])
        self.assertTrue(all(t['consulta'].startswith('obras ') for t in data['terminos']))
        self.assertNotIn('Militancia sin contexto', [n['titulo'] for n in data['noticias']])

    def test_noticias_titulo_antes_de_contenido(self):
        self.crear('Sólo contenido', contenido='Misiones')
        titulo = self.crear('Misiones educación', procesado_ia=False, departamento='')
        for i in range(6):
            self.crear(f'Misiones {i}')
        data = self.get('mi').json()
        self.assertEqual(len(data['noticias']), 4)
        self.assertNotIn('Sólo contenido', [n['titulo'] for n in data['noticias']])
        self.assertEqual(self.get('educacion').json()['noticias'][0]['url'], reverse('noticia', kwargs={'pk': titulo.pk}))
        self.assertEqual(titulo.temas.count(), 0)

    def test_contenido_y_vacio(self):
        p = self.crear('Título diferente', contenido='economía')
        data = self.get('economia').json()
        self.assertEqual(data['terminos'], [])
        self.assertEqual(data['noticias'][0]['url'], reverse('noticia', kwargs={'pk': p.pk}))
        self.assertEqual(self.get('inexistente').json()['noticias'], [])

    def test_literales_lectura_y_actualizacion(self):
        p = self.crear('Misiones <script>alert(1)</script>')
        for q in ['%_', "mi' OR 1=1 --", '\\\\mi']:
            self.assertEqual(self.get(q).json()['noticias'], [])
        with self.assertNumQueries(2), patch.object(Publicacion, 'save', side_effect=AssertionError('escritura')):
            respuesta = self.get('mi')
        self.assertEqual(respuesta['Cache-Control'], 'no-store')
        Publicacion.objects.filter(pk=p.pk).update(titulo='Minería')
        self.assertEqual(self.get('mi').json()['terminos'][0]['texto'], 'Minería')
        p.delete()
        self.assertEqual(self.get('mi').json()['terminos'], [])

    def test_formularios_comparten_endpoint(self):
        response = self.client.get(reverse('buscar_noticias'))
        self.assertContains(response, reverse('sugerencias_publicaciones'))

    def test_ultima_palabra_repetida_conserva_contexto(self):
        self.crear('Misiones obras')
        self.crear('Obras misioneras')
        data = self.get('misiones obras misiones').json()
        self.assertTrue(data['terminos'])
        self.assertTrue(all(t['consulta'].startswith('misiones obras ') for t in data['terminos']))
        self.assertTrue(all(t['texto'].lower().startswith('misiones') for t in data['terminos']))

    def test_sugerencias_seleccionables_no_exceden_contrato(self):
        self.crear('ab' + 'c'*149)
        self.crear('İ válido')
        self.assertEqual(self.get('ab').json()['terminos'], [])
        self.assertEqual(self.get('i\u0307').json()['terminos'], [])

    def test_origen_publico_compartido_sin_clasificacion(self):
        from core.services.buscador import publicaciones_coincidentes
        visible = self.crear('Misiones público', contenido='economía', departamento='', procesado_ia=False)
        self.crear('Ministerio excluido')
        def alcance(terminos):
            return publicaciones_coincidentes(terminos).filter(pk=visible.pk)
        with patch('core.services.sugerencias.publicaciones_coincidentes', side_effect=alcance):
            data = self.get('mi').json()
            self.assertEqual([n['url'] for n in data['noticias']], [reverse('noticia', args=[visible.pk])])
            self.assertNotIn('Ministerio', [t['texto'] for t in data['terminos']])
        for consulta in ['misiones', 'economia']:
            self.assertIn(reverse('noticia', args=[visible.pk]), [n['url'] for n in self.get(consulta).json()['noticias']])

    def test_solo_select_sin_http_y_errores_no_disfrazados(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.crear('Misiones')
        with patch('requests.sessions.Session.request', side_effect=AssertionError('HTTP externo')), CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.get('mi').status_code, 200)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(q['sql'].lstrip().startswith(('WITH', 'SELECT')) for q in queries))
        with patch('core.services.sugerencias.sugerir', side_effect=RuntimeError('interno')):
            with self.assertRaises(RuntimeError): self.get('mi')
        self.assertEqual(self.get('x')['Cache-Control'], 'no-store')

    def test_escape_literal_de_underscore_porcentaje_y_barra(self):
        self.crear('mi_literal mifalso')
        datos = self.get('mi_').json()
        self.assertEqual([t['texto'] for t in datos['terminos']], ['mi_literal'])
        for consulta in ['mi%', 'mi\\']:
            self.assertEqual(self.get(consulta).json()['terminos'], [])

    def test_ranking_numero_de_terminos_y_desempates(self):
        from datetime import datetime, timezone
        fecha = datetime(2026,10,23,12,tzinfo=timezone.utc)
        contenido = self.crear('Otra noticia', contenido='educación provincial', fecha_captura=fecha)
        uno = self.crear('Educación nueva', contenido='provincial', fecha_captura=fecha)
        ambos = self.crear('Educación provincial', fecha_captura=fecha)
        ultimo = self.crear('Educación provincial reciente', fecha_captura=fecha)
        urls = [n['url'] for n in self.get('educacion provincial').json()['noticias']]
        self.assertEqual(urls, [reverse('noticia', args=[p.pk]) for p in [ultimo,ambos,uno,contenido]])

    def test_formato_acceso_anonimo_y_mismo_alcance_busqueda(self):
        p = self.crear('Niño de Misiones', contenido='economía educativa', procesado_ia=False, departamento='')
        for consulta in ['NIÑO', 'misio', 'economia educativa']:
            datos = self.get(consulta).json()
            self.assertEqual(set(datos), {'consulta','terminos','noticias'})
            self.assertEqual(datos['noticias'], [{'titulo':p.titulo,'url':reverse('noticia',args=[p.pk])}])
            busqueda = self.client.get(reverse('buscar_publicaciones'), {'q':consulta}).json()
            self.assertEqual(busqueda['total'],1)
        self.assertEqual(self.get('nino').json()['noticias'],[])
        for metodo in ['head','put','delete','options']:
            self.assertEqual(getattr(self.client,metodo)(reverse('sugerencias_publicaciones')).status_code,405)
