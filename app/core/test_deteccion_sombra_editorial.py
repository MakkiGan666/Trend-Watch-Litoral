from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from time import perf_counter
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from core.models import (
    CandidatoDuplicadoEditorial, GrupoEditorial, MiembroGrupoEditorial, Publicacion,
)
from core.services.deteccion_sombra_editorial import (
    VERSION_DETECTOR, registrar_candidatos_sombra,
)
from core.services.duplicados_editoriales import detectar_candidatos


CUERPO = 'La municipalidad anunció obras y servicios para distintos barrios de Misiones. ' * 10


class ClasificacionSombraTests(SimpleTestCase):
    def fila(self, pk, **cambios):
        fila = {
            'pk': pk, 'fuente': 'El Territorio', 'titulo': 'Municipio anunció obras para los barrios',
            'url': f'https://medio.test/noticia/{pk}', 'fecha_publicacion': timezone.now().date(),
            'contenido': '', 'contenido_completo': False,
        }
        fila.update(cambios)
        return fila

    def test_noticias_de_medios_distintos_son_cobertura_no_candidato(self):
        a = self.fila(1, contenido=CUERPO, contenido_completo=True)
        b = self.fila(2, fuente='Norte Misionero', contenido=CUERPO, contenido_completo=True)
        self.assertEqual(detectar_candidatos([a, b])[0]['estado'], 'COBERTURA_MULTIMEDIO')

    def test_cuerpos_distintos_con_titulo_parecido_son_falso_positivo(self):
        a = self.fila(1, contenido=CUERPO, contenido_completo=True)
        b = self.fila(2, titulo='Municipio anunció obras para la zona',
                      contenido='El Concejo debatió tasas, presupuesto y ordenanzas locales. ' * 10,
                      contenido_completo=True)
        self.assertEqual(detectar_candidatos([a, b])[0]['estado'], 'TITULO_COINCIDENTE_DISTINTO_CONTENIDO')

    def test_referencia_estructural_79_grupos_y_81_pares_directos(self):
        registros = []
        pk = 1
        for grupo in range(79):
            cantidad = 3 if grupo == 0 else 2
            for miembro in range(cantidad):
                registros.append({
                    'pk': pk, 'fuente': 'El Territorio',
                    'titulo': f'Noticia referencia sintética grupo {grupo:03d}',
                    'url': f'https://medio.test/referencia/{grupo}',
                    'fecha_publicacion': timezone.now().date() - timedelta(days=grupo * 3),
                    'contenido': '', 'contenido_completo': False,
                })
                pk += 1
        inicio = perf_counter()
        candidatos = detectar_candidatos(registros)
        duracion = perf_counter() - inicio
        self.assertEqual(len(candidatos), 81)
        self.assertTrue(all(item['estado'] == 'DUPLICADO_CONFIRMADO' for item in candidatos))
        self.assertLess(duracion, 5.0)


class ColaSombraTests(TestCase):
    def crear_publicacion(self, numero, *, fuente='El Territorio', titulo='Municipio anunció obras para los barrios',
                          url=None, cuerpo=CUERPO, completa=True, fecha=None):
        return Publicacion.objects.create(
            hash_origen=f'fase3a-{numero}', fuente=fuente, titulo=titulo,
            url=url or f'https://medio.test/noticia/{numero}',
            contenido=cuerpo if completa else '', contenido_completo=completa,
            fecha_publicacion=fecha or timezone.now() - timedelta(hours=1),
        )

    def candidato(self, a, b):
        evaluacion, = detectar_candidatos([
            {'pk': a.pk, 'fuente': a.fuente, 'titulo': a.titulo, 'url': a.url,
             'fecha_publicacion': a.fecha_publicacion, 'contenido': a.contenido,
             'contenido_completo': a.contenido_completo},
            {'pk': b.pk, 'fuente': b.fuente, 'titulo': b.titulo, 'url': b.url,
             'fecha_publicacion': b.fecha_publicacion, 'contenido': b.contenido,
             'contenido_completo': b.contenido_completo},
        ])
        return evaluacion

    def test_cola_guarda_evidencia_hashes_y_no_cuerpo(self):
        a = self.crear_publicacion(1, url='https://medio.test/canonica')
        b = self.crear_publicacion(2, url='https://www.medio.test/canonica?utm_source=rss')
        resultado = registrar_candidatos_sombra([self.candidato(a, b)])
        candidato = CandidatoDuplicadoEditorial.objects.get()
        self.assertEqual(candidato.clasificacion, CandidatoDuplicadoEditorial.Clasificacion.EXACTO)
        self.assertEqual(candidato.version_detector, VERSION_DETECTOR)
        self.assertEqual(len(candidato.clave_idempotencia), 64)
        self.assertEqual(len(candidato.huella_a), 64)
        self.assertEqual(len(candidato.huella_b), 64)
        self.assertIn('similitud_titulo', candidato.evidencia)
        self.assertNotIn('contenido', candidato.evidencia)
        self.assertEqual(resultado['candidatos_registrados_o_actualizados'], 1)

    def test_idempotencia_incrementa_observaciones_sin_crear_segunda_fila(self):
        a = self.crear_publicacion(3, url='https://medio.test/misma')
        b = self.crear_publicacion(4, url='https://www.medio.test/misma')
        par = self.candidato(a, b)
        registrar_candidatos_sombra([par])
        primera = CandidatoDuplicadoEditorial.objects.get()
        registrar_candidatos_sombra([par])
        segunda = CandidatoDuplicadoEditorial.objects.get()
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 1)
        self.assertEqual(segunda.veces_detectado, 2)
        self.assertEqual(segunda.primera_detectada, primera.primera_detectada)
        registrar_candidatos_sombra([par], version_detector='editorial-v2')
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 2)
        version_nueva = CandidatoDuplicadoEditorial.objects.get(version_detector='editorial-v2')
        self.assertEqual(version_nueva.evidencia['version_detector'], 'editorial-v2')

    def test_cola_distingue_ambiguedad_y_no_persiste_falsos_positivos(self):
        incompleta_a = self.crear_publicacion(5, completa=False, cuerpo='')
        incompleta_b = self.crear_publicacion(6, completa=False, cuerpo='')
        registrar_candidatos_sombra([self.candidato(incompleta_a, incompleta_b)])
        guardada = CandidatoDuplicadoEditorial.objects.get()
        self.assertEqual(guardada.clasificacion, CandidatoDuplicadoEditorial.Clasificacion.AMBIGUO)

        falsa_a = self.crear_publicacion(7, titulo='Municipio anunció obras para los barrios',
                                         cuerpo='Los vecinos participaron en un torneo deportivo local. ' * 10)
        falsa_b = self.crear_publicacion(8, titulo='Municipio anunció obras para la zona',
                                         cuerpo='El Concejo debatió tasas y presupuesto anual. ' * 10)
        resultado = registrar_candidatos_sombra([self.candidato(falsa_a, falsa_b)])
        self.assertEqual(resultado['omitidos']['no_candidato'], 1)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 1)

    def test_evidencia_de_cuerpo_sustancial_se_clasifica_probable(self):
        vocabulario = (
            'municipio anunció obras servicios vecinos comunidad barrio provincia reuniones '
            'concejo gobierno presupuesto autoridades desarrollo caminos salud escuela hospital '
            'infraestructura rural agua energía transporte familias cooperativas agricultores docentes '
            'estudiantes comercio industria turismo ambiente jornadas actividades proyectos gestión medidas '
            'inversión políticas equipos funcionarios trabajadores recursos programas territorio región '
            'seguridad cultura deportes producción crecimiento'.split()
        )
        tokens_a = vocabulario * 4
        tokens_b = tokens_a.copy()
        for indice in (0, 2, 4, 6, 8, 10, 12, 14):
            tokens_b[indice] = f'variante{chr(97 + indice)}'
        a = self.crear_publicacion(16, titulo='Municipio anunció obras para los barrios',
                                  cuerpo=' '.join(tokens_a))
        b = self.crear_publicacion(17, titulo='Municipio anunció obras para los barrios',
                                  url='https://medio.test/probable-17', cuerpo=' '.join(tokens_b))
        par = self.candidato(a, b)
        self.assertEqual(par['estado'], 'DUPLICADO_PROBABLE', par)
        resultado = registrar_candidatos_sombra([par])
        self.assertEqual(resultado['candidatos_registrados_o_actualizados'], 1, resultado)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.get().clasificacion,
                         CandidatoDuplicadoEditorial.Clasificacion.PROBABLE)

    def test_cuerpo_confirmado_con_urls_distintas_no_se_etiqueta_exacta(self):
        a = self.crear_publicacion(18, cuerpo=CUERPO)
        b = self.crear_publicacion(19, url='https://medio.test/otra-version', cuerpo=CUERPO)
        registrar_candidatos_sombra([self.candidato(a, b)])
        self.assertEqual(CandidatoDuplicadoEditorial.objects.get().clasificacion,
                         CandidatoDuplicadoEditorial.Clasificacion.PROBABLE)

    def test_medios_distintos_se_excluyen_de_la_cola(self):
        a = self.crear_publicacion(9)
        b = self.crear_publicacion(10, fuente='Norte Misionero')
        resultado = registrar_candidatos_sombra([self.candidato(a, b)])
        self.assertEqual(resultado['omitidos']['fuente_distinta'], 1)
        self.assertFalse(CandidatoDuplicadoEditorial.objects.exists())

    def test_no_construye_agrupacion_transitiva(self):
        url = 'https://medio.test/misma-noticia'
        a = self.crear_publicacion(11, url=url)
        b = self.crear_publicacion(12, url=url)
        c = self.crear_publicacion(13, url=url)
        pares = [self.candidato(a, b), self.candidato(b, c)]
        registrar_candidatos_sombra(pares)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 2)
        self.assertFalse(CandidatoDuplicadoEditorial.objects.filter(publicacion_a=a, publicacion_b=c).exists())
        self.assertFalse(GrupoEditorial.objects.exists())
        self.assertFalse(MiembroGrupoEditorial.objects.exists())

    def test_omite_publicaciones_que_ya_pertenecen_a_grupo_vigente(self):
        a = self.crear_publicacion(14, url='https://medio.test/activa')
        b = self.crear_publicacion(15, url='https://www.medio.test/activa')
        usuario = get_user_model().objects.create_user(username='fase3a-editor')
        grupo = GrupoEditorial.objects.create(
            representante=a, estado=GrupoEditorial.Estado.ACTIVO, creado_por=usuario,
            aprobado_por=usuario, aprobado=timezone.now(), motivo_aprobacion='Grupo de prueba aislado',
        )
        for publicacion, rol in ((a, MiembroGrupoEditorial.Rol.REPRESENTANTE),
                                 (b, MiembroGrupoEditorial.Rol.MIEMBRO)):
            MiembroGrupoEditorial.objects.create(
                grupo=grupo, publicacion=publicacion, rol=rol,
                decision=MiembroGrupoEditorial.Decision.APROBADO,
                huella_publicacion='a' * 64, revisado_por=usuario, revisado=timezone.now(),
                motivo_revision='Aprobación fixture', vigente=True,
            )
        resultado = registrar_candidatos_sombra([self.candidato(a, b)])
        self.assertEqual(resultado['omitidos']['grupo_vigente'], 1)
        self.assertFalse(CandidatoDuplicadoEditorial.objects.exists())
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.ACTIVO)

    def test_revalida_identificadores_y_rechaza_pares_invalidos(self):
        with self.assertRaisesMessage(ValueError, 'dos IDs positivos y distintos'):
            registrar_candidatos_sombra([{'publicaciones': [{'pk': 1}, {'pk': 1}]}])
        with self.assertRaisesMessage(ValueError, 'publicaciones inexistentes'):
            registrar_candidatos_sombra([{'publicaciones': [{'pk': 101}, {'pk': 102}]}])


class ComandoSombraTests(TransactionTestCase):
    def test_dry_run_no_escribe_y_registro_es_explicito(self):
        a = Publicacion.objects.create(hash_origen='fase3a-cmd-1', titulo='La noticia larga de prueba sobre la ciudad',
                                       fuente='El Territorio', url='https://medio.test/1', contenido_completo=False)
        b = Publicacion.objects.create(hash_origen='fase3a-cmd-2', titulo='La noticia larga de prueba sobre la ciudad',
                                       fuente='El Territorio', url='https://medio.test/2', contenido_completo=False)
        with self.assertRaises(CommandError):
            call_command('auditar_duplicados_editoriales')
        salida = StringIO()
        call_command('auditar_duplicados_editoriales', dry_run=True, stdout=salida)
        self.assertFalse(CandidatoDuplicadoEditorial.objects.exists())
        call_command('auditar_duplicados_editoriales', registrar_sombra=True, stdout=StringIO())
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 1)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.titulo, b.titulo), (
            'La noticia larga de prueba sobre la ciudad', 'La noticia larga de prueba sobre la ciudad',
        ))
        self.assertFalse(GrupoEditorial.objects.exists())


class AdminColaSombraTests(SimpleTestCase):
    def test_cola_es_consultable_por_revisor_y_no_admite_escritura_admin(self):
        model_admin = admin.site._registry[CandidatoDuplicadoEditorial]
        request = SimpleNamespace(
            user=SimpleNamespace(has_perm=lambda permiso: permiso == 'core.revisar_candidatos_editoriales'),
        )
        self.assertTrue(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        request.user = SimpleNamespace(has_perm=lambda permiso: False)
        self.assertFalse(model_admin.has_view_permission(request))


@skipUnless(connection.vendor == 'postgresql', 'La concurrencia de la cola se valida en PostgreSQL aislado.')
class ConcurrenciaColaSombraTests(TransactionTestCase):
    reset_sequences = True

    def test_ejecuciones_concurrentes_comparten_clave_idempotente(self):
        a = Publicacion.objects.create(hash_origen='fase3a-conc-1', fuente='El Territorio',
                                       titulo='Municipio anunció obras para los barrios',
                                       url='https://medio.test/concurrente', contenido_completo=False)
        b = Publicacion.objects.create(hash_origen='fase3a-conc-2', fuente='El Territorio',
                                       titulo='Municipio anunció obras para los barrios',
                                       url='https://www.medio.test/concurrente', contenido_completo=False)
        candidato = {
            'publicaciones': [
                {'pk': a.pk}, {'pk': b.pk},
            ],
        }
        barrera = Barrier(2)

        def ejecutar():
            close_old_connections()
            barrera.wait(timeout=10)
            resultado = registrar_candidatos_sombra([candidato])
            close_old_connections()
            return resultado

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: ejecutar(), range(2)))
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 1)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.get().veces_detectado, 2)
