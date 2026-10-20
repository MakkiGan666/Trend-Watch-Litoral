"""Plan aditivo de validación y defensa Python; no importa Django ni ejecuta Docker."""
from contextlib import contextmanager
import socket
from unittest.mock import patch

# Conservar el bloque original: las 64 pruebas informadas de Fase 1.1.
BASE_LABELS = (
    'core.tests.LoginIdentificadorTestCase',
    'core.tests.RolesPermisosTestCase',
    'core.tests.PublicacionDuplicadosTestCase',
)
FASE12_LABELS = (
    'core.test_ingesta_historico',  # Incluye las seis nuevas y las tres PostgreSQL.
    'core.tests.IngestaTestCase',
    'core.tests.IngestaRSSTestCase',
    'core.tests.ScraperAlternativoTestCase',
    'core.tests.EjecutarScraperCommandTestCase',
    'core.tests.RunPipelineCommandTestCase',
    'core.tests.ConsumidoresResultadoIATestCase',
    'core.test_ingesta_validacion',
)


FASE21_LABELS = ('core.test_fechas',)
FASE22_LABELS = (
    'core.test_categorias_compat',
    'core.test_clasificacion.CategoriaPorReglasTestCase',
    'core.test_clasificacion.DepartamentoPorTextoTestCase',
    'core.test_clasificacion.ClasificarLoteConIATestCase',
    'core.test_clasificacion.VincularCategoriaTestCase',
)


FASE23_LABELS = (
    'core.test_fase2_3',
    'core.tests.GeminiIntegridadTestCase',
    'core.tests.GeminiTransaccionesTestCase',
    'core.tests.EscritoresLocalesIntegridadTestCase',
    'core.tests.GeminiResultadosTestCase',
)


PR24_LABELS = (
    'core.test_dashboard_localidades',
    'core.test_publicacion_imagen',
    'core.test_comentarios',
    'core.test_valoraciones',
    'core.test_perfil',
    'core.test_integracion_pr24',
)


FASE32_LABELS = ('core.test_identidad', 'core.test_auth_views')


@contextmanager
def sin_red_python():
    """libpq usa C y queda sujeto a los controles de identidad del runner.

    No reemplaza la frontera de red Docker. Los mocks de cada prueba pueden
    reemplazar estas funciones para simular respuestas, sin abrir sockets.
    """
    def rechazar(*args, **kwargs):
        raise RuntimeError('Red Python externa deshabilitada en validación')

    with patch.object(socket.socket, 'connect', rechazar), patch.object(
        socket.socket, 'connect_ex', rechazar
    ), patch.object(socket, 'getaddrinfo', rechazar), patch.object(
        socket, 'gethostbyname', rechazar
    ), patch.object(socket, 'gethostbyname_ex', rechazar):
        yield


def ejecutar_plan(call_command):
    call_command('check')
    print('Fase 1.1: bloque original de regresiones', flush=True)
    call_command('test', *BASE_LABELS, verbosity=2, interactive=False)
    print('Fase 1.2: ingesta, consumidores y newspaper local', flush=True)
    call_command('test', *FASE12_LABELS, verbosity=2, interactive=False)

    print('Fase 2.1: fechas y ordenamiento', flush=True)
    call_command('test', *FASE21_LABELS, verbosity=2, interactive=False)

    print('Fase 2.2: categorías, clasificación y compatibilidad', flush=True)
    call_command('test', *FASE22_LABELS, verbosity=2, interactive=False)

    print('Fase 2.3: territorio, Gemini, URLs y límites', flush=True)
    call_command('test', *FASE23_LABELS, verbosity=2, interactive=False)

    print('Integración PR #24: frontend, imágenes, perfil y consumidores', flush=True)
    call_command('test', *PR24_LABELS, verbosity=2, interactive=False)

    print('Fase 3.2: identidad y autenticación', flush=True)
    call_command('test', *FASE32_LABELS, verbosity=2, interactive=False)
