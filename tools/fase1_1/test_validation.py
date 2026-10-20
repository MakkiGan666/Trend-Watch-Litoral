"""Preparación del plan, copia y guardas: biblioteca estándar, sin Docker/Django."""
import ast
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import run
import validation as v

ROOT = Path(__file__).resolve().parents[2]


def clases(archivo):
    return {n.name: n for n in ast.parse(archivo.read_text()).body if isinstance(n, ast.ClassDef)}


def metodos(clase):
    return [n.name for n in clase.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith('test_')]


class ValidationPreparationTests(unittest.TestCase):
    def test_bloque_original_conserva_64_pruebas(self):
        self.assertEqual(v.BASE_LABELS, (
            'core.tests.LoginIdentificadorTestCase', 'core.tests.RolesPermisosTestCase',
            'core.tests.PublicacionDuplicadosTestCase',
        ))
        existentes = clases(ROOT / 'app/core/tests.py')
        self.assertEqual(sum(len(metodos(existentes[label.rsplit('.', 1)[1]]))
                             for label in v.BASE_LABELS), 64)
        self.assertTrue(set(v.BASE_LABELS).isdisjoint(v.FASE12_LABELS))

    def test_labels_resuelven_y_cubren_seis_regresiones_y_postgresql(self):
        for label in (*v.FASE12_LABELS, *v.FASE21_LABELS, *v.FASE22_LABELS, *v.FASE23_LABELS):
            with self.subTest(label=label):
                partes = label.split('.')
                if partes[-1].endswith('TestCase'):
                    archivo = ROOT / 'app' / ('/'.join(partes[:-1]) + '.py')
                    self.assertIn(partes[-1], clases(archivo))
                else:
                    self.assertTrue((ROOT / 'app' / ('/'.join(partes) + '.py')).is_file())
        historico = clases(ROOT / 'app/core/test_ingesta_historico.py')
        self.assertEqual(len(metodos(historico['CoberturaFase12TestCase'])), 6)
        self.assertEqual(len(metodos(historico['IngestaPostgreSQLTestCase'])), 3)
        self.assertIn('core.test_ingesta_historico', v.FASE12_LABELS)
        self.assertIn('core.test_ingesta_validacion', v.FASE12_LABELS)

    def test_orden_check_y_cinco_bloques_sin_keepdb(self):
        comando = Mock()
        v.ejecutar_plan(comando)
        self.assertEqual(comando.call_args_list, [
            call('check'), call('test', *v.BASE_LABELS, verbosity=2, interactive=False),
            call('test', *v.FASE12_LABELS, verbosity=2, interactive=False),
            call('test', *v.FASE21_LABELS, verbosity=2, interactive=False),
            call('test', *v.FASE22_LABELS, verbosity=2, interactive=False),
            call('test', *v.FASE23_LABELS, verbosity=2, interactive=False),
        ])

    def test_fallo_baseline_no_anuncia_ni_ejecuta_fase12(self):
        comando = Mock(side_effect=[None, RuntimeError('falló baseline')])
        with self.assertRaises(RuntimeError):
            v.ejecutar_plan(comando)
        self.assertEqual(comando.call_count, 2)

    def test_guardas_rechazan_y_restauran_sockets_dns(self):
        funciones = (('connect', socket.socket), ('connect_ex', socket.socket),
                     ('getaddrinfo', socket), ('gethostbyname', socket), ('gethostbyname_ex', socket))
        originales = {(nombre, modulo): getattr(modulo, nombre) for nombre, modulo in funciones}
        with v.sin_red_python():
            for nombre, modulo in funciones:
                with self.subTest(nombre=nombre), self.assertRaises(RuntimeError):
                    getattr(modulo, nombre)('dato-sintetico')
            # Excepción durante setup/test también debe restaurar los parches.
            with self.assertRaises(ValueError):
                with v.sin_red_python():
                    raise ValueError('fallo simulado')
            with self.assertRaises(RuntimeError):
                socket.getaddrinfo('medio.invalid', 443)
        for (nombre, modulo), original in originales.items():
            self.assertIs(getattr(modulo, nombre), original)

    def test_copia_solo_codigo_descartable_y_plan(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            app = raiz / 'app'
            app.mkdir()
            for nombre in ('core/caso.py', 'core/fixture.html', '.env', 'db.sqlite3',
                           'media/privado.html', 'uploads/privado.py', '.oculto/codigo.py'):
                archivo = app / nombre
                archivo.parent.mkdir(parents=True, exist_ok=True)
                archivo.write_text('dato sintético')
            (app / 'enlace.py').symlink_to(app / '.env')
            stage = raiz / 'stage'
            stage.mkdir()
            with patch.object(run, 'ROOT', raiz):
                run.copy_code(stage)
            archivos = {str(p.relative_to(stage)) for p in stage.rglob('*') if p.is_file()}
            self.assertEqual(archivos, {'core/caso.py', 'core/fixture.html',
                                       'fase1_1_runner.py', 'fase1_1_security.py',
                                       'fase1_1_validation.py'})
            self.assertEqual((stage / 'fase1_1_validation.py').read_text(),
                             Path(v.__file__).read_text())

    def test_runner_mantiene_guardas_de_identidad_y_usa_plan(self):
        arbol = ast.parse(Path(run.__file__).with_name('runner.py').read_text())
        llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)]
        nombres = [n.func.id for n in llamadas if isinstance(n.func, ast.Name)]
        for nombre in ('database_config', 'connection_params', 'authorize_writes',
                       'runner_environment', 'sin_red_python', 'ejecutar_plan'):
            self.assertIn(nombre, nombres)
        self.assertEqual(nombres.count('ejecutar_plan'), 1)
        contextos = [n for n in ast.walk(arbol) if isinstance(n, ast.With)
                     and any(isinstance(i.context_expr, ast.Call)
                             and isinstance(i.context_expr.func, ast.Name)
                             and i.context_expr.func.id == 'sin_red_python' for i in n.items)]
        self.assertEqual(len(contextos), 1)
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id == 'ejecutar_plan' for n in ast.walk(contextos[0])))
