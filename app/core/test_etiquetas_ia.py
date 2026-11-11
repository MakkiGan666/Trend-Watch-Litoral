"""Etiquetas temáticas con IA e inteligencia temática.

Gemini y Ollama están simulados: ninguna prueba usa red ni consume API.
"""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from core.models import (
    Categoria, EjecucionIA, Etiqueta, Publicacion, PublicacionEtiqueta, PublicacionTema, Sentimiento, Tema,
)
from core.services import temas
from core.services.etiquetas_ia import (
    clave_variante, etiquetar_publicacion, extraer_candidatas, normalizar_nombre, validar_etiquetas,
)
from core.test_motor_ia import BaseMotorIA, error_gemini_401

User = get_user_model()
IA = PublicacionEtiqueta.Origen.IA
LEXICO = PublicacionEtiqueta.Origen.LEXICO

TITULO = 'Misiones fortalece la atención sanitaria en hospitales del interior'
CONTENIDO = ('El Ministerio de Salud Pública anunció una inversión provincial para mejorar la infraestructura '
             'sanitaria de los hospitales del interior. La atención médica incluirá nuevas guardias y '
             'políticas públicas de prevención en Oberá y Eldorado.')


def respuesta(*etiquetas):
    return SimpleNamespace(text=json.dumps({'etiquetas': list(etiquetas)}, ensure_ascii=False))


def crear_publicacion(hash_origen, titulo=TITULO, contenido=CONTENIDO, **datos):
    return Publicacion.objects.create(hash_origen=hash_origen, titulo=titulo, contenido=contenido, **datos)


class ValidacionTests(TestCase):
    def test_normalizacion_de_nombres(self):
        self.assertEqual(normalizar_nombre('  #salud   pública. '), 'Salud pública')
        self.assertEqual(normalizar_nombre('"INFRAESTRUCTURA SANITARIA"'), 'Infraestructura sanitaria')
        self.assertEqual(normalizar_nombre('IPS'), 'IPS')
        self.assertEqual(normalizar_nombre(None), '')
        self.assertEqual(clave_variante('hospitales'), clave_variante('hospital'))

    def test_filtra_genericas_duplicadas_sin_respaldo_y_categoria(self):
        validacion = validar_etiquetas(
            ['Hospitales', 'hospital', 'Salud pública', 'Noticias', 'Misiones', 'Salud', 'Turismo rural',
             'Infraestructura sanitaria', '2026', 'x', 'Atención médica', 'Una etiqueta con demasiadas palabras juntas'],
            TITULO, CONTENIDO, categoria='Salud')
        aceptadas = [nombre for _, nombre in validacion.aceptadas]
        self.assertEqual(aceptadas, ['Hospitales', 'Salud pública', 'Infraestructura sanitaria', 'Atención médica'])
        motivos = {d['etiqueta']: d['motivo'] for d in validacion.descartadas}
        self.assertEqual(motivos['hospital'], 'duplicada')
        self.assertEqual(motivos['Noticias'], 'generica')
        self.assertEqual(motivos['Misiones'], 'generica')
        self.assertEqual(motivos['Salud'], 'repite_categoria')
        self.assertEqual(motivos['Turismo rural'], 'sin_respaldo_en_texto')
        self.assertEqual(motivos['2026'], 'solo_numeros')
        self.assertEqual(motivos['x'], 'largo_invalido')
        self.assertEqual(motivos['Una etiqueta con demasiadas palabras juntas'], 'demasiadas_palabras')

    def test_no_acepta_lugares_que_no_estan_en_el_texto(self):
        validacion = validar_etiquetas(['Hospital de Posadas', 'Hospitales de Oberá'], TITULO, CONTENIDO)
        self.assertEqual([n for _, n in validacion.aceptadas], ['Hospitales de Oberá'])

    def test_formas_de_respuesta(self):
        self.assertEqual(extraer_candidatas('{"etiquetas": ["A b", {"nombre": "C d"}, 3]}'), ['A b', 'C d'])
        self.assertEqual(extraer_candidatas('["Uno", "Dos"]'), ['Uno', 'Dos'])
        for invalida in ('', 'no es json', '{"otra": []}', '{"etiquetas": []}', '{"etiquetas": [1, 2]}', 'x' * 30000):
            with self.subTest(invalida=invalida[:20]), self.assertRaises(ValueError):
                extraer_candidatas(invalida)


class EtiquetadoTests(BaseMotorIA):
    def setUp(self):
        super().setUp()
        self.configurar('gemini', respaldo=False)
        categoria = Categoria.objects.create(nombre_categoria='Salud')
        self.pub = crear_publicacion('ia-1')
        self.tema = Tema.objects.create(id_categoria=categoria, descripcion='Salud')
        PublicacionTema.objects.create(id_publicacion_api=self.pub, id_temas=self.tema)
        self.generar = self.gemini.client.models.generate_content

    def ia(self, publicacion=None):
        return list(PublicacionEtiqueta.objects.filter(publicacion=publicacion or self.pub, origen=IA)
                    .select_related('etiqueta').order_by('posicion'))

    def test_genera_multiples_etiquetas_con_procedencia(self):
        self.generar.return_value = respuesta('Hospitales', 'Salud pública', 'Infraestructura sanitaria',
                                              'Atención médica', 'Políticas públicas', 'Inversión provincial',
                                              'Interior de Misiones')
        resultado = etiquetar_publicacion(self.pub)
        self.assertEqual(resultado.estado, 'etiquetada')
        relaciones = self.ia()
        # El catálogo es compartido: se reutiliza la etiqueta existente aunque la haya creado la extracción léxica.
        self.assertEqual([r.etiqueta.slug for r in relaciones],
                         ['hospitales', 'salud-publica', 'infraestructura-sanitaria', 'atencion-medica',
                          'politicas-publicas', 'inversion-provincial', 'interior-de-misiones'])
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual((ejecucion.tarea, ejecucion.estado, ejecucion.publicacion_id),
                         ('etiquetado_tematico', 'exitosa', self.pub.pk))
        for relacion in relaciones:
            self.assertEqual((relacion.ejecucion_id, relacion.modelo_ia), (ejecucion.pk, 'gemini:gemini-test'))
            self.assertIsNotNone(relacion.fecha_asignacion)
        self.assertTrue(ejecucion.resultado['guardado'])
        self.assertEqual(len(ejecucion.resultado['vigentes']), 7)
        # La categoría principal sigue intacta e independiente de las etiquetas.
        self.assertEqual(list(PublicacionTema.objects.filter(id_publicacion_api=self.pub).values_list('id_temas', flat=True)), [self.tema.pk])
        self.assertEqual(self.pub.categoria_principal, 'Salud')
        # El prompt menciona la categoría para no repetirla y nunca incluye credenciales.
        sistema = self.generar.call_args.kwargs['config']
        self.assertIsNotNone(sistema)

    def test_ollama_tambien_etiqueta_e_identifica_el_modelo(self):
        self.configurar('ollama')
        self.ollama.contenido = json.dumps({'etiquetas': ['Hospitales', 'Atención médica']})
        resultado = etiquetar_publicacion(self.pub)
        self.assertEqual((resultado.estado, resultado.proveedor), ('etiquetada', 'ollama'))
        self.assertEqual({r.modelo_ia for r in self.ia()}, {'ollama:llama3.1:latest'})

    def test_reutiliza_el_catalogo_y_variantes_sin_duplicar(self):
        hospitales, _ = Etiqueta.objects.get_or_create(slug='hospitales', defaults={'nombre': 'Hospitales'})
        guardia = Etiqueta.objects.create(nombre='Guardia', slug='guardia')
        self.generar.return_value = respuesta('Hospital', 'HOSPITALES', 'Guardias', 'Atención médica')
        etiquetar_publicacion(self.pub)
        self.assertEqual([r.etiqueta_id for r in self.ia()][:2], [hospitales.pk, guardia.pk])
        self.assertEqual(len(self.ia()), 3)
        self.assertFalse(Etiqueta.objects.filter(slug__in=['hospital', 'guardias']).exists())

    def test_misma_etiqueta_lexica_e_ia_conviven_y_se_muestra_una_vez(self):
        lexica = PublicacionEtiqueta.objects.get(publicacion=self.pub, origen=LEXICO, posicion=1)
        self.generar.return_value = respuesta(lexica.etiqueta.nombre, 'Atención médica')
        etiquetar_publicacion(self.pub)
        self.assertTrue(PublicacionEtiqueta.objects.filter(publicacion=self.pub, etiqueta=lexica.etiqueta, origen=IA).exists())
        pub = Publicacion.objects.prefetch_related('etiquetas__etiqueta').get(pk=self.pub.pk)
        visibles = [r.etiqueta_id for r in pub.etiquetas_visibles]
        self.assertEqual(len(visibles), len(set(visibles)))
        self.assertEqual(pub.etiquetas_visibles[0].origen, IA)

    def test_editar_el_texto_no_borra_las_etiquetas_de_ia(self):
        self.generar.return_value = respuesta('Hospitales', 'Atención médica')
        etiquetar_publicacion(self.pub)
        self.pub.contenido = CONTENIDO + ' Se sumarán ambulancias.'
        self.pub.save()
        self.assertEqual(len(self.ia()), 2)
        self.assertTrue(PublicacionEtiqueta.objects.filter(publicacion=self.pub, origen=LEXICO).exists())

    def test_reetiquetar_reemplaza_vigentes_conserva_fechas_y_el_historial(self):
        self.generar.return_value = respuesta('Hospitales', 'Atención médica')
        etiquetar_publicacion(self.pub)
        fecha = self.ia()[0].fecha_asignacion
        self.generar.return_value = respuesta('Hospitales', 'Salud pública')
        etiquetar_publicacion(self.pub)
        relaciones = self.ia()
        self.assertEqual([r.etiqueta.slug for r in relaciones], ['hospitales', 'salud-publica'])
        self.assertEqual(relaciones[0].fecha_asignacion, fecha)
        primera, segunda = EjecucionIA.objects.order_by('pk')
        self.assertIn('Atención médica', primera.respuesta_original)
        self.assertEqual(relaciones[1].ejecucion_id, segunda.pk)

    def test_respuestas_invalidas_no_borran_las_vigentes(self):
        self.generar.return_value = respuesta('Hospitales', 'Atención médica')
        etiquetar_publicacion(self.pub)
        for texto, codigo in (('no es json', 'json_invalido'), ('{"otra": 1}', 'sin_lista_de_etiquetas'),
                              (json.dumps({'etiquetas': ['Noticias', 'Turismo rural']}), 'sin_etiquetas_validas')):
            with self.subTest(codigo=codigo):
                self.generar.return_value = SimpleNamespace(text=texto)
                resultado = etiquetar_publicacion(self.pub)
                self.assertEqual((resultado.estado, resultado.codigo), ('invalida', codigo))
                ejecucion = EjecucionIA.objects.latest('pk')
                self.assertEqual((ejecucion.estado, ejecucion.codigo_error), ('invalida', codigo))
                self.assertEqual(ejecucion.respuesta_original, texto)
                self.assertEqual(len(self.ia()), 2)
        descartadas = EjecucionIA.objects.latest('pk').resultado['descartadas']
        self.assertEqual({d['motivo'] for d in descartadas}, {'generica', 'sin_respaldo_en_texto'})

    def test_error_del_proveedor_no_borra_ni_propaga(self):
        self.generar.return_value = respuesta('Hospitales')
        etiquetar_publicacion(self.pub)
        self.generar.side_effect = error_gemini_401()
        resultado = etiquetar_publicacion(self.pub)
        self.assertEqual((resultado.estado, resultado.codigo), ('fallida', 'autenticacion'))
        self.assertEqual(EjecucionIA.objects.latest('pk').estado, 'fallida')
        self.assertEqual(len(self.ia()), 1)

    def test_fallo_del_historial_no_impide_etiquetar(self):
        self.generar.return_value = respuesta('Hospitales', 'Atención médica')
        with patch.object(EjecucionIA.objects, 'create', side_effect=RuntimeError('sin tabla')), \
                self.assertLogs('core.services.ia.seguimiento', 'WARNING'):
            resultado = etiquetar_publicacion(self.pub)
        self.assertEqual(resultado.estado, 'etiquetada')
        self.assertEqual([(r.ejecucion_id, r.modelo_ia) for r in self.ia()],
                         [(None, 'gemini:gemini-test')] * 2)


class ComandoEtiquetarTests(BaseMotorIA):
    def setUp(self):
        super().setUp()
        self.configurar('gemini', respaldo=False)
        self.pubs = [crear_publicacion(f'cmd-{i}') for i in range(3)]
        self.gemini.client.models.generate_content.return_value = respuesta('Hospitales', 'Atención médica')

    def ejecutar(self, *args):
        salida = StringIO()
        with patch('core.management.commands.etiquetar_con_ia.time.sleep'):
            call_command('etiquetar_con_ia', *args, stdout=salida)
        return salida.getvalue()

    def test_vista_previa_no_llama_al_modelo(self):
        salida = self.ejecutar('--limite', '2')
        self.assertIn('Vista previa', salida)
        self.assertEqual(self.llamadas_gemini, 0)
        self.assertFalse(EjecucionIA.objects.exists())

    def test_confirmar_etiqueta_solo_las_elegidas_y_omite_las_ya_etiquetadas(self):
        self.ejecutar('--ids', str(self.pubs[0].pk), '--confirmar')
        self.assertEqual(self.llamadas_gemini, 1)
        salida = self.ejecutar('--ids', str(self.pubs[0].pk), str(self.pubs[1].pk), '--confirmar')
        self.assertEqual(self.llamadas_gemini, 2)
        self.assertIn('Etiquetadas: 1', salida)
        self.assertFalse(PublicacionEtiqueta.objects.filter(publicacion=self.pubs[2], origen=IA).exists())

    def test_limites_de_seguridad(self):
        for args in ([], ['--limite', '0'], ['--limite', '26'], ['--ids', '1', '--limite', '2'],
                     ['--ids', '999999'], ['--limite', '2', '--pausa', '-1']):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.ejecutar(*args)
        self.assertEqual(self.llamadas_gemini, 0)


class ConsultasTematicasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoy = datetime(2026, 11, 6, 15, tzinfo=dt_timezone.utc)

        def pub(clave, dias, departamento='', etiquetas=(), polaridad=None):
            p = crear_publicacion(f'q-{clave}', titulo=f'Noticia {clave}', contenido='Texto breve',
                                  fecha_publicacion=cls.hoy - timedelta(days=dias), departamento=departamento)
            for posicion, nombre in enumerate(etiquetas, start=1):
                etiqueta, _ = Etiqueta.objects.get_or_create(slug=slugify(nombre), defaults={'nombre': nombre})
                PublicacionEtiqueta.objects.create(publicacion=p, etiqueta=etiqueta, posicion=posicion, origen=IA)
            if polaridad is not None:
                Sentimiento.objects.create(id_publicacion_api=p, polaridad=polaridad, confianza=0.9)
            return p

        cls.a = pub('a', 1, 'obera', ['Dengue', 'Salud pública'], -0.6)
        cls.b = pub('b', 2, 'obera', ['Dengue', 'Salud pública', 'Hospitales'], -0.4)
        cls.c = pub('c', 3, 'capital', ['Dengue', 'Hospitales'], 0.3)
        cls.d = pub('d', 4, '', ['Dengue', 'Turismo rural'], -0.2)
        cls.e = pub('e', 40, 'capital', ['Turismo rural'])
        cls.f = pub('f', 41, 'capital', ['Turismo rural', 'Dengue'])
        cls.g = pub('g', 5, 'departamento-inventado', ['Dengue'])

    def test_filtro_por_varias_etiquetas_exige_todas(self):
        base = Publicacion.objects.all()
        self.assertEqual(set(temas.filtrar_por_etiquetas(base, ['dengue'])), {self.a, self.b, self.c, self.d, self.f, self.g})
        self.assertEqual(set(temas.filtrar_por_etiquetas(base, ['dengue', 'hospitales'])), {self.b, self.c})
        self.assertEqual(list(temas.filtrar_por_etiquetas(base, ['dengue', 'hospitales', 'salud-publica'])), [self.b])

    def test_frecuencia_y_coocurrencia(self):
        frecuentes = temas.frecuencia_etiquetas(Publicacion.objects.all(), limite=2)
        self.assertEqual(frecuentes[0], {'slug': 'dengue', 'nombre': 'Dengue', 'total': 6})
        co = temas.etiquetas_coocurrentes(Publicacion.objects.all(), ['dengue'])
        self.assertEqual(co[0]['slug'], 'hospitales')
        self.assertNotIn('dengue', [f['slug'] for f in co])

    def test_etiquetas_en_alza_compara_periodos_iguales(self):
        fin = self.hoy.date()
        alza = temas.etiquetas_en_alza(Publicacion.objects.all(), fin - timedelta(days=29), fin, minimo=2)
        self.assertEqual(alza['anterior'], (fin - timedelta(days=59), fin - timedelta(days=30)))
        por_slug = {e['slug']: e for e in alza['etiquetas']}
        self.assertEqual((por_slug['dengue']['actual'], por_slug['dengue']['anterior'], por_slug['dengue']['variacion']), (5, 1, 400))
        self.assertIsNone(por_slug['hospitales']['variacion'])  # sin base de comparación: no se inventa porcentaje
        self.assertNotIn('turismo-rural', por_slug)  # 1 actual frente a 2 anteriores: no crece

    def test_por_departamento_ignora_sin_identificar_y_valores_fuera_del_catalogo(self):
        grupos = {g['slug']: g for g in temas.etiquetas_por_departamento(Publicacion.objects.all())}
        self.assertEqual(set(grupos), {'obera', 'capital'})
        self.assertEqual([e['slug'] for e in grupos['obera']['etiquetas']], ['dengue', 'salud-publica'])
        dengue = {d['slug']: d['total'] for d in temas.departamentos_de_etiqueta(Publicacion.objects.all(), 'dengue')}
        self.assertEqual(dengue, {'obera': 2, 'capital': 2})  # sin la noticia sin departamento ni la inventada

    def test_sentimiento_negativo_por_etiqueta(self):
        filas = {f['slug']: f for f in temas.sentimiento_por_etiqueta(Publicacion.objects.all(), minimo=2)}
        self.assertEqual((filas['dengue']['negativas'], filas['dengue']['total']), (3, 4))
        self.assertEqual(filas['salud-publica']['proporcion'], 100)

    def test_evolucion_semanal(self):
        semanas = temas.evolucion_etiqueta(Publicacion.objects.all(), 'dengue', self.hoy.date(), semanas=8)
        self.assertEqual(len(semanas), 8)
        self.assertEqual(semanas[-1]['total'], 5)
        self.assertEqual(sum(s['total'] for s in semanas), 6)

    def test_relacionadas_por_coincidencia_tematica(self):
        a = Publicacion.objects.prefetch_related('etiquetas').get(pk=self.a.pk)
        relacionadas = temas.publicaciones_relacionadas(a)
        self.assertEqual(relacionadas[0][0], self.b)
        self.assertIn('Salud pública', relacionadas[0][1])
        self.assertNotIn(self.a, [r for r, _ in relacionadas])

    def test_origen_preferido(self):
        self.assertEqual(temas.origen_preferido(), IA)


class InterfazTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('configurar_roles', stdout=StringIO())
        cls.admin = User.objects.create_user('admin-temas', is_staff=True)
        cls.admin.groups.add(Group.objects.get(name='Administrador'))
        cls.pub = crear_publicacion('ui-1', departamento='obera', fecha_publicacion=datetime(2026, 11, 5, 12, tzinfo=dt_timezone.utc))
        cls.otra = crear_publicacion('ui-2', titulo='Más guardias en hospitales del interior',
                                     fecha_publicacion=datetime(2026, 11, 4, 12, tzinfo=dt_timezone.utc))
        for p in (cls.pub, cls.otra):
            for posicion, nombre in enumerate(['Hospitales', 'Atención médica'], start=1):
                etiqueta, _ = Etiqueta.objects.get_or_create(slug=slugify(nombre), defaults={'nombre': nombre})
                PublicacionEtiqueta.objects.create(publicacion=p, etiqueta=etiqueta, posicion=posicion, origen=IA,
                                                   modelo_ia='gemini:gemini-test')

    def test_detalle_muestra_temas_ia_departamento_y_relacionadas(self):
        respuesta = self.client.get(reverse('noticia', args=[self.pub.pk]))
        self.assertContains(respuesta, 'Temas identificados con IA')
        self.assertContains(respuesta, 'news-keywords__ia')
        self.assertContains(respuesta, 'Departamento Oberá')
        self.assertContains(respuesta, 'Noticias relacionadas por tema')
        self.assertContains(respuesta, reverse('noticia', args=[self.otra.pk]))

    def test_pagina_de_etiqueta_combina_filtros(self):
        url = reverse('publicaciones_etiqueta', args=['hospitales'])
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.context['pagina'].paginator.count, 2)
        self.assertContains(respuesta, '?y=atencion-medica')
        self.assertContains(respuesta, 'Oberá')
        combinada = self.client.get(url, {'y': 'atencion-medica'})
        self.assertEqual(combinada.context['pagina'].paginator.count, 2)
        self.assertContains(combinada, 'Quitar la etiqueta Atención médica')
        self.assertEqual(self.client.get(url, {'y': 'inexistente'}).context['pagina'].paginator.count, 2)

    def test_dashboard_muestra_bloque_tematico_con_su_origen(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Etiquetas temáticas (IA)')
        self.assertContains(respuesta, 'Etiquetas más frecuentes')
        self.assertEqual(respuesta.context['tematica']['frecuentes'][0]['total'], 2)
