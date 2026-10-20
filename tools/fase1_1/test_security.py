"""Pruebas sin daemon, servicios, Django ni dependencias de terceros."""
import io
import os
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import check_ports
import run
import security as s

PREFIX = 'tw-f11-' + 'a' * 32
NET = 'b' * 64
CID = 'c' * 64
IMAGE = 'sha256:' + 'd' * 64
IP = '172.29.0.2'
TOKEN = 'e' * 32


def image(role='web'):
    return {'Id': IMAGE, 'Os': 'linux', 'Config': {
        'User': '', 'WorkingDir': '/app' if role == 'web' else '',
        'Entrypoint': None if role == 'web' else ['docker-entrypoint.sh'],
        'Cmd': ['python3'] if role == 'web' else ['postgres'],
        'Volumes': None if role == 'web' else {s.PGDATA: {}},
        'ExposedPorts': None if role == 'web' else {'5432/tcp': {}},
        'Env': ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                + (':/usr/lib/postgresql/17/bin' if role == 'db' else ''), 'LANG=C.UTF-8'],
    }}


def network():
    return {'Id': NET, 'Name': PREFIX, 'Labels': {s.LABEL_KEY: PREFIX},
            'Driver': 'bridge', 'Scope': 'local', 'Internal': True,
            'IPAM': {'Driver': 'default', 'Options': None},
            'EnableIPv6': False, 'Options': dict(s.NETWORK_OPTIONS), 'Containers': {}}


def container():
    spec = {'id': CID, 'name': PREFIX + '-web', 'role': 'web', 'image': IMAGE,
            'user': '65534:65534', 'image_env': {'PATH': s.PATH},
            'command': ['-i', '/usr/local/bin/python'],
            'tmpfs': {'/tmp': 'rw,nosuid'}, 'mounts': []}
    info = {'Id': CID, 'Name': '/' + spec['name'], 'Image': IMAGE,
            'State': {'Status': 'running'},
            'Config': {'Labels': {s.LABEL_KEY: PREFIX}, 'User': spec['user'],
                       'Env': [f'PATH={s.PATH}'], 'WorkingDir': '/app',
                       'Entrypoint': ['/usr/bin/env'], 'Cmd': spec['command']},
            'HostConfig': {'ReadonlyRootfs': True, 'CapDrop': ['ALL'],
                           'SecurityOpt': ['no-new-privileges'], 'NetworkMode': NET,
                           'RestartPolicy': {'Name': 'no'}, 'IpcMode': 'private', 'Runtime': 'runc',
                           'Dns': ['127.0.0.1'], 'DnsSearch': ['.'], 'DnsOptions': ['ndots:0'],
                           'Tmpfs': spec['tmpfs'], 'LogConfig': {'Type': 'none', 'Config': {}}},
            'Mounts': [], 'NetworkSettings': {
                'Networks': {PREFIX: {'NetworkID': NET}}, 'Ports': {}}}
    return info, spec


class SecurityTests(unittest.TestCase):
    def test_environment_rejects_inherited_docker_and_remote(self):
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY',
                    'CONTAINER_HOST', 'SSH_AUTH_SOCK'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.client_environment({key: 'anything'})
        self.assertEqual(s.client_environment({'HOME': '/private', 'HTTPS_PROXY': 'remote'}),
                         {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})

    def test_all_client_calls_pin_socket_config_and_environment(self):
        client = run.LocalDocker.__new__(run.LocalDocker)
        client.env = s.client_environment({})
        client.config = '/owned/empty-config'
        client.socket_identity = (1, 2)
        with patch.object(client, 'socket_stat', return_value=(1, 2)), patch(
            'run.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'ok\n')
        ) as invoke:
            self.assertEqual(client.call('info'), 'ok')
            args, kwargs = invoke.call_args
            self.assertEqual(args[0], ['/usr/bin/docker', '--config', '/owned/empty-config',
                                       '--host', 'unix:///var/run/docker.sock', 'info'])
            self.assertEqual(kwargs['env'], client.env)
            self.assertNotIn('shell', kwargs)
        with patch.object(client, 'socket_stat', return_value=(1, 3)), patch('run.subprocess.run') as invoke:
            with self.assertRaises(RuntimeError):
                client.call('info')
            invoke.assert_not_called()

    def test_runner_rejects_all_extra_environment_including_libpq(self):
        env = {'PATH': s.PATH, 'LANG': 'C.UTF-8', 'HOME': '/nonexistent',
               'DB_HOST': IP, 'DB_PORT': '5432', 'DB_NAME': 'tw_disposable',
               'DB_USER': 'tw_disposable', 'DB_PASSWORD': 'disposable-only',
               'PYTHON_DOTENV_DISABLED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'SECRET_KEY': 'disposable-fase1-1-only', 'DEBUG': 'False',
               'ALLOWED_HOSTS': 'testserver,localhost', 'GEMINI_API_KEY': '',
               'TW_TEST_IP': IP, 'TW_TEST_TOKEN': TOKEN}
        self.assertEqual(s.runner_environment(env), (IP, TOKEN))
        for key in ('PGHOSTADDR', 'PGSERVICE', 'PGOPTIONS', 'PGPASSFILE', 'PYTHONPATH', 'HTTP_PROXY'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.runner_environment(dict(env, **{key: 'unexpected'}))
        with self.assertRaises(RuntimeError):
            s.runner_environment(dict(env, DB_HOST='external'))

    def test_main_rejects_image_before_copy_or_resource_creation(self):
        calls = []
        class Fake:
            def __init__(self, *args):
                pass

            def call(self, *args):
                calls.append(args)
                return json.dumps({'OSType': 'linux', 'ID': 'local', 'ServerVersion': '28.0.0'})

            def inspect(self, kind, tag):
                info = image('db')
                info['Config']['Env'].append('PGHOSTADDR=external')
                return info
        with patch.dict(os.environ, {}, clear=True), patch('run.LocalDocker', Fake), patch(
            'run.copy_code'
        ) as copy, patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(RuntimeError):
                run.main()
            copy.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'info')

    def test_image_accepts_expected_metadata(self):
        for role in ('web', 'db'):
            s.image_environment(image(role), role)

    def test_postgres_path_variants_and_absolute_metadata_commands(self):
        base = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        # Expectativas literales: no reutilizar PG17_PATH para fabricar el fixture.
        for path in (base, base + ':/usr/lib/postgresql/17/bin'):
            for command in (['postgres'], ['/usr/lib/postgresql/17/bin/postgres']):
                for entrypoint in (['docker-entrypoint.sh'], ['/usr/local/bin/docker-entrypoint.sh']):
                    info = image('db')
                    info['Config'].update(Env=['PATH=' + path, 'LANG=C.UTF-8'],
                                          Cmd=command, Entrypoint=entrypoint)
                    with self.subTest(path=path, command=command, entrypoint=entrypoint):
                        self.assertEqual(s.image_environment(info, 'db')['PATH'], path)

    def test_postgres_rejects_unauthorized_search_paths_and_absolute_commands(self):
        base = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        for path in (base + ':/tmp', '/tmp:' + base, base + ':', ':' + base,
                     base + ':.', base + ':/usr/lib/postgresql/16/bin',
                     base + ':/usr/lib/postgresql/17/bin:/opt/bin',
                     base + ':/usr/lib/postgresql/17/bin/../18/bin',
                     '$PATH:/usr/lib/postgresql/17/bin', '', 'relative/bin'):
            info = image('db')
            info['Config']['Env'][0] = 'PATH=' + path
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                s.image_environment(info, 'db')
        for key, value in (('Cmd', ['/opt/bin/postgres']),
                           ('Cmd', ['/usr/lib/postgresql/16/bin/postgres']),
                           ('Entrypoint', ['/tmp/docker-entrypoint.sh'])):
            info = image('db')
            info['Config'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                s.image_environment(info, 'db')

    def test_postgres_runtime_path_is_fixed_and_does_not_change_web_policy(self):
        expected = ('/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                    ':/usr/lib/postgresql/17/bin')
        with patch.dict(os.environ, {'PATH': '/untrusted', 'PGHOST': 'external'}):
            env = run.postgres_environment()
        self.assertEqual(env['PATH'], expected)
        self.assertEqual(set(env), {'PATH', 'LANG', 'HOME', 'PGDATA', 'POSTGRES_DB',
                                   'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_INITDB_ARGS'})
        info = image('web')
        info['Config']['Env'][0] = 'PATH=' + expected
        with self.assertRaises(RuntimeError):
            s.image_environment(info, 'web')

    def test_image_rejects_env_hooks_users_volumes_and_ports(self):
        mutations = {'Env': ['PGHOSTADDR=192.0.2.1'], 'User': 'someone',
                     'Entrypoint': ['evil'], 'Cmd': ['evil'], 'WorkingDir': '/elsewhere',
                     'Volumes': {'/other': {}}, 'Healthcheck': {'Test': ['CMD', 'evil']},
                     'OnBuild': ['RUN evil'], 'ExposedPorts': {'9999/tcp': {}}}
        for key, value in mutations.items():
            info = image()
            info['Config'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.image_environment(info, 'web')

    def test_network_rejects_nonisolated_options_and_foreign_members(self):
        s.network_valid(network(), NET, PREFIX, [])
        for key, value in {'Internal': False, 'Driver': 'host', 'Scope': 'swarm',
                           'EnableIPv6': True, 'Attachable': True,
                           'Options': {}, 'Containers': {'foreign': {}}}.items():
            info = network()
            info[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.network_valid(info, NET, PREFIX, [])

    def test_container_accepts_expected_configuration(self):
        info, spec = container()
        s.container_valid(info, spec, PREFIX, NET)

    def test_container_rejects_unsafe_host_configuration(self):
        mutations = {'Privileged': True, 'ReadonlyRootfs': False, 'CapAdd': ['SYS_ADMIN'],
                     'CapDrop': [], 'SecurityOpt': [], 'NetworkMode': 'host',
                     'PortBindings': {'5432/tcp': [{'HostPort': '5432'}]},
                     'PublishAllPorts': True, 'Binds': ['/real:/app'],
                     'VolumesFrom': ['real'], 'Devices': ['device'],
                     'ExtraHosts': ['db:192.0.2.1'], 'Dns': ['192.0.2.1'],
                     'PidMode': 'host', 'IpcMode': 'host', 'UsernsMode': 'host',
                     'Runtime': 'other', 'Tmpfs': {}, 'Mounts': [{'Type': 'volume'}],
                     'RestartPolicy': {'Name': 'always'},
                     'LogConfig': {'Type': 'syslog', 'Config': {}}}
        for key, value in mutations.items():
            info, spec = container()
            info['HostConfig'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.container_valid(info, spec, PREFIX, NET)

    def test_container_rejects_effective_mounts_env_identity_networks(self):
        for mutation in ('mount', 'env', 'user', 'entrypoint', 'image', 'network', 'label'):
            info, spec = container()
            if mutation == 'mount':
                info['Mounts'] = [{'Type': 'volume', 'Destination': '/other'}]
            elif mutation == 'env':
                info['Config']['Env'].append('PGSERVICE=real')
            elif mutation == 'user':
                info['Config']['User'] = '0'
            elif mutation == 'entrypoint':
                info['Config']['Entrypoint'] = ['sh']
            elif mutation == 'image':
                info['Image'] = 'other'
            elif mutation == 'network':
                info['NetworkSettings']['Networks']['foreign'] = {}
            else:
                info['Config']['Labels'] = {}
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                s.container_valid(info, spec, PREFIX, NET)

    def test_bind_must_be_owned_readonly_and_private(self):
        for key, value in ((None, None), ('RW', True), ('Source', '/real'),
                           ('Propagation', 'rshared')):
            info, spec = container()
            spec['mounts'] = [{'Type': 'bind', 'Source': '/owned/code', 'Target': '/app',
                               'ReadOnly': True, 'BindOptions': {'Propagation': 'rprivate'}}]
            info['HostConfig']['Mounts'] = spec['mounts']
            info['Mounts'] = [{'Type': 'bind', 'Source': '/owned/code', 'Destination': '/app',
                               'RW': False, 'Propagation': 'rprivate'}]
            if key is None:
                s.container_valid(info, spec, PREFIX, NET)
            else:
                info['Mounts'][0][key] = value
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    s.container_valid(info, spec, PREFIX, NET)

    def test_no_writes_enabled_before_matching_identity(self):
        for valid in (True, False):
            queries = []
            class Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def execute(self, sql):
                    queries.append(sql)

                def fetchone(self):
                    return ('tw_disposable', 'tw_disposable', IP, 5432,
                            TOKEN if valid else 'foreign', s.PGDATA)

            class Connection:
                def cursor(self):
                    return Cursor()

            if valid:
                s.authorize_writes(Connection(), IP, TOKEN)
                self.assertEqual(queries, [s.IDENTITY_SQL, 'SET default_transaction_read_only = off'])
            else:
                with self.assertRaises(RuntimeError):
                    s.authorize_writes(Connection(), IP, TOKEN)
                self.assertEqual(queries, [s.IDENTITY_SQL])

    def test_database_rejects_sqlite_external_alias_and_additional_options(self):
        db = {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'tw_disposable',
              'USER': 'tw_disposable', 'PASSWORD': 'disposable-only', 'HOST': IP, 'PORT': '5432'}
        s.database_config({'default': db}, IP)
        for key, value in {'ENGINE': 'django.db.backends.sqlite3', 'HOST': 'external',
                           'OPTIONS': {'service': 'real'}, 'TEST': {'NAME': 'real'}}.items():
            bad = dict(db, **{key: value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.database_config({'default': bad}, IP)
        with self.assertRaises(RuntimeError):
            s.database_config({'default': db, 'real': db}, IP)

    def test_libpq_rejects_extra_or_changed_parameters(self):
        params = {'dbname': 'tw_disposable', 'host': IP, 'hostaddr': IP, 'port': '5432',
                  'user': 'tw_disposable', 'password': 'disposable-only',
                  'passfile': '/dev/null', 'sslmode': 'disable', 'connect_timeout': 5,
                  'client_encoding': 'UTF8', 'options': '-c default_transaction_read_only=on'}
        s.connection_params(params, IP)
        for key, value in {'service': 'real', 'hostaddr': '192.0.2.1', 'dbname': 'postgres',
                           'passfile': '/real', 'options': '', 'client_encoding': 'other'}.items():
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                s.connection_params(dict(params, **{key: value}), IP)

    def test_identity_sql_projects_host_address_in_third_column(self):
        # Contrato SQL: mismo orden de seis campos y dirección host sin máscara.
        # PostgreSQL documenta inet::text como dirección + /32, no como host().
        expected = ("SELECT current_database(), current_user, host(inet_server_addr()), "
                    "inet_server_port(), current_setting('tw.fase1_1', true), "
                    "current_setting('data_directory')")
        self.assertEqual(' '.join(s.IDENTITY_SQL.split()), expected)

    def test_identity_regression_masked_address_does_not_equal_docker_ip(self):
        # Ejemplo de representación PostgreSQL 17; no requiere conectar al motor.
        row = ['tw_disposable', 'tw_disposable', '172.29.0.2/32', 5432, TOKEN, s.PGDATA]
        with self.assertRaisesRegex(RuntimeError, 'Identidad PostgreSQL no autorizada'):
            s.database_identity(row, '172.29.0.2', TOKEN)
        row[2] = '172.29.0.2'  # Salida documentada de host(inet_server_addr()).
        s.database_identity(row, '172.29.0.2', TOKEN)
        row[2] = '172.29.0.3'
        with self.assertRaises(RuntimeError):
            s.database_identity(row, '172.29.0.2', TOKEN)

    def test_identity_keeps_strict_types_and_paths(self):
        row = ['tw_disposable', 'tw_disposable', IP, 5432, TOKEN, s.PGDATA]
        for index, value in ((0, b'tw_disposable'), (2, IP.encode()),
                             (3, '5432'), (5, s.PGDATA + '/')):
            bad = row.copy()
            bad[index] = value
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                s.database_identity(bad, IP, TOKEN)

    def test_identity_requires_all_fields_including_run_token(self):
        row = ['tw_disposable', 'tw_disposable', IP, 5432, TOKEN, s.PGDATA]
        s.database_identity(row, IP, TOKEN)
        s.database_identity(['test_tw_disposable', *row[1:]], IP, TOKEN)
        for index in range(len(row)):
            bad = row.copy()
            bad[index] = 'foreign'
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                s.database_identity(bad, IP, TOKEN)

    def test_cleanup_attempts_remaining_resources_after_error(self):
        calls = []
        class Fake:
            def call(self, kind, action, *args):
                calls.append((kind, action, args))
                if action == 'ls':
                    return NET if kind == 'network' else CID
                if kind == 'container':
                    raise RuntimeError('simulated rm failure')
                return ''

            def inspect(self, kind, identifier):
                if kind == 'network':
                    return network()
                return container()[0]
        errors = run.cleanup(Fake(), [
            {'kind': 'network', 'name': PREFIX, 'id': NET},
            {'kind': 'container', 'name': PREFIX + '-web', 'id': CID},
        ], PREFIX)
        self.assertEqual(len(errors), 1)
        self.assertIn(('network', 'rm', (NET,)), calls)

    def test_cleanup_refuses_changed_id_label_or_occupied_network(self):
        for mutation in ('id', 'label', 'occupied', 'other_run'):
            removed = []
            class Fake:
                def call(self, kind, action, *args):
                    if action == 'ls':
                        return NET
                    removed.append(args)

                def inspect(self, kind, identifier):
                    info = network()
                    if mutation == 'id':
                        info['Id'] = 'foreign'
                    elif mutation == 'label':
                        info['Labels'] = {}
                    elif mutation == 'occupied':
                        info['Containers'] = {'foreign': {}}
                    else:
                        info['Labels'] = {s.LABEL_KEY: 'tw-f11-' + 'f' * 32}
                    return info
            with self.subTest(mutation=mutation):
                self.assertTrue(run.cleanup(Fake(), [{'kind': 'network', 'name': PREFIX, 'id': NET}], PREFIX))
                self.assertEqual(removed, [])

    def test_cleanup_recovers_unregistered_creation_only_with_own_identity(self):
        removed = []
        class Fake:
            def call(self, kind, action, *args):
                if action == 'ls':
                    return NET
                removed.append(args)

            def inspect(self, kind, identifier):
                return network()
        self.assertEqual(run.cleanup(Fake(), [{'kind': 'network', 'name': PREFIX}], PREFIX), [])
        self.assertEqual(removed, [(NET,)])

    def test_no_assert_or_general_destructive_commands_in_harness(self):
        import ast
        for name in ('run.py', 'runner.py', 'security.py', 'check_ports.py'):
            text = Path(__file__).with_name(name).read_text()
            self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(text))))
            for forbidden in ('system prune', 'compose down', 'shell=True'):
                self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
