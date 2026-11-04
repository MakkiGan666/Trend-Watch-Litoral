from django.test import SimpleTestCase

from .lectura_noticia import preparar_lectura


class PrepararLecturaTestCase(SimpleTestCase):
    def test_separa_entradilla_primer_parrafo_y_continuacion(self):
        lectura = preparar_lectura(
            'Una noticia breve. El segundo dato completa la entrada.\n\n'
            'Este es el segundo párrafo.\n\nEste es el tercero.'
        )

        self.assertEqual(lectura['resumen'], 'Una noticia breve. El segundo dato completa la entrada.')
        self.assertEqual(lectura['primer_parrafo'], 'Una noticia breve. El segundo dato completa la entrada.')
        self.assertEqual(lectura['resto'], 'Este es el segundo párrafo.\n\nEste es el tercero.')

    def test_un_parrafo_no_tiene_contenido_para_desplegar(self):
        lectura = preparar_lectura('Una sola explicación de la noticia.')

        self.assertEqual(lectura['primer_parrafo'], 'Una sola explicación de la noticia.')
        self.assertEqual(lectura['resto'], '')

    def test_limpia_html_y_acorta_frase_extensa_en_limite_de_palabra(self):
        lectura = preparar_lectura('<p>' + 'detalle ' * 60 + '</p>')

        self.assertNotIn('<p>', lectura['primer_parrafo'])
        self.assertLessEqual(len(lectura['resumen']), 241)
        self.assertTrue(lectura['resumen'].endswith('…'))

    def test_bloques_consecutivos_no_concatenan_palabras(self):
        lectura = preparar_lectura('<p>Primero.</p><div>Segundo.</div><h2>Tercero.</h2><ul><li>Cuarto.</li><li>Quinto.</li></ul>')
        self.assertEqual(lectura['primer_parrafo'], 'Primero.')
        self.assertEqual(lectura['resto'], 'Segundo.\n\nTercero.\n\nCuarto.\n\nQuinto.')

    def test_br_conserva_linea_y_doble_br_separa_parrafos(self):
        lectura = preparar_lectura('<p>Uno<br>Dos<br/><br />Tres</p>')
        self.assertEqual(lectura['primer_parrafo'], 'Uno\nDos')
        self.assertEqual(lectura['resto'], 'Tres')
        self.assertEqual(lectura['resumen'], 'Uno Dos')

    def test_html_inline_no_inventa_espacios_dentro_de_palabras(self):
        lectura = preparar_lectura('<p>Educa<strong>ción</strong> para <a href="https://example.invalid">todos</a>.</p>')
        self.assertEqual(lectura['primer_parrafo'], 'Educación para todos.')

    def test_html_malformado_conserva_texto_y_bloques(self):
        lectura = preparar_lectura('<DIV><p>Uno<p>Dos</DIV><p>Tres <b>sin cerrar')
        self.assertEqual(lectura['primer_parrafo'], 'Uno')
        self.assertEqual(lectura['resto'], 'Dos\n\nTres sin cerrar')

    def test_declaracion_invalida_se_conserva_como_texto_literal(self):
        lectura = preparar_lectura('<![declaracion-invalida]><p>Noticia conservada</p>')
        self.assertIn('Noticia conservada', lectura['primer_parrafo'])

    def test_entidades_se_decodifican_una_sola_vez_y_preservan_unicode(self):
        lectura = preparar_lectura('<p>Niñez &amp; salud &#x1F600;: Ω, 漢字, e\u0301 y &lt;ejemplo&gt;. &amp;lt;</p>')
        self.assertEqual(lectura['primer_parrafo'], 'Niñez & salud 😀: Ω, 漢字, e\u0301 y <ejemplo>. &lt;')

    def test_script_style_y_comentarios_no_aparecen_como_articulo(self):
        lectura = preparar_lectura('<style>body{display:none}</style><p>Noticia</p><!-- privado --><script>alert(1)</script><p>Continuación</p>')
        self.assertEqual(lectura, {'resumen': 'Noticia', 'primer_parrafo': 'Noticia', 'resto': 'Continuación'})

    def test_vacios_y_none(self):
        for texto in (None, '', ' \t\r\n', '<p> &nbsp; </p>', '<br><div></div>', '<!-- comentario -->'):
            with self.subTest(texto=texto):
                self.assertEqual(preparar_lectura(texto), {'resumen': '', 'primer_parrafo': '', 'resto': ''})

    def test_tipos_invalidos_se_rechazan_explicitamente(self):
        for valor in (0, 15, False, [], {}, b'texto'):
            with self.subTest(valor=valor), self.assertRaises(TypeError):
                preparar_lectura(valor)

    def test_cr_y_separadores_unicode_conservan_parrafos(self):
        lectura = preparar_lectura('Uno\r\rDos\r\n\r\nTres\u2029Cuatro\u2028cinco')
        self.assertEqual(lectura['primer_parrafo'], 'Uno')
        self.assertEqual(lectura['resto'], 'Dos\n\nTres\n\nCuatro\ncinco')

    def test_resumen_respeta_240_incluida_elipsis_sin_espacios(self):
        for largo in (239, 240, 241, 300):
            for simbolo in ('X', '😀', '漢'):
                texto = simbolo * largo
                with self.subTest(largo=largo, simbolo=simbolo):
                    lectura = preparar_lectura(texto)
                    self.assertLessEqual(len(lectura['resumen']), 240)
                    self.assertEqual(lectura['primer_parrafo'], texto)
                    self.assertEqual(lectura['resto'], '')
                    if largo > 240:
                        self.assertTrue(lectura['resumen'].endswith('…'))
                    else:
                        self.assertEqual(lectura['resumen'], texto)

    def test_resumen_recorta_en_palabra_sin_truncar_articulo(self):
        texto = 'detalle ' * 80
        lectura = preparar_lectura(texto)
        self.assertLessEqual(len(lectura['resumen']), 240)
        self.assertTrue(lectura['resumen'].endswith('detalle…'))
        self.assertEqual(lectura['primer_parrafo'], texto.strip())

    def test_comparaciones_y_signos_literales_no_se_pierden(self):
        texto = '2 < 3 y 5 > 4. Precio: $200; ¿acción? ¡Sí!'
        self.assertEqual(preparar_lectura(texto)['primer_parrafo'], texto)


from pathlib import Path
from types import SimpleNamespace
from django.template import Context, Engine
from django.test import override_settings
from django.urls import path


def _destino_prueba(request, pk=None):
    raise AssertionError('Las pruebas de plantilla no deben navegar ni escribir datos.')


urlpatterns = [
    path('', _destino_prueba, name='landing'),
    path('guardar/<int:pk>/', _destino_prueba, name='guardar_publicacion'),
    path('valorar/<int:pk>/', _destino_prueba, name='valorar_noticia'),
    path('comentar/<int:pk>/', _destino_prueba, name='crear_comentario'),
]


def renderizar_noticia_prueba(contenido):
    """Plantilla y parciales reales, marco mínimo sin fuentes ni servicios externos."""
    motor = Engine(
        dirs=[str(Path(__file__).parent / 'templates')],
        libraries={'static': 'django.templatetags.static'},
        loaders=[('django.template.loaders.locmem.Loader', {'base.html':
            '<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '{% block extra_head %}{% endblock %}</head><body>'
            '{% block content %}{% endblock %}{% block extra_js %}{% endblock %}</body></html>'}),
            'django.template.loaders.filesystem.Loader'],
    )
    contexto = {
        **preparar_lectura(contenido),
        'publicacion': SimpleNamespace(pk=1, titulo='Noticia de prueba', fuente='Fuente sintética'),
        'request': SimpleNamespace(user=SimpleNamespace(is_authenticated=True)),
        'valoraciones_opciones': [
            {'valor': 'positivo', 'etiqueta': 'Positivo', 'seleccionada': False, 'total': 0},
            {'valor': 'neutral', 'etiqueta': 'Neutral', 'seleccionada': False, 'total': 0},
        ],
        'valoraciones_total': 0,
    }
    with override_settings(ROOT_URLCONF=__name__):
        return motor.get_template('noticia.html').render(Context(contexto))


class PlantillaLecturaTestCase(SimpleTestCase):
    def test_contenido_completo_visible_sin_js_y_control_oculto(self):
        html = renderizar_noticia_prueba('<p>Primero.</p><p>Segundo.</p><p>Tercero.</p>')
        self.assertIn('<div id="news-remaining-content" data-news-more><p>Segundo.</p>', html)
        self.assertIn('<p>Tercero.</p>', html)
        self.assertIn('data-news-expand hidden', html)
        self.assertIn('aria-controls="news-remaining-content"', html)
        self.assertIn('action="/guardar/1/"', html)
        self.assertIn('action="/valorar/1/"', html)

    def test_un_solo_parrafo_y_vacio_no_tienen_boton_inutil(self):
        for texto in ('Un único párrafo.', ''):
            with self.subTest(texto=texto):
                html = renderizar_noticia_prueba(texto)
                self.assertNotIn('data-news-read-more', html)
                self.assertNotIn('data-news-more', html)
                if not texto:
                    self.assertIn('El contenido de esta noticia todavía no está disponible.', html)

    def test_texto_decodificado_sigue_escapado_en_resumen_y_cuerpo(self):
        html = renderizar_noticia_prueba(
            '&lt;img src=x onerror=alert(1)&gt;\n\n'
            '&lt;script&gt;alert(2)&lt;/script&gt;<img src=x onerror=alert(3)>'
        )
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertIn('&lt;script&gt;alert(2)&lt;/script&gt;', html)
        self.assertNotIn('alert(3)', html)

    def test_fallback_de_html_invalido_no_introduce_marcas_activas(self):
        html = renderizar_noticia_prueba('<![invalida]><img src=x onerror=alert(4)>Texto')
        self.assertNotIn('<img src=x', html)
        self.assertIn('Texto', html)
