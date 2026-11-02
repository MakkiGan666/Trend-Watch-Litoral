"""Pruebas de la etapa 1: análisis automático de sentimiento sobre comentarios.

Cubren el modelo, el servicio, el comando idempotente, la integración visual y
la separación respecto del sentimiento de noticias y de las valoraciones manuales.
Ollama se mockea; estas pruebas no requieren red ni descargas.
"""
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Comentario,
    Publicacion,
    SentimientoComentario,
    Sentimiento,
    ValoracionPublicacion,
)
from core.services import sentimiento_comentarios as servicio


class ModeloSentimientoComentarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('prueba', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='n-sentcom-1', titulo='t', contenido='c')
        cls.comentario = Comentario.objects.create(
            publicacion=cls.noticia, autor=cls.usuario, texto='Comentario de prueba',
        )

    def _crear(self, **cambios):
        datos = {
            'comentario': self.comentario,
            'polaridad': 0.5, 'confianza': 0.8,
            'metodo': SentimientoComentario.Metodo.LEXICON, 'modelo': 'lexicon_v1',
            'texto_hash': 'x' * 64,
            'estado': SentimientoComentario.Estado.PROCESADO,
        }
        datos.update(cambios)
        return SentimientoComentario.objects.create(**datos)

    def test_etiqueta_umbral_neutral(self):
        self.assertEqual(self._crear(polaridad=0.3).etiqueta, 'positivo')
        self.assertEqual(SentimientoComentario(polaridad=0.0,
            estado=SentimientoComentario.Estado.PROCESADO).etiqueta, 'neutral')
        self.assertEqual(SentimientoComentario(polaridad=-0.4,
            estado=SentimientoComentario.Estado.PROCESADO).etiqueta, 'negativo')
        # Dentro de la zona neutra: una señal débil no se declara positiva.
        for pol in (0.04, -0.04):
            self.assertEqual(SentimientoComentario(polaridad=pol,
                estado=SentimientoComentario.Estado.PROCESADO).etiqueta, 'neutral')

    def test_estado_error_no_tiene_etiqueta(self):
        obj = SentimientoComentario(polaridad=None, confianza=None,
                                    estado=SentimientoComentario.Estado.ERROR,
                                    codigo_error='x')
        self.assertIsNone(obj.etiqueta)

    def test_oneto_one_rechaza_duplicado(self):
        self._crear()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._crear()

    def test_constraint_polaridad_fuera_de_rango(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._crear(polaridad=1.2)

    def test_procesado_requiere_polaridad_y_confianza(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._crear(polaridad=None, confianza=None,
                        estado=SentimientoComentario.Estado.PROCESADO)

    def test_cascade_al_borrar_comentario(self):
        self._crear()
        self.comentario.delete()
        self.assertFalse(SentimientoComentario.objects.exists())


class ServicioSentimientoComentariosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('autor_sent', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='n-sentcom-2', titulo='t', contenido='c')

    def _comentario(self, texto):
        return Comentario.objects.create(publicacion=self.noticia, autor=self.usuario, texto=texto)

    def test_hash_cambia_con_el_texto(self):
        self.assertNotEqual(
            servicio.calcular_texto_hash('bueno'), servicio.calcular_texto_hash('malo'),
        )
        # El strip evita falsos negativos por espacios al final.
        self.assertEqual(
            servicio.calcular_texto_hash('bueno'), servicio.calcular_texto_hash('  bueno  '),
        )

    def test_predecir_lexicon_es_determinista(self):
        pos = servicio.predecir_lexicon('Este servicio es excelente e impecable')
        neg = servicio.predecir_lexicon('Fue terrible y horrible, muchos problemas')
        neu = servicio.predecir_lexicon('')
        self.assertGreater(pos.polaridad, 0)
        self.assertLess(neg.polaridad, 0)
        self.assertEqual(neu.polaridad, 0.0)
        self.assertEqual(pos.metodo, SentimientoComentario.Metodo.LEXICON)
        self.assertEqual(pos.modelo, servicio.VERSION_LEXICON)
        # Idempotencia: la misma entrada da la misma salida.
        self.assertEqual(pos, servicio.predecir_lexicon('Este servicio es excelente e impecable'))

    def test_analizar_comentario_crea_actualiza_y_omite(self):
        comentario = self._comentario('Es excelente')
        obj, accion = servicio.analizar_comentario(comentario)
        self.assertEqual(accion, 'creado')
        self.assertEqual(obj.estado, SentimientoComentario.Estado.PROCESADO)
        self.assertEqual(obj.metodo, SentimientoComentario.Metodo.LEXICON)
        self.assertEqual(obj.texto_hash, servicio.calcular_texto_hash('Es excelente'))

        # Mismo texto: se omite sin tocar la base.
        comentario.refresh_from_db()
        obj2, accion2 = servicio.analizar_comentario(comentario)
        self.assertEqual(accion2, 'omitido')
        self.assertEqual(obj2.pk, obj.pk)

        # Texto editado: el hash cambia y el registro se actualiza.
        comentario.texto = 'Fue terrible'
        comentario.save(update_fields=['texto'])
        comentario.refresh_from_db()
        obj3, accion3 = servicio.analizar_comentario(comentario)
        self.assertEqual(accion3, 'actualizado')
        self.assertEqual(obj3.pk, obj.pk)
        self.assertLess(obj3.polaridad, 0)
        self.assertEqual(obj3.texto_hash, servicio.calcular_texto_hash('Fue terrible'))

    def test_ia_fallida_cae_a_lexicon(self):
        comentario = self._comentario('Es excelente')
        with patch.object(servicio, 'predecir_ollama',
                          side_effect=servicio.SentimientoNoDisponible('ollama_sin_respuesta')):
            obj, accion = servicio.analizar_comentario(comentario, usar_ia=True)
        self.assertEqual(accion, 'creado')
        # Al caer al método léxico, el registro queda procesado con metodo='lexicon'.
        self.assertEqual(obj.estado, SentimientoComentario.Estado.PROCESADO)
        self.assertEqual(obj.metodo, SentimientoComentario.Metodo.LEXICON)

    def test_ia_exitosa_registra_metodo_ia(self):
        comentario = self._comentario('Es excelente')
        prediccion_ia = servicio.Prediccion(
            polaridad=0.6, confianza=0.9,
            metodo=SentimientoComentario.Metodo.IA, modelo='ollama:mock',
        )
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia):
            obj, _ = servicio.analizar_comentario(comentario, usar_ia=True)
        self.assertEqual(obj.metodo, SentimientoComentario.Metodo.IA)
        self.assertEqual(obj.modelo, 'ollama:mock')
        self.assertAlmostEqual(obj.polaridad, 0.6)

    def test_predecir_ollama_valida_la_respuesta(self):
        # Formato correcto: devuelve una Prediccion con metodo IA.
        cliente = MagicMock()
        cliente.post.return_value.raise_for_status = lambda: None
        cliente.post.return_value.json.return_value = {
            'response': '{"polaridad": 0.4, "confianza": 0.9}',
        }
        pred = servicio.predecir_ollama('Buen comentario', cliente_http=cliente)
        self.assertEqual(pred.metodo, SentimientoComentario.Metodo.IA)
        self.assertAlmostEqual(pred.polaridad, 0.4)
        self.assertAlmostEqual(pred.confianza, 0.9)

        # JSON inválido como respuesta: se traduce a SentimientoNoDisponible.
        cliente.post.return_value.json.return_value = {'response': 'no es json'}
        with self.assertRaises(servicio.SentimientoNoDisponible) as ctx:
            servicio.predecir_ollama('x', cliente_http=cliente)
        self.assertEqual(ctx.exception.codigo, 'respuesta_invalida')

        # Fuera de rango: también se descarta.
        cliente.post.return_value.json.return_value = {
            'response': '{"polaridad": 2.0, "confianza": 0.5}',
        }
        with self.assertRaises(servicio.SentimientoNoDisponible) as ctx:
            servicio.predecir_ollama('x', cliente_http=cliente)
        self.assertEqual(ctx.exception.codigo, 'respuesta_fuera_de_rango')

    def test_registrar_error_persiste_sin_polaridad(self):
        comentario = self._comentario('x')
        obj = servicio.registrar_error_analisis(comentario, 'cualquier_codigo')
        self.assertEqual(obj.estado, SentimientoComentario.Estado.ERROR)
        self.assertIsNone(obj.polaridad)
        self.assertIsNone(obj.confianza)
        self.assertEqual(obj.codigo_error, 'cualquier_codigo')


class ComandoAnalizarSentimientoComentariosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('cmd_autor', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='n-sentcom-3', titulo='t', contenido='c')
        for i, texto in enumerate(['Es excelente', 'Fue terrible', 'Sin opinión fuerte']):
            Comentario.objects.create(publicacion=cls.noticia, autor=cls.usuario, texto=texto)

    def test_procesa_pendientes_y_es_idempotente(self):
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', stdout=out)
        self.assertIn('procesados=3', out.getvalue())
        self.assertEqual(SentimientoComentario.objects.count(), 3)
        timestamps = list(SentimientoComentario.objects.values_list('fecha_actualizacion', flat=True))

        # Segunda corrida sin cambios: ningún comentario entra como candidato,
        # el conteo se queda en cero y las filas existentes no se tocan.
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', stdout=out)
        self.assertIn('procesados=0 actualizados=0 omitidos=0 fallidos=0', out.getvalue())
        self.assertEqual(SentimientoComentario.objects.count(), 3)
        self.assertEqual(
            list(SentimientoComentario.objects.values_list('fecha_actualizacion', flat=True)),
            timestamps,
        )

    def test_detecta_texto_editado_y_reprocesa(self):
        call_command('analizar_sentimiento_comentarios', stdout=StringIO())
        comentario = Comentario.objects.first()
        comentario.texto = 'Ahora es terrible'
        comentario.save(update_fields=['texto'])
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', stdout=out)
        # Sólo el editado debe entrar como candidato, con hash desactualizado.
        self.assertIn('actualizados=1', out.getvalue())
        self.assertIn('procesados=0', out.getvalue())
        self.assertIn('fallidos=0', out.getvalue())

    def test_reanalizar_fuerza_a_todos(self):
        call_command('analizar_sentimiento_comentarios', stdout=StringIO())
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', '--reanalizar', stdout=out)
        # Al forzar, los procesados vuelven a escribirse (como 'actualizado').
        self.assertIn('actualizados=3', out.getvalue())

    def test_dry_run_no_escribe(self):
        out = StringIO()
        call_command('analizar_sentimiento_comentarios', '--dry-run', stdout=out)
        self.assertFalse(SentimientoComentario.objects.exists())
        self.assertIn('[dry-run]', out.getvalue())

    def test_metodo_ia_con_ollama_mockeado(self):
        prediccion_ia = servicio.Prediccion(
            polaridad=0.3, confianza=0.85,
            metodo=SentimientoComentario.Metodo.IA, modelo='ollama:mock',
        )
        with patch.object(servicio, 'predecir_ollama', return_value=prediccion_ia):
            call_command('analizar_sentimiento_comentarios', '--metodo', 'ia', stdout=StringIO())
        metodos = set(SentimientoComentario.objects.values_list('metodo', flat=True))
        self.assertEqual(metodos, {SentimientoComentario.Metodo.IA})

    def test_errores_de_ia_no_detienen_el_lote(self):
        # El llamador pide IA pero cada llamada falla; el lote completo sigue con léxico.
        with patch.object(servicio, 'predecir_ollama',
                          side_effect=servicio.SentimientoNoDisponible('ollama_sin_respuesta')):
            call_command('analizar_sentimiento_comentarios', '--metodo', 'ia', stdout=StringIO())
        metodos = set(SentimientoComentario.objects.values_list('metodo', flat=True))
        self.assertEqual(metodos, {SentimientoComentario.Metodo.LEXICON})


class IntegracionVisualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('visor', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='n-sentcom-4', titulo='t', contenido='c')

    def test_sin_analisis_no_se_muestra_badge(self):
        Comentario.objects.create(publicacion=self.noticia, autor=self.usuario, texto='Sin análisis todavía')
        response = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'comment-sentiment')

    def test_con_analisis_se_muestra_badge_y_aclaracion(self):
        comentario = Comentario.objects.create(
            publicacion=self.noticia, autor=self.usuario, texto='Es excelente', estado=Comentario.Estado.PUBLICADO,
        )
        servicio.analizar_comentario(comentario)
        response = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertContains(response, 'comment-sentiment--positivo')
        self.assertContains(response, 'Predicción automática')
        self.assertContains(response, 'análisis automático')

    def test_etiqueta_no_censura_al_comentario(self):
        comentario = Comentario.objects.create(
            publicacion=self.noticia, autor=self.usuario, texto='Fue terrible', estado=Comentario.Estado.PUBLICADO,
        )
        servicio.analizar_comentario(comentario)
        response = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertContains(response, 'Fue terrible')
        self.assertContains(response, 'comment-sentiment--negativo')


class SeparacionFuentesTests(TestCase):
    """Garantiza que el sentimiento de comentarios no comparte almacenamiento con el de noticias."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('separador', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='n-sentcom-5', titulo='t', contenido='c')
        cls.comentario = Comentario.objects.create(
            publicacion=cls.noticia, autor=cls.usuario, texto='Es excelente',
        )

    def test_analisis_de_comentario_no_toca_sentimiento_de_noticia(self):
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=self.noticia).exists())
        servicio.analizar_comentario(self.comentario)
        # Se guardó una fila en la tabla propia; la de noticias sigue intacta.
        self.assertEqual(SentimientoComentario.objects.count(), 1)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=self.noticia).exists())

    def test_voto_manual_no_se_confunde_con_prediccion_automatica(self):
        ValoracionPublicacion.objects.create(
            publicacion=self.noticia, usuario=self.usuario,
            sentimiento=ValoracionPublicacion.Sentimiento.POSITIVO,
        )
        servicio.analizar_comentario(self.comentario)
        # Son objetos distintos, viven en modelos distintos y no se derivan uno del otro.
        obj = SentimientoComentario.objects.get()
        self.assertEqual(obj.comentario_id, self.comentario.pk)
        self.assertEqual(ValoracionPublicacion.objects.count(), 1)


class RegresionesAuditoriaPR31Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aud31', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='aud31', titulo='t', contenido='c')

    def _comentario(self, texto='Es excelente'):
        return Comentario.objects.create(publicacion=self.noticia, autor=self.usuario, texto=texto,
                                        estado=Comentario.Estado.PUBLICADO)

    def _lote_mixto(self):
        nuevo = self._comentario()
        error = self._comentario()
        servicio.registrar_error_analisis(error, 'prueba')
        editado = self._comentario()
        servicio.analizar_comentario(editado)
        Comentario.objects.filter(pk=editado.pk).update(texto='Fue terrible')
        vigente = self._comentario()
        servicio.analizar_comentario(vigente)
        return [nuevo.pk, error.pk, editado.pk, vigente.pk]

    def test_editar_por_http_oculta_etiqueta_hasta_reanalizar(self):
        comentario = self._comentario()
        servicio.analizar_comentario(comentario)
        self.client.force_login(self.usuario)
        respuesta = self.client.post(reverse('editar_comentario', args=[comentario.pk]),
                                     {'texto': 'Fue terrible'})
        self.assertEqual(respuesta.status_code, 302)
        url = reverse('noticia', args=[self.noticia.pk])
        respuesta = self.client.get(url)
        self.assertContains(respuesta, 'Fue terrible')
        self.assertNotContains(respuesta, 'comment-sentiment--')
        # Se conserva el resultado anterior, pero no se presenta como vigente.
        self.assertEqual(SentimientoComentario.objects.get().etiqueta, 'positivo')
        comentario.refresh_from_db()
        servicio.analizar_comentario(comentario)
        self.assertNotContains(self.client.get(url), 'comment-sentiment--negativo')

    def test_editar_fuera_del_formulario_tambien_oculta_etiqueta(self):
        comentario = self._comentario()
        servicio.analizar_comentario(comentario)
        Comentario.objects.filter(pk=comentario.pk).update(texto='Fue terrible')
        comentario = Comentario.objects.select_related('sentimiento').get(pk=comentario.pk)
        with self.assertNumQueries(0):
            self.assertIsNone(comentario.sentimiento_vigente)

    def test_vigente_precargado_no_agrega_consultas(self):
        comentario = self._comentario()
        servicio.analizar_comentario(comentario)
        comentario = Comentario.objects.select_related('sentimiento').get(pk=comentario.pk)
        with self.assertNumQueries(0):
            self.assertEqual(comentario.sentimiento_vigente.etiqueta, 'positivo')

    def test_sin_analisis_no_expone_comentario_de_plantilla(self):
        from django.template.loader import render_to_string
        html = render_to_string('partials/_sentimiento_comentario.html',
                                {'comentario': self._comentario()})
        self.assertEqual(html.strip(), '')

    def test_reanalizar_lote_mixto_una_inferencia_por_comentario(self):
        pks = self._lote_mixto()
        out = StringIO()
        with patch.object(servicio, 'predecir_ollama', return_value=servicio.Prediccion(
                -0.7, 0.8, SentimientoComentario.Metodo.IA, 'ollama:mock')) as inferir:
            call_command('analizar_sentimiento_comentarios', reanalizar=True,
                         metodo='ia', stdout=out)
        self.assertEqual(inferir.call_count, len(pks))
        self.assertIn('procesados=1 actualizados=3 omitidos=0 fallidos=0', out.getvalue())
        self.assertEqual(SentimientoComentario.objects.count(), len(pks))

    def test_reanalizar_limite_cuenta_comentarios_unicos(self):
        pks = self._lote_mixto()
        out = StringIO()
        with patch('core.management.commands.analizar_sentimiento_comentarios.analizar_comentario',
                   wraps=servicio.analizar_comentario) as analizar:
            call_command('analizar_sentimiento_comentarios', reanalizar=True,
                         limite=3, stdout=out)
        self.assertEqual([c.args[0].pk for c in analizar.call_args_list], pks[:3])

    def test_reanalizar_dry_run_es_unico_y_no_escribe(self):
        pks = self._lote_mixto()
        antes = list(SentimientoComentario.objects.order_by('pk').values())
        out = StringIO()
        with patch.object(servicio, 'predecir_ollama') as inferir:
            call_command('analizar_sentimiento_comentarios', reanalizar=True,
                         dry_run=True, metodo='ia', limite=0, stdout=out)
        self.assertEqual([l for l in out.getvalue().splitlines() if l.startswith('[dry-run]')],
                         [f'[dry-run] comentario #{pk}' for pk in pks])
        inferir.assert_not_called()
        self.assertEqual(list(SentimientoComentario.objects.order_by('pk').values()), antes)

    def test_modo_normal_procesa_pendientes_editados_y_omite_vigentes(self):
        self._lote_mixto()
        out = StringIO()
        with patch.object(servicio, 'predecir_lexicon', wraps=servicio.predecir_lexicon) as inferir:
            call_command('analizar_sentimiento_comentarios', stdout=out)
        self.assertEqual(inferir.call_count, 3)
        self.assertIn('procesados=1 actualizados=2 omitidos=0 fallidos=0', out.getvalue())

    def test_ollama_envoltorios_invalidos_caen_a_lexico(self):
        for envoltorio in ([], None, 'texto', 42, {}, {'response': None}, {'response': {}}):
            with self.subTest(envoltorio=envoltorio):
                comentario = self._comentario()
                cliente = MagicMock()
                cliente.post.return_value.json.return_value = envoltorio
                obj, _ = servicio.analizar_comentario(comentario, usar_ia=True, cliente_http=cliente)
                self.assertEqual(obj.estado, SentimientoComentario.Estado.PROCESADO)
                self.assertEqual(obj.metodo, SentimientoComentario.Metodo.LEXICON)
                self.assertGreater(obj.polaridad, 0)

    def test_ollama_timeout_cae_a_lexico(self):
        import httpx
        cliente = MagicMock()
        cliente.post.side_effect = httpx.ReadTimeout('timeout de prueba')
        obj, _ = servicio.analizar_comentario(self._comentario(), usar_ia=True, cliente_http=cliente)
        self.assertEqual(obj.metodo, SentimientoComentario.Metodo.LEXICON)

    def test_ollama_numeros_invalidos_se_rechazan(self):
        cliente = MagicMock()
        for raw in ('{"polaridad": true, "confianza": 0.5}',
                    '{"polaridad": 0, "confianza": NaN}',
                    '{"polaridad": 0, "confianza": 1.1}'):
            with self.subTest(raw=raw):
                cliente.post.return_value.json.return_value = {'response': raw}
                with self.assertRaises(servicio.SentimientoNoDisponible):
                    servicio.predecir_ollama('texto', cliente_http=cliente)
