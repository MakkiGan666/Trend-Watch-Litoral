"""Ejecuta funciones reales del merge con dependencias simuladas, sin Django/BD/red."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
from core.categorias import datos_categorias
from core.fechas import datos_fecha
from core.localidades import DEPARTAMENTOS, departamento_de_ubicacion


def funcion(nombre, contexto):
    arbol = ast.parse((ROOT / 'app/core/views.py').read_text())
    nodo = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == nombre)
    nodo.decorator_list = []
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), '<vista-real-integrada>', 'exec'), contexto)
    return contexto[nombre]


def publicacion():
    categorias = [SimpleNamespace(pk=2, nombre_categoria='Turismo'),
                  SimpleNamespace(pk=1, nombre_categoria='Salud')]
    return SimpleNamespace(
        id_publicacion_api=7, titulo='Archivo', contenido='Texto', fuente='El Territorio (Archivo)',
        departamento='capital', imagen_publica_url='/media/publicaciones/local.png',
        imagen_url='https://example.invalid/remota.png', url='', procesado_ia=False,
        fecha_publicacion=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        fecha_captura=datetime(2026, 10, 20, 2, tzinfo=timezone.utc),
        temas=SimpleNamespace(all=lambda: [SimpleNamespace(id_categoria=c) for c in categorias]),
        locacion_set=SimpleNamespace(all=lambda: [SimpleNamespace(location='El Soberbio')]),
    )


class IntegracionUnitTests(unittest.TestCase):
    def setUp(self):
        for destino in ('socket.socket.connect', 'socket.getaddrinfo'):
            bloqueo = patch(destino, side_effect=AssertionError('Red prohibida'))
            bloqueo.start()
            self.addCleanup(bloqueo.stop)

    def test_dashboard_lee_categorias_y_territorio_sin_perder_orden(self):
        p = publicacion()
        manager = Mock()
        consulta = manager.select_related.return_value.prefetch_related.return_value
        consulta.order_by.return_value = [p]
        contexto = {
            'Publicacion': SimpleNamespace(objects=manager), 'Categoria': Mock(),
            '_orden_por_publicacion': lambda: ('orden-efectivo', '-id_publicacion_api'),
            'datos_categorias': datos_categorias, 'DEPARTAMENTOS': DEPARTAMENTOS,
            'departamento_de_ubicacion': departamento_de_ubicacion,
            'render': lambda request, template, data: data,
        }
        resultado = funcion('dashboard', contexto)(SimpleNamespace())
        consulta.order_by.assert_called_once_with('orden-efectivo', '-id_publicacion_api')
        self.assertEqual(resultado['publicaciones'], [p])
        self.assertEqual(p.dashboard_categorias, [1, 2])
        self.assertEqual(p.categorias_navegacion, ['Salud', 'Turismo'])
        self.assertEqual(p.dashboard_departamentos, ['capital', 'guarani'])
        self.assertEqual(len(resultado['departamentos']), 17)

    def test_listado_lee_imagen_efectiva_y_metadatos_sin_cambiar_fecha_legacy(self):
        p = publicacion()
        manager = Mock()
        manager.prefetch_related.return_value.order_by.return_value = [p]
        sentimiento = Mock()
        sentimiento.objects.filter.return_value.first.return_value = None
        contexto = {
            'Publicacion': SimpleNamespace(objects=manager), 'Sentimiento': sentimiento,
            '_orden_por_publicacion': lambda: ('efectiva', '-id_publicacion_api'),
            'LIMITE_LISTADO': 150, 'datos_categorias': datos_categorias, 'datos_fecha': datos_fecha,
            'JsonResponse': lambda data, **kwargs: data,
        }
        respuesta = funcion('listar_publicaciones', contexto)(SimpleNamespace(method='GET'))
        dato = respuesta['data'][0]
        self.assertEqual(dato['imagen_url'], '/media/publicaciones/local.png')
        self.assertEqual(dato['categorias_detalle'], [{'id': 1, 'nombre': 'Salud'}, {'id': 2, 'nombre': 'Turismo'}])
        self.assertEqual(dato['fecha'], '2026-10-20 02:00:00')
        self.assertEqual(dato['fecha_efectiva'], '2026-10-01')
        self.assertEqual(dato['fecha_precision'], 'dia')


if __name__ == '__main__':
    unittest.main(verbosity=2)
