from datetime import date
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase

from core.services.duplicados_editoriales import (
    canonicalizar_url,
    detectar_candidatos,
    normalizar_texto,
)


def registro(pk, *, fuente='El Territorio', titulo='Noticia de prueba sobre la ciudad',
             url='https://medio.test/noticia/1', fecha=date(2026, 11, 10),
             contenido='', completo=False):
    return {
        'pk': pk, 'fuente': fuente, 'titulo': titulo, 'url': url,
        'fecha_publicacion': fecha, 'contenido': contenido,
        'contenido_completo': completo,
    }


class DuplicadosEditorialesTests(SimpleTestCase):
    def test_normaliza_tildes_puntuacion_y_espacios(self):
        self.assertEqual(normalizar_texto('  ÁRBOL, río!  '), 'arbol rio')

    def test_urls_con_tracking_se_consideran_misma_identidad_en_fuente(self):
        a = registro(1, url='http://www.medio.test/noticia/1?utm_source=feed')
        b = registro(2, url='https://medio.test/noticia/1#texto')
        self.assertEqual(canonicalizar_url(a['url']), canonicalizar_url(b['url']))
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'DUPLICADO_CONFIRMADO')

    def test_titulo_identico_con_fechas_distintas_no_basta(self):
        a = registro(1)
        b = registro(2, url='https://medio.test/noticia/2', fecha=date(2026, 10, 10))
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'TITULO_REPETIDO_NO_CONFIRMADO')

    def test_mismo_titulo_en_fuentes_distintas_es_cobertura_no_duplicado(self):
        a = registro(1)
        b = registro(2, fuente='Norte Misionero', url='https://norte.test/noticia/1')
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'COBERTURA_MULTIMEDIO')

    def test_cuerpos_casi_iguales_y_url_distinta_confirman_candidato(self):
        cuerpo = ('La comunidad anunció obras y servicios para los vecinos. ' * 12)
        a = registro(1, contenido=cuerpo, completo=True)
        b = registro(2, url='https://medio.test/noticia/2', contenido=cuerpo, completo=True)
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'DUPLICADO_CONFIRMADO')
        self.assertIsNotNone(candidato['similitud_contenido'])

    def test_fichas_rss_incompletas_no_se_confirman_por_titulo_y_fecha(self):
        a = registro(1, completo=False)
        b = registro(2, url='https://medio.test/noticia/2', completo=False)
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'DATOS_INSUFICIENTES')
        self.assertIsNone(candidato['similitud_contenido'])

    def test_titulos_parecidos_con_cuerpos_distintos_separan_falsos_positivos(self):
        titulo = 'El municipio anunció obras nuevas para los barrios de la ciudad'
        otro = 'El municipio anunció obras nuevas para los barrios de la zona'
        a = registro(1, titulo=titulo, contenido=('Los vecinos participaron en una actividad deportiva. ' * 12), completo=True)
        b = registro(2, titulo=otro, url='https://medio.test/noticia/2',
                     contenido=('El Concejo debatió el presupuesto anual y las tasas locales. ' * 12), completo=True)
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'TITULO_COINCIDENTE_DISTINTO_CONTENIDO')

    def test_fuentes_de_el_territorio_se_normalizan_sin_unir_medios_distintos(self):
        a = registro(1, fuente='El Territorio (Archivo)')
        b = registro(2, fuente='El Territorio (Misiones)', url='https://medio.test/noticia/2')
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'DATOS_INSUFICIENTES')

    def test_titulos_cercanos_del_mismo_dia_entran_al_analisis(self):
        a = registro(1, contenido=('Texto editorial sustancial para contrastar. ' * 20), completo=True)
        b = registro(2, titulo='Noticia de prueba sobre otra ciudad', url='https://medio.test/noticia/2',
                     contenido=('Contenido diferente sobre un asunto local. ' * 20), completo=True)
        candidatos = detectar_candidatos([a, b])
        self.assertEqual(len(candidatos), 1)

    def test_no_genera_pares_para_publicacion_con_si_misma(self):
        self.assertEqual(detectar_candidatos([registro(1)]), [])

    def test_acepta_registros_de_analisis_sin_pk(self):
        a, b = registro(1), registro(2, url='https://medio.test/noticia/2')
        a.pop('pk')
        b.pop('pk')
        candidato, = detectar_candidatos([a, b])
        self.assertEqual(candidato['estado'], 'DATOS_INSUFICIENTES')

    def test_comando_exige_modo_dry_run(self):
        with self.assertRaises(CommandError):
            call_command('auditar_duplicados_editoriales')

    def test_comando_rechaza_backend_no_postgresql(self):
        with patch('core.management.commands.auditar_duplicados_editoriales.connection.vendor', 'sqlite'):
            with self.assertRaisesMessage(CommandError, 'PostgreSQL'):
                call_command('auditar_duplicados_editoriales', dry_run=True)
