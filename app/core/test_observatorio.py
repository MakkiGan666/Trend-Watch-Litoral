"""Portada del observatorio y panel de observación: datos reales, filtros y roles."""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core.fechas import ZONA_LOCAL
from core.models import (
    Categoria, Comentario, Publicacion, PublicacionTema, SentimientoComentario, Tema,
)
from core.services.observatorio import hoy_local, resumen_portada
from core.services.sentimiento_comentarios import calcular_texto_hash


class ObservatorioBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser('obs_root', 'obs@example.com', None)
        cls.admin = get_user_model().objects.create_user('obs_admin', is_staff=True)
        cls.admin.user_permissions.set(Permission.objects.all())
        cls.lector = get_user_model().objects.create_user('obs_lector')
        cls.salud = Categoria.objects.create(nombre_categoria='Salud')
        cls.educacion = Categoria.objects.create(nombre_categoria='Educación')
        cls.hoy = hoy_local()
        # Período actual (últimos 30 días hasta hoy).
        cls.a = cls.noticia('hoy-capital', 0, 'capital', cls.salud)
        cls.b = cls.noticia('capital-3', 3, 'capital', cls.salud)
        cls.c = cls.noticia('obera-10', 10, 'obera', cls.educacion)
        cls.d = cls.noticia('provincial-5', 5, '', cls.salud, titulo='Represa Urugua-í en revisión')
        # Período anterior (31 a 60 días atrás).
        cls.e = cls.noticia('obera-40', 40, 'obera', cls.educacion)
        cls.f = cls.noticia('iguazu-45', 45, 'iguazu', cls.educacion)
        # Una fecha futura no debe anclar los períodos.
        cls.g = cls.noticia('futura', -5, 'capital')

    @classmethod
    def noticia(cls, clave, dias_atras, departamento, categoria=None, titulo=None):
        dia = cls.hoy - timedelta(days=dias_atras)
        publicacion = Publicacion.objects.create(
            hash_origen=clave, titulo=titulo or clave, contenido='Texto de prueba',
            departamento=departamento, fuente='Fuente prueba',
            fecha_publicacion=datetime.combine(dia, time(12), tzinfo=ZONA_LOCAL),
        )
        if categoria:
            tema = Tema.objects.create(descripcion=clave, id_categoria=categoria)
            PublicacionTema.objects.create(id_publicacion_api=publicacion, id_temas=tema)
        return publicacion


class ResumenPortadaTests(ObservatorioBase):
    def test_indicadores_reales_de_la_agenda_reciente(self):
        resumen = resumen_portada()
        self.assertEqual(resumen['total'], 7)
        self.assertEqual(resumen['fin'], self.hoy)
        comparacion = resumen['comparacion']
        self.assertEqual((comparacion['actual'], comparacion['anterior'], comparacion['variacion']), (4, 2, 100))
        temas = {t['nombre']: (t['actual'], t['anterior'], t['diferencia']) for t in comparacion['temas']}
        self.assertEqual(temas, {'Salud': (3, 0, 3), 'Educación': (1, 2, -1)})
        self.assertEqual(resumen['temas_presentes'], 2)
        territorio = resumen['territorio']
        self.assertEqual(len(territorio['departamentos']), 17)
        self.assertEqual(territorio['con_cobertura'], 2)
        self.assertEqual(territorio['sin_identificar'], 1)
        self.assertEqual([(f['slug'], f['total']) for f in resumen['departamentos']], [('capital', 2), ('obera', 1)])
        semanas = resumen['semanas']
        self.assertEqual(len(semanas), 12)
        self.assertEqual(semanas[-1]['fin'], self.hoy)
        self.assertEqual(semanas[-1]['total'], 3)
        self.assertEqual(sum(s['total'] for s in semanas), 6)

    def test_sin_publicaciones_no_inventa_resumen(self):
        Publicacion.objects.all().delete()
        self.assertIsNone(resumen_portada())
        response = self.client.get(reverse('landing'))
        self.assertContains(response, 'Todavía no hay publicaciones registradas')


class PortadaObservatorioTests(ObservatorioBase):
    def test_portada_publica_para_anonimos_y_lectores_sin_panel(self):
        for usuario in (None, self.lector):
            self.client.logout()
            if usuario:
                self.client.force_login(usuario)
            response = self.client.get(reverse('landing'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'id="observatorio-title"')
            self.assertContains(response, 'Observatorio de la agenda mediática de Misiones')
            self.assertContains(response, 'href="/localidad/capital/"')
            self.assertContains(response, 'href="/categorias/salud/"')
            self.assertNotContains(response, 'href="/dashboard/"')
            self.assertNotContains(response, 'Abrir panel de análisis')
            self.assertEqual(response.context['observatorio']['comparacion']['actual'], 4)

    def test_administrador_accede_al_panel_desde_la_portada(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('landing'))
        self.assertContains(response, 'Abrir panel de análisis')
        html = response.content.decode()
        self.assertLess(html.index('id="observatorio-title"'), html.index('id="inicio-indicadores"'))
        self.assertLess(html.index('id="inicio-indicadores"'), html.index('id="regional-news-title"'))


class PanelObservacionTests(ObservatorioBase):
    def setUp(self):
        self.client.force_login(self.root)

    def get(self, **params):
        return self.client.get(reverse('dashboard'), params)

    def test_roles_se_conservan(self):
        self.client.force_login(self.lector)
        self.assertEqual(self.get().status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.get().status_code, 200)

    def test_busqueda_filtra_y_estado_vacio(self):
        response = self.get(q='urugua')
        self.assertEqual(response.context['resumen']['total'], 1)
        vacia = self.get(q='palabrainexistentexyz')
        self.assertEqual(vacia.status_code, 200)
        self.assertEqual(vacia.context['resumen']['total'], 0)
        self.assertContains(vacia, 'Sin publicaciones para estos filtros')

    def test_periodo_rapido_y_conflicto_con_fechas(self):
        response = self.get(periodo='7')
        self.assertEqual(response.context['resumen']['total'], 3)
        self.assertEqual(self.get(periodo='7', desde=str(self.hoy)).status_code, 400)
        self.assertEqual(self.get(periodo='15').status_code, 400)

    def test_comparacion_y_temas_en_aumento_o_descenso(self):
        comparacion = self.get().context['comparacion']
        self.assertTrue(comparacion['automatica'])
        self.assertEqual((comparacion['fin'], comparacion['actual'], comparacion['anterior']), (self.hoy, 4, 2))
        self.assertEqual([(t['nombre'], t['diferencia']) for t in comparacion['en_aumento']], [('Salud', 3)])
        self.assertEqual([(t['nombre'], t['diferencia']) for t in comparacion['en_descenso']], [('Educación', -1)])
        rango = self.get(desde=str(self.hoy - timedelta(days=9)), hasta=str(self.hoy)).context['comparacion']
        self.assertFalse(rango['automatica'])
        self.assertEqual((rango['dias'], rango['actual'], rango['anterior']), (10, 3, 1))

    def test_departamento_ranking_comparable_y_foco(self):
        response = self.get(departamento='capital')
        self.assertEqual(response.context['resumen']['total'], 3)
        ranking = {f['slug']: f for f in response.context['departamentos']}
        self.assertEqual(len(ranking), 17)
        self.assertTrue(ranking['capital']['seleccionado'])
        self.assertEqual((ranking['capital']['total'], ranking['obera']['total'], ranking['iguazu']['total']), (3, 2, 1))
        self.assertEqual(ranking['sanjavier']['total'], 0)
        foco = response.context['foco_territorial']
        self.assertEqual(foco['nombre'], 'Capital')
        self.assertEqual([(t['nombre'], t['total']) for t in foco['temas']], [('Salud', 2)])
        self.assertContains(response, 'href="/localidad/capital/"')

    def test_enlaces_a_publicaciones_devuelven_las_mismas_noticias(self):
        response = self.get(departamento='capital')
        salud = next(f for f in response.context['categorias'] if f['nombre'] == 'Salud')
        self.assertEqual(salud['url_publicaciones'], f'/publicaciones/?localidad=capital&categoria={self.salud.pk}')
        listado = self.client.get(salud['url_publicaciones'])
        self.assertEqual({p.pk for p in listado.context['publicaciones']}, {self.a.pk, self.b.pk})
        self.assertIn('categoria=', salud['url'])
        self.assertIn('departamento=capital', salud['url'])

    def test_tono_de_publicaciones_y_comentarios_separados(self):
        vigente = Comentario.objects.create(publicacion=self.a, autor=self.lector, texto='Muy buena gestión', estado=Comentario.Estado.PUBLICADO)
        editado = Comentario.objects.create(publicacion=self.a, autor=self.lector, texto='Texto editado', estado=Comentario.Estado.PUBLICADO)
        pendiente = Comentario.objects.create(publicacion=self.a, autor=self.lector, texto='Pendiente', estado=Comentario.Estado.PENDIENTE)
        for comentario, texto, polaridad in ((vigente, vigente.texto, .7), (editado, 'Texto original', -.6), (pendiente, pendiente.texto, -.8)):
            SentimientoComentario.objects.create(
                comentario=comentario, polaridad=polaridad, confianza=.9, metodo='lexicon',
                modelo='lexicon_v1', texto_hash=calcular_texto_hash(texto),
            )
        response = self.get()
        tono = response.context['tono_comentarios']
        self.assertEqual({f['nombre']: f['total'] for f in tono['filas']}, {'Positivo': 1, 'Neutral': 0, 'Negativo': 0})
        self.assertEqual((tono['analizados'], tono['sin_analisis']), (1, 1))
        self.assertEqual(response.context['resumen']['analizadas'], 0)
        self.assertContains(response, 'Todavía no hay análisis de sentimiento registrado para estas publicaciones')
        self.assertContains(response, 'Tono de los comentarios de lectores')
        self.assertContains(response, 'no representan la opinión de la población')

    def test_secciones_del_panel_y_participacion_conservada(self):
        response = self.get()
        for ancla in ('id="agenda"', 'id="territorio"', 'id="temas"', 'id="tono"', 'id="participacion"'):
            self.assertContains(response, ancla)
        self.assertContains(response, 'Participación de lectores')
        evolucion = response.context['evolucion_temas']
        self.assertEqual({t['nombre'] for t in evolucion['temas']}, {'Salud', 'Educación'})
        self.assertEqual(response.context['temas_presentes'], 2)
