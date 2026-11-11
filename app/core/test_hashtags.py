from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from core.models import Publicacion
from core.services.clasificacion import vincular_categoria_por_nombre


class HashtagsTests(TestCase):
    def crear(self, titulo, contenido='Texto de prueba', categorias=(), **datos):
        publicacion = Publicacion.objects.create(
            titulo=titulo, contenido=contenido, hash_origen=f'h{Publicacion.objects.count()}', **datos)
        for categoria in categorias:
            vincular_categoria_por_nombre(publicacion, categoria)
        return publicacion

    def hashtags(self, q):
        respuesta = self.client.get(reverse('hashtags_publicaciones'), {'q': q})
        self.assertEqual(respuesta.status_code, 200)
        return {h['texto']: h for h in respuesta.json()['hashtags']}

    def pagina(self, q, **datos):
        return self.client.get(reverse('buscar_noticias'), {'q': q, **datos})

    def setUp(self):
        self.anuncio = self.crear('El gobernador Passalacqua anunció un aumento', categorias=['Economía'],
                                  departamento='capital')
        self.viaje = self.crear('Passalacqua viajó a Oberá', categorias=['Política', 'Economía'],
                                departamento='obera')
        # Mención sólo en el contenido y con otra grafía: el filtro igual la encuentra.
        self.mencion = self.crear('Reunión gremial', contenido='Participó el gobernador PASSALACQUA.')
        # "Passo" coincide con "pass" pero sólo va en mayúscula al comenzar el título.
        self.passo = self.crear('Passo Fundo recibe estudiantes', contenido='El intercambio sigue.')
        # Resto del archivo: sin relación con estas búsquedas. La afinidad compara la
        # búsqueda con el archivo completo, así que hace falta un archivo realista.
        for titulo in ['Feria de artesanos', 'Torneo de ajedrez escolar', 'Corte programado de energía',
                       'Nueva ruta asfaltada', 'Muestra de pintura', 'Campaña de vacunación']:
            self.crear(titulo, contenido='Texto de prueba')

    def test_entidades_reales_con_conteo_igual_al_filtro(self):
        datos = self.hashtags('pass')
        self.assertIn('#Passalacqua', datos)
        etiqueta = datos['#Passalacqua']
        self.assertEqual((etiqueta['valor'], etiqueta['tipo']), ('ent:passalacqua', 'ent'))
        # Cuenta título y contenido: tres noticias, no sólo las dos con el nombre en el título.
        self.assertEqual(etiqueta['total'], 3)
        filtrada = self.client.get(reverse('buscar_publicaciones'), {'q': 'pass', 'h': etiqueta['valor']}).json()
        self.assertEqual(filtrada['total'], etiqueta['total'])
        self.assertEqual({r['id_publicacion_api'] for r in filtrada['resultados']},
                         {self.anuncio.pk, self.viaje.pk, self.mencion.pk})

    def test_no_inventa_etiquetas(self):
        textos = set(self.hashtags('pass'))
        # Mayúscula sólo al comienzo del título no es nombre propio; minúsculas tampoco.
        self.assertNotIn('#Passo', textos)
        self.assertNotIn('#Gobernador', textos)
        # Dos palabras con mayúscula seguidas forman un solo nombre propio.
        self.assertIn('#PassoFundo', textos)

    def test_palabras_comunes_con_mayuscula_ocasional(self):
        self.crear('Alerta por El Niño en la región', contenido='Lluvias intensas.')
        self.crear('Rescatan a un niño en la costa', contenido='Lluvias intensas.')
        self.crear('Un niño ganó el torneo', contenido='Lluvias intensas.')
        self.assertNotIn('#Niño', self.hashtags('lluvias'))

    def test_nombre_que_en_el_contenido_es_palabra_comun(self):
        self.crear('Surge el bloque Movimiento por lo que Viene', contenido='El sector viene creciendo.')
        self.crear('Debate en el bloque', contenido='Se viene una sesión larga.')
        self.crear('Clima: El Niño golpea las colonias', contenido='Persisten las lluvias por El Niño.')
        datos = self.hashtags('bloque')
        self.assertIn('#Movimiento', datos)
        if connection.vendor == 'postgresql':
            # La comparación sensible a mayúsculas sobre el contenido sólo se hace en PostgreSQL.
            self.assertNotIn('#Viene', datos)  # " viene" supera a " Viene" en el contenido
        self.assertIn('#Niño', self.hashtags('colonias'))  # aquí es el fenómeno climático

    def test_nombres_compuestos(self):
        from core.services.hashtags import nombres_propios
        self.assertEqual(nombres_propios('Recital en el Parque de las Naciones de Oberá'),
                         [['Parque', 'de', 'las', 'Naciones'], ['Oberá']])
        self.assertIn(['San', 'Ignacio'], nombres_propios('Turismo récord en San Ignacio'))
        self.assertEqual(nombres_propios('Passalacqua anunció un aumento'), [])
        self.assertEqual(nombres_propios('"Llevaste nuestra camiseta": el mensaje de Passalacqua'),
                         [['Passalacqua']])
        self.crear('Recital en el Parque de las Naciones', contenido='Música en el parque de las naciones.')
        datos = self.hashtags('recital')
        self.assertEqual(datos['#ParqueDeLasNaciones']['valor'], 'ent:parque-de-las-naciones')
        filtrada = self.pagina('recital', h='ent:parque-de-las-naciones')
        self.assertEqual(filtrada.context['total'], 1)
        self.assertEqual(filtrada.context['hashtag_activo']['texto'], '#ParqueDeLasNaciones')
        self.assertEqual(self.hashtags('inexistente'), {})
        Publicacion.objects.all().delete()
        self.assertEqual(self.hashtags('pass'), {})

    def test_categorias_y_departamentos_desde_datos_guardados(self):
        datos = self.hashtags('passalacqua')
        self.assertEqual(datos['#Economía']['total'], 2)
        self.assertEqual(datos['#Política']['total'], 1)
        self.assertEqual(datos['#Capital']['valor'], 'dep:capital')
        # Oberá figura como departamento, no repetida como palabra del título.
        self.assertEqual(datos['#Oberá']['valor'], 'dep:obera')
        self.assertEqual(sum(1 for texto in datos if texto.casefold() == '#oberá'), 1)
        # El hashtag de la propia consulta encabeza la lista.
        self.assertEqual(next(iter(datos)), '#Passalacqua')
        for texto in datos:
            self.assertNotIn(texto, {'#Salud', '#Deportes', '#Iguazú'})

    def test_normaliza_mayusculas_y_acentos(self):
        self.crear('Llegó la delegación de POSADAS', contenido='Visita oficial')
        self.crear('Obras en Posadas', contenido='Visita oficial')
        self.assertEqual(list(self.hashtags('POSADAS'))[:1], ['#Posadas'])
        datos = self.hashtags('visita')
        # Una sola etiqueta para ambas grafías, escrita como nombre propio.
        self.assertEqual([t for t in datos if t.casefold() == '#posadas'], ['#Posadas'])
        self.assertEqual(datos['#Posadas']['total'], 2)

    def test_filtro_categoria_sin_duplicados_y_combinado_con_texto(self):
        respuesta = self.pagina('passalacqua', h='cat:economia')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['total'], 2)
        self.assertEqual(self.pagina('viajo', h='cat:economia').context['total'], 1)
        self.assertEqual(self.pagina('aumento', h='dep:obera').context['total'], 0)

    def test_hashtag_activo_marcado_y_se_puede_quitar(self):
        respuesta = self.pagina('pass', h='ent:passalacqua')
        contenido = respuesta.content.decode()
        self.assertEqual(respuesta.context['total'], 3)
        activo = respuesta.context['hashtag_activo']
        self.assertEqual(activo['texto'], '#Passalacqua')
        self.assertIn('aria-current="true"', contenido)
        self.assertEqual(parse_qs(urlsplit(activo['url']).query), {'q': ['pass']})
        self.assertContains(respuesta, 'Quitar filtro y ver todas')
        self.assertEqual(self.pagina('pass').context['total'], 4)

    def test_hashtags_antes_de_las_sugerencias_y_solo_en_la_pagina(self):
        contenido = self.pagina('pass').content.decode()
        formulario = contenido.index('id="page-search-q"')
        chips = contenido.index('search-hashtags--page')
        cierre = contenido.index('</form>', formulario)
        # Dentro del formulario y antes de su cierre, donde el script agrega el panel.
        self.assertLess(formulario, chips)
        self.assertLess(chips, cierre)
        self.assertEqual(contenido.count('search-hashtags--page'), 1)
        self.assertContains(self.pagina('pass'), reverse('hashtags_publicaciones'))

    def test_paginacion_conserva_el_filtro(self):
        Publicacion.objects.bulk_create([
            Publicacion(hash_origen=f'p{i}', titulo=f'Visita de Passalacqua número {i}', contenido='-')
            for i in range(21)
        ])
        siguiente = self.pagina('visita', h='ent:passalacqua').context['siguiente']
        self.assertEqual(parse_qs(urlsplit(siguiente).query)['h'], ['ent:passalacqua'])
        api = self.client.get(reverse('buscar_publicaciones'), {'q': 'visita', 'h': 'ent:passalacqua'}).json()
        self.assertEqual(parse_qs(urlsplit(api['siguiente']).query)['h'], ['ent:passalacqua'])

    def test_valores_invalidos(self):
        for valor in ['x:abc', 'ent:', 'ent:Passalacqua', 'ent:ab', 'cat:inexistente', 'dep:posadas',
                      'ent:a b', 'ent:\x00abc', 'ent:' + 'a' * 51, 'ent:1234']:
            with self.subTest(valor=valor):
                self.assertEqual(self.pagina('pass', h=valor).status_code, 400)
                api = self.client.get(reverse('buscar_publicaciones'), {'q': 'pass', 'h': valor})
                self.assertEqual(api.json()['error']['codigo'], 'hashtag_invalido')
        # Sin consulta no se busca ni se valida el filtro.
        self.assertEqual(self.pagina('', h='x:abc').status_code, 200)

    def test_endpoint_contrato_y_errores(self):
        respuesta = self.client.get(reverse('hashtags_publicaciones'), {'q': 'pass'})
        self.assertEqual(respuesta['Cache-Control'], 'no-store')
        datos = respuesta.json()
        self.assertEqual(set(datos), {'consulta', 'hashtags'})
        self.assertEqual(set(datos['hashtags'][0]), {'valor', 'texto', 'tipo', 'descripcion', 'total'})
        self.assertLessEqual(len(datos['hashtags']), 8)
        with self.assertNumQueries(4):  # títulos, búsqueda, archivo, categorías
            self.client.get(reverse('hashtags_publicaciones'), {'q': 'pass'})
        for q in ['', 'a', 'a' * 151]:
            self.assertEqual(self.client.get(reverse('hashtags_publicaciones'), {'q': q}).status_code, 400)
        self.assertEqual(self.client.post(reverse('hashtags_publicaciones'), {'q': 'pass'}).status_code, 405)

    def test_sugerencias_conservan_su_contrato(self):
        datos = self.client.get(reverse('sugerencias_publicaciones'), {'q': 'pass'}).json()
        self.assertEqual(set(datos), {'consulta', 'terminos', 'noticias'})

    def test_variantes_de_mayusculas_y_acentos_son_equivalentes(self):
        self.crear('Debate político en la Legislatura', contenido='Sesión sobre política provincial.',
                   categorias=['Política'])
        variantes = [self.hashtags(q) for q in ['política', 'Política', 'POLÍTICA', 'politica']]
        self.assertTrue(variantes[0])
        self.assertTrue(all(v == variantes[0] for v in variantes))
        self.assertEqual(next(iter(variantes[0])), '#Política')  # coincide con la consulta
        self.assertIn('#Legislatura', variantes[0])

    def test_se_ordenan_por_afinidad_y_no_por_volumen(self):
        # "Misiones" figura en todo el archivo: no describe una búsqueda en particular.
        for titulo in ['Turismo en Misiones', 'Lluvias en Misiones', 'Ferias en Misiones',
                       'Rutas de Misiones', 'Salud en Misiones']:
            self.crear(titulo, contenido='Texto de prueba')
        self.crear('Sesión de la Legislatura en Misiones', contenido='Sesión de diputados.')
        self.crear('La Legislatura aprobó el presupuesto de Misiones', contenido='Sesión de diputados.')
        datos = self.hashtags('sesion')
        self.assertIn('#Legislatura', datos)
        self.assertLess(list(datos).index('#Legislatura'), list(datos).index('#Misiones')
                        if '#Misiones' in datos else len(datos))

    def test_estado_inicial_vacio(self):
        for url in [reverse('buscar_noticias'), reverse('landing')]:
            with self.subTest(url=url):
                contenido = self.client.get(url).content.decode()
                self.assertNotIn('hashtag-chip', contenido)
                self.assertNotIn('search-hashtags--page', contenido)
                self.assertRegex(contenido, r'name="q" value=""')
                self.assertIn('placeholder="Buscar noticias, personas, localidades o temas…"', contenido)
                self.assertIn('autocomplete="off"', contenido)
        # Una consulta vacía o de espacios vuelve al estado inicial, sin hashtags.
        for q in ['', '   ']:
            self.assertNotIn('hashtag-chip', self.pagina(q).content.decode())

    def test_cambiar_de_consulta_cambia_los_hashtags(self):
        primera, segunda = set(self.hashtags('passalacqua')), set(self.hashtags('ajedrez'))
        self.assertIn('#Passalacqua', primera)
        self.assertFalse(primera & segunda)
        # La página guarda la consulta de sus chips para ocultarlos si se edita el texto.
        self.assertIn('data-consulta="passalacqua"', self.pagina('passalacqua').content.decode())
