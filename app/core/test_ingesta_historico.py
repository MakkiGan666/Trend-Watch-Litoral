"""ING-02 / TW-03: persistencia histórica, deduplicación e integridad de la ingesta.

Todas las pruebas usan RSS y artículos simulados: no hay acceso a red ni a datos reales.
Las que provocan errores de base de datos usan TransactionTestCase para reproducir el
autocommit de producción (en TestCase un IntegrityError invalida la transacción del test).
"""
import hashlib
import logging
from contextlib import contextmanager
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError
from xml.sax.saxutils import escape

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from core.models import (
    Categoria, Locacion, Publicacion, PublicacionTema, RegistroDatos, Sentimiento, Tema,
)
from core.services.scraper import fetch_and_store_elterritorio

BASE = 'https://www.elterritorio.com.ar/noticias/2026/10/16/'
FUENTE_OFICIAL = 'El Territorio (Misiones)'


def identidad(link):
    """Identidad documentada del scraper oficial: sha256 del link sin espacios externos."""
    return hashlib.sha256(link.strip().encode('utf-8')).hexdigest()


def rss(*items):
    """Arma un feed RSS a partir de tuplas (titulo, link, descripcion); None omite el nodo."""
    partes = []
    for titulo, link, descripcion in items:
        nodos = ''
        if titulo is not None:
            nodos += f'<title>{escape(titulo)}</title>'
        if link is not None:
            nodos += f'<link>{escape(link)}</link>'
        nodos += f'<description>{escape(descripcion or "")}</description>'
        partes.append(f'<item>{nodos}</item>')
    return f'<rss><channel>{"".join(partes)}</channel></rss>'.encode('utf-8')


@contextmanager
def capturar_avisos():
    """Junta los WARNING del scraper sin fallar si no hay ninguno (assertLogs fallaría
    antes de poder verificar los datos guardados)."""
    avisos = []

    class Recolector(logging.Handler):
        def emit(self, record):
            avisos.append(record.getMessage())

    logger = logging.getLogger('core.services.scraper')
    manejador = Recolector(level=logging.WARNING)
    logger.addHandler(manejador)
    try:
        yield avisos
    finally:
        logger.removeHandler(manejador)


def articulo_simulado(url, language=None, **kwargs):
    return SimpleNamespace(text=f'Texto completo de {url.strip()}', download=lambda **kwargs: None, parse=lambda: None)


class IngestaSimuladaMixin:
    """Simula el feed y la descarga de artículos del scraper oficial."""

    def setUp(self):
        super().setUp()
        # Simular la frontera de descarga: ningún feed ni artículo accede a la red.
        parche_urlopen = patch('core.services.scraper._descargar')
        self.urlopen = parche_urlopen.start()
        self.addCleanup(parche_urlopen.stop)
        parche_article = patch('core.services.scraper.Article', side_effect=articulo_simulado)
        self.article = parche_article.start()
        self.addCleanup(parche_article.stop)
        # Nunca llamar a Gemini en las pruebas: la clasificación usa sólo reglas locales.
        parche_ia = patch('core.services.clasificacion._clasificar_con_ia', return_value={})
        parche_ia.start()
        self.addCleanup(parche_ia.stop)

    def feed(self, *items):
        self.urlopen.return_value = rss(*items)

    def ingerir(self, *items, categoria='misiones'):
        self.feed(*items)
        return fetch_and_store_elterritorio(categoria)

    def foto(self, publicacion):
        """Estado completo de una publicación y sus relaciones, para comparar antes y después."""
        pk = publicacion.pk
        return {
            'publicacion': Publicacion.objects.filter(pk=pk).values().get(),
            'sentimientos': list(Sentimiento.objects.filter(id_publicacion_api=pk).order_by('pk').values()),
            'locaciones': list(Locacion.objects.filter(id_publicacion_api=pk).order_by('pk').values()),
            'temas': list(PublicacionTema.objects.filter(id_publicacion_api=pk).order_by('pk').values()),
        }

    def crear_historico(self, link=BASE + '900001-historica'):
        self.registro_viejo = RegistroDatos.objects.create(
            fuentes_api=FUENTE_OFICIAL, fecha_ejecucion=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            estado='EXITO', lenguaje='es',
        )
        publicacion = Publicacion.objects.create(
            hash_origen=identidad(link), fuente=FUENTE_OFICIAL, titulo='Noticia histórica',
            contenido='Contenido histórico', url=link,
            fecha_captura=datetime(2026, 1, 1, 12, tzinfo=dt_timezone.utc),
            procesado_ia=True, id_registro=self.registro_viejo,
        )
        Sentimiento.objects.create(id_publicacion_api=publicacion, polaridad=0.4, confianza=0.9)
        Locacion.objects.create(id_publicacion_api=publicacion, location='Posadas', latitud=-27.36, longitud=-55.9)
        tema = Tema.objects.create(
            descripcion='Tema histórico', id_categoria=Categoria.objects.create(nombre_categoria='Política'),
        )
        PublicacionTema.objects.create(id_publicacion_api=publicacion, id_temas=tema)
        return publicacion


# ---------------------------------------------------------------- A. Persistencia histórica
class PersistenciaHistoricaTestCase(IngestaSimuladaMixin, TestCase):
    def test_a1_historico_y_relaciones_se_conservan_tras_nueva_ingesta(self):
        historica = self.crear_historico()
        antes = self.foto(historica)
        registro_antes = RegistroDatos.objects.filter(pk=self.registro_viejo.pk).values().get()

        resultado = self.ingerir(
            ('Nueva uno', BASE + '900002-nueva-uno', 'Resumen uno'),
            ('Nueva dos', BASE + '900003-nueva-dos', 'Resumen dos'),
        )

        self.assertEqual(resultado['status'], 'EXITO')
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual(self.foto(historica), antes)
        self.assertEqual(RegistroDatos.objects.filter(pk=self.registro_viejo.pk).values().get(), registro_antes)
        nuevas = Publicacion.objects.exclude(pk=historica.pk)
        self.assertEqual(
            set(nuevas.values_list('hash_origen', flat=True)),
            {identidad(BASE + '900002-nueva-uno'), identidad(BASE + '900003-nueva-dos')},
        )
        self.assertEqual(set(nuevas.values_list('id_registro', flat=True)), {resultado['registro_id']})
        self.assertNotEqual(resultado['registro_id'], self.registro_viejo.pk)

    def test_a2_link_existente_con_otros_datos_no_reemplaza_ni_duplica(self):
        historica = self.crear_historico()
        antes = self.foto(historica)

        resultado = self.ingerir(('Título modificado', historica.url, 'Descripción modificada'))

        self.assertEqual(resultado['status'], 'EXITO')
        self.assertEqual(resultado['capturados'], 0)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(self.foto(historica), antes)
        self.article.assert_not_called()

    def test_a3_reingesta_del_mismo_feed_conserva_publicaciones_y_su_registro(self):
        items = (
            ('Uno', BASE + '900010-uno', 'Resumen uno'),
            ('Dos', BASE + '900011-dos', 'Resumen dos'),
        )
        primera = self.ingerir(*items)
        fotos = {p.pk: self.foto(p) for p in Publicacion.objects.all()}

        segunda = self.ingerir(*items)

        self.assertEqual((primera['capturados'], segunda['capturados']), (2, 0))
        self.assertEqual({p.pk: self.foto(p) for p in Publicacion.objects.all()}, fotos)
        self.assertEqual(
            set(Publicacion.objects.values_list('id_registro', flat=True)), {primera['registro_id']},
        )
        self.assertEqual(list(RegistroDatos.objects.order_by('pk').values_list('estado', flat=True)),
                         ['EXITO', 'EXITO'])


# ---------------------------------------------------------------- B. Deduplicación
class DeduplicacionTestCase(IngestaSimuladaMixin, TestCase):
    def test_b1_link_con_espacios_externos_comparte_identidad(self):
        link = BASE + '900020-espacios'
        primera = self.ingerir(('Con espacios', f'  {link}\n', 'Resumen'))
        segunda = self.ingerir(('Sin espacios', link, 'Resumen'))

        self.assertEqual((primera['capturados'], segunda['capturados']), (1, 0))
        publicacion = Publicacion.objects.get()
        self.assertEqual(publicacion.url, link)
        self.assertEqual(publicacion.hash_origen, identidad(link))

    def test_b2_links_distintos_con_mismo_titulo_son_publicaciones_distintas(self):
        resultado = self.ingerir(
            ('Mismo título', BASE + '900021-a', 'Resumen a'),
            ('Mismo título', BASE + '900022-b', 'Resumen b'),
        )
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual(Publicacion.objects.filter(titulo='Mismo título').count(), 2)

    def test_b3_link_repetido_en_el_mismo_feed_se_guarda_una_vez(self):
        link = BASE + '900023-repetida'
        resultado = self.ingerir(('Repetida', link, 'Resumen'), ('Repetida', link, 'Resumen'))
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(Publicacion.objects.filter(hash_origen=identidad(link)).count(), 1)


# ---------------------------------------------------------------- B4 y C. Errores con autocommit
class ErroresIndividualesTestCase(IngestaSimuladaMixin, TransactionTestCase):
    def test_b4_colision_por_concurrencia_no_interrumpe_el_lote(self):
        """Otro proceso guarda la misma noticia entre la verificación y el alta (D2)."""
        repetida, nueva = BASE + '900030-carrera', BASE + '900031-siguiente'

        def articulo_con_carrera(url, language=None, **kwargs):
            if url == repetida:
                Publicacion.objects.create(hash_origen=identidad(repetida), contenido='Otro proceso', url=repetida)
            return articulo_simulado(url)

        self.article.side_effect = articulo_con_carrera
        resultado = self.ingerir(('Carrera', repetida, 'Resumen'), ('Siguiente', nueva, 'Resumen'))

        self.assertTrue(Publicacion.objects.filter(hash_origen=identidad(nueva)).exists(),
                        'La noticia válida posterior a la colisión no se guardó.')
        self.assertEqual(Publicacion.objects.filter(hash_origen=identidad(repetida)).count(), 1)
        self.assertEqual(resultado['status'], 'EXITO')
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(resultado['omitidas'], 1)

    def _comprobar_invalida_registrada(self, invalida, valida_1, valida_2):
        with capturar_avisos() as avisos:
            resultado = self.ingerir(valida_1, invalida, valida_2)

        for titulo, link, _ in (valida_1, valida_2):
            self.assertTrue(Publicacion.objects.filter(hash_origen=identidad(link)).exists(),
                            f'No se guardó la noticia válida {titulo!r}.')
        self.assertFalse(Publicacion.objects.filter(hash_origen=identidad(invalida[1])).exists(),
                         'La noticia inválida se guardó sin control.')
        self.assertEqual(resultado['status'], 'ERROR')
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual(RegistroDatos.objects.get(pk=resultado['registro_id']).estado, 'ERROR: PARCIAL')
        self.assertTrue(any(invalida[1] in aviso for aviso in avisos),
                        'El error de la noticia no quedó registrado en el log.')
        self.assertEqual(len(resultado.get('errores', [])), 1)
        self.assertEqual(resultado['errores'][0]['link'], invalida[1])
        self.assertEqual(resultado['errores'][0]['codigo'], 'datos_invalidos')

    def test_c1_titulo_demasiado_largo_se_registra_y_el_lote_continua(self):
        self._comprobar_invalida_registrada(
            ('T' * 300, BASE + '900041-titulo-largo', 'Resumen'),
            ('Válida uno', BASE + '900040-valida-uno', 'Resumen'),
            ('Válida dos', BASE + '900042-valida-dos', 'Resumen'),
        )

    def test_c2_url_demasiado_larga_se_registra_y_el_lote_continua(self):
        self._comprobar_invalida_registrada(
            ('URL larga', BASE + '900051-' + 'x' * 500, 'Resumen'),
            ('Válida uno', BASE + '900050-valida-uno', 'Resumen'),
            ('Válida dos', BASE + '900052-valida-dos', 'Resumen'),
        )

    def test_c3_noticia_sin_enlace_queda_registrada(self):
        with capturar_avisos() as avisos:
            resultado = self.ingerir(
                ('Sin enlace', None, 'Resumen'),
                ('Con enlace', BASE + '900060-con-enlace', 'Resumen'),
            )
        self.assertTrue(Publicacion.objects.filter(hash_origen=identidad(BASE + '900060-con-enlace')).exists())
        self.assertEqual(resultado['capturados'], 1)
        self.assertTrue(avisos, 'La noticia sin enlace se descartó sin dejar registro en el log.')
        self.assertEqual([e['codigo'] for e in resultado.get('errores', [])], ['sin_enlace'])

    def test_c5_fallo_de_infraestructura_corta_el_lote_e_informa_lo_capturado(self):
        crear_real = Publicacion.objects.create
        llamadas = []

        def crear_con_fallo(**datos):
            llamadas.append(datos['url'])
            if len(llamadas) == 2:
                raise OperationalError('conexión perdida')
            return crear_real(**datos)

        with patch('core.services.scraper.Publicacion.objects.create', side_effect=crear_con_fallo):
            resultado = self.ingerir(
                ('Primera', BASE + '900070-primera', 'Resumen'),
                ('Segunda', BASE + '900071-segunda', 'Resumen'),
                ('Tercera', BASE + '900072-tercera', 'Resumen'),
            )

        self.assertEqual(resultado['status'], 'ERROR')
        self.assertTrue(Publicacion.objects.filter(hash_origen=identidad(BASE + '900070-primera')).exists())
        self.assertTrue(RegistroDatos.objects.get().estado.startswith('ERROR'))
        self.assertEqual(resultado.get('capturados'), 1)


class ErroresDeFeedTestCase(IngestaSimuladaMixin, TestCase):
    def test_c4_fallo_de_descarga_usa_descripcion_sin_html_y_continua(self):
        falla = BASE + '900080-falla'

        def articulo_que_falla(url, language=None, **kwargs):
            if url == falla:
                return SimpleNamespace(text='', download=lambda **kwargs: (_ for _ in ()).throw(OSError('timeout')),
                                       parse=lambda: None)
            return articulo_simulado(url)

        self.article.side_effect = articulo_que_falla
        resultado = self.ingerir(
            ('Falla', falla, '<p>Resumen <b>del feed</b></p>'),
            ('Sigue', BASE + '900081-sigue', 'Resumen'),
        )
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual(Publicacion.objects.get(hash_origen=identidad(falla)).contenido, 'Resumen del feed')

    def test_c6_feed_caido_o_xml_invalido_informa_error_sin_publicaciones(self):
        for caso, configurar in (
            ('feed caído', lambda: setattr(self.urlopen, 'side_effect', URLError('Feed no disponible'))),
            ('xml inválido', lambda: self.urlopen.configure_mock(return_value=b'<rss>')),
        ):
            with self.subTest(caso=caso):
                self.urlopen.reset_mock(side_effect=True)
                configurar()
                resultado = fetch_and_store_elterritorio('misiones')
                self.assertEqual(resultado['status'], 'ERROR')
                self.assertFalse(Publicacion.objects.exists())
                self.assertTrue(RegistroDatos.objects.latest('pk').estado.startswith('ERROR'))


# ---------------------------------------------------------------- D. Relaciones y borrados
class BorradoRegistroDatosAdminTestCase(TestCase):
    """Se prueban dos casos: con sentimiento, el admin ya bloquea la cascada porque nadie puede
    borrar sentimientos; recién ingerida (sin sentimiento todavía) no hay nada que la frene."""

    def setUp(self):
        call_command('configurar_roles', stdout=StringIO())
        usuario = get_user_model().objects.create_user(username='admin-ing02', is_staff=True)
        usuario.groups.add(Group.objects.get(name='Administrador'))
        self.client.force_login(usuario)
        self.casos = {}
        for caso, con_sentimiento in (('recién ingerida', False), ('con sentimiento', True)):
            registro = RegistroDatos.objects.create(
                fuentes_api=FUENTE_OFICIAL, fecha_ejecucion=timezone.now(), estado='EXITO', lenguaje='es',
            )
            link = BASE + f'90009{int(con_sentimiento)}-admin'
            publicacion = Publicacion.objects.create(
                hash_origen=identidad(link), contenido='Histórica', url=link, id_registro=registro,
            )
            if con_sentimiento:
                Sentimiento.objects.create(id_publicacion_api=publicacion, polaridad=0.1, confianza=0.5)
            self.casos[caso] = (registro, publicacion)

    def comprobar_historico_intacto(self, registro, publicacion):
        self.assertTrue(Publicacion.objects.filter(pk=publicacion.pk).exists(),
                        'Borrar el registro de ejecución eliminó la publicación histórica.')
        self.assertTrue(RegistroDatos.objects.filter(pk=registro.pk).exists())

    def test_d2_borrado_individual_de_registro_no_elimina_historico(self):
        for caso, (registro, publicacion) in self.casos.items():
            with self.subTest(caso=caso):
                ruta = f'/admin/core/registrodatos/{registro.pk}/delete/'
                respuesta = self.client.post(ruta, {'post': 'yes'})
                self.comprobar_historico_intacto(registro, publicacion)
                self.assertEqual(respuesta.status_code, 403)
                self.assertEqual(self.client.get(ruta).status_code, 403)

    def test_d2_borrado_masivo_de_registros_no_elimina_historico(self):
        for caso, (registro, publicacion) in self.casos.items():
            with self.subTest(caso=caso):
                respuesta = self.client.post('/admin/core/registrodatos/', {
                    'action': 'delete_selected', '_selected_action': [registro.pk], 'post': 'yes',
                })
                self.comprobar_historico_intacto(registro, publicacion)
                self.assertEqual(respuesta.status_code, 403)


# ---------------------------------------------------------------- E. Scraper oficial e identidad unificada
class EjecutarScraperOficialTestCase(IngestaSimuladaMixin, TransactionTestCase):
    def ejecutar(self, **opciones):
        salida = StringIO()
        call_command('ejecutar_scraper', stdout=salida, **opciones)
        return salida.getvalue()

    def test_e1_noticia_ya_guardada_por_el_scraper_oficial_no_falla_ni_duplica(self):
        existente, nueva = BASE + '918300-existente', BASE + '918301-nueva'
        self.ingerir(('Existente', existente, 'Resumen'))
        self.feed(('Existente', existente, 'Resumen'), ('Nueva', nueva, 'Resumen'))

        salida = self.ejecutar(category='misiones', limit=5)

        self.assertIn('Ingesta finalizada correctamente', salida)
        self.assertEqual(Publicacion.objects.filter(hash_origen=identidad(existente)).count(), 1)
        self.assertTrue(Publicacion.objects.filter(hash_origen=identidad(nueva)).exists())

    def test_e2_usa_identidad_y_registro_del_scraper_oficial(self):
        link = BASE + '918312-noticia'
        self.feed(('Noticia', link, 'Resumen'))

        self.ejecutar(category='misiones', limit=5)

        publicacion = Publicacion.objects.get(hash_origen=identidad(link))
        self.assertNotEqual(publicacion.pk, 918312, 'La PK no debe ser el número externo de la URL.')
        self.assertIsNotNone(publicacion.id_registro_id)
        self.assertEqual(publicacion.fuente, FUENTE_OFICIAL)
        self.assertEqual(RegistroDatos.objects.count(), 1)

    def test_e3_error_del_feed_falla_sin_anunciar_exito(self):
        self.urlopen.side_effect = URLError('Feed no disponible')
        salida = StringIO()
        with self.assertRaises(CommandError):
            call_command('ejecutar_scraper', category='misiones', stdout=salida)
        self.assertNotIn('[✔]', salida.getvalue())
        self.assertFalse(Publicacion.objects.exists())

    def test_e4_comando_rechaza_categoria_inexistente(self):
        self.feed(('Horóscopo', BASE + '918320-horoscopo', 'Resumen'))
        with self.assertRaises(CommandError):
            self.ejecutar(category='horoscopo', limit=5)
        self.urlopen.assert_not_called()
        self.assertFalse(Publicacion.objects.exists())

    def test_e5_servicio_no_ingiere_otra_categoria_ante_categoria_inexistente(self):
        resultado = self.ingerir(('Misiones', BASE + '918321-misiones', 'Resumen'), categoria='horoscopo')
        self.assertEqual(resultado['status'], 'ERROR')
        self.urlopen.assert_not_called()
        self.assertFalse(Publicacion.objects.exists())


# ---------------------------------------------------------------- Sólo PostgreSQL
class IngestaPostgreSQLTestCase(IngestaSimuladaMixin, TransactionTestCase):
    """Comportamiento que SQLite no reproduce: límites de varchar y bloqueo por índice único."""

    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requiere PostgreSQL: SQLite no aplica límites de varchar ni concurrencia real.')
        super().setUp()

    def _ingerir_con_data_error_real(self):
        """Desactiva la validación previa para que la URL larga llegue a PostgreSQL."""
        self.valida_1, self.valida_2 = BASE + '900100-valida-uno', BASE + '900102-valida-dos'
        self.larga = BASE + '900101-' + 'x' * 500
        with patch('core.services.scraper._excede_largo_maximo', return_value=False), \
                capturar_avisos() as avisos:
            resultado = self.ingerir(
                ('Válida uno', self.valida_1, 'Resumen'),
                ('URL larga', self.larga, 'Resumen'),
                ('Válida dos', self.valida_2, 'Resumen'),
            )
        return resultado, avisos

    def _comprobar_data_error(self, resultado, avisos):
        for link in (self.valida_1, self.valida_2):
            self.assertTrue(Publicacion.objects.filter(hash_origen=identidad(link)).exists(),
                            'La noticia válida posterior al DataError no se guardó.')
        self.assertFalse(Publicacion.objects.filter(hash_origen=identidad(self.larga)).exists())
        self.assertEqual(resultado['status'], 'ERROR')
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual([(e['link'], e['codigo']) for e in resultado['errores']],
                         [(self.larga, 'datos_invalidos')])
        self.assertTrue(any(self.larga in aviso for aviso in avisos))
        self.assertEqual(RegistroDatos.objects.get(pk=resultado['registro_id']).estado, 'ERROR: PARCIAL')

    def test_pg_data_error_real_en_autocommit_no_interrumpe_el_lote(self):
        self._comprobar_data_error(*self._ingerir_con_data_error_real())

    def test_pg_data_error_real_dentro_de_transaccion_externa_no_la_inutiliza(self):
        # Si el savepoint por noticia no existiera, PostgreSQL abortaría la transacción
        # externa y cualquier consulta posterior fallaría con InFailedSqlTransaction.
        with transaction.atomic():
            resultado, avisos = self._ingerir_con_data_error_real()
            self.assertEqual(Publicacion.objects.count(), 2)
        self._comprobar_data_error(resultado, avisos)

    def test_pg_dos_conexiones_ingieren_el_mismo_feed_sin_duplicar(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        links = (BASE + '900110-concurrente-uno', BASE + '900111-concurrente-dos')
        self.feed(*((f'Concurrente {i}', link, 'Resumen') for i, link in enumerate(links)))
        # Una barrera por noticia: ambas conexiones ya pasaron la verificación previa sin
        # encontrarla cuando intentan insertarla, así que una debe chocar con el índice único.
        barreras = {link: Barrier(2, timeout=15) for link in links}

        def articulo_sincronizado(url, language=None, **kwargs):
            barreras[url.strip()].wait()
            return articulo_simulado(url)

        self.article.side_effect = articulo_sincronizado

        def ingerir_en_conexion_propia():
            try:
                return fetch_and_store_elterritorio('misiones')
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [executor.submit(ingerir_en_conexion_propia) for _ in range(2)]
            resultados = [futuro.result(timeout=60) for futuro in futuros]

        self.assertFalse(any(b.broken for b in barreras.values()),
                         'Las conexiones no llegaron a competir por la misma noticia.')
        self.assertEqual([r['status'] for r in resultados], ['EXITO', 'EXITO'])
        self.assertEqual([r['errores'] for r in resultados], [[], []])
        self.assertEqual(sum(r['capturados'] for r in resultados), len(links))
        self.assertEqual(sum(r['omitidas'] for r in resultados), len(links))
        for link in links:
            self.assertEqual(Publicacion.objects.filter(hash_origen=identidad(link)).count(), 1)
        self.assertEqual(list(RegistroDatos.objects.values_list('estado', flat=True)), ['EXITO', 'EXITO'])


class CoberturaFase12TestCase(IngestaSimuladaMixin, TestCase):
    """Regresiones con ORM real; descargas y clasificación externa simuladas."""

    def test_vacio_difiere_de_duplicados(self):
        vacio = self.ingerir()
        self.ingerir(('Título', BASE + '900200-noticia', 'Resumen'))
        duplicados = self.ingerir(('Título', BASE + '900200-noticia', 'Resumen'))
        self.assertEqual(vacio['estado'], 'SIN_RESULTADOS')
        self.assertEqual(duplicados['estado'], 'DUPLICADOS')
        self.assertEqual(duplicados['omitidas'], 1)
        self.assertTrue(duplicados['cobertura_completa'])

    def test_titulo_vacio_no_persiste(self):
        resultado = self.ingerir(('', BASE + '900201-sin-titulo', 'Resumen'))
        self.assertEqual(resultado['status'], 'ERROR')
        self.assertFalse(Publicacion.objects.exists())

    def test_contenido_vacio_no_persiste(self):
        with patch('core.services.scraper._leer_articulo', return_value=None):
            resultado = self.ingerir(('Título', BASE + '900202-sin-contenido', ''))
        self.assertEqual(resultado['status'], 'ERROR')
        self.assertFalse(Publicacion.objects.exists())

    def test_destino_ajeno_no_se_descarga(self):
        with patch('core.services.scraper._leer_articulo') as articulo:
            resultado = self.ingerir(('Título', 'https://localhost/noticias/1', 'Resumen'))
        articulo.assert_not_called()
        self.assertEqual(resultado['errores'][0]['codigo'], 'url_invalida')
        self.assertFalse(Publicacion.objects.exists())

    def test_limite_reporta_parcial(self):
        self.feed(('Uno', BASE + '900203-uno', 'Resumen'), ('Dos', BASE + '900204-dos', 'Resumen'))
        resultado = fetch_and_store_elterritorio(limit=1, usar_ia=False)
        self.assertEqual((resultado['status'], resultado['estado']), ('ERROR', 'PARCIAL'))
        self.assertEqual(Publicacion.objects.count(), 1)

    def test_sitemap_parcial_conserva_publicacion(self):
        from datetime import date
        from core.services.scraper import ingestar_historico_elterritorio
        indice = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.elterritorio.com.ar/a.xml</loc></sitemap><sitemap><loc>https://www.elterritorio.com.ar/b.xml</loc></sitemap></sitemapindex>'
        mapa = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'
                + BASE + '900205-historica</loc></url></urlset>').encode()
        self.urlopen.side_effect = [indice, mapa, OSError('Mapa caído')]
        with patch('core.services.scraper._leer_articulo', return_value=SimpleNamespace(
                title='Histórica', text='Contenido', top_image='', publish_date=None)):
            resultado = ingestar_historico_elterritorio(date(2026, 1, 1), date(2026, 12, 31), usar_ia=False, pausa=0)
        self.assertEqual((resultado['estado'], resultado['capturados']), ('PARCIAL', 1))
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(RegistroDatos.objects.get().estado, 'ERROR: PARCIAL')
