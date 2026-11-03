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
