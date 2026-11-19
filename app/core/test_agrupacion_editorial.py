from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.db.models.deletion import ProtectedError
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AliasURLPublicacion, EventoRevisionEditorial, GrupoEditorial,
    MiembroGrupoEditorial, Publicacion,
)
from core.services.agrupacion_editorial import (
    activar_grupo, crear_grupo, decidir_miembro, revocar_grupo,
    seleccionar_representante,
)


CUERPO = 'La municipalidad informó obras y servicios para los barrios de Misiones. ' * 12


class AgrupacionEditorialTestCase(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.revisor = self.usuario('revisor', 'revisar_candidatos_editoriales')
        self.aprobador = self.usuario('aprobador', 'aprobar_agrupacion_editorial')
        self.revocador = self.usuario('revocador', 'revocar_agrupacion_editorial')

    def usuario(self, username, *codigos):
        user = get_user_model().objects.create_user(username=username, password='prueba-segura')
        user.is_staff = True
        user.save(update_fields=['is_staff'])
        permissions = Permission.objects.filter(
            content_type__app_label='core', codename__in=codigos,
        )
        user.user_permissions.add(*permissions)
        return get_user_model().objects.get(pk=user.pk)

    def publicacion(self, numero, *, fuente='El Territorio', contenido=CUERPO, completo=True,
                    titulo='La municipalidad informa obras y servicios', fecha=None, url=None):
        fecha = fecha or timezone.now() - timedelta(hours=2)
        return Publicacion.objects.create(
            hash_origen=f'agrupacion-{numero}', fuente=fuente, titulo=titulo,
            contenido=contenido if completo else '', contenido_completo=completo,
            fecha_publicacion=fecha, url=url or f'https://medio.test/noticia/{numero}',
        )

    def crear(self, publicaciones, actor=None, representante_id=None):
        return crear_grupo(
            actor=actor or self.revisor,
            publicacion_ids=[p.pk for p in publicaciones],
            representante_id=representante_id,
            motivo='Revisión humana de evidencia editorial directa',
        )

    def aprobar_miembros(self, grupo, actor=None):
        for miembro in grupo.miembros.order_by('pk'):
            decidir_miembro(
                actor=actor or self.revisor, miembro_id=miembro.pk,
                decision=MiembroGrupoEditorial.Decision.APROBADO,
                motivo='La comparación directa confirma la pertenencia',
            )

    def test_creacion_revision_individual_activacion_revocacion_y_preservacion(self):
        fecha = timezone.now() - timedelta(days=1)
        a = self.publicacion(1, fecha=fecha)
        b = self.publicacion(2, fecha=fecha, url='https://medio.test/noticia/canonica-distinta')
        alias = AliasURLPublicacion.objects.create(
            publicacion=b, fuente='noticias_del_6', url_normalizada='https://medio.test/alias/2',
        )
        antes = (a.titulo, a.contenido, a.url, b.titulo, b.contenido, b.url, alias.publicacion_id)
        grupo = self.crear([a, b])
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.BORRADOR)
        self.assertEqual(grupo.representante_id, a.pk)
        self.assertFalse(grupo.miembros.filter(vigente=True).exists())
        self.assertEqual(grupo.miembros.count(), 2)
        self.aprobar_miembros(grupo)
        activar_grupo(actor=self.aprobador, grupo_id=grupo.pk, motivo='Aprobación editorial independiente')
        grupo.refresh_from_db()
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.ACTIVO)
        self.assertEqual(grupo.miembros.filter(vigente=True).count(), 2)
        revocar_grupo(actor=self.revocador, grupo_id=grupo.pk, motivo='Revocación de control')
        grupo.refresh_from_db()
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.REVOCADO)
        self.assertFalse(grupo.miembros.filter(vigente=True).exists())
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.titulo, a.contenido, a.url, b.titulo, b.contenido, b.url, alias.publicacion_id), antes)
        self.assertEqual(grupo.eventos_revision.count(), 5)

    def test_permisos_y_motivo_obligatorio(self):
        a, b = self.publicacion(3), self.publicacion(4)
        sin_permiso = get_user_model().objects.create_user(username='sin_permiso', password='prueba-segura')
        with self.assertRaises(PermissionDenied):
            self.crear([a, b], actor=sin_permiso)
        grupo = self.crear([a, b])
        miembro = grupo.miembros.exclude(rol=MiembroGrupoEditorial.Rol.REPRESENTANTE).get()
        with self.assertRaises(ValidationError):
            decidir_miembro(actor=self.revisor, miembro_id=miembro.pk,
                            decision=MiembroGrupoEditorial.Decision.APROBADO, motivo=' ')
        with self.assertRaises(PermissionDenied):
            activar_grupo(actor=self.revisor, grupo_id=grupo.pk, motivo='No tiene permiso de aprobación')

    def test_seleccion_determinista_prefiere_integridad_y_desempata_por_id(self):
        fecha = timezone.now() - timedelta(days=1)
        a = self.publicacion(5, contenido='', completo=False, url='https://medio.test/rss/5')
        b = self.publicacion(6, contenido=CUERPO, completo=True, fecha=fecha, url='https://medio.test/articulo/6')
        c = self.publicacion(7, contenido=CUERPO, completo=True, fecha=fecha, url='https://medio.test/articulo/7')
        self.assertEqual(seleccionar_representante([a, c, b]).pk, b.pk)
        self.assertEqual(seleccionar_representante([c, b, a]).pk, b.pk)

    def test_rechaza_medios_distintos_y_candidato_transitivo_sin_evidencia_directa(self):
        a = self.publicacion(8, contenido=CUERPO)
        b = self.publicacion(9, contenido=CUERPO, url='https://medio.test/noticia/b')
        c = self.publicacion(10, contenido=('El Concejo trató impuestos, presupuesto y tasas. ' * 12),
                             titulo='El Concejo sesionó por presupuesto', url='https://medio.test/noticia/c')
        grupo_ab = self.crear([a, b], representante_id=a.pk)
        with self.assertRaises(ValidationError):
            self.crear([a, c], representante_id=a.pk)
        otro_medio = self.publicacion(11, fuente='Norte Misionero', url='https://norte.test/noticia/11')
        with self.assertRaisesMessage(ValidationError, 'medios distintos'):
            self.crear([a, otro_medio])
        self.assertEqual(grupo_ab.estado, GrupoEditorial.Estado.BORRADOR)

    def test_requiere_decision_explicita_de_todos_y_no_aprueba_transitivamente(self):
        a, b = self.publicacion(12), self.publicacion(13, url='https://medio.test/noticia/13')
        grupo = self.crear([a, b])
        with self.assertRaisesMessage(ValidationError, 'decisión individual'):
            activar_grupo(actor=self.aprobador, grupo_id=grupo.pk, motivo='Aprobación')
        self.aprobar_miembros(grupo)
        activar_grupo(actor=self.aprobador, grupo_id=grupo.pk, motivo='Revisión completa')
        self.assertEqual(grupo.miembros.filter(vigente=True).count(), 2)

    def test_rechazo_individual_queda_auditado_y_no_activa_el_grupo(self):
        a, b = self.publicacion(22), self.publicacion(23, url='https://medio.test/noticia/23')
        grupo = self.crear([a, b])
        miembros = list(grupo.miembros.order_by('pk'))
        for miembro in miembros:
            decidir_miembro(
                actor=self.revisor, miembro_id=miembro.pk,
                decision=(MiembroGrupoEditorial.Decision.RECHAZADO
                          if miembro.rol == MiembroGrupoEditorial.Rol.MIEMBRO
                          else MiembroGrupoEditorial.Decision.APROBADO),
                motivo='Revisión individual con evidencia insuficiente',
            )
        with self.assertRaisesMessage(ValidationError, 'al menos un miembro aprobado'):
            activar_grupo(actor=self.aprobador, grupo_id=grupo.pk, motivo='No debe activarse')
        self.assertTrue(EventoRevisionEditorial.objects.filter(
            grupo=grupo, tipo=EventoRevisionEditorial.Tipo.RECHAZADO,
        ).exists())
        self.assertFalse(grupo.miembros.filter(vigente=True).exists())

    def test_representante_final_se_selecciona_al_aprobar_y_reabre_revision_si_cambia(self):
        fecha = timezone.now() - timedelta(days=2)
        a = self.publicacion(24, fecha=fecha)
        b = self.publicacion(25, fecha=fecha, url='https://medio.test/noticia/25')
        grupo = self.crear([a, b], representante_id=a.pk)
        self.aprobar_miembros(grupo)
        resultado = activar_grupo(
            actor=self.aprobador, grupo_id=grupo.pk, representante_id=b.pk,
            motivo='La revisión final elige la versión más completa',
        )
        self.assertTrue(resultado['requiere_revision'])
        grupo.refresh_from_db()
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.BORRADOR)
        self.assertEqual(grupo.representante_id, b.pk)
        self.assertEqual(grupo.miembros.filter(decision=MiembroGrupoEditorial.Decision.PENDIENTE).count(), 2)
        self.assertFalse(grupo.miembros.filter(vigente=True).exists())
        self.aprobar_miembros(grupo)
        resultado = activar_grupo(
            actor=self.aprobador, grupo_id=grupo.pk, representante_id=b.pk,
            motivo='Aprobación final de todas las relaciones directas',
        )
        self.assertFalse(resultado['requiere_revision'])
        grupo.refresh_from_db()
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.ACTIVO)
        self.assertEqual(grupo.representante_id, b.pk)
        self.assertTrue(grupo.eventos_revision.filter(tipo=EventoRevisionEditorial.Tipo.REPRESENTANTE).exists())

    def test_fichas_rss_incompletas_no_se_agrupan_por_titulo_y_fecha(self):
        a = self.publicacion(14, completo=False)
        b = self.publicacion(15, completo=False, url='https://medio.test/rss/15')
        with self.assertRaises(ValidationError):
            self.crear([a, b])
        self.assertEqual(GrupoEditorial.objects.count(), 0)

    def test_eventos_son_inmutables_y_membresias_protegidas(self):
        a, b = self.publicacion(16), self.publicacion(17)
        grupo = self.crear([a, b])
        evento = grupo.eventos_revision.get()
        with self.assertRaisesMessage(ValidationError, 'inmutables'):
            evento.save()
        with self.assertRaisesMessage(ValidationError, 'eliminar'):
            evento.delete()
        with self.assertRaisesMessage(ValidationError, 'inmutables'):
            EventoRevisionEditorial.objects.filter(pk=evento.pk).update(motivo='alterado')
        with self.assertRaisesMessage(ValidationError, 'eliminar'):
            EventoRevisionEditorial.objects.filter(pk=evento.pk).delete()
        with self.assertRaises(ProtectedError):
            b.delete()

    def test_interfaz_admin_exige_staff_permiso_y_csrf(self):
        a, b = self.publicacion(18), self.publicacion(19)
        grupo = self.crear([a, b])
        miembro = grupo.miembros.exclude(rol=MiembroGrupoEditorial.Rol.REPRESENTANTE).get()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.revisor)
        self.assertEqual(client.get(reverse('admin:core_grupoeditorial_changelist')).status_code, 200)
        self.assertEqual(client.get(reverse('admin:core_grupoeditorial_crear')).status_code, 200)
        self.assertEqual(
            client.get(reverse('admin:core_grupoeditorial_revision', args=[grupo.pk])).status_code,
            200,
        )
        pagina_admin = client.get(reverse('admin:core_grupoeditorial_change', args=[grupo.pk]))
        self.assertEqual(pagina_admin.status_code, 200)
        self.assertContains(pagina_admin, 'readonly')
        self.assertEqual(client.post(
            reverse('admin:core_grupoeditorial_change', args=[grupo.pk]), {'estado': 'ACTIVO'},
        ).status_code, 403)
        grupo.refresh_from_db()
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.BORRADOR)
        url = reverse('admin:core_grupoeditorial_decidir', args=[grupo.pk, miembro.pk])
        self.assertEqual(client.get(url).status_code, 200)
        response = client.post(url, {'decision': 'APROBADO', 'motivo': 'Revisado'})
        self.assertEqual(response.status_code, 403)
        miembro.refresh_from_db()
        self.assertEqual(miembro.decision, MiembroGrupoEditorial.Decision.PENDIENTE)
        sin_permiso = get_user_model().objects.create_user(username='solo_staff', password='prueba-segura', is_staff=True)
        client.force_login(sin_permiso)
        self.assertEqual(client.get(reverse('admin:core_grupoeditorial_changelist')).status_code, 403)

    def test_aprobaciones_concurrentes_no_crean_doble_membresia_vigente(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La prueba de bloqueo requiere PostgreSQL.')
        a, b = self.publicacion(20), self.publicacion(21, url='https://medio.test/noticia/21')
        grupo1 = self.crear([a, b], representante_id=a.pk)
        grupo2 = self.crear([a, b], representante_id=b.pk)
        self.aprobar_miembros(grupo1)
        self.aprobar_miembros(grupo2)
        barrera = Barrier(2)

        def activar(pk):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.aprobador.pk)
                barrera.wait(timeout=10)
                activar_grupo(actor=actor, grupo_id=pk, motivo='Carrera de prueba')
                return 'ACTIVO'
            except Exception as error:
                return f'ERROR:{type(error).__name__}:{error}'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(activar, [grupo1.pk, grupo2.pk]))
        self.assertEqual(resultados.count('ACTIVO'), 1, resultados)
        self.assertEqual(sum(valor.startswith('ERROR:ValidationError') for valor in resultados), 1, resultados)
        self.assertEqual(MiembroGrupoEditorial.objects.filter(publicacion__in=[a, b], vigente=True).count(), 2)
        self.assertEqual(GrupoEditorial.objects.filter(estado=GrupoEditorial.Estado.ACTIVO).count(), 1)
