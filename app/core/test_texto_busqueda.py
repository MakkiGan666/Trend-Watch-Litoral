"""Persistencia, proyección e historial del texto derivado; sin servicios externos."""
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import serializers
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.admin import PublicacionAdminForm
from core.busqueda_texto_v1 import plegar_v1
from core.forms import PublicacionForm
from core.models import Comentario, Publicacion, PublicacionGuardada, Sentimiento, Locacion, PublicacionTema, VotoPublicacion
from core.serializers import PublicacionCreateSerializer, PublicacionUpdateSerializer

DERIVADOS = {'titulo_busqueda', 'contenido_busqueda'}


class TextoBusquedaTests(TestCase):
    def crear(self, clave='texto'):
        return Publicacion.objects.create(hash_origen=clave, titulo='EDUCACIO\u0301N NIÑO', contenido='PINGÜINO')

    def comprobar(self, p, titulo, contenido):
        datos = Publicacion.objects.values('titulo', 'contenido', 'titulo_busqueda', 'contenido_busqueda').get(pk=p.pk)
        self.assertEqual((datos['titulo'], datos['contenido']), (titulo, contenido))
        self.assertEqual((datos['titulo_busqueda'], datos['contenido_busqueda']),
                         (plegar_v1(titulo), plegar_v1(contenido)))

    def test_save_y_update_fields(self):
        p = self.crear()
        self.comprobar(p, 'EDUCACIO\u0301N NIÑO', 'PINGÜINO')
        p.titulo = 'NIÑO y NINO'
        p.save()
        self.comprobar(p, p.titulo, p.contenido)
        p.contenido = 'pingu\u0308ino'
        p.save(update_fields=['contenido'])
        self.comprobar(p, p.titulo, p.contenido)

    def test_queryset_update_y_bulk(self):
        p = self.crear()
        Publicacion.objects.filter(pk=p.pk).update(titulo='EDUCACIÓN', contenido='NIÑO')
        self.comprobar(p, 'EDUCACIÓN', 'NIÑO')
        p.titulo, p.contenido = 'educacio\u0301n', 'PINGÜINO niño'
        Publicacion.objects.bulk_update([p], ['titulo', 'contenido'])
        self.comprobar(p, p.titulo, p.contenido)
        nuevos = Publicacion.objects.bulk_create([
            Publicacion(hash_origen='bulk-a', titulo='ÑANDÚ', contenido='EDUCACIÓN'),
            Publicacion(hash_origen='bulk-b', titulo='NANDU', contenido='pingu\u0308ino'),
        ])
        for noticia in nuevos:
            self.comprobar(noticia, noticia.titulo, noticia.contenido)

    def test_proyeccion_no_lee_derivados_ni_dispara_consultas_adicionales(self):
        p = self.crear()
        with self.assertNumQueries(1), CaptureQueriesContext(connection) as consultas:
            leida = Publicacion.objects.get(pk=p.pk)
            self.assertEqual(leida.titulo, p.titulo)
            self.assertEqual(leida.contenido, p.contenido)
            self.assertEqual(str(leida), p.titulo)
        self.assertEqual(leida.get_deferred_fields(), DERIVADOS)
        seleccion = consultas[0]['sql'].split(' FROM ')[0]
        for nombre in DERIVADOS:
            self.assertNotIn(nombre, seleccion)
        # Serializar tampoco debe cargar derivados diferidos ni exponerlos.
        with self.assertNumQueries(0):
            datos = serializers.serialize('json', [leida])
        for nombre in DERIVADOS:
            self.assertNotIn(nombre, datos)

    def test_no_editables_en_formularios_admin_ni_api(self):
        request = RequestFactory().get('/admin/')
        request.user = get_user_model()(is_active=True, is_staff=True, is_superuser=True)
        campos_admin = admin.site._registry[Publicacion].get_fields(request)
        for nombre in DERIVADOS:
            campo = Publicacion._meta.get_field(nombre)
            self.assertTrue(campo.generated)
            self.assertTrue(campo.db_persist)
            self.assertFalse(campo.editable)
            self.assertFalse(campo.serialize)
            self.assertNotIn(nombre, PublicacionForm.base_fields)
            self.assertNotIn(nombre, PublicacionAdminForm.base_fields)
            self.assertNotIn(nombre, campos_admin)
            self.assertNotIn(nombre, PublicacionCreateSerializer().fields)
            self.assertNotIn(nombre, PublicacionUpdateSerializer().fields)
        entrada = PublicacionUpdateSerializer(data={'titulo_busqueda': 'forzado'}, partial=True)
        self.assertFalse(entrada.is_valid())

    def test_listado_y_detalle_no_exponen_ni_seleccionan_derivados(self):
        p = self.crear()
        for url in [reverse('listar_publicaciones'), reverse('detalle_publicacion', args=[p.pk])]:
            with CaptureQueriesContext(connection) as consultas:
                respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 200)
            for nombre in DERIVADOS:
                self.assertNotIn(nombre, respuesta.content.decode())
                for consulta in consultas:
                    self.assertNotIn(nombre, consulta['sql'].split(' FROM ')[0])

    def test_relaciones_omiten_derivados(self):
        p = self.crear()
        user = get_user_model().objects.create_user(username='lector')
        PublicacionGuardada.objects.create(usuario=user, publicacion=p)
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as consultas:
            respuesta = self.client.get(reverse('mis_guardados'))
        self.assertEqual(respuesta.status_code, 200)
        for consulta in consultas:
            for nombre in DERIVADOS:
                self.assertNotIn(nombre, consulta['sql'].split(' FROM ')[0])
        comentario = Comentario.objects.create(publicacion=p, autor=user, texto='Un comentario')
        with CaptureQueriesContext(connection) as consultas:
            respuesta = self.client.get(reverse('editar_comentario', args=[comentario.pk]))
        self.assertEqual(respuesta.status_code, 200)
        for consulta in consultas:
            for nombre in DERIVADOS:
                self.assertNotIn(nombre, consulta['sql'].split(' FROM ')[0])
        request = RequestFactory().get('/admin/')
        for modelo in [Sentimiento, Locacion, PublicacionTema, VotoPublicacion]:
            queryset = admin.site._registry[modelo].get_queryset(request).select_related('id_publicacion_api')
            seleccion = str(queryset.query).split(' FROM ')[0]
            for nombre in DERIVADOS:
                self.assertNotIn(nombre, seleccion)

    def test_sqlite_registra_funcion_al_conectar_sin_compilar_busquedas(self):
        if connection.vendor != 'sqlite':
            self.skipTest('Registro específico de SQLite')
        nueva = connection.copy(alias='sqlite_busqueda_nueva')
        try:
            with nueva.cursor() as cursor:
                cursor.execute('SELECT tw_plegar_v1(%s)', ['EDUCACIO\u0301N NIÑO PINGÜINO'])
                self.assertEqual(cursor.fetchone()[0], 'educacion niño pinguino')
        finally:
            nueva.close()


class MigracionTextoBusquedaTests(TransactionTestCase):
    anterior = ('core', '0010_perfilusuario_publicacionguardada')
    nueva = ('core', '0011_publicacion_texto_busqueda')

    def test_migrar_existentes_y_revertir_preserva_originales(self):
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([self.anterior])
            Vieja = executor.loader.project_state([self.anterior]).apps.get_model('core', 'Publicacion')
            p = Vieja.objects.create(hash_origen='historica', titulo='EDUCACIO\u0301N niño', contenido='PINGÜINO nino')
            originales = (p.pk, p.titulo, p.contenido)
            executor = MigrationExecutor(connection)
            executor.migrate([self.nueva])
            Nueva = executor.loader.project_state([self.nueva]).apps.get_model('core', 'Publicacion')
            leida = Nueva.objects.get(pk=p.pk)
            self.assertEqual((leida.pk, leida.titulo, leida.contenido), originales)
            self.assertEqual((leida.titulo_busqueda, leida.contenido_busqueda),
                             ('educacion niño', 'pinguino nino'))
            executor = MigrationExecutor(connection)
            executor.migrate([self.anterior])
            Vieja = executor.loader.project_state([self.anterior]).apps.get_model('core', 'Publicacion')
            leida = Vieja.objects.get(pk=p.pk)
            self.assertEqual((leida.pk, leida.titulo, leida.contenido), originales)
            with connection.cursor() as cursor:
                columnas = {c.name for c in connection.introspection.get_table_description(cursor, 'Publicacion')}
            self.assertTrue(DERIVADOS.isdisjoint(columnas))
        finally:
            MigrationExecutor(connection).migrate([self.nueva])
