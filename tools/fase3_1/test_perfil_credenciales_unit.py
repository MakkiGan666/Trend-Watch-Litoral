"""Vista y clean de email reales, con ORM/hash/PasswordChangeForm simulados.

Sin Django ni BD. No sustituye las regresiones PostgreSQL de bloqueo de fila.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class CredencialesTests(unittest.TestCase):
    def setUp(self):
        for destino in ('socket.socket.connect', 'socket.getaddrinfo'):
            bloqueo = patch(destino, side_effect=AssertionError('Red prohibida'))
            bloqueo.start()
            self.addCleanup(bloqueo.stop)
        self.fila = dict(pk=1, password='anterior', first_name='Ana', last_name='',
                         email='antes@example.invalid', is_active=True)
        self.locked = False
        self.validaciones = []
        self.rotada = False
        self.activa = True
        caso = self

        class Usuario:
            def __init__(self):
                self.__dict__.update(deepcopy(caso.fila))

            def check_password(self, valor):
                return self.password == valor

            def save(self, update_fields=None):
                for campo in (update_fields if update_fields is not None else caso.fila):
                    caso.fila[campo] = getattr(self, campo)

        class BaseClean:
            def clean(self):
                return self.cleaned_data

        arbol = ast.parse((ROOT / 'app/core/forms_perfil.py').read_text())
        clase = next(n for n in arbol.body if isinstance(n, ast.ClassDef) and n.name == 'PerfilForm')
        clean = next(n for n in clase.body if isinstance(n, ast.FunctionDef) and n.name == 'clean')
        nodo = ast.ClassDef(name='CleanReal', bases=[ast.Name(id='BaseClean', ctx=ast.Load())],
                            keywords=[], body=[clean], decorator_list=[])
        manager = Mock()
        manager.exclude.return_value.filter.return_value.exists.return_value = False
        contexto_clean = {'BaseClean': BaseClean, 'get_user_model': lambda: SimpleNamespace(objects=manager)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[nodo], type_ignores=[])),
                     '<clean-email-real>', 'exec'), contexto_clean)

        class Formulario(contexto_clean['CleanReal']):
            def __init__(self, data=None, instance=None, **kwargs):
                self.instance = instance
                self.cleaned_data = dict(email=(data or {}).get('datos-email', instance.email),
                    confirmar_password=(data or {}).get('datos-confirmar_password', ''),
                    fecha_nacimiento=None, celular='')
                self.changed_data = ['email'] if self.cleaned_data['email'] != instance.email else []
                self.errors = []

            def add_error(self, campo, mensaje):
                self.errors.append(campo)

            def is_valid(self):
                caso.validaciones.append(caso.locked)
                self.clean()
                return not self.errors

            def save(self, commit=True):
                self.instance.email = self.cleaned_data['email']
                if commit:
                    self.instance.save()
                return self.instance

        class PasswordFormulario:
            def __init__(self, user, data=None, **kwargs):
                self.user, self.data = user, data
                if not caso.rotada:
                    # Segunda instancia actualiza BD tras cargar el usuario del request.
                    segunda = Usuario()
                    segunda.password = 'vigente'
                    segunda.is_active = caso.activa
                    segunda.save(update_fields=['password', 'is_active'])
                    caso.rotada = True

            def is_valid(self):
                caso.validaciones.append(caso.locked)
                return self.user.check_password(self.data['password-old_password'])

            def save(self, commit=True):
                self.user.password = self.data['password-new_password1']
                if commit:
                    self.user.save()
                return self.user

        @contextmanager
        def atomic():
            anterior = deepcopy(self.fila)
            try:
                yield
            except Exception:
                self.fila.clear()
                self.fila.update(anterior)
                raise
            finally:
                self.locked = False

        def obtener(*args, **kwargs):
            self.locked = True
            return Usuario()

        self.usuario = Usuario()
        self.modelo_perfil = Mock()
        self.modelo_perfil.objects.filter.return_value.first.return_value = None
        self.sesion = Mock()
        self.permission_error = type('PermissionDenied', (RuntimeError,), {})
        contexto = dict(
            PerfilForm=Formulario, PasswordChangeForm=PasswordFormulario, PerfilUsuario=self.modelo_perfil,
            transaction=SimpleNamespace(atomic=atomic), get_user_model=lambda: SimpleNamespace(objects=Mock()),
            get_object_or_404=obtener, PermissionDenied=self.permission_error, update_session_auth_hash=self.sesion,
            messages=Mock(), redirect=lambda nombre: ('redirect', nombre),
            render=lambda request, template, data, **kwargs: ('render', kwargs.get('status', 200)),
        )
        arbol = ast.parse((ROOT / 'app/core/views_perfil.py').read_text())
        vista = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == 'perfil')
        vista.decorator_list = []
        exec(compile(ast.Module(body=[vista], type_ignores=[]), '<perfil-real>', 'exec'), contexto)
        self.vista = contexto['perfil']

    def enviar(self, accion, clave):
        data = {'accion': accion, 'datos-email': 'nuevo@example.invalid',
                'datos-confirmar_password': clave, 'password-old_password': clave,
                'password-new_password1': 'final', 'password-new_password2': 'final'}
        return self.vista(SimpleNamespace(method='POST', POST=data, user=self.usuario))

    def test_email_rechaza_clave_anterior_despues_de_rotacion(self):
        self.assertEqual(self.enviar('datos', 'anterior'), ('render', 400))
        self.assertEqual(self.fila['email'], 'antes@example.invalid')
        self.assertEqual(self.fila['password'], 'vigente')

    def test_password_rechaza_clave_anterior_despues_de_rotacion(self):
        self.assertEqual(self.enviar('password', 'anterior'), ('render', 400))
        self.assertEqual(self.fila['password'], 'vigente')
        self.sesion.assert_not_called()

    def test_email_acepta_clave_vigente_sin_renovar_sesion(self):
        self.assertEqual(self.enviar('datos', 'vigente'), ('redirect', 'perfil'))
        self.assertEqual(self.fila['email'], 'nuevo@example.invalid')
        self.assertEqual(self.validaciones, [True])
        self.sesion.assert_not_called()

    def test_password_acepta_clave_vigente_y_actualiza_sesion(self):
        self.assertEqual(self.enviar('password', 'vigente'), ('redirect', 'perfil'))
        self.assertEqual(self.fila['password'], 'final')
        self.assertEqual(self.validaciones, [True])
        self.sesion.assert_called_once()

    def test_password_revierte_si_falla_actualizacion_de_sesion(self):
        self.sesion.side_effect = RuntimeError('fallo simulado')
        with self.assertRaises(RuntimeError):
            self.enviar('password', 'vigente')
        self.assertEqual(self.fila['password'], 'vigente')

    def test_email_revierte_si_falla_guardado_de_perfil(self):
        self.modelo_perfil.objects.update_or_create.side_effect = RuntimeError('fallo simulado')
        with self.assertRaises(RuntimeError):
            self.enviar('datos', 'vigente')
        self.assertEqual(self.fila['email'], 'antes@example.invalid')
        self.assertEqual(self.fila['password'], 'vigente')

    def test_no_acepta_cuenta_desactivada_desde_la_lectura_inicial(self):
        self.activa = False
        with self.assertRaises(self.permission_error):
            self.enviar('datos', 'vigente')


if __name__ == '__main__':
    unittest.main(verbosity=2)
