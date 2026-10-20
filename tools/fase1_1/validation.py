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
