"""Regresiones de configuración: sin Django instalado, archivos .env ni redes."""
import hashlib
import importlib.util
import os
from pathlib import Path
import runpy
import socket
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / 'app' / 'mi_proyecto'
SPEC = importlib.util.spec_from_file_location('production_policy', PROJECT / 'production_config.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def environment():
    # Datos exclusivamente sintéticos; nunca se leen credenciales del anfitrión.
    return {
        'DJANGO_SETTINGS_MODULE': 'mi_proyecto.settings_production',
        'DEBUG': 'False', 'SECRET_KEY': hashlib.sha512(b'test-only-not-a-deployment-key').hexdigest(),
        'ALLOWED_HOSTS': 'app.test,news.app.test', 'DB_HOST': 'database.test',
        'DB_PORT': '5432', 'DB_NAME': 'test_only', 'DB_USER': 'test_only',
        'DB_PASSWORD': 'test-only', 'DB_SSLMODE': 'verify-full',
        'DB_SSLROOTCERT': '/test-only/ca.pem', 'MEDIA_ROOT': '/test-only/media',
    }


class ProductionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.env = environment()
        self.guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_required_values_fail_closed(self):
        for name in ('DEBUG', 'SECRET_KEY', 'ALLOWED_HOSTS', 'DB_HOST', 'DB_PORT',
                     'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_SSLMODE', 'MEDIA_ROOT'):
            for value in ('', '   ', None):
                env = self.env.copy()
                if value is None:
                    env.pop(name)
                else:
                    env[name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    POLICY.production_config(env)

    def test_only_explicit_false_debug(self):
        for value in ('True', '1', '0', 'no', 'garbage'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                POLICY.production_config(dict(self.env, DEBUG=value))

    def test_weak_secrets_rejected_without_echoing_them(self):
        for secret in ('short', 'a' * 80, 'django-insecure-' + 'abcde' * 20, 'change-me-' + 'abcde' * 20):
            with self.assertRaises(ValueError) as caught:
                POLICY.production_config(dict(self.env, SECRET_KEY=secret))
            self.assertNotIn(secret, str(caught.exception))

    def test_invalid_hosts(self):
        for host in ('*', '.app.test', '*.app.test', 'https://app.test', 'app.test:443',
                     'app.test/path', 'app.test,', 'localhost', 'user@app.test',
                     'bad_host', '-bad.test', '[not-ip]', '::1'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                POLICY.production_config(dict(self.env, ALLOWED_HOSTS=host))

    def test_specific_dns_and_ip_hosts(self):
        for host in ('app.test', '192.0.2.1', '[2001:db8::1]', 'app.test, news.app.test'):
            with self.subTest(host=host):
                self.assertEqual(POLICY.production_config(dict(self.env, ALLOWED_HOSTS=host))['ALLOWED_HOSTS'],
                                 [part.strip() for part in host.split(',')])

    def test_invalid_db_ports(self):
        for value in ('0', '-1', '65536', 'abc', '5432.0', '+5432', '５４３２'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                POLICY.production_config(dict(self.env, DB_PORT=value))

    def test_database_is_always_postgresql(self):
        config = POLICY.production_config(self.env)
        self.assertEqual(config['DATABASES']['default']['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(config['DATABASES']['default']['OPTIONS'],
                         {'sslmode': 'verify-full', 'sslrootcert': '/test-only/ca.pem'})

    def test_ssl_requires_explicit_decision_and_ca(self):
        for mode in ('allow', 'prefer', 'unknown'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                POLICY.production_config(dict(self.env, DB_SSLMODE=mode))
        for mode in ('verify-ca', 'verify-full'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                POLICY.production_config(dict(self.env, DB_SSLMODE=mode, DB_SSLROOTCERT=''))
        self.assertEqual(POLICY.production_config(dict(self.env, DB_SSLMODE='disable'))
                         ['DATABASES']['default']['OPTIONS'], {'sslmode': 'disable'})

    def test_media_path_must_be_absolute(self):
        with self.assertRaises(ValueError):
            POLICY.production_config(dict(self.env, MEDIA_ROOT='media'))

    def test_https_cookies_csrf_and_proxy_defaults(self):
        config = POLICY.production_config(self.env)
        for name in ('SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE',
                     'SESSION_COOKIE_HTTPONLY', 'SECURE_CONTENT_TYPE_NOSNIFF'):
            self.assertIs(config[name], True)
        self.assertIsNone(config['SECURE_PROXY_SSL_HEADER'])
        self.assertFalse(config['USE_X_FORWARDED_HOST'])
        self.assertEqual(config['CSRF_TRUSTED_ORIGINS'], [])
        self.assertEqual(config['SESSION_COOKIE_SAMESITE'], 'Lax')
        self.assertEqual(config['CSRF_COOKIE_SAMESITE'], 'Lax')

    def test_proxy_trust_is_opt_in(self):
        self.assertEqual(POLICY.production_config(dict(self.env, TRUST_PROXY_HTTPS='true'))
                         ['SECURE_PROXY_SSL_HEADER'], ('HTTP_X_FORWARDED_PROTO', 'https'))
        with self.assertRaises(ValueError):
            POLICY.production_config(dict(self.env, TRUST_PROXY_HTTPS='maybe'))

    def test_hsts_is_explicit_bounded_and_without_subdomains(self):
        config = POLICY.production_config(self.env)
        self.assertEqual(config['SECURE_HSTS_SECONDS'], 0)
        self.assertFalse(config['SECURE_HSTS_INCLUDE_SUBDOMAINS'])
        self.assertFalse(config['SECURE_HSTS_PRELOAD'])
        self.assertEqual(POLICY.production_config(dict(self.env, SECURE_HSTS_SECONDS='300'))
                         ['SECURE_HSTS_SECONDS'], 300)
        for value in ('-1', '31536001', 'true', '1.5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                POLICY.production_config(dict(self.env, SECURE_HSTS_SECONDS=value))

    def load_settings(self, production, env):
        dotenv = types.ModuleType('dotenv')
        dotenv.load_dotenv = Mock(side_effect=AssertionError('Production read .env') if production else None)
        django = types.ModuleType('django')
        core = types.ModuleType('django.core')
        exceptions = types.ModuleType('django.core.exceptions')
        exceptions.ImproperlyConfigured = type('ImproperlyConfigured', (Exception,), {})
        package = types.ModuleType('mi_proyecto')
        package.__path__ = [str(PROJECT)]
        modules = {'dotenv': dotenv, 'django': django, 'django.core': core,
                   'django.core.exceptions': exceptions, 'mi_proyecto': package}
        with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, modules):
            # No se importa ningún componente Django real ni se abre una conexión.
            if production:
                spec = importlib.util.spec_from_file_location('mi_proyecto.settings_production',
                                                             PROJECT / 'settings_production.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                config = vars(module)
            else:
                config = runpy.run_path(str(PROJECT / 'settings.py'))
        return config, dotenv.load_dotenv

    def test_production_module_imports_base_without_dotenv(self):
        config, loader = self.load_settings(True, self.env)
        loader.assert_not_called()
        self.assertFalse(config['DEBUG'])
        self.assertTrue(config['SESSION_COOKIE_SECURE'])
        self.assertEqual(config['DATABASES']['default']['HOST'], 'database.test')
        self.assertEqual(config['SIMPLE_JWT']['ROTATE_REFRESH_TOKENS'], True)
        self.assertIn('django.middleware.csrf.CsrfViewMiddleware', config['MIDDLEWARE'])

    def test_invalid_production_module_fails_before_loading_base(self):
        with self.assertRaisesRegex(Exception, 'Producción exige DEBUG=False'):
            self.load_settings(True, dict(self.env, DEBUG='True'))

    def test_development_sqlite_dotenv_and_debug_unchanged(self):
        env = {'SECRET_KEY': self.env['SECRET_KEY'], 'DEBUG': 'True'}
        config, loader = self.load_settings(False, env)
        loader.assert_called_once_with()
        self.assertTrue(config['DEBUG'])
        self.assertEqual(config['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(config['ALLOWED_HOSTS'], ['localhost', '127.0.0.1'])
        self.assertNotIn('SECURE_SSL_REDIRECT', config)

    def test_development_postgres_preserved(self):
        env = dict(self.env, DJANGO_SETTINGS_MODULE='mi_proyecto.settings', DEBUG='True')
        config, loader = self.load_settings(False, env)
        loader.assert_called_once_with()
        self.assertTrue(config['DEBUG'])
        self.assertEqual(config['DATABASES']['default']['PORT'], '5432')

    def test_production_container_is_separate_and_unprivileged(self):
        docker = (ROOT / 'Dockerfile.production').read_text()
        compose = (ROOT / 'compose.production.yml').read_text()
        self.assertIn('USER 10001:10001', docker)
        self.assertIn('"gunicorn"', docker)
        self.assertIn('collectstatic', docker)
        self.assertIn('read_only: true', compose)
        self.assertIn('127.0.0.1:8001:8000', compose)
        self.assertIn('create_host_path: false', compose)
        self.assertNotIn('./app:/app', compose)
        self.assertNotIn('runserver', compose)
        self.assertNotIn('env_file:', compose)
        self.assertNotIn('gunicorn', (ROOT / 'requirements.txt').read_text())
        self.assertIn('runserver', (ROOT / 'docker-compose.yml').read_text())


if __name__ == '__main__':
    unittest.main()
