"""Controles puros y conservadores: no ejecutan Docker ni importan Django."""
import ipaddress
import re

SOCKET = '/var/run/docker.sock'
ENDPOINT = 'unix://' + SOCKET
LABEL_KEY = 'trendwatch.fase1_1'
PGDATA = '/var/lib/postgresql/data'
PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
PG17_PATH = PATH + ':/usr/lib/postgresql/17/bin'
NETWORK_OPTIONS = {'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def client_environment(environ):
    require(not any(k.startswith(('DOCKER_', 'CONTAINER_', 'SSH_')) for k in environ),
            'Eliminar variables DOCKER_*, CONTAINER_* y SSH_* antes de ejecutar')
    # No heredar HOME, proxies, plugins ni configuración personal del cliente.
    return {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}


def env_map(items):
    result = {}
    for item in items or []:
        key, sep, value = item.partition('=')
        require(sep and key and key not in result, 'Entorno inválido o duplicado')
        result[key] = value
    return result


def image_environment(info, role):
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', info.get('Id', '')), 'ID de imagen inválido')
    require(info.get('Os') == 'linux', 'Imagen no Linux')
    config = info['Config']
    require(not config.get('OnBuild') and not config.get('Healthcheck'),
            'Imagen con hooks no autorizados')
    require(config.get('User', '') in ('', '0', 'root'), 'Usuario de imagen inesperado')
    require(config.get('WorkingDir', '') == ('/app' if role == 'web' else ''),
            'WorkingDir de imagen inesperado')
    entrypoints = (None, []) if role == 'web' else (
        ['docker-entrypoint.sh'], ['/usr/local/bin/docker-entrypoint.sh'],
    )
    commands = (['python3'],) if role == 'web' else (
        ['postgres'], ['/usr/lib/postgresql/17/bin/postgres'],
    )
    require(config.get('Entrypoint') in entrypoints, 'Entrypoint de imagen inesperado')
    require(config.get('Cmd') in commands, 'Cmd de imagen inesperado')
    require(set(config.get('Volumes') or {}) == (set() if role == 'web' else {PGDATA}),
            'Volúmenes declarados inesperados')
    require(set(config.get('ExposedPorts') or {}) ==
            (set() if role == 'web' else {'5432/tcp'}), 'Puertos declarados inesperados')
    env = env_map(config.get('Env'))
    # Dos valores exactos por rol; ninguna ruta del anfitrión ni comodines.
    paths = (PATH, '/usr/local/bin:' + PATH) if role == 'web' else (PATH, PG17_PATH)
    patterns = {
        'PATH': '(?:' + '|'.join(re.escape(value) for value in paths) + ')',
        'LANG': r'(?:C|en_US)\.(?:UTF-8|utf8)',
    }
    patterns.update({
        'GPG_KEY': r'[A-F0-9]{40}', 'PYTHON_VERSION': r'3\.13\.\d+',
        'PYTHON_SHA256': r'[a-f0-9]{64}', 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONUNBUFFERED': '1',
    } if role == 'web' else {
        'GOSU_VERSION': r'\d+\.\d+', 'PG_MAJOR': '17',
        'PG_VERSION': r'17[.0-9a-zA-Z+~:-]*', 'PG_SHA256': r'[a-f0-9]{64}',
        'PGDATA': re.escape(PGDATA), 'POSTGIS_MAJOR': '3',
        'POSTGIS_VERSION': r'3\.5[.0-9a-zA-Z+~:-]*',
    })
    require(set(env) <= set(patterns), 'Variables de imagen no autorizadas')
    for key, value in env.items():
        require(re.fullmatch(patterns[key], value) is not None,
                f'Valor de imagen no autorizado: {key}')
    return env


def owned(info, kind, identifier, name, prefix):
    require(info.get('Id') == identifier, 'ID ajeno o cambiado')
    require(info.get('Name') == ('/' + name if kind == 'container' else name),
            'Nombre ajeno o cambiado')
    labels = info['Config'].get('Labels') if kind == 'container' else info.get('Labels')
    require((labels or {}).get(LABEL_KEY) == prefix, 'Etiqueta ajena o cambiada')


def network_valid(info, identifier, prefix, members):
    owned(info, 'network', identifier, prefix, prefix)
    require(info.get('Driver') == 'bridge' and info.get('Scope') == 'local'
            and info.get('Internal') is True and not info.get('EnableIPv6')
            and not info.get('Attachable') and not info.get('Ingress'), 'Red no aislada')
    require(info.get('Options') == NETWORK_OPTIONS, 'Opciones de red inesperadas')
    require(info.get('IPAM', {}).get('Driver') == 'default' and
            not info.get('IPAM', {}).get('Options'), 'IPAM externo o inesperado')
    require(set(info.get('Containers') or {}) <= set(members), 'Miembros de red ajenos')


def container_valid(info, spec, prefix, network_id):
    owned(info, 'container', spec['id'], spec['name'], prefix)
    config, host = info['Config'], info['HostConfig']
    require(info.get('Image') == spec['image'], 'Imagen efectiva inesperada')
    for key, value in {'User': spec['user'], 'Entrypoint': ['/usr/bin/env'],
                       'Cmd': spec['command'], 'WorkingDir': '/app' if spec['role'] == 'web' else '/',
                       'Volumes': None}.items():
        actual = config.get(key)
        if key == 'Volumes':
            # La declaración PGDATA de la imagen debe estar cubierta por tmpfs.
            require(set(actual or {}) == (set() if spec['role'] == 'web' else {PGDATA}),
                    'Declaración de volumen inesperada')
        else:
            require(actual == value, f'Configuración efectiva inesperada: {key}')
    require(env_map(config.get('Env')) == spec['image_env'], 'Entorno efectivo alterado')
    require(not config.get('Healthcheck') and not config.get('OnBuild'), 'Hooks efectivos inesperados')
    require(host.get('ReadonlyRootfs') is True and not host.get('Privileged'), 'Raíz o privilegios inseguros')
    require(host.get('CapDrop') == ['ALL'] and not host.get('CapAdd'), 'Capabilities inesperadas')
    require(host.get('SecurityOpt') == ['no-new-privileges'], 'Opciones de seguridad inesperadas')
    require(host.get('NetworkMode') == network_id, 'NetworkMode ajeno')
    require(not host.get('PublishAllPorts') and not host.get('PortBindings'), 'Puertos publicados')
    require((host.get('RestartPolicy') or {}).get('Name') == 'no', 'Reinicio automático inesperado')
    for key in ('Binds', 'VolumesFrom', 'Devices', 'DeviceRequests', 'DeviceCgroupRules',
                'Links', 'ExtraHosts', 'Sysctls',
                'StorageOpt', 'GroupAdd', 'LxcConf'):
        require(not host.get(key), f'HostConfig no autorizado: {key}')
    require(host.get('Dns') == ['127.0.0.1'] and host.get('DnsSearch') == ['.']
            and host.get('DnsOptions') == ['ndots:0'], 'DNS no local o inesperado')
    for key in ('PidMode', 'UTSMode', 'UsernsMode', 'CgroupnsMode'):
        require(host.get(key, '') in ('', 'private'), f'Namespace no privado: {key}')
    require(host.get('IpcMode') == 'private', 'IPC no privado')
    require(host.get('Runtime') in ('runc', ''), 'Runtime inesperado')
    require(host.get('LogConfig') == {'Type': 'none', 'Config': {}}, 'Logging externo o inesperado')
    require(host.get('Tmpfs') == spec['tmpfs'], 'Tmpfs inesperado')
    expected_mounts = spec['mounts']
    require((host.get('Mounts') or []) == expected_mounts, 'Montajes declarados inesperados')
    binds = []
    for mount in info.get('Mounts') or []:
        if mount.get('Type') == 'tmpfs':
            require(mount.get('Destination') in spec['tmpfs'], 'Tmpfs efectivo inesperado')
        else:
            binds.append(mount)
    require(len(binds) == len(expected_mounts), 'Volumen persistente o bind inesperado')
    for mount, expected in zip(binds, expected_mounts):
        require(mount.get('Type') == 'bind' and mount.get('Source') == expected['Source']
                and mount.get('Destination') == '/app' and mount.get('RW') is False
                and mount.get('Propagation') == 'rprivate', 'Bind efectivo inseguro')
    networks = info['NetworkSettings'].get('Networks') or {}
    if info.get('State', {}).get('Status') == 'created':
        require(set(networks) in ({prefix}, {network_id}), 'Red declarada inesperada')
        require(next(iter(networks.values())).get('NetworkID') in ('', network_id),
                'ID de red declarada inesperado')
    else:
        require(set(networks) == {prefix} and networks[prefix].get('NetworkID') == network_id,
                'Conexiones de red inesperadas')
    require(not info['NetworkSettings'].get('Ports') or
            all(value is None for value in info['NetworkSettings']['Ports'].values()),
            'Publicación efectiva de puertos')


def database_config(databases, ip):
    ipaddress.IPv4Address(ip)
    require(set(databases) == {'default'}, 'Alias de base inesperado')
    expected = {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'tw_disposable',
                'USER': 'tw_disposable', 'PASSWORD': 'disposable-only', 'HOST': ip, 'PORT': '5432'}
    require(databases['default'] == expected, 'Configuración PostgreSQL adicional o inesperada')


def database_identity(row, ip, token):
    require(tuple(row) in {
        (name, 'tw_disposable', ip, 5432, token, PGDATA)
        for name in ('tw_disposable', 'test_tw_disposable')
    }, 'Identidad PostgreSQL no autorizada')


def connection_params(params, ip):
    allowed = {'dbname', 'user', 'password', 'host', 'hostaddr', 'port',
               'passfile', 'sslmode', 'connect_timeout', 'client_encoding', 'cursor_factory', 'options'}
    require(set(params) <= allowed, 'Parámetros libpq adicionales')
    required = {'host': ip, 'hostaddr': ip, 'port': '5432', 'user': 'tw_disposable',
                'password': 'disposable-only', 'passfile': '/dev/null',
                'sslmode': 'disable', 'connect_timeout': 5,
                'options': '-c default_transaction_read_only=on'}
    require(all(params.get(k) == v for k, v in required.items()), 'Parámetros libpq alterados')
    require(params.get('dbname') in ('tw_disposable', 'test_tw_disposable'), 'Base no autorizada')
    require(params.get('client_encoding') == 'UTF8', 'Encoding no autorizado')


def runner_environment(environ):
    ip, token = environ.get('TW_TEST_IP', ''), environ.get('TW_TEST_TOKEN', '')
    address = ipaddress.IPv4Address(ip)
    require(address.is_private and not (address.is_loopback or address.is_link_local
            or address.is_unspecified or address.is_multicast or address.is_reserved),
            'IP de prueba no autorizada')
    require(re.fullmatch(r'[0-9a-f]{32}', token) is not None, 'Token de ejecución inválido')
    expected = {
        'PATH': PATH, 'LANG': 'C.UTF-8', 'HOME': '/nonexistent',
        'DB_HOST': ip, 'DB_PORT': '5432', 'DB_NAME': 'tw_disposable',
        'DB_USER': 'tw_disposable', 'DB_PASSWORD': 'disposable-only',
        'PYTHON_DOTENV_DISABLED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'SECRET_KEY': 'disposable-fase1-1-only', 'DEBUG': 'False',
        'ALLOWED_HOSTS': 'testserver,localhost', 'GEMINI_API_KEY': '',
        'TW_TEST_IP': ip, 'TW_TEST_TOKEN': token,
    }
    require(dict(environ) == expected, 'Entorno de runner adicional o alterado')
    return ip, token


# inet::text incluye /32 en IPv4; Docker entrega la dirección sin máscara.
# host() alinea la representación SQL sin relajar la identidad esperada.
IDENTITY_SQL = """SELECT current_database(), current_user, host(inet_server_addr()),
    inet_server_port(), current_setting('tw.fase1_1', true),
    current_setting('data_directory')"""


def authorize_writes(raw_connection, ip, token):
    # Primera consulta de aplicación: SELECT, mientras libpq exige sólo lectura.
    with raw_connection.cursor() as cursor:
        cursor.execute(IDENTITY_SQL)
        database_identity(cursor.fetchone(), ip, token)
        cursor.execute('SET default_transaction_read_only = off')
