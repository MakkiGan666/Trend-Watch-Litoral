"""Regresión del registro y conservación del sentimiento local, sin servicios externos."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, SimpleTestCase
from django.urls import reverse


class RegistroCompatibilidadLocalTests(TestCase):
    datos = {'username': 'registro-local', 'email': 'registro@example.invalid',
             'password': 'Sintetica-9b#Rio2026'}

    def test_registro_valido_crea_cuenta_y_sesion(self):
        respuesta = self.client.post(reverse('registro'), self.datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json()['success'])
        usuario = get_user_model().objects.get(username=self.datos['username'])
        self.assertTrue(usuario.check_password(self.datos['password']))
        self.assertEqual(int(self.client.session['_auth_user_id']), usuario.pk)

    def test_campos_obligatorios_vacios_no_crean_cuentas(self):
        for campo in self.datos:
            with self.subTest(campo=campo):
                respuesta = self.client.post(reverse('registro'), {**self.datos, campo: ''})
                self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_email_invalido_y_password_debil_no_crean_cuentas(self):
        for cambio in ({'email': 'invalido'}, {'password': '123'}):
            with self.subTest(cambio=cambio):
                respuesta = self.client.post(reverse('registro'), {**self.datos, **cambio})
                self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_usuario_o_email_existente_se_rechazan(self):
        get_user_model().objects.create_user(username=self.datos['username'],
                                            email=self.datos['email'], password=self.datos['password'])
        for cambio in ({'email': 'otro@example.invalid'},
                       {'username': 'otro', 'email': self.datos['email'].upper()}):
            with self.subTest(cambio=cambio):
                respuesta = self.client.post(reverse('registro'), {**self.datos, **cambio})
                self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_metodos_distintos_de_post_no_crean_cuentas(self):
        for metodo in ('get', 'head', 'put', 'patch', 'delete', 'options'):
            with self.subTest(metodo=metodo):
                respuesta = getattr(self.client, metodo)(reverse('registro'))
                self.assertEqual(respuesta.status_code, 405)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_csrf_sigue_siendo_obligatorio(self):
        respuesta = Client(enforce_csrf_checks=True).post(reverse('registro'), self.datos)
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(get_user_model().objects.exists())


class SentimientoCompatibilidadTests(SimpleTestCase):
    def test_lexico_conserva_polaridad_en_consumidores(self):
        from core import views
        from core.services import sentimiento
        casos = [('', 0.0), ('bueno', 0.7), ('terrible', -0.7),
                 ('excelente mejora', 1.0), ('bueno malo', 0.0),
                 ('niñez sin polaridad', 0.0)]
        for analizar in (views.analyze_sentiment_lexicon, sentimiento.analyze_sentiment_lexicon):
            for texto, esperado in casos:
                with self.subTest(texto=texto):
                    self.assertAlmostEqual(analizar(texto), esperado)

    def test_estadisticas_vacias_y_muestra_individual(self):
        from core import views
        from core.services import sentimiento
        campos = {'sample_size', 'mean_polarity', 'confidence_score', 'std_dev',
                  't_ci_lower', 't_ci_upper', 'wilson_lower', 'wilson_upper', 'positive_ratio'}
        for analizar in (views.compute_probabilistic_sentiment, sentimiento.compute_probabilistic_sentiment):
            vacio = analizar([])
            self.assertEqual(set(vacio), campos)
            self.assertTrue(all(valor == 0 for valor in vacio.values()))
            individual = analizar([{'message': 'bueno'}])
            self.assertEqual(individual['sample_size'], 1)
            self.assertEqual(individual['mean_polarity'], 0.7)
            self.assertEqual(individual['std_dev'], 0.0)
            self.assertEqual(individual['t_ci_lower'], 0.7)
            self.assertEqual(individual['t_ci_upper'], 0.7)
            self.assertEqual(individual['positive_ratio'], 100.0)
            self.assertEqual(individual['confidence_score'], 40.0)

    def test_muestra_mixta_conserva_intervalos_y_rangos(self):
        from core import views
        from core.services import sentimiento
        for analizar in (views.compute_probabilistic_sentiment, sentimiento.compute_probabilistic_sentiment):
            resultado = analizar([{'message': 'bueno'}, {'message': 'terrible'}])
            self.assertEqual(resultado['sample_size'], 2)
            self.assertEqual(resultado['mean_polarity'], 0.0)
            self.assertEqual(resultado['positive_ratio'], 50.0)
            self.assertGreater(resultado['std_dev'], 0)
            self.assertLessEqual(-1.0, resultado['t_ci_lower'])
            self.assertLessEqual(resultado['t_ci_lower'], resultado['mean_polarity'])
            self.assertLessEqual(resultado['mean_polarity'], resultado['t_ci_upper'])
            self.assertLessEqual(resultado['t_ci_upper'], 1.0)
            self.assertLessEqual(0.0, resultado['wilson_lower'])
            self.assertLessEqual(resultado['wilson_lower'], resultado['wilson_upper'])
            self.assertLessEqual(resultado['wilson_upper'], 1.0)
            self.assertLessEqual(0.0, resultado['confidence_score'])
            self.assertLessEqual(resultado['confidence_score'], 100.0)
