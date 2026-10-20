"""Arnés independiente; requiere revisión de seguridad antes de ejecutarse."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from security import (ENDPOINT, LABEL_KEY, NETWORK_OPTIONS, PATH, PG17_PATH, PGDATA, SOCKET,
                      client_environment, container_valid, image_environment,
                      network_valid, owned, require)

ROOT = Path(__file__).resolve().parents[2]


class LocalDocker:
    def __init__(self, config, environ):
        self.env = client_environment(environ)
        self.config = str(config)
        self.socket_identity = self.socket_stat()
        executable = Path('/usr/bin/docker').stat()
        require(executable.st_uid == 0 and not executable.st_mode & 0o022,
                'Cliente Docker no confiable')

    @staticmethod
    def socket_stat():
        value = os.lstat(SOCKET)
        require(stat.S_ISSOCK(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o002,
                'Se requiere el socket local root-owned autorizado, sin symlinks')
        return value.st_dev, value.st_ino

    def call(self, *args, capture=True, timeout=30):
        require(self.socket_stat() == self.socket_identity, 'Socket Docker reemplazado')
        result = subprocess.run(
            ['/usr/bin/docker', '--config', self.config, '--host', ENDPOINT, *args],
            env=self.env, check=True, text=True, timeout=timeout,
            stdout=subprocess.PIPE if capture else None,
        )
        return result.stdout.strip() if capture else None

    def inspect(self, kind, identifier):
        data = json.loads(self.call(kind, 'inspect', identifier))
        require(len(data) == 1, 'Inspección ambigua')
        return data[0]


def cleanup(client, resources, prefix):
    """También recupera creaciones cuya respuesta se perdió; nunca borra por filtro."""
    errors = []
    for resource in reversed(resources):
        kind, name = resource['kind'], resource['name']
        try:
            # Lista sólo para resolver identidad exacta; ausencia no es un error.
            ids = client.call(kind, 'ls', *(['-a'] if kind == 'container' else []),
                              '--no-trunc', '--filter', f'label={LABEL_KEY}={prefix}',
                              '--format', '{{.ID}}').splitlines()
            matches = []
            for identifier in ids:
                info = client.inspect(kind, identifier)
                actual_name = info.get('Name', '').lstrip('/')
                if actual_name == name:
                    matches.append((identifier, info))
            require(len(matches) <= 1, 'Limpieza ambigua')
            if not matches:
                require(not resource.get('id'), 'Recurso registrado ausente o etiqueta cambiada')
                continue
            identifier, info = matches[0]
            require(not resource.get('id') or resource['id'] == identifier, 'Recurso reemplazado')
            owned(info, kind, identifier, name, prefix)
            if kind == 'network':
                require(not info.get('Containers'), 'Red todavía ocupada; no se elimina')
            client.call(kind, 'rm', *(['-f'] if kind == 'container' else []), identifier)
        except (Exception, KeyboardInterrupt) as error:
            errors.append(f'{kind} {name}: {type(error).__name__}: {error}')
    return errors


def copy_code(stage):
    app = ROOT / 'app'
    require(not app.is_symlink(), 'app no puede ser symlink')
    for source in app.rglob('*'):
        relative = source.relative_to(app)
        if any(part.startswith('.') or part in ('media', 'uploads', '__pycache__')
               for part in relative.parts):
            continue
        if source.is_symlink() or any(p.is_symlink() for p in source.parents):
            continue
        if source.is_file() and source.suffix in ('.py', '.html'):
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
    (stage / 'static').mkdir(exist_ok=True)
    for name in ('runner.py', 'security.py', 'validation.py'):
        shutil.copyfile(Path(__file__).with_name(name), stage / ('fase1_1_' + name))
        (stage / ('fase1_1_' + name)).chmod(0o644)
    for directory in stage.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o755)
    stage.chmod(0o755)


def create_container(client, spec, prefix, network, resources):
    resource = {'kind': 'container', 'name': spec['name']}
    resources.append(resource)  # Antes de create: permite recuperar fallos parciales.
    args = ['create', '--pull=never', '--name', spec['name'], '--label', f'{LABEL_KEY}={prefix}',
            '--network', network, '--read-only', '--user', spec['user'],
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--ipc=private',
            '--cgroupns=private', '--restart=no', '--log-driver=none',
            '--dns=127.0.0.1', '--dns-search=.', '--dns-option=ndots:0', '--workdir',
            '/app' if spec['role'] == 'web' else '/', '--entrypoint', '/usr/bin/env']
    for destination, options in spec['tmpfs'].items():
        args += ['--tmpfs', destination + ':' + options]
    for mount in spec['mounts']:
        require(',' not in mount['Source'], 'Ruta no representable en --mount')
        args += ['--mount', f'type=bind,src={mount["Source"]},dst=/app,readonly,bind-propagation=rprivate']
    identifier = client.call(*args, spec['image'], *spec['command'])
    require(re.fullmatch(r'[a-f0-9]{64}', identifier), 'ID de contenedor inválido')
    resource['id'] = spec['id'] = identifier
    container_valid(client.inspect('container', identifier), spec, prefix, network)
    return identifier


def postgres_environment():
    # Entorno de proceso cerrado; no deriva del PATH del host ni de la imagen.
    return {'PATH': PG17_PATH, 'LANG': 'C.UTF-8', 'HOME': '/nonexistent',
            'PGDATA': PGDATA, 'POSTGRES_DB': 'tw_disposable',
            'POSTGRES_USER': 'tw_disposable', 'POSTGRES_PASSWORD': 'disposable-only',
            'POSTGRES_INITDB_ARGS': '--auth-host=scram-sha-256 --auth-local=trust'}


def main():
    # Validar entorno antes de cualquier operación Docker o copia de código.
    client_environment(os.environ)
    prefix = 'tw-f11-' + uuid.uuid4().hex
    token = uuid.uuid4().hex
    print('Recursos exclusivos:', prefix, flush=True)
    with tempfile.TemporaryDirectory(prefix='.tw-f11-', dir=ROOT) as directory:
        work = Path(directory)
        config, stage = work / 'docker-config', work / 'code'
        config.mkdir()
        stage.mkdir()
        client = LocalDocker(config, os.environ)
        daemon = json.loads(client.call('info', '--format', '{{json .}}'))
        require(daemon.get('OSType') == 'linux' and daemon.get('ID'), 'Daemon no autorizado')
        version = re.match(r'^(\d+)\.(\d+)\.', daemon.get('ServerVersion', ''))
        require(version is not None and int(version.group(1)) >= 28,
                'Se requiere Docker Engine 28+ con bridge isolated')
        images = {}
        for role, tag in [('db', 'postgis/postgis:17-3.5'), ('web', 'trendwatch-litoral-web:latest')]:
            info = client.inspect('image', tag)
            images[role] = (info['Id'], image_environment(info, role))
        copy_code(stage)
        resources = []
        try:
            # Una colisión de nombre aborta sin adoptar recursos preexistentes.
            for kind in ('container', 'network'):
                require(not client.call(kind, 'ls', *(['-a'] if kind == 'container' else []),
                                        '--filter', f'name={prefix}', '--format', '{{.ID}}'),
                        'Colisión de nombres; no se crea ni adopta ningún recurso')
            resource = {'kind': 'network', 'name': prefix}
            resources.append(resource)
            network = client.call('network', 'create', '--driver', 'bridge', '--ipam-driver', 'default', '--internal',
                                  '--label', f'{LABEL_KEY}={prefix}', '--opt',
                                  'com.docker.network.bridge.gateway_mode_ipv4=isolated', prefix)
            require(re.fullmatch(r'[a-f0-9]{64}', network), 'ID de red inválido')
            resource['id'] = network
            network_valid(client.inspect('network', network), network, prefix, [])
            base_env = {'PATH': PATH, 'LANG': 'C.UTF-8', 'HOME': '/nonexistent'}
            db_env = postgres_environment()
            db_spec = {'role': 'db', 'name': prefix + '-db', 'image': images['db'][0],
                       'image_env': images['db'][1], 'user': '999:999', 'mounts': [],
                       'tmpfs': {PGDATA: 'rw,nosuid,nodev,noexec,uid=999,gid=999,mode=0700',
                                 '/var/run/postgresql': 'rw,nosuid,nodev,noexec,uid=999,gid=999,mode=0770',
                                 '/tmp': 'rw,nosuid,nodev,noexec,mode=1777'},
                       'command': ['-i', *[f'{k}={v}' for k, v in db_env.items()],
                                   '/usr/local/bin/docker-entrypoint.sh', 'postgres',
                                   '-c', 'listen_addresses=*', '-c', 'port=5432',
                                   '-c', f'tw.fase1_1={token}']}
            db = create_container(client, db_spec, prefix, network, resources)
            network_valid(client.inspect('network', network), network, prefix, [db])
            client.call('start', db)
            for attempt in range(30):
                try:
                    client.call('exec', db, '/usr/bin/env', '-i', f'PATH={db_env["PATH"]}',
                                'pg_isready', '-h', '127.0.0.1', '-U', 'tw_disposable', '-d', 'tw_disposable')
                    break
                except subprocess.CalledProcessError:
                    time.sleep(1)
            else:
                raise RuntimeError('PostgreSQL no disponible')
            db_info = client.inspect('container', db)
            container_valid(db_info, db_spec, prefix, network)
            ip = db_info['NetworkSettings']['Networks'][prefix]['IPAddress']
            import ipaddress
            require(ipaddress.IPv4Address(ip).is_private, 'IP PostgreSQL no privada')
            web_env = dict(base_env, PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1',
                           SECRET_KEY='disposable-fase1-1-only', DEBUG='False',
                           ALLOWED_HOSTS='testserver,localhost', GEMINI_API_KEY='',
                           DB_HOST=ip, DB_PORT='5432', DB_NAME='tw_disposable',
                           DB_USER='tw_disposable', DB_PASSWORD='disposable-only',
                           TW_TEST_IP=ip, TW_TEST_TOKEN=token)
            web_spec = {'role': 'web', 'name': prefix + '-web', 'image': images['web'][0],
                        'image_env': images['web'][1], 'user': '65534:65534',
                        'tmpfs': {'/tmp': 'rw,nosuid,nodev,noexec,mode=1777'},
                        'mounts': [{'Type': 'bind', 'Source': str(stage), 'Target': '/app',
                                    'ReadOnly': True, 'BindOptions': {'Propagation': 'rprivate'}}],
                        'command': ['-i', *[f'{k}={v}' for k, v in web_env.items()],
                                    '/usr/local/bin/python', '-B', '/app/fase1_1_runner.py']}
            web = create_container(client, web_spec, prefix, network, resources)
            network_valid(client.inspect('network', network), network, prefix, [db, web])
            client.call('start', '--attach', web, capture=False, timeout=600)
            result = client.inspect('container', web)
            container_valid(result, web_spec, prefix, network)
            require(not result['State']['Running'] and result['State']['ExitCode'] == 0,
                    'Pruebas fallidas o contenedor aún activo')
        finally:
            errors = cleanup(client, resources, prefix)
            if errors:
                raise RuntimeError('Limpieza incompleta; revisar recursos propios:\n' + '\n'.join(errors))


if __name__ == '__main__':
    main()
