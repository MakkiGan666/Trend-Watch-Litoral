"""Regresiones para fichas RSS que no almacenan el artículo completo."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import importlib
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, migrations, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from google.genai import types

from core.models import (AliasURLPublicacion, Etiqueta, ProcesamientoIAMultifuente,
                         Publicacion, PublicacionEtiqueta, RegistroDatos, Sentimiento)
from core.services import gemini_multifuente
from core.services.clasificacion import clasificar_lote
from core.services.clasificacion_departamentos import consultar_ia
from core.services.etiquetas import sincronizar_etiquetas
from core.services.gemini_cliente import GeminiCliente
from core.forms import PublicacionForm
from core.views import _analizar_y_guardar_sentimiento


class MigracionCuerpoCompletoTests(SimpleTestCase):
    def test_migracion_es_aditiva_default_compatible_y_sin_operacion_de_datos(self):
        migration = importlib.import_module(
            'core.migrations.0023_publicacion_contenido_completo',
        ).Migration
        self.assertEqual(migration.dependencies, [('core', '0022_merge_multifuente_sentimiento')])
        self.assertEqual(
            [type(op) for op in migration.operations],
            [migrations.AddField, migrations.AlterField, migrations.AddConstraint],
        )
        self.assertFalse(any(isinstance(op, migrations.RunPython) for op in migration.operations))
        campo = next(op for op in migration.operations
                     if isinstance(op, migrations.AddField) and op.name == 'contenido_completo')
        self.assertIs(campo.field.default, True)
        self.assertEqual(campo.field.null, False)


class ValidacionCuerpoPublicacionTests(TestCase):
    def test_articulo_completo_requiere_texto_y_ficha_rss_debe_tener_cuerpo_vacio(self):
        with self.assertRaises(ValidationError):
            Publicacion.objects.create(hash_origen='h53-completo-vacio', titulo='Artículo')
        with self.assertRaises(ValidationError):
            Publicacion.objects.create(
                hash_origen='h53-ficha-con-texto', titulo='Ficha', contenido='texto',
                contenido_completo=False,
            )

        ficha = Publicacion.objects.create(
            hash_origen='h53-ficha', fuente='Noticias del 6', titulo='Titular RSS',
            contenido='', contenido_completo=False,
        )
        self.assertFalse(ficha.tiene_cuerpo_completo)
        with self.assertRaises(ValidationError):
            ficha.full_clean()

    def test_default_completo_preserva_registros_historicos_y_no_reescribe_identidad(self):
        antigua = Publicacion.objects.create(
            hash_origen='h53-historica', titulo='Histórica', contenido='cuerpo histórico',
        )
        identidad = (antigua.pk, antigua.hash_origen, antigua.contenido)
        # Representa una fila histórica excepcionalmente vacía anterior a H5.3.
        Publicacion.objects.filter(pk=antigua.pk).update(contenido='')
        antigua.refresh_from_db()
        antigua.save(update_fields=['titulo'])
        antigua.refresh_from_db()
        self.assertTrue(antigua.contenido_completo)
        self.assertEqual((antigua.pk, antigua.hash_origen), identidad[:2])
        self.assertEqual(antigua.contenido, '')

    def test_formulario_conserva_validacion_completa_y_admite_editar_ficha_vacia(self):
        completa = Publicacion.objects.create(
            hash_origen='h53-form-completa', titulo='Artículo', contenido='Cuerpo',
        )
        ficha = Publicacion.objects.create(
            hash_origen='h53-form-ficha', titulo='Titular', fuente='Noticias del 6',
            contenido='', contenido_completo=False,
        )
        def formulario(publicacion):
            return PublicacionForm(data={
                'titulo': 'Título editado', 'fuente': publicacion.fuente, 'contenido': '',
                'url': publicacion.url, 'imagen_url': '',
            }, instance=publicacion)
        self.assertFalse(formulario(completa).is_valid())
        ficha_form = formulario(ficha)
        self.assertTrue(ficha_form.is_valid(), ficha_form.errors)

    def test_constraint_impide_ficha_con_cuerpo_a_nivel_de_base(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-check', titulo='Ficha', contenido='', contenido_completo=False,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Publicacion.objects.filter(pk=ficha.pk).update(contenido='no permitido')

    def test_ficha_no_genera_etiquetas_y_clasificacion_no_infiere_con_titulo(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-sin-analisis', fuente='Noticias del 6',
            titulo='Hospital de San Pedro inaugura una nueva sala', contenido='',
            contenido_completo=False,
        )
        self.assertFalse(PublicacionEtiqueta.objects.filter(publicacion=ficha).exists())
        self.assertEqual(sincronizar_etiquetas(ficha), 0)
        self.assertFalse(Etiqueta.objects.exists())
        with patch('core.services.clasificacion._clasificar_con_ia') as clasificador_ia:
            resultado = clasificar_lote([{
                'titulo': ficha.titulo, 'contenido': '', 'contenido_completo': False,
            }], usar_ia=True, fuente_id='noticias_del_6')
        self.assertEqual(resultado, [{
            'categoria': None, 'departamento': None,
            'metodo': 'omitida_sin_cuerpo', 'confirmada': False,
        }])
        clasificador_ia.assert_not_called()

    def test_al_convertir_articulo_en_ficha_se_quitan_etiquetas_generadas(self):
        publicacion = Publicacion.objects.create(
            hash_origen='h53-transicion', fuente='Noticias del 6',
            titulo='Hospital San Pedro inaugura nueva sala', contenido='Cuerpo completo con detalles.',
        )
        self.assertTrue(PublicacionEtiqueta.objects.filter(publicacion=publicacion).exists())
        publicacion.contenido = ''
        publicacion.contenido_completo = False
        publicacion.save(update_fields=['contenido', 'contenido_completo'])
        self.assertFalse(PublicacionEtiqueta.objects.filter(publicacion=publicacion).exists())

    def test_comando_de_imagenes_omite_fichas_sin_intentar_descargar(self):
        Publicacion.objects.create(
            hash_origen='h53-imagen', fuente='El Territorio (Policiales)',
            titulo='Ficha policial', contenido='', contenido_completo=False,
            url='https://www.elterritorio.com.ar/nota',
        )
        with patch('core.management.commands.recuperar_imagenes.descargar') as descargar:
            call_command('recuperar_imagenes', limite=1)
        descargar.assert_not_called()

    def test_ficha_no_admite_sentimiento_ni_analisis_local(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-sin-sentimiento', fuente='Noticias del 6',
            titulo='Titular', contenido='', contenido_completo=False,
        )
        with self.assertRaises(ValueError):
            _analizar_y_guardar_sentimiento(ficha)
        with self.assertRaises(ValidationError):
            Sentimiento.objects.create(id_publicacion_api=ficha, polaridad=0, confianza=1)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=ficha).exists())

    def test_editar_titulo_de_ficha_no_dispara_sentimiento(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-edicion', fuente='Noticias del 6', titulo='Titular',
            contenido='', contenido_completo=False,
        )
        usuario = get_user_model().objects.create_superuser('h53_editor', 'h53@example.invalid', 'test-only')
        from django.test import Client
        cliente = Client()
        cliente.force_login(usuario)
        respuesta = cliente.post(reverse('editar_publicacion_web', args=[ficha.pk]), {
            'titulo': 'Titular corregido', 'fuente': ficha.fuente, 'contenido': '',
            'url': ficha.url, 'imagen_url': '', 'categorias': [],
        })
        self.assertEqual(respuesta.status_code, 302)
        ficha.refresh_from_db()
        self.assertEqual(ficha.titulo, 'Titular corregido')
        self.assertFalse(ficha.contenido_completo)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=ficha).exists())

    def test_consultar_departamentos_rechaza_ficha_antes_de_consultar_gemini(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-sin-departamento', fuente='Noticias del 6',
            titulo='Titular', contenido='', contenido_completo=False,
        )
        cliente = Mock()
        with self.assertRaises(ValueError):
            consultar_ia([ficha], cliente=cliente)
        cliente.client.models.generate_content.assert_not_called()

    def test_comando_de_departamentos_filtra_fichas_antes_del_limite(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-limite', fuente='Noticias del 6', titulo='Titular',
            contenido='', contenido_completo=False,
        )
        salida = __import__('io').StringIO()
        call_command('revisar_departamentos', '--sin-ia', '--limite=1', stdout=salida)
        self.assertIn('Seleccionadas: 0.', salida.getvalue())
        ficha.refresh_from_db()
        self.assertEqual(ficha.departamento, '')


class ExclusionesColaMultifuenteTests(TransactionTestCase):
    def test_ficha_no_consumida_ni_enviada_por_cola_h32(self):
        fuente_id = 'noticias_del_6'
        fuente_nombre = 'Noticias del 6'
        autorizacion = override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=(fuente_id,))
        autorizacion.enable()
        self.addCleanup(autorizacion.disable)
        registro = RegistroDatos.objects.create(
            fuentes_api='RSS multifuente', fecha_ejecucion=timezone.now(),
            estado='EXITO', lenguaje='es',
        )
        ficha = Publicacion.objects.create(
            hash_origen='h53-cola', fuente=fuente_nombre, titulo='Titular', contenido='',
            contenido_completo=False, id_registro=registro, url='https://noticiasdel6.com/item',
        )
        AliasURLPublicacion.objects.create(
            publicacion=ficha, fuente=fuente_id, url_normalizada=ficha.url,
        )
        trabajo = ProcesamientoIAMultifuente.objects.create(publicacion=ficha)
        sdk = Mock()
        cliente = SimpleNamespace(
            client=sdk,
            types=SimpleNamespace(
                GenerateContentConfig=lambda **kw: kw,
                HttpOptions=lambda **kw: kw,
                HttpRetryOptions=lambda **kw: kw,
            ),
            model_name='test-model',
        )
        recibo = {'registro_id': registro.pk, 'noticias': [{
            'estado': 'GUARDADA', 'publicacion_id': ficha.pk, 'hash_origen': ficha.hash_origen,
        }]}
        resultado = gemini_multifuente.procesar_nuevas(
            recibo, cliente=cliente, pausa_segundos=0,
        )
        trabajo.refresh_from_db()
        self.assertEqual(resultado['llamadas'], 0)
        self.assertEqual(resultado['omitidas'], 1)
        self.assertEqual(trabajo.estado, 'PENDIENTE')
        self.assertIsNone(trabajo.token_intento)
        sdk.models.generate_content.assert_not_called()

    def test_procesador_global_excluye_fichas_antes_del_lote_y_del_envio(self):
        ficha = Publicacion.objects.create(
            hash_origen='h53-global', fuente='Noticias del 6', titulo='Titular',
            contenido='', contenido_completo=False,
        )
        completa = Publicacion.objects.create(
            hash_origen='h53-global-completa', fuente='El Territorio',
            titulo='Artículo completo', contenido='Cuerpo verificable del artículo.',
        )
        sdk = Mock()
        sdk.models.generate_content.return_value.text = json.dumps({
            'polaridad': 0, 'confianza': 0.8, 'localidades': [],
        })
        cliente = GeminiCliente(api_key='synthetic-test-key')
        cliente.client = sdk
        cliente.types = types
        with patch('core.services.gemini_cliente.time.sleep'):
            resultado = cliente.procesar_pendientes(batch_size=1)
        self.assertEqual(resultado['seleccionadas'], 1)
        prompt = sdk.models.generate_content.call_args.kwargs['contents']
        self.assertIn('Artículo completo', prompt)
        self.assertNotIn('Titular', prompt)
        ficha.refresh_from_db()
        self.assertFalse(ficha.procesado_ia)
        completa.refresh_from_db()
        self.assertTrue(completa.procesado_ia)
