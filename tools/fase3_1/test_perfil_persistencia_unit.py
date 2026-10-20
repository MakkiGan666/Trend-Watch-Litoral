"""Regresión del flujo real con almacenamiento simulado; no sustituye el ORM.

Se extrae solo la vista por AST para ejecutarla sin Django. El doble de formulario
reproduce el guardado amplio de ModelForm; las nuevas pruebas ORM usan el real.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class PerfilPersistenciaTests(unittest.TestCase):
    def setUp(self):
        for nombre in ('socket.socket.connect', 'socket.getaddrinfo'):
            p = patch(nombre, side_effect=AssertionError('Red prohibida'))
            p.start()
            self.addCleanup(p.stop)
        self.fila = dict(pk=1, first_name='Antes', last_name='Apellido', email='uno@example.invalid',
                         password='hash-anterior', username='lector', is_staff=False, is_active=True)
        self.escrituras = []
        self.cambio = lambda: None
        caso = self

        class Usuario:
            def __init__(self):
                self.__dict__.update(deepcopy(caso.fila))

            def save(self, update_fields=None):
                caso.escrituras.append((self, update_fields))
                for campo in (update_fields if update_fields is not None else caso.fila):
                    caso.fila[campo] = getattr(self, campo)

        self.Usuario = Usuario
        self.usuario = Usuario()
        self.campos = ['first_name']
        self.valido = True

        class Formulario:
            def __init__(self, data=None, instance=None, **kwargs):
                self.instance = instance
                self.changed_data = caso.campos
                self.cleaned_data = dict(fecha_nacimiento=None, celular='')

            def is_valid(self):
                self.instance.first_name = 'Editado'
                return caso.valido

            def save(self, commit=True):
                caso.cambio()
                if commit:
                    self.instance.save()
                return self.instance

        @contextmanager
        def atomic():
            anterior = deepcopy(self.fila)
            try:
                yield
            except Exception:
                self.fila.clear()
                self.fila.update(anterior)
                raise

        self.perfil_modelo = Mock()
        self.perfil_modelo.objects.filter.return_value.first.return_value = None
        contexto = dict(
            PerfilUsuario=self.perfil_modelo, PerfilForm=Formulario, PasswordChangeForm=Mock(),
            transaction=SimpleNamespace(atomic=atomic), serializar_identidad=atomic, messages=Mock(),
            get_user_model=lambda: SimpleNamespace(objects=Mock()),
            get_object_or_404=lambda *args, **kwargs: Usuario(),
            PermissionDenied=RuntimeError,
            redirect=lambda destino: destino, render=lambda *a, **k: k,
        )
        arbol = ast.parse((ROOT / 'app/core/views_perfil.py').read_text())
        vista = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == 'perfil')
        vista.decorator_list = []
        exec(compile(ast.Module(body=[vista], type_ignores=[]), '<perfil-real>', 'exec'), contexto)
        self.vista = contexto['perfil']

    def enviar(self):
        return self.vista(SimpleNamespace(method='POST', POST={'accion': 'datos'}, user=self.usuario))

    def test_password_y_flags_concurrentes_sobreviven_al_guardado(self):
        def cambiar():
            segunda = self.Usuario()
            segunda.password = 'hash-nuevo'
            segunda.is_staff = True
            segunda.is_active = False
            segunda.save(update_fields=['password', 'is_staff', 'is_active'])
        self.cambio = cambiar
        self.assertEqual(self.enviar(), 'perfil')
        self.assertEqual(self.fila['password'], 'hash-nuevo')
        self.assertTrue(self.fila['is_staff'])
        self.assertFalse(self.fila['is_active'])
        self.assertEqual(self.fila['first_name'], 'Editado')

    def test_campos_autorizados_no_editados_conservan_cambios_concurrentes(self):
        def cambiar():
            segunda = self.Usuario()
            segunda.email = 'nuevo@example.invalid'
            segunda.last_name = 'Concurrente'
            segunda.save(update_fields=['email', 'last_name'])
        self.cambio = cambiar
        self.enviar()
        self.assertEqual(self.fila['email'], 'nuevo@example.invalid')
        self.assertEqual(self.fila['last_name'], 'Concurrente')
        self.assertEqual(self.fila['first_name'], 'Editado')

    def test_perfil_extra_no_actualiza_usuario_ni_acepta_atributos_ajenos(self):
        self.campos = ['fecha_nacimiento', 'celular', 'is_staff', 'password']
        self.enviar()
        self.assertEqual(self.escrituras, [])
        self.perfil_modelo.objects.update_or_create.assert_called_once()

    def test_fallo_de_perfil_revierte_guardado_del_nombre(self):
        self.perfil_modelo.objects.update_or_create.side_effect = RuntimeError('fallo simulado')
        with self.assertRaises(RuntimeError):
            self.enviar()
        self.assertEqual(self.fila['first_name'], 'Antes')

    def test_formulario_invalido_no_escribe(self):
        self.valido = False
        self.enviar()
        self.assertEqual(self.escrituras, [])
        self.perfil_modelo.objects.update_or_create.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
