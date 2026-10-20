"""Código real con ORM/locks simulados; biblioteca estándar y red prohibida."""
import ast
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unicodedata
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class Q:
    def __init__(self, **kwargs):
        self.condiciones = [kwargs]

    def __or__(self, otro):
        nuevo = Q()
        nuevo.condiciones = self.condiciones + otro.condiciones
        return nuevo


class Consulta:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self

    def exclude(self, **kwargs):
        return Consulta([r for r in self.rows if r.pk != kwargs['pk']])

    def filter(self, *predicados, **kwargs):
        def coincide(r, condiciones):
            return all((str(getattr(r, k.split('__')[0])).casefold() == str(v).casefold()
                        if k.endswith('__iexact') else getattr(r, k) == v)
                       for k, v in condiciones.items())
        def aceptar(r):
            return coincide(r, kwargs) and all(any(coincide(r, c) for c in q.condiciones) for q in predicados)
        return Consulta([r for r in self.rows if aceptar(r)])

    def exists(self):
        return bool(self.rows)


def cargar(path, nombre, contexto):
    spec = importlib.util.spec_from_file_location(nombre, path)
    modulo = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, contexto):
        spec.loader.exec_module(modulo)
    return modulo


class IdentidadTests(unittest.TestCase):
    def setUp(self):
        for destino in ('socket.socket.connect', 'socket.getaddrinfo'):
            bloqueo = patch(destino, side_effect=AssertionError('Red prohibida'))
            bloqueo.start()
            self.addCleanup(bloqueo.stop)
        self.rows = [SimpleNamespace(pk=1, username='Alias@example.com', email='otro@example.com', is_active=False)]
        self.eventos = []
        self.manager = Consulta(self.rows)
        self.model = SimpleNamespace(objects=self.manager, _default_manager=self.manager,
                                     normalize_username=lambda s: unicodedata.normalize('NFKC', s))
        self.model._meta = SimpleNamespace(get_field=lambda n: SimpleNamespace(max_length=254))
        self.manager.create_user = lambda **kw: SimpleNamespace(pk=2, **kw)

        @contextmanager
        def atomic():
            self.eventos.append('inicio')
            try:
                yield
            finally:
                self.eventos.append('fin')

        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.execute.side_effect = lambda *a: self.eventos.append('bloqueo')
        self.cursor = cursor
        self.connection = SimpleNamespace(vendor='postgresql', cursor=lambda: cursor)
        auth = ModuleType('django.contrib.auth'); auth.get_user_model = lambda: self.model
        db = ModuleType('django.db'); db.connection = self.connection; db.transaction = SimpleNamespace(atomic=atomic)
        models = ModuleType('django.db.models'); models.Q = Q
        self.identidad = cargar(ROOT / 'app/core/services/identidad.py', 'identidad_real', {
            'django.contrib.auth': auth, 'django.db': db, 'django.db.models': models,
        })

    def test_email_cruza_username_case_espacios_e_inactivos(self):
        self.assertIn('email', self.identidad.errores_identidad(email='  ALIAS@example.com  '))

    def test_username_cruza_email_sin_ignorar_inactivos(self):
        self.assertIn('username', self.identidad.errores_identidad(username=' OTRO@example.com '))

    def test_misma_cuenta_permitida(self):
        self.assertEqual(self.identidad.errores_identidad(email='Alias@example.com', excluir_pk=1), {})

    def test_email_duplicado_rechazado(self):
        self.assertIn('email', self.identidad.errores_identidad(email='OTRO@example.com'))

    def test_vacios_y_distintos_no_inventan_conflictos(self):
        self.assertEqual(self.identidad.errores_identidad(username='', email=''), {})
        self.assertEqual(self.identidad.errores_identidad(username='nuevo', email='nuevo@example.com'), {})

    def test_decorador_bloquea_antes_de_validar_y_libera_por_error(self):
        @self.identidad.con_identidad_serializada
        def vista():
            self.assertEqual(self.eventos, ['inicio', 'bloqueo'])
            raise ValueError('simulado')
        with self.assertRaises(ValueError):
            vista()
        self.assertEqual(self.eventos, ['inicio', 'bloqueo', 'fin'])
        self.cursor.execute.assert_called_once_with('SELECT pg_advisory_xact_lock(%s, %s)', [0x54574C, 0x4944])

    def test_otro_motor_no_simula_soporte_de_advisory_lock(self):
        self.connection.vendor = 'sqlite'
        with self.identidad.serializar_identidad():
            self.assertEqual(self.eventos, ['inicio'])
        self.cursor.execute.assert_not_called()

    def test_clean_real_del_perfil_rechaza_email_que_es_username_ajeno(self):
        class Base:
            def clean(self):
                return self.cleaned_data
        tree = ast.parse((ROOT / 'app/core/forms_perfil.py').read_text())
        clase = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        clean = next(n for n in clase.body if isinstance(n, ast.FunctionDef) and n.name == 'clean')
        nodo = ast.ClassDef(name='FormReal', bases=[ast.Name(id='Base', ctx=ast.Load())],
                            keywords=[], body=[clean], decorator_list=[])
        context = {'Base': Base, 'get_user_model': lambda: self.model,
                   'errores_identidad': self.identidad.errores_identidad}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[nodo], type_ignores=[])), '<clean-real>', 'exec'), context)
        form = context['FormReal']()
        form.instance = SimpleNamespace(pk=2, email='antes@example.com', check_password=lambda s: True)
        form.cleaned_data = {'email': 'ALIAS@example.com', 'confirmar_password': 'test-only'}
        form.add_error = Mock()
        form.clean()
        self.assertIn('email', [c.args[0] for c in form.add_error.call_args_list])

    def test_registro_real_rechaza_email_que_es_username_ajeno(self):
        tree = ast.parse((ROOT / 'app/core/views.py').read_text())
        vista = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'registro_view')
        vista.decorator_list = []
        context = {'get_user_model': lambda: self.model, 'EmailValidator': lambda: lambda s: None,
                   'validate_password': lambda *a, **kw: None, 'ValidationError': ValueError,
                   'login': Mock(), 'errores_identidad': self.identidad.errores_identidad,
                   'JsonResponse': lambda d, status=200: SimpleNamespace(status_code=status, data=d)}
        # La instancia temporal usada al validar contraseña no necesita ORM.
        class Modelo:
            objects = self.manager
            _meta = self.model._meta
            normalize_username = staticmethod(self.model.normalize_username)

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        context['get_user_model'] = lambda: Modelo
        exec(compile(ast.Module(body=[vista], type_ignores=[]), '<registro-real>', 'exec'), context)
        respuesta = context['registro_view'](SimpleNamespace(POST={
            'username': 'nuevo', 'email': 'ALIAS@example.com', 'password': 'test-only'}))
        self.assertEqual(respuesta.status_code, 400)
        context['login'].assert_not_called()

    def test_admin_delega_bajo_bloqueo_solo_en_post_incluida_password(self):
        caso = self

        class BaseAdmin:
            def changeform_view(self, *args):
                caso.eventos.append('padre')
                return 'respuesta'

            user_change_password = changeform_view

        tree = ast.parse((ROOT / 'app/core/admin.py').read_text())
        clase = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'UsuarioAdmin')
        metodos = [n for n in clase.body if isinstance(n, ast.FunctionDef)]
        nodo = ast.ClassDef(name='AdminReal', bases=[ast.Name(id='BaseAdmin', ctx=ast.Load())],
                            keywords=[], body=metodos, decorator_list=[])
        context = {'BaseAdmin': BaseAdmin, 'serializar_identidad': self.identidad.serializar_identidad}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[nodo], type_ignores=[])), '<admin-real>', 'exec'), context)
        instancia = context['AdminReal']()
        for metodo in ('changeform_view', 'user_change_password'):
            for method in ('GET', 'POST'):
                self.eventos.clear()
                respuesta = getattr(instancia, metodo)(SimpleNamespace(method=method), '2')
                self.assertEqual(respuesta, 'respuesta')
                esperado = ['inicio', 'bloqueo', 'padre', 'fin'] if method == 'POST' else ['padre']
                self.assertEqual(self.eventos, esperado)


if __name__ == '__main__':
    unittest.main(verbosity=2)
