from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
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


class SincronizacionEtiquetasTestCase(TestCase):
    def setUp(self):
        self.publicacion = Publicacion.objects.create(
            hash_origen='sincronizacion', titulo='Turismo en Puerto Iguazú',
            contenido='Turismo en Puerto Iguazú y visitantes en Puerto Iguazú.',
        )

    def relaciones(self):
        return list(self.publicacion.etiquetas.values_list('pk', 'etiqueta__slug', 'posicion'))

    def test_guardados_sin_cambios_de_texto_no_extraen_ni_reescriben(self):
        from unittest.mock import patch
        antes = self.relaciones()
        with patch('core.signals_etiquetas.sincronizar_etiquetas') as sincronizar:
            self.publicacion.save()
            self.publicacion.save(update_fields=['titulo', 'contenido'])
            self.publicacion.procesado_ia = True
            self.publicacion.save(update_fields=['procesado_ia'])
            self.publicacion.fuente = 'Otra fuente'
            self.publicacion.save()
            self.publicacion.save(update_fields=[])
            sincronizar.assert_not_called()
        self.assertEqual(self.relaciones(), antes)

    def test_cambio_real_sin_update_fields_y_cambio_parcial_sincronizan(self):
        from unittest.mock import patch
        from .services.etiquetas import sincronizar_etiquetas
        with patch('core.signals_etiquetas.sincronizar_etiquetas', wraps=sincronizar_etiquetas) as sincronizar:
            self.publicacion.titulo = 'Salud en San Pedro'
            self.publicacion.contenido = 'Salud en San Pedro y controles en San Pedro.'
            self.publicacion.save()
            self.assertEqual(sincronizar.call_count, 1)
            self.publicacion.contenido = 'Deportes en Oberá. Deportes en Oberá.'
            self.publicacion.save(update_fields=['contenido'])
            self.assertEqual(sincronizar.call_count, 2)
        self.assertEqual(
            list(self.publicacion.etiquetas.values_list('etiqueta__slug', flat=True)),
            [slug for slug, _ in sugerir_etiquetas(self.publicacion.titulo, self.publicacion.contenido)],
        )

    def test_save_parcial_ignora_texto_modificado_pero_no_guardado(self):
        from unittest.mock import patch
        antes = self.relaciones()
        self.publicacion.titulo = 'No persistir este título'
        with patch('core.signals_etiquetas.sincronizar_etiquetas') as sincronizar:
            self.publicacion.save(update_fields=['procesado_ia'])
            sincronizar.assert_not_called()
        self.assertEqual(self.relaciones(), antes)

    def test_instancia_diferida_no_regenera_al_guardar_otro_campo(self):
        from unittest.mock import patch
        parcial = Publicacion.objects.only('fuente').get(pk=self.publicacion.pk)
        with patch('core.signals_etiquetas.sincronizar_etiquetas') as sincronizar:
            parcial.fuente = 'Nueva fuente'
            parcial.save()
            sincronizar.assert_not_called()

    def test_servicio_usa_texto_persistido_y_conserva_ids_al_repetir(self):
        from .services.etiquetas import sincronizar_etiquetas
        antes = self.relaciones()
        self.publicacion.titulo = 'Instancia antigua'
        self.publicacion.contenido = 'Esto no se guardó'
        total = sincronizar_etiquetas(self.publicacion)
        self.assertEqual(total, len(antes))
        self.assertEqual(self.relaciones(), antes)
        self.assertEqual(sincronizar_etiquetas(self.publicacion), total)
        self.assertEqual(self.relaciones(), antes)

    def test_repetir_sincronizacion_no_ejecuta_escrituras(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .services.etiquetas import sincronizar_etiquetas
        with CaptureQueriesContext(connection) as consultas:
            sincronizar_etiquetas(self.publicacion)
        escrituras = [c['sql'] for c in consultas if c['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(escrituras, [])

    def test_orden_intercambiado_no_colisiona_con_posiciones_unicas(self):
        from unittest.mock import patch
        from .services.etiquetas import sincronizar_etiquetas
        propuestas = [('salud', 'Salud'), ('turismo', 'Turismo')]
        with patch('core.services.etiquetas.sugerir_etiquetas', return_value=propuestas):
            sincronizar_etiquetas(self.publicacion)
        with patch('core.services.etiquetas.sugerir_etiquetas', return_value=list(reversed(propuestas))):
            sincronizar_etiquetas(self.publicacion)
        self.assertEqual(list(self.publicacion.etiquetas.values_list('etiqueta__slug', 'posicion')),
                         [('turismo', 1), ('salud', 2)])

    def test_error_al_insertar_revierte_texto_y_asociaciones(self):
        from unittest.mock import patch
        from django.db import IntegrityError
        from django.db.models.query import QuerySet
        texto = (self.publicacion.titulo, self.publicacion.contenido)
        antes = self.relaciones()
        self.publicacion.titulo = 'Salud en San Pedro'
        self.publicacion.contenido = 'Salud en San Pedro.'
        with patch.object(QuerySet, 'bulk_create', side_effect=IntegrityError('fallo de prueba')):
            with self.assertRaises(IntegrityError):
                self.publicacion.save(update_fields=['titulo', 'contenido'])
        self.publicacion.refresh_from_db()
        self.assertEqual((self.publicacion.titulo, self.publicacion.contenido), texto)
        self.assertEqual(self.relaciones(), antes)
        self.assertFalse(Etiqueta.objects.filter(slug='san-pedro').exists())

    def test_error_en_alta_no_deja_publicacion_huerfana(self):
        from unittest.mock import patch
        from django.db import IntegrityError
        with patch('core.signals_etiquetas.sincronizar_etiquetas', side_effect=IntegrityError('fallo de prueba')):
            with self.assertRaises(IntegrityError):
                Publicacion.objects.create(hash_origen='alta-fallida', titulo='San Pedro', contenido='Salud')
        self.assertFalse(Publicacion.objects.filter(hash_origen='alta-fallida').exists())

    def test_fixture_raw_no_sincroniza(self):
        from unittest.mock import patch
        with patch('core.signals_etiquetas.sincronizar_etiquetas') as sincronizar:
            self.publicacion.save_base(raw=True)
            sincronizar.assert_not_called()

    def test_expresion_en_texto_se_resuelve_desde_la_base(self):
        from django.db.models import Value
        self.publicacion.titulo = Value('Salud en San Pedro')
        self.publicacion.contenido = 'Salud en San Pedro.'
        self.publicacion.save(update_fields=['titulo', 'contenido'])
        self.assertTrue(self.publicacion.etiquetas.filter(etiqueta__slug='san-pedro').exists())

    def test_bulk_requiere_sincronizacion_explicita_atomica(self):
        from django.db import transaction
        from .services.etiquetas import sincronizar_etiquetas
        nueva = Publicacion(hash_origen='bulk', titulo='Salud en San Pedro', contenido='Salud en San Pedro.')
        with transaction.atomic():
            Publicacion.objects.bulk_create([nueva])
            self.assertFalse(nueva.etiquetas.exists())  # Contrato de bulk: no emite señales.
            sincronizar_etiquetas(nueva)
        self.assertTrue(nueva.etiquetas.filter(etiqueta__slug='san-pedro').exists())
        with transaction.atomic():
            Publicacion.objects.filter(pk=nueva.pk).update(titulo='Turismo en Oberá', contenido='Turismo en Oberá.')
            sincronizar_etiquetas(nueva)  # Instancia deliberadamente antigua.
        self.assertFalse(nueva.etiquetas.filter(etiqueta__slug='san-pedro').exists())
        nueva.titulo = 'Salud en San Pedro'
        nueva.contenido = 'Salud en San Pedro.'
        with transaction.atomic():
            Publicacion.objects.bulk_update([nueva], ['titulo', 'contenido'])
            sincronizar_etiquetas(nueva)
        self.assertTrue(nueva.etiquetas.filter(etiqueta__slug='san-pedro').exists())


class GenerarEtiquetasTestCase(TestCase):
    def setUp(self):
        self.primera, self.segunda = Publicacion.objects.bulk_create([
            Publicacion(hash_origen='lote-1', titulo='Salud en San Pedro', contenido='Salud en San Pedro.'),
            Publicacion(hash_origen='lote-2', titulo='Turismo en Oberá', contenido='Turismo en Oberá.'),
        ])

    def ejecutar(self, **opciones):
        from io import StringIO
        from django.core.management import call_command
        salida = StringIO()
        call_command('generar_etiquetas', stdout=salida, **opciones)
        return salida.getvalue()

    def test_lotes_cursor_reanudacion_idempotencia_y_fin(self):
        salida = self.ejecutar(limite=1)
        self.assertIn(f'Cursor: {self.primera.pk}.', salida)
        self.assertTrue(self.primera.etiquetas.exists())
        self.assertFalse(self.segunda.etiquetas.exists())
        ids = list(self.primera.etiquetas.values_list('pk', flat=True))
        self.ejecutar(limite=1)
        self.assertEqual(ids, list(self.primera.etiquetas.values_list('pk', flat=True)))
        self.assertIn(f'Cursor: {self.segunda.pk}.', self.ejecutar(despues_de_id=self.primera.pk, limite=1))
        self.assertTrue(self.segunda.etiquetas.exists())
        self.assertIn('Publicaciones procesadas: 0.', self.ejecutar(despues_de_id=self.segunda.pk))
        self.assertIn(f'Cursor: {self.segunda.pk}.', self.ejecutar(despues_de_id=self.segunda.pk))

    def test_parametros_invalidos_fallan_antes_de_consultar(self):
        from django.core.management.base import CommandError
        for opciones in ({'limite': 0}, {'limite': -1}, {'despues_de_id': -1}):
            with self.subTest(opciones=opciones), self.assertNumQueries(0):
                with self.assertRaises(CommandError):
                    self.ejecutar(**opciones)

    def test_solo_sin_etiquetas_preserva_asociacion_existente(self):
        manual = Etiqueta.objects.create(slug='manual', nombre='Manual')
        relacion = PublicacionEtiqueta.objects.create(publicacion=self.primera, etiqueta=manual, posicion=1)
        self.ejecutar(solo_sin_etiquetas=True)
        self.assertTrue(PublicacionEtiqueta.objects.filter(pk=relacion.pk).exists())
        self.assertTrue(self.segunda.etiquetas.exists())
        self.ejecutar(limite=1)
        self.assertFalse(PublicacionEtiqueta.objects.filter(pk=relacion.pk).exists())

    def test_solo_sin_etiquetas_revalida_tras_seleccionar_lote(self):
        from unittest.mock import patch
        from .services.etiquetas import sincronizar_etiquetas
        manual = Etiqueta.objects.create(slug='manual', nombre='Manual')
        def agregar_antes_del_bloqueo(publicacion, **opciones):
            PublicacionEtiqueta.objects.create(publicacion=publicacion, etiqueta=manual, posicion=1)
            return sincronizar_etiquetas(publicacion, **opciones)
        with patch('core.management.commands.generar_etiquetas.sincronizar_etiquetas', side_effect=agregar_antes_del_bloqueo):
            self.ejecutar(limite=1, solo_sin_etiquetas=True)
        self.assertEqual(list(self.primera.etiquetas.values_list('etiqueta__slug', flat=True)), ['manual'])

    def test_fallo_a_mitad_del_lote_se_puede_reanudar(self):
        from unittest.mock import patch
        from .services.etiquetas import sincronizar_etiquetas
        def fallar_segunda(publicacion, **opciones):
            if publicacion.pk == self.segunda.pk:
                raise RuntimeError('interrupción de prueba')
            return sincronizar_etiquetas(publicacion, **opciones)
        with patch('core.management.commands.generar_etiquetas.sincronizar_etiquetas', side_effect=fallar_segunda):
            with self.assertRaises(RuntimeError):
                self.ejecutar()
        antes = list(self.primera.etiquetas.values_list('pk', flat=True))
        self.assertFalse(self.segunda.etiquetas.exists())
        self.ejecutar()
        self.assertEqual(antes, list(self.primera.etiquetas.values_list('pk', flat=True)))
        self.assertTrue(self.segunda.etiquetas.exists())


@skipUnlessDBFeature('has_select_for_update')
class ConcurrenciaEtiquetasTestCase(TransactionTestCase):
    def setUp(self):
        self.publicacion = Publicacion.objects.create(
            hash_origen='concurrente', titulo='Salud en San Pedro', contenido='Salud en San Pedro.',
        )

    def test_dos_sincronizaciones_de_la_misma_publicacion_se_serializan(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from django.db import connections
        from .services.etiquetas import sincronizar_etiquetas
        import core.services.etiquetas as servicio
        entro = Event()
        segundo_empezo = Event()
        segundo_entro = Event()
        liberar = Event()
        original = servicio.sugerir_etiquetas
        def extraer(titulo, contenido):
            if not entro.is_set():
                entro.set()
                if not liberar.wait(10):
                    raise AssertionError('No se liberó la primera sincronización')
            else:
                segundo_entro.set()
            return original(titulo, contenido)
        def ejecutar(segundo=False):
            try:
                if segundo:
                    segundo_empezo.set()
                return sincronizar_etiquetas(self.publicacion)
            finally:
                connections.close_all()
        with patch.object(servicio, 'sugerir_etiquetas', side_effect=extraer), ThreadPoolExecutor(max_workers=2) as pool:
            primera = pool.submit(ejecutar)
            try:
                self.assertTrue(entro.wait(5))
                segunda = pool.submit(ejecutar, True)
                self.assertTrue(segundo_empezo.wait(5))
                self.assertFalse(segundo_entro.wait(0.2))
            finally:
                liberar.set()
            self.assertEqual(primera.result(timeout=10), segunda.result(timeout=10))
        self.assertTrue(segundo_entro.is_set())
        self.assertEqual(self.publicacion.etiquetas.count(), len(sugerir_etiquetas(self.publicacion.titulo, self.publicacion.contenido)))

    def test_edicion_y_comando_con_instancia_antigua_convergen(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from django.db import connections, transaction
        from .services.etiquetas import sincronizar_etiquetas
        obsoleta = Publicacion.objects.get(pk=self.publicacion.pk)
        actualizado = Event()
        liberar = Event()
        intento = Event()
        def editar():
            try:
                with transaction.atomic():
                    publicacion = Publicacion.objects.get(pk=obsoleta.pk)
                    publicacion.titulo = 'Turismo en Oberá'
                    publicacion.contenido = 'Turismo en Oberá.'
                    publicacion.save(update_fields=['titulo', 'contenido'])
                    actualizado.set()
                    if not liberar.wait(10):
                        raise AssertionError('No se liberó la edición')
            finally:
                connections.close_all()
        def sincronizar():
            try:
                intento.set()
                return sincronizar_etiquetas(obsoleta)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            edicion = pool.submit(editar)
            try:
                self.assertTrue(actualizado.wait(5))
                sincronizacion = pool.submit(sincronizar)
                self.assertTrue(intento.wait(5))
                self.assertFalse(sincronizacion.done())
            finally:
                liberar.set()
            edicion.result(timeout=10)
            sincronizacion.result(timeout=10)
        self.publicacion.refresh_from_db()
        self.assertEqual(list(self.publicacion.etiquetas.values_list('etiqueta__slug', flat=True)),
                         [slug for slug, _ in sugerir_etiquetas(self.publicacion.titulo, self.publicacion.contenido)])
        self.assertFalse(self.publicacion.etiquetas.filter(etiqueta__slug='san-pedro').exists())

    def test_guardados_parciales_concurrentes_conservan_ambos_campos(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        barrera = Barrier(2)
        def editar(campo, valor):
            try:
                publicacion = Publicacion.objects.get(pk=self.publicacion.pk)
                setattr(publicacion, campo, valor)
                barrera.wait(timeout=5)
                publicacion.save(update_fields=[campo])
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            trabajos = [pool.submit(editar, 'titulo', 'Turismo en Oberá'),
                        pool.submit(editar, 'contenido', 'Turismo en Oberá y visitantes en Oberá.')]
            for trabajo in trabajos:
                trabajo.result(timeout=10)
        self.publicacion.refresh_from_db()
        self.assertEqual(self.publicacion.titulo, 'Turismo en Oberá')
        self.assertEqual(self.publicacion.contenido, 'Turismo en Oberá y visitantes en Oberá.')
        self.assertEqual(list(self.publicacion.etiquetas.values_list('etiqueta__slug', flat=True)),
                         [slug for slug, _ in sugerir_etiquetas(self.publicacion.titulo, self.publicacion.contenido)])

    def test_publicaciones_distintas_comparten_slugs_sin_colision(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from unittest.mock import patch
        from django.db import connections
        from .services.etiquetas import sincronizar_etiquetas
        publicaciones = Publicacion.objects.bulk_create([
            Publicacion(hash_origen='paralela-1', titulo='Uno', contenido='Texto'),
            Publicacion(hash_origen='paralela-2', titulo='Dos', contenido='Texto'),
        ])
        barrera = Barrier(2)
        def extraer(titulo, contenido):
            barrera.wait(timeout=5)
            propuestas = [('compartida-a', 'Compartida A'), ('compartida-b', 'Compartida B')]
            return propuestas if titulo == 'Uno' else list(reversed(propuestas))
        def ejecutar(publicacion):
            try:
                return sincronizar_etiquetas(publicacion)
            finally:
                connections.close_all()
        with patch('core.services.etiquetas.sugerir_etiquetas', side_effect=extraer), ThreadPoolExecutor(max_workers=2) as pool:
            resultados = [pool.submit(ejecutar, publicacion) for publicacion in publicaciones]
            self.assertEqual([f.result(timeout=10) for f in resultados], [2, 2])
        self.assertEqual(Etiqueta.objects.filter(slug__startswith='compartida-').count(), 2)
        self.assertEqual([p.etiquetas.count() for p in publicaciones], [2, 2])


from django.test import SimpleTestCase


class EtiquetasLargasTests(SimpleTestCase):
    def test_longitudes_y_unicode_no_generan_slugs_invalidos(self):
        for largo in (100, 110, 111, 150, 151, 255, 500):
            for letra in ('a', 'ñ', 'Á', '漢'):
                with self.subTest(largo=largo, letra=letra):
                    propuestas = sugerir_etiquetas(letra * largo, 'Texto neutro.')
                    slugs = [slug for slug, _ in propuestas]
                    self.assertEqual(len(slugs), len(set(slugs)))
                    self.assertLessEqual(len(slugs), 15)
                    for slug, nombre in propuestas:
                        self.assertTrue(0 < len(slug) <= 110)
                        self.assertTrue(0 < len(nombre) <= 100)
                    if letra != '漢' and largo <= 110:
                        self.assertEqual(len(propuestas), 1)
                    elif largo > 110:
                        self.assertEqual(propuestas, [])

    def test_palabra_descartada_no_elimina_nombres_propios_validos(self):
        propuestas = sugerir_etiquetas('a' * 151 + ' San Pedro', 'Salud en San Pedro.')
        self.assertIn('san-pedro', dict(propuestas))
        self.assertTrue(all(len(slug) <= 110 for slug, _ in propuestas))

    def test_vacios_y_muchos_candidatos_respetan_limite(self):
        self.assertEqual(sugerir_etiquetas('', ''), [])
        self.assertEqual(sugerir_etiquetas(None, None), [])
        propuestas = sugerir_etiquetas(' '.join(['Cultura', 'Educación', 'Turismo', 'Industria', 'Economía', 'Hospitales', 'Escuelas', 'Deportes', 'Ciencia', 'Bosques'] * 3), '')
        self.assertLessEqual(len(propuestas), 15)
        self.assertEqual(len(propuestas), len(dict(propuestas)))


class GuardadoEtiquetasLargasTests(TestCase):
    def test_alta_edicion_y_repeticion_con_palabras_largas(self):
        from .services.etiquetas import sincronizar_etiquetas
        publicacion = Publicacion.objects.create(hash_origen='larga-alta', titulo='a' * 151, contenido='Texto neutro.')
        self.assertFalse(publicacion.etiquetas.exists())
        for largo in (100, 110, 111, 150, 151, 255):
            with self.subTest(largo=largo):
                publicacion.titulo = 'ñ' * largo
                publicacion.save(update_fields=['titulo'])
                antes = list(publicacion.etiquetas.values_list('pk', 'etiqueta__slug', 'posicion'))
                sincronizar_etiquetas(publicacion)
                self.assertEqual(antes, list(publicacion.etiquetas.values_list('pk', 'etiqueta__slug', 'posicion')))
                self.assertEqual([pos for _, _, pos in antes], list(range(1, len(antes) + 1)))

    def test_error_de_insercion_revierte_edicion_y_etiquetas_previas(self):
        from unittest.mock import patch
        from django.db import IntegrityError
        from django.db.models.query import QuerySet
        publicacion = Publicacion.objects.create(hash_origen='larga-rollback', titulo='Salud en San Pedro', contenido='Salud en San Pedro.')
        antes = list(publicacion.etiquetas.values_list('pk', 'etiqueta_id', 'posicion'))
        titulo = publicacion.titulo
        publicacion.titulo = 'ñ' * 100
        with patch.object(QuerySet, 'bulk_create', side_effect=IntegrityError('fallo sintético')):
            with self.assertRaises(IntegrityError):
                publicacion.save(update_fields=['titulo'])
        publicacion.refresh_from_db()
        self.assertEqual(publicacion.titulo, titulo)
        self.assertEqual(antes, list(publicacion.etiquetas.values_list('pk', 'etiqueta_id', 'posicion')))
