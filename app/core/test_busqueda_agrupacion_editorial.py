from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Categoria, GrupoEditorial, MiembroGrupoEditorial, Publicacion, Tema,
)


class BusquedaAgrupacionEditorialTests(TestCase):
    secuencia = 0

    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(
            username='editorial-search-tests', password='synthetic-only',
        )
        cls.categoria = Categoria.objects.create(nombre_categoria='Salud')

    def publicacion(self, titulo, *, fuente='Noticias del 6', contenido=None, fecha=None):
        type(self).secuencia += 1
        texto = contenido if contenido is not None else f'Contenido sintético distinto de {titulo}.'
        return Publicacion.objects.create(
            hash_origen=f'fase2b-{self.secuencia}', titulo=titulo, fuente=fuente,
            contenido=texto, url=f'https://example.invalid/fase2b/{self.secuencia}',
            fecha_publicacion=fecha or timezone.now(),
        )

    def agregar_categoria(self, publicacion):
        tema = Tema.objects.create(descripcion=f'Tema sintético {publicacion.pk}', id_categoria=self.categoria)
        tema.publicaciones.add(publicacion)

    def agrupar(self, representante, miembros, *, estado=GrupoEditorial.Estado.ACTIVO,
                decision=MiembroGrupoEditorial.Decision.APROBADO, vigente=True):
        ahora = timezone.now()
        activo = estado == GrupoEditorial.Estado.ACTIVO
        revocado = estado == GrupoEditorial.Estado.REVOCADO
        grupo = GrupoEditorial.objects.create(
            representante=representante, creado_por=self.actor, estado=estado,
            aprobado_por=self.actor if activo else None,
            aprobado=ahora if activo else None,
            motivo_aprobacion='aprobación sintética' if activo else '',
            revocado_por=self.actor if revocado else None,
            revocado=ahora if revocado else None,
            motivo_revocacion='revocación sintética' if revocado else '',
        )
        for publicacion in [representante, *miembros]:
            aprobada = decision == MiembroGrupoEditorial.Decision.APROBADO
            MiembroGrupoEditorial.objects.create(
                grupo=grupo, publicacion=publicacion,
                rol=(MiembroGrupoEditorial.Rol.REPRESENTANTE if publicacion.pk == representante.pk
                     else MiembroGrupoEditorial.Rol.MIEMBRO),
                decision=decision,
                revisado_por=self.actor if decision != MiembroGrupoEditorial.Decision.PENDIENTE else None,
                revisado=ahora if decision != MiembroGrupoEditorial.Decision.PENDIENTE else None,
                motivo_revision='decisión sintética' if decision != MiembroGrupoEditorial.Decision.PENDIENTE else '',
                vigente=bool(vigente and activo and aprobada),
                huella_publicacion='0' * 64,
            )
        return grupo

    def api(self, q='incendio', **params):
        return self.client.get(reverse('buscar_publicaciones'), {'q': q, **params})

    def test_sin_agrupaciones_conserva_publicaciones_individuales(self):
        a = self.publicacion('Incendio en Posadas uno')
        b = self.publicacion('Incendio en Posadas dos')
        respuesta = self.api()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['total'], 2)
        self.assertEqual({r['id_publicacion_api'] for r in respuesta.json()['resultados']}, {a.pk, b.pk})
        self.assertNotIn('versiones_originales', respuesta.json()['resultados'][0])

    def test_solo_grupo_activo_y_miembros_vigentes_aprobados_se_agrupan(self):
        representante = self.publicacion('Incendio regional representativo')
        miembro_activo = self.publicacion('Incendio regional versión activa')
        self.agrupar(representante, [miembro_activo])
        pendiente_rep = self.publicacion('Incendio regional pendiente')
        pendiente_otro = self.publicacion('Incendio regional pendiente versión')
        self.agrupar(pendiente_rep, [pendiente_otro], estado=GrupoEditorial.Estado.BORRADOR,
                     decision=MiembroGrupoEditorial.Decision.PENDIENTE, vigente=False)
        rechazado_rep = self.publicacion('Incendio regional rechazado')
        rechazado_otro = self.publicacion('Incendio regional rechazado versión')
        self.agrupar(rechazado_rep, [rechazado_otro], estado=GrupoEditorial.Estado.BORRADOR,
                     decision=MiembroGrupoEditorial.Decision.RECHAZADO, vigente=False)
        revocado_rep = self.publicacion('Incendio regional revocado')
        revocado_otro = self.publicacion('Incendio regional revocado versión')
        self.agrupar(revocado_rep, [revocado_otro], estado=GrupoEditorial.Estado.REVOCADO,
                     vigente=False)

        with CaptureQueriesContext(connection) as consultas:
            data = self.api().json()
        self.assertLessEqual(len(consultas), 4)
        ids = [fila['id_publicacion_api'] for fila in data['resultados']]
        self.assertEqual(data['total'], 7)
        self.assertEqual(ids.count(representante.pk), 1)
        self.assertNotIn(miembro_activo.pk, ids)
        for pk in (pendiente_rep.pk, pendiente_otro.pk, rechazado_rep.pk,
                   rechazado_otro.pk, revocado_rep.pk, revocado_otro.pk):
            self.assertIn(pk, ids)

    def test_coincidencia_en_miembro_conserva_relevancia_y_versiones_originales(self):
        antigua = timezone.now() - timedelta(days=30)
        reciente = timezone.now() - timedelta(days=1)
        representante = self.publicacion('Incendio regional principal', fecha=antigua,
                                         contenido='Resumen sintético del incendio regional.')
        miembro = self.publicacion('Incendio regional operativo', fecha=reciente,
                                   contenido='La búsqueda incendio encuentra esta evidencia exclusiva del miembro.')
        self.agrupar(representante, [miembro])
        otra = self.publicacion('Incendio regional noticia independiente', fecha=timezone.now())

        with CaptureQueriesContext(connection) as queries:
            respuesta = self.api('evidencia exclusiva')
        self.assertLessEqual(len(queries), 4)
        data = respuesta.json()
        self.assertEqual(data['total'], 1)
        fila = data['resultados'][0]
        self.assertEqual(fila['id_publicacion_api'], representante.pk)
        self.assertIn('evidencia exclusiva', fila['extracto'])
        self.assertEqual(fila['coincidencia']['id_publicacion_api'], miembro.pk)
        self.assertEqual({v['id_publicacion_api'] for v in fila['versiones_originales']},
                         {representante.pk, miembro.pk})
        self.assertNotEqual(fila['id_publicacion_api'], otra.pk)

        html = self.client.get(reverse('buscar_noticias'), {'q': 'evidencia exclusiva'})
        self.assertEqual(html.status_code, 200)
        self.assertContains(html, 'La coincidencia aparece en')
        self.assertContains(html, reverse('noticia', args=[miembro.pk]))
        self.assertContains(html, reverse('noticia', args=[representante.pk]))

    def test_distintos_medios_no_se_colapsan_y_total_pagina_es_por_grupo(self):
        fuentes = ('Noticias del 6', 'Norte Misionero')
        representantes = []
        for fuente in fuentes:
            representante = self.publicacion('Incendio regional compartido', fuente=fuente)
            miembro = self.publicacion('Incendio regional edición duplicada', fuente=fuente)
            self.agrupar(representante, [miembro])
            representantes.append(representante)
        for indice in range(19):
            representante = self.publicacion(f'Incendio regional adicional {indice}')
            miembro = self.publicacion(f'Incendio regional adicional versión {indice}')
            self.agrupar(representante, [miembro])
        data = self.api().json()
        self.assertEqual((data['total'], data['total_paginas'], len(data['resultados'])), (21, 2, 20))
        segunda = self.api(page=2).json()
        self.assertEqual((segunda['pagina'], len(segunda['resultados'])), (2, 1))
        self.assertEqual(len({r['id_publicacion_api'] for r in data['resultados'] + segunda['resultados']}), 21)
        todas = data['resultados'] + segunda['resultados']
        for publicacion in representantes:
            self.assertIn(publicacion.pk, {r['id_publicacion_api'] for r in todas})

    def test_filtros_fecha_fuente_categoria_y_paginacion_html_api(self):
        hoy = timezone.localdate()
        fecha_en_rango = timezone.now() - timedelta(hours=1)
        representante = self.publicacion('Incendio regional filtro representante', fecha=fecha_en_rango)
        miembro = self.publicacion('Incendio regional filtro coincidencia', fecha=fecha_en_rango)
        self.agrupar(representante, [miembro])
        self.agregar_categoria(miembro)
        otra_fuente = self.publicacion('Incendio regional filtro otra fuente', fuente='Norte Misionero', fecha=fecha_en_rango)
        self.agregar_categoria(otra_fuente)
        vieja = self.publicacion('Incendio regional filtro antiguo', fecha=timezone.now() - timedelta(days=5))
        self.agregar_categoria(vieja)

        params = {'desde': hoy.isoformat(), 'hasta': hoy.isoformat(),
                  'fuente': 'Noticias del 6', 'categoria': 'Salud'}
        data = self.api(**params).json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['resultados'][0]['id_publicacion_api'], representante.pk)
        html = self.client.get(reverse('buscar_noticias'), {'q': 'incendio', **params})
        self.assertEqual(html.status_code, 200)
        self.assertEqual(html.context['total'], 1)
        self.assertContains(html, 'name="desde"')
        self.assertContains(html, hoy.isoformat())
        next_url = html.context['siguiente']
        self.assertIsNone(next_url)

        for indice in range(20):
            adicional = self.publicacion(f'Incendio regional filtrado adicional {indice}', fecha=fecha_en_rango)
            self.agregar_categoria(adicional)
        pagina_uno = self.api(**params).json()
        self.assertEqual((pagina_uno['total'], len(pagina_uno['resultados'])), (21, 20))
        from urllib.parse import parse_qs, urlsplit
        query_siguiente = parse_qs(urlsplit(pagina_uno['siguiente']).query)
        self.assertEqual(query_siguiente['desde'], [hoy.isoformat()])
        self.assertEqual(query_siguiente['hasta'], [hoy.isoformat()])
        self.assertEqual(query_siguiente['fuente'], ['Noticias del 6'])
        self.assertEqual(query_siguiente['categoria'], ['Salud'])
        self.assertEqual(len(self.api(**params, page=2).json()['resultados']), 1)
        self.assertEqual(self.api(desde='2026-99-99').status_code, 400)
        self.assertEqual(self.api(desde='2026-11-20', hasta='2026-11-19').status_code, 400)

    def test_autocompletado_cuenta_grupos_unicos_y_conserva_fuentes_distintas(self):
        representante = self.publicacion('Incendio Misiones común representante')
        miembro = self.publicacion('Incendio Misiones común miembro')
        self.agrupar(representante, [miembro])
        otra_fuente = self.publicacion('Incendio Misiones común otro medio', fuente='Norte Misionero')
        respuesta = self.client.get(reverse('sugerencias_publicaciones'), {'q': 'incendio mi'})
        self.assertEqual(respuesta.status_code, 200)
        data = respuesta.json()
        sugerencia = next(f for f in data['terminos'] if f['texto'].lower() == 'misiones')
        self.assertEqual(sugerencia['texto'], 'Misiones')
        urls = [fila['url'] for fila in data['noticias']]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertIn(reverse('noticia', args=[representante.pk]), urls)
        self.assertNotIn(reverse('noticia', args=[miembro.pk]), urls)
        self.assertIn(reverse('noticia', args=[otra_fuente.pk]), urls)

    def test_filtro_autocompletado_y_redundancia_de_grupo(self):
        representante = self.publicacion('Incendio Misiones filtro representante')
        miembro = self.publicacion('Incendio Misiones filtro miembro')
        self.agrupar(representante, [miembro])
        otra = self.publicacion('Incendio Misiones otra fuente', fuente='Norte Misionero')
        data = self.client.get(reverse('sugerencias_publicaciones'), {
            'q': 'incendio mi', 'fuente': 'Noticias del 6',
        }).json()
        urls = [fila['url'] for fila in data['noticias']]
        self.assertEqual(urls.count(reverse('noticia', args=[representante.pk])), 1)
        self.assertNotIn(reverse('noticia', args=[miembro.pk]), urls)
        self.assertNotIn(reverse('noticia', args=[otra.pk]), urls)
