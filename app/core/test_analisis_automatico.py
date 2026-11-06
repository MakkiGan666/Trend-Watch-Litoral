"""Pruebas de la etapa de análisis automático de comentarios y su categoría.

Cubren la clasificación en las 12 categorías del proyecto, el disparo en segundo
plano al publicar y editar, los fallos de Ollama y la recuperación con el comando
de respaldo. Ollama se simula: no requieren red ni modelos descargados. El
trabajo en segundo plano se ejecuta en el mismo hilo dentro de cada prueba
(salvo la del hilo trabajador, que no toca la base).
"""
import os
import queue
import threading
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Categoria, Comentario, Publicacion, SentimientoComentario
from core.services import analisis_automatico
from core.services import sentimiento_comentarios as servicio
from core.services.clasificacion import CATEGORIAS_PROYECTO

IA = SentimientoComentario.Metodo.IA
LEXICON = SentimientoComentario.Metodo.LEXICON


def prediccion_ia(polaridad=0.6, categoria='Economía'):
    return servicio.Prediccion(polaridad, 0.9, IA, 'ollama:mock', categoria)


def cliente_ollama(raw):
    cliente = MagicMock()
    cliente.post.return_value.json.return_value = {'response': raw}
    return cliente


class BaseComentarios(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('auto_autor', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='auto-1', titulo='t', contenido='c')

    def _comentario(self, texto='Es excelente'):
        return Comentario.objects.create(publicacion=self.noticia, autor=self.usuario, texto=texto)


class CategoriaComentarioTests(BaseComentarios):
    def test_prompt_ofrece_exactamente_las_12_categorias(self):
        for nombre in CATEGORIAS_PROYECTO:
            self.assertIn(nombre, servicio._PROMPT_IA)
        self.assertEqual(len(CATEGORIAS_PROYECTO), 12)

    def test_ollama_categoria_valida_y_normalizada(self):
        for valor, esperado in (('Economía', 'Economía'), ('economia', 'Economía'), ('  SALUD ', 'Salud')):
            with self.subTest(valor=valor):
                raw = f'{{"polaridad": 0.2, "confianza": 0.8, "categoria": "{valor}"}}'
                self.assertEqual(servicio.predecir_ollama('x', cliente_http=cliente_ollama(raw)).categoria, esperado)

    def test_ollama_sin_categoria_o_null(self):
        for raw in ('{"polaridad": 0.2, "confianza": 0.8}',
                    '{"polaridad": 0.2, "confianza": 0.8, "categoria": null}'):
            with self.subTest(raw=raw):
                self.assertIsNone(servicio.predecir_ollama('x', cliente_http=cliente_ollama(raw)).categoria)

    def test_categoria_inventada_invalida_la_respuesta_y_cae_a_lexico(self):
        for valor in ('"Transporte"', '3', '["Salud"]'):
            with self.subTest(valor=valor):
                raw = f'{{"polaridad": 0.2, "confianza": 0.8, "categoria": {valor}}}'
                with self.assertRaises(servicio.SentimientoNoDisponible) as ctx:
                    servicio.predecir_ollama('x', cliente_http=cliente_ollama(raw))
                self.assertEqual(ctx.exception.codigo, 'categoria_invalida')
        raw = '{"polaridad": 0.2, "confianza": 0.8, "categoria": "Transporte"}'
        obj, _ = servicio.analizar_comentario(self._comentario(), usar_ia=True, cliente_http=cliente_ollama(raw))
        self.assertEqual(obj.metodo, LEXICON)
        self.assertEqual(obj.codigo_error, 'ia:categoria_invalida')
        self.assertFalse(Categoria.objects.filter(nombre_categoria='Transporte').exists())

    def test_lexico_asigna_categoria_solo_con_evidencia(self):
        self.assertEqual(servicio.predecir_lexicon('El hospital no tiene médicos').categoria, 'Salud')
        # Sin palabras clave no se usa la categoría por defecto ("Sociedad").
        self.assertIsNone(servicio.predecir_lexicon('excelente').categoria)

    def test_persiste_fk_a_la_categoria_compartida_con_noticias(self):
        existente = Categoria.objects.create(nombre_categoria='Economía')
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia(categoria='Economía')):
            obj, _ = servicio.analizar_comentario(self._comentario(), usar_ia=True)
        self.assertEqual(obj.categoria, existente)
        self.assertEqual(Categoria.objects.filter(nombre_categoria='Economía').count(), 1)

    def test_categoria_del_proyecto_faltante_se_crea_una_sola_vez(self):
        self.assertFalse(Categoria.objects.filter(nombre_categoria='Tecnología').exists())
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia(categoria='Tecnología')):
            servicio.analizar_comentario(self._comentario(), usar_ia=True)
            servicio.analizar_comentario(self._comentario('Otro'), usar_ia=True)
        self.assertEqual(Categoria.objects.filter(nombre_categoria='Tecnología').count(), 1)

    def test_no_crea_categorias_fuera_de_la_lista(self):
        with self.assertRaises(ValueError):
            servicio._categoria_por_nombre('Transporte')
        self.assertFalse(Categoria.objects.filter(nombre_categoria='Transporte').exists())

    def test_error_limpia_la_categoria(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia()):
            servicio.analizar_comentario(comentario, usar_ia=True)
        Comentario.objects.filter(pk=comentario.pk).update(texto='editado')
        obj = servicio.registrar_error_analisis(comentario, 'prueba')
        self.assertEqual(obj.estado, SentimientoComentario.Estado.ERROR)
        self.assertIsNone(obj.categoria)


class PublicacionYEdicionTests(BaseComentarios):
    def _publicar(self, texto):
        self.client.force_login(self.usuario)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('crear_comentario', args=[self.noticia.pk]), {'texto': texto})

    def _editar(self, comentario, texto):
        self.client.force_login(self.usuario)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('editar_comentario', args=[comentario.pk]), {'texto': texto})

    def test_publicar_solo_encola_y_no_analiza_en_la_respuesta(self):
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano') as enviar, \
                patch.object(servicio, 'predecir_ollama') as ia:
            respuesta = self._publicar('Es excelente')
        self.assertEqual(respuesta.status_code, 302)
        comentario = Comentario.objects.get()
        enviar.assert_called_once_with(comentario.pk)
        ia.assert_not_called()
        self.assertFalse(SentimientoComentario.objects.exists())

    def test_encola_recien_despues_del_commit(self):
        self.client.force_login(self.usuario)
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano') as enviar:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.client.post(reverse('crear_comentario', args=[self.noticia.pk]), {'texto': 'Hola'})
            enviar.assert_not_called()
            for callback in callbacks:
                callback()
        enviar.assert_called_once()

    def test_publicacion_completa_con_ia_muestra_sentimiento_y_categoria(self):
        Categoria.objects.create(nombre_categoria='Economía')
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano',
                          side_effect=analisis_automatico.procesar_comentario), \
                patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia()):
            self._publicar('Subió la yerba otra vez, excelente para los productores')
        obj = SentimientoComentario.objects.get()
        self.assertEqual((obj.metodo, obj.modelo, obj.categoria.nombre_categoria), (IA, 'ollama:mock', 'Economía'))
        # La etiqueta se muestra una vez que la moderación publica el comentario.
        Comentario.objects.update(estado=Comentario.Estado.PUBLICADO)
        pagina = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertContains(pagina, 'comment-sentiment--positivo')
        self.assertContains(pagina, '· Economía')
        self.assertNotContains(pagina, 'Análisis automático pendiente')

    def test_sin_procesar_se_muestra_pendiente(self):
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano'):
            self._publicar('Todavía sin analizar')
        Comentario.objects.update(estado=Comentario.Estado.PUBLICADO)
        pagina = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertContains(pagina, 'Análisis automático pendiente')
        self.assertNotContains(pagina, 'comment-sentiment--')

    def test_edicion_reanaliza_sin_duplicar(self):
        procesar = analisis_automatico.procesar_comentario
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano', side_effect=procesar), \
                patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia(0.7)):
            self._publicar('Es excelente')
        comentario = Comentario.objects.get()
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano', side_effect=procesar) as enviar, \
                patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia(-0.8, 'Salud')):
            self.assertEqual(self._editar(comentario, 'Fue terrible la atención').status_code, 302)
        enviar.assert_called_once_with(comentario.pk)
        self.assertEqual(SentimientoComentario.objects.count(), 1)
        obj = SentimientoComentario.objects.get()
        self.assertEqual(obj.texto_hash, servicio.calcular_texto_hash('Fue terrible la atención'))
        self.assertEqual((obj.polaridad, obj.categoria.nombre_categoria), (-0.8, 'Salud'))

    def test_reproceso_sin_cambios_de_texto_se_omite(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia()) as ia:
            self.assertEqual(analisis_automatico.procesar_comentario(comentario.pk), 'creado')
            self.assertEqual(analisis_automatico.procesar_comentario(comentario.pk), 'omitido')
        self.assertEqual(ia.call_count, 1)

    def test_formulario_invalido_no_encola(self):
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano') as enviar:
            self.assertEqual(self._publicar('').status_code, 400)
        enviar.assert_not_called()

    def test_desactivado_por_entorno(self):
        with patch.dict(os.environ, {'SENTIMIENTO_COMENTARIOS_AUTOMATICO': '0'}), \
                patch.object(analisis_automatico, '_enviar_a_segundo_plano') as enviar:
            self.assertEqual(self._publicar('Hola').status_code, 302)
            self.assertFalse(analisis_automatico.programar_analisis(Comentario.objects.get().pk))
        enviar.assert_not_called()

    def test_metodo_lexicon_por_entorno_no_llama_a_ollama(self):
        comentario = self._comentario()
        with patch.dict(os.environ, {'SENTIMIENTO_COMENTARIOS_METODO': 'lexicon'}), \
                patch.object(servicio, 'predecir_ollama') as ia:
            analisis_automatico.procesar_comentario(comentario.pk)
        ia.assert_not_called()
        self.assertEqual(SentimientoComentario.objects.get().codigo_error, '')

    def test_error_al_encolar_no_rompe_la_publicacion(self):
        with patch.object(analisis_automatico, '_enviar_a_segundo_plano', side_effect=RuntimeError('cola rota')):
            respuesta = self._publicar('Hola')
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Comentario.objects.count(), 1)


class FallosYRecuperacionTests(BaseComentarios):
    def test_ollama_caido_deja_lexico_marcado_y_el_comando_lo_recupera(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama',
                          side_effect=servicio.SentimientoNoDisponible('ollama_sin_respuesta')):
            analisis_automatico.procesar_comentario(comentario.pk)
        obj = SentimientoComentario.objects.get()
        self.assertEqual((obj.estado, obj.metodo, obj.codigo_error),
                         (SentimientoComentario.Estado.PROCESADO, LEXICON, 'ia:ollama_sin_respuesta'))

        # Con Ollama de vuelta, el respaldo reintenta sólo ese comentario con IA.
        out = StringIO()
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia()):
            call_command('analizar_sentimiento_comentarios', metodo='ia', stdout=out)
        self.assertIn('procesados=0 actualizados=1 omitidos=0 fallidos=0', out.getvalue())
        obj.refresh_from_db()
        self.assertEqual((obj.metodo, obj.codigo_error, obj.categoria.nombre_categoria), (IA, '', 'Economía'))

    def test_respaldo_con_lexico_no_reprocesa_fallbacks_de_ia(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama',
                          side_effect=servicio.SentimientoNoDisponible('ollama_sin_respuesta')):
            analisis_automatico.procesar_comentario(comentario.pk)
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', stdout=out)
        self.assertIn('procesados=0 actualizados=0 omitidos=0 fallidos=0', out.getvalue())

    def test_fallback_editado_se_procesa_una_sola_vez(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama',
                          side_effect=servicio.SentimientoNoDisponible('ollama_sin_respuesta')):
            analisis_automatico.procesar_comentario(comentario.pk)
        # Queda desactualizado y además pendiente de IA: dos fuentes del comando.
        Comentario.objects.filter(pk=comentario.pk).update(texto='Fue terrible')
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia(-0.5)) as ia:
            call_command('analizar_sentimiento_comentarios', metodo='ia', stdout=StringIO())
        self.assertEqual(ia.call_count, 1)

    def test_excepcion_inesperada_queda_en_error_y_se_recupera(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama', side_effect=KeyError('inesperado')):
            self.assertEqual(analisis_automatico.procesar_comentario(comentario.pk), 'error')
        obj = SentimientoComentario.objects.get()
        self.assertEqual((obj.estado, obj.codigo_error), (SentimientoComentario.Estado.ERROR, 'excepcion_inesperada'))
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', stdout=out)
        self.assertIn('actualizados=1', out.getvalue())
        obj.refresh_from_db()
        self.assertEqual(obj.estado, SentimientoComentario.Estado.PROCESADO)

    def test_excepcion_inesperada_conserva_analisis_vigente(self):
        comentario = self._comentario()
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia()):
            analisis_automatico.procesar_comentario(comentario.pk)
        with patch.object(analisis_automatico, 'analizar_comentario', side_effect=KeyError('inesperado')):
            analisis_automatico.procesar_comentario(comentario.pk)
        obj = SentimientoComentario.objects.get()
        self.assertEqual((obj.estado, obj.metodo), (SentimientoComentario.Estado.PROCESADO, IA))

    def test_comentario_borrado_antes_de_procesar(self):
        comentario = self._comentario()
        Comentario.objects.filter(pk=comentario.pk).delete()
        self.assertIsNone(analisis_automatico.procesar_comentario(comentario.pk))
        self.assertFalse(SentimientoComentario.objects.exists())


class ColaEnSegundoPlanoTests(TestCase):
    """Mecánica de la cola y del hilo trabajador, sin acceso a la base."""

    def _aislar(self):
        hilo_vivo = MagicMock()
        hilo_vivo.is_alive.return_value = True
        return (patch.object(analisis_automatico, '_cola', queue.Queue()),
                patch.object(analisis_automatico, '_en_cola', set()),
                patch.object(analisis_automatico, '_hilo', hilo_vivo))

    def test_no_encola_dos_veces_el_mismo_comentario_mientras_espera(self):
        cola, en_cola, hilo = self._aislar()
        with cola, en_cola, hilo:
            self.assertTrue(analisis_automatico._enviar_a_segundo_plano(7))
            self.assertFalse(analisis_automatico._enviar_a_segundo_plano(7))
            self.assertTrue(analisis_automatico._enviar_a_segundo_plano(8))
            self.assertEqual(analisis_automatico._cola.qsize(), 2)

    def test_hilo_trabajador_procesa_en_orden_y_libera_para_nuevas_ediciones(self):
        vistos, listo = [], threading.Event()

        def registrar(comentario_id):
            vistos.append(comentario_id)
            if len(vistos) == 4:
                listo.set()

        cola, en_cola, _ = self._aislar()
        with cola, en_cola, patch.object(analisis_automatico, '_hilo', None), \
                patch.object(analisis_automatico, 'procesar_comentario', side_effect=registrar), \
                patch.object(analisis_automatico, 'close_old_connections'):
            for comentario_id in (1, 2, 3):
                analisis_automatico._enviar_a_segundo_plano(comentario_id)
            analisis_automatico._cola.join()
            # Ya procesado: una edición posterior vuelve a encolarse.
            self.assertTrue(analisis_automatico._enviar_a_segundo_plano(1))
            self.assertTrue(listo.wait(5))
            hilo = analisis_automatico._hilo
        self.assertEqual(vistos, [1, 2, 3, 1])
        self.assertTrue(hilo.daemon)
