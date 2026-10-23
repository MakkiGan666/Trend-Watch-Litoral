"""Compatibilidad temática previa a CAT-02: sin red ni IA reales."""
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.categorias import datos_categorias
from core.models import Categoria, Publicacion, PublicacionTema, Tema
from core.test_ingesta_historico import IngestaSimuladaMixin, BASE


class IngestaCategoriaConfirmadaTestCase(IngestaSimuladaMixin, TestCase):
    def test_incierta_se_guarda_sin_asignar_sociedad(self):
        resultado = self.ingerir(('Lorem ipsum', BASE + '990100-incierta', 'dolor sit amet'))
        self.assertEqual((resultado['status'], resultado['estado']), ('EXITO', 'EXITO'))
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(resultado['sin_categoria'], 1)
        self.assertEqual(resultado['categorias'], {})
        self.assertFalse(PublicacionTema.objects.exists())
        self.assertFalse(Categoria.objects.filter(nombre_categoria='Sociedad').exists())

    def test_sociedad_con_evidencia_local_se_asocia(self):
        resultado = self.ingerir(('Vecinos del barrio ayudan a la comunidad', BASE + '990101-sociedad', 'Resumen'))
        self.assertEqual(resultado['categorias'], {'Sociedad': 1})
        self.assertEqual(resultado['sin_categoria'], 0)
        self.assertEqual(list(Publicacion.objects.get().temas.values_list(
            'id_categoria__nombre_categoria', flat=True)), ['Sociedad'])

    def test_respuesta_ia_validada_confirma_una_propuesta(self):
        with patch('core.services.clasificacion._clasificar_con_ia', return_value={0: 'Turismo'}):
            resultado = self.ingerir(('Lorem ipsum', BASE + '990102-ia', 'Resumen'))
        self.assertEqual(resultado['categorias'], {'Turismo': 1})
        self.assertEqual(resultado['sin_categoria'], 0)

    def test_reingesta_no_reclasifica_ni_borra_asociaciones_historicas(self):
        link = BASE + '990103-legacy'
        primera = self.ingerir(('Vecinos del barrio ayudan a la comunidad', link, 'Resumen'))
        p = Publicacion.objects.get()
        extra = Categoria.objects.create(nombre_categoria='Categoría histórica ajena al catálogo')
        tema = Tema.objects.create(id_categoria=extra, descripcion='Tema específico histórico')
        PublicacionTema.objects.create(id_publicacion_api=p, id_temas=tema)
        antes = list(PublicacionTema.objects.order_by('pk').values())
        segunda = self.ingerir(('Lorem ipsum', link, 'Resumen'))
        self.assertEqual(primera['capturados'], 1)
        self.assertEqual((segunda['estado'], segunda['omitidas']), ('DUPLICADOS', 1))
        self.assertEqual(list(PublicacionTema.objects.order_by('pk').values()), antes)

    def test_resultado_sin_confirmacion_explicita_no_crea_vinculo(self):
        with patch('core.services.scraper.clasificar_lote', return_value=[{
            'categoria': 'Sociedad', 'departamento': '', 'metodo': 'reglas',
        }]):
            resultado = self.ingerir(('Lorem ipsum', BASE + '990104-sin-marca', 'Resumen'))
        self.assertEqual(resultado['sin_categoria'], 1)
        self.assertFalse(PublicacionTema.objects.exists())


class LecturaCategoriasCompatTestCase(TestCase):
    def setUp(self):
        self.p = Publicacion.objects.create(hash_origen='lectura-cat', titulo='Noticia histórica',
                                            contenido='Texto', fuente='El Territorio (Misiones)',
                                            departamento='capital')
        self.salud = Categoria.objects.create(nombre_categoria='Salud')
        self.turismo = Categoria.objects.create(nombre_categoria='Turismo')
        for categoria, descripcion in ((self.salud, 'Específico 1'), (self.salud, 'Específico 2'),
                                       (self.turismo, 'Específico 3')):
            tema = Tema.objects.create(id_categoria=categoria, descripcion=descripcion)
            PublicacionTema.objects.create(id_publicacion_api=self.p, id_temas=tema)

    def test_lectura_no_modifica_relaciones_y_deduplica_por_categoria(self):
        antes = list(PublicacionTema.objects.order_by('pk').values())
        datos = datos_categorias(self.p)
        self.assertEqual(datos['categorias'], ['Salud', 'Turismo'])
        self.assertEqual(len(datos['categorias_detalle']), 2)
        self.assertEqual(list(PublicacionTema.objects.order_by('pk').values()), antes)

    def test_global_localidad_y_detalle_api_comparten_representacion(self):
        global_ = self.client.get(reverse('listar_publicaciones')).json()['data'][0]
        local = self.client.get(reverse('publicaciones_localidad', args=['capital'])).json()['data'][0]
        # Usar la ruta nombrada existente de detalle, sin publicar un endpoint nuevo.
        from core.views import obtener_detalle_publicacion
        from django.test import RequestFactory
        import json
        detalle = json.loads(obtener_detalle_publicacion(RequestFactory().get('/detalle/'), self.p.pk).content)
        for dato in (global_, local, detalle):
            self.assertEqual(dato['categorias'], ['Salud', 'Turismo'])
            self.assertEqual(dato['categorias_detalle'], global_['categorias_detalle'])
            self.assertEqual(dato['categorias_origen'], 'asociaciones')
            self.assertEqual(dato['seccion_origen'], 'Misiones')

    def test_seccion_no_se_presenta_como_categoria_asociada(self):
        otra = Publicacion.objects.create(hash_origen='sin-categoria', titulo='Sin categoría', contenido='Texto',
                                          fuente='El Territorio (Archivo)')
        dato = datos_categorias(otra)
        self.assertEqual(dato['categorias'], ['Archivo'])  # compatibilidad legacy
        self.assertEqual(dato['categorias_detalle'], [])
        respuesta = self.client.get(reverse('noticia', args=[otra.pk]))
        self.assertContains(respuesta, 'Sin categoría asociada')
        self.assertContains(respuesta, 'Sección: Archivo')

    def test_dashboard_y_detalle_muestran_todas_las_categorias_asociadas(self):
        usuario = get_user_model().objects.create_superuser(username='categorias-panel')
        self.client.force_login(usuario)
        panel = self.client.get(reverse('publicaciones'))
        p = list(panel.context['publicaciones'])[0]
        self.assertEqual(p.dashboard_categorias, [self.salud.pk, self.turismo.pk])
        self.assertEqual(p.categorias_navegacion, ['Salud', 'Turismo'])
        detalle = self.client.get(reverse('noticia', args=[self.p.pk]))
        self.assertEqual(detalle.context['categorias_noticia'], p.categorias_navegacion)

    def test_nombre_ajeno_se_conserva_sin_inventar_codigo(self):
        nombre = 'Categoría histórica'
        categoria = Categoria.objects.create(nombre_categoria=nombre)
        tema = Tema.objects.create(id_categoria=categoria, descripcion='Tema heredado')
        PublicacionTema.objects.create(id_publicacion_api=self.p, id_temas=tema)
        dato = datos_categorias(self.p)
        self.assertIn(nombre, dato['categorias'])
        self.assertNotIn('codigo', dato['categorias_detalle'][-1])
