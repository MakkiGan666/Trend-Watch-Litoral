from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.db import IntegrityError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
import json
from io import StringIO

from core.models import (
    CandidatoDuplicadoEditorial, EventoRevisionEditorial, GrupoEditorial,
    MiembroGrupoEditorial, Publicacion, PublicacionEtiqueta, PublicacionTema,
)
from core.services.agrupacion_automatica import (
    VERSION_REGLA_AUTOMATICA,
    aplicar_candidato_automatico,
    evaluar_elegibilidad,
)
from core.services.agrupacion_editorial import revocar_grupo
from core.services.deteccion_sombra_editorial import registrar_candidatos_sombra
from core.services.deteccion_sombra_editorial import _huella as huella_detector
from core.services.duplicados_editoriales import detectar_candidatos


CUERPO = (
    'El municipio informó el inicio de obras de infraestructura, servicios y mejoras para distintos barrios '
    'de Misiones. Las autoridades explicaron el alcance del proyecto, el calendario de ejecución y las '
    'medidas previstas para acompañar a las familias durante los trabajos. ' * 5
)


class AgrupacionAutomaticaTests(TestCase):
    def setUp(self):
        self.fecha = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.publicacion_a = self.publicacion(1)
        self.publicacion_b = self.publicacion(2)
        self.candidato = self.crear_candidato(self.publicacion_a, self.publicacion_b)

    def publicacion(self, numero, **cambios):
        datos = {
            'hash_origen': f'fase3b-{numero}',
            'fuente': 'El Territorio (Archivo)',
            'titulo': 'Municipio informó nuevas obras para distintos barrios',
            'url': f'https://medio.test/noticia/{numero}',
            'contenido': CUERPO,
            'contenido_completo': True,
            'fecha_publicacion': self.fecha,
        }
        datos.update(cambios)
        return Publicacion.objects.create(**datos)

    def crear_candidato(self, a, b):
        evaluacion = detectar_candidatos([self.fila(a), self.fila(b)])
        if not evaluacion:
            self.fail('El fixture debe producir un par para revisión en sombra.')
        registrar_candidatos_sombra(evaluacion)
        return CandidatoDuplicadoEditorial.objects.get(
            publicacion_a_id=min(a.pk, b.pk), publicacion_b_id=max(a.pk, b.pk),
        )

    @staticmethod
    def fila(publicacion):
        return {
            'pk': publicacion.pk, 'fuente': publicacion.fuente,
            'titulo': publicacion.titulo, 'url': publicacion.url,
            'fecha_publicacion': publicacion.fecha_publicacion,
            'contenido': publicacion.contenido,
            'contenido_completo': publicacion.contenido_completo,
        }

    def test_politica_estricta_exige_mismo_titulo_fecha_y_cuerpo_completo(self):
        verdict = evaluar_elegibilidad(self.candidato)
        self.assertTrue(verdict['elegible'], verdict)
        self.assertEqual(verdict['version_regla'], VERSION_REGLA_AUTOMATICA)
        self.assertEqual(verdict['similitud_detector']['estado'], 'DUPLICADO_CONFIRMADO')

        incompleta = self.publicacion(3, contenido='', contenido_completo=False)
        par_incompleto = self.crear_candidato(self.publicacion_a, incompleta)
        self.assertFalse(evaluar_elegibilidad(par_incompleto)['elegible'])

    def test_candidato_url_exacta_requiere_y_supera_la_misma_regla_editorial(self):
        self.publicacion_b.url = self.publicacion_a.url
        self.publicacion_b.save(update_fields=['url'])
        candidato = self.crear_candidato(self.publicacion_a, self.publicacion_b)
        self.assertEqual(candidato.clasificacion, CandidatoDuplicadoEditorial.Clasificacion.EXACTO)
        resultado = evaluar_elegibilidad(candidato)
        self.assertTrue(resultado['elegible'], resultado)

    def test_aliases_del_mismo_medio_se_comparan_por_fuente_normalizada(self):
        self.publicacion_b.fuente = 'El Territorio'
        self.publicacion_b.save(update_fields=['fuente'])
        candidato = self.crear_candidato(self.publicacion_a, self.publicacion_b)
        resultado = evaluar_elegibilidad(candidato)
        self.assertTrue(resultado['elegible'], resultado)

    def test_actualizacion_editorial_legitima_no_se_agrupa_por_similitud(self):
        actualizada = self.publicacion(4, contenido=CUERPO + ' La nueva etapa comenzará en diciembre.')
        candidato = self.crear_candidato(self.publicacion_a, actualizada)
        verdict = evaluar_elegibilidad(candidato)
        self.assertEqual(verdict['motivo'], 'CUERPO_NO_EQUIVALENTE')
        self.assertFalse(verdict['elegible'])

    def test_normaliza_markup_y_espacios_pero_preserva_puntuacion(self):
        representada = self.publicacion_a
        duplicada = self.publicacion_b
        duplicada.contenido = '<p>' + CUERPO.replace('  ', ' ').replace('obras de infraestructura', 'obras de <b>infraestructura</b>') + '</p>'
        duplicada.save(update_fields=['contenido'])
        candidato = self.crear_candidato(representada, duplicada)
        self.assertTrue(evaluar_elegibilidad(candidato)['elegible'])

        duplicada.contenido = duplicada.contenido.replace('obras de', 'obras, de', 1)
        duplicada.save(update_fields=['contenido'])
        candidato = self.crear_candidato(representada, duplicada)
        self.assertEqual(evaluar_elegibilidad(candidato)['motivo'], 'CUERPO_NO_EQUIVALENTE')

    def test_fuentes_y_fechas_editoriales_distintas_no_son_elegibles(self):
        self.publicacion_b.fuente = 'Norte Misionero'
        self.publicacion_b.save(update_fields=['fuente'])
        evidencia = self.candidato.evidencia
        huellas_actuales = [
            huella_detector(self.fila(self.publicacion_a)),
            huella_detector(self.fila(self.publicacion_b)),
        ]
        self.candidato.huella_a, self.candidato.huella_b = huellas_actuales
        evidencia['huellas_publicacion'] = huellas_actuales
        self.candidato.evidencia = evidencia
        self.candidato.save(update_fields=['huella_a', 'huella_b', 'evidencia'])
        self.assertEqual(evaluar_elegibilidad(self.candidato)['motivo'], 'FUENTE_DISTINTA')

        fecha_distinta = self.publicacion(
            5, fecha_publicacion=self.fecha + timedelta(days=1),
        )
        candidato_fecha = self.crear_candidato(self.publicacion_a, fecha_distinta)
        self.assertEqual(evaluar_elegibilidad(candidato_fecha)['motivo'], 'FECHA_EDITORIAL_DISTINTA')

    def test_evidencia_obsoleta_se_rechaza_sin_actualizar_candidato(self):
        self.publicacion_b.titulo = 'Una noticia distinta sobre otra localidad'
        self.publicacion_b.save(update_fields=['titulo'])
        resultado = evaluar_elegibilidad(self.candidato)
        self.assertEqual(resultado['motivo'], 'EVIDENCIA_DESACTUALIZADA')
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.estado, CandidatoDuplicadoEditorial.Estado.PENDIENTE)

    def test_fuente_de_evidencia_manipulada_no_habilita_agrupacion(self):
        self.candidato.evidencia['fuente_normalizada'] = 'norte misionero'
        self.candidato.save(update_fields=['evidencia'])
        self.assertEqual(
            evaluar_elegibilidad(self.candidato)['motivo'],
            'FUENTE_EVIDENCIA_DESACTUALIZADA',
        )

    @override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=False)
    def test_aplicar_esta_bloqueado_por_defecto(self):
        with self.assertRaises(PermissionDenied):
            aplicar_candidato_automatico(self.candidato.pk)
        self.assertFalse(GrupoEditorial.objects.exists())

    @override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=True)
    def test_aplicacion_es_atomica_auditable_idempotente_y_preserva_originales(self):
        publicaciones_antes = list(Publicacion.objects.order_by('pk').values_list(
            'pk', 'titulo', 'contenido', 'url', 'fuente', 'fecha_publicacion', 'contenido_completo',
        ))
        relaciones_antes = (PublicacionTema.objects.count(), PublicacionEtiqueta.objects.count())
        creado = aplicar_candidato_automatico(self.candidato.pk)
        repetido = aplicar_candidato_automatico(self.candidato.pk)

        self.assertTrue(creado['creado'])
        self.assertFalse(repetido['creado'])
        self.assertEqual(GrupoEditorial.objects.count(), 1)
        self.assertEqual(MiembroGrupoEditorial.objects.count(), 2)
        grupo = GrupoEditorial.objects.get()
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.ACTIVO)
        self.assertEqual(grupo.origen_decision, GrupoEditorial.OrigenDecision.AUTOMATICA)
        self.assertIsNone(grupo.creado_por)
        self.assertIsNone(grupo.aprobado_por)
        self.assertEqual(grupo.candidato_automatico_id, self.candidato.pk)
        self.assertEqual(grupo.regla_automatica_version, VERSION_REGLA_AUTOMATICA)
        self.assertTrue(all(m.metodo_decision == MiembroGrupoEditorial.MetodoDecision.AUTOMATICA
                            and m.revisado_por is None and m.vigente
                            for m in grupo.miembros.all()))
        evento = EventoRevisionEditorial.objects.get(grupo=grupo)
        self.assertEqual(evento.tipo, EventoRevisionEditorial.Tipo.AUTOAGRUPADO)
        self.assertEqual(evento.metodo_actor, EventoRevisionEditorial.MetodoActor.AUTOMATIZACION)
        self.assertIsNone(evento.actor)
        self.assertEqual(len(evento.clave_idempotencia), 64)
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.estado, CandidatoDuplicadoEditorial.Estado.EN_GRUPO)
        self.assertEqual(publicaciones_antes, list(Publicacion.objects.order_by('pk').values_list(
            'pk', 'titulo', 'contenido', 'url', 'fuente', 'fecha_publicacion', 'contenido_completo',
        )))
        self.assertEqual(relaciones_antes, (PublicacionTema.objects.count(), PublicacionEtiqueta.objects.count()))

    @override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=True)
    def test_fallo_al_escribir_auditoria_revierte_grupo_membresias_y_estado(self):
        with patch.object(EventoRevisionEditorial.objects, 'create', side_effect=IntegrityError('fallo aislado')):
            with self.assertRaises(IntegrityError):
                aplicar_candidato_automatico(self.candidato.pk)
        self.assertFalse(GrupoEditorial.objects.exists())
        self.assertFalse(MiembroGrupoEditorial.objects.exists())
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.estado, CandidatoDuplicadoEditorial.Estado.PENDIENTE)

    @override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=True)
    def test_revocar_grupo_automatico_bloquea_reagrupacion(self):
        alternativa = self.publicacion(8)
        candidato_alternativo = self.crear_candidato(self.publicacion_a, alternativa)
        resultado = aplicar_candidato_automatico(self.candidato.pk)
        actor = get_user_model().objects.create_superuser(
            username='fase3b-revocador', email='fase3b@example.test', password='test-only-password',
        )
        revocar_grupo(actor=actor, grupo_id=resultado['grupo_id'], motivo='Revocación aislada de regresión')
        self.candidato.refresh_from_db()
        self.assertTrue(self.candidato.automatizacion_bloqueada)
        registrar_candidatos_sombra(detectar_candidatos([
            self.fila(self.publicacion_a), self.fila(self.publicacion_b),
        ]))
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.estado, CandidatoDuplicadoEditorial.Estado.PENDIENTE)
        self.assertFalse(aplicar_candidato_automatico(self.candidato.pk)['creado'])
        candidato_alternativo.refresh_from_db()
        self.assertTrue(candidato_alternativo.automatizacion_bloqueada)
        self.assertEqual(
            evaluar_elegibilidad(candidato_alternativo)['motivo'],
            'AUTOMATIZACION_BLOQUEADA',
        )

    def test_api_y_sugerencias_conservan_un_resultado_y_versiones_originales(self):
        with override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=True):
            resultado = aplicar_candidato_automatico(self.candidato.pk)
        self.publicacion_a.refresh_from_db()
        consulta = 'municipio informó nuevas obras'
        api = self.client.get('/api/publicaciones/buscar/', {'q': consulta})
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        grupo = next(item for item in payload['resultados']
                     if item.get('id_publicacion_api') == resultado['representante_id'])
        self.assertEqual(len(grupo['versiones_originales']), 2)
        sugerencias = self.client.get('/api/publicaciones/sugerencias/', {'q': 'municipio informó'})
        self.assertEqual(sugerencias.status_code, 200)
        self.assertIn(resultado['representante_id'], [
            item.get('id_publicacion_api') for item in sugerencias.json()['noticias']
        ])


class AgrupacionAutomaticaConcurrenciaTests(TransactionTestCase):
    reset_sequences = True

    @override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=False)
    def test_dry_run_no_escribe_y_command_apply_requiere_gate(self):
        fecha = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        a = Publicacion.objects.create(
            hash_origen='fase3b-dry-a', fuente='El Territorio (Archivo)',
            titulo='Municipio informó nuevas obras para distintos barrios',
            url='https://medio.test/dry-a', contenido=CUERPO, contenido_completo=True,
            fecha_publicacion=fecha,
        )
        b = Publicacion.objects.create(
            hash_origen='fase3b-dry-b', fuente=a.fuente, titulo=a.titulo,
            url='https://medio.test/dry-b', contenido=CUERPO, contenido_completo=True,
            fecha_publicacion=fecha,
        )
        par = detectar_candidatos([{
            'pk': p.pk, 'fuente': p.fuente, 'titulo': p.titulo, 'url': p.url,
            'fecha_publicacion': p.fecha_publicacion, 'contenido': p.contenido,
            'contenido_completo': p.contenido_completo,
        } for p in (a, b)])
        registrar_candidatos_sombra(par)
        salida = StringIO()
        call_command('agrupar_duplicados_editoriales', dry_run=True, stdout=salida)
        datos = json.loads(salida.getvalue())
        self.assertEqual(datos['elegibles'], 1)
        self.assertFalse(GrupoEditorial.objects.exists())
        with self.assertRaises(CommandError):
            call_command('agrupar_duplicados_editoriales', aplicar=True, stdout=StringIO())

    def test_ejecuciones_concurrentes_sobre_pares_solapados_no_crean_transitividad(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La concurrencia se valida en PostgreSQL aislado.')
        fecha = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        publicaciones = [Publicacion.objects.create(
            hash_origen=f'fase3b-concurrente-{i}', fuente='El Territorio (Archivo)',
            titulo='La misma noticia con contenido idéntico en el archivo',
            url=f'https://medio.test/concurrente/{i}', contenido=CUERPO,
            contenido_completo=True, fecha_publicacion=fecha,
        ) for i in range(3)]
        filas = [{
            'pk': p.pk, 'fuente': p.fuente, 'titulo': p.titulo, 'url': p.url,
            'fecha_publicacion': p.fecha_publicacion, 'contenido': p.contenido,
            'contenido_completo': p.contenido_completo,
        } for p in publicaciones]
        pares = [par for par in detectar_candidatos(filas)
                 if set(row['pk'] for row in par['publicaciones']) in (
                     {publicaciones[0].pk, publicaciones[1].pk},
                     {publicaciones[0].pk, publicaciones[2].pk},
                 )]
        registrar_candidatos_sombra(pares)
        ids = list(CandidatoDuplicadoEditorial.objects.order_by('pk').values_list('pk', flat=True))
        self.assertEqual(len(ids), 2)
        barrera = Barrier(2)

        def ejecutar(pk):
            close_old_connections()
            try:
                barrera.wait(timeout=10)
                return aplicar_candidato_automatico(pk)
            finally:
                close_old_connections()

        with override_settings(AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA=True):
            with ThreadPoolExecutor(max_workers=2) as executor:
                resultados = list(executor.map(ejecutar, ids))
        self.assertEqual(sum(r['creado'] for r in resultados), 1)
        self.assertEqual(GrupoEditorial.objects.filter(estado=GrupoEditorial.Estado.ACTIVO).count(), 1)
        self.assertEqual(MiembroGrupoEditorial.objects.filter(vigente=True).count(), 2)
        self.assertEqual(EventoRevisionEditorial.objects.filter(tipo=EventoRevisionEditorial.Tipo.AUTOAGRUPADO).count(), 1)
