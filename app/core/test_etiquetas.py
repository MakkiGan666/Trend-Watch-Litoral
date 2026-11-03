from django.test import TestCase
from django.urls import reverse

from .models import Etiqueta, Publicacion, PublicacionEtiqueta
from .services.etiquetas import sugerir_etiquetas


class EtiquetasNoticiasTestCase(TestCase):
    def test_etiqueta_compartida_enlaza_noticias_y_actualiza_al_editar(self):
        primera = Publicacion.objects.create(
            hash_origen='etiquetas-1', titulo='Jornada de salud en San Pedro',
            contenido='San Pedro organiza una jornada de salud.\n\nHabrá controles gratuitos.',
        )
        segunda = Publicacion.objects.create(
            hash_origen='etiquetas-2', titulo='Nuevas actividades en San Pedro',
            contenido='San Pedro prepara actividades para la comunidad.',
        )
        etiqueta = Etiqueta.objects.get(slug='san-pedro')
        self.assertEqual(PublicacionEtiqueta.objects.filter(etiqueta=etiqueta).count(), 2)

        listado = self.client.get(reverse('publicaciones_etiqueta', args=[etiqueta.slug]))
        self.assertEqual(listado.status_code, 200)
        self.assertContains(listado, primera.titulo)
        self.assertContains(listado, segunda.titulo)
        self.assertContains(self.client.get(reverse('noticia', args=[primera.pk])), etiqueta.slug)

        primera.titulo = 'Jornada de salud en Oberá'
        primera.contenido = 'Oberá organiza una jornada de salud.'
        primera.save(update_fields=['titulo', 'contenido'])
        self.assertFalse(PublicacionEtiqueta.objects.filter(publicacion=primera, etiqueta=etiqueta).exists())

    def test_extrae_como_maximo_quince_y_descarta_palabras_comunes(self):
        etiquetas = sugerir_etiquetas('Turismo en Puerto Iguazú', 'Turismo y visitantes en Puerto Iguazú.')
        self.assertLessEqual(len(etiquetas), 15)
        self.assertIn('puerto-iguazu', [slug for slug, _ in etiquetas])
        self.assertNotIn('para', [slug for slug, _ in etiquetas])

    def test_no_une_palabras_a_los_dos_lados_de_puntuacion(self):
        etiquetas = sugerir_etiquetas(
            'Nuevo golpe al narcotráfico: Gendarmería secuestró marihuana en San Pedro',
            'Gendarmería incautó marihuana en San Pedro.',
        )
        slugs = [slug for slug, _ in etiquetas]
        self.assertIn('san-pedro', slugs)
        self.assertIn('marihuana', slugs)
        self.assertNotIn('narcotrafico-gendarmeria-secuestro', slugs)

    def test_no_termina_nombre_propio_en_articulo(self):
        etiquetas = sugerir_etiquetas(
            'El regreso al club', 'El Club El Ceibo recibió a su equipo.',
        )
        self.assertNotIn('club-el', [slug for slug, _ in etiquetas])

    def test_descarta_palabras_generales_aunque_aparezcan_en_titulo_y_texto(self):
        etiquetas = sugerir_etiquetas(
            'Estamos dispuestos para la asamblea de productores',
            'Estamos dispuestos para la asamblea de productores de yerba.',
        )
        slugs = [slug for slug, _ in etiquetas]
        self.assertIn('asamblea-de-productores', slugs)
        self.assertNotIn('estamos', slugs)
        self.assertNotIn('dispuestos', slugs)

    def test_respaldo_para_titulo_especifico_sin_repeticion(self):
        etiquetas = sugerir_etiquetas('Glifosato', 'Desafilado brillo del acero, veneno alado.')
        self.assertIn('glifosato', [slug for slug, _ in etiquetas])

    def test_respaldo_para_titulo_generico_usa_nombres_del_texto(self):
        etiquetas = sugerir_etiquetas(
            'Agenda', 'Jairo se presentará en el Auditórium Montoya. Jairo recorrerá su historia en canciones.',
        )
        slugs = [slug for slug, _ in etiquetas]
        self.assertIn('auditorium-montoya', slugs)
        self.assertNotIn('agenda', slugs)

    def test_respaldo_no_une_nombres_de_parrafos_distintos(self):
        etiquetas = sugerir_etiquetas(
            'Agenda', 'Música\n\nJairo se presentará en el Auditórium Montoya.',
        )
        slugs = [slug for slug, _ in etiquetas]
        self.assertIn('auditorium-montoya', slugs)
        self.assertNotIn('musica-jairo', slugs)
