from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Comentario, Publicacion


class ComentariosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.autor = get_user_model().objects.create_user('autor_comentario', password='test-only-password')
        cls.otro = get_user_model().objects.create_user('otro_comentario', password='test-only-password')
        cls.admin = get_user_model().objects.create_user('moderador_comentario', password='test-only-password', is_staff=True)
        call_command('configurar_roles', verbosity=0)
        cls.admin.groups.add(Group.objects.get(name='Administrador'))
        cls.noticia = Publicacion.objects.create(hash_origen='comentarios-prueba', titulo='Noticia de prueba', contenido='Contenido')

    def comentario(self, texto='Comentario de prueba'):
        return Comentario.objects.create(publicacion=self.noticia, autor=self.autor, texto=texto,
                                        estado=Comentario.Estado.PUBLICADO)

    def test_lectura_publica_y_html_escapado_sin_acciones_ajenas(self):
        comentario = self.comentario('<script>alert(1)</script>')
        response = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ingresar para participar')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, reverse('editar_comentario', args=[comentario.pk]))
        self.assertNotContains(response, reverse('eliminar_comentario', args=[comentario.pk]))

    def test_anonimo_no_puede_escribir_editar_ni_eliminar(self):
        comentario = self.comentario()
        for nombre, pk in [('crear_comentario', self.noticia.pk), ('editar_comentario', comentario.pk), ('eliminar_comentario', comentario.pk)]:
            response = self.client.post(reverse(nombre, args=[pk]), {'texto': 'Cambio'})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse('login')))
        comentario.refresh_from_db()
        self.assertEqual(comentario.texto, 'Comentario de prueba')
        self.assertEqual(Comentario.objects.count(), 1)

    def test_creacion_fija_autor_y_noticia_del_servidor(self):
        self.client.force_login(self.autor)
        response = self.client.post(reverse('crear_comentario', args=[self.noticia.pk]), {
            'texto': '  Mi opinión  ', 'autor': self.otro.pk, 'publicacion': 999,
        })
        self.assertEqual(response.status_code, 302)
        comentario = Comentario.objects.get()
        self.assertEqual(comentario.autor, self.autor)
        self.assertEqual(comentario.publicacion, self.noticia)
        self.assertEqual(comentario.texto, 'Mi opinión')
        self.assertEqual(comentario.estado, Comentario.Estado.PENDIENTE)
        self.assertContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Mi opinión')
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Mi opinión')

    def test_vacio_largo_y_noticia_inexistente(self):
        self.client.force_login(self.autor)
        for texto in ['', '  \n ', 'a' * 2001]:
            response = self.client.post(reverse('crear_comentario', args=[self.noticia.pk]), {'texto': texto})
            self.assertEqual(response.status_code, 400)
            self.assertIn('texto', response.context['form'].errors)
        self.assertFalse(Comentario.objects.exists())
        self.assertEqual(self.client.post(reverse('crear_comentario', args=[999999]), {'texto': 'Texto'}).status_code, 404)

    def test_autor_edita_y_borra_solo_mediante_post(self):
        comentario = self.comentario()
        original = comentario.fecha_creacion
        self.client.force_login(self.autor)
        self.assertEqual(self.client.get(reverse('crear_comentario', args=[self.noticia.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('editar_comentario', args=[comentario.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('eliminar_comentario', args=[comentario.pk])).status_code, 405)
        response = self.client.post(reverse('editar_comentario', args=[comentario.pk]), {'texto': 'Actualizado'})
        self.assertEqual(response.status_code, 302)
        comentario.refresh_from_db()
        self.assertEqual(comentario.texto, 'Actualizado')
        self.assertEqual(comentario.fecha_creacion, original)
        self.assertIsNotNone(comentario.fecha_edicion)
        self.assertEqual(comentario.estado, Comentario.Estado.PENDIENTE)
        self.assertEqual(self.client.post(reverse('eliminar_comentario', args=[comentario.pk])).status_code, 302)
        self.assertFalse(Comentario.objects.exists())

    def test_otro_usuario_no_puede_editar_ni_borrar(self):
        comentario = self.comentario()
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(reverse('editar_comentario', args=[comentario.pk])).status_code, 403)
        for nombre in ['editar_comentario', 'eliminar_comentario']:
            self.assertEqual(self.client.post(reverse(nombre, args=[comentario.pk]), {'texto': 'Manipulado'}).status_code, 403)
        comentario.refresh_from_db()
        self.assertEqual(comentario.texto, 'Comentario de prueba')

    def test_administrador_modera_sin_reescribir_al_autor(self):
        comentario = self.comentario()
        self.client.force_login(self.admin)
        self.assertTrue(self.admin.has_perm('core.delete_comentario'))
        self.assertContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Moderar comentario')
        self.assertEqual(self.client.post(reverse('editar_comentario', args=[comentario.pk]), {'texto': 'Cambio ajeno'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('eliminar_comentario', args=[comentario.pk])).status_code, 302)
        self.assertFalse(Comentario.objects.exists())

    def test_staff_sin_permiso_no_puede_moderar(self):
        comentario = self.comentario()
        self.otro.is_staff = True
        self.otro.save(update_fields=['is_staff'])
        self.client.force_login(self.otro)
        self.assertEqual(self.client.post(reverse('eliminar_comentario', args=[comentario.pk])).status_code, 403)

    def test_paginacion_y_usuario_eliminado(self):
        for indice in range(12):
            self.comentario(f'Opinión {indice}')
        url = reverse('noticia', args=[self.noticia.pk])
        primero = self.client.get(url)
        self.assertEqual(len(primero.context['comentarios_pagina']), 10)
        self.assertEqual(primero.context['comentarios_pagina'].paginator.count, 12)
        self.assertEqual(len(self.client.get(url + '?pagina_comentarios=2').context['comentarios_pagina']), 2)
        self.assertEqual(self.client.get(url + '?pagina_comentarios=no-numero').status_code, 200)
        self.autor.delete()
        self.assertEqual(Comentario.objects.count(), 12)
        self.assertContains(self.client.get(url), 'Usuario eliminado')

    def test_csrf_en_creacion_edicion_y_eliminacion(self):
        comentario = self.comentario()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.autor)
        for nombre, pk in [('crear_comentario', self.noticia.pk), ('editar_comentario', comentario.pk), ('eliminar_comentario', comentario.pk)]:
            self.assertEqual(client.post(reverse(nombre, args=[pk]), {'texto': 'Sin token'}).status_code, 403)
        self.assertEqual(Comentario.objects.count(), 1)
